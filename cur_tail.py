#!/usr/bin/env python3
'''Function that provides the latest zenith value'''

from pathlib import Path
from .eldata import DataType, ElData
from .common import get_latest_path, get_previous_path

DIRBASE = Path('/data/gb/logbdata/el_enc')

def enc2z(enc_val):
#    ''' Formula valid around 2019-10 '''
#    return (enc_val - 9113)/900
#    ''' Formula valid around 2022-0112 '''
#    return (enc_val - 6234)/900
    ''' Formula valid around 2022-0829 '''
    return (enc_val - 7062)/900


def get_latest_zenith():
    '''Returns latest zenith value
    Returns
    zenith: float
        Latest zenith value
    '''
    latest_path = get_latest_path(DIRBASE)
    try:
        tmpeld = ElData(latest_path)

        for i in range(tmpeld.length):
            _, data, d_type = tmpeld.get_data(tmpeld.length - i - 1)
            if d_type == DataType.DATA:
                return enc2z(data)
    except Exception as err:
        print(err)

    # Reach here if the latest path does not have enough length
    second_path = get_previous_path(latest_path)
    tmpeld = ElData(second_path)
    for i in range(tmpeld.length):
        _, data, d_type = tmpeld.get_data(tmpeld.length - i - 1)
        if d_type == DataType.DATA:
            return enc2z(data)

    raise RuntimeError('Caonnt find the latest.')


def main():
    '''Main function'''
    print(get_latest_zenith())


if __name__ == '__main__':
    main()
