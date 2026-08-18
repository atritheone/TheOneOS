#!/usr/bin/env python3

"""Linux-side encoding gate for every T1OS nftables admission rule."""

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
import sys
import types


if os.name != 'posix':
    raise SystemExit(
        'refusing to import T1OS runtime code outside an isolated Linux environment'
    )

sys.dont_write_bytecode = True


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'source' / 'software' / 'python' / 'lib' / 'python3.14' / 'site-packages'))
sys.path.insert(0, str(ROOT / 'source' / 'build software'))

goddesspackage = types.ModuleType('GODDESS')
goddess = types.ModuleType('GODDESS.GODDESS')
goddess.formatlog = lambda component, message: f'{component}: {message}'
goddess.popenisolated = None
sys.modules['GODDESS'] = goddesspackage
sys.modules['GODDESS.GODDESS'] = goddess

source = ROOT / 'source' / 'build software' / 'network' / 'network.py'
spec = importlib.util.spec_from_file_location('t1os_network_firewall_linux_test', source)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)

from pyroute2.netlink.nfnetlink.nftsocket import nft_rule_msg  # noqa: E402


groups = (
    (network._nftmetacompare(6, b'lo\0'), network._nftverdict()),
    (network._nftestablishedrelated(), network._nftverdict()),
    (network._nftmetacompare(16, bytes((socket.IPPROTO_ICMP,))), network._nftverdict()),
    (network._nftmetacompare(16, bytes((socket.IPPROTO_ICMPV6,))), network._nftverdict()),
    (network._nftdhcpreply(), network._nftverdict()),
)

for rulegroups in groups:
    expressions = []
    for group in rulegroups:
        expressions.extend(group)
    message = nft_rule_msg()
    message['attrs'] = [
        ('NFTA_RULE_TABLE', network.FIREWALLTABLE),
        ('NFTA_RULE_CHAIN', 'input'),
        ('NFTA_RULE_EXPRESSIONS', expressions),
    ]
    message.encode()
    if not message.data:
        raise SystemExit('nftables rule encoded to an empty message')

if os.environ.get('T1OS_TEST_APPLY_FIREWALL') == '1':
    if os.environ.get('T1OS_TEST_ISOLATED_LINUX') != '1':
        raise SystemExit('firewall mutation requires T1OS_TEST_ISOLATED_LINUX=1')
    try:
        if os.stat('/proc/self/ns/net').st_ino == os.stat('/proc/1/ns/net').st_ino:
            raise SystemExit('firewall mutation requires a private network namespace')
    except FileNotFoundError as error:
        raise SystemExit('cannot verify a private Linux network namespace') from error
    if not network.applyhostfirewall():
        raise SystemExit('nftables policy did not apply inside the isolated network namespace')

print('network firewall Linux encoding tests passed')
