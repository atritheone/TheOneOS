#!/bin/python3.13

import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(5)
s.bind(('',0))
s.sendto(b'test', ('10.0.2.3', 53))
try:
    data, addr = s.recvfrom(512)
    print("got reply", data, "from", addr)
except socket.timeout:
    print("UDP still timed out")