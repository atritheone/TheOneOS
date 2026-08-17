#!/usr/bin/env python3

"""Focused adversarial tests for the T1OS userspace DNS resolver."""

from __future__ import annotations

import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import importlib.util
import os
import pathlib
import socket
import struct
import sys
import tempfile
import types


# This test imports a target-runtime module.  Refuse native Windows before the
# module loader is reached: T1OS absolute paths such as "/the one/..." would be
# interpreted relative to the Windows system drive by host Python.
if os.name == 'nt':
    raise SystemExit(
        'refusing to import T1OS runtime code with native Windows Python; '
        'run this test in an isolated Linux environment'
    )

sys.dont_write_bytecode = True


ROOT = pathlib.Path(__file__).resolve().parents[1]
NETWORK_SOURCE = ROOT / 'source' / 'build software' / 'network' / 'network.py'


def loadnetwork():
    sys.path.insert(0, str(ROOT / 'source' / 'build software'))
    pyroute2 = types.ModuleType('pyroute2')
    pyroute2.IPRoute = object
    goddesspackage = types.ModuleType('GODDESS')
    goddess = types.ModuleType('GODDESS.GODDESS')
    goddess.formatlog = lambda component, message: f'{component}: {message}'
    goddess.popenisolated = None
    sys.modules['pyroute2'] = pyroute2
    sys.modules['GODDESS'] = goddesspackage
    sys.modules['GODDESS.GODDESS'] = goddess
    spec = importlib.util.spec_from_file_location('t1os_network_security_test', NETWORK_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def responsefor(query, address='203.0.113.7', *, ident=None, flags=0x8180, owner=b'\xc0\x0c'):
    queryident = struct.unpack('!H', query[:2])[0]
    header = struct.pack(
        '!HHHHHH',
        queryident if ident is None else ident,
        flags,
        1,
        1,
        0,
        0,
    )
    answer = owner + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton(address)
    return header + query[12:] + answer


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    network = loadnetwork()

    runtimelogfile = network.LOGFILE
    runtimeos = network.os
    with tempfile.TemporaryDirectory(prefix='t1os-network-host-guard-') as directory:
        guardedlog = pathlib.Path(directory) / 'network.py.log'
        try:
            network.os = types.SimpleNamespace(name='nt')
            network.LOGFILE = str(guardedlog)
            network.log('simulated native Windows logging safety probe')
        finally:
            network.os = runtimeos
            network.LOGFILE = runtimelogfile
        require(not guardedlog.exists(), 'native Windows execution wrote a T1OS runtime log')

    # The remaining cases intentionally exercise error logging. Keep those
    # diagnostics off every development host, including privileged Linux CI.
    network.LOGFILE = os.devnull

    packets = [network.makednspacket('Example.COM.') for _ in range(96)]
    require(all(packets), 'valid DNS names must produce queries')
    require(len({packet[:2] for packet in packets}) > 80, 'DNS IDs must be unpredictable per query')
    require(network.dnsquestion(packets[0])[1:] == ('example.com', 1, 1), 'query must be canonical')
    require(network.makednspacket('../bad') == b'', 'malformed host names must be refused')

    query = packets[0]
    good = responsefor(query)
    require(network.validatednsresponse(good, query), 'matching response was rejected')
    require(network.parsednsanswer(good, query=query) == '203.0.113.7', 'matching A answer was not returned')

    queryident = struct.unpack('!H', query[:2])[0]
    wrongid = responsefor(query, ident=queryident ^ 0xFFFF)
    require(not network.validatednsresponse(wrongid, query), 'mismatched transaction ID was accepted')

    otherquery = network.makednspacket('attacker.example')
    wrongquestion = responsefor(
        otherquery,
        ident=queryident,
    )
    require(not network.validatednsresponse(wrongquestion, query), 'mismatched question was accepted')
    require(
        not network.validatednsresponse(responsefor(query, flags=0x8380), query),
        'truncated response was accepted',
    )
    require(
        network.parsednsanswer(responsefor(query, owner=b'\x08attacker\x07example\x00'), query=query) == '',
        'unrelated answer owner was accepted',
    )

    pointerloop = b'\x00' * 12 + b'\xc0\x0c'
    require(network.parsename(pointerloop, 12) == ('', 12), 'compression loop must fail closed')

    class FakeSocket:
        instances = []

        def __init__(self, *args):
            self.connected = None
            self.sent = None
            self.responses = [wrongid, good]
            self.closed = False
            self.instances.append(self)

        def settimeout(self, timeout):
            require(timeout > 0, 'resolver timeout must remain positive')

        def bind(self, address):
            require(address == ('', 0), 'resolver must request an ephemeral source port')

        def getsockname(self):
            return ('0.0.0.0', 49152)

        def connect(self, address):
            self.connected = address

        def send(self, packet):
            self.sent = packet

        def recv(self, maximum):
            require(maximum == network.DNSMAXRESP, 'resolver receive bound changed')
            return self.responses.pop(0)

        def close(self):
            self.closed = True

    originalsocket = network.socket.socket
    try:
        network.socket.socket = FakeSocket
        received = network.senddns(query, ['192.0.2.53'])
    finally:
        network.socket.socket = originalsocket

    fake = FakeSocket.instances[0]
    require(received == good, 'resolver did not skip a spoofed packet')
    require(fake.connected == ('192.0.2.53', 53), 'resolver socket was not source-bound with connect')
    require(fake.sent == query and fake.closed, 'resolver socket lifecycle was incomplete')

    with tempfile.TemporaryDirectory(prefix='t1os-network-secret-') as directory:
        settingspath = pathlib.Path(directory) / 'wireless.txt'
        credential = 'network.wireless.' + ('a' * 24)
        settingspath.write_text(
            'ssid=Home Network\nsecurity=wpa3\ncredential=' + credential + '\n',
            encoding='utf-8',
        )
        originalnetdir = network.NETDIR
        originalwireless = network.WIRELESSCONF
        originalgetsecret = network.service_secret_get
        originallog = network.log
        try:
            network.NETDIR = directory
            network.WIRELESSCONF = str(settingspath)
            network.log = lambda *args, **kwargs: None
            network.service_secret_get = lambda name, timeout=3.0: (
                'correct horse battery staple' if name == credential else ''
            )
            loaded = network.wirelesssettings('wlan0')
            require(
                loaded.get('passphrase') == 'correct horse battery staple',
                'wireless credential reference was not resolved through the broker',
            )
            settingspath.write_text(
                'ssid=Home Network\nsecurity=wpa2\npassphrase=plaintext-is-forbidden\n',
                encoding='utf-8',
            )
            require(
                network.wirelesssettings('wlan0') == {},
                'legacy plaintext wireless credential was accepted',
            )
            settingspath.write_text(
                'ssid=Home Network\nsecurity=wpa2\ncredential=authentication.master\n',
                encoding='utf-8',
            )
            require(
                network.wirelesssettings('wlan0') == {},
                'cross-service credential reference was accepted',
            )
        finally:
            network.NETDIR = originalnetdir
            network.WIRELESSCONF = originalwireless
            network.service_secret_get = originalgetsecret
            network.log = originallog

    class FakeNFTables:
        def __init__(self):
            self.commands = []
            self.chains = []
            self.rules = []
            self.closed = False

        def get_tables(self):
            return [{'attrs': [('NFTA_TABLE_NAME', network.FIREWALLTABLE)]}]

        def get_chains(self):
            return [
                {'attrs': [
                    ('NFTA_CHAIN_TABLE', network.FIREWALLTABLE),
                    ('NFTA_CHAIN_NAME', name['name']),
                    ('NFTA_CHAIN_POLICY', name['policy']),
                ]}
                for name in self.chains
            ]

        def get_rules(self):
            return [
                {'attrs': [
                    ('NFTA_RULE_TABLE', item['table']),
                    ('NFTA_RULE_CHAIN', item['chain']),
                ]}
                for item in self.rules
            ]

        def begin(self):
            self.commands.append(('begin', {}))

        def commit(self):
            self.commands.append(('commit', {}))

        def table(self, operation, **kwargs):
            self.commands.append((f'table:{operation}', kwargs))

        def chain(self, operation, **kwargs):
            self.commands.append((f'chain:{operation}', kwargs))
            if operation == 'add':
                self.chains.append(dict(kwargs))

        def rule(self, operation, **kwargs):
            self.commands.append((f'rule:{operation}', kwargs))
            if operation == 'add':
                self.rules.append(dict(kwargs))

        def close(self):
            self.closed = True

    nft = FakeNFTables()
    require(network.applyhostfirewall(lambda: nft), 'default-deny firewall did not apply')
    require(nft.closed, 'firewall netlink socket was not closed')
    require(
        ('table:del', {'name': network.FIREWALLTABLE}) in nft.commands,
        'existing owned firewall table was not atomically replaced',
    )
    chaincommands = [kwargs for command, kwargs in nft.commands if command == 'chain:add']
    policies = {item['name']: item['policy'] for item in chaincommands}
    require(
        policies == {'input': 0, 'forward': 0, 'output': 1},
        'firewall base-chain policies are not default-deny inbound/forward',
    )
    rules = [kwargs for command, kwargs in nft.commands if command == 'rule:add']
    require(len(rules) == 5, 'firewall must expose only five explicit inbound admission rules')
    require(
        all(rule['chain'] == 'input' for rule in rules),
        'firewall accidentally added an outbound or forwarding admission rule',
    )
    require(
        network.verifyhostfirewall(lambda: nft),
        'firewall verification did not recognize the exact committed policy',
    )
    nft.rules.pop()
    require(
        not network.verifyhostfirewall(lambda: nft),
        'firewall verification accepted a missing admission rule',
    )

    print('network security tests passed')


if __name__ == '__main__':
    main()
