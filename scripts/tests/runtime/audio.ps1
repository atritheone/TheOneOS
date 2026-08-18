[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $projectRoot 'scripts\common.ps1')
Set-Location -LiteralPath $environmentRoot

function Invoke-AudioDiagnostic {

    $mountScript = Join-Path $projectRoot 'scripts/mount.ps1'
    $unmountScript = Join-Path $projectRoot 'scripts/unmount.ps1'
    $buildSource = Join-Path $projectRoot 'source\build software'
    $catalogueSource = Join-Path $projectRoot 'source\catalogue\audio'
    $graphicsCatalogueSource = Join-Path $projectRoot 'source\catalogue\graphics'
    $softwareSource = Join-Path $projectRoot 'source\software\audio'
    $fixturesSource = Join-Path $projectRoot 'resource\tests\audio'
    $mediaFixturesSource = Join-Path $projectRoot 'resource\tests\media'
    $mountPoint = '/mnt/t1fs'
    $buildTarget = '/mnt/t1fs/the one/build'
    $catalogueTarget = '/mnt/t1fs/the one/catalogue/audio'
    $graphicsCatalogueTarget = '/mnt/t1fs/the one/catalogue/graphics'
    $softwareTarget = '/mnt/t1fs/the one/software/audio'
    $fixturesTarget = '/mnt/t1fs/.ephemeral/audio-tests'
    $metadataTarget = '/mnt/t1fs/.ephemeral/audio-metadata-tests'
    $mediaFixturesTarget = '/mnt/t1fs/.ephemeral/media-fixture-source'
    $mediaTarget = '/mnt/t1fs/.ephemeral/media-tests'
    $metadataPath = '/.ephemeral/audio-metadata-tests/tagged.mp3'
    $diskMounted = $false
    $buildMounted = $false
    $catalogueMounted = $false
    $graphicsCatalogueMounted = $false
    $softwareMounted = $false
    $fixturesMounted = $false
    $mediaFixturesMounted = $false
    $metadataCreated = $false
    $mediaCreated = $false
    $cleanupError = $null

    foreach ($requiredPath in @($buildSource, $catalogueSource, $graphicsCatalogueSource, $softwareSource, $fixturesSource, $mediaFixturesSource)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "audio diagnostic source directory not found: $requiredPath"
        }
    }

    try {
        Write-Host 'mounting the T1OS image for audio diagnostics...'
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "mount failed with exit code $LASTEXITCODE."
        }
        $diskMounted = $true

        $wslSources = @()
        foreach ($source in @($buildSource, $catalogueSource, $graphicsCatalogueSource, $softwareSource, $fixturesSource, $mediaFixturesSource)) {
            $translated = & wsl.exe --exec wslpath -a $source
            if ($LASTEXITCODE -ne 0 -or -not $translated) {
                throw "could not translate audio diagnostic path for WSL: $source"
            }
            $wslSources += ([string]($translated | Select-Object -First 1)).Trim()
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $catalogueTarget $graphicsCatalogueTarget $softwareTarget $fixturesTarget $mediaFixturesTarget $mediaTarget
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create audio diagnostic mount targets.'
        }
        & wsl.exe -u root --exec nsenter -t 1 -m -- install -d -m 0700 -o 0 -g 0 '/mnt/t1fs/.ephemeral/media'
        if ($LASTEXITCODE -ne 0) {
            throw 'could not prepare the root-owned media sandbox diagnostic directory.'
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[0] $buildTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio build bind mount failed.' }
        $buildMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[1] $catalogueTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio catalogue bind mount failed.' }
        $catalogueMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[2] $graphicsCatalogueTarget
        if ($LASTEXITCODE -ne 0) { throw 'graphics catalogue bind mount failed.' }
        $graphicsCatalogueMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[3] $softwareTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio software bind mount failed.' }
        $softwareMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[4] $fixturesTarget
        if ($LASTEXITCODE -ne 0) { throw 'audio fixture bind mount failed.' }
        $fixturesMounted = $true

        & wsl.exe -u root --exec nsenter -t 1 -m -- mount --bind $wslSources[5] $mediaFixturesTarget
        if ($LASTEXITCODE -ne 0) { throw 'media fixture source bind mount failed.' }
        $mediaFixturesMounted = $true
        $mediaCreated = $true

        $python = '/the one/software/python/bin/python3.13'
        $audioApi = '/the one/build/audio/audio.py'
        $mediaApi = '/the one/build/media/media.py'
        $serverImport = "import runpy, sys; sys.path.insert(0, '/the one/build/audio'); runpy.run_path('/the one/build/audio/audioserver.py', run_name='audio_diagnostic')"
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $serverImport
        if ($LASTEXITCODE -ne 0) {
            throw 'audio server could not load from its boot-time script path.'
        }

        $serverCheck = @'
import runpy
import sys
import json
import os
import socket
import errno

sys.path.insert(0, '/the one/build/audio')
server = runpy.run_path('/the one/build/audio/audioserver.py', run_name='audio_engine_diagnostic')
realtek = {
    'card': 3,
    'codecs': [{'name': 'Realtek ALC897', 'vendor_id': '10ec0897', 'subsystem_id': '1462ee26'}],
    'usb': '',
}
soundblaster = {
    'card': 1,
    'codecs': [{'name': 'Realtek ALC899', 'vendor_id': '10ec0899', 'subsystem_id': '11020041'}],
    'usb': '',
}
hdmi = {
    'card': 0,
    'codecs': [{'name': 'NVIDIA HDMI', 'vendor_id': '10de00a5', 'subsystem_id': ''}],
    'usb': '',
}
assert server['pcmnumbers']('/the one/drivers/nodes/snd/pcmC3D0p') == (3, 0)
assert server['pcmpreferencekey']('pcmC3D0p', '10ec0897', realtek) < server['pcmpreferencekey']('pcmC1D0p', '10ec0897', soundblaster)
assert server['pcmpreferencekey']('pcmC3D0p', '10ec0897', realtek) < server['pcmpreferencekey']('pcmC0D3p', '10ec0897', hdmi)
assert server['pcmpreferencekey']('pcmC3D0p', None, realtek) < server['pcmpreferencekey']('pcmC1D0p', None, soundblaster)
server['ALSACARDINFO'][3] = realtek
assert server['pcmcandidatediagnostic']('pcmC3D0p', None)['rank'] == 5
assert server['calibratedmastergain'](0.0) == 0.0
assert abs(server['calibratedmastergain'](0.20) - (0.20 * 0.90 / 0.28)) < 0.000001
assert abs(server['calibratedmastergain'](0.28) - 0.90) < 0.000001
assert server['calibratedmastergain'](1.0) == 1.0

engine = server['alsactlpath'].__globals__
assert engine['ctypes'].sizeof(engine['sndctleminfo']) == 272
assert engine['ctypes'].sizeof(engine['sndctlemvalue']) == 1224
assert engine['ctypes'].sizeof(engine['sndctlemlist']) == 80
originalischardev = engine['ischardev']
engine['ischardev'] = lambda path: str(path).endswith('/controlC3')
assert server['alsactlpath']('/the one/drivers/nodes/snd', 'pcmC3D0p').endswith('/controlC3')
engine['ischardev'] = originalischardev

originalioctl = engine['fcntl'].ioctl
writes = []
currenttype = [None]
def mixerioctl(fd, request, obj, *args):
    if isinstance(obj, engine['sndctleminfo']):
        assert obj.id.iface == 2
        name = bytes(obj.id.name).split(b'\x00', 1)[0].decode('ascii')
        obj.type = 3 if name == 'Auto-Mute Mode' else (1 if name.endswith('Switch') else 2)
        obj.count = 2
        obj.value.integer.min = 0
        obj.value.integer.max = 100
        currenttype[0] = obj.type
        return 0
    if isinstance(obj, engine['sndctlemvalue']):
        if currenttype[0] == 1:
            values = obj.value.boolean
        elif currenttype[0] == 2:
            values = obj.value.integer
        else:
            values = obj.value.enumerated
        writes.append([int(values[0]), int(values[1])])
        return 0
    raise AssertionError(type(obj))
engine['fcntl'].ioctl = mixerioctl
assert server['alsasetbyname'](1, 'Front Playback Volume', 0.5)
assert writes[-1] == [50, 50]
assert server['alsasetbyname'](1, 'Front Playback Switch', 1)
assert writes[-1] == [1, 1]
assert server['alsasetbyname'](1, 'Auto-Mute Mode', 0)
assert writes[-1] == [0, 0]
engine['fcntl'].ioctl = originalioctl

setuprequests = []
startthresholds = []
def setupioctl(fd, request, obj, *args):
    setuprequests.append(request)
    if isinstance(obj, engine['snd_pcm_sw_params']):
        startthresholds.append(int(obj.start_threshold))
    return 0
engine['fcntl'].ioctl = setupioctl
originalserverlog = engine['log']
engine['log'] = lambda text: None
setupinfo = server['alsasetup'](9, 48000, 2, 480, 's16le')
assert setupinfo['samplerate'] == 48000
assert setupinfo['channels'] == 2
assert startthresholds == [1440]
assert engine['io']('A', 0x40) in setuprequests
assert engine['io']('A', 0x42) not in setuprequests
engine['log'] = originalserverlog
engine['fcntl'].ioctl = originalioctl

stream = {
    'id': 1,
    'fd': 1,
    'alive': True,
    'closing': False,
    'started': True,
    'paused': True,
    'state': 'paused',
    'rb': server['rbnew'](server['FRAMEBYTES'] * 960),
    'gain': 1.0,
    'mute': False,
    'inbytes': 0,
    'outbytes': 0,
    'presentedframes': 0,
    'segments': [],
    'format': {'samplerate': 48000, 'channels': 2, 'format': 's16le'},
    'underruns': 0,
}
assert server['rbpush'](stream['rb'], b'\x01\x00\x01\x00' * 480)
server['STREAMS'].clear()
server['STREAMS'][1] = stream
queued = server['rbavail'](stream['rb'])
assert server['mixcollectframes'](480) == []
assert server['rbavail'](stream['rb']) == queued
stream['paused'] = False
stream['state'] = 'playing'
assert len(server['mixcollectframes'](480)) == 1
assert server['rbavail'](stream['rb']) == 0
assert server['rbpush'](stream['rb'], b'\x01\x00\x01\x00' * 480)
stream['mute'] = True
beforemutedoutput = stream['outbytes']
assert server['mixcollectframes'](480) == []
assert server['rbavail'](stream['rb']) == 0
assert stream['outbytes'] == beforemutedoutput + (480 * server['FRAMEBYTES'])
stream['mute'] = False

clock = [0.0]
engine = server['mixloop'].__globals__
originalbackendwrite = engine['backendwrite']
engine['time'].monotonic = lambda: clock[0]
engine['BACKEND'] = {
    'type': 'hda',
    'hda': {'samplerate': 44100, 'channels': 2, 'format': 's16le'},
}
engine['MIXFRAMES'] = 441
engine['LASTMIX'] = 0.0
engine['MIXEDFRAMES'] = 0
engine['BACKENDPRESENTEDFRAMES'] = 0
engine['XRUNS'] = 0
engine['LASTSTATLOG'] = 0.0
engine['mixonceframes'] = lambda frames, timelineframe=None: b'\x00' * (frames * engine['FRAMEBYTES'])
engine['backendwrite'] = lambda pcm: True
engine['log'] = lambda text: None
engine['mixloop']()
baseline = engine['MIXEDFRAMES']
for tick in range(1, 51):
    clock[0] = tick * 0.02
    engine['mixloop']()
assert engine['MIXEDFRAMES'] - baseline == 44100
assert engine['XRUNS'] == 0
assert engine['backendsamplerate']() == 44100
assert engine['streamformat']({'samplerate': 44100, 'channels': 2, 'format': 's16le'})['samplerate'] == 44100

outputring = engine['rbnew'](441 * engine['FRAMEBYTES'] * 16)
originalbackendfilepump = engine['backendfilepump']
engine['BACKEND'] = {
    'type': 'file',
    'alsa': True,
    'alsainfo': {'samplerate': 44100, 'channels': 2, 'format': 's16le'},
    'periodframes': 441,
    'bufferframes': 1764,
    'framebytes': engine['FRAMEBYTES'],
    'outrb': outputring,
    'pending': b'',
    'outfd': None,
}
engine['LASTMIX'] = 0.0
engine['MIXEDFRAMES'] = 0
engine['BACKENDPRESENTEDFRAMES'] = 0
engine['backendfilepump'] = lambda: False
engine['backendwrite'] = originalbackendwrite
engine['mixloop']()
assert engine['backendpendingframes']() == 1764
assert engine['MIXEDFRAMES'] == 1764
engine['rbpop'](outputring, 441 * engine['FRAMEBYTES'])
clock[0] += 0.02
engine['mixloop']()
assert engine['MIXEDFRAMES'] == 2205
assert engine['backendpresentedframes']() == 441

engine['backendfilepump'] = originalbackendfilepump
recoveryring = engine['rbnew'](480 * engine['FRAMEBYTES'] * 4)
assert engine['rbpush'](recoveryring, b'\x01\x00\x01\x00' * 480)
engine['BACKEND'] = {
    'type': 'file',
    'alsa': True,
    'periodframes': 480,
    'bufferframes': 1920,
    'framebytes': engine['FRAMEBYTES'],
    'outrb': recoveryring,
    'pending': b'',
    'outfd': 9,
    'outpath': '/test/pcmC1D0p',
    'ready': True,
    'recoveries': 0,
}
engine['BACKENDERRS'] = 0
engine['BACKENDWRITES'] = 0
engine['BACKENDBYTES'] = 0
engine['XRUNS'] = 0
originalalsadelay = engine['alsadelay']
originaloswrite = engine['os'].write
originalioctl = engine['fcntl'].ioctl
writesfailed = [False]
def recoveringwrite(fd, data):
    if not writesfailed[0]:
        writesfailed[0] = True
        raise OSError(errno.EPIPE, 'simulated playback underrun')
    return len(data)
engine['alsadelay'] = lambda fd: 0
engine['os'].write = recoveringwrite
engine['fcntl'].ioctl = lambda fd, request, obj, *args: 0
engine['log'] = lambda text: None
assert not engine['backendfilepump']()
assert engine['BACKEND']['recoveries'] == 1
assert engine['XRUNS'] == 1
assert engine['BACKENDERRS'] == 1
assert len(engine['BACKEND']['pending']) == 480 * engine['FRAMEBYTES']
assert engine['backendfilepump']()
assert engine['BACKEND']['pending'] == b''
assert engine['BACKENDWRITES'] == 1
assert engine['BACKENDBYTES'] == 480 * engine['FRAMEBYTES']
engine['alsadelay'] = originalalsadelay
engine['os'].write = originaloswrite
engine['fcntl'].ioctl = originalioctl

engine['BACKEND'] = {}
engine['MIXEDFRAMES'] = 350
engine['BACKENDPRESENTEDFRAMES'] = 0
presented = {
    'outbytes': 400 * engine['FRAMEBYTES'],
    'presentedframes': 0,
    'segments': [[100, 500, 0]],
}
assert engine['streampresentedframes'](presented) == 250
assert engine['streamstatusdata'](dict(presented, id=2, state='playing'))['presented_bytes'] == 250 * engine['FRAMEBYTES']

decoder = engine['audioapi'].decodercommand('/tmp/test.flac', samplerate=44100)
rateindex = decoder.index('-ar')
assert decoder[rateindex + 1] == '44100'

controller = engine['audioapi'].PlaybackController()
sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
try:
    for payload in (
        {'command': 'pause'},
        {'command': 'resume'},
        {'command': 'mute', 'muted': True},
        {'command': 'seek', 'position': 2.5},
        {'command': 'stop'},
    ):
        sender.sendto(json.dumps(payload).encode('utf-8'), controller.path)
    controller.poll()
    assert controller.paused is False
    assert controller.muted is True
    assert controller.takeseek() == 2.5
    assert controller.stopped is True
finally:
    sender.close()
    controller.close()

controlpath = '/.ephemeral/audio/control-helper-test.sock'
receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
try:
    if os.path.exists(controlpath):
        os.unlink(controlpath)
    receiver.bind(controlpath)
    receiver.settimeout(1.0)
    commands = (
        ('pause', None, {'command': 'pause'}),
        ('resume', None, {'command': 'resume'}),
        ('mute', None, {'command': 'mute', 'muted': True}),
        ('seek', 4.25, {'command': 'seek', 'position': 4.25}),
        ('stop', None, {'command': 'stop'}),
    )
    for command, position, expected in commands:
        assert engine['audioapi'].sendcontrol(
            controlpath,
            command,
            position=position,
            muted=True if command == 'mute' else None,
        )
        actual = json.loads(receiver.recv(4096).decode('utf-8'))
        assert actual == expected
    assert not engine['audioapi'].sendcontrol(controlpath, 'unknown')
    assert not engine['audioapi'].sendcontrol(controlpath, 'seek', position=-1.0)
finally:
    receiver.close()
    try:
        os.unlink(controlpath)
    except Exception:
        pass
print('audio engine timing and pause diagnostics passed.')
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $serverCheck
        if ($LASTEXITCODE -ne 0) {
            throw 'audio engine timing or pause diagnostic failed.'
        }

        $brickCheck = @'
import json
import os
import runpy
import socket
import sys

sys.path.insert(0, '/the one/build')
brick = runpy.run_path('/the one/build/brick/brick.py', run_name='brick_audio_diagnostic')
brick['gfx']._xres = 900
brick['gfx']._yres = 600
brick['applyuiscale'](900, 600)
brick['measurements']()
playback = brick['PLAYBACK']
playback.update({
    'id': 77,
    'state': 'playing',
    'position': 30.0,
    'duration': 120.0,
    'control': '/.ephemeral/audio/test.sock',
})
brick['playbackappend'](77)
geometry = brick['playbackgeometry']()
assert geometry['track'][2] > 20
assert geometry['track'][2] < 450
assert geometry['thumb'][0] > geometry['track'][0]
playbackindex = brick['playbacklineindex']()
layout = brick['contentlayout']()
assert geometry['y'] == layout['y0'] + ((playbackindex - layout['start']) * brick['LINEHEIGHT'])
playingcommands = []
brick['graphicsbuildplayback'](playingcommands, [0, 0, 900, 600])
assert any(command.get('kind') == 'text' for command in playingcommands)
playingrects = [command for command in playingcommands if command.get('kind') == 'rectangle']
assert brick['playbackstatusline'](
    'T1OS_AUDIO_STATUS ' + json.dumps({
        'type': 'audio_status',
        'state': 'paused',
        'position': 31.0,
        'duration': 120.0,
    })
)
assert playback['state'] == 'paused'
pausedcommands = []
brick['graphicsbuildplayback'](pausedcommands, [0, 0, 900, 600])
pausedrects = [command for command in pausedcommands if command.get('kind') == 'rectangle']
assert len(playingrects) < len(pausedrects)
playback['state'] = 'stopped'
assert brick['playbacksuppressline']('> playback stopped')
assert not brick['playbacksuppressline']('> another message')
playback['state'] = 'paused'

controlpath = '/.ephemeral/audio/brick-test.sock'
try:
    if os.path.exists(controlpath):
        os.unlink(controlpath)
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(controlpath)
    receiver.settimeout(1.0)
    playback['control'] = controlpath
    assert brick['playbackcommand']('seek', position=45.0)
    command = json.loads(receiver.recv(4096).decode('utf-8'))
    assert command == {'command': 'seek', 'position': 45.0}
finally:
    try:
        receiver.close()
    except Exception:
        pass
    try:
        os.unlink(controlpath)
    except Exception:
        pass
brick['playbackfinish'](77, '> playback complete')
assert brick['SCROLL'][playbackindex] == '> playback complete'
assert brick['STYLES'][playbackindex] is None
assert len(brick['SCROLL']) == 1

brick['SCROLL'].clear()
brick['STYLES'].clear()
playback.clear()
playback.update({
    'id': 88,
    'state': 'playing',
    'media_kind': 'video',
    'position': 1.0,
    'duration': 2.0,
    'generation': 0,
    'rows': 10,
    'control': '/.ephemeral/media/test.sock',
    'frame': {},
})
brick['playbackappend'](88, rows=10)
frameroot = '/.ephemeral/media/brick-diagnostic'
os.makedirs(frameroot, exist_ok=True)
framepath = frameroot + '/frame.bgra'
with open(framepath, 'wb') as stream:
    stream.write(bytes((0x11, 0x22, 0x33, 0xff)) * 4)
assert brick['playbackstatusline'](
    'T1OS_MEDIA_STATUS ' + json.dumps({
        'type': 'media_status',
        'state': 'playing',
        'media_kind': 'video',
        'position': 1.1,
        'duration': 2.0,
        'generation': 0,
    })
)
assert brick['playbackstatusline'](
    'T1OS_MEDIA_FRAME ' + json.dumps({
        'type': 'media_frame',
        'media_kind': 'video',
        'path': framepath,
        'width': 2,
        'height': 2,
        'pts': 1.1,
        'frame': 1,
        'generation': 0,
    })
)
videogeometry = brick['playbackgeometry']()
assert len(brick['SCROLL']) == 10
assert videogeometry['video'][3] > 0
videocommands = []
brick['graphicsbuildplayback'](videocommands, [0, 0, 900, 600])
assert any(command.get('kind') == 'image' and command.get('id') == 'playback-video' for command in videocommands)
brick['playbackfinish'](88, '> playback complete')
assert len(brick['SCROLL']) == 1 and brick['SCROLL'][0] == '> playback complete'
os.unlink(framepath)
os.rmdir(frameroot)
print('brick media control diagnostics passed.')
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $brickCheck
        if ($LASTEXITCODE -ne 0) {
            throw 'brick audio control diagnostic failed.'
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- mkdir -p $metadataTarget
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create the tagged audio diagnostic directory.'
        }
        $metadataCreated = $true

        $taggedBuilder = @'
import struct
import zlib

source = '/.ephemeral/audio-tests/sample.mp3'
target = '/.ephemeral/audio-metadata-tests/tagged.mp3'


def frame(name, value):

    payload = b'\x00' + value.encode('latin-1')
    return name.encode('ascii') + struct.pack('>I', len(payload)) + b'\x00\x00' + payload


def synchsafe(value):

    return bytes(((value >> 21) & 0x7f, (value >> 14) & 0x7f, (value >> 7) & 0x7f, value & 0x7f))


def chunk(name, value):

    return struct.pack('>I', len(value)) + name + value + struct.pack('>I', zlib.crc32(name + value) & 0xffffffff)


cover = b'\x89PNG\r\n\x1a\n'
cover += chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
cover += chunk(b'IDAT', zlib.compress(b'\x00\xd2\x50\x1e\x28\x46\xa0\x00\xfa\xbe\x46\xd2\x50\x1e'))
cover += chunk(b'IEND', b'')


frames = b''.join((
    frame('TIT2', 'Signal Fires'),
    frame('TPE1', 'The Diagnostics'),
    frame('TALB', 'Native Audio'),
    frame('TPE2', 'T1OS Ensemble'),
    frame('TCOM', 'Ada Signal'),
    frame('TCON', 'Electronic'),
    frame('TYER', '2026'),
    frame('TRCK', '3/12'),
    frame('TPOS', '1/2'),
))
picture = b'\x00image/png\x00\x03\x00' + cover
frames += b'APIC' + struct.pack('>I', len(picture)) + b'\x00\x00' + picture

with open(source, 'rb') as stream:

    audio = stream.read()

if audio.startswith(b'ID3') and len(audio) >= 10:

    oldsize = ((audio[6] & 0x7f) << 21) | ((audio[7] & 0x7f) << 14) | ((audio[8] & 0x7f) << 7) | (audio[9] & 0x7f)
    audio = audio[10 + oldsize:]

with open(target, 'wb') as stream:

    stream.write(b'ID3\x03\x00\x00' + synchsafe(len(frames)) + frames + audio)
'@
        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B -c $taggedBuilder
        if ($LASTEXITCODE -ne 0) {
            throw 'could not create the tagged MP3 and embedded artwork fixture.'
        }

        $validOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $audioApi diagnostic '/.ephemeral/audio-tests/sample.mp3' '/.ephemeral/audio-tests/sample.flac' $metadataPath
        $validExitCode = $LASTEXITCODE
        if (-not $validOutput) {
            throw 'audio diagnostic produced no output.'
        }

        $actual = ([string]($validOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($validExitCode -ne 0 -or -not $actual.passed) {
            throw "valid audio fixtures failed: $($actual.errors -join '; ')"
        }
        if (@($actual.checks.decoded.PSObject.Properties).Count -ne 3) {
            throw 'audio diagnostic did not decode MP3, FLAC, and tagged MP3 fixtures.'
        }

        $taggedInfo = @($actual.checks.metadata.PSObject.Properties | Where-Object Name -EQ $metadataPath | Select-Object -ExpandProperty Value)
        $taggedArtwork = @($actual.checks.artworks.PSObject.Properties | Where-Object Name -EQ $metadataPath | Select-Object -ExpandProperty Value)
        if (-not $actual.checks.metadata_parser -or $taggedInfo.Count -ne 1 -or $taggedInfo[0].tags.title -ne 'Signal Fires' -or $taggedInfo[0].tags.artist -ne 'The Diagnostics' -or $taggedInfo[0].tags.album -ne 'Native Audio' -or -not $taggedInfo[0].artwork -or $taggedArtwork.Count -ne 1 -or [int]$taggedArtwork[0] -lt 8) {
            throw 'audio diagnostic did not preserve tags, stream information, and embedded artwork.'
        }

        $player = '/the one/build/player/player.py'
        $playerOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $player metadata-diagnostic $metadataPath 2>&1
        $playerExitCode = $LASTEXITCODE
        if (-not $playerOutput) {
            throw 'Player metadata diagnostic produced no output.'
        }

        $playerActual = ([string]($playerOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($playerExitCode -ne 0 -or -not $playerActual.passed -or -not $playerActual.checks.scene -or $playerActual.checks.metadata.title -ne 'Signal Fires' -or $playerActual.checks.metadata.artist -ne 'The Diagnostics' -or $playerActual.checks.metadata.album -ne 'Native Audio' -or $playerActual.checks.artwork.surface.Count -ne 2) {
            throw "Player metadata diagnostic failed: $($playerActual.errors -join '; ')"
        }

        & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B '/.ephemeral/media-fixture-source/build.py' '/.ephemeral/media-tests'
        if ($LASTEXITCODE -ne 0) {
            throw 'could not generate deterministic media fixtures.'
        }

        $mediaAudioVideo = '/.ephemeral/media-tests/sample audio video.avi'
        $mediaVideoOnly = '/.ephemeral/media-tests/sample video only.avi'
        $mediaOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $mediaApi diagnostic $mediaAudioVideo $mediaVideoOnly 2>&1
        $mediaExitCode = $LASTEXITCODE
        if (-not $mediaOutput) {
            throw 'media diagnostic produced no output.'
        }

        $mediaActual = ([string]($mediaOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($mediaExitCode -ne 0 -or -not $mediaActual.passed -or -not $mediaActual.checks.decoder_optimizations -or -not $mediaActual.checks.shared_frame_ring -or -not $mediaActual.checks.probe_parser -or -not $mediaActual.checks.frame_publication -or -not $mediaActual.checks.video_only_playback -or -not $mediaActual.checks.video_controls -or -not $mediaActual.checks.audio_video_sync) {
            throw "media runtime diagnostic failed: $($mediaActual.errors -join '; ')"
        }
        if (@($mediaActual.checks.decoded.PSObject.Properties).Count -ne 2) {
            throw 'media diagnostic did not decode both generated video fixtures.'
        }

        $invalidOutput = & wsl.exe -u root --exec nsenter -t 1 -m -- /usr/sbin/chroot $mountPoint $python -B $audioApi diagnostic '/.ephemeral/audio-tests/corrupt.mp3' 2>&1
        $invalidExitCode = $LASTEXITCODE
        if (-not $invalidOutput) {
            throw 'invalid audio diagnostic produced no output.'
        }

        $invalid = ([string]($invalidOutput | Select-Object -Last 1)).Trim() | ConvertFrom-Json
        if ($invalidExitCode -eq 0 -or $invalid.passed -or $invalid.errors.Count -eq 0) {
            throw 'the decoder accepted the corrupt MP3 fixture.'
        }

        Write-Host 'audio runtime diagnostic passed.'
        Write-Host ($actual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host ($playerActual | ConvertTo-Json -Depth 8 -Compress)
        Write-Host 'media runtime diagnostic passed.'
        Write-Host ($mediaActual | ConvertTo-Json -Depth 8 -Compress)
    }
    finally {
        if ($mediaCreated) {
            if ($mediaTarget -ne '/mnt/t1fs/.ephemeral/media-tests') {
                throw 'refusing to remove an unexpected media diagnostic path.'
            }
            & wsl.exe -u root --exec nsenter -t 1 -m -- rm -rf -- $mediaTarget
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'media diagnostic cleanup failed.'
            }
        }

        if ($metadataCreated) {
            if ($metadataTarget -ne '/mnt/t1fs/.ephemeral/audio-metadata-tests') {
                throw 'refusing to remove an unexpected audio metadata diagnostic path.'
            }
            & wsl.exe -u root --exec nsenter -t 1 -m -- rm -rf -- $metadataTarget
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'audio metadata diagnostic cleanup failed.'
            }
        }

        foreach ($mount in @(
            @($mediaFixturesMounted, $mediaFixturesTarget),
            @($fixturesMounted, $fixturesTarget),
            @($softwareMounted, $softwareTarget),
            @($graphicsCatalogueMounted, $graphicsCatalogueTarget),
            @($catalogueMounted, $catalogueTarget),
            @($buildMounted, $buildTarget)
        )) {
            if ($mount[0]) {
                & wsl.exe -u root --exec nsenter -t 1 -m -- umount $mount[1]
                if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                    $cleanupError = "audio bind unmount failed for $($mount[1])."
                }
            }
        }

        if ($diskMounted) {
            & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript | Out-Host
            if ($LASTEXITCODE -ne 0 -and -not $cleanupError) {
                $cleanupError = 'audio diagnostic image unmount failed.'
            }
        }

        if ($cleanupError) {
            throw $cleanupError
        }
    }
}


Write-Host "checking that storage is not mounted..."

$mounted = Test-T1OSDiskMounted

if ($mounted) {
    Write-Host ""
    Write-Host "t1fs is mounted. running unmount..."

    $unmountScript = Join-Path $projectRoot 'scripts/unmount.ps1'

    if (-not (Test-Path $unmountScript)) {
        Write-Host "unmount.ps1 not found in this directory."
        exit 1
    }

    & pwsh -NoLogo -NoProfile -NonInteractive -File "$unmountScript"
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Host "unmount failed with exit code $exitCode."
        exit 1
    }

    Write-Host ""
    Write-Host "unmount completed. continuing..."
}


Invoke-AudioDiagnostic

Write-Host 'Runtime audio validation passed.'
