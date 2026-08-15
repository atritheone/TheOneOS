

"""
ping.py

ping measures ICMP or HTTPS handshake latency for The One OS.
"""



# imports
import os
import sys

sys.path.insert(0, '/the one/build')

import time
import socket
import struct
from network.network import parseurl, resolvename, opentcp, opentls, NETTIMEOUT



# globals
PACKETCOUNT = 4
TIMEOUT = 5
HTTPSPORT = 443



# checksum functions
def checksum(data):

    try:

        # initialize accumulator
        s = 0

        # compute in 16-bit words
        end = (len(data) // 2) * 2
        i = 0
        while i < end:

            # add word in little-endian order
            val = data[i+1] * 256 + data[i]
            s = (s + val) & 0xFFFFFFFF
            i += 2

        # handle trailing byte
        if end < len(data):
            s = (s + data[-1]) & 0xFFFFFFFF

        # fold to 16 bits
        s = (s >> 16) + (s & 0xFFFF)
        s = s + (s >> 16)

        # ones' complement and network order
        res = socket.htons((~s) & 0xFFFF)
        return res

    except Exception as e:

        # checksum computation error
        print(f"> checksum error {e}")
        return 0


# https functions
def httpping(target):

    try:

        # parse target into components
        scheme, host, port, _ = parseurl(target)

        # validate host
        if not host:
            print("> invalid url")
            return

        # choose default https port when scheme is not explicitly https
        if scheme != 'https':
            port = HTTPSPORT

    except Exception as e:

        # url parse error
        print(f"> url parse error {e}")
        return

    try:

        # resolve hostname to ipv4
        ip = resolvename(host)

    except Exception:

        # dns resolution failure
        print(f"> cannot resolve {host}")
        return

    # print header for https ping
    print(f"> ping {host} [{ip}] port {port}:")

    # initialize counters
    sent = 0
    recv = 0

    # iterate sequence numbers
    for seq in range(1, PACKETCOUNT + 1):

        s = None
        t = None

        try:

            # record start time
            start = time.time()

            # open tcp socket
            s = opentcp(ip, port, timeout=NETTIMEOUT)

            # if tcp failed
            if not s:
                print("> connection failed")
                continue

            # count attempt
            sent += 1

            # perform tls handshake
            t = opentls(s, host)

            # if tls failed
            if not t:
                print("> tls handshake failed")
                continue

            # compute elapsed
            elapsed = int((time.time() - start) * 1000)

            # increment success
            recv += 1

            # print reply line
            print(f"> reply from {ip} seq {seq} time {elapsed}ms")

        except Exception as e:

            # generic https ping error
            print(f"> error {e}")

        finally:

            # close tls socket
            if t:
                t.close()
            if s:
                s.close()
    try:

        # compute loss
        lost = sent - recv
        loss = int(lost / sent * 100) if sent else 100

        # print summary
        print(f"\n> ping statistics for {host} [{ip}]")
        print(f"  packets sent {sent}, completed {recv}, failed {lost} ({loss}% loss)")

    except Exception as e:

        # summary computation error
        print(f"> summary error {e}")


# icmp functions
def icmpping(raw):

    try:

        # pick host from raw target or url
        scheme, host, _, _ = parseurl(raw if '://' in raw else 'http://' + raw)
        desthost = host or raw

    except Exception:

        # fallback to raw target
        desthost = raw

    try:

        # resolve ip address
        destip = resolvename(desthost)

    except Exception:

        # dns resolution failure
        print(f"> cannot resolve {desthost}")
        return

    # print header for icmp ping
    print(f"> PING {desthost} [{destip}] with {PACKETCOUNT} packets:")

    try:

        # create raw icmp socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)

    except PermissionError:

        # architect privileges required
        print("> architect required")
        return

    except OSError as e:

        # socket creation failure
        print(f"> socket error {e}")
        return

    # initialize counters
    pid = os.getpid() & 0xFFFF
    sent = 0
    recv = 0

    # iterate sequence numbers
    for seq in range(1, PACKETCOUNT + 1):

        try:

            # build icmp echo header with zero checksum
            hdr = struct.pack("!BBHHH", 8, 0, 0, pid, seq)

            # build payload with timestamp
            pay = struct.pack("!d", time.time())

            # compute checksum on header+payload
            chk = checksum(hdr + pay)

            # rebuild header with checksum
            hdr = struct.pack("!BBHHH", 8, 0, chk, pid, seq)

            # compose packet
            pkt = hdr + pay

        except Exception as e:

            # packet build error
            print(f"> packet build error {e}")
            continue

        try:

            # send packet
            sent += 1
            sock.sendto(pkt, (destip, 1))

            # set timeout and record start
            sock.settimeout(TIMEOUT)
            start = time.time()

            # receive reply
            _rec, addr = sock.recvfrom(1024)

            # compute elapsed
            elapsed = int((time.time() - start) * 1000)

            # increment success
            recv += 1

            # print reply line
            print(f"> reply from {destip} seq {seq} time {elapsed}ms")

        except socket.timeout:

            # request timed out
            print("> request timed out")

        except Exception as e:

            # send/receive error
            print(f"> error {e}")


    # close socket
    sock.close()

    try:

        # compute loss
        lost = sent - recv
        loss = int(lost / sent * 100) if sent else 100

        # print summary
        print(f"\n> ping statistics for {desthost} [{destip}]")
        print(f"  packets sent {sent}, received {recv}, lost {lost} ({loss}% loss)")

    except Exception as e:

        # summary computation error
        print(f"> summary error {e}")


# core
def main():

    try:

        # require at least one argument
        if len(sys.argv) < 2:
            print("> ping <host or https://url> required")
            return

        # define target
        target = sys.argv[1]

        # decide mode by scheme
        try:
            scheme, _, _, _ = parseurl(target if '://' in target else 'http://' + target)
        except Exception:
            scheme = ''

        # run https mode
        if scheme == 'https':
            httpping(target)
            return

        # run icmp mode
        icmpping(target)

    except KeyboardInterrupt:

        # user aborted
        print("> aborted")

    except Exception as e:

        # fatal runtime error
        print(f"> fatal error {e}")


# execute
if __name__ == '__main__':

    main()
