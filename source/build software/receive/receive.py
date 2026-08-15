

"""
receive.py

receive fetches a site page for The One OS.
"""



# imports
import sys

sys.path.insert(0, '/the one/build')

from network.network import parseurl, resolvename, opentcp, opentls, NETBUFSIZE, NETTIMEOUT



# globals
DEFAULTPORT = 80
DEFAULTSPORT = 443
TIMEOUT = NETTIMEOUT
BUFSIZE = NETBUFSIZE



# functions
def fetch(url):

    try:

        # parse the target url into components
        scheme, host, port, path = parseurl(url)

    except Exception as e:

        # url parsing error
        sys.__stdout__.write(f"> url parse error {e}\n")
        return

    if not host:

        # invalid url missing host
        sys.__stdout__.write("> invalid url\n")
        return

    try:

        # resolve hostname to ipv4
        ip = resolvename(host)

    except Exception as e:

        # dns resolve failure
        sys.__stdout__.write(f"> dns resolve failed {host} {e}\n")
        return

    try:

        # choose default port when missing
        if not port:
            port = DEFAULTSPORT if scheme == 'https' else DEFAULTPORT

        # open tcp connection to target ip and port
        s = opentcp(ip, port, timeout=TIMEOUT)

        # handle tcp connection failure
        if not s:
            sys.__stdout__.write("> connection failed\n")
            return

        # wrap in tls if scheme is https
        if scheme == 'https':
            t = opentls(s, host)
            if not t:
                sys.__stdout__.write("> tls handshake failed\n")
                s.close()
                return
            sock = t
        else:
            sock = s

    except Exception as e:

        # socket setup error
        sys.__stdout__.write(f"> connection failed {e}\n")
        return

    try:

        # build minimal http/1.1 request with host and close semantics
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: t1os-receive/0.2\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()

        # send full http request
        sock.sendall(req)

    except Exception as e:

        # request send error
        sys.__stdout__.write(f"> error sending request {e}\n")
        sock.close()
        return

    try:

        # receive response into buffer until connection closes
        chunks = []
        while True:

            # read next chunk
            data = sock.recv(BUFSIZE)

            # stop on eof
            if not data:
                break

            # append to buffer list
            chunks.append(data)

        # close socket after read loop
        sock.close()
        response = b"".join(chunks)

    except Exception as e:

        # error while receiving
        sys.__stdout__.write(f"> error fetching page {e}\n")
        sock.close()
        return

    try:

        # split headers and body on first blank line
        headsep = response.split(b"\r\n\r\n", 1)
        body = headsep[1] if len(headsep) > 1 else b""

        # write body bytes directly to stdout buffer
        sys.__stdout__.buffer.write(body)

        # flush output
        sys.__stdout__.flush()

    except Exception as e:

        # printing error
        sys.__stdout__.write(f"> error printing page {e}\n")


def main():

    try:

        # require a single url argument
        if len(sys.argv) < 2:
            sys.__stdout__.write("> usage receive url\n")
            return

        # read the url from arguments
        target = sys.argv[1]

        # fetch target url
        fetch(target)

    except KeyboardInterrupt:

        # user aborted
        sys.__stdout__.write("> aborted\n")

    except Exception as e:

        # fatal error
        sys.__stdout__.write(f"> fatal error {e}\n")


# execute
if __name__ == '__main__':

    main()
