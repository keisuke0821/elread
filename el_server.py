#!/usr/bin/env python3
'''Server script'''
import socket
from .cur_tail import get_latest_zenith


IP_ADDRESS = '161.72.134.66'
EL_PORT = 9876

class ElServer:
    '''Server software that provdes the latest zenith angle'''
    def __init__(self, ip_addr=IP_ADDRESS, port=EL_PORT):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((ip_addr, port))

    def run(self):
        '''Run server program'''
        self._sock.listen(10)
        while True:
            clientsock, _ = self._sock.accept()
            while True:
                rcvmsg = clientsock.recv(1024)
                if len(rcvmsg) == 0:
                    break
                print('Received -> %s' % (rcvmsg))
                rcvmsg = rcvmsg.decode().strip()
                if rcvmsg == 'e#zenith?':
                    ret = '{:.3f}'.format(get_latest_zenith())
                    clientsock.sendall(ret.encode('utf-8'))
            clientsock.close()

def main():
    '''Main function'''
    elserver = ElServer()
    elserver.run()


if __name__ == '__main__':
    main()
