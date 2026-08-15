

"""
rubbish.py

manages the rubbish bin for The One OS.
"""



# imports
import os
import sys
import json
import re

sys.path.insert(0, '/the one/build')

import time
import shutil
import getpass
import secrets
from reign.reign import timestamp
import architect.architect as arch



# globals
RUBBISHDIR='/.rubbish'
INDEXFILE='/.rubbish/index.txt'
LOGFILE='/the one/logs/rubbish.py.log'
CONF_FILE='/the one/settings/rubbish.txt'
SESSIONIDENTITYFILE='/the one/settings/session/identity.json'
SESSIONIDENTITYMAXBYTES=1024
SESSIONUSERNAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,31}')



# misc functions
def loadconfig():

    cfg={'maxsizemb':'512','maxagedays':'30','protectsecs':'3600'}

    try:

        # read config file if present
        if os.path.exists(CONF_FILE):

            with open(CONF_FILE) as f:

                for line in f:

                    line=line.strip()

                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        k,v=line.split('=',1)
                        cfg[k.strip()]=v.strip()

    except Exception as e:

        # config read error
        print(f"> config read error {e}")

    return cfg


def getusername():

    try:

        with open(SESSIONIDENTITYFILE, 'rb') as stream:
            raw = stream.read(SESSIONIDENTITYMAXBYTES + 1)

    except OSError as error:

        raise RuntimeError(
            'the active session identity is unavailable') from error

    if len(raw) > SESSIONIDENTITYMAXBYTES:

        raise RuntimeError('the active session identity is too large')

    try:

        identity = json.loads(raw.decode('utf-8'))

    except (UnicodeDecodeError, ValueError) as error:

        raise RuntimeError('the active session identity is invalid') from error

    if (
        not isinstance(identity, dict) or
        set(identity) != {'format', 'username'} or
        type(identity.get('format')) is not int or
        identity.get('format') != 1
    ):

        raise RuntimeError('the active session identity is invalid')

    username = identity.get('username')
    if not isinstance(username, str) or not SESSIONUSERNAME.fullmatch(username):

        raise RuntimeError('the active session username is invalid')

    return username


def formattime(secs):

    try:

        # prefer atreyan formatter from reign
        return timestamp(int(secs))

    except TypeError:

        # some builds of timestamp() take no args; fall back to "now"
        return timestamp()
    except Exception:
        pass

    try:

        # Last resort still uses the T1OS Atreyan date contract.
        value = time.localtime(int(secs))
        year = value.tm_year - 2020
        hour = value.tm_hour % 12 or 12
        ampm = 'AM' if value.tm_hour < 12 else 'PM'
        return f'[{value.tm_mday:02}:{value.tm_mon:02}:{year}AE {hour}:{value.tm_min:02}:{value.tm_sec:02} {ampm}]'

    except Exception:

        # if all else fails, show the raw value
        return str(secs)


def ensuretiers():

    try:

        # create rubbish index tier
        os.makedirs(RUBBISHDIR,exist_ok=True)

        # create index if missing
        if not os.path.exists(INDEXFILE):
            with open(INDEXFILE,'w') as f:
                f.write("id\tname\torigpath\tisdir\tsize\tdeletedts\tuser\n")

    except PermissionError:

        # permission denied creating rubbish tiers
        print(f"> permission denied to create rubbish tiers")
        return False

    except Exception as e:

        # other error creating rubbish tiers
        print(f"> cannot ensure rubbish tiers {e}")
        return False

    return True


# rubbish functions
def maketemp(path):

    try:

        # make temp file path
        return f"{path}.tmp.{secrets.token_hex(3)}"

    except Exception as e:

        # error building temp path
        print(f"> temp path error {e}")
        return f"{path}.tmp"


def appendindex(row):

    try:

        # atomic append via temp then concat to index
        tmp=maketemp(INDEXFILE)

        # open temp for append
        with open(tmp,'w') as tf:

            tf.write(row)

        # append to index
        with open(INDEXFILE,'a') as f:

            with open(tmp) as tf:

                f.write(tf.read())

        # remove temp
        os.remove(tmp)
    except PermissionError:

        # permission denied appending index
        print(f"> permission denied to write to the index")

    except Exception as e:

        # index append error
        print(f"> index append error {e}")


def readindex():

    items=[]

    try:

        # open index file
        with open(INDEXFILE) as f:

            # skip header
            header=True

            for line in f:

                if header:
                    header=False
                    continue

                line=line.rstrip('\n')

                if not line:
                    continue

                parts=line.split('\t')

                if len(parts) < 7:
                    continue

                rec={
                    'id':parts[0],
                    'name':parts[1],
                    'origpath':parts[2],
                    'isdir':parts[3],
                    'size':parts[4],
                    'deletedts':parts[5],
                    'user':parts[6],
                }

                items.append(rec)

    except FileNotFoundError:

        # index missing
        return []

    except Exception as e:

        # error reading index
        print(f"> read index error {e}")

    return items


def writeindex(items):

    try:

        # build text with header
        lines=["id\tname\torigpath\tisdir\tsize\tdeletedts\tuser\n"]

        for r in items:

            line="\t".join([
                r.get('id',''),
                r.get('name',''),
                r.get('origpath',''),
                r.get('isdir',''),
                r.get('size',''),
                r.get('deletedts',''),
                r.get('user',''),
            ])+"\n"

            lines.append(line)

        # atomic replace
        tmp=maketemp(INDEXFILE)

        with open(tmp,'w') as f:

            f.writelines(lines)

        os.replace(tmp,INDEXFILE)

    except PermissionError:

        # permission denied rewriting index
        print(f"> permission denied to rewrite the index")

    except Exception as e:

        # error rewriting index
        print(f"> write index error {e}")


def makeid():

    try:

        # build unique id
        return f"{int(time.time()*1000)}-{secrets.token_hex(4)}"

    except Exception as e:

        # id generation error
        print(f"> id make error {e}")
        return f"{int(time.time()*1000)}-xxxx"


def sizesingle(path):

    try:

        # if tier compute recursive size
        if os.path.isdir(path):

            total=0

            for root,dirs,files in os.walk(path):

                for n in files:

                    fp=os.path.join(root,n)

                    total+=os.path.getsize(fp)
            return total

        # if file use stat size
        else:

            return os.path.getsize(path)

    except FileNotFoundError:

        # size path missing
        return 0

    except Exception as e:

        # size compute error
        print(f"> size error {e}")
        return 0


def rubbishsize():

    total=0

    try:

        # sum sizes of all content payloads
        for r in readindex():

            payload=os.path.join(RUBBISHDIR,r['id'],'content')

            total+=sizesingle(payload)

    except Exception as e:

        # rubbish size error
        print(f"> rubbish size error {e}")

    return total


# store functions
def storeone(path):

    try:

        # Resolve the authenticated owner before creating a rubbish tier or
        # moving any data. Missing or malformed session identity fails closed.
        user=getusername()

    except Exception as e:

        print(f"> active session identity unavailable {e}")
        return

    # normalize path
    target=os.path.abspath(path)

    try:

        # block deleting rubbish itself
        if os.path.commonpath([target,RUBBISHDIR]) == RUBBISHDIR:
            print(f"> ignore request inside rubbish {target}")
            return

    except Exception as e:

        # commonpath error
        print(f"> path check error {e}")

    try:

        # verify exists
        if not os.path.exists(target):
            print(f"> {target} not found")
            return

        # build id and payload tier
        rid=makeid()

        payloadtier=os.path.join(RUBBISHDIR,rid)

        os.makedirs(payloadtier,exist_ok=False)

        payload=os.path.join(payloadtier,'content')

    except PermissionError:

        # permission denied building payload
        print(f"> permission denied to create payload")
        return

    except FileExistsError:

        # rare id clash, try again once
        rid=makeid()
        payloadtier=os.path.join(RUBBISHDIR,rid)
        try:
            os.makedirs(payloadtier,exist_ok=False)
            payload=os.path.join(payloadtier,'content')
        except Exception as e:
            print(f"> payload tier clash {e}")
            return

    except Exception as e:

        # payload build error
        print(f"> payload build error {e}")
        return

    try:

        # move the target into payload
        shutil.move(target,payload)

    except PermissionError:

        # permission denied moving target
        print(f"> permission denied to put {target} in the rubbish")
        return

    except Exception as e:

        # move error
        print(f"> error putting {target} in the rubbish {e}")
        return

    try:

        # gather metadata
        name=os.path.basename(target)

        isdir='1' if os.path.isdir(payload) else '0'

        size=str(sizesingle(payload))

        ts=str(int(time.time()))

        row=f"{rid}\t{name}\t{target}\t{isdir}\t{size}\t{ts}\t{user}\n"

        appendindex(row)

    except Exception as e:

        # metadata append error
        print(f"> error writing metadata {e}")


def storepaths(paths):

    try:

        # ensure tiers present
        if not ensuretiers():
            return

        # store each given path
        for p in paths:
            storeone(p)

    except Exception as e:

        # storepaths unexpected error
        print(f"> error deleting tier {e}")


# brick functions
def deletedkey(item):

    try:
        return int(item[4])
    except Exception:
        return 0


def restorefromrubbish(name, originalpath=None):

    indexfile = '/.rubbish/index.txt'

    try:
        with open(indexfile) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        print('> rubbish is empty')
        return False

    matches = []
    for line in lines[1:]:
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 7:
            continue
        rid, fname, origpath, isdir, size, deletedts, user = parts
        if fname == name and (originalpath is None or os.path.abspath(origpath) == os.path.abspath(originalpath)):
            matches.append((rid, fname, origpath, isdir, deletedts))

    if not matches:
        print(f'> no such file or tier {name} in rubbish')
        return False

    if len(matches) > 1:

        matches.sort(key=deletedkey, reverse=True)

        print('> id\tname\toriginal path\tdeleted')

        for rid, fname, origpath, isdir, deletedts in matches:
            ts_str = formattime(deletedts)
            print(f'> {rid}\t{fname}\t{origpath}\t{ts_str}')

        print('> use restore id <id> or restore <name> from <original tier>')
        return False
    else:
        rid, fname, origpath, isdir, deletedts = matches[0]

    try:
        source = os.path.join('/.rubbish', rid, 'content')

        # check the complete original destination before restoring
        if not arch.check(origpath):
            print('> permission denied to restore item')
            return False

        if os.path.exists(origpath):
            print(f'> restore destination already exists {origpath}')
            return False

        dest_dir = os.path.dirname(origpath)
        os.makedirs(dest_dir, exist_ok=True)

        shutil.move(source, origpath)

        newlines = [lines[0]] + [l for l in lines[1:] if not l.startswith(rid + '\t')]
        with open(indexfile, 'w') as f:
            f.write('\n'.join(newlines) + '\n')

        print(f"> {fname} restored")
        return True

    except PermissionError:
        print('> permission denied to restore item')
        return False

    except Exception as e:
        print(f"> error restoring {fname} {e}")
        return False


def restorefromrubbishrid(rid):

    indexfile = '/.rubbish/index.txt'

    try:
        with open(indexfile) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        print('> rubbish is empty')
        return False

    record = None

    for line in lines[1:]:

        if not line:
            continue

        parts = line.split('\t')

        if len(parts) < 7:
            continue

        if parts[0] == rid:
            record = parts
            break

    if not record:
        print('> item not found in rubbish index')
        return False

    rid, fname, origpath, isdir, size, deletedts, user = record

    try:

        source = os.path.join('/.rubbish', rid, 'content')

        # check the complete original destination before restoring
        if not arch.check(origpath):
            print('> permission denied to restore item')
            return False

        if os.path.exists(origpath):
            print(f'> restore destination already exists {origpath}')
            return False

        destdir = os.path.dirname(origpath)

        os.makedirs(destdir, exist_ok=True)

        shutil.move(source, origpath)

        newlines = [lines[0]] + [l for l in lines[1:] if not l.startswith(rid + '\t')]

        with open(indexfile, 'w') as f:
            f.write('\n'.join(newlines) + '\n')

        print(f"> {fname} restored")
        return True

    except Exception as e:

        print(f"> error restoring {fname} {e}")
        return False


def emptyrubbish(args=None):

    try:

        # read all records
        items=readindex()

        # remove payloads
        for r in items:

            payload=os.path.join(RUBBISHDIR,r['id'])

            if os.path.isdir(payload):
                shutil.rmtree(payload,ignore_errors=True)
            elif os.path.exists(payload):
                os.remove(payload)
        writeindex([])

        print(f"> rubbish emptied")

    except PermissionError:

        # permission denied empty
        print(f"> permission denied to empty the rubbish")

    except Exception as e:

        # empty error
        print(f"> error whilst emptying the rubbish {e}")


def purgerubbish(args=None):

    try:

        # ensure index
        if not ensuretiers():
            return

        # load config
        cfg=loadconfig()

        maxsizemb=int(cfg.get('maxsizemb','512') or '512')

        maxagedays=int(cfg.get('maxagedays','30') or '30')

        protectsecs=int(cfg.get('protectsecs','3600') or '3600')

        # load records
        items=readindex()

        now=int(time.time())

        # first remove items older than maxage (respect protect)
        keep=[]
        remove=[]

        for r in items:

            age=now-int(r['deletedts'])

            if age >= maxagedays*86400 and age >= protectsecs:
                remove.append(r)
            else:
                keep.append(r)

        for r in remove:

            payload=os.path.join(RUBBISHDIR,r['id'])

            shutil.rmtree(payload,ignore_errors=True)
        if remove:
            writeindex(keep)

        # enforce size cap
        total=rubbishsize()

        cap=maxsizemb*1024*1024

        if total <= cap:
            print(f"> purge ok size={total} cap={cap}")
            return

        # sort keep by oldest first
        keep_sorted=sorted(keep,key=lambda x:int(x['deletedts']))

        changed=False

        for r in keep_sorted:

            if total <= cap:
                break

            age=now-int(r['deletedts'])

            if age < protectsecs:
                continue

            payload=os.path.join(RUBBISHDIR,r['id'])

            try:
                sz=sizesingle(payload)
            except Exception:
                sz=0

            shutil.rmtree(payload,ignore_errors=True)
            total-=sz

            keep=[x for x in keep if x['id']!=r['id']]

            changed=True

        if changed:
            writeindex(keep)

        print(f"> purge done size={total} cap={cap}")

    except Exception as e:

        # purge error
        print(f"> purge error {e}")
