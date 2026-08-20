[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$source = Join-Path $projectRoot 'source\entry\recoveryauth\recoveryauth.c'
$brokerDirectory = Join-Path $projectRoot 'source\build software'

foreach ($required in @($source, (Join-Path $brokerDirectory 'broker\broker.py'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Recovery authenticator test input is missing: $required"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to test the recovery authenticator.'
}

$wslSource = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $source | Select-Object -First 1)).Trim()
$wslBrokerDirectory = ([string](& wsl.exe -d Ubuntu --exec wslpath -a $brokerDirectory | Select-Object -First 1)).Trim()
if (-not $wslSource -or -not $wslBrokerDirectory) {
    throw 'Could not translate recovery authenticator test paths for WSL.'
}

$test = @'
set -euo pipefail
source_file=$1
broker_directory=$2
work=$(mktemp -d /var/tmp/t1os-recoveryauth.XXXXXX)
cleanup() {
    rm -rf -- "$work"
}
trap cleanup EXIT

cc -std=c11 -O2 -Wall -Wextra -Werror -D_FORTIFY_SOURCE=2 \
    -fstack-protector-strong -Wl,-z,relro,-z,now \
    -o "$work/recoveryauth" "$source_file" \
    -Wl,-l:libargon2.so.1 -lcrypto

PYTHONDONTWRITEBYTECODE=1 python3 -B - "$broker_directory" "$work" <<'PY'
import base64
import hashlib
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from broker import broker

work = Path(sys.argv[2])
password = 'recovery secret'
salt = bytes(range(16))

representations = {
    'argon2': broker.hash_password(password),
    'scrypt': (
        't1auth$v=1$kdf=scrypt$n=32768$r=8$p=1'
        f'$salt={base64.urlsafe_b64encode(salt).rstrip(b"=").decode()}'
        f'$hash={base64.urlsafe_b64encode(hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)).rstrip(b"=").decode()}'
    ),
    'legacy': (
        'sha256$100000$' + salt.hex() + '$' +
        hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000, dklen=32).hex()
    ),
}
for name, representation in representations.items():
    path = work / f'{name}.txt'
    path.write_text(f'Architect:{representation}\n', encoding='utf-8')
    path.chmod(0o600)
legacy_parts = representations['legacy'].split('$')
legacy_parts[2] = 'g' + legacy_parts[2][1:]
malformed = work / 'malformed.txt'
malformed.write_text(
    'Architect:' + '$'.join(legacy_parts) + '\nsecond line\n',
    encoding='utf-8',
)
malformed.chmod(0o600)
PY

for credential in "$work/argon2.txt" "$work/scrypt.txt" "$work/legacy.txt"; do
    printf '%s\n' 'recovery secret' | "$work/recoveryauth" "$credential"
    set +e
    printf '%s\n' 'wrong secret' | "$work/recoveryauth" "$credential"
    status=$?
    set -e
    [ "$status" -eq 1 ]
done

chmod 0644 "$work/argon2.txt"
set +e
printf '%s\n' 'recovery secret' | "$work/recoveryauth" "$work/argon2.txt"
status=$?
set -e
[ "$status" -eq 2 ]

set +e
printf '%s\n' 'recovery secret' | "$work/recoveryauth" "$work/malformed.txt"
status=$?
set -e
[ "$status" -eq 2 ]

echo 'Recovery authenticator tests passed.'
'@

$test.Replace("`r", '') |
    & wsl.exe -d Ubuntu -u root --exec bash -s -- $wslSource $wslBrokerDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Recovery authenticator validation failed with exit code $LASTEXITCODE."
}
