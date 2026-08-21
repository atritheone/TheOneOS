#!"/the one/software/python/bin/python" -B

"""
network.py

network.py manages interface setup in The One OS.
"""



# imports
import os
import sys
import ssl
import time
import json
import hashlib
import socket
import struct
import random
import secrets
import re
import stat as statmodule
import select
import subprocess
import urllib.parse
from pyroute2 import IPRoute

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import formatlog, popenisolated
from operations.operations import service_secret_get



# globals
NETDIR='/the one/settings/network'
CACERTSFILE = '/the one/settings/network/cacerts.pem'
DNSCONF = '/the one/settings/network/dns.txt'
GLOBALCONF = '/the one/settings/network/network.txt'
WIRELESSCONF = '/the one/settings/network/wireless.txt'
WIRELESSCREDENTIALPATTERN = r'network\.wireless\.[0-9a-f]{24}'
WIRELESSENGINE = '/the one/software/network/wireless-engine'
NETWORKRUNTIME = '/.ephemeral/network'
CONNECTIONSTATE = os.path.join(NETWORKRUNTIME, 'connection.json')
INTERFACESTATE = os.path.join(NETWORKRUNTIME, 'interfaces.json')
FIREWALLSTATE = os.path.join(NETWORKRUNTIME, 'firewall.json')
INITIALSTATE = os.path.join(NETWORKRUNTIME, 'initial.json')
INITIALSTATEFIELDS = frozenset(('format', 'connected', 'interface', 'completed'))
INITIALSTATEMAXIMUM = 512
INITIALSTATEINTERFACE = re.compile(r'[A-Za-z0-9_.:-]{0,15}')
WIRELESSSCANREQUEST = os.path.join(NETWORKRUNTIME, 'scan.request')
WIRELESSSCANSTATE = os.path.join(NETWORKRUNTIME, 'wireless.json')
RECONFIGUREREQUEST = os.path.join(NETWORKRUNTIME, 'reconfigure.request')
DMIROOT = '/the one/drivers/state/class/dmi/id'
LOGFILE = "/the one/logs/network.py.log"
DHCPSERVERPORT=67
DHCPCLIENTPORT=68
DHCPTIMEOUT=10
DHCPMAGIC = b'\x63\x82\x53\x63'
DNSPORT = 53
DNSTIMEOUT = 3
DNSMAXRESP = 4096
DEBUGNETWORK = os.environ.get('T1OS_NETWORK_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')
NETTIMEOUT = 15
NETBUFSIZE = 65536
WIRELESSPROCESSES = {}
WIRELESSCONFIGURATIONS = {}
LASTDHCPOPTIONS = {}
FIREWALLTABLE = 't1os_filter'
FIREWALLREADY = False
FIREWALLPROFILE = ''
FIREWALLPROFILES = frozenset(('protected', 'open'))



# misc functions
def getconfig(path):

    # try reading the interface config file into memory
    try:

        # open the file path for read-only access
        with open(path) as f:

            # build a list of "key=value" lines ignoring comments/blank lines
            lines = [
                l.strip()
                for l in f
                if '=' in l and not l.startswith('#')
            ]

    # if the file cannot be opened or read, report and return empty config
    except Exception as e:

        # log the config open failure with timestamp and continue gracefully
        log(f"could not open config {path} {e}")

        # return an empty dictionary to signal no configuration
        return {}

    # transform "key=value" lines into a dictionary and return it
    return dict(l.split('=', 1) for l in lines)


def hostnetworksettings():

    config = getconfig(GLOBALCONF) if os.path.exists(GLOBALCONF) else {}
    firewall = str(config.get('firewall') or 'protected').strip().lower()
    if firewall not in FIREWALLPROFILES:
        firewall = 'protected'
    dns = str(config.get('dns') or 'automatic').strip().lower()
    if dns not in ('automatic', 'manual'):
        dns = 'automatic'
    interface = str(config.get('interface') or '').strip()
    if INITIALSTATEINTERFACE.fullmatch(interface) is None:
        interface = ''
    return {
        'firewall': firewall,
        'dns': dns,
        'interface': interface,
    }


def dhcpoptiontext(options, code):

    value = options.get(int(code), b'') if isinstance(options, dict) else b''

    if not isinstance(value, (bytes, bytearray)):
        return ''

    decoded = bytes(value).decode('utf-8', errors='replace').replace('\x00', '')
    decoded = ''.join(character for character in decoded if character.isprintable())
    return ' '.join(decoded.split()).strip()


def connectiontype(iface):

    iface = str(iface or '').strip()
    lowered = iface.lower()

    if iswirelessname(iface):
        return 'wi-fi'
    if lowered.startswith(('ww', 'ppp', 'rmnet', 'cdc-wdm')):
        return 'mobile'
    if lowered.startswith(('bnep', 'bt')):
        return 'bluetooth'
    if lowered.startswith(('tun', 'tap', 'wg')):
        return 'vpn'
    if lowered.startswith(('usb', 'rndis')):
        return 'usb'
    return 'ethernet'


def ethernetconnectionid(iface, gateway='', server='', mac=''):

    identity = '\0'.join((
        'ethernet',
        str(iface or '').strip(),
        str(mac or '').strip().lower(),
        str(gateway or '').strip(),
        str(server or '').strip(),
    ))
    return 'ethernet-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def writeconnectionstate(iface, connected, name='', address='', gateway='', server='', mac='', connectionid=''):

    displayname = ''.join(
        character for character in str(name or '')
        if character.isprintable() and character not in ('\r', '\n')
    ).strip()
    state = {
        'interface': str(iface or ''),
        'type': connectiontype(iface) if iface else '',
        'connected': bool(connected),
        # Preserve the capitalization supplied by DHCP or the associated AP.
        'name': displayname,
        'address': str(address or ''),
        'gateway': str(gateway or ''),
        'server': str(server or ''),
        'mac': str(mac or ''),
        'connection_id': str(connectionid or ''),
        'updated': int(time.time()),
    }

    try:

        ensurenetworkruntime()
        temporary = CONNECTIONSTATE + '.tmp'

        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, sort_keys=True, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, 0o644)
        os.replace(temporary, CONNECTIONSTATE)

    except Exception as error:

        log(f"could not publish connection state iface='{iface}' err='{error}'")


def atomicjson(path, value):

    ensurenetworkruntime()
    temporary = path + '.tmp'

    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, sort_keys=True, separators=(',', ':'))
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def ensurenetworkruntime():

    # Settings creates fixed request files while Network owns state and the
    # directory.  Write+traverse without listing, plus sticky deletion rules,
    # provides the intended boot-scoped exchange using ordinary DAC.
    os.makedirs(NETWORKRUNTIME, mode=0o1733, exist_ok=True)
    os.chmod(NETWORKRUNTIME, 0o1733)


def writeinitialstate(value):

    if not isinstance(value, dict) or set(value) != INITIALSTATEFIELDS:
        raise ValueError('invalid initial network state fields')
    if type(value.get('format')) is not int or value['format'] != 1:
        raise ValueError('invalid initial network state format')
    if type(value.get('connected')) is not bool:
        raise ValueError('invalid initial network connection status')
    interface = value.get('interface')
    if not isinstance(interface, str) or INITIALSTATEINTERFACE.fullmatch(interface) is None:
        raise ValueError('invalid initial network interface')
    completed = value.get('completed')
    if type(completed) is not int or completed <= 0:
        raise ValueError('invalid initial network completion time')

    payload = json.dumps(
        value, sort_keys=True, separators=(',', ':')
    ).encode('utf-8') + b'\n'
    if not payload or len(payload) > INITIALSTATEMAXIMUM:
        raise ValueError('initial network state is too large')

    directory = os.path.dirname(INITIALSTATE)
    ensurenetworkruntime()
    directorydescriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
        getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
    )
    temporary = (
        f'.initial.json.new.{os.getpid()}.{secrets.token_hex(8)}'
    )
    descriptor = None

    try:
        status = os.fstat(directorydescriptor)
        if (
            not statmodule.S_ISDIR(status.st_mode)
            or status.st_uid != 0
            or status.st_gid != 0
            or statmodule.S_IMODE(status.st_mode) != 0o1733
        ):
            raise PermissionError('initial network state directory is unsafe')

        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
            0o600,
            dir_fd=directorydescriptor,
        )
        os.fchmod(descriptor, 0o600)
        created = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(created.st_mode)
            or created.st_uid != 0
            or created.st_gid != 0
            or created.st_nlink != 1
            or statmodule.S_IMODE(created.st_mode) != 0o600
        ):
            raise PermissionError('initial network state file is unsafe')

        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError('short write publishing initial network state')
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            os.path.basename(INITIALSTATE),
            src_dir_fd=directorydescriptor,
            dst_dir_fd=directorydescriptor,
        )
        os.fsync(directorydescriptor)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directorydescriptor)
        except OSError:
            pass
        raise
    finally:
        os.close(directorydescriptor)


def loadjson(path, default=None):

    try:

        with open(path, 'r', encoding='utf-8') as handle:
            value = json.load(handle)

        return value

    except Exception:

        return {} if default is None else default


def log(msg, debug=False, durable=False):

    # T1OS absolute paths are meaningful only inside the target Linux runtime.
    # Native Windows Python interprets "/the one/..." at the root of the
    # current Windows drive, so host-side imports and tests must never write it.
    if os.name == 'nt':
        return

    if debug and not DEBUGNETWORK:
        return


    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
    except Exception:
        pass

    line = formatlog('network', msg) + '\n'

    with open(LOGFILE, "a") as f:

        f.write(line)

        f.flush()

        if durable:
            os.fsync(f.fileno())


def _nftexpression(name, attributes):

    return {
        'attrs': [
            ('NFTA_EXPR_NAME', name),
            ('NFTA_EXPR_DATA', {
                'attrs': [
                    (f'NFTA_{name.upper()}_{key.upper()}', value)
                    for key, value in attributes
                ],
            }),
        ],
    }


def _nftverdict(code=1):

    return [_nftexpression('immediate', (
        ('dreg', 0),
        ('data', {
            'attrs': [
                ('NFTA_DATA_VERDICT', {
                    'attrs': [('NFTA_VERDICT_CODE', int(code))],
                }),
            ],
        }),
    ))]


def _nftmetacompare(key, value):

    return [
        _nftexpression('meta', (('dreg', 1), ('key', int(key)))),
        _nftexpression('cmp', (
            ('sreg', 1),
            ('op', 0),
            ('data', {'attrs': [('NFTA_DATA_VALUE', bytes(value))]}),
        )),
    ]


def _nftestablishedrelated():

    # nftables conntrack state bits: established=0x02, related=0x04.
    # The ct expression places NFT_CT_STATE in a native-endian register.
    # Encoding this mask in network byte order tests 0x06000000 on T1OS's
    # little-endian x86-64 target, so no ESTABLISHED or RELATED reply can
    # match and the input chain's default-drop policy discards DNS, TCP, and
    # TLS responses.  Data-register masks must use the target's native order.
    mask = struct.pack('=I', 0x06)
    zero = struct.pack('=I', 0)
    return [
        _nftexpression('ct', (('dreg', 1), ('key', 0))),
        _nftexpression('bitwise', (
            ('sreg', 1),
            ('dreg', 1),
            ('len', 4),
            ('mask', {'attrs': [('NFTA_DATA_VALUE', mask)]}),
            ('xor', {'attrs': [('NFTA_DATA_VALUE', zero)]}),
        )),
        _nftexpression('cmp', (
            ('sreg', 1),
            ('op', 1),
            ('data', {'attrs': [('NFTA_DATA_VALUE', zero)]}),
        )),
    ]


def _nftdhcpreply():

    # UDP source 67, destination 68.  The L4 protocol check precedes the
    # transport-header load so non-UDP packets can never match by accident.
    return [
        *_nftmetacompare(16, struct.pack('B', socket.IPPROTO_UDP)),
        _nftexpression('payload', (
            ('dreg', 1),
            ('base', 2),
            ('offset', 0),
            ('len', 4),
        )),
        _nftexpression('cmp', (
            ('sreg', 1),
            ('op', 0),
            ('data', {'attrs': [
                ('NFTA_DATA_VALUE', struct.pack('!HH', DHCPSERVERPORT, DHCPCLIENTPORT)),
            ]}),
        )),
    ]


def _nftattribute(message, name):

    getter = getattr(message, 'get_attr', None)
    if callable(getter):
        return getter(name)
    if isinstance(message, dict):
        if name in message:
            return message[name]
        for key, value in message.get('attrs', ()):  # test and fallback representation
            if key == name:
                return value
    return None


def firewallpresent(nft, profile='protected'):

    profile = profile if profile in FIREWALLPROFILES else 'protected'

    expected = {
        (FIREWALLTABLE, 'input'): 0,
        (FIREWALLTABLE, 'forward'): 0,
        (FIREWALLTABLE, 'output'): 1,
    }
    actual = {
        (
            _nftattribute(message, 'NFTA_CHAIN_TABLE'),
            _nftattribute(message, 'NFTA_CHAIN_NAME'),
        ): _nftattribute(message, 'NFTA_CHAIN_POLICY')
        for message in nft.get_chains()
    }
    ownedrules = [
        message for message in nft.get_rules()
        if _nftattribute(message, 'NFTA_RULE_TABLE') == FIREWALLTABLE
    ]
    return (
        all(actual.get(identity) == policy for identity, policy in expected.items()) and
        len(ownedrules) == (6 if profile == 'open' else 5) and
        all(_nftattribute(message, 'NFTA_RULE_CHAIN') == 'input' for message in ownedrules)
    )


def verifyhostfirewall(nftfactory=None, profile='protected'):

    if nftfactory is None:
        from pyroute2.nftables.main import NFTables
        nftfactory = lambda: NFTables(nfgen_family=1)

    nft = nftfactory()
    try:
        return firewallpresent(nft, profile)
    finally:
        close = getattr(nft, 'close', None)
        if callable(close):
            close()


def applyhostfirewall(nftfactory=None, profile='protected'):

    profile = profile if profile in FIREWALLPROFILES else 'protected'

    if nftfactory is None:
        from pyroute2.nftables.main import NFTables
        nftfactory = lambda: NFTables(nfgen_family=1)  # NFPROTO_INET

    nft = nftfactory()

    try:
        tables = nft.get_tables()
        exists = any(
            _nftattribute(message, 'NFTA_TABLE_NAME') == FIREWALLTABLE
            for message in tables
        )

        nft.begin()
        if exists:
            nft.table('del', name=FIREWALLTABLE)
        nft.table('add', name=FIREWALLTABLE)
        nft.chain(
            'add', table=FIREWALLTABLE, name='input', hook='input',
            type='filter', priority=0, policy=0,
        )
        nft.chain(
            'add', table=FIREWALLTABLE, name='forward', hook='forward',
            type='filter', priority=0, policy=0,
        )
        nft.chain(
            'add', table=FIREWALLTABLE, name='output', hook='output',
            type='filter', priority=0, policy=1,
        )

        # The input policy is deny-by-default.  Only local IPC, replies to
        # outbound flows, network-control ICMP, and DHCP configuration traffic
        # cross the boundary.
        nft.rule(
            'add', table=FIREWALLTABLE, chain='input',
            expressions=(_nftmetacompare(6, b'lo\x00'), _nftverdict()),
        )
        nft.rule(
            'add', table=FIREWALLTABLE, chain='input',
            expressions=(_nftestablishedrelated(), _nftverdict()),
        )
        nft.rule(
            'add', table=FIREWALLTABLE, chain='input',
            expressions=(_nftmetacompare(16, struct.pack('B', socket.IPPROTO_ICMP)), _nftverdict()),
        )
        nft.rule(
            'add', table=FIREWALLTABLE, chain='input',
            expressions=(_nftmetacompare(16, struct.pack('B', socket.IPPROTO_ICMPV6)), _nftverdict()),
        )
        nft.rule(
            'add', table=FIREWALLTABLE, chain='input',
            expressions=(_nftdhcpreply(), _nftverdict()),
        )
        if profile == 'open':
            # The firewall remains installed and forwarding remains denied.
            # This final input verdict is the explicit user-selected policy for
            # software that must accept unsolicited connections from the link.
            nft.rule(
                'add', table=FIREWALLTABLE, chain='input',
                expressions=(_nftverdict(),),
            )
        nft.commit()

        if not firewallpresent(nft, profile):
            raise RuntimeError('committed firewall chains were not observable')
        return True

    finally:
        close = getattr(nft, 'close', None)
        if callable(close):
            close()


def writefirewallstate(profile, active, error=''):

    try:
        atomicjson(FIREWALLSTATE, {
            'active': bool(active),
            'profile': profile if profile in FIREWALLPROFILES else 'protected',
            'incoming': 'allowed' if profile == 'open' else 'blocked',
            'forwarding': 'blocked',
            'outgoing': 'allowed',
            'error': str(error or ''),
            'updated': int(time.time()),
        })
    except Exception as stateerror:
        log(f'could not publish firewall state: {stateerror}', durable=True)


def ensurehostfirewall(profile=None):

    global FIREWALLREADY, FIREWALLPROFILE

    if profile is None:
        profile = hostnetworksettings()['firewall']
    profile = profile if profile in FIREWALLPROFILES else 'protected'

    if FIREWALLREADY and FIREWALLPROFILE == profile:
        try:
            if verifyhostfirewall(profile=profile):
                writefirewallstate(profile, True)
                return True
            log('host firewall drift detected; rebuilding policy', durable=True)
        except Exception as error:
            log(f'host firewall verification failed: {error}', durable=True)
        FIREWALLREADY = False
        FIREWALLPROFILE = ''

    try:
        FIREWALLREADY = bool(applyhostfirewall(profile=profile))
        FIREWALLPROFILE = profile if FIREWALLREADY else ''
        writefirewallstate(profile, FIREWALLREADY)
    except Exception as error:
        FIREWALLREADY = False
        FIREWALLPROFILE = ''
        log(f'host firewall admission failed: {error}', durable=True)
        writefirewallstate(profile, False, error)

    return FIREWALLREADY


def quarantinenetworkinterfaces():

    for iface in list(WIRELESSPROCESSES):
        stopwireless(iface)

    ip = None
    try:
        ip = IPRoute()
        for link in ip.get_links():
            name = link.get_attr('IFLA_IFNAME')
            if not name or name == 'lo':
                continue
            indexes = ip.link_lookup(ifname=name)
            if indexes:
                ip.link('set', index=indexes[0], state='down')
    except Exception as error:
        log(f'network quarantine failed: {error}', durable=True)
    finally:
        if ip is not None:
            ip.close()


def iswirelessname(name):

    lowered = str(name or '').lower()
    state = os.path.join('/the one/drivers/state/class/net', str(name or ''))
    return (
        os.path.isdir(os.path.join(state, 'wireless')) or
        os.path.exists(os.path.join(state, 'phy80211')) or
        lowered.startswith(('wl', 'wifi'))
    )


def virtualboxplatform():

    for name in ('product_name', 'sys_vendor', 'board_vendor'):

        try:

            with open(os.path.join(DMIROOT, name), encoding='utf-8') as stream:

                value = stream.read(256).strip().lower()

        except OSError:

            continue

        if 'virtualbox' in value or 'innotek' in value:

            return True

    return False


def dnsserversforlease(router, servers, isvirtualbox=None):

    result = list(servers or [])

    if isvirtualbox is None:

        isvirtualbox = virtualboxplatform()

    # VirtualBox's NAT DHCP service can advertise the host's physical/VPN DNS
    # addresses even when its DNS proxy is enabled.  The proxy is exposed to
    # the guest at 10.0.2.3 beside the standard 10.0.2.2 NAT gateway.
    if isvirtualbox and router == '10.0.2.2' and '10.0.2.3' not in result:

        result.insert(0, '10.0.2.3')

        log("using VirtualBox NAT dns proxy 10.0.2.3")

    return result


def linkinventory():

    links = []

    with IPRoute() as ip:

        for link in ip.get_links():

            name = link.get_attr('IFLA_IFNAME')

            if not name or name == 'lo':
                continue

            carrier = link.get_attr('IFLA_CARRIER')
            operstate = str(link.get_attr('IFLA_OPERSTATE') or '').upper()
            flags = int(link.get('flags', 0) or 0)
            wireless = iswirelessname(name)

            links.append({
                'name': name,
                'index': int(link.get('index', 0) or 0),
                'carrier': bool(int(carrier or 0)),
                'operstate': operstate,
                'up': bool(flags & 0x1),
                'wireless': wireless,
                'mac': link.get_attr('IFLA_ADDRESS'),
            })

    links.sort(key=lambda item: (
        0 if linkready(item) and not item['wireless'] else
        1 if linkready(item) and item['wireless'] else
        2 if not item['wireless'] else 3,
        item['index'],
        item['name'],
    ))

    try:
        atomicjson(INTERFACESTATE, {'interfaces': [
            {
                'name': link['name'],
                'type': 'wi-fi' if link['wireless'] else connectiontype(link['name']),
                'state': str(link.get('operstate') or '').lower() or 'offline',
                'wireless': bool(link['wireless']),
            }
            for link in links
        ]})
    except Exception as error:
        log(f'could not publish interface inventory err={error}')

    log(f"interface inventory {links}", debug=True)
    return links


def linkready(link):

    # Wireless drivers may expose IFLA_CARRIER before an access point has
    # accepted the station.  DHCP is only valid once the interface is both
    # associated (carrier) and operational.  Wired links retain the normal
    # carrier rule because their operstate can lag briefly after link-up.
    if link.get('wireless'):
        return bool(link.get('carrier')) and str(link.get('operstate', '')).upper() == 'UP'

    return bool(link.get('carrier'))


def activatewiredinterfaces(links):

    activated = []

    for link in links:

        if link['wireless'] or link['up']:
            continue

        name = link['name']
        log(f"bringing wired interface '{name}' up before carrier detection")

        if upinterface(name):
            activated.append(name)

    return activated


def activatewirelessinterfaces(links):

    activated = []

    for link in links:

        if not link['wireless'] or link['up']:
            continue

        name = link['name']
        log(f"bringing wireless interface '{name}' up")

        if upinterface(name):
            activated.append(name)

    return activated


def detectinterface(allowwireless=False):

    for link in linkinventory():

        if link['wireless'] and not allowwireless:
            continue

        if linkready(link):

            log(
                f"detected usable interface '{link['name']}' carrier=1 "
                f"operstate={link['operstate']} wireless={link['wireless']}"
            )
            return link['name']

    kind = 'interface' if allowwireless else 'wired interface'
    log(f'no carrier-ready {kind} found')

    # indicate detection failure to caller
    return None


def wirelesssettings(iface):

    specific = os.path.join(NETDIR, f'{iface}.wireless.txt')
    path = specific if os.path.exists(specific) else WIRELESSCONF

    if not os.path.exists(path):
        return {}

    settings = getconfig(path)

    # General network settings contain only a credential reference.  The
    # secret itself is kept in the broker's descriptor-relative, root-only
    # service store so UI and status readers cannot scrape it.
    credential = str(settings.get('credential', '') or '').strip()
    if 'passphrase' in settings:
        log(f"refusing legacy plaintext wireless credential in {path}", durable=True)
        return {}
    if credential and not re.fullmatch(WIRELESSCREDENTIALPATTERN, credential):
        log(f"refusing invalid wireless credential reference in {path}", durable=True)
        return {}
    if credential:
        try:
            passphrase = service_secret_get(credential, timeout=3.0)
            if not passphrase:
                raise ValueError('empty broker response')
            settings['passphrase'] = passphrase
        except Exception as error:
            log(f"wireless credential '{credential}' unavailable: {error}", durable=True)
            return {}

    return settings


def wirelessconfigurationtext(settings):

    ssid = str(settings.get('ssid', '')).strip()
    security = str(settings.get('security', 'wpa2')).strip().lower()
    passphrase = str(settings.get('passphrase', ''))

    if (
        not ssid or
        len(ssid.encode('utf-8')) > 32 or
        '=' in ssid or
        any(character in ssid for character in ('\x00', '\n', '\r'))
    ):
        return None

    def quoted(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

    lines = [
        'ctrl_interface=' + NETWORKRUNTIME + '/control',
        'update_config=0',
        'network={',
        '    ssid=' + quoted(ssid),
    ]

    if security in ('open', 'none'):
        lines.append('    key_mgmt=NONE')
    elif security in ('wpa3', 'sae'):
        if (
            len(passphrase.encode('utf-8')) < 8 or
            len(passphrase.encode('utf-8')) > 63 or
            any(character in passphrase for character in ('\x00', '\n', '\r'))
        ):
            return None
        lines.extend(('    key_mgmt=SAE', '    sae_password=' + quoted(passphrase), '    ieee80211w=2'))
    elif security in ('wpa2', 'wpa', 'psk'):
        if (
            len(passphrase.encode('utf-8')) < 8 or
            len(passphrase.encode('utf-8')) > 63 or
            any(character in passphrase for character in ('\x00', '\n', '\r'))
        ):
            return None
        lines.extend(('    key_mgmt=WPA-PSK', '    psk=' + quoted(passphrase), '    ieee80211w=1'))
    else:
        return None

    lines.extend(('}', ''))
    return '\n'.join(lines)


def wirelessscanconfigurationtext():

    return '\n'.join((
        'ctrl_interface=' + NETWORKRUNTIME + '/control',
        'update_config=0',
        'ap_scan=1',
        '',
    ))


def stopwireless(iface):

    process = WIRELESSPROCESSES.pop(iface, None)
    WIRELESSCONFIGURATIONS.pop(iface, None)

    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    try:
        os.unlink(os.path.join(NETWORKRUNTIME, 'control', iface))
    except OSError:
        pass


def startwireless(iface, configuration):

    if not os.path.isfile(WIRELESSENGINE):
        log(f"wireless engine unavailable at {WIRELESSENGINE}")
        return False

    existing = WIRELESSPROCESSES.get(iface)

    if (
        existing is not None and
        existing.poll() is None and
        WIRELESSCONFIGURATIONS.get(iface) == configuration
    ):
        return True

    if existing is not None:
        stopwireless(iface)

    ensurenetworkruntime()
    control = os.path.join(NETWORKRUNTIME, 'control')
    os.makedirs(control, mode=0o700, exist_ok=True)
    configpath = os.path.join(NETWORKRUNTIME, f'{iface}.wireless.conf')

    with open(configpath, 'w', encoding='utf-8') as handle:
        handle.write(configuration)
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(configpath, 0o600)
    try:
        process = popenisolated(
            [WIRELESSENGINE, '-i', iface, '-D', 'nl80211', '-c', configpath, '-C', control],
            softwarepath=WIRELESSENGINE,
            logpath=LOGFILE,
            stdin=subprocess.PIPE,
            close_fds=True,
        )
        process.stdin.close()
    except Exception as e:
        log(f"wireless engine start failed interface='{iface}' err={e}")
        return False

    WIRELESSPROCESSES[iface] = process
    WIRELESSCONFIGURATIONS[iface] = configuration
    log(f"wireless engine started interface='{iface}' pid={process.pid}")
    return True


def ensurewireless(iface):

    settings = wirelesssettings(iface)
    configuration = wirelessconfigurationtext(settings)

    if not configuration:
        log(f"wireless interface '{iface}' has no valid T1OS wireless settings")
        return False

    return startwireless(iface, configuration)


def wirelesscontrolcommand(iface, command, timeout=5):

    server = os.path.join(NETWORKRUNTIME, 'control', iface)
    deadline = time.monotonic() + max(0.1, float(timeout))

    while not os.path.exists(server):
        process = WIRELESSPROCESSES.get(iface)
        if process is not None and process.poll() is not None:
            return ''
        if time.monotonic() >= deadline:
            return ''
        time.sleep(0.1)

    clientpath = os.path.join(
        NETWORKRUNTIME,
        f'control-client-{os.getpid()}-{random.randint(1, 2**31 - 1)}',
    )
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    try:
        channel.bind(clientpath)
        channel.settimeout(max(0.1, float(timeout)))
        channel.connect(server)
        channel.send(str(command).encode('utf-8'))
        return channel.recv(NETBUFSIZE).decode('utf-8', errors='replace')
    except Exception as error:
        log(f"wireless control command failed interface='{iface}' command='{command}' err={error}")
        return ''
    finally:
        channel.close()
        try:
            os.unlink(clientpath)
        except OSError:
            pass


def connectedwirelessname(iface):

    status = wirelesscontrolcommand(iface, 'STATUS', timeout=2)

    for line in status.splitlines():
        if line.startswith('ssid='):
            name = ''.join(
                character for character in line.split('=', 1)[1]
                if character.isprintable() and character not in ('\r', '\n')
            ).strip()
            if name:
                return name

    # The control status should normally be authoritative.  Retain the saved
    # value only as a compatibility fallback for an older wireless engine.
    return str(wirelesssettings(iface).get('ssid', '') or '').strip()


def wirelesssecurity(flags):

    upper = str(flags or '').upper()

    if 'SAE' in upper or 'WPA3' in upper:
        return 'wpa3'
    if 'WPA' in upper or 'RSN' in upper or 'PSK' in upper:
        return 'wpa2'
    return 'open'


def parsewirelessscan(text):

    networks = {}

    for line in str(text or '').splitlines():
        columns = line.split('\t', 4)
        if len(columns) < 5 or columns[0].strip().lower() == 'bssid':
            continue

        try:
            signal = int(columns[2].strip())
        except ValueError:
            signal = -999

        flags = columns[3].strip()
        ssid = ''.join(character for character in columns[4] if character.isprintable()).strip()

        if not ssid:
            continue

        candidate = {
            'ssid': ssid,
            'security': wirelesssecurity(flags),
            'signal': signal,
        }
        previous = networks.get(ssid)

        if previous is None or candidate['signal'] > previous['signal']:
            networks[ssid] = candidate

    return sorted(networks.values(), key=lambda item: (-item['signal'], item['ssid'].casefold()))


def scanwireless(iface):

    upinterface(iface)
    settings = wirelesssettings(iface)
    configuration = wirelessconfigurationtext(settings) or wirelessscanconfigurationtext()

    if not startwireless(iface, configuration):
        return []

    response = wirelesscontrolcommand(iface, 'SCAN')
    if not response.startswith('OK'):
        log(f"wireless scan request rejected interface='{iface}' response={response!r}")
        return []

    deadline = time.monotonic() + 8

    while time.monotonic() < deadline:
        time.sleep(0.5)
        results = parsewirelessscan(wirelesscontrolcommand(iface, 'SCAN_RESULTS', timeout=2))
        if results:
            return results

    return []


def waitforwirelessready(iface, timeout=NETTIMEOUT):

    deadline = time.monotonic() + max(1, int(timeout))

    while time.monotonic() < deadline:

        for link in linkinventory():

            if link['name'] == iface and linkready(link):
                log(
                    f"wireless association ready interface='{iface}' "
                    f"operstate={link['operstate']}"
                )
                return True

        process = WIRELESSPROCESSES.get(iface)

        if process is not None and process.poll() is not None:
            log(f"wireless engine exited interface='{iface}' status={process.returncode}")
            return False

        time.sleep(0.5)

    log(f"wireless association timed out interface='{iface}'")
    return False


def upinterface(iface):

    # create a netlink handle to modify link state
    ip = IPRoute()

    # resolve the interface index by name
    idxs = ip.link_lookup(ifname=iface)

    # if the interface does not exist, close and report
    if not idxs:

        # close the netlink handle before returning
        ip.close()

        # log that the interface name could not be found
        log(f"interface '{iface}' not found")

        # return None to signal failure to bring interface up
        return None

    # pick the first matching index for operations
    idx = idxs[0]

    # try to set interface state to UP and read its MAC
    try:

        # instruct kernel to bring the link up
        ip.link('set', index=idx, state='up')

        # fetch fresh link information after the state change
        info = ip.get_links(idx)[0]

        # extract the MAC address attribute from the link info
        mac = info.get_attr('IFLA_ADDRESS')

        # log success with the interface MAC shown
        log(f"interface '{iface}' up with mac {mac}")

    # if netlink operations fail, report and set mac to None
    except Exception as e:

        # log the error encountered while trying to activate the link
        log(f"error bringing up '{iface}' {e}")

        # clear mac to indicate failure
        mac = None

    # always close the netlink handle
    finally:

        # close the IPRoute instance
        ip.close()

    # return the MAC string (or None on failure)
    return mac


def dhcpbasepacket(mac, xid, broadcast=True):

    chaddr = bytes(int(value, 16) for value in mac.split(':'))

    if len(chaddr) != 6:
        raise ValueError("DHCP requires a six-byte hardware address")

    return struct.pack(
        '!BBBBIHHIIII16s192s4s',
        1,
        1,
        6,
        0,
        int(xid),
        0,
        0x8000 if broadcast else 0,
        0,
        0,
        0,
        0,
        chaddr + (b'\x00' * 10),
        b'\x00' * 192,
        DHCPMAGIC
    )


def padbootp(packet):

    # RFC 2131 requires clients to be prepared for 576-byte datagrams and the
    # historic BOOTP minimum is 300 bytes. Some home routers discard a shorter
    # DHCPREQUEST even after accepting a padded DHCPDISCOVER.
    if len(packet) < 300:
        packet += b'\x00' * (300 - len(packet))

    return packet


def dhcpdiscoverpacket(mac, xid):

    hardware = bytes(int(value, 16) for value in mac.split(':'))
    packet = dhcpbasepacket(mac, xid)
    packet += b'\x35\x01\x01'
    packet += b'\x3d\x07\x01' + hardware
    packet += b'\x39\x02\x02\x40'
    packet += b'\x37\x08\x01\x03\x06\x0f\x1c\x33\x3a\x3b'
    packet += b'\xff'
    return padbootp(packet)


def dhcprequestpacket(mac, xid, yiaddr, server, broadcast=True):

    hardware = bytes(int(value, 16) for value in mac.split(':'))
    packet = dhcpbasepacket(mac, xid, broadcast=broadcast)

    # SELECTING-state DHCPREQUEST. The client identifier must be identical to
    # the one used in DHCPDISCOVER; omitting it can make a server treat this as
    # a different client and silently ignore the request.
    packet += b'\x35\x01\x03'
    packet += b'\x32\x04' + socket.inet_aton(yiaddr)
    packet += b'\x36\x04' + socket.inet_aton(server)
    packet += b'\x3d\x07\x01' + hardware
    packet += b'\x39\x02\x02\x40'
    packet += b'\x37\x08\x01\x03\x06\x0f\x1c\x33\x3a\x3b'
    packet += b'\xff'
    return padbootp(packet)


def dhcpframepayload(frame):

    # A DHCP server is permitted to deliver a reply directly to the offered
    # hardware address before the client owns the offered IPv4 address.  Such
    # a frame is visible at the link layer but can be discarded by the IPv4
    # stack before a UDP socket bound to 0.0.0.0 sees it.
    if not isinstance(frame, (bytes, bytearray)) or len(frame) < 42:
        return None, None

    packet = bytes(frame)
    offset = 14
    ethertype = struct.unpack('!H', packet[12:14])[0]

    # Preserve compatibility with one or two 802.1Q/QinQ tags.
    for _ in range(2):
        if ethertype not in (0x8100, 0x88A8):
            break
        if len(packet) < offset + 4:
            return None, None
        ethertype = struct.unpack('!H', packet[offset + 2:offset + 4])[0]
        offset += 4

    if ethertype != 0x0800 or len(packet) < offset + 20:
        return None, None

    versionihl = packet[offset]
    if versionihl >> 4 != 4:
        return None, None

    ipheader = (versionihl & 0x0F) * 4
    if ipheader < 20 or len(packet) < offset + ipheader + 8:
        return None, None
    if packet[offset + 9] != socket.IPPROTO_UDP:
        return None, None
    if struct.unpack('!H', packet[offset + 6:offset + 8])[0] & 0x1FFF:
        return None, None

    source = socket.inet_ntoa(packet[offset + 12:offset + 16])
    udp = offset + ipheader
    sourceport, destinationport, udplength = struct.unpack('!HHH', packet[udp:udp + 6])
    if sourceport != DHCPSERVERPORT or destinationport != DHCPCLIENTPORT or udplength < 8:
        return None, None

    end = min(len(packet), udp + udplength)
    payload = packet[udp + 8:end]
    return (payload, (source, sourceport)) if payload else (None, None)


def dhcppacketlistener(iface):

    try:
        listener = socket.socket(
            socket.AF_PACKET,
            socket.SOCK_RAW,
            socket.htons(0x0800)
        )
        listener.bind((iface, 0))
        listener.setblocking(False)
        log(f"dhcp link-layer reply listener ready iface='{iface}'")
        return listener
    except Exception as error:
        log(f"dhcp link-layer reply listener unavailable iface='{iface}' err='{error}'")
        try:
            listener.close()
        except Exception:
            pass
        return None


def receivedhcpreply(udpsocket, packetlistener, timeout):

    if packetlistener is None:
        udpsocket.settimeout(timeout)
        return udpsocket.recvfrom(2048)

    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout()

        readable, _, _ = select.select(
            [udpsocket, packetlistener], [], [], remaining
        )
        if not readable:
            raise socket.timeout()

        for source in readable:
            if source is udpsocket:
                return udpsocket.recvfrom(2048)

            frame, _ = packetlistener.recvfrom(65535)
            payload, peer = dhcpframepayload(frame)
            if payload is not None:
                log(
                    f"dhcp reply received at link layer src={peer} "
                    f"bytes={len(payload)}"
                )
                return payload, peer


def parsedhcpoptions(packet):

    if len(packet) < 240 or packet[236:240] != DHCPMAGIC:
        return {}

    result = {}
    options = packet[240:]
    offset = 0

    while offset < len(options):
        code = options[offset]

        if code == 255:
            break

        if code == 0:
            offset += 1
            continue

        if offset + 1 >= len(options):
            break

        length = options[offset + 1]
        end = offset + 2 + length

        if end > len(options):
            break

        result.setdefault(code, options[offset + 2:end])
        offset = end

    return result


def dhcptransaction(iface, mac):

    global LASTDHCPOPTIONS

    LASTDHCPOPTIONS = {}

    # generate a random transaction id for this DHCP session
    xid = random.randrange(1, 0xFFFFFFFF)

    log(f"dhcp start iface='{iface}' mac='{mac}' xid=0x{xid:08x}")

    pkt = dhcpdiscoverpacket(mac, xid)

    log(f"dhcp discover packet len={len(pkt)} clientport={DHCPCLIENTPORT} serverport={DHCPSERVERPORT} timeout={DHCPTIMEOUT}")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    log(f"dhcp socket created fd={s.fileno()}")

    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    log("dhcp socket opts set: SO_REUSEADDR=1 SO_BROADCAST=1")

    # bind the socket to the specified interface (link scope)
    try:

        s.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BINDTODEVICE,
            iface.encode()
        )

        log(f"bindtodevice ok iface='{iface}'")

    except Exception as e:

        log(f"bindtodevice failed iface='{iface}' err='{e}'")

        log(f"bindtodevice failed on '{iface}' {e}")

    ip2 = None

    try:

        ip2 = IPRoute()

        idxs2 = ip2.link_lookup(ifname=iface)

        log(f"netlink link_lookup iface='{iface}' idxs={idxs2}")

        if idxs2:
            ip2.route(
                'replace',
                dst='255.255.255.255/32',
                scope='link',
                oif=idxs2[0]
            )

            log(f"netlink route replace ok dst=255.255.255.255/32 oif={idxs2[0]} scope=link")

    except Exception as e:

        log(f"netlink route setup failed err='{e}'")

    finally:

        if ip2:
            ip2.close()

            log("netlink handle closed")

    s.bind(('0.0.0.0', DHCPCLIENTPORT))

    log(f"dhcp socket bind ok sockname={s.getsockname()}")

    s.settimeout(DHCPTIMEOUT)

    log("dhcp recv timeout set")

    # transmit the DHCPDISCOVER packet to the broadcast address
    try:

        s.sendto(pkt, ('255.255.255.255', DHCPSERVERPORT))

        log(f"dhcp discover sent dst=255.255.255.255:{DHCPSERVERPORT} bytes={len(pkt)}")

    except Exception as e:

        log(f"dhcp sendto failed err='{e}'")

        raise

    # wait for a server DHCPOFFER until timeout triggers
    try:

        data, src = s.recvfrom(1024)
        LASTDHCPOPTIONS = parsedhcpoptions(data)

        log(f"dhcp recvfrom ok src={src} bytes={len(data)}")

        if len(data) < 240:

            log(f"dhcp rx too short len={len(data)} expected>=240")

        rx_xid = struct.unpack('!I', data[4:8])[0]

        log(f"dhcp rx xid=0x{rx_xid:08x} match={(rx_xid == xid)}")

        cookie = data[236:240]

        log(f"dhcp rx cookie={cookie.hex()} ok={(cookie == DHCPMAGIC)}")

        msgtype = None

        optspeek = data[240:]

        j = 0

        while j < len(optspeek):

            c = optspeek[j]

            if c == 255:
                break

            if c == 0:
                j += 1
                continue

            if j + 1 >= len(optspeek):
                break

            l = optspeek[j+1]

            if j + 2 + l > len(optspeek):
                break

            if c == 53 and l >= 1:

                msgtype = optspeek[j+2]

                break

            j += 2 + l

        log(f"dhcp rx msgtype={msgtype}")

    # if no response in time, log and return failure
    except socket.timeout:

        log(f"dhcpdiscover timeout iface='{iface}' after {DHCPTIMEOUT}s")

        log(f"dhcpdiscover timeout on '{iface}'")

        return None, None, None, None, None

    # extract the offered IP address (yiaddr) from the BOOTP header
    yiaddr = socket.inet_ntoa(data[16:20])

    log(f"dhcp yiaddr offered={yiaddr}")

    server = None

    router = None

    dnsservers = []

    opts = data[240:]

    i = 0

    while i < len(opts):

        code = opts[i]

        if code == 255:
            break

        if code == 0:
            i += 1
            continue

        if i + 1 >= len(opts):
            break

        length = opts[i+1]

        if i + 2 + length > len(opts):
            break

        if code == 3 and length >= 4 and not router:

            router = socket.inet_ntoa(opts[i+2:i+6])

            log(f"dhcp option router={router}")

        if code == 54 and length >= 4 and not server:

            server = socket.inet_ntoa(opts[i+2:i+6])

            log(f"dhcp option serverid={server}")

        if code == 6 and length >= 4:

            usable = length - (length % 4)

            for offset in range(0, usable, 4):

                nameserver = socket.inet_ntoa(opts[i+2+offset:i+6+offset])

                if nameserver not in dnsservers:

                    dnsservers.append(nameserver)

            log(f"dhcp option dns={dnsservers}")

        i += 2 + length

    log(f"dhcp parsed result yiaddr={yiaddr} router={router} server={server} dns={dnsservers}")

    return yiaddr, router, server, dnsservers, xid


def dhcprequest(iface, mac, xid, yiaddr, server):

    global LASTDHCPOPTIONS

    hardware = bytes(int(value, 16) for value in mac.split(':'))

    log(
        f"dhcp request start iface='{iface}' xid=0x{xid:08x} "
        f"address={yiaddr} server={server}"
    )

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    packetlistener = None

    try:

        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, iface.encode())

        route = None

        try:
            route = IPRoute()
            indices = route.link_lookup(ifname=iface)

            if indices:
                route.route(
                    'replace',
                    dst='255.255.255.255/32',
                    scope='link',
                    oif=indices[0]
                )
        finally:
            if route is not None:
                route.close()

        s.bind(('0.0.0.0', DHCPCLIENTPORT))
        packetlistener = dhcppacketlistener(iface)

        # Start with the RFC 2131 broadcast-reply preference.  If the server
        # remains silent, retry the same selecting-state request with the
        # broadcast flag clear.  Both packets are still sent to the link
        # broadcast address; the second mode supports DHCP servers that reply
        # directly to the offered MAC/IP, as common desktop clients permit.
        modes = (
            (True, 'broadcast-reply'),
            (False, 'direct-reply'),
        )

        for broadcast, mode in modes:
            packet = dhcprequestpacket(
                mac, xid, yiaddr, server, broadcast=broadcast
            )
            s.sendto(packet, ('255.255.255.255', DHCPSERVERPORT))
            log(
                f"dhcp request sent iface='{iface}' mode={mode} "
                f"dst=255.255.255.255:{DHCPSERVERPORT} bytes={len(packet)}"
            )
            deadline = time.monotonic() + (DHCPTIMEOUT / len(modes))

            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    log(f"dhcp request mode timeout iface='{iface}' mode={mode}")
                    break

                try:
                    data, source = receivedhcpreply(s, packetlistener, remaining)
                except socket.timeout:
                    log(f"dhcp request mode timeout iface='{iface}' mode={mode}")
                    break

                if len(data) < 240:
                    log(f"dhcp request ignored short reply src={source} bytes={len(data)}")
                    continue

                replyxid = struct.unpack('!I', data[4:8])[0]

                if replyxid != xid or data[28:34] != hardware:
                    log(
                        f"dhcp request ignored foreign reply src={source} "
                        f"xid=0x{replyxid:08x}"
                    )
                    continue

                options = parsedhcpoptions(data)
                messagetype = options.get(53, b'\x00')[:1]

                if messagetype == b'\x05':
                    LASTDHCPOPTIONS.update(options)
                    log(f"dhcp ack received iface='{iface}' mode={mode} src={source}")
                    return True

                if messagetype == b'\x06':
                    log(f"dhcp nak received iface='{iface}' mode={mode} src={source}")
                    return False

                log(
                    f"dhcp request ignored reply src={source} "
                    f"message_type={messagetype.hex() if messagetype else 'missing'}"
                )

        log(f"dhcp request timeout iface='{iface}' after {DHCPTIMEOUT}s")
        return False

    except Exception as error:

        log(f"dhcp request failed iface='{iface}' err='{error}'")
        return False

    finally:

        s.close()
        if packetlistener is not None:
            packetlistener.close()


def applyleasedns(router, dnsservers, automatic=True):

    if not automatic:
        log('retaining manually configured dns servers')
        return False
    return configuredns(dnsserversforlease(router, dnsservers))


def configdhcp(iface):

    # log that we are beginning the DHCP process for the interface
    log(f"starting dhcp on '{iface}'")
    writeconnectionstate(iface, False)

    mac = upinterface(iface)

    if not mac:
        return

    # allow virtual NIC to settle (VMware requires this)
    time.sleep(1)

    attempts = 3
    
    yiaddr = None
    
    router = None
    
    server = None

    dnsservers = []

    xid = None

    for _ in range(attempts):

        yiaddr, router, server, dnsservers, xid = dhcptransaction(iface, mac)

        if yiaddr and router:
            break

        time.sleep(2)

    if not yiaddr or not router:
        
        log(f"dhcp failed on '{iface}'")
        
        return

    if server:

        ok = dhcprequest(iface, mac, xid, yiaddr, server)

        if not ok:

            log(f"dhcprequest failed on '{iface}'")

            return

    # log the offered IP, router (gateway), and server id if present
    if server:

        log(f"got address {yiaddr} gw {router} from {server}")

    else:

        log(f"got address {yiaddr} gw {router}")

    # apply the obtained address with /24 mask and router as gateway
    configstatic(iface, yiaddr, '24', router)

    applyleasedns(
        router, dnsservers,
        hostnetworksettings()['dns'] == 'automatic')

    if iswirelessname(iface):
        connectionname = connectedwirelessname(iface)
    else:
        connectionname = dhcpoptiontext(LASTDHCPOPTIONS, 15)

    connectionid = (
        '' if iswirelessname(iface)
        else ethernetconnectionid(iface, router, server, mac)
    )
    writeconnectionstate(
        iface, True, connectionname, f'{yiaddr}/24', router, server, mac,
        connectionid=connectionid)

    # report that DHCP configuration phase has completed
    log(f"dhcp configuration complete for '{iface}'")


def configstatic(iface, addr, mask, gw):

    # open a netlink handle to configure address and routes
    ip = IPRoute()

    # resolve the interface index from its name
    idxs = ip.link_lookup(ifname=iface)

    # if the interface cannot be found, close and report
    if not idxs:

        # close the netlink handle before returning
        ip.close()

        # log that static configuration cannot proceed
        log(f"interface '{iface}' not found for static config")

        # return to caller without applying config
        return

    # pick the first matching interface index
    idx = idxs[0]

    # try to assign address and default route
    try:

        # add the IPv4 address/mask onto the interface
        ip.addr('replace', index=idx, address=addr, mask=int(mask))

        # add a default route via the provided gateway
        ip.route('replace', dst='default', gateway=gw)

        # log that the static configuration was successful
        log(f"configured static ip {addr}/{mask} gw {gw} on '{iface}'")

    # catch any failure from address/route operations and log
    except Exception as e:

        # log the configuration error reason
        log(f"error setting static config on '{iface}' {e}")

    # make sure the netlink handle is closed either way
    finally:

        # close the IPRoute instance
        ip.close()


# dns functions
def configuredns(servers):

    validated = []

    for server in servers or []:

        try:

            value = socket.inet_ntoa(socket.inet_aton(str(server)))

        except OSError:

            continue

        if value not in validated:

            validated.append(value)

    if not validated:

        log("dhcp supplied no valid dns servers")

        return False

    os.makedirs(NETDIR, mode=0o755, exist_ok=True)

    temporary = f"{DNSCONF}.temporary-{os.getpid()}"

    payload = ''.join(f"nameserver {server}\n" for server in validated[:3])

    payload += "options timeout:2 attempts:3\n"

    descriptor = None

    try:

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)

        descriptor = os.open(temporary, flags, 0o644)

        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:

            descriptor = None

            stream.write(payload)

            stream.flush()

            os.fsync(stream.fileno())

        os.replace(temporary, DNSCONF)

        os.chmod(DNSCONF, 0o644)

        log(f"configured dns servers {validated[:3]} in {DNSCONF}")

        return True

    except Exception as e:

        log(f"could not configure dns {e}")

        return False

    finally:

        if descriptor is not None:

            os.close(descriptor)

        try:

            os.unlink(temporary)

        except OSError:

            pass


def loaddns():

    servers = []

    try:

        # open dns config
        with open(DNSCONF) as f:

            # parse nameserver lines
            for line in f:

                line = line.strip()

                if not line or line.startswith('#'):
                    continue

                parts = line.split()

                if parts[0].lower() == 'nameserver' and len(parts) >= 2:
                    servers.append(parts[1])

    except FileNotFoundError:

        # dns config not found
        log(f"loaddns missing {DNSCONF}")

    except PermissionError:

        # permission denied
        log(f"loaddns permission denied {DNSCONF}")

    except Exception as e:

        # other error
        log(f"loaddns error {e}")

    return servers


def makednspacket(host):

    try:

        # DNS names are canonicalised before they are put on the wire.  This
        # keeps the response validator's comparison unambiguous and prevents
        # malformed labels from escaping the bounds of a DNS question.
        host = normalizednshost(host)

        # build dns header
        ident = secrets.randbits(16)
        flags = 0x0100
        qdcount = 1
        ancount = 0
        nscount = 0
        arcount = 0
        header = struct.pack('!HHHHHH', ident, flags, qdcount, ancount, nscount, arcount)

        # build qname
        qname = b''

        for part in host.split('.'):

            qname += struct.pack('B', len(part))
            qname += part.encode('ascii')

        qname += b'\x00'

        # set qtype and qclass (A, IN)
        question = struct.pack('!HH', 1, 1)

        # combine header and question
        packet = header + qname + question

        if DEBUGNETWORK: log(f"makednspacket id={ident} len={len(packet)}")
        return packet

    except Exception as e:

        # packet build error
        if DEBUGNETWORK: log(f"makednspacket error {e}")
        return b''


def normalizednshost(host):

    value = str(host or '').strip().rstrip('.')

    if not value or len(value) > 253:
        raise ValueError('invalid dns name length')

    try:
        value = value.encode('idna').decode('ascii').lower()
    except (UnicodeError, UnicodeDecodeError) as error:
        raise ValueError('invalid international dns name') from error

    if len(value) > 253:
        raise ValueError('encoded dns name is too long')

    for label in value.split('.'):
        if not label or len(label) > 63:
            raise ValueError('invalid dns label length')
        if not label[0].isalnum() or not label[-1].isalnum():
            raise ValueError('dns label must begin and end with a letter or digit')
        if any(not (character.isalnum() or character == '-') for character in label):
            raise ValueError('invalid dns label character')

    return value


def _parsednsname(data, offset):

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError('dns packet must be bytes')

    packet = bytes(data)
    cursor = int(offset)
    returnoffset = None
    labels = []
    visited = set()
    jumps = 0

    while True:
        if cursor < 0 or cursor >= len(packet):
            raise ValueError('dns name is out of bounds')

        length = packet[cursor]

        if length == 0:
            if returnoffset is None:
                returnoffset = cursor + 1
            break

        if (length & 0xC0) == 0xC0:
            if cursor + 1 >= len(packet):
                raise ValueError('dns compression pointer is truncated')
            pointer = ((length & 0x3F) << 8) | packet[cursor + 1]
            if pointer >= len(packet) or pointer in visited:
                raise ValueError('dns compression pointer loops or escapes packet')
            visited.add(pointer)
            jumps += 1
            if jumps > 32:
                raise ValueError('too many dns compression pointers')
            if returnoffset is None:
                returnoffset = cursor + 2
            cursor = pointer
            continue

        if length & 0xC0 or length > 63:
            raise ValueError('invalid dns label encoding')

        cursor += 1
        end = cursor + length
        if length == 0 or end > len(packet):
            raise ValueError('dns label is truncated')

        try:
            label = packet[cursor:end].decode('ascii').lower()
        except UnicodeDecodeError as error:
            raise ValueError('dns label is not ascii') from error

        labels.append(label)
        if len('.'.join(labels)) > 253:
            raise ValueError('decoded dns name is too long')
        cursor = end

    return '.'.join(labels), returnoffset


def dnsquestion(packet):

    if len(packet) < 12:
        raise ValueError('dns question has a short header')

    ident, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        '!HHHHHH', packet[:12]
    )

    if flags & 0x8000 or qdcount != 1 or ancount or nscount or arcount:
        raise ValueError('dns query header is not a single standard question')

    name, offset = _parsednsname(packet, 12)
    if offset + 4 != len(packet):
        raise ValueError('dns question has trailing or truncated fields')

    qtype, qclass = struct.unpack('!HH', packet[offset:offset + 4])
    return ident, name, qtype, qclass


def _dnsresponsemetadata(data, query=None):

    if len(data) < 12 or len(data) > DNSMAXRESP:
        raise ValueError('dns response size is invalid')

    ident, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        '!HHHHHH', data[:12]
    )

    if not (flags & 0x8000) or ((flags >> 11) & 0xF) != 0 or flags & 0x0200:
        raise ValueError('dns response has invalid qr, opcode, or truncation flags')
    if qdcount != 1 or ancount + nscount + arcount > 256:
        raise ValueError('dns response has invalid section counts')

    questionname, offset = _parsednsname(data, 12)
    if offset + 4 > len(data):
        raise ValueError('dns response question is truncated')
    qtype, qclass = struct.unpack('!HH', data[offset:offset + 4])
    offset += 4

    if query is not None:
        expectedid, expectedname, expectedtype, expectedclass = dnsquestion(query)
        if (
            ident != expectedid or
            questionname != expectedname or
            qtype != expectedtype or
            qclass != expectedclass
        ):
            raise ValueError('dns response does not match the outstanding question')

    records = []
    for section, count in (
        ('answer', ancount),
        ('authority', nscount),
        ('additional', arcount),
    ):
        for _ in range(count):
            owner, offset = _parsednsname(data, offset)
            if offset + 10 > len(data):
                raise ValueError('dns resource record header is truncated')
            recordtype, recordclass, ttl, rdlength = struct.unpack(
                '!HHIH', data[offset:offset + 10]
            )
            offset += 10
            dataoffset = offset
            offset += rdlength
            if offset > len(data):
                raise ValueError('dns resource record data is truncated')
            records.append((
                section,
                owner,
                recordtype,
                recordclass,
                ttl,
                dataoffset,
                rdlength,
            ))

    if offset != len(data):
        raise ValueError('dns response contains trailing data')

    return flags & 0xF, questionname, qtype, qclass, records


def validatednsresponse(data, query):

    try:
        _dnsresponsemetadata(data, query=query)
        return True
    except Exception as error:
        if DEBUGNETWORK:
            log(f"validatednsresponse rejected packet {error}")
        return False


def senddns(packet, servers):

    if not packet:
        if DEBUGNETWORK: log(f"senddns empty packet")
        return b''

    if not servers:
        if DEBUGNETWORK: log(f"senddns no servers")
        return b''

    for ns in servers:

        if DEBUGNETWORK: log(f"senddns try ns={ns}")

        s = None

        try:

            # Only configured IPv4 literals are accepted as recursive
            # resolvers.  Connecting the UDP socket makes the kernel discard
            # datagrams from every other source address and port.
            socket.inet_pton(socket.AF_INET, str(ns))

            # create udp socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # set timeout
            s.settimeout(DNSTIMEOUT)

            # bind ephemeral port
            s.bind(('', 0))
            if DEBUGNETWORK: log(f"senddns bound local={s.getsockname()}")

            # connect and send query from an OS-selected random source port
            s.connect((ns, DNSPORT))
            s.send(packet)

            deadline = time.monotonic() + DNSTIMEOUT
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise socket.timeout
                s.settimeout(remaining)
                data = s.recv(DNSMAXRESP)
                if DEBUGNETWORK: log(f"senddns recv len={len(data)}")
                if validatednsresponse(data, packet):
                    return data

        except socket.timeout:

            # dns timeout
            if DEBUGNETWORK: log(f"senddns timeout ns={ns}")

        except PermissionError:

            # permission denied for socket
            if DEBUGNETWORK: log(f"senddns permission denied")

        except Exception as e:

            # other socket error
            if DEBUGNETWORK: log(f"senddns error ns={ns} {e}")

        finally:

            # close socket if opened
            if s:
                s.close()
    if DEBUGNETWORK: log(f"senddns all attempts failed")
    return b''


def parsename(data, offset):

    try:
        return _parsednsname(data, offset)
    except Exception as error:
        if DEBUGNETWORK: log(f"parsename error start={offset} {error}")
        return '', offset


def parsednsanswer(data, query=None):

    try:

        rcode, questionname, qtype, qclass, records = _dnsresponsemetadata(
            data,
            query=query,
        )

        if rcode != 0 or qtype != 1 or qclass != 1:
            if DEBUGNETWORK: log(f"parsednsanswer unusable rcode={rcode} qtype={qtype} qclass={qclass}")
            return ''

        # Follow only CNAMEs anchored at the exact question.  Unrelated A
        # records in the answer or additional sections are never trusted.
        acceptednames = {questionname}
        for _ in range(len(records) + 1):
            changed = False
            for section, owner, typ, cls, ttl, dataoffset, rdlen in records:
                if section != 'answer' or cls != 1 or typ != 5 or owner not in acceptednames:
                    continue
                alias, aliasend = _parsednsname(data, dataoffset)
                if aliasend != dataoffset + rdlen or not alias:
                    raise ValueError('invalid cname record')
                if alias not in acceptednames:
                    acceptednames.add(alias)
                    changed = True
            if not changed:
                break

        for section, owner, typ, cls, ttl, dataoffset, rdlen in records:
            if (
                section == 'answer' and
                owner in acceptednames and
                typ == 1 and cls == 1 and rdlen == 4
            ):
                ip = socket.inet_ntoa(data[dataoffset:dataoffset + rdlen])
                if DEBUGNETWORK: log(f"parsednsanswer A {ip}")
                return ip

        if DEBUGNETWORK: log(f"parsednsanswer no matching A record")
        return ''

    except Exception as e:

        # parsing error
        if DEBUGNETWORK: log(f"parsednsanswer error {e}")
        return ''


def resolvename(host):

    if DEBUGNETWORK: log(f"resolvename host={host}")

    try:

        # return literal ipv4
        socket.inet_aton(host)
        if DEBUGNETWORK: log(f"resolvename literal ipv4 {host}")
        return host

    except Exception:

        # not an ipv4 literal
        if DEBUGNETWORK: log(f"resolvename lookup dns")

    # load servers
    servers = loaddns()

    if not servers:

        # no nameservers available
        if DEBUGNETWORK: log(f"resolvename no nameservers")
        raise socket.gaierror

    # build query packet
    packet = makednspacket(host)

    if not packet:

        # could not build packet
        if DEBUGNETWORK: log(f"resolvename packet build failed")
        raise socket.gaierror

    # send query
    data = senddns(packet, servers)

    if not data:

        # no response from any server
        if DEBUGNETWORK: log(f"resolvename no response")
        raise socket.gaierror

    # parse answer
    ip = parsednsanswer(data, query=packet)

    if ip:

        if DEBUGNETWORK: log(f"resolvename {host} -> {ip}")
        return ip

    # no usable answer
    if DEBUGNETWORK: log(f"resolvename no a record")
    raise socket.gaierror


# url helper functions
def hostfrom(raw):

    try:

        # parse and extract hostname or fall back to raw
        p = urllib.parse.urlparse(raw)
        host = p.hostname or raw
        return host

    except Exception as e:

        # parsing failure
        log(f"hostfrom error {e}")
        return raw


def parseurl(raw):

    try:

        # ensure scheme present for parse
        val = raw if '://' in raw else 'http://' + raw

        # parse url components
        p = urllib.parse.urlparse(val)

        # scheme
        scheme = (p.scheme or 'http').lower()

        # host
        host = p.hostname or ''

        # port
        if p.port:
            port = p.port
        else:
            port = 443 if scheme == 'https' else 80

        # path and query
        path = p.path or '/'
        if p.query:
            path += '?' + p.query

        return scheme, host, port, path

    except Exception as e:

        # parsing failure
        log(f"parseurl error {e}")
        return '', '', 0, ''


# socket helper functions
def opentcp(ip, port, timeout=None):

    s = None

    try:

        # create tcp socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # set timeout
        s.settimeout(timeout or NETTIMEOUT)

        # connect
        s.connect((ip, port))

        return s

    except PermissionError:

        # permission error
        log(f"opentcp permission denied")
        if s:
            s.close()
        return None

    except Exception as e:

        # connection error
        log(f"opentcp error {ip}:{port} {e}")
        if s:
            s.close()
        return None


def opentls(sock, host, cafile=None, allow_insecure=False):

    try:

        # create context
        ctx = ssl.create_default_context()

        # load custom CA if present or explicit
        usefile = cafile or CACERTSFILE

        if os.path.exists(usefile):

            # load custom bundle
            ctx.load_verify_locations(cafile=usefile)

        # optionally allow insecure
        if allow_insecure:

            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        # wrap
        tls = ctx.wrap_socket(sock, server_hostname=host)

        return tls

    except ssl.SSLError as e:

        # tls error
        log(f"opentls ssl error {e}")
        sock.close()
        return None

    except Exception as e:

        # other error
        log(f"opentls error {e}")
        sock.close()
        return None


def configureinterface(iface):

    log(f"using interface '{iface}'")
    conf = os.path.join(NETDIR, f'{iface}.txt')

    if os.path.exists(conf):
        cfg = getconfig(conf)
        log(f"using interface configuration {conf}")
    elif os.path.exists(GLOBALCONF):
        cfg = getconfig(GLOBALCONF)
        log(f"using global network configuration {GLOBALCONF}")
    else:
        cfg = {'dhcp': 'true'}
        log(f"no interface configuration found; defaulting '{iface}' to dhcp")

    if cfg.get('dhcp', '').lower() == 'true':
        configdhcp(iface)
    else:
        configstatic(
            iface,
            cfg.get('address', ''),
            cfg.get('netmask', ''),
            cfg.get('gateway', '')
        )
        connectionname = connectedwirelessname(iface) if iswirelessname(iface) else ''
        address = cfg.get('address', '')
        netmask = cfg.get('netmask', '')
        publishedaddress = address + ('/' + netmask if address and netmask else '')
        connectionid = (
            '' if iswirelessname(iface)
            else ethernetconnectionid(iface, cfg.get('gateway', ''), '', '')
        )
        writeconnectionstate(
            iface, True, connectionname, publishedaddress, cfg.get('gateway', ''),
            connectionid=connectionid)

    log(f"cycle complete\n\n")


def usablecurrentinterface(links):

    state = loadjson(CONNECTIONSTATE, {})

    if not bool(state.get('connected')):
        return ''

    current = str(state.get('interface') or '').strip()

    for link in links:
        if link['name'] == current and linkready(link):
            return current

    return ''


def configuredinterface(links):

    preferred = hostnetworksettings()['interface']
    if not preferred:
        return None
    return next((link for link in links if link.get('name') == preferred), None)


def configuredwirelesslinks(links):

    candidates = [
        link for link in links
        if link.get('wireless') and wirelessconfigurationtext(wirelesssettings(link['name']))
    ]
    candidates.sort(key=lambda item: (item.get('index', 0), item.get('name', '')))
    return candidates


def readywirelessinterface(links, candidates):

    names = {link['name'] for link in candidates}

    for link in links:
        if link['name'] in names and linkready(link):
            log(
                f"wireless association ready interface='{link['name']}' "
                f"operstate={link['operstate']}"
            )
            return link['name']

    return None


def publishinitialstate():

    state = loadjson(CONNECTIONSTATE, {})
    interface = str(state.get('interface') or '').strip()
    if INITIALSTATEINTERFACE.fullmatch(interface) is None:
        interface = ''
    initial = {
        'format': 1,
        'connected': bool(state.get('connected')),
        'interface': interface,
        'completed': max(1, int(time.time())),
    }
    writeinitialstate(initial)
    print(
        'T1OS_NETWORK_INITIAL=' + json.dumps(
            initial, sort_keys=True, separators=(',', ':'),
        ),
        flush=True,
    )
    log(
        f"initial connection attempt complete connected={initial['connected']} "
        f"interface='{initial['interface']}'"
    )


def performwirelessscan():

    links = linkinventory()
    wireless = [link for link in links if link.get('wireless')]
    activatewirelessinterfaces(wireless)
    merged = {}

    for link in wireless:
        for network in scanwireless(link['name']):
            previous = merged.get(network['ssid'])
            if previous is None or network['signal'] > previous['signal']:
                merged[network['ssid']] = network

    networks = sorted(
        merged.values(),
        key=lambda item: (-item['signal'], item['ssid'].casefold()),
    )
    atomicjson(WIRELESSSCANSTATE, {
        'networks': networks,
        'updated': int(time.time()),
    })
    log(f"wireless scan published {len(networks)} network(s)")


def consumerequest(path):

    try:
        os.unlink(path)
        return True
    except OSError:
        return False


# core loop
def main(force=False):

    # Network configuration is conditional on a successfully committed and
    # verified default-deny host firewall.  Failure leaves every external
    # interface down instead of silently booting with an open attack surface.
    if not ensurehostfirewall():
        quarantinenetworkinterfaces()
        writeconnectionstate('', False)
        return

    initiallinks = linkinventory()
    activatewiredinterfaces(initiallinks)
    activatewirelessinterfaces(initiallinks)
    links = linkinventory()
    current = usablecurrentinterface(links)
    preferredlink = configuredinterface(links)
    preferred = preferredlink['name'] if preferredlink else ''
    if preferredlink and preferredlink.get('wireless'):
        ensurewireless(preferred)
    wiredready = [
        link for link in links
        if not link.get('wireless') and linkready(link)
    ]

    # Keep a healthy connection untouched.  A ready Ethernet link is the sole
    # exception: it always pre-empts an existing Wi-Fi connection.
    if current and not force:
        currentlink = next((link for link in links if link['name'] == current), None)
        preferredready = bool(preferredlink and linkready(preferredlink))
        if preferred and current != preferred and not preferredready:
            return
        if (
            (not preferred or current == preferred) and currentlink and
            (preferred or not currentlink.get('wireless') or not wiredready)
        ):
            return

    iface = preferred if preferredlink and linkready(preferredlink) else None
    if not iface:
        iface = wiredready[0]['name'] if wiredready else None

    if iface:
        configureinterface(iface)
        return

    wirelesslinks = configuredwirelesslinks(links)
    if preferred:
        wirelesslinks.sort(key=lambda item: item.get('name') != preferred)

    # Begin configured Wi-Fi association while Ethernet auto-negotiates. The
    # former serial path waited the full Ethernet settling interval before it
    # even launched the wireless engine, making Wi-Fi-only boot unnecessarily
    # late. Whichever configured link becomes usable first may establish the
    # initial connection; the service still promotes Ethernet on a later poll.
    wirelesslinks = [
        link for link in wirelesslinks
        if ensurewireless(link['name'])
    ]

    if not iface:
        deadline = time.monotonic() + NETTIMEOUT

        while time.monotonic() < deadline:
            latest = linkinventory()
            activatewiredinterfaces(latest)
            activatewirelessinterfaces(latest)
            iface = next((
                link['name'] for link in latest
                if not link.get('wireless') and linkready(link)
            ), None)

            if iface:
                break

            wireless = readywirelessinterface(latest, wirelesslinks)

            if wireless:
                configureinterface(wireless)
                return

            time.sleep(0.5)

    if iface:
        configureinterface(iface)
        return

    log("no usable Ethernet or configured Wi-Fi interface found")
    writeconnectionstate('', False)


# execute main
if __name__ == '__main__':

    ensurenetworkruntime()
    initialattempt = True

    while True:
        scanrequested = consumerequest(WIRELESSSCANREQUEST)
        reconfigure = consumerequest(RECONFIGUREREQUEST)

        if scanrequested:
            performwirelessscan()

        try:
            main(force=reconfigure)
        finally:
            if initialattempt:
                publishinitialstate()
                initialattempt = False

        # Poll often enough to prefer newly connected Ethernet and to service
        # Settings requests without repeatedly re-running DHCP on a healthy
        # connection.
        for _ in range(50):
            if os.path.exists(WIRELESSSCANREQUEST) or os.path.exists(RECONFIGUREREQUEST):
                break
            time.sleep(0.1)
