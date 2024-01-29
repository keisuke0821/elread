#!/usr/bin/env python3
'''Client software to read latest elevation data'''
import socket


IP_ADDRESS = '161.72.134.66'
EL_PORT = 9876

class ElClient:
    '''Client class to read latest elevation data
    '''
    def __init__(self, ip_addr=IP_ADDRESS, port=EL_PORT):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._ip_addr = ip_addr
        self._port = port
        self._sock.connect((self._ip_addr, self._port))

    def get_zenith(self):
        '''Get zenith angle
        Returns
        -------
        res: float
            Response from the server
        '''
        #self._sock.connect((self._ip_addr, self._port))
        self._sock.send('e#zenith?'.encode('utf-8'))
        res = self._sock.recv(4096)
        return float(res)

def main():
    '''Main function'''
    elc = ElClient()
    print(elc.get_zenith())


if __name__ == '__main__':
    main()
