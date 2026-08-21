#!"/the one/software/python/bin/python" -B

"""
exchange.py

exchange is the clipboard for The One OS.
"""



## imports
import os
import sys
import time
import json
import socket
import select
import signal
import hashlib

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import formatlog, openreadablelog



## globals

# misc
DEBUGEXCHANGE = False
RUNNING=True

# paths
EPHROOT="/.ephemeral"
SOCKPATH="/.ephemeral/exchange.sock"
PIDPATH="/.ephemeral/exchange.pid"
KEYPATH="/.ephemeral/exchange.key"
STATEPATH="/.ephemeral/exchange.json"
LOGPATH="/the one/logs/exchange.py.log"

# clipboard
MAXBYTES=1048576
MAXMSG=1048576
POLL=0.2
CLIENTS=[]
CLIENTBUFS={}
WATCHERS=[]
STATE={
    "type":"empty",
    "data":"",
    "hash":"",
    "ts":0,
    "source":"system",
    "bytes":0,
    "ttl":0
}
SHUTKEY=""



## functions

# setup functions
def ensurepath(path):

    try:

        # create directory if missing
        os.makedirs(path, exist_ok=True)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to create {path}')

        return False

    except Exception as e:

        # other errors
        logline(f'error creating {path} {e}')

        return False

    return True


def removestale(path):

    try:

        # remove stale socket file
        if os.path.exists(path):
            os.remove(path)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to remove {path}')

        return False

    except Exception as e:

        # other errors
        logline(f'error removing {path} {e}')

        return False

    return True


def writepid(pid):

    try:

        # write pid file
        with open(PIDPATH, 'w', encoding='utf-8') as f:

            f.write(str(pid))

    except PermissionError:

        # permission denied error
        logline(f'permission denied to write {PIDPATH}')

        return False

    except Exception as e:

        # other errors
        logline(f'error writing pid file {e}')

        return False

    return True


def clearpid():

    try:

        # remove pid file
        if os.path.exists(PIDPATH):
            os.remove(PIDPATH)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to remove {PIDPATH}')

    except Exception as e:

        # other errors
        logline(f'error removing pid file {e}')


def writekey(key):

    try:

        # write shutdown key file
        with open(KEYPATH, 'w', encoding='utf-8') as f:

            f.write(key)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to write {KEYPATH}')

        return False

    except Exception as e:

        # other errors
        logline(f'error writing shutdown key {e}')

        return False

    return True


def clearkey():

    try:

        # remove key file
        if os.path.exists(KEYPATH):
            os.remove(KEYPATH)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to remove {KEYPATH}')

    except Exception as e:

        # other errors
        logline(f'error removing key file {e}')


def logline(text):

    if not DEBUGEXCHANGE:
        return

    os.makedirs(os.path.dirname(LOGPATH), exist_ok=True)
    line = formatlog('exchange', text) + '\n'

    with openreadablelog(LOGPATH, "a") as f:

        f.write(line)

        f.flush()

        os.fsync(f.fileno())


def nowsec():

    try:

        # epoch seconds
        return int(time.time())

    except Exception:

        # fallback
        return 0


def makehash(text):

    try:

        # compute sha256
        h=hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()

        return h

    except Exception:

        # hash error
        return ""


def randkey():

    try:

        # generate random bytes
        raw=os.urandom(32)

    except Exception:

        # urandom error fallback
        raw=f'{time.time()}:{os.getpid()}'.encode('utf-8', errors='replace')

    try:

        # hex key
        return hashlib.sha256(raw).hexdigest()

    except Exception:

        # hash error fallback
        return ""


def loadstate():

    global STATE

    # no state file
    if not os.path.exists(STATEPATH):
        return

    try:

        # read state file
        with open(STATEPATH, 'r', encoding='utf-8') as f:

            raw=f.read()

    except FileNotFoundError:

        # state file missing
        return

    except PermissionError:

        # permission denied error
        logline(f'permission denied to read {STATEPATH}')

        return

    except Exception as e:

        # other errors
        logline(f'error reading state file {e}')

        return

    try:

        # parse json
        obj=json.loads(raw)

    except json.JSONDecodeError:

        # invalid json
        return

    except Exception:

        # parse error
        return

    # minimal validation
    t=str(obj.get("type","empty"))

    d=str(obj.get("data",""))

    s=str(obj.get("source","system"))

    ts=int(obj.get("ts",0))

    ttl=int(obj.get("ttl",0))

    # enforce size
    b=len(d.encode('utf-8', errors='replace'))

    if b > MAXBYTES:
        return

    try:

        # compute hash
        h=makehash(d)

    except Exception:

        # hash error
        h=""

    STATE={
        "type":t,
        "data":d,
        "hash":h,
        "ts":ts,
        "source":s,
        "bytes":b,
        "ttl":ttl
    }


def savestate():

    try:

        # dump json
        raw=json.dumps(STATE, ensure_ascii=False)

    except Exception as e:

        # json dump error
        logline(f'error encoding state {e}')

        return False

    try:

        # write state file
        with open(STATEPATH, 'w', encoding='utf-8') as f:

            f.write(raw)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to write {STATEPATH}')

        return False

    except Exception as e:

        # other errors
        logline(f'error writing state file {e}')

        return False

    return True


# validation functions
def validtext(text):

    try:

        # ensure string
        if text is None:
            return False, "no text"

        if not isinstance(text, str):
            text=str(text)

    except Exception:

        # conversion error
        return False, "invalid text"

    try:

        # reject null bytes
        if "\x00" in text:
            return False, "null byte"

    except Exception:

        # scan error
        return False, "scan error"

    try:

        # byte size
        b=len(text.encode('utf-8', errors='replace'))

    except Exception:

        # encode error
        return False, "encode error"

    if b > MAXBYTES:
        return False, "too large"

    return True, ""


def expired(state):

    try:

        # ttl disabled
        ttl=int(state.get("ttl",0))

        if ttl <= 0:
            return False

    except Exception:

        # ttl parse error
        return False

    try:

        # expiry check
        ts=int(state.get("ts",0))

        if ts <= 0:
            return False

    except Exception:

        # ts parse error
        return False

    try:

        # compare
        if nowsec() >= ts + ttl:
            return True

    except Exception:

        # compare error
        return False

    return False


# state functions
def setstate(text, source):

    global STATE

    ok, err=validtext(text)
    if not ok:
        return False, err

    try:

        # compute bytes
        b=len(text.encode('utf-8', errors='replace'))

    except Exception:

        # encode error
        return False, "encode error"

    try:

        # compute hash
        h=makehash(text)

    except Exception:

        # hash error
        h=""

    try:

        # update state
        STATE["type"]="text"

        STATE["data"]=text

        STATE["hash"]=h

        STATE["ts"]=nowsec()

        STATE["source"]=source

        STATE["bytes"]=b

        STATE["ttl"]=0

    except Exception as e:

        # state update error
        return False, f'state update error {e}'

    if not savestate():
        return False, "save error"

    return True, ""


def setstatetype(t, text, source):

    global STATE

    ok, err=validtext(text)
    if not ok:
        return False, err

    try:

        b=len(text.encode('utf-8', errors='replace'))

    except Exception:

        return False, "encode error"

    try:

        h=makehash(text)

    except Exception:

        h=""

    try:

        STATE["type"]=t

        STATE["data"]=text

        STATE["hash"]=h

        STATE["ts"]=nowsec()

        STATE["source"]=source

        STATE["bytes"]=b

        STATE["ttl"]=0

    except Exception as e:

        return False, f'state update error {e}'

    if not savestate():
        return False, "save error"

    return True, ""


def clearstate(source):

    global STATE

    try:

        # clear state
        STATE["type"]="empty"

        STATE["data"]=""

        STATE["hash"]=""

        STATE["ts"]=nowsec()

        STATE["source"]=source

        STATE["bytes"]=0

        STATE["ttl"]=0

    except Exception as e:

        # state clear error
        return False, f'state clear error {e}'

    if not savestate():
        return False, "save error"

    return True, ""


def getstate():


    # expire check
    if expired(STATE):

        # clear expired state
        clearstate("system:expired")

    try:

        # return copy
        return dict(STATE)

    except Exception:

        # fallback
        return {
            "type":"empty",
            "data":"",
            "hash":"",
            "ts":0,
            "source":"system",
            "bytes":0,
            "ttl":0
        }


# permission functions
def allowed(msg):

    try:

        # ensure dict
        if not isinstance(msg, dict):
            return False

    except Exception:

        # type error
        return False

    try:

        # op present
        op=str(msg.get("op","")).strip()

    except Exception:

        # op parse error
        return False

    if op == "":
        return False

    if op == "shutdown":

        try:

            # key required
            key=str(msg.get("key",""))

        except Exception:

            # key parse error
            return False

        if key != SHUTKEY:
            return False

    return True


# socket functions
def serveropen():

    try:

        # create server socket
        srv=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except Exception as e:

        # socket create error
        logline(f'error creating socket {e}')
        return None


    # allow reuse
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:

        # bind and listen
        srv.bind(SOCKPATH)

        # GODDESS deliberately starts services under umask 0077. Exchange is
        # a session broker, so publish only its socket to the desktop group;
        # its state, PID, and shutdown key remain root-private.
        os.chown(SOCKPATH, 0, 1000)

        os.chmod(SOCKPATH, 0o660)

        srv.listen(64)

    except PermissionError:

        # permission denied error
        logline(f'permission denied to bind {SOCKPATH}')

        srv.close()
        return None

    except OSError as e:

        # bind/listen error
        logline(f'error binding socket {e}')

        srv.close()
        return None

    except Exception as e:

        # other errors
        logline(f'error opening server {e}')

        srv.close()
        return None

    # nonblocking
    srv.setblocking(False)

    return srv


def acceptclient(srv):

    global CLIENTBUFS

    try:

        # accept connection
        cli, _=srv.accept()

    except BlockingIOError:

        # nothing to accept
        return

    except Exception:

        # accept error
        return

    # nonblocking client
    cli.setblocking(False)

    # attach buffer
    CLIENTBUFS[cli]=b""

    CLIENTS.append(cli)


def dropclient(cli):

    global CLIENTBUFS

    # remove from watchers
    if cli in WATCHERS:
        WATCHERS.remove(cli)


    # remove from clients
    if cli in CLIENTS:
        CLIENTS.remove(cli)

    # remove buffer
    if cli in CLIENTBUFS:
        del CLIENTBUFS[cli]

    # close socket
    cli.close()


def sendobj(cli, obj):

    try:

        # encode json line
        raw=json.dumps(obj, ensure_ascii=False) + "\n"

        data=raw.encode('utf-8', errors='replace')

    except Exception:

        # encode error
        return False

    try:

        # send all
        cli.sendall(data)

    except BrokenPipeError:

        # broken pipe
        return False

    except ConnectionResetError:

        # reset
        return False

    except OSError:

        # socket error
        return False

    except Exception:

        # other errors
        return False

    return True


def notify(event):

    dead=[]

    for w in list(WATCHERS):

        ok=sendobj(w, event)

        if not ok:
            dead.append(w)

    for w in dead:

        dropclient(w)


def readmsgs(cli):

    global CLIENTBUFS

    data=b""

    try:

        # recv chunk
        data=cli.recv(8192)

    except BlockingIOError:

        # nothing available
        return []

    except ConnectionResetError:

        # reset
        dropclient(cli)

        return []

    except Exception:

        # read error
        dropclient(cli)

        return []

    if data == b"":

        # closed
        dropclient(cli)

        return []

    try:

        # get buffer
        buf=CLIENTBUFS.get(cli, b"") + data

    except Exception:

        # buffer error
        buf=data

    if len(buf) > MAXMSG:

        # message too large
        sendobj(cli, {"ok":False,"error":"message too large"})

        dropclient(cli)

        return []

    msgs=[]

    while True:

        try:

            # split on newline
            i=buf.find(b"\n")

            if i < 0:
                break

        except Exception:

            # find error
            break

        line=buf[:i]

        buf=buf[i+1:]

        if line.strip() == b"":
            continue

        try:

            # parse json
            obj=json.loads(line.decode('utf-8', errors='replace'))

        except json.JSONDecodeError:

            # bad json
            sendobj(cli, {"ok":False,"error":"bad json"})

            continue

        except Exception:

            # parse error
            sendobj(cli, {"ok":False,"error":"parse error"})

            continue

        msgs.append(obj)

    # store remainder
    CLIENTBUFS[cli]=buf

    return msgs


# operation functions
def opping():

    st=getstate()

    try:

        # status payload
        return {
            "ok":True,
            "daemon":"exchange",
            "ts":nowsec(),
            "statehash":st.get("hash",""),
            "statetype":st.get("type","empty"),
            "bytes":st.get("bytes",0)
        }

    except Exception:

        # fallback
        return {"ok":True}


def opget():

    st=getstate()

    try:

        # respond with state
        return {"ok":True,"state":st}

    except Exception:

        # fallback
        return {"ok":True,"state":{}}


def opmeta():

    st=getstate()

    try:

        # metadata only
        return {
            "ok":True,
            "type":st.get("type","empty"),
            "hash":st.get("hash",""),
            "ts":st.get("ts",0),
            "source":st.get("source",""),
            "bytes":st.get("bytes",0),
            "ttl":st.get("ttl",0)
        }

    except Exception:

        # fallback
        return {"ok":True}


def opset(msg):

    try:

        # extract fields
        t=str(msg.get("type","text"))

        d=msg.get("data","")

        s=str(msg.get("source","app"))

    except Exception:

        # parse error
        return {"ok":False,"error":"bad request"}

    if t not in ("text", "files", "html", "image"):
        return {"ok":False,"error":"unsupported type"}

    try:

        # ensure string
        if not isinstance(d, str):
            d=str(d)

    except Exception:

        # conversion error
        return {"ok":False,"error":"invalid data"}

    ok, err=setstatetype(t, d, s)

    if not ok:
        return {"ok":False,"error":err}

    st=getstate()

    # notify watchers
    notify({
        "event":"changed",
        "hash":st.get("hash",""),
        "ts":st.get("ts",0),
        "source":st.get("source",""),
        "bytes":st.get("bytes",0)
    })

    return {"ok":True,"hash":st.get("hash",""),"ts":st.get("ts",0)}


def opclear(msg):

    try:

        # source
        s=str(msg.get("source","app"))

    except Exception:

        # parse error
        s="app"

    ok, err=clearstate(s)

    if not ok:
        return {"ok":False,"error":err}

    st=getstate()

    # notify watchers
    notify({
        "event":"changed",
        "hash":st.get("hash",""),
        "ts":st.get("ts",0),
        "source":st.get("source",""),
        "bytes":st.get("bytes",0)
    })

    return {"ok":True,"ts":st.get("ts",0)}


def opwatch(cli):

    try:

        # add watcher
        if cli not in WATCHERS:
            WATCHERS.append(cli)

    except Exception:

        # watcher error
        return {"ok":False,"error":"watch error"}

    st=getstate()

    # send current state meta immediately
    sendobj(cli, {
        "event":"ready",
        "hash":st.get("hash",""),
        "ts":st.get("ts",0),
        "type":st.get("type","empty"),
        "bytes":st.get("bytes",0)
    })

    return {"ok":True}


def opunwatch(cli):

    try:

        # remove watcher
        if cli in WATCHERS:
            WATCHERS.remove(cli)

    except Exception:

        # unwatch error
        return {"ok":False,"error":"unwatch error"}

    return {"ok":True}


def opshutdown():

    global RUNNING

    # stop loop
    RUNNING=False

    return {"ok":True}


# routing functions
def handle(cli, msg):

    if not allowed(msg):
        return {"ok":False,"error":"not allowed"}

    try:

        # op
        op=str(msg.get("op","")).strip()

    except Exception:

        # parse error
        return {"ok":False,"error":"bad op"}

    if op == "ping":
        return opping()

    if op == "get":
        return opget()

    if op == "meta":
        return opmeta()

    if op == "set":
        return opset(msg)

    if op == "clear":
        return opclear(msg)

    if op == "watch":
        return opwatch(cli)

    if op == "unwatch":
        return opunwatch(cli)

    if op == "shutdown":
        return opshutdown()

    return {"ok":False,"error":"unknown op"}


# signal functions
def handlesig(signum, frame):

    global RUNNING

    # stop loop
    RUNNING=False


def daemonrun():

    global SHUTKEY

    ok=ensurepath(EPHROOT)

    if not ok:
        return 1

    ok=removestale(SOCKPATH)

    if not ok:
        return 1

    SHUTKEY=randkey()

    if SHUTKEY == "":
        return 1

    ok=writekey(SHUTKEY)

    if not ok:
        return 1

    ok=writepid(os.getpid())

    if not ok:
        return 1

    loadstate()

    # attach signals
    signal.signal(signal.SIGTERM, handlesig)

    signal.signal(signal.SIGINT, handlesig)

    srv=serveropen()
    if srv is None:

        clearpid()

        clearkey()

        return 1

    logline(f'exchange daemon started pid = {os.getpid()} sock = {SOCKPATH}')

    while RUNNING:

        rlist=[srv] + list(CLIENTS)

        try:

            # select with timeout
            ready, _, _=select.select(rlist, [], [], POLL)

        except InterruptedError:

            # signal interrupt
            continue

        except Exception:

            # select error
            time.sleep(POLL)

            continue

        for s in ready:

            if s is srv:

                acceptclient(srv)

                continue

            msgs=readmsgs(s)

            if msgs == []:

                continue

            for m in msgs:

                res=handle(s, m)

                ok=sendobj(s, res)

                if not ok:

                    dropclient(s)

                    break

    # close clients
    for c in list(CLIENTS):
        dropclient(c)

    # close server
    srv.close()

    removestale(SOCKPATH)

    clearpid()

    clearkey()

    logline('exchange daemon stopped')

    return 0


# client functions
def exconnect():

    try:

        # create socket
        cli=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except Exception:

        # socket create error
        return None

    try:

        # connect
        cli.connect(SOCKPATH)

    except Exception:

        # connect error
        cli.close()

        return None

    return cli


def exrecv(cli, timeout=2.0):

    buf=b""

    t0=time.time()

    while True:

        try:

            # recv
            data=cli.recv(8192)

        except Exception:

            # recv error
            return None

        if data == b"":
            return None

        buf += data

        if len(buf) > MAXMSG:
            return None

        try:

            # newline terminator
            i=buf.find(b"\n")

            if i < 0:
                pass

            else:

                line=buf[:i]

                obj=json.loads(line.decode('utf-8', errors='replace'))

                return obj

        except Exception:
            return None

        try:

            # timeout
            if time.time() - t0 > timeout:
                return None

        except Exception:
            return None


def excall(msg, timeout=2.0):

    cli=exconnect()

    if cli is None:
        return None

    try:

        # send request
        raw=json.dumps(msg, ensure_ascii=False) + "\n"

        cli.sendall(raw.encode('utf-8', errors='replace'))

    except Exception:

        # send error
        cli.close()

        return None

    res=exrecv(cli, timeout=timeout)

    # close
    cli.close()

    return res


def exping():

    res=excall({"op":"ping"})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exget():

    res=excall({"op":"get"})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    try:

        # state object
        st=res.get("state", {})
        return True, st

    except Exception:

        # parse error
        return False, res


def exmeta():

    res=excall({"op":"meta"})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exset(text, source="app"):

    try:

        # ensure string
        if not isinstance(text, str):
            text=str(text)

    except Exception:

        # conversion error
        return False, {"error":"invalid text"}

    res=excall({"op":"set","type":"text","data":text,"source":source})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exsetfiles(payload, source="app"):

    try:

        raw=json.dumps(payload, ensure_ascii=False)

    except Exception:

        return False, {"error":"invalid payload"}

    res=excall({"op":"set","type":"files","data":raw,"source":source})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exsethtml(text, source="app"):

    try:

        if not isinstance(text, str):
            text=str(text)

    except Exception:

        return False, {"error":"invalid html"}

    res=excall({"op":"set","type":"html","data":text,"source":source})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exsetimage(payload, source="app"):

    try:

        raw=json.dumps(payload, ensure_ascii=False)

    except Exception:

        return False, {"error":"invalid image payload"}

    res=excall({"op":"set","type":"image","data":raw,"source":source})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exclear(source="app"):

    res=excall({"op":"clear","source":source})

    if res is None:
        return False, {}

    if not res.get("ok", False):
        return False, res

    return True, res


def exwatch(onchange, source="app"):

    cli=exconnect()

    if cli is None:
        return False, {"error":"connect error"}

    try:

        # send watch request
        raw=json.dumps({"op":"watch","source":source}, ensure_ascii=False) + "\n"

        cli.sendall(raw.encode('utf-8', errors='replace'))

    except Exception:

        # send error
        cli.close()

        return False, {"error":"send error"}

    # watch loop
    while True:

        msg=exrecv(cli, timeout=3600.0)

        if msg is None:
            break

        try:

            # callback
            onchange(msg)

        except Exception:

            # ignore callback errors
            pass

    # close socket
    cli.close()

    return True, {"ok":True}


# entry functions
def start():

    return daemonrun()



# execute start
if __name__ == "__main__":

    raise SystemExit(start())
