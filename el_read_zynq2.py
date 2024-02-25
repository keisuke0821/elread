import socket
import fcntl
import mmap
import os
import sys
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep

import numpy as np

# baseaddress of axi_fifo_mm_s
ADDR_AXI = 0x43c10000
# path to the uio
PATH_DEV_BASE = Path(f'/sys/devices/platform/axi/{ADDR_AXI:08x}.axi_fifo_mm_s/uio')
# path to the lock file
PATH_LOCK = Path(__file__).parent.joinpath('.lock')
# offset of timestamp
LEAP_OFFSET = 37

# error class
class el_EncError(Exception):
    '''
    Exception rased by elevation encoder reader.
    '''

# time data class
class el_EncTime:
    '''
    elevation encoder time.

    Parameter
    ---------
    time_raw : int
        Raw time format from TSU.
        [sec 48 bits][nsec 30 bits][sub-nsec 16 bits]
    '''

    def __init__(self, time_raw):
        self._time_raw = time_raw

    @property
    def sec(self):
        '''
        Seconds part of timestamp.

        Returns
        -------
        sec : int
            Seconds part of timestamp.
        '''
        return self._time_raw >> 46

    @property
    def nsec(self):
        '''
        Nano second part of timestamp.

        Returns
        -------
        nsec : int
            Nano-sec part of timestamp.
        '''
        return (0x_00000000_00003fff_ffff0000 & self._time_raw) >> 16

    @property
    def tai(self):
        '''
        Time in seconds from TAI epoch.

        Returns
        -------
        tai : float
            Seconds from TAI epoch.
        '''
        return self.sec + (self.nsec / 1e9)

    @property
    def utc(self):
        '''
        Time in seconds in UTC.

        Returns
        -------
        utc : float
            UnixTime.
        '''
        return self.tai - LEAP_OFFSET

    @property
    def g3(self):
        '''
        G3Time.

        Returns
        -------
        time_g3 : np.int64
            G3Time
        '''
        time_g3 = np.floor((self.utc) * 1e8)

        return np.int64(time_g3)

# data class
class el_EncData:
    '''
    elevation encoder data.

    Parameter
    ---------
    data_raw : ndarray
        Raw data from PL FIFO.
    '''

    def __init__(self, data_bytes):
        self._data_bytes = data_bytes
        self._data_int = int(data_bytes[0]) + (int(data_bytes[1]) << 32) + (int(data_bytes[2]) << 64)

    @property
    def state(self):
        return (self._data_int & 0xC0_00_00_00_00000000_00000000) >> 94

    @property
    def time_raw(self):
        '''94 bit TSU timestamp.

        Returns
        -------
        time_raw : int
            94 bit TSU timestamp.
        '''
        return self._data_int & 0x3F_FF_FF_FF_FFFFFFFF_FFFFFFFF

    @property
    def time(self):
        '''
        TSU timestamp.

        Returns
        -------
        time : StmTime
            TSU timestamp abstraction.
        '''
        return el_EncTime(self.time_raw)

    def __str__(self):
        return f'time={int(self.time.g3)/1e8:.8f} data={self.state:02b}'


def get_path_dev():
    '''
    Acquire devicefile path for `axi_fifo_mm_s` IP core.

    Returns
    -------
    path_dev : Path
        Path to the device file.
    '''
    if not PATH_DEV_BASE.exists():
        raise el_EncError('Device is not found. Check firmware and device tree.')

    # zynq uio -> check the generic uio
    name_dev = list(PATH_DEV_BASE.glob('uio*'))[0].name
    path_dev = Path(f'/dev/{name_dev}')

    return path_dev


class el_EncReader:
    '''Class to read encoder data.

    Parameters
    ----------
    path_dev : str or pathlib.Path
        Path to the generic-uio device file for axi_fifo_mm_s IP.
    path_lock : str or pathlib.Path
        Path to the lockfile.
    '''

    # initialize method -> open the uio device and memorry mapping with mmap
    def __init__(self, path_dev, path_lock=PATH_LOCK, verbose=True):
        # Verbose level
        self._verbose = verbose

        # Locking
        self._fp_lock = open(path_lock, 'w')
        try:
            fcntl.flock(self._fp_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            raise el_EncError('locked.')

        # Connection
        self._path_dev = path_dev
        self._dfile = os.open(self._path_dev, os.O_RDONLY | os.O_SYNC)
        self._dev = mmap.mmap(self._dfile, 0x100, mmap.MAP_SHARED, mmap.PROT_READ, offset=0)

        # Data FIFO
        self.fifo = Queue()

        # Runner
        self._thread = None
        self._running = False

    def __del__(self):
        if self._running:
            self.stop()
        fcntl.flock(self._fp_lock, fcntl.LOCK_UN)
        self._dev.close()
        os.close(self._dfile)

        self._eprint('Fin.')

    def _eprint(self, errmsg):
        if self._verbose:
            sys.stderr.write(f'{errmsg}\r\n')

    # read the data
    def _get_info(self):
         # access to FPGA
        data = np.frombuffer(self._dev, np.uint32, 4, offset=0)
        r_len = data[0]
        w_len = data[1]
        residue = data[2]

        return r_len, w_len, residue

    def _get_data(self):
        data = np.frombuffer(self._dev, np.uint32, 4, offset=16)

        return el_EncData(data)

    def send_data_tcp(self, data):
        try:
          # make socket
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
          # connect to the server
            tcp_socket.connect(('192.168.215.210', 8080))
          # send the data
            tcp_socket.sendall(data)
          # close the socket
            tcp_socket.close()
        except Exception as e:
            print(f"Error in send_data_tcp: {e}")

    def fill(self):
        '''
        Get data from PL fifo and put into software fifo.
        '''
        while True:
            r_len, w_len, residue = self._get_info()

            if (r_len == 0) and (residue == 0):
                break

            self.fifo.put(self._get_data())

    # inifinity loop of reading data
    def _loop(self):
        while self._running:
            self.fill()

           # take the data from queue and send by TCP
            while not self.fifo.empty():
                data = self.fifo.get()
                self.send_data_tcp(data)

            sleep(0.1)

    # start
    def run(self):
        '''
        Run infinite loop of data filling.
        '''
        self._running = True
        self._thread = Thread(target=self._loop)
        self._thread.start()

    # stop
    def stop(self):
        if not self._running:
            raise el_EncError('Not started yet.')

        self._running = False
        self._thread.join()


def main():
    '''Main function to boot infinite loop'''
    el_enc = el_EncReader(get_path_dev(), verbose=True)

    # Filler loop
    fd = open('test.dat', 'w')
    el_enc.run()
    while True:
        try:
            while not el_enc.fifo.empty():
                data = el_enc.fifo.get()
                print(data)
                fd.write(str(data) + '\n')
            sleep(0.1)
        except KeyboardInterrupt:
            el_enc.stop()
            fd.close()
            break

    print('Fin.')


if __name__ == '__main__':
    main()
