#!/usr/bin/env python3
'''Provides utility for elevation data analysis
'''
from pathlib import Path
import numpy as np

import sys
sys.path.append('/Users/suenoyoshinori/マイドライブ（yoshinori0778@gmail.com）/CMB/GB/elevation/elread')
from common import get_previous_path, get_next_path
from eldata import ElData

#from .common import get_previous_path, get_next_path
#from .eldata import ElData

EL_FMT = '{:/data/gb/logbdata/el_enc/%Y/%m/%d/el_%Y-%m%d-%H%M%S+0000.dat.xz}'

def dt2elpath(dt_tgt):
    '''Find a path to elevation data that covers the given `dt_tgt`
    Parameter
    ---------
    dt_tgt: datetime.datetime
        target datetime

    Returns
    -------
    elpath: pathlib.Path
        Path to the data that covers `dt_tgt`
    '''
    path_fake = Path(EL_FMT.format(dt_tgt))
    pdir = path_fake.parent
    ppaths = sorted(pdir.glob('*' + path_fake.suffix))
    ind = np.searchsorted(ppaths, path_fake)

    return get_previous_path(ppaths[ind])

def span2elpaths(dt_start, dt_end):
    '''Find paths to elevation data that covers the given region
    Parameters
    ----------
    dt_start: datetime.datetime
        Start of the region
    dt_end: datetime.datetime
        End of the region

    Returns
    -------
    paths: list of pathlib.Path
    '''
    if dt_start >= dt_end:
        raise Exception(f'{dt_start} should be smaller than {dt_end}')

    path_st = dt2elpath(dt_start)
    path_en = get_next_path(dt2elpath(dt_end))

    paths = []
    _pdir = path_st.parent

    while True:
        p_gl = sorted(_pdir.glob('*' + path_st.suffix))

        if path_en in p_gl:
            paths += p_gl[:p_gl.index(path_en)+1]
            return paths[paths.index(path_st):]

        paths += p_gl
        _pdir = get_next_path(p_gl[-1]).parent


def elpaths2el(elpaths):
    '''Combine elevation files
    Parameters
    ----------
    elpaths: list of pathlib.Path

    Returns
    -------
    el_data: array-like
        Length x 5 array (stamp, unixtime, data, sync_no, sync_offset)
    '''
    eld_list = [ElData(path, preinfo=True, postinfo=True) for path in elpaths]
    print(eld_list)
    length = sum([eld.length for eld in eld_list])
    el_data = np.zeros((length, 5)) # stamp, unixtime, data, syn_no, offset
    cur = 0
    dt_st = eld_list[0].c_utime
    st_st = None
    for eld in eld_list:
        tmpd = eld.parse_all()
        if st_st is None:
            st_st = tmpd[0][0]

        tmplen = len(tmpd)
        el_data[cur:cur+tmplen, 0] = tmpd[:, 0] # stamp
        el_data[cur:cur+tmplen, 2:] = tmpd[:, 1:] # data, syn_no, offset
        el_data[cur:cur+tmplen, 1] = dt_st + (tmpd[:, 0] - st_st)/1e3
        cur = cur + tmplen
    return el_data[:cur]
