#!/usr/bin/env python3

"""Verify the modern local-media playback contract and its consumers."""

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

import ast
import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / 'source' / 'settings' / 'media' / 'playback capabilities.json'
MANIFEST_PATH = ROOT / 'source' / 'software' / 'audio' / 'manifest.json'
CAPABILITIES_PATH = ROOT / 'source' / 'build software' / 'media' / 'capabilities.py'
MEDIA_PATH = ROOT / 'source' / 'build software' / 'media' / 'media.py'
AUDIO_PATH = ROOT / 'source' / 'build software' / 'audio' / 'audio.py'
ARRAY_PATH = ROOT / 'source' / 'build software' / 'array' / 'array.py'
GRAPHICS_PATH = ROOT / 'source' / 'build software' / 'graphics' / 'graphics.py'
NATIVE_PATH = ROOT / 'source' / 'native' / 'video' / 't1_video_decode.c'
BUILD_PATH = ROOT / 'scripts' / 'build audio runtime.ps1'


def require(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def loadmodule(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, f'cannot load {path}')
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def extractfunction(path, name, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'),
        namespace,
    )
    return namespace[name]


def main():
    contract = json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    require(contract.get('format') == 1, 'unsupported capability contract format')
    require(contract.get('scope') == 'local-unencrypted-media', 'contract scope is not bounded')

    for key in ('video_extensions', 'audio_extensions'):
        values = contract.get(key, [])
        require(values == sorted(set(values)), f'{key} must be sorted and unique')
        require(all(value.startswith('.') and value == value.lower() for value in values), f'{key} is not normalized')

    capabilities = loadmodule('t1_media_capability_contract', CAPABILITIES_PATH)
    loaded = capabilities.load(str(CONTRACT_PATH))
    require(tuple(loaded['video_extensions']) == tuple(contract['video_extensions']), 'video extension contract diverged')
    require(capabilities.extensionkind('film.VVC') == 'video', 'fallback discovery omitted VVC')
    require(capabilities.extensionkind('film.MXF') == 'video', 'fallback discovery omitted MXF')

    runtime = manifest.get('capabilities', {})
    sandbox = manifest.get('runtime', {}).get('media_decode_sandbox', {})
    requiredmap = {
        'guaranteed_video_decoders': 'video_decoders',
        'compatibility_video_decoders': 'video_decoders',
        'guaranteed_audio_decoders': 'audio_decoders',
        'guaranteed_subtitle_codecs': 'subtitle_decoders',
        'required_demuxers': 'demuxers',
        'required_filters': 'filters',
        'required_hwaccels': 'hardware_accelerators',
    }
    missing = {
        promised: sorted(set(contract.get(promised, ())) - set(runtime.get(available, ())))
        for promised, available in requiredmap.items()
        if set(contract.get(promised, ())) - set(runtime.get(available, ()))
    }
    require(not missing, f'runtime manifest does not satisfy the media contract: {missing}')
    require(not manifest.get('verification', {}).get('missing_capabilities'), 'runtime records missing capabilities')
    require(
        sandbox.get('local_file_native', {}).get('activation') == 'before-container-open'
        and sandbox.get('local_file_software', {}).get('activation') == 'pre-main-constructor'
        and sandbox.get('local_file_native', {}).get('seccomp') == 'filter-tsync'
        and sandbox.get('local_file_software', {}).get('seccomp') == 'filter-tsync',
        'local file decoder sandbox attestation is incomplete',
    )
    require(
        (ROOT / 'source' / 'catalogue' / 'audio' / 'libt1-media-file-sandbox.so.1').is_file(),
        'software decoder sandbox library is not packaged',
    )

    audio_package = types.ModuleType('audio')
    audio_module = types.ModuleType('audio.audio')
    audio_module.LOSSLESSCODECS = {'flac', 'alac', 'ffv1'}
    audio_module.AUDIOSOCK = '/nonexistent/audio.sock'
    audio_package.audio = audio_module
    sys.modules['audio'] = audio_package
    sys.modules['audio.audio'] = audio_module
    media = loadmodule('t1_media_contract_test', MEDIA_PATH)

    probe = {
        'format': {'format_name': 'matroska,webm', 'duration': '12.5', 'size': '1024'},
        'chapters': [{'id': 4, 'start_time': '1.0', 'end_time': '3.0', 'tags': {'title': 'Intro'}}],
        'streams': [
            {'index': 0, 'codec_type': 'video', 'codec_name': 'av1', 'width': 3840, 'height': 2160,
             'pix_fmt': 'yuv420p10le', 'color_transfer': 'smpte2084', 'color_primaries': 'bt2020',
             'color_space': 'bt2020nc', 'field_order': 'progressive', 'disposition': {'default': 1}},
            {'index': 1, 'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 720,
             'pix_fmt': 'yuv420p', 'disposition': {'default': 0}},
            {'index': 2, 'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '48000',
             'channels': 2, 'channel_layout': 'stereo', 'tags': {'language': 'eng'}, 'disposition': {'default': 1}},
            {'index': 3, 'codec_type': 'audio', 'codec_name': 'ac3', 'sample_rate': '48000',
             'channels': 6, 'channel_layout': '5.1', 'tags': {'language': 'deu'}},
            {'index': 4, 'codec_type': 'subtitle', 'codec_name': 'ass', 'tags': {'language': 'eng'},
             'disposition': {'forced': 1}},
        ],
    }
    info = media.parseprobe(probe, '/tmp/sample.mkv')
    require(info['selected_video_stream'] == 0 and len(info['video_tracks']) == 2, 'video inventory/default selection failed')
    require(info['selected_audio_stream'] == 2 and len(info['audio_tracks']) == 2, 'audio inventory/default selection failed')
    require(len(info['subtitle_tracks']) == 1 and len(info['chapters']) == 1, 'subtitle/chapter inventory failed')
    require(info['video']['hdr_format'] == 'PQ' and info['video']['bit_depth'] == 10, 'HDR stream metadata failed')
    selected = media.selecttracks(dict(info), video_stream_index=1, audio_stream_index=3)
    require(selected['video']['codec'] == 'H264' and selected['audio']['codec'] == 'AC3', 'explicit stream selection failed')
    command, _, _, _ = media.videocommand('/tmp/interlaced.mkv', {
        **selected['video'], 'field_order': 'tt', 'index': 1,
    }, ffmpegpath='/decoder', maximumwidth=640, maximumheight=360)
    require(command[command.index('-map') + 1] == '0:1', 'video decoder did not use the selected absolute stream')
    require('bwdif=' in command[command.index('-vf') + 1], 'software deinterlacing is not selected')

    decodercommand = extractfunction(
        AUDIO_PATH,
        'decodercommand',
        {'FFMPEGPATH': '/decoder', 'DEFAULTSR': 48000, 'DEFAULTCH': 2},
    )
    audiocommand = decodercommand('/tmp/multi.mkv', ffmpegpath='/decoder', startseconds=3.25, streamindex=3)
    require(audiocommand[audiocommand.index('-map') + 1] == '0:3', 'audio decoder did not use the selected absolute stream')
    require(audiocommand[audiocommand.index('-ss') + 1] == '3.250000', 'audio restart position was lost')

    arraytext = ARRAY_PATH.read_text(encoding='utf-8')
    graphicstext = GRAPHICS_PATH.read_text(encoding='utf-8')
    nativetext = NATIVE_PATH.read_text(encoding='utf-8')
    audiotext = AUDIO_PATH.read_text(encoding='utf-8')
    buildtext = BUILD_PATH.read_text(encoding='utf-8')
    require('from media.capabilities import' in arraytext, 'Array does not consume the canonical extension contract')
    require('hdrtransfer' in graphicstext and '78.84375' in graphicstext and '0.17883277' in graphicstext, 'GPU HDR transfer handling is absent')
    require('--stream-index' in nativetext and 'rotation_state' in nativetext and '\\"formats\\"' in nativetext, 'native stream/rotation/format selection is absent')
    native_decode = nativetext[nativetext.index('t1_video_decode(const char *path,'):]
    landlock_position = native_decode.index(
        't1_video_install_file_landlock(path, &landlock_abi)'
    )
    device_position = native_decode.index('av_hwdevice_ctx_create(')
    seccomp_position = native_decode.index(
        't1_video_install_file_seccomp(landlock_abi)'
    )
    input_position = native_decode.index('avformat_open_input(&decoder.format')
    require(
        landlock_position < device_position < seccomp_position < input_position,
        'native decoder confinement/device ordering regressed',
    )
    require('T1OS_MEDIA_SANDBOX_REQUIRED' in audiotext and 'LD_PRELOAD' in audiotext, 'software fallback does not require confinement')
    require('missing_media_capabilities' in buildtext, 'runtime build does not enforce the contract')

    result = {
        'format': 1,
        'passed': True,
        'policy': contract['policy'],
        'runtime_counts': {name: len(runtime.get(name, ())) for name in requiredmap.values()},
        'video_extensions': len(contract['video_extensions']),
        'audio_extensions': len(contract['audio_extensions']),
        'track_inventory': {'video': 2, 'audio': 2, 'subtitle': 1, 'chapters': 1},
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
