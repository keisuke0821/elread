#!/usr/bin/env python3
'''Module to read elevation encoder data
'''
from datetime import datetime, timezone
from collections import deque
from enum import Enum
from pathlib import Path

import lzma
import warnings
import numpy as np

from .common import get_next_path, get_previous_path


PACKET_LENGTH = 12
BUFFER_LENGTH = 128
SEEK_LENGTH = 1000

class DataType(Enum):
    '''Elevation data type
    '''
    DATA = 1
    SYNC = 2
    UART = 3


def header_info(d_bytes):
    '''Parse header of encoder data file
    Parameters
    ----------
    d_bytes: bytes
        Header bytes

    Returns
    -------
    numbytes: int
        Header length
    version: int
        File format version
    time: float
        Unix timestamp of start
    headertxt: str
        Text information
    '''
    numbytes = d_bytes[0:4].decode('utf-8')
    version = int.from_bytes(d_bytes[4:8], 'little', signed=False)
    time = float(int.from_bytes(d_bytes[8:12], 'little', signed=False)) + \
        float(int.from_bytes(d_bytes[12:16], 'little', signed=False))*1e-6
    headertxt = d_bytes[16:].decode('utf-8')

    return numbytes, version, time, headertxt


def parsebytes(d_bytes):
    '''Parse encoder data bytes
    Parameters
    ----------
    d_bytes: bytes
        Data bytes

    Returns
    -------
    timestamp: int
        Timestamp
    data: int
        Data
    d_type: DataType
        Data type
    '''
    if d_bytes[0:2] != b'\x07\x12':
        raise Exception('HEADER ERROR: {}'.format(d_bytes[0:2]))
    if d_bytes[10:12] == b'z\xda':  # DATA
        d_type = DataType.DATA
    elif d_bytes[10:12] == b'\x0cW':  # SYNC
        d_type = DataType.SYNC
    elif d_bytes[10:12] == b'H ':  # UART
        d_type = DataType.UART
    else:
        raise Exception('FOOTER ERROR ', d_bytes[10:12])

    timestamp = int.from_bytes(d_bytes[2:6], 'little')
    data = int.from_bytes(d_bytes[6:10], 'little', signed=True)

    return timestamp, data, d_type




class ElEOF(Exception):
    '''Exception signaling EOF during reading elevation encoder file'''


class ElData:
    '''Elevation data class'''
    def __init__(self, path, use_deque=True, preinfo=False, postinfo=False):
        self._path = Path(path)
        self._fd = None
        if self._path.suffix == '.xz':
            self._fd = lzma.open(self._path, 'rb')
            self._isxz = True
        else:
            self._fd = open(self._path, 'rb')
            self._isxz = False
        self._i = 0

        # First 4 bytes: header length in bytes
        self._hlen = int(self._fd.read(4).decode('utf-8'))
        self._fd.seek(0)

        # Read and parse header
        header = self._fd.read(self._hlen)
        _, version, utime, txt = header_info(header)
        self.file_version = version
        self.c_utime = utime  # creation unix time
        self.c_dt = datetime.fromtimestamp(utime, tz=timezone.utc)  # creation
        self.header_info = txt

        if self._isxz:
            self._length = None
        else:
            self._length = int((self._path.stat().st_size - self._hlen)
                               / PACKET_LENGTH)

        # Data buffer
        self._use_deque = use_deque
        if use_deque:
            self._buffer = deque()
        else:
            self._buffer = []

        self._fin = False

        # Sync information
        self._sync_info = []
        self._sync_count = 6
        self._skip = False
        self._skip_list = []

        if preinfo is False:
            self._sync_stamp = -1
            self._sync_id = -1
            self._sync_offset = 0
        else:
            if isinstance(preinfo, bool):
                path_pre = get_previous_path(path)
                (self._sync_stamp,
                 self._sync_id,
                 self._sync_offset), self._sync_count\
                    = ElData(path_pre).get_last_sync(accept_residue=True)
            else:
                (self._sync_stamp,
                 self._sync_id,
                 self._sync_offset), self._sync_count = preinfo

        if self._sync_count != 6:
            self._sync_info.append([-1, -1, 0])
        else:
            self._sync_info.append([self._sync_stamp,
                                    self._sync_id,
                                    self._sync_offset])

        self._postinfo = postinfo
        self._init = False
        self.__sstamp = None

    def defrag(self, sync_id, uart_count):
        ''' Recover synchronization data from fragmentation.
            Will be used only when a synchronization sequence
            (i.e SYNC + 6*UART) splits into two files.

        Parameters
        ----------
        sync_id: int
            Incomplete synchronization ID from first half of fragmentation

        uart_count: int
            UART count from first half of fragmentation

        Returns
        -------
        sync_id: int
            Recovered synchronization ID
        '''
        u_frag = self._uart_fragment()
        if len(u_frag) + uart_count != 6:
            warnings.warn('UART length wrong')
            return -1

        for i, (_, data) in enumerate(u_frag):
            if (uart_count + i) == 0:
                if data != 0x55:
                    warnings.warn(f'UART header wrong {data}')
                    return -1
            else:
                sync_id += data << 8*(i + uart_count - 1)

        return sync_id

    @property
    def length(self):
        '''Length of the file in packets'''
        if self._length is None:
            cur_pos = self._fd.tell()
            pos = self._fd.seek(0, whence=2)
            self._length = int((pos-self._hlen)/PACKET_LENGTH)
            self._fd.seek(cur_pos)
        return self._length

    @property
    def _sstamp(self):
        if self.__sstamp is None:
            cur_pos = self._tell()
            _i = 0
            while True:
                stamp, _, dtype = self.get_data(_i)
                if dtype == DataType.DATA:
                    break
                _i += 1
            self.__sstamp = stamp
            self._init = True
            self._seek(cur_pos)

        return self.__sstamp

    def __del__(self):
        if self._fd and (not self._fd.closed):
            self._fd.close()

    def __iter__(self):
        self._fd.seek(self._hlen)
        return self

    def _sync_replace(self):
        start = self._buffer[0][0]
        if self._sync_stamp < start:
            if self._sstamp <= self._sync_stamp:
                raise Exception('Buffer too short')
            index = 0
        else:
            index = self._sync_stamp - start + 1

        for _i in range(index, len(self._buffer)):
            if self._buffer[_i][0] > self._sync_stamp:
                self._buffer[_i][2] = self._sync_id
                self._buffer[_i][3] = self._sync_offset
            else:  # This will occur when timestamp goes 2**32-1 -> 0
                print(f'mismatch: {_i}, {self._buffer[_i]}')

    def _sync_push(self, packet):
        stamp, data, d_type = packet
        if d_type == DataType.SYNC:  # start of synchronization
            if self._sync_count != 6:  # SYNC comes before 6 UARTs
                _info = (self._sync_stamp, self._sync_id, self._sync_count)
                warnings.warn(f'UART fragmentation: {_info}')
                # special case
                if (self._sync_count > 0) & (not self._skip):
                    warnings.warn(f'Try to recover: {_info}')
                    return

            # Initialization
            self._sync_stamp = stamp
            self._sync_count = 0
            self._sync_id = 0
            self._sync_offset = data
            self._skip = False
        elif d_type == DataType.UART:  # UART handling
            if self._sync_count == 0:  # header byte. Should be 0x55
                if data != 0x55:
                    warnings.warn('UART header broken. skip.')
                    self._skip = True
            elif 0 < self._sync_count < 6:  # UART body
                self._sync_id += data << 8*(self._sync_count - 1)
            else:
                warnings.warn(
                    f'UART too long. SyncID {self._sync_id} may be ill'
                )
            self._sync_count += 1

            if self._sync_count == 6:  # flush
                if not self._skip:
                    # Calculation for the replacement
                    if len(self._buffer) > 0:
                        self._sync_replace()

                    # Push info
                    self._sync_info.append([self._sync_stamp,
                                            self._sync_id,
                                            self._sync_offset])
                    self._skip = True

        else:  # Do nothing
            warnings.warn('`_sync_push` used for `DATA`')
            return


    def __next__(self):
        # Buffer flush
        if self._fin:
            if len(self._buffer) == 0:
                raise StopIteration()
            if self._use_deque:
                return self._buffer.popleft()
            return self._buffer.pop(0)

        # File read
        try:
            tmpd = self._read()
        except ElEOF:  # finalization
            self._fin = True
            if self._postinfo is False:
                self._sync_stamp = self._buffer[0][0]
                self._sync_id = -1
                self._sync_offset = 0
            else:
                if isinstance(self._postinfo, bool):
                    path_next = get_next_path(self._path)
                    ned = ElData(path_next)
                    if not self._skip:  # searching for synchronization
                        self._sync_id = ned.defrag(self._sync_id,
                                                   self._sync_count)
                    else:
                        (self._sync_stamp,
                         self._sync_id,
                         self._sync_offset), _ = ned.get_first_sync()
                else:
                    (self._sync_stamp,
                     self._sync_id,
                     self._sync_offset), _ = self._postinfo
            self._sync_replace()

            return self.__next__()

        # Parse
        stamp, data, d_type = parsebytes(tmpd)

        # Buffering
        if d_type == DataType.DATA:
            self._buffer.append([stamp, data,
                                 self._sync_info[-1][1],  # SYNC ID
                                 self._sync_info[-1][2]])  # SYNC OFFSET
            if not self._init:  # First data stamp
                self.__sstamp = stamp
                self._init = True
        else:
            self._sync_push((stamp, data, d_type))

        # Output
        if len(self._buffer) < BUFFER_LENGTH:
            return self.__next__()

        if self._use_deque:
            return self._buffer.popleft()

        return self._buffer.pop(0)

    def _uart_fragment(self):
        cur_pos = self._tell()
        uarts = []
        _i = 0
        while True:
            stamp, data, d_type = self.get_data(_i)
            if d_type == DataType.SYNC:
                break

            if d_type == DataType.UART:
                uarts.append([stamp, data])
            _i += 1

        self._seek(cur_pos)

        return uarts

    def parse_all(self):
        '''Parse everything
        Returns
        -------
        ret_list: np.array
            Array of [stamp, data, sync_id, offset]
        '''
        ret_list = []
        for stmp, data, sid, soff in self:
            ret_list.append([stmp, data, sid, soff])
        return np.array(ret_list)

    def get_data(self, cur):
        '''Get data at the given position
        Parameter
        ---------
        cur: int
            Packet number

        Returns
        -------
        stamp: int
        data: int
        d_type: DataType
        '''
        self._seek(cur)
        return parsebytes(self._read())

    def _read(self):
        buf = self._fd.read(PACKET_LENGTH)
        if len(buf) != PACKET_LENGTH:
            raise ElEOF
        return buf

    def _seek(self, cur):
        self._fd.seek(self._hlen + PACKET_LENGTH*cur)

    def _tell(self):
        return int((self._fd.tell() - self._hlen)/PACKET_LENGTH)

    def _find_sync(self, cur_st, cur_en):
        cur_pos = self._fd.tell()

        sync_info = []
        uart_count = 0
        sync_in = False
        sync_id = 0
        sync_stamp = 0
        sync_offset = 0

        try:
            self.get_data(cur_st)
        except ElEOF:
            raise ElEOF

        for _i in range(cur_st, cur_en):
            try:
                stamp, data, d_type = self.get_data(_i)
            except ElEOF:
                break

            if d_type == DataType.SYNC:
                sync_in = True
                sync_stamp = stamp
                sync_offset = data
                sync_id = 0
                uart_count = 0
            elif d_type == DataType.UART:
                if uart_count == 6:
                    raise Exception('UART too long')
                if uart_count != 0:
                    sync_id += data << 8*(uart_count - 1)
                uart_count += 1
            else:  # d_type = DataType.DATA
                if uart_count == 6:
                    if sync_in:
                        sync_info.append([sync_stamp, sync_id, sync_offset])
                    sync_id = 0
                    sync_in = False

        # Back
        if sync_in:
            sync_info.append([sync_stamp, sync_id, sync_offset])

        self._fd.seek(cur_pos)
        return sync_info, uart_count

    def get_last_sync(self, seek_from=0, seek_length=SEEK_LENGTH,
                      accept_residue=False):
        '''Obtain last synchronization information in the file
        Parameters
        ----------
        seek_from: int
            starting point of synchronization seek from the end of file
        seek_length: int
            chunk size to search. If sync not found, the function recursively
            runs with 10*seek_length.
        accept_residue: bool
            Accept incomplete synchronization sequence.
            Use with `defrag` method in the ElData instance of the next file

        Returns
        -------
        sync_info: (int, int, int)
            stamp, sync_id, sync_offset
        uart_count: int
            uart count
        '''
        if seek_from > self.length:
            raise ElEOF

        start = max(self.length - seek_length - seek_from, 0)
        ret_list, uart_count = self._find_sync(start, self.length - seek_from)
        if len(ret_list) == 0:
            return self.get_last_sync(seek_from=seek_from + seek_length - 7,
                                      seek_length=seek_length*10,
                                      accept_residue=accept_residue)

        if uart_count:
            if accept_residue:
                return ret_list[-1], uart_count

            if len(ret_list) > 1:
                return ret_list[-2], uart_count

            sf_rev = seek_from + seek_length - 7
            return self.get_last_sync(seek_from=sf_rev,
                                      seek_length=seek_length*10,
                                      accept_residue=accept_residue)

        return ret_list[-1], uart_count

    def get_first_sync(self, seek_from=0, seek_length=SEEK_LENGTH):
        '''Obtain first synchronization sequence
        '''
        ret_list, _ = self._find_sync(seek_from, seek_from + seek_length)
        if len(ret_list) == 0:
            return self.get_first_sync(seek_from=seek_from + seek_length - 7,
                                       seek_length=seek_length*10)

        return ret_list[0], 0
