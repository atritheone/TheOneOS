#!/usr/bin/env python3
"""Apply the pinned T1OS media backend to Chromium 150.0.7871.181.

The script is intentionally strict: an unpatched file must match the exact
upstream SHA-256 before an anchored edit is attempted.  A patched tree is
checked against the exact bytes derived from the pinned Git revision and by
byte-comparing every overlay file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OVERLAY = ROOT / "overlay"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
REVISION = MANIFEST["chromium_revision"]
SKIA_REVISION = MANIFEST["skia_revision"]
SKIA_ROOT = Path("third_party/skia")

UPSTREAM_SHA256 = {
    "base/command_line.h": "973770ed8317caccc46dd194a5f705c0721a8b6a5fbc31149cc44ab7dc94645d",
    "base/command_line.cc": "e02061a9607905df47375abca55e1e7e480c846865d73dcde338b9af98ae48a3",
    "media/media_options.gni": "21a6c0617fd9d86f1b09bce6f808134190d7b098274cc8ba92b934e1fe2eb53f",
    "media/BUILD.gn": "2a7ddbb932cef7366d91b002703f9d6859ccdb71360cd79073dbda56bf0e4a08",
    "media/base/BUILD.gn": "69dd1d25aec36f607c65c7329a0c1f5cc7c98ef24f6260ea99211b2f957474a2",
    "media/base/decoder.h": "3c04c73ed1a56bdb6d7ca75d19bad1d50317535e560d8bb09a6f78f28b092445",
    "media/base/decoder.cc": "060cf8ca161bb246ba132c1a912269bd06426ede84c5e745c95dc6909ecd7300",
    "media/audio/alsa/alsa_output.cc": "198d0e36b97598289bea6d0767a947adf41545928818b2c7a3beb2551941a03a",
    "media/audio/alsa/alsa_output.h": "575f7b441142b1f87f3d4f05eb7c32076a11234408ace495c075037420444b16",
    "media/gpu/BUILD.gn": "d8632850b858586b8045664734f88f84ecb76dbb69c4bb1c77264942358bfdbb",
    "media/mojo/services/BUILD.gn": "20d038cc4c10210ed0c13bc6df972e1c58e6bd4b4c96738ed211de3f085b3f40",
    "media/mojo/services/gpu_mojo_media_client_linux.cc": "e81d770bdaf2d27baf2bd9aa2df25f57516162d462ceed78cf15918e792c0819",
    "media/mojo/services/gpu_mojo_media_client.cc": "8cb081a712a70d6731c1bf7b6d04454006c8fd4252649c23f78eb9300650e440",
    "content/renderer/render_thread_impl.cc": "2616964affc2dbd53a2092971aff88d865313884501e7f71248dd864fa6eaa46",
    "content/browser/BUILD.gn": "dbf7d74906ccdabec3abd3e52d57f95a581fc40c2158182d7cc7ba3ec22338b8",
    "content/browser/gpu/gpu_process_host.cc": "ba83a2b601dc8f6bc138218ced8ac6da5433612d079c5604b510017cf05a4e85",
    "content/browser/compositor/viz_process_transport_factory.cc": "711d07bdb75b8eb9e9dd18eb0033a3fc3029ffca826f8223aad8a76b48a7b64d",
    "content/browser/child_process_launcher_helper.cc": "4a92455ffd7555323ae499eabf147fe6f3d02ab16c1c9481c552ed5f311a4f56",
    "content/common/zygote/zygote_communication_linux.cc": "f4b6e367bec13cb114286eaa1fc55e25ededeee37159b466b7af19d1fd452e8d",
    "content/browser/service_host/utility_sandbox_delegate.cc": "3bcd64501e07a0ef1a8aa28d6c8bea938c2017e64c0a186e68e43d0c68aebcab",
    "content/common/gpu_pre_sandbox_hook_linux.cc": "6484df28cc337258695fdcb99b44f4c28e741e2bb229adde75fefc6fd5612f05",
    "components/viz/service/display_embedder/skia_output_surface_impl_on_gpu.cc": "8ef1c71ed3d610bd5b8841d13c98731b75eba8e1015d0d34b55ca496c9ddfc6e",
    "components/viz/host/gpu_host_impl.cc": "7294175f1442f99108ec1cc3be1f290be061add734e057188df375ac8472e19c",
    "components/viz/service/frame_sinks/root_compositor_frame_sink_impl.cc": "43d119f352f31ab0912238f4bff6da05fedb01c3b24d5391071a25600b0887eb",
    "content/child/child_thread_impl.cc": "50f824b28f4306eaefe94b151b41f0cdf29b23ddd5eb6c89eff7ab70d56cecba",
    "content/gpu/gpu_child_thread.cc": "2372fea4bfcd0f71a3af4f27aa7abea9e12116be4051b0bfa3cdd188f559d5bb",
    "content/gpu/gpu_main.cc": "f70c0a33fa41fffd0353f08de41748aa83e4b3861e4ae61d78e410e8e38b2db7",
    "mojo/core/channel_posix.cc": "2bf413d817e986b5d2cace2c298707d512c3fd9abf68df906761c6a8190c13ef",
    "sandbox/policy/linux/bpf_gpu_policy_linux.cc": "0c9c7cc1aae9e2ae16e939f6693608efd7072b0598e93d4bbbe560d863df92c9",
    "sandbox/policy/BUILD.gn": "5d616deb44e55497cfe819e62c11d4e1151a372e36c77d4a835688af2585c267",
    "net/dns/dns_config_service_linux.cc": "5c0d2e1698467d5794c22069bb3618a4cc073bbe5dc079991445271a07d24982",
    "services/network/network_sandbox_hook_linux.cc": "61f500a5fc1ea7e2a66368b2981fff81409b71fa536678910b41e443390e6799",
    "tools/metrics/histograms/enums.xml": "bd8075f63df0e07fb07e54294b3ea414964fa4fb5715bc0b60cc2d77640ac88e",
    "gpu/command_buffer/service/shared_image/ozone_image_backing_factory.cc": "08785b475344840b24c45eb25c12e6e9ac35e4db3b10df299a005dafcd7de4ff",
    "gpu/command_buffer/service/shared_image/ozone_image_gl_textures_holder.cc": "c78f6ead73b74567796660226a86c0f1049522e8429fa4e2663048155206fc0b",
    "ui/ozone/common/native_pixmap_egl_binding.cc": "4ace0a021f9a02f7a61e2295b1cd2af4d6a3566088f9b1ac025c88240c0cc978",
    "ui/ozone/platform/x11/x11_surface_factory.cc": "9ce4f1260b3a4d8b3f6b9237dd01a0d1622f97e86b6cbb460fe3ae1398da2c8c",
    "ui/ozone/platform/x11/BUILD.gn": "52a831becb66fa40a53f09aa238b0f0235a2d6a7e6d5c0410f278699ed85ab7e",
    "ui/ozone/platform/x11/ozone_platform_x11.cc": "9fd667496147b2ea949d0de4785175ee34802fa952695f7edd5c5e6960e9ed7c",
    "ui/gfx/linux/gbm_support_x11.h": "f7ed6ad412a595b5083d78d6438d11d8dd670f1c72ba7cf982a64ae6bd17513d",
    "ui/gfx/linux/gbm_support_x11.cc": "cad6f4b68dd53732b01913903b13cedf0ee038c12fe03be0e41892b6fdf845cf",
    "ui/gfx/linux/gbm_device.h": "a4f8c52f7bceaf38b6667bb1aa5e48be6d7b42cd41531e8b7cc331f8c3087843",
    "ui/gfx/linux/gbm_wrapper.cc": "982cadbf770a4149c6f54746e85cc2c44c0aad60e3aa059e6ee90adcebfd6a54",
    "ui/gfx/native_pixmap_handle.h": "80f35fdf1aa62e464252ce5ba6515a2188ce137a0017e84b06fab9ec5d66d43c",
    "ui/gfx/native_pixmap_handle.cc": "22689dabcbe126caaf03d64cf708bfe7b2b097f430a10179febffabce1067717",
    "ui/gfx/mojom/native_handle_types.mojom": "2e173f5dfed26bf7273e773478923d3ae0df1f762eca7d1552754dae509ad9d0",
    "ui/gfx/mojom/native_handle_types_mojom_traits.h": "5b83172efc012f70aee588b081af0b1b2596419436a392023bb137f9aee8079c",
    "ui/gfx/mojom/native_handle_types_mojom_traits.cc": "733b88bfe111d8ebdb961179e094b1a70d01b885410871704c8a368431c713cb",
    "media/mojo/mojom/stable/native_pixmap_handle.mojom": "2b910532bb1cbe8e589f3fa08bc2a4076fc89b52b11136249ee670b87265ed95",
    "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.h": "06fd1523475f53c28760c4f24f7037e0ee768d5e14abee3f049c338e1f24fa44",
    "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.cc": "d9a108e62566d0b065b9433b1b6a9e75767385edad38bb3f6e8a8ae6b80a5bd2",
    "media/gpu/chromeos/mailbox_video_frame_converter.h": "d2b1d4c86be3baf11a0cd8055984d9fc31a12594bdb11a03bdd1be9c2d812040",
    "media/gpu/chromeos/mailbox_video_frame_converter.cc": "2e442cd9162c050ce49fa85479a847d7bc4c60141438edeec3662446f58f7ea0",
    "media/gpu/chromeos/native_pixmap_frame_resource.h": "7fe6742b01a5f3f6fd7cd0ea82ce0054e304fa8c181e2c372d9a008b661e4ae7",
    "media/gpu/chromeos/native_pixmap_frame_resource.cc": "228780969acc9c3ba9c0b15c46805a6ffdba7e2152e1b49bedd520a60f0d1da6",
    "media/mojo/clients/mojo_codec_factory.cc": "09fb7e236879eabfe042be71940dd5904926344a13a1e390dd83854468844c1a",
    "media/renderers/video_resource_updater.h": "6fa375b124d0e54d83c95b2095a505df36cb10651c6535957fad5760a80b8651",
    "media/renderers/video_resource_updater.cc": "c34a4a3e472ff1b4de337053e6c732f0c2ae641d98eceb8898fe46d1d4dd6992",
    "components/viz/service/display/direct_renderer.cc": "3e7ef19bef57f7a6bc0d7245028bc22929b067c867fdd99af766405073e9b4e7",
    "ui/gl/gl_utils.cc": "bdc0a4d69ab1a67af33aa6846cca03959e7ef1aceb7e7d9578cadff3034a55a3",
    "gpu/ipc/service/gpu_init.cc": "0c492e9e75f96b00a38998c55e5fd3014d61ebc8bd3b46afe7de2714996e4b0c",
}

SKIA_UPSTREAM_SHA256 = {
    "src/gpu/ganesh/gl/GrGLCaps.cpp":
        "5d446eca6422a92dd02eb9bb126ddf89413a0150f424355adddada4ff5fc67fa",
}

BUILD_MARKER_OVERLAY_PATH = Path("media/base/t1os_media_switches.h")
PROTOCOL_OVERLAY_PATH = Path("media/gpu/t1os/t1_media_decode_protocol.h")

# Exact patched bytes from the immediately preceding verified overlay. This
# permits an in-place overlay upgrade while continuing to reject arbitrary
# dirty Chromium source.
MIGRATABLE_PATCHED_SHA256 = {
    "mojo/core/channel_posix.cc": {
        # High-volume transport trace used to prove bidirectional Mojo and fd
        # passing. Keep only a bounded startup sample in the next pass.
        "e0aa978859e3abda83fed798d222203de2cc4729d229f5e263fdfbc481e66cbf",
    },
    "content/child/child_thread_impl.cc": {
        # Prior verified child connection-timeout diagnostic. The next bounded
        # pass probes the inherited Mojo descriptor before accepting it.
        "f1bd1bcc3f6fe4b96d9f3f87470b4d9b11fb980cf4f8832036eb5dcf6fcf0fe7",
        # The first descriptor probe used socket introspection that Chromium's
        # utility/renderer seccomp policy correctly rejects. Migrate it to the
        # non-invasive descriptor-existence probe below.
        "21f294f6d0e28448a66e61d76f6bbd3d80b3c79465ecfb2fa0d4985a8071cc11",
        # Valid endpoint/transport diagnostics before replacing the T1OS-
        # incompatible Ping watchdog with disconnect-based supervision.
        "b9c61844946618f4f8b0e6aad486927625a25a0ba96d4ef859a4d9e46ce5b7b0",
    },
    "content/browser/gpu/gpu_process_host.cc": {
        # Previous T1OS broker/presentation host before the GPU-only launcher
        # bypass kept utility processes on Chromium's supported zygote path.
        "a3ccad4db6f093ba92b21aade4b0230ac3ded5015ade93a85fdc3e391a4048ac",
        # GPU-only launcher bypass selected from the rewritten delegate
        # program rather than the browser's immutable launcher switch.
        "833d1eed8414ff45059cfe49c161df2ccea15bf0c4abc979a5959cfb2c855e6f",
        # Direct launch selected from the unquoted launcher value; paths with
        # spaces were subsequently split by CommandLine::PrependWrapper.
        "48a844895273b3caa9fa67dd3b90cba8d727c17847906b873c9da1e28ba89313",
        # Quoted launcher value kept the path together, but Chromium's wrapper
        # tokenizer retained the quote bytes in argv[0], so execvp rejected it.
        "636c6f07f8c884a3f0a93c4d2b825c592698bb0ef56b50a6aa1bcd5d6012c5c5",
        # Exact argv construction preserved the path but lost CommandLine's
        # switch boundary before BrowserChildProcessHost forwarded switches.
        "2877ef81ab8cc8d88a105d15224563885f80d643dc1661a89c4958e10ac343dc",
        # Exact launcher plus the first X11/Viz surface diagnostics. The next
        # bounded pass adds browser/GPU child bootstrap milestones.
        "181ec882afb4f4e0fe81507f52ede87bf40ab98a9d57c6acefb5af0c746be90d",
    },
    "src/gpu/ganesh/gl/GrGLCaps.cpp": {
        "11d1fed87bfa71106fcf4427db0b1e9284ccd4404db6189556370ad17084b685",
        # Same NVIDIA implicit-MSAA workaround with the previous EGLStream
        # rationale; the replacement documents the GBM window surface.
        "715b4443e6ad84133512935da274c387342b27c93957f60bada73eecc95feacc",
    },
    "sandbox/policy/linux/bpf_gpu_policy_linux.cc": {
        "2922f5c945b590c2b29941355f63498b9bd12d36c06a9f89dabc3672dc01f6f3",
        # Legacy EGLStream PI-futex exception plus the sealed-output memfd
        # allowance. Reconciliation removes the obsolete futex exception.
        "90607117c161464d66f529f5d6973c2499b908bcf9016ea1b8527a75f6517016",
    },
    "media/mojo/mojom/stable/native_pixmap_handle.mojom": {
        "cf2320d3f8646c58e5a835e617c3f560ea9d6fcc1d80dd0e8f0c51adbb9fff7c",
    },
    "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.cc": {
        "55418b5014babdc8acab6f2dc70abaabaed9d7d8f6914def69efffb7d2c40235",
    },
    "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.h": {
        "634ac10bef452694a8763b4dc35261fbf9286211b9e00f0b3627d02efd9a47f0",
    },
    "ui/gfx/mojom/native_handle_types.mojom": {
        "b7c2a3d902136fba835f22445fbacfecb3be56f7e90a6bc380b4a7a4c7013d01",
    },
    "ui/gfx/mojom/native_handle_types_mojom_traits.cc": {
        "38234d8a7611925eefec2e8b20e60b4435cb99ca8a35833d3aac5668a052964a",
    },
    "ui/gfx/mojom/native_handle_types_mojom_traits.h": {
        "1e046b6f7c833d6343d9f4037711b221d8462aacc07f4fc80e30cdf2574499c8",
    },
    "ui/gfx/native_pixmap_handle.cc": {
        "67a994760d53b4de6e02439ae7405bd9aabee1cf447cd99faa2e6cb67621b8c8",
    },
    "ui/gfx/native_pixmap_handle.h": {
        "e22861e9b6e5714d013b72d23e201e0448e1ec2da1168610cb33d646691d1440",
    },
    "ui/ozone/platform/x11/BUILD.gn": {
        # Previous T1OS presentation target before the direct libdrm include
        # dependency required by drm_fourcc.h was added.
        "4ffb6fa3f1be012355a3b177f5262b54b9ae7d30acb6f754a8572a7b9290a11b",
    },
    "components/viz/service/display/direct_renderer.cc": {
        "212ab5bf3d5d3a3f8260cf0d3eda5b094145f1af2b35328b889083b791044d6a",
    },
    "media/gpu/chromeos/native_pixmap_frame_resource.h": {
        "f4f51d46b79b8cd316776a44f1a9fedcdf0f8ce6b9cbaddf49eee5cbd59b698c",
        "0c6ebbe047169d259c4559cfd2ca827642e59f8207d1801090e01138baba7c39",
        "e6f74d5f18bc227c213709c5fa01842c848843350d6622d03164923ee5a01cff",
    },
    "media/gpu/chromeos/native_pixmap_frame_resource.cc": {
        "73cebb67efd33844f432453699e7267db35dc797e246ac198a0b633c17df0761",
        "1e4a3f25ae20c3665b86b1a9c6444633044f846605576caea7f5a11c733c6ce5",
        # Immediately preceding T1OS variant that temporarily carried the
        # chroma order in the WebGPU compatibility bit. The new overlay gives
        # that contract an explicit Mojo field.
        "1a8760a040cf21e8b6311064093f82de6d5d7a220f4cd6d5af463db8ea85ae77",
    },
    "ui/ozone/common/native_pixmap_egl_binding.cc": {
        "5fb6829e0a02625c899f45db74309acd6245c0e3b1fd3d8e4aaadcb8c205fb22",
        "0f367b199a8447d857e1152f6d3da588d0fb9f509ebc763cfc2d3c8910f06f2c",
        # Previous T1OS import path carrying chroma order through the WebGPU
        # compatibility bit. The new overlay uses an explicit Mojo field.
        "dce21540e1808fd81e145983511c5caf351d8a92eb1d1de4656fbce1dfc74ee7",
    },
    "ui/ozone/platform/x11/x11_surface_factory.cc": {
        "d85e59a1dd14fb012d662040cff32968b4f3ac5297f4dc9c858a06f130596902",
        "1c593d019917f72b17c3653c8062c1b0e64a8019d3868c2045beda909f64eeae",
        "1288c3b3e1438a985a2cc2f341ed2e80feabe3e4593bc8feae3e99837674d3a5",
        "c3447c553feca74d61447db6c6685a100a3ce83a73b5d2c7fa4c0a208a863f68",
        "9f35f22155e81ab7161e23f97d361910ed858e8fa3a43dcf9b6078a2cfccf8f3",
        "35e537700273566091ab3b1979e06fd46e5b55b0a155e8ff4ee353ac1703b642",
        "80c4a8edb8b659d979ce2a2c4b5b17d2c5ca1b2cf277470d936a4d4c42e29aa4",
        "e5ed0e35b6f67ffd4f68d0f9a34252156a5a0815d5518cebe75a54b7a6e6f972",
        "83e05c2a8cd8fe543d0fd09339df6939196cb40947e780b3a2846c6cc9045450",
        "5e8af93dd3e0fdbdbf3387c9b1afabb8c27359e57d0717f33c3c47de07efb76f",
        # Previous T1OS factory with render-node path discovery and no
        # containment for an unexpected second top-level widget.
        "b6b9559b0df1b06966551a6191b45d74c3b9d6aefd217445616abd14bccc08bd",
        # Immediately preceding verified factory; M150 represents
        # EGLNativeDisplayType as an integer, so the invalid-display sentinel
        # is upgraded from a nullptr cast to value initialization.
        "fb9fac45b57312f231efde21dbc4f83e0df1d86cd3f9ced8891636a2a673801f",
        # Immediately preceding brokered EGL/GBM factory, before bounded
        # surface-request diagnostics were added.
        "d4d816c729c169185dece5bd00669a20168caf48d76b86ca9ed1153a2ecaf81d",
        # Diagnostic factory before gl::Presenter's complete type was included.
        "4fe5e0fbaebab58d464a81ee03174d24d3837a6a2b67c2737dd0049945aaf4af",
    },
    "media/gpu/chromeos/mailbox_video_frame_converter.cc": {
        "8b0c7f84a6c48f0ba182f3a0b779f0d3933c29b7467dbffcba30e15b63005730",
        "2fb4051c7b482c50aa11c43535e5e3419b3452c97cdddd2fd5b69245a3485916",
        "27cf9e2e103ef57fe6be6e25d4fd95d3a552f0c3dadcf62945d4c5734685fdac",
    },
    "gpu/command_buffer/service/shared_image/ozone_image_gl_textures_holder.cc": {
        "290f61deaf69ce404436e4fd8a9c449ac04801752ff4e3ae0dc070b493adf81b",
        "feef04d40dd2350635497985117af054c163c5c6297761badab438f265da571f",
    },
    "ui/gfx/linux/gbm_support_x11.h": {
        "216e848624fbbb46d4a6f8d8162764d30975a7321cbb5e721f19bf42108bf8cd",
        "46b5c4a92d22eb8ca616e270055c08a214758c22902c902a8d836df4079ddd42",
        "2e1909a1578190f1c6684a816bfe1b7e146655f47eac51629fc1453da4fffdcb",
    },
    "ui/gfx/linux/gbm_support_x11.cc": {
        "5f620a74201d9566e2cbfca36c0dd603fdab84c5fdd8777ac4ea8f0c8b117ad8",
        "f61814519bc526e90a1448270cd7d8ac90cc7037943f402bf0c3c203226a4ea8",
        "fbf9fffe355a54db93664fa0ef6c31d88378523190b088ab7db91890c7a79cc6",
        # Previous T1OS brokered-GBM/modifier implementation. The replacement
        # adds a fail-closed guard against DRI3/device-path discovery.
        "523a60eb3e3e55ab5c67632366e0ffcf59aab09809974d28f3564d0295070aa4",
    },
    "ui/gfx/linux/gbm_device.h": {
        "4f801c6bcf8117856b0887a0c6f233f97e1ebccedf0053ed2dca1b7feb7e9c82",
    },
    "ui/gfx/linux/gbm_wrapper.cc": {
        "d3b132011fd41e41afa685c9fe2eeccaa68977ac26e71c339367c09375537596",
        "57be2869003113a9de19196acff9973f7ff79c7037afae7c315777d8dc0768e9",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, path: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one edit anchor, found {count}")
    return text.replace(old, new, 1)


def append_once(text: str, block: str, sentinel: str) -> str:
    if sentinel in text:
        return text
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def transformations() -> dict[str, tuple[str, callable]]:
    def command_line_h(text: str) -> str:
        text = replace_once(
            text,
            "  // Insert a command before the current command.\n"
            "  // Common for debuggers, like \"gdb --args\".\n"
            "  void PrependWrapper(StringViewType wrapper);\n",
            "  // Insert a command before the current command.\n"
            "  // Common for debuggers, like \"gdb --args\".\n"
            "  void PrependWrapper(StringViewType wrapper);\n\n"
            "  // Insert one exact wrapper program without parsing its path. This\n"
            "  // preserves spaces and the existing switch/argument boundary.\n"
            "  void PrependWrapperPath(const FilePath& wrapper);\n",
            "base/command_line.h",
        )
        return text

    def command_line_cc(text: str) -> str:
        return replace_once(
            text,
            "void CommandLine::PrependWrapper(StringViewType wrapper) {\n",
            "void CommandLine::PrependWrapperPath(const FilePath& wrapper) {\n"
            "#if BUILDFLAG(ENABLE_COMMANDLINE_SEQUENCE_CHECKS)\n"
            "  sequence_checker_.Check();\n"
            "#endif\n"
            "  if (wrapper.empty()) {\n"
            "    return;\n"
            "  }\n"
            "  argv_.insert(argv_.begin(), wrapper.value());\n"
            "  ++begin_args_;\n"
            "}\n\n"
            "void CommandLine::PrependWrapper(StringViewType wrapper) {\n",
            "base/command_line.cc",
        )

    def media_options(text: str) -> str:
        text = replace_once(
            text,
            "declare_args() {\n"
            "  # Allows distributions to link pulseaudio directly",
            "declare_args() {\n"
            "  # T1OS brokered native video decoding. This is Linux-only and\n"
            "  # remains opt-in for every non-T1OS Chromium build.\n"
            "  enable_t1os_video_decoder = false\n\n"
            "  # Allows distributions to link pulseaudio directly",
            "media/media_options.gni",
        )
        return append_once(
            text,
            'assert(!enable_t1os_video_decoder || is_linux,\n'
            '       "T1OS video decoding is supported only on Linux")',
            "T1OS video decoding is supported only on Linux",
        )

    def media_build(text: str) -> str:
        return replace_once(
            text,
            '    "ALLOW_HOSTING_OOP_VIDEO_DECODER=$allow_hosting_oop_video_decoder",\n',
            '    "ALLOW_HOSTING_OOP_VIDEO_DECODER=$allow_hosting_oop_video_decoder",\n'
            '    "ENABLE_T1OS_VIDEO_DECODER=$enable_t1os_video_decoder",\n',
            "media/BUILD.gn",
        )

    def media_base_build(text: str) -> str:
        return replace_once(
            text,
            '  sources = [\n    "agtm.cc",\n',
            '  sources = [\n'
            '    "t1os_media_switches.cc",\n'
            '    "t1os_media_switches.h",\n'
            '    "agtm.cc",\n',
            "media/base/BUILD.gn",
        )

    def decoder_h(text: str) -> str:
        return replace_once(
            text,
            "  kVideoToolbox = 19,  // VideoToolboxVideoDecoder (Mac)\n\n"
            "  // Keep this at the end and equal to the last entry.\n"
            "  kMaxValue = kVideoToolbox",
            "  kVideoToolbox = 19,  // VideoToolboxVideoDecoder (Mac)\n"
            "  kT1OS = 20,          // Brokered T1OS native media decoder\n\n"
            "  // Keep this at the end and equal to the last entry.\n"
            "  kMaxValue = kT1OS",
            "media/base/decoder.h",
        )

    def decoder_cc(text: str) -> str:
        return replace_once(
            text,
            '    case VideoDecoderType::kVideoToolbox:\n'
            '      return "VideoToolboxVideoDecoder";\n',
            '    case VideoDecoderType::kVideoToolbox:\n'
            '      return "VideoToolboxVideoDecoder";\n'
            '    case VideoDecoderType::kT1OS:\n'
            '      return "T1OSVideoDecoder";\n',
            "media/base/decoder.cc",
        )

    def alsa_output_h(text: str) -> str:
        text = replace_once(
            text,
            '#include "base/memory/scoped_refptr.h"\n',
            '#include "base/files/scoped_file.h"\n'
            '#include "base/memory/scoped_refptr.h"\n',
            "media/audio/alsa/alsa_output.h",
        )
        return replace_once(
            text,
            "  raw_ptr<snd_pcm_t> playback_handle_ = nullptr;\n\n"
            "  std::unique_ptr<SeekableBuffer> buffer_;\n",
            "  raw_ptr<snd_pcm_t> playback_handle_ = nullptr;\n\n"
            "  // T1OS's ALSA file PCM terminates at a FIFO/null slave, so its\n"
            "  // snd_pcm_delay() excludes the relay, AudioServer ring, and real\n"
            "  // hardware queue. The launcher publishes those queues here.\n"
            "  base::ScopedFD t1os_audio_clock_fd_;\n\n"
            "  std::unique_ptr<SeekableBuffer> buffer_;\n",
            "media/audio/alsa/alsa_output.h",
        )

    def alsa_output_cc(text: str) -> str:
        text = replace_once(
            text,
            "#include <stddef.h>\n\n"
            "#include <algorithm>\n"
            "#include <memory>\n",
            "#include <stddef.h>\n"
            "#include <stdint.h>\n"
            "#include <stdlib.h>\n"
            "#include <fcntl.h>\n"
            "#include <time.h>\n"
            "#include <unistd.h>\n\n"
            "#include <algorithm>\n"
            "#include <limits>\n"
            "#include <memory>\n"
            "#include <optional>\n",
            "media/audio/alsa/alsa_output.cc",
        )
        text = replace_once(
            text,
            "constexpr ChannelLayout kDefaultOutputChannelLayout = "
            "CHANNEL_LAYOUT_STEREO;\n\n",
            "constexpr ChannelLayout kDefaultOutputChannelLayout = "
            "CHANNEL_LAYOUT_STEREO;\n\n"
            "// T1OS audio presentation clock v1. This exact little-endian\n"
            "// layout is also defined by chromium.py's AUDIOCLOCKFORMAT. The\n"
            "// relay writes an odd sequence, the payload, then an even sequence.\n"
            "constexpr char kT1OSAudioClockPathEnvironment[] =\n"
            "    \"T1OS_CHROMIUM_AUDIO_CLOCK_PATH\";\n"
            "constexpr uint32_t kT1OSAudioClockMagic = 0x43413154;  // \"T1AC\"\n"
            "constexpr uint32_t kT1OSAudioClockVersion = 1;\n"
            "constexpr uint64_t kT1OSAudioClockFreshNanoseconds =\n"
            "    UINT64_C(2000000000);\n\n"
            "struct T1OSAudioClock {\n"
            "  uint32_t magic;\n"
            "  uint32_t version;\n"
            "  uint64_t sequence;\n"
            "  uint64_t updated_monotonic_ns;\n"
            "  uint64_t fifo_frames;\n"
            "  uint64_t server_queued_frames;\n"
            "  uint64_t hardware_pending_frames;\n"
            "  uint64_t presented_frames;\n"
            "  uint64_t underruns;\n"
            "  uint32_t sample_rate;\n"
            "  uint32_t stream_id;\n"
            "};\n"
            "static_assert(sizeof(T1OSAudioClock) == 72);\n"
            "static_assert(offsetof(T1OSAudioClock, sequence) == 8);\n\n"
            "std::optional<snd_pcm_sframes_t> ReadT1OSAudioClockDelay(\n"
            "    int descriptor,\n"
            "    uint32_t sample_rate) {\n"
            "  if (descriptor < 0 || sample_rate == 0) {\n"
            "    return std::nullopt;\n"
            "  }\n"
            "  for (int attempt = 0; attempt < 3; ++attempt) {\n"
            "    T1OSAudioClock clock = {};\n"
            "    if (pread(descriptor, &clock, sizeof(clock), 0) !=\n"
            "        static_cast<ssize_t>(sizeof(clock))) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    if (clock.magic != kT1OSAudioClockMagic ||\n"
            "        clock.version != kT1OSAudioClockVersion ||\n"
            "        clock.sequence == 0 || (clock.sequence & 1) != 0 ||\n"
            "        clock.sample_rate != sample_rate) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    uint64_t verified_sequence = 0;\n"
            "    if (pread(descriptor, &verified_sequence,\n"
            "              sizeof(verified_sequence),\n"
            "              offsetof(T1OSAudioClock, sequence)) !=\n"
            "            static_cast<ssize_t>(sizeof(verified_sequence)) ||\n"
            "        verified_sequence != clock.sequence) {\n"
            "      continue;\n"
            "    }\n"
            "    struct timespec now = {};\n"
            "    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    const uint64_t now_ns =\n"
            "        static_cast<uint64_t>(now.tv_sec) * UINT64_C(1000000000) +\n"
            "        static_cast<uint64_t>(now.tv_nsec);\n"
            "    if (clock.updated_monotonic_ns > now_ns) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    const uint64_t age_ns = now_ns - clock.updated_monotonic_ns;\n"
            "    if (age_ns > kT1OSAudioClockFreshNanoseconds) {\n"
            "      return 0;\n"
            "    }\n"
            "    const uint64_t maximum_frames =\n"
            "        static_cast<uint64_t>(sample_rate) * 2;\n"
            "    if (clock.fifo_frames > maximum_frames ||\n"
            "        clock.server_queued_frames > maximum_frames ||\n"
            "        clock.hardware_pending_frames > maximum_frames) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    const uint64_t queued_frames = clock.fifo_frames +\n"
            "        clock.server_queued_frames + clock.hardware_pending_frames;\n"
            "    if (queued_frames > maximum_frames) {\n"
            "      return std::nullopt;\n"
            "    }\n"
            "    const uint64_t elapsed_frames =\n"
            "        age_ns * static_cast<uint64_t>(sample_rate) /\n"
            "        UINT64_C(1000000000);\n"
            "    return static_cast<snd_pcm_sframes_t>(\n"
            "        queued_frames > elapsed_frames\n"
            "            ? queued_frames - elapsed_frames\n"
            "            : 0);\n"
            "  }\n"
            "  return std::nullopt;\n"
            "}\n\n",
            "media/audio/alsa/alsa_output.cc",
        )
        text = replace_once(
            text,
            "  if (playback_handle_ == nullptr) {\n"
            "    stop_stream_ = true;\n"
            "    TransitionTo(kInError);\n"
            "    return false;\n"
            "  }\n"
            "  bytes_per_output_frame_ =\n",
            "  if (playback_handle_ == nullptr) {\n"
            "    stop_stream_ = true;\n"
            "    TransitionTo(kInError);\n"
            "    return false;\n"
            "  }\n"
            "  if (const char* path = getenv(kT1OSAudioClockPathEnvironment);\n"
            "      path && path[0] != '\\0') {\n"
            "    t1os_audio_clock_fd_.reset(open(path, O_RDONLY | O_CLOEXEC));\n"
            "    if (!t1os_audio_clock_fd_.is_valid()) {\n"
            "      PLOG(WARNING) << \"Unable to open T1OS audio presentation clock\";\n"
            "    }\n"
            "  }\n"
            "  bytes_per_output_frame_ =\n",
            "media/audio/alsa/alsa_output.cc",
        )
        text = replace_once(
            text,
            "  weak_factory_.InvalidateWeakPtrsAndDoom();\n\n"
            "  // Signal to the manager that we're closed and can be removed.\n",
            "  t1os_audio_clock_fd_.reset();\n"
            "  weak_factory_.InvalidateWeakPtrsAndDoom();\n\n"
            "  // Signal to the manager that we're closed and can be removed.\n",
            "media/audio/alsa/alsa_output.cc",
        )
        return replace_once(
            text,
            "  if (delay < 0) {\n"
            "    delay = 0;\n"
            "  }\n"
            "  TRACE_EVENT_END(\n",
            "  if (delay < 0) {\n"
            "    delay = 0;\n"
            "  }\n"
            "  if (auto downstream_delay = ReadT1OSAudioClockDelay(\n"
            "          t1os_audio_clock_fd_.get(), sample_rate_)) {\n"
            "    const snd_pcm_sframes_t maximum =\n"
            "        std::numeric_limits<snd_pcm_sframes_t>::max();\n"
            "    delay = *downstream_delay > maximum - delay\n"
            "                ? maximum\n"
            "                : delay + *downstream_delay;\n"
            "  }\n"
            "  TRACE_EVENT_END(\n",
            "media/audio/alsa/alsa_output.cc",
        )

    def media_gpu_build(text: str) -> str:
        text = replace_once(
            text,
            '    "hrd_buffer_unittest.cc",\n'
            '  ]\n',
            '    "hrd_buffer_unittest.cc",\n'
            '  ]\n'
            '  if (enable_t1os_video_decoder) {\n'
            '    sources += [ "t1os/t1os_video_decoder_unittest.cc" ]\n'
            '    deps += [ ":t1os_video_decoder" ]\n'
            '  }\n',
            "media/gpu/BUILD.gn",
        )
        block = """
if (enable_t1os_video_decoder) {
  source_set("t1os_video_decoder") {
    defines = [ "IS_MEDIA_GPU_IMPL" ]
    sources = [
      "t1os/t1_media_decode_protocol.h",
      "t1os/t1os_decoder_connection.cc",
      "t1os/t1os_decoder_connection.h",
      "t1os/t1os_video_decoder.cc",
      "t1os/t1os_video_decoder.h",
    ]
    deps = [
      ":gpu",
      "//base",
      "//media",
      "//third_party/libdrm",
      "//ui/gfx",
    ]
  }
}
"""
        return append_once(text, block, 'source_set("t1os_video_decoder")')

    def mojo_build(text: str) -> str:
        text = replace_once(
            text,
            '  deps = [\n'
            '    "//gpu/ipc/service",\n'
            '    "//media",\n'
            '    "//media/gpu",\n'
            '    "//media/gpu:buildflags",\n'
            '    "//media/gpu/ipc/service",\n'
            '    "//media/mojo/common",\n'
            '    "//services/metrics/public/cpp:metrics_cpp",\n'
            '    "//services/metrics/public/cpp:ukm_builders",\n'
            '    "//services/metrics/public/mojom",\n'
            '    "//services/service_manager/public/mojom",\n'
            '  ]\n',
            '  deps = [\n'
            '    "//gpu/ipc/service",\n'
            '    "//media",\n'
            '    "//media/gpu",\n'
            '    "//media/gpu:buildflags",\n'
            '    "//media/gpu/ipc/service",\n'
            '    "//media/mojo/common",\n'
            '    "//services/metrics/public/cpp:metrics_cpp",\n'
            '    "//services/metrics/public/cpp:ukm_builders",\n'
            '    "//services/metrics/public/mojom",\n'
            '    "//services/service_manager/public/mojom",\n'
            '  ]\n\n'
            '  if (enable_t1os_video_decoder) {\n'
            '    deps += [ "//media/gpu:t1os_video_decoder" ]\n'
            '  }\n',
            "media/mojo/services/BUILD.gn",
        )
        return replace_once(
            text,
            '  } else if (use_linux_video_acceleration) {\n'
            '    if (is_linux) {\n'
            '      sources += [ "gpu_mojo_media_client_linux.cc" ]\n'
            '    } else {\n'
            '      sources += [ "gpu_mojo_media_client_cros.cc" ]\n'
            '    }\n',
            '  } else if (is_linux &&\n'
            '             (use_linux_video_acceleration ||\n'
            '              enable_t1os_video_decoder)) {\n'
            '    sources += [ "gpu_mojo_media_client_linux.cc" ]\n'
            '  } else if (use_linux_video_acceleration) {\n'
            '    sources += [ "gpu_mojo_media_client_cros.cc" ]\n',
            "media/mojo/services/BUILD.gn",
        )

    def mojo_linux(text: str) -> str:
        text = replace_once(
            text,
            '#include "media/base/media_switches.h"\n',
            '#include "media/base/media_switches.h"\n'
            '#include "media/media_buildflags.h"\n'
            '#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n'
            '#include "media/base/t1os_media_switches.h"\n'
            '#include "media/gpu/t1os/t1os_video_decoder.h"\n'
            '#endif\n',
            "gpu_mojo_media_client_linux.cc",
        )
        text = replace_once(
            text,
            "VideoDecoderType GetPreferredLinuxDecoderImplementation() {\n"
            "  // VaapiVideoDecoder flag is required for VaapiVideoDecoder.",
            "VideoDecoderType GetPreferredLinuxDecoderImplementation() {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (base::FeatureList::IsEnabled(kT1OSVideoDecoder)) {\n"
            "    return VideoDecoderType::kT1OS;\n"
            "  }\n"
            "#endif\n\n"
            "  // VaapiVideoDecoder flag is required for VaapiVideoDecoder.",
            "gpu_mojo_media_client_linux.cc",
        )
        text = replace_once(
            text,
            "    case VideoDecoderType::kOutOfProcess:\n"
            "      return VideoDecoderType::kOutOfProcess;\n",
            "    case VideoDecoderType::kOutOfProcess:\n"
            "      return VideoDecoderType::kOutOfProcess;\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "    case VideoDecoderType::kT1OS:\n"
            "      return T1OSVideoDecoder::IsAvailable()\n"
            "                 ? VideoDecoderType::kT1OS\n"
            "                 : VideoDecoderType::kUnknown;\n"
            "#endif\n",
            "gpu_mojo_media_client_linux.cc",
        )
        text = replace_once(
            text,
            "    switch (decoder_type) {\n"
            "      case VideoDecoderType::kOutOfProcess: {",
            "    switch (decoder_type) {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "      case VideoDecoderType::kT1OS:\n"
            "        return T1OSVideoDecoder::Create(\n"
            "            traits.task_runner, traits.media_log->Clone(),\n"
            "            MailboxVideoFrameConverter::Create(\n"
            "                gpu_task_runner_, traits.get_command_buffer_stub_cb,\n"
            "                /*output_mappable=*/false));\n"
            "#endif\n"
            "      case VideoDecoderType::kOutOfProcess: {",
            "gpu_mojo_media_client_linux.cc",
        )
        text = replace_once(
            text,
            "      case VideoDecoderType::kOutOfProcess:\n"
            "      case VideoDecoderType::kVaapi:\n"
            "      case VideoDecoderType::kV4L2:\n"
            "        VideoDecoderPipeline::NotifySupportKnown",
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "      case VideoDecoderType::kT1OS:\n"
            "        std::move(cb).Run(std::move(oop_video_decoder));\n"
            "        break;\n"
            "#endif\n"
            "      case VideoDecoderType::kOutOfProcess:\n"
            "      case VideoDecoderType::kVaapi:\n"
            "      case VideoDecoderType::kV4L2:\n"
            "        VideoDecoderPipeline::NotifySupportKnown",
            "gpu_mojo_media_client_linux.cc",
        )
        return replace_once(
            text,
            "    switch (decoder_implementation) {\n"
            "      case VideoDecoderType::kOutOfProcess:\n",
            "    switch (decoder_implementation) {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "      case VideoDecoderType::kT1OS:\n"
            "        return T1OSVideoDecoder::GetSupportedConfigs();\n"
            "#endif\n"
            "      case VideoDecoderType::kOutOfProcess:\n",
            "gpu_mojo_media_client_linux.cc",
        )

    def mojo_service_gate(text: str) -> str:
        text = replace_once(
            text,
            '#include "base/feature_list.h"\n',
            '#include "base/command_line.h"\n'
            '#include "base/feature_list.h"\n',
            "gpu_mojo_media_client.cc",
        )
        text = replace_once(
            text,
            '#include "media/base/media_switches.h"\n'
            '#include "media/base/media_util.h"\n',
            '#include "media/base/media_switches.h"\n'
            '#include "media/media_buildflags.h"\n'
            '#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n'
            '#include "media/base/t1os_media_switches.h"\n'
            '#endif\n'
            '#include "media/base/media_util.h"\n',
            "gpu_mojo_media_client.cc",
        )
        text = replace_once(
            text,
            "bool IsAcceleratedDecodingDisabled(\n"
            "    const gpu::GpuPreferences& gpu_preferences,\n"
            "    const gpu::GpuFeatureInfo& gpu_feature_info) {\n"
            "  return gpu_preferences.disable_accelerated_video_decode ||\n"
            "         gpu_feature_info.status_values\n"
            "                 [gpu::GPU_FEATURE_TYPE_ACCELERATED_VIDEO_DECODE] !=\n"
            "             gpu::kGpuFeatureStatusEnabled ||\n"
            "         // For some reason the GpuPreferences and GpuFeatureInfo may not be\n"
            "         // up to date in this case.\n"
            "         gl::GetGLImplementation() == gl::kGLImplementationDisabled;\n"
            "}\n",
            "bool IsAcceleratedDecodingDisabled(\n"
            "    const gpu::GpuPreferences& gpu_preferences,\n"
            "    const gpu::GpuFeatureInfo& gpu_feature_info) {\n"
            "  // T1OS does not use Chromium's VA-API/VDA path, so its brokered\n"
            "  // decoder must not inherit that path's blocklist status or the\n"
            "  // derived GpuPreferences bit that GpuInit sets from that status.\n"
            "  // Preserve a literal command-line kill switch and the GL\n"
            "  // command-buffer requirement.\n"
            "  const bool conventional_gpu_feature_disabled =\n"
            "      gpu_feature_info.status_values\n"
            "              [gpu::GPU_FEATURE_TYPE_ACCELERATED_VIDEO_DECODE] !=\n"
            "          gpu::kGpuFeatureStatusEnabled;\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  const bool t1os_decoder_enabled =\n"
            "      base::FeatureList::IsEnabled(kT1OSVideoDecoder);\n"
            "#else\n"
            "  constexpr bool t1os_decoder_enabled = false;\n"
            "#endif\n"
            "  const bool explicit_decode_kill_switch =\n"
            "      base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
            "          \"disable-accelerated-video-decode\");\n"
            "  const bool preference_disables_selected_decoder =\n"
            "      gpu_preferences.disable_accelerated_video_decode &&\n"
            "      (!t1os_decoder_enabled || explicit_decode_kill_switch);\n"
            "  return preference_disables_selected_decoder ||\n"
            "         (conventional_gpu_feature_disabled &&\n"
            "          !t1os_decoder_enabled) ||\n"
            "         // Every implementation still requires a command buffer.\n"
            "         gl::GetGLImplementation() == gl::kGLImplementationDisabled;\n"
            "}\n",
            "gpu_mojo_media_client.cc",
        )
        return replace_once(
            text,
            "    if (IsAcceleratedDecodingDisabled(gpu_preferences_, gpu_feature_info_)) {\n"
            "      supported_config_cache_ = SupportedVideoDecoderConfigs();\n"
            "    } else {\n"
            "      supported_config_cache_ = GetPlatformSupportedVideoDecoderConfigs();\n"
            "    }\n\n"
            "    // Once per GPU process record accelerator information.",
            "    const bool decoder_gate_disabled =\n"
            "        IsAcceleratedDecodingDisabled(gpu_preferences_, gpu_feature_info_);\n"
            "    if (decoder_gate_disabled) {\n"
            "      supported_config_cache_ = SupportedVideoDecoderConfigs();\n"
            "    } else {\n"
            "      supported_config_cache_ = GetPlatformSupportedVideoDecoderConfigs();\n"
            "    }\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "    if (base::FeatureList::IsEnabled(kT1OSVideoDecoder)) {\n"
            "      LOG(INFO) << \"T1OS_MEDIA_DECODER gpu_service_gate disabled=\"\n"
            "                << decoder_gate_disabled << \" preference_disabled=\"\n"
            "                << gpu_preferences_.disable_accelerated_video_decode\n"
            "                << \" explicit_kill_switch=\"\n"
            "                << base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
            "                       \"disable-accelerated-video-decode\")\n"
            "                << \" conventional_status=\"\n"
            "                << gpu_feature_info_.status_values\n"
            "                       [gpu::GPU_FEATURE_TYPE_ACCELERATED_VIDEO_DECODE]\n"
            "                << \" gl_implementation=\"\n"
            "                << static_cast<int>(gl::GetGLImplementation())\n"
            "                << \" supported_configs=\"\n"
            "                << (supported_config_cache_\n"
            "                        ? supported_config_cache_->size()\n"
            "                        : 0u);\n"
            "    }\n"
            "#endif\n\n"
            "    // Once per GPU process record accelerator information.",
            "gpu_mojo_media_client.cc",
        )

    def renderer_decoder_gate(text: str) -> str:
        text = replace_once(
            text,
            '#include "media/base/media_switches.h"\n'
            '#include "media/media_buildflags.h"\n',
            '#include "media/base/media_switches.h"\n'
            '#include "media/media_buildflags.h"\n'
            '#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n'
            '#include "media/base/t1os_media_switches.h"\n'
            '#endif\n',
            "content/renderer/render_thread_impl.cc",
        )
        text = replace_once(
            text,
            "  const base::CommandLine* cmd_line = base::CommandLine::ForCurrentProcess();\n"
            "\n"
            "  scoped_refptr<gpu::GpuChannelHost> gpu_channel_host =\n"
            "      EstablishGpuChannelSync();\n"
            "  if (!gpu_channel_host)\n"
            "    return nullptr;\n"
            "  // Currently, VideoResourceUpdater can't convert hardware resources to\n"
            "  // software resources in software compositing mode.  So, fall back to software\n"
            "  // video decoding if gpu compositing is off.\n"
            "  if (is_gpu_compositing_disabled_)\n"
            "    return nullptr;\n",
            "  const base::CommandLine* cmd_line = base::CommandLine::ForCurrentProcess();\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  const bool t1os_decoder_requested =\n"
            "      base::FeatureList::IsEnabled(media::kT1OSVideoDecoder);\n"
            "#else\n"
            "  constexpr bool t1os_decoder_requested = false;\n"
            "#endif\n"
            "\n"
            "  scoped_refptr<gpu::GpuChannelHost> gpu_channel_host =\n"
            "      EstablishGpuChannelSync();\n"
            "  if (!gpu_channel_host) {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "    if (t1os_decoder_requested) {\n"
            "      LOG(ERROR) << \"T1OS_MEDIA_DECODER renderer_factory \"\n"
            "                    \"gpu_channel=0\";\n"
            "    }\n"
            "#endif\n"
            "    return nullptr;\n"
            "  }\n"
            "  // Conventional platform decoders still require GPU page compositing.\n"
            "  // T1OS decoding instead uses its own offscreen media command buffer;\n"
            "  // keep the native decoder selected while its presentation transport is\n"
            "  // bridged into T1OS's private display path.\n"
            "  if (is_gpu_compositing_disabled_ && !t1os_decoder_requested)\n"
            "    return nullptr;\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (t1os_decoder_requested) {\n"
            "    LOG(INFO) << \"T1OS_MEDIA_DECODER renderer_factory gpu_channel=1 \"\n"
            "              << \"software_compositing=\"\n"
            "              << is_gpu_compositing_disabled_;\n"
            "  }\n"
            "#endif\n",
            "content/renderer/render_thread_impl.cc",
        )
        return replace_once(
            text,
            "  const bool enable_video_decode_accelerator =\n"
            "#if BUILDFLAG(IS_LINUX)\n"
            "      base::FeatureList::IsEnabled(media::kAcceleratedVideoDecodeLinux) &&\n"
            "#endif  // BUILDFLAG(IS_LINUX)\n"
            "      !cmd_line->HasSwitch(switches::kDisableAcceleratedVideoDecode) &&\n"
            "      (gpu_channel_host->gpu_feature_info()\n"
            "           .status_values[gpu::GPU_FEATURE_TYPE_ACCELERATED_VIDEO_DECODE] ==\n"
            "       gpu::kGpuFeatureStatusEnabled);\n",
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  const bool enable_t1os_video_decoder =\n"
            "      base::FeatureList::IsEnabled(media::kT1OSVideoDecoder);\n"
            "#else\n"
            "  constexpr bool enable_t1os_video_decoder = false;\n"
            "#endif\n"
            "  const auto video_decode_gpu_status =\n"
            "      gpu_channel_host->gpu_feature_info().status_values\n"
            "          [gpu::GPU_FEATURE_TYPE_ACCELERATED_VIDEO_DECODE];\n"
            "  const bool conventional_video_decode_enabled =\n"
            "#if BUILDFLAG(IS_LINUX)\n"
            "      base::FeatureList::IsEnabled(media::kAcceleratedVideoDecodeLinux) &&\n"
            "#endif  // BUILDFLAG(IS_LINUX)\n"
            "      video_decode_gpu_status == gpu::kGpuFeatureStatusEnabled;\n"
            "  const bool enable_video_decode_accelerator =\n"
            "      !cmd_line->HasSwitch(switches::kDisableAcceleratedVideoDecode) &&\n"
            "      (enable_t1os_video_decoder || conventional_video_decode_enabled);\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (enable_t1os_video_decoder) {\n"
            "    LOG(INFO) << \"T1OS_MEDIA_DECODER renderer_gate enabled=\"\n"
            "              << enable_video_decode_accelerator\n"
            "              << \" global_switch_disabled=\"\n"
            "              << cmd_line->HasSwitch(\n"
            "                     switches::kDisableAcceleratedVideoDecode)\n"
            "              << \" conventional_feature_enabled=\"\n"
            "              << conventional_video_decode_enabled\n"
            "              << \" conventional_status=\"\n"
            "              << video_decode_gpu_status;\n"
            "  }\n"
            "#endif\n",
            "content/renderer/render_thread_impl.cc",
        )

    def native_pixmap_frame_resource_h(text: str) -> str:
        return replace_once(
            text,
            "      const gfx::Size& natural_size,\n"
            "      std::vector<base::ScopedFD> dmabuf_fds,\n"
            "      base::TimeDelta timestamp);\n",
            "      const gfx::Size& natural_size,\n"
            "      std::vector<base::ScopedFD> dmabuf_fds,\n"
            "      base::TimeDelta timestamp);\n\n"
            "  // T1OS's decoder exports NVIDIA chroma layers as either DRM RG or GR.\n"
            "  // Preserve that producer ordering explicitly across native-pixmap IPC.\n"
            "  static scoped_refptr<NativePixmapFrameResource> CreateForT1OS(\n"
            "      const media::VideoFrameLayout& layout,\n"
            "      const gfx::Rect& visible_rect,\n"
            "      const gfx::Size& natural_size,\n"
            "      std::vector<base::ScopedFD> dmabuf_fds,\n"
            "      std::vector<uint64_t> plane_modifiers,\n"
            "      base::TimeDelta timestamp,\n"
            "      bool chroma_is_drm_rg);\n",
            "media/gpu/chromeos/native_pixmap_frame_resource.h",
        )

    def native_pixmap_frame_resource_cc(text: str) -> str:
        text = replace_once(
            text,
            "    const gfx::Size& natural_size,\n"
            "    std::vector<base::ScopedFD> dmabuf_fds,\n"
            "    base::TimeDelta timestamp) {\n",
            "    const gfx::Size& natural_size,\n"
            "    std::vector<base::ScopedFD> dmabuf_fds,\n"
            "    base::TimeDelta timestamp) {\n"
            "  return CreateForT1OS(layout, visible_rect, natural_size,\n"
            "                         std::move(dmabuf_fds),\n"
            "                         std::vector<uint64_t>(\n"
            "                             layout.num_planes(), layout.modifier()),\n"
            "                         timestamp,\n"
            "                         /*chroma_is_drm_rg=*/false);\n"
            "}\n\n"
            "scoped_refptr<NativePixmapFrameResource>\n"
            "NativePixmapFrameResource::CreateForT1OS(\n"
            "    const media::VideoFrameLayout& layout,\n"
            "    const gfx::Rect& visible_rect,\n"
            "    const gfx::Size& natural_size,\n"
            "    std::vector<base::ScopedFD> dmabuf_fds,\n"
            "    std::vector<uint64_t> plane_modifiers,\n"
            "    base::TimeDelta timestamp,\n"
            "    bool chroma_is_drm_rg) {\n",
            "media/gpu/chromeos/native_pixmap_frame_resource.cc",
        )
        return replace_once(
            text,
            "  handle.modifier = layout.modifier();\n\n"
            "  // Note: |buffer_usage| is not set. As a result, the constructed\n",
            "  if (plane_modifiers.size() != num_planes) {\n"
            "    DLOGF(ERROR) << \"Layout num_planes=\" << num_planes\n"
            "                 << \" must match plane_modifiers.size()=\"\n"
            "                 << plane_modifiers.size();\n"
            "    return nullptr;\n"
            "  }\n"
            "  handle.modifier = layout.modifier();\n"
            "  handle.plane_modifiers = std::move(plane_modifiers);\n"
            "  handle.t1os_chroma_is_drm_rg = chroma_is_drm_rg;\n\n"
            "  // Note: |buffer_usage| is not set. As a result, the constructed\n",
            "media/gpu/chromeos/native_pixmap_frame_resource.cc",
        )

    def native_pixmap_handle_h(text: str) -> str:
        return replace_once(
            text,
            "  uint64_t modifier = kNoModifier;\n\n"
            "  // WebGPU can directly import the handle to create texture from it.\n",
            "  uint64_t modifier = kNoModifier;\n\n"
            "  // A multi-object allocation can have one natural DRM modifier per\n"
            "  // plane. Empty means every plane uses |modifier|. T1OS uses this for\n"
            "  // NVIDIA NVDEC exports whose standalone luma and chroma objects must\n"
            "  // retain their independently calculated block heights.\n"
            "  std::vector<uint64_t> plane_modifiers;\n\n"
            "  // Exact component order of a T1OS standalone chroma object. This must\n"
            "  // not be conflated with WebGPU import capability.\n"
            "  bool t1os_chroma_is_drm_rg = false;\n\n"
            "  // WebGPU can directly import the handle to create texture from it.\n",
            "ui/gfx/native_pixmap_handle.h",
        )

    def native_pixmap_handle_cc(text: str) -> str:
        return replace_once(
            text,
            "  clone.modifier = handle.modifier;\n"
            "  clone.supports_zero_copy_webgpu_import =\n",
            "  clone.modifier = handle.modifier;\n"
            "  clone.plane_modifiers = handle.plane_modifiers;\n"
            "  clone.t1os_chroma_is_drm_rg = handle.t1os_chroma_is_drm_rg;\n"
            "  clone.supports_zero_copy_webgpu_import =\n",
            "ui/gfx/native_pixmap_handle.cc",
        )

    def native_handle_types_mojom(text: str) -> str:
        return replace_once(
            text,
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  uint64 modifier;\n\n"
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  bool supports_zero_copy_webgpu_import;\n",
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  uint64 modifier;\n\n"
            "  // Optional per-plane modifiers for multi-object DMA-BUF exports.\n"
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  array<uint64> plane_modifiers;\n\n"
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  bool t1os_chroma_is_drm_rg;\n\n"
            "  [EnableIf=is_chromeos|is_linux]\n"
            "  bool supports_zero_copy_webgpu_import;\n",
            "ui/gfx/mojom/native_handle_types.mojom",
        )

    def native_handle_types_traits_h(text: str) -> str:
        return replace_once(
            text,
            "  static uint64_t modifier(const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "    return pixmap_handle.modifier;\n"
            "  }\n"
            "#endif\n\n"
            "#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)\n"
            "  static bool supports_zero_copy_webgpu_import(\n",
            "  static uint64_t modifier(const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "    return pixmap_handle.modifier;\n"
            "  }\n"
            "  static const std::vector<uint64_t>& plane_modifiers(\n"
            "      const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "    return pixmap_handle.plane_modifiers;\n"
            "  }\n"
            "  static bool t1os_chroma_is_drm_rg(\n"
            "      const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "    return pixmap_handle.t1os_chroma_is_drm_rg;\n"
            "  }\n"
            "#endif\n\n"
            "#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)\n"
            "  static bool supports_zero_copy_webgpu_import(\n",
            "ui/gfx/mojom/native_handle_types_mojom_traits.h",
        )

    def native_handle_types_traits_cc(text: str) -> str:
        return replace_once(
            text,
            "  out->modifier = data.modifier();\n"
            "  out->supports_zero_copy_webgpu_import =\n"
            "      data.supports_zero_copy_webgpu_import();\n",
            "  out->modifier = data.modifier();\n"
            "  if (!data.ReadPlaneModifiers(&out->plane_modifiers)) {\n"
            "    return false;\n"
            "  }\n"
            "  out->t1os_chroma_is_drm_rg = data.t1os_chroma_is_drm_rg();\n"
            "  out->supports_zero_copy_webgpu_import =\n"
            "      data.supports_zero_copy_webgpu_import();\n",
            "ui/gfx/mojom/native_handle_types_mojom_traits.cc",
        )

    def stable_native_pixmap_handle_mojom(text: str) -> str:
        text = replace_once(
            text,
            "// Next min field ID: 2\n"
            "[Stable]\n"
            "struct NativePixmapHandle {\n"
            "  array<NativePixmapPlane> planes@0;\n"
            "  uint64 modifier@1;\n"
            "};\n",
            "// Next min field ID: 4\n"
            "[Stable]\n"
            "struct NativePixmapHandle {\n"
            "  array<NativePixmapPlane> planes@0;\n"
            "  uint64 modifier@1;\n"
            "  array<uint64> plane_modifiers@2;\n"
            "  bool t1os_chroma_is_drm_rg@3;\n"
            "};\n",
            "media/mojo/mojom/stable/native_pixmap_handle.mojom",
        )
        return text

    def stable_native_pixmap_handle_traits_h(text: str) -> str:
        return replace_once(
            text,
            "  static uint64_t modifier(const gfx::NativePixmapHandle& pixmap_handle);\n\n"
            "  static bool Read(media::stable::mojom::NativePixmapHandleDataView data,\n",
            "  static uint64_t modifier(const gfx::NativePixmapHandle& pixmap_handle);\n\n"
            "  static const std::vector<uint64_t>& plane_modifiers(\n"
            "      const gfx::NativePixmapHandle& pixmap_handle);\n\n"
            "  static bool t1os_chroma_is_drm_rg(\n"
            "      const gfx::NativePixmapHandle& pixmap_handle);\n\n"
            "  static bool Read(media::stable::mojom::NativePixmapHandleDataView data,\n",
            "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.h",
        )

    def stable_native_pixmap_handle_traits_cc(text: str) -> str:
        text = replace_once(
            text,
            "  return pixmap_handle.modifier;\n"
            "}\n\n"
            "// static\n"
            "bool StructTraits<media::stable::mojom::NativePixmapHandleDataView,\n",
            "  return pixmap_handle.modifier;\n"
            "}\n\n"
            "// static\n"
            "const std::vector<uint64_t>&\n"
            "StructTraits<media::stable::mojom::NativePixmapHandleDataView,\n"
            "             gfx::NativePixmapHandle>::plane_modifiers(\n"
            "    const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "  return pixmap_handle.plane_modifiers;\n"
            "}\n\n"
            "// static\n"
            "bool StructTraits<media::stable::mojom::NativePixmapHandleDataView,\n"
            "                  gfx::NativePixmapHandle>::t1os_chroma_is_drm_rg(\n"
            "    const gfx::NativePixmapHandle& pixmap_handle) {\n"
            "  return pixmap_handle.t1os_chroma_is_drm_rg;\n"
            "}\n\n"
            "// static\n"
            "bool StructTraits<media::stable::mojom::NativePixmapHandleDataView,\n",
            "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.cc",
        )
        return replace_once(
            text,
            "  out->modifier = data.modifier();\n"
            "  return data.ReadPlanes(&out->planes);\n",
            "  out->modifier = data.modifier();\n"
            "  if (!data.ReadPlaneModifiers(&out->plane_modifiers)) {\n"
            "    return false;\n"
            "  }\n"
            "  out->t1os_chroma_is_drm_rg = data.t1os_chroma_is_drm_rg();\n"
            "  return data.ReadPlanes(&out->planes);\n",
            "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.cc",
        )

    def mojo_codec_factory_cc(text: str) -> str:
        return replace_once(
            text,
            "void MojoCodecFactory::OnGetSupportedDecoderConfigs() {\n"
            "  base::AutoLock lock(supported_profiles_lock_);\n"
            "  decoder_support_notifier_.Notify();\n"
            "}\n",
            "void MojoCodecFactory::OnGetSupportedDecoderConfigs() {\n"
            "  base::AutoLock lock(supported_profiles_lock_);\n"
            "  // A GPU-process loss can race the GetSupportedConfigs reply with the\n"
            "  // decoder remote's disconnect handler. Both complete the same one-shot\n"
            "  // readiness notification; the late path must not notify twice.\n"
            "  if (decoder_support_notifier_.is_notified()) {\n"
            "    return;\n"
            "  }\n"
            "  decoder_support_notifier_.Notify();\n"
            "}\n",
            "media/mojo/clients/mojo_codec_factory.cc",
        )

    def mailbox_converter_h(text: str) -> str:
        text = replace_once(
            text,
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "      GetCommandBufferStubCB get_stub_cb);\n"
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<gpu::SharedImageInterface> sii);\n",
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "      GetCommandBufferStubCB get_stub_cb);\n"
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "      GetCommandBufferStubCB get_stub_cb,\n"
            "      bool output_mappable);\n"
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<gpu::SharedImageInterface> sii);\n"
            "  static std::unique_ptr<FrameResourceConverter> Create(\n"
            "      scoped_refptr<gpu::SharedImageInterface> sii,\n"
            "      bool output_mappable);\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.h",
        )
        text = replace_once(
            text,
            "  explicit MailboxVideoFrameConverter(\n"
            "      scoped_refptr<gpu::SharedImageInterface> sii);\n",
            "  MailboxVideoFrameConverter(\n"
            "      scoped_refptr<gpu::SharedImageInterface> sii,\n"
            "      bool output_mappable);\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.h",
        )
        return replace_once(
            text,
            "  const scoped_refptr<gpu::SharedImageInterface> shared_image_interface_;\n\n"
            "  // Mapping from the unique id of the frame to its corresponding SharedImage.\n",
            "  const scoped_refptr<gpu::SharedImageInterface> shared_image_interface_;\n"
            "  const bool output_mappable_;\n\n"
            "  // Mapping from the unique id of the frame to its corresponding SharedImage.\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.h",
        )

    def mailbox_converter_cc(text: str) -> str:
        text = replace_once(
            text,
            "#include \"media/gpu/chromeos/mailbox_video_frame_converter.h\"\n\n",
            "#include \"media/gpu/chromeos/mailbox_video_frame_converter.h\"\n\n"
            "#include <cstdlib>\n\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "  // These SharedImage can potentially be used for overlays (Scanout).\n"
            "  if (shared_image_interface_->GetCapabilities()\n"
            "          .supports_scanout_shared_images) {\n"
            "    shared_image_usage |= gpu::SHARED_IMAGE_USAGE_SCANOUT;\n"
            "  }\n",
            "  // T1OS composites decoded frames into Chromium's root surface; the\n"
            "  // decoder DMA-BUFs are never scanned out by Chromium. Advertising\n"
            "  // SCANOUT for NVIDIA's producer-owned NVDEC surfaces selects GBM/KMS\n"
            "  // import paths which are invalid for those separate native layers.\n"
            "  const bool t1os_native_decoder_surface =\n"
            "      std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "      si_format->is_multi_plane();\n"
            "  if (!t1os_native_decoder_surface &&\n"
            "      shared_image_interface_->GetCapabilities()\n"
            "          .supports_scanout_shared_images) {\n"
            "    shared_image_usage |= gpu::SHARED_IMAGE_USAGE_SCANOUT;\n"
            "  }\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<gpu::SharedImageInterface> sii) {\n"
            "  return base::WrapUnique<FrameResourceConverter>(\n"
            "      new MailboxVideoFrameConverter(std::move(sii)));\n"
            "}\n",
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<gpu::SharedImageInterface> sii) {\n"
            "  return Create(std::move(sii), /*output_mappable=*/false);\n"
            "}\n\n"
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<gpu::SharedImageInterface> sii,\n"
            "    bool output_mappable) {\n"
            "  return base::WrapUnique<FrameResourceConverter>(\n"
            "      new MailboxVideoFrameConverter(std::move(sii),\n"
            "                                     output_mappable));\n"
            "}\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "    GetCommandBufferStubCB get_stub_cb) {\n",
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "    GetCommandBufferStubCB get_stub_cb) {\n"
            "  return Create(std::move(gpu_task_runner), std::move(get_stub_cb),\n"
            "                /*output_mappable=*/false);\n"
            "}\n\n"
            "std::unique_ptr<FrameResourceConverter> MailboxVideoFrameConverter::Create(\n"
            "    scoped_refptr<base::SingleThreadTaskRunner> gpu_task_runner,\n"
            "    GetCommandBufferStubCB get_stub_cb,\n"
            "    bool output_mappable) {\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "  return Create(std::move(sii));\n"
            "}\n\n"
            "MailboxVideoFrameConverter::MailboxVideoFrameConverter(\n"
            "    scoped_refptr<gpu::SharedImageInterface> sii)\n"
            "    : shared_image_interface_(std::move(sii)) {\n",
            "  return Create(std::move(sii), output_mappable);\n"
            "}\n\n"
            "MailboxVideoFrameConverter::MailboxVideoFrameConverter(\n"
            "    scoped_refptr<gpu::SharedImageInterface> sii,\n"
            "    bool output_mappable)\n"
            "    : shared_image_interface_(std::move(sii)),\n"
            "      output_mappable_(output_mappable) {\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "  scoped_refptr<VideoFrame> mailbox_frame = VideoFrame::WrapSharedImage(\n"
            "      frame->format(), shared_image, shared_image_sync_token,\n"
            "      /*shared_image_release_cb=*/{}, frame->visible_rect(),\n"
            "      frame->natural_size(), frame->timestamp());\n",
            "  scoped_refptr<VideoFrame> mailbox_frame;\n"
            "  if (output_mappable_) {\n"
            "    mailbox_frame = VideoFrame::WrapMappableSharedImage(\n"
            "        shared_image, shared_image_sync_token,\n"
            "        /*shared_image_release_cb=*/{}, frame->visible_rect(),\n"
            "        frame->natural_size(), frame->timestamp());\n"
            "  } else {\n"
            "    mailbox_frame = VideoFrame::WrapSharedImage(\n"
            "        frame->format(), shared_image, shared_image_sync_token,\n"
            "        /*shared_image_release_cb=*/{}, frame->visible_rect(),\n"
            "        frame->natural_size(), frame->timestamp());\n"
            "  }\n"
            "  if (!mailbox_frame) {\n"
            "    return OnError(FROM_HERE, \"Failed to wrap shared image.\");\n"
            "  }\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        text = replace_once(
            text,
            "  scoped_refptr<gpu::ClientSharedImage> client_shared_image =\n"
            "      shared_image_interface_->CreateSharedImage(\n"
            "          {*si_format, shared_image_size, color_space, shared_image_usage,\n"
            "           \"MailboxVideoFrameConverter\"},\n"
            "          std::move(gpu_memory_buffer_handle));\n",
            "  const gpu::SharedImageInfo shared_image_info = {\n"
            "      *si_format, shared_image_size, color_space, shared_image_usage,\n"
            "      \"MailboxVideoFrameConverter\"};\n"
            "  scoped_refptr<gpu::ClientSharedImage> client_shared_image;\n"
            "  if (output_mappable_) {\n"
            "    client_shared_image = shared_image_interface_->CreateSharedImage(\n"
            "        shared_image_info, gpu::kNullSurfaceHandle,\n"
            "        gfx::BufferUsage::GPU_READ_CPU_READ_WRITE,\n"
            "        std::move(gpu_memory_buffer_handle));\n"
            "  } else {\n"
            "    client_shared_image = shared_image_interface_->CreateSharedImage(\n"
            "        shared_image_info, std::move(gpu_memory_buffer_handle));\n"
            "  }\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )
        return replace_once(
            text,
            "  // If format is true multiplanar format, we prefer external sampler on\n"
            "  // ChromeOS and Linux.\n"
            "  if (si_format->is_multi_plane()) {\n"
            "    si_format->SetPrefersExternalSampler();\n"
            "  }\n",
            "  // Import multiplanar decoder output as one external YUV image. T1OS's\n"
            "  // NVDEC exporter supplies one DMA-BUF object and modifier per plane;\n"
            "  // NativePixmapEGLBinding preserves that per-plane metadata on the\n"
            "  // composed NV12/P010 import. Splitting these block-linear objects into\n"
            "  // standalone R8/GR88 EGLImages is not supported by NVIDIA EGL.\n"
            "  if (si_format->is_multi_plane()) {\n"
            "    si_format->SetPrefersExternalSampler();\n"
            "    if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      VLOG(2) << \"T1OS_MEDIA_DECODER SharedImage \"\n"
            "                   \"import=external-yuv\";\n"
            "    }\n"
            "  }\n",
            "media/gpu/chromeos/mailbox_video_frame_converter.cc",
        )

    def video_resource_updater_h(text: str) -> str:
        return replace_once(
            text,
            "  std::vector<std::unique_ptr<FrameResource>> all_resources_;\n\n"
            "  base::WeakPtrFactory<VideoResourceUpdater> weak_ptr_factory_{this};\n",
            "  std::vector<std::unique_ptr<FrameResource>> all_resources_;\n"
            "  bool mappable_hardware_bridge_reported_ = false;\n\n"
            "  base::WeakPtrFactory<VideoResourceUpdater> weak_ptr_factory_{this};\n",
            "media/renderers/video_resource_updater.h",
        )

    def video_resource_updater_cc(text: str) -> str:
        return replace_once(
            text,
            "  DCHECK(video_frame->HasSharedImage() || video_frame->HasDirectCpuAccess());\n"
            "  if (video_frame->HasSharedImage()) {\n"
            "    return CreateForHardwareFrame(std::move(video_frame));\n"
            "  } else {\n"
            "    return CreateForSoftwareFrame(std::move(video_frame));\n"
            "  }\n",
            "  DCHECK(video_frame->HasSharedImage() || video_frame->HasDirectCpuAccess());\n"
            "  if (software_compositor() && video_frame->HasMappableSharedImage()) {\n"
            "    scoped_refptr<VideoFrame> mapped_frame =\n"
            "        ConvertToMemoryMappedFrame(video_frame);\n"
            "    if (!mapped_frame) {\n"
            "      if (!mappable_hardware_bridge_reported_) {\n"
            "        LOG(ERROR) << \"T1OS_MEDIA_DECODER presentation_bridge \"\n"
            "                      \"mapped=0\";\n"
            "        mappable_hardware_bridge_reported_ = true;\n"
            "      }\n"
            "      return VideoFrameExternalResource();\n"
            "    }\n"
            "    if (!mappable_hardware_bridge_reported_) {\n"
            "      LOG(INFO) << \"T1OS_MEDIA_DECODER presentation_bridge mapped=1 \"\n"
            "                << \"format=\"\n"
            "                << VideoPixelFormatToString(mapped_frame->format())\n"
            "                << \" size=\" << mapped_frame->coded_size().ToString();\n"
            "      mappable_hardware_bridge_reported_ = true;\n"
            "    }\n"
            "    return CreateForSoftwareFrame(std::move(mapped_frame));\n"
            "  }\n"
            "  if (video_frame->HasSharedImage()) {\n"
            "    return CreateForHardwareFrame(std::move(video_frame));\n"
            "  }\n"
            "  return CreateForSoftwareFrame(std::move(video_frame));\n",
            "media/renderers/video_resource_updater.cc",
        )

    def content_build(text: str) -> str:
        text = text.replace(
            '    "gpu/gpu_process_host.cc",\n'
            '    "gpu/gpu_process_host.h",\n'
            '    "gpu/t1os_media_decode_broker.cc",\n'
            '    "gpu/t1os_media_decode_broker.h",\n',
            '    "gpu/gpu_process_host.cc",\n'
            '    "gpu/gpu_process_host.h",\n',
            1,
        )
        return replace_once(
            text,
            '    "worker_host/worker_util.cc",\n'
            '    "worker_host/worker_util.h",\n'
            '  ]\n\n'
            '  if (is_android) {\n',
            '    "worker_host/worker_util.cc",\n'
            '    "worker_host/worker_util.h",\n'
            '  ]\n\n'
            '  if (enable_t1os_video_decoder) {\n'
            '    sources += [\n'
            '      "gpu/t1os_media_decode_broker.cc",\n'
            '      "gpu/t1os_media_decode_broker.h",\n'
            '    ]\n'
            '  }\n\n'
            '  if (is_android) {\n',
            "content/browser/BUILD.gn",
        )

    def gpu_host(text: str) -> str:
        text = replace_once(
            text,
            '#include "content/browser/gpu/gpu_process_host.h"\n',
            '#include "content/browser/gpu/gpu_process_host.h"\n\n'
            '#include "media/media_buildflags.h"\n'
            '#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n'
            '#include "content/browser/gpu/t1os_media_decode_broker.h"\n'
            '#include "media/base/t1os_media_switches.h"\n'
            '#endif\n',
            "content/browser/gpu/gpu_process_host.cc",
        )
        text = replace_once(
            text,
            "  ZygoteCommunication* GetZygote() override {\n"
            "    if (sandbox::policy::IsUnsandboxedSandboxType(GetSandboxType()))\n"
            "      return nullptr;\n\n"
            "    // The GPU process needs a specialized sandbox, so fork from the unsandboxed\n",
            "  ZygoteCommunication* GetZygote() override {\n"
            "    if (sandbox::policy::IsUnsandboxedSandboxType(GetSandboxType()))\n"
            "      return nullptr;\n\n"
            "    // T1OS uses Chromium's GPU-only launcher to install the measured\n"
            "    // EGL/GBM loader before the GPU sandbox is entered. A wrapper\n"
            "    // command cannot run inside a fork-only zygote, so use the browser's\n"
            "    // immutable exact launcher contract to select a direct GPU launch.\n"
            "    // Utility and renderer processes retain Chromium's normal zygotes.\n"
            "    const auto t1os_gpu_launcher =\n"
            "        base::CommandLine::ForCurrentProcess()->GetSwitchValueNative(\n"
            "            switches::kGpuLauncher);\n"
            "    if (t1os_gpu_launcher ==\n"
            "        \"/the one/software/chromium/tools/\"\n"
            "        \"t1os-chrome-subprocess\") {\n"
            "      return nullptr;\n"
            "    }\n\n"
            "    // The GPU process needs a specialized sandbox, so fork from the unsandboxed\n",
            "content/browser/gpu/gpu_process_host.cc",
        )
        text = replace_once(
            text,
            "  // If specified, prepend a launcher program to the command line.\n"
            "  if (!gpu_launcher.empty())\n"
            "    cmd_line->PrependWrapper(gpu_launcher);\n\n"
            "  std::unique_ptr<GpuSandboxedProcessLauncherDelegate> delegate =\n"
            "      std::make_unique<GpuSandboxedProcessLauncherDelegate>(*cmd_line);\n",
            "#if BUILDFLAG(IS_LINUX)\n"
            "  if (gpu_launcher ==\n"
            "      \"/the one/software/chromium/tools/t1os-chrome-subprocess\") {\n"
            "    // Preserve this exact path as one argv element and preserve the\n"
            "    // CommandLine switch boundary. BrowserChildProcessHost can then\n"
            "    // append forwarded switches without moving them ahead of the\n"
            "    // wrapped Chrome executable required at argv[1].\n"
            "    cmd_line->PrependWrapperPath(base::FilePath(gpu_launcher));\n"
            "  } else\n"
            "#endif\n"
            "  if (!gpu_launcher.empty()) {\n"
            "    cmd_line->PrependWrapper(gpu_launcher);\n"
            "  }\n\n"
            "  std::unique_ptr<GpuSandboxedProcessLauncherDelegate> delegate =\n"
            "      std::make_unique<GpuSandboxedProcessLauncherDelegate>(*cmd_line);\n",
            "content/browser/gpu/gpu_process_host.cc",
        )
        text = replace_once(
            text,
            "  // Do not call process_->Launch() here.\n",
            "  auto file_data = std::make_unique<ChildProcessLauncherFileData>();\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (kind_ == GPU_PROCESS_KIND_SANDBOXED) {\n"
            "    auto sockets = ConnectT1OSMediaDecoderPool(browser_command_line);\n"
            "    for (size_t index = 0; index < sockets.size(); ++index) {\n"
            "      file_data->files_to_preload.emplace(\n"
            "          base::StringPrintf(\"%s%zu\",\n"
            "                             media::kT1OSMediaDecodeDescriptorPrefix,\n"
            "                             index),\n"
            "          std::move(sockets[index]));\n"
            "    }\n"
            "    auto presentation =\n"
            "        ConnectT1OSPresentationBridge(browser_command_line);\n"
            "    if (presentation.socket.is_valid() &&\n"
            "        presentation.render_node.is_valid()) {\n"
            "      file_data->files_to_preload.emplace(\n"
            "          media::kT1OSPresentationDescriptor,\n"
            "          std::move(presentation.socket));\n"
            "      file_data->files_to_preload.emplace(\n"
            "          media::kT1OSPresentationRenderNodeDescriptor,\n"
            "          std::move(presentation.render_node));\n"
            "    }\n"
            "  }\n"
            "#endif\n\n"
            "  // Do not call process_->Launch() here.\n",
            "content/browser/gpu/gpu_process_host.cc",
        ).replace(
            "      /*file_data=*/\n"
            "      std::make_unique<ChildProcessLauncherFileData>());",
            "      /*file_data=*/std::move(file_data));",
            1,
        )
        text = replace_once(
            text,
            "void GpuProcessHost::OnProcessLaunched() {\n"
            "  process_start_time_ = base::TimeTicks::Now();\n",
            "void GpuProcessHost::OnProcessLaunched() {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
            "          media::kT1OSPresentationSocketSwitch)) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU process launched\";\n"
            "  }\n"
            "#endif\n"
            "  process_start_time_ = base::TimeTicks::Now();\n",
            "content/browser/gpu/gpu_process_host.cc",
        )
        return replace_once(
            text,
            "    const gfx::GpuExtraInfo& gpu_extra_info) {\n",
            "    const gfx::GpuExtraInfo& gpu_extra_info) {\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  if (base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
            "          media::kT1OSPresentationSocketSwitch)) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU DidInitialize\";\n"
            "  }\n"
            "#endif\n",
            "content/browser/gpu/gpu_process_host.cc",
        )

    def gpu_main_diagnostics(text: str) -> str:
        return replace_once(
            text,
            "  const bool init_success = gpu_init->InitializeAndStartSandbox(\n"
            "      const_cast<base::CommandLine*>(&command_line), gpu_preferences);\n",
            "  const bool init_success = gpu_init->InitializeAndStartSandbox(\n"
            "      const_cast<base::CommandLine*>(&command_line), gpu_preferences);\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE GPU init complete success=\"\n"
            "              << init_success;\n"
            "  }\n",
            "content/gpu/gpu_main.cc",
        )

    def gpu_child_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <stddef.h>\n",
            "#include <stddef.h>\n#include <cstdlib>\n",
            "content/gpu/gpu_child_thread.cc",
        )
        text = replace_once(
            text,
            "void GpuChildThread::Init(const base::TimeTicks& process_start_time) {\n",
            "void GpuChildThread::Init(const base::TimeTicks& process_start_time) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE GPU child ready\";\n"
            "  }\n",
            "content/gpu/gpu_child_thread.cc",
        )
        return replace_once(
            text,
            "void GpuChildThread::OnGpuServiceConnection(viz::GpuServiceImpl* gpu_service) {\n",
            "void GpuChildThread::OnGpuServiceConnection(viz::GpuServiceImpl* gpu_service) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE GPU service connected\";\n"
            "  }\n",
            "content/gpu/gpu_child_thread.cc",
        )

    def child_connection_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <signal.h>\n\n#include <memory>\n",
            "#include <signal.h>\n\n#include <cerrno>\n#include <cstdlib>\n#include <memory>\n",
            "content/child/child_thread_impl.cc",
        )
        text = replace_once(
            text,
            "  main_thread_runner_->PostDelayedTask(\n"
            "      FROM_HERE,\n"
            "      base::BindOnce(&ChildThreadImpl::EnsureConnected,\n"
            "                     channel_connected_factory_->GetWeakPtr(),\n"
            "                     connection_timeout),\n"
            "      base::Seconds(connection_timeout));\n",
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    // The measured T1OS child has already accepted the browser's\n"
            "    // invitation and installed its disconnect handler. On T1OS the\n"
            "    // separate Ping callback is not delivered even though the Mojo\n"
            "    // transport and attached pipes exchange data successfully. Use\n"
            "    // the live disconnect monitor as the child-liveness authority.\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child supervision=disconnect\";\n"
            "    channel_connected_factory_.reset();\n"
            "  } else {\n"
            "    main_thread_runner_->PostDelayedTask(\n"
            "        FROM_HERE,\n"
            "        base::BindOnce(&ChildThreadImpl::EnsureConnected,\n"
            "                       channel_connected_factory_->GetWeakPtr(),\n"
            "                       connection_timeout),\n"
            "        base::Seconds(connection_timeout));\n"
            "  }\n",
            "content/child/child_thread_impl.cc",
        )
        text = replace_once(
            text,
            '#include "build/build_config.h"\n',
            '#include "build/build_config.h"\n'
            '#if BUILDFLAG(IS_POSIX)\n'
            '#include <fcntl.h>\n'
            '#endif\n',
            "content/child/child_thread_impl.cc",
        )
        text = replace_once(
            text,
            "  if (!endpoint.is_valid()) {\n"
            "    endpoint =\n"
            "        mojo::PlatformChannelEndpoint(mojo::PlatformHandle(base::ScopedFD(\n"
            "            base::GlobalDescriptors::GetInstance()->Get(kMojoIPCChannel))));\n"
            "  }\n"
            "#endif\n",
            "  if (!endpoint.is_valid()) {\n"
            "    const int descriptor =\n"
            "        base::GlobalDescriptors::GetInstance()->Get(kMojoIPCChannel);\n"
            "    if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      errno = 0;\n"
            "      const int descriptor_flags = fcntl(descriptor, F_GETFD);\n"
            "      const int descriptor_errno = descriptor_flags < 0 ? errno : 0;\n"
            "      const auto* command_line = base::CommandLine::ForCurrentProcess();\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child mojo endpoint pid=\"\n"
            "                << base::GetCurrentProcId() << \" type=\"\n"
            "                << command_line->GetSwitchValueASCII(switches::kProcessType)\n"
            "                << \" utility=\"\n"
            "                << command_line->GetSwitchValueASCII(switches::kUtilitySubType)\n"
            "                << \" fd=\" << descriptor\n"
            "                << \" flags=\" << descriptor_flags\n"
            "                << \" flags_errno=\" << descriptor_errno;\n"
            "    }\n"
            "    endpoint = mojo::PlatformChannelEndpoint(\n"
            "        mojo::PlatformHandle(base::ScopedFD(descriptor)));\n"
            "  }\n"
            "#endif\n",
            "content/child/child_thread_impl.cc",
        )
        return replace_once(
            text,
            "void ChildThreadImpl::EnsureConnected(int connection_timeout) {\n"
            "  VLOG(0) << \"Terminating current process after \" << connection_timeout\n"
            "          << \" seconds with no connection.\";\n",
            "void ChildThreadImpl::EnsureConnected(int connection_timeout) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    const auto* command_line = base::CommandLine::ForCurrentProcess();\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child connection timeout pid=\"\n"
            "              << base::GetCurrentProcId() << \" type=\"\n"
            "              << command_line->GetSwitchValueASCII(switches::kProcessType)\n"
            "              << \" utility=\"\n"
            "              << command_line->GetSwitchValueASCII(switches::kUtilitySubType);\n"
            "  }\n"
            "  VLOG(0) << \"Terminating current process after \" << connection_timeout\n"
            "          << \" seconds with no connection.\";\n",
            "content/child/child_thread_impl.cc",
        )

    def child_launcher_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <optional>\n",
            "#include <cstdlib>\n#include <optional>\n",
            "content/browser/child_process_launcher_helper.cc",
        )
        text = replace_once(
            text,
            "  // Launch the child process.\n"
            "  Process process;\n",
            "  // Launch the child process.\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child launch begin type=\"\n"
            "              << command_line_->GetSwitchValueASCII(switches::kProcessType);\n"
            "  }\n"
            "  Process process;\n",
            "content/browser/child_process_launcher_helper.cc",
        )
        text = replace_once(
            text,
            "  if (is_synchronous_launch) {\n"
            "    // The LastError is set on the launcher thread, but needs to be transferred\n",
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child launch returned type=\"\n"
            "              << command_line_->GetSwitchValueASCII(switches::kProcessType)\n"
            "              << \" valid=\" << process.process.IsValid();\n"
            "  }\n\n"
            "  if (is_synchronous_launch) {\n"
            "    // The LastError is set on the launcher thread, but needs to be transferred\n",
            "content/browser/child_process_launcher_helper.cc",
        )
        return replace_once(
            text,
            "  client_task_runner_->PostTask(\n"
            "      FROM_HERE,\n",
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE child invitation sent type=\"\n"
            "              << command_line_->GetSwitchValueASCII(switches::kProcessType);\n"
            "  }\n\n"
            "  client_task_runner_->PostTask(\n"
            "      FROM_HERE,\n",
            "content/browser/child_process_launcher_helper.cc",
        )

    def mojo_channel_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <atomic>\n#include <limits>\n",
            "#include <atomic>\n#include <cstdlib>\n#include <limits>\n",
            "mojo/core/channel_posix.cc",
        )
        text = replace_once(
            text,
            "const size_t kMaxBatchReadCapacity = 256 * 1024;\n",
            "const size_t kMaxBatchReadCapacity = 256 * 1024;\n"
            "std::atomic<int> g_t1os_channel_diagnostic_count{0};\n\n"
            "bool ShouldLogT1OSChannelDiagnostic() {\n"
            "  return std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "         g_t1os_channel_diagnostic_count.fetch_add(\n"
            "             1, std::memory_order_relaxed) < 12;\n"
            "}\n",
            "mojo/core/channel_posix.cc",
        )
        text = replace_once(
            text,
            "  read_watcher_ = base::IOWatcher::Get()->WatchFileDescriptor(\n"
            "      socket_.get(), base::IOWatcher::FdWatchDuration::kPersistent,\n"
            "      base::IOWatcher::FdWatchMode::kRead, *this);\n"
            "  DCHECK(!write_watcher_);\n",
            "  read_watcher_ = base::IOWatcher::Get()->WatchFileDescriptor(\n"
            "      socket_.get(), base::IOWatcher::FdWatchDuration::kPersistent,\n"
            "      base::IOWatcher::FdWatchMode::kRead, *this);\n"
            "  if (ShouldLogT1OSChannelDiagnostic()) {\n"
            "    LOG(INFO) << \"T1OS_MOJO_CHANNEL start fd=\" << socket_.get()\n"
            "              << \" watcher=\" << static_cast<bool>(read_watcher_);\n"
            "  }\n"
            "  DCHECK(!write_watcher_);\n",
            "mojo/core/channel_posix.cc",
        )
        text = replace_once(
            text,
            "    ssize_t read_result =\n"
            "        SocketRecvmsg(socket_.get(), buffer, buffer_capacity, &incoming_fds);\n"
            "    for (auto& incoming_fd : incoming_fds) {\n",
            "    errno = 0;\n"
            "    ssize_t read_result =\n"
            "        SocketRecvmsg(socket_.get(), buffer, buffer_capacity, &incoming_fds);\n"
            "    const int read_errno = read_result < 0 ? errno : 0;\n"
            "    if (ShouldLogT1OSChannelDiagnostic()) {\n"
            "      LOG(INFO) << \"T1OS_MOJO_CHANNEL read fd=\" << socket_.get()\n"
            "                << \" result=\" << read_result\n"
            "                << \" errno=\" << read_errno\n"
            "                << \" handles=\" << incoming_fds.size();\n"
            "    }\n"
            "    for (auto& incoming_fd : incoming_fds) {\n",
            "mojo/core/channel_posix.cc",
        )
        return replace_once(
            text,
            "    if (result < 0) {\n"
            "      if (errno != EAGAIN &&\n",
            "    const int write_errno = result < 0 ? errno : 0;\n"
            "    if (ShouldLogT1OSChannelDiagnostic()) {\n"
            "      LOG(INFO) << \"T1OS_MOJO_CHANNEL write fd=\" << socket_.get()\n"
            "                << \" result=\" << result\n"
            "                << \" errno=\" << write_errno\n"
            "                << \" handles_total=\" << num_handles\n"
            "                << \" handles_sent=\" << handles_written;\n"
            "    }\n"
            "    if (result < 0) {\n"
            "      if (errno != EAGAIN &&\n",
            "mojo/core/channel_posix.cc",
        )

    def zygote_communication_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <string.h>\n",
            "#include <string.h>\n#include <cstdlib>\n",
            "content/common/zygote/zygote_communication_linux.cc",
        )
        text = replace_once(
            text,
            "    const std::string& process_type) {\n"
            "  DCHECK(init_);\n\n  base::Pickle pickle;\n",
            "    const std::string& process_type) {\n"
            "  DCHECK(init_);\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE zygote fork begin type=\"\n"
            "              << process_type << \" mappings=\" << mapping.size();\n"
            "  }\n\n"
            "  base::Pickle pickle;\n",
            "content/common/zygote/zygote_communication_linux.cc",
        )
        return replace_once(
            text,
            "    if (pid <= 0)\n"
            "      return base::kNullProcessHandle;\n"
            "  }\n",
            "    if (pid <= 0)\n"
            "      return base::kNullProcessHandle;\n"
            "    if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE zygote fork reply type=\"\n"
            "                << process_type << \" pid=\" << pid;\n"
            "    }\n"
            "  }\n",
            "content/common/zygote/zygote_communication_linux.cc",
        )

    def utility_sandbox_delegate(text: str) -> str:
        return replace_once(
            text,
            "  // TODO(crbug.com/40261714): remove this special case and fork from the\n"
            "  // zygote. For now, browser tests fail when forking the network service from\n"
            "  // the unsandboxed zygote, as the forked process only creates the\n"
            "  // NetworkServiceTestHelper if the process is exec'd.\n"
            "  if (sandbox_type_ == sandbox::mojom::Sandbox::kNetwork) {\n"
            "    return nullptr;\n"
            "  }\n\n",
            "  // T1OS routes Network Service through Chromium's existing unsandboxed\n"
            "  // zygote below. The forked child still applies kNetwork before service\n"
            "  // startup, while preserving the Mojo bootstrap that a direct exec loses\n"
            "  // under the T1OS process architecture. The removed upstream exception is\n"
            "  // needed only by NetworkServiceTestHelper in browser-test processes.\n\n",
            "content/browser/service_host/utility_sandbox_delegate.cc",
        )

    def gpu_policy(text: str) -> str:
        return replace_once(
            text,
            "      const unsigned long kAllowedMask =\n"
            "          F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW;",
            "      const unsigned long kAllowedMask =\n"
            "          F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW |\n"
            "          F_SEAL_WRITE;",
            "sandbox/policy/linux/bpf_gpu_policy_linux.cc",
        )

    def gpu_pre_sandbox_hook(text: str) -> str:
        text = replace_once(
            text,
            '#include "media/gpu/buildflags.h"\n',
            '#include "media/gpu/buildflags.h"\n'
            '#include "media/media_buildflags.h"\n',
            "content/common/gpu_pre_sandbox_hook_linux.cc",
        )
        return replace_once(
            text,
            "  std::vector<BrokerFilePermission> permissions = {\n"
            "      BrokerFilePermission::ReadOnly(kDriRcPath)};\n\n"
            "  AddVulkanICDPermissions(&permissions);",
            "  std::vector<BrokerFilePermission> permissions = {\n"
            "      BrokerFilePermission::ReadOnly(kDriRcPath)};\n"
            "#if BUILDFLAG(ENABLE_T1OS_VIDEO_DECODER)\n"
            "  // T1OS passes the render node into the GPU sandbox. NVIDIA's\n"
            "  // userspace still opens conventional /dev/nvidia* paths lazily;\n"
            "  // the measured T1OS provider translates those paths before the\n"
            "  // broker sees them. Mirror Chromium's standard presentation-node\n"
            "  // permissions at their translated destinations so first-swap\n"
            "  // EGLStream DMA-BUF export is not denied after sandbox entry.\n"
            "  // UVM, CUDA, and NVDEC devices remain unavailable to Chromium.\n"
            "  static constexpr const char* kT1OSNvidiaPresentationLibraries[] = {\n"
            "      \"/the one/catalogue/graphics/nvidia/gbm/nvidia-drm_gbm.so\",\n"
            "      \"/the one/catalogue/graphics/nvidia/libnvidia-egl-gbm.so.1\",\n"
            "  };\n"
            "  for (const char* library : kT1OSNvidiaPresentationLibraries) {\n"
            "    permissions.push_back(BrokerFilePermission::ReadOnly(library));\n"
            "  }\n"
            "  static constexpr const char* kT1OSNvidiaPresentationNodes[] = {\n"
            "      \"/the one/drivers/nodes/nvidiactl\",\n"
            "      \"/the one/drivers/nodes/nvidia-modeset\",\n"
            "  };\n"
            "  for (const char* node : kT1OSNvidiaPresentationNodes) {\n"
            "    permissions.push_back(BrokerFilePermission::ReadWrite(node));\n"
            "  }\n"
            "  for (int i = 0; i < 10; ++i) {\n"
            "    permissions.push_back(BrokerFilePermission::ReadWrite(\n"
            "        base::StringPrintf(\"/the one/drivers/nodes/nvidia%d\", i)));\n"
            "  }\n"
            "  permissions.push_back(BrokerFilePermission::ReadOnly(\n"
            "      \"/the one/drivers/processes/driver/nvidia/params\"));\n"
            "#endif\n\n"
            "  AddVulkanICDPermissions(&permissions);",
            "content/common/gpu_pre_sandbox_hook_linux.cc",
        )

    def sandbox_build(text: str) -> str:
        return replace_once(
            text,
            '    sources += [ "linux/bpf_speech_recognition_policy_linux_unittest.cc" ]\n',
            '    sources += [\n'
            '      "linux/bpf_speech_recognition_policy_linux_unittest.cc",\n'
            '      "linux/t1os_gpu_seal_policy_unittest.cc",\n'
            '    ]\n',
            "sandbox/policy/BUILD.gn",
        )

    def dns_config_linux(text: str) -> str:
        return replace_once(
            text,
            "#ifndef _PATH_RESCONF  // Normally defined in <resolv.h>\n"
            '#define _PATH_RESCONF FILE_PATH_LITERAL("/etc/resolv.conf")\n'
            "#endif\n\n"
            "constexpr base::FilePath::CharType kFilePathResolv[] = "
            "_PATH_RESCONF;",
            "// T1OS owns resolver configuration and creates this file before\n"
            "// Chromium starts. libc is patched to read the same path.\n"
            "constexpr base::FilePath::CharType kFilePathResolv[] =\n"
            '    FILE_PATH_LITERAL("/the one/settings/network/dns.txt");',
            "net/dns/dns_config_service_linux.cc",
        )

    def network_sandbox_linux(text: str) -> str:
        return replace_once(
            text,
            'base::FilePath("/etc/hosts"), '
            'base::FilePath("/etc/resolv.conf"),',
            'base::FilePath("/etc/hosts"),\n'
            '      base::FilePath("/the one/settings/network/dns.txt"),',
            "services/network/network_sandbox_hook_linux.cc",
        )

    def metrics_enums(text: str) -> str:
        return replace_once(
            text,
            '  <int value="19" label="VideoToolbox Video Decoder"/>\n'
            '</enum>\n\n'
            '<enum name="VideoEncoderUseCase">',
            '  <int value="19" label="VideoToolbox Video Decoder"/>\n'
            '  <int value="20" label="T1OS Video Decoder"/>\n'
            '</enum>\n\n'
            '<enum name="VideoEncoderUseCase">',
            "tools/metrics/histograms/enums.xml",
        )

    def ozone_imported_native_pixmap(text: str) -> str:
        return replace_once(
            text,
            "  auto* factory = ui::OzonePlatform::GetInstance()->"
            "GetSurfaceFactoryOzone();\n"
            "  if (!factory->CanCreateNativePixmapForFormat(format)) {\n"
            "    return false;\n"
            "  }\n",
            "  auto* factory = ui::OzonePlatform::GetInstance()->"
            "GetSurfaceFactoryOzone();\n"
            "  // An imported NATIVE_PIXMAP already owns its allocation. "
            "Requiring the\n"
            "  // display platform to allocate the same format incorrectly "
            "rejects direct\n"
            "  // EGL DMA-BUF import on X11 servers without DRI3 (including "
            "T1OS).\n"
            "  if (gmb_type != gfx::NATIVE_PIXMAP &&\n"
            "      !factory->CanCreateNativePixmapForFormat(format)) {\n"
            "    return false;\n"
            "  }\n",
            "gpu/command_buffer/service/shared_image/"
            "ozone_image_backing_factory.cc",
        )

    def t1os_nvdec_planar_textures(text: str) -> str:
        text = replace_once(
            text,
            '#include "gpu/command_buffer/service/shared_image/'
            'ozone_image_gl_textures_holder.h"\n\n#include <memory>\n',
            '#include "gpu/command_buffer/service/shared_image/'
            'ozone_image_gl_textures_holder.h"\n\n#include <cstdlib>\n'
            '#include <memory>\n',
            "gpu/command_buffer/service/shared_image/"
            "ozone_image_gl_textures_holder.cc",
        )
        return replace_once(
            text,
            "  if (format.PrefersExternalSampler()) {\n"
            "    target = GL_TEXTURE_EXTERNAL_OES;\n"
            "  } else {\n"
            "    target = GL_TEXTURE_2D;\n"
            "  }\n",
            "  if (format.PrefersExternalSampler()) {\n"
            "    target = GL_TEXTURE_EXTERNAL_OES;\n"
            "  } else {\n"
            "    target = GL_TEXTURE_2D;\n"
            "    if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "        format.is_multi_plane() && plane_index == 0) {\n"
            "      LOG(INFO) << \"T1OS_MEDIA_DECODER texture_target=2d \"\n"
            "                   \"composition=chromium-planar\";\n"
            "    }\n"
            "  }\n",
            "gpu/command_buffer/service/shared_image/"
            "ozone_image_gl_textures_holder.cc",
        )

    def t1os_implicit_linear_egl_import(text: str) -> str:
        text = replace_once(
            text,
            "#include <array>\n",
            "#include <array>\n#include <cstdlib>\n",
            "ui/ozone/common/native_pixmap_egl_binding.cc",
        )
        text = replace_once(
            text,
            "#define DRM_FORMAT_GR88 FOURCC('G', 'R', '8', '8')\n"
            "#define DRM_FORMAT_GR1616 FOURCC('G', 'R', '3', '2')\n",
            "#define DRM_FORMAT_GR88 FOURCC('G', 'R', '8', '8')\n"
            "#define DRM_FORMAT_GR1616 FOURCC('G', 'R', '3', '2')\n"
            "#define DRM_FORMAT_RG88 FOURCC('R', 'G', '8', '8')\n"
            "#define DRM_FORMAT_RG1616 FOURCC('R', 'G', '3', '2')\n",
            "ui/ozone/common/native_pixmap_egl_binding.cc",
        )
        text = replace_once(
            text,
            "  attrs.push_back(EGL_HEIGHT);\n"
            "  attrs.push_back(size_.height());\n"
            "  attrs.push_back(EGL_LINUX_DRM_FOURCC_EXT);\n"
            "  attrs.push_back(GetFourCCFormatFromSharedImageFormat(format_));\n",
            "  attrs.push_back(EGL_HEIGHT);\n"
            "  attrs.push_back(size_.height());\n"
            "  attrs.push_back(EGL_LINUX_DRM_FOURCC_EXT);\n"
            "  int import_fourcc = GetFourCCFormatFromSharedImageFormat(format_);\n"
            "  if (plane_index_ == 1) {\n"
            "    // The T1OS decoder carries NVIDIA's exact UV component ordering in\n"
            "    // a dedicated NativePixmapHandle field. This is independent of the\n"
            "    // presentation bridge and of WebGPU import capability.\n"
            "    gfx::NativePixmapHandle producer_handle = pixmap->ExportHandle();\n"
            "    if (producer_handle.t1os_chroma_is_drm_rg) {\n"
            "      if (import_fourcc == DRM_FORMAT_GR88) {\n"
            "        import_fourcc = DRM_FORMAT_RG88;\n"
            "      } else if (import_fourcc == DRM_FORMAT_GR1616) {\n"
            "        import_fourcc = DRM_FORMAT_RG1616;\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "  attrs.push_back(import_fourcc);\n",
            "ui/ozone/common/native_pixmap_egl_binding.cc",
        )
        text = replace_once(
            text,
            "      uint64_t modifier = pixmap->GetFormatModifier();\n"
            "      if (has_dma_buf_import_modifier &&\n"
            "          modifier != gfx::NativePixmapHandle::kNoModifier) {\n",
            "      gfx::NativePixmapHandle producer_handle = pixmap->ExportHandle();\n"
            "      uint64_t modifier = pixmap->GetFormatModifier();\n"
            "      if (producer_handle.plane_modifiers.size() ==\n"
            "              pixmap->GetNumberOfPlanes() &&\n"
            "          producer_handle.plane_modifiers[attrs_plane] !=\n"
            "              gfx::NativePixmapHandle::kNoModifier) {\n"
            "        modifier = producer_handle.plane_modifiers[attrs_plane];\n"
            "      }\n"
            "      // NVIDIA's EGLDevice path does not advertise DRM linear as an\n"
            "      // explicit modifier, but accepts the same linear DMA-BUF through\n"
            "      // the base EGL_EXT_image_dma_buf_import contract. Keep explicit\n"
            "      // modifier attributes for native NVDEC surfaces and omit them only\n"
            "      // for T1OS's composed linear root transport.\n"
            "      const bool t1os_implicit_linear =\n"
            "          getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "          modifier == 0;\n"
            "      if (t1os_implicit_linear && attrs_plane == 0) {\n"
            "        LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE EGL import \"\n"
            "                     \"modifier policy=implicit-linear\";\n"
            "      }\n"
            "      if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "          format_.is_multi_plane()) {\n"
            "        VLOG(2) << \"T1OS_MEDIA_DECODER EGL external plane=\"\n"
            "                  << attrs_plane\n"
            "                  << \" pitch=\" << pixmap->GetDmaBufPitch(attrs_plane)\n"
            "                  << \" offset=\" << pixmap->GetDmaBufOffset(attrs_plane)\n"
            "                  << \" modifier=\" << modifier;\n"
            "      }\n"
            "      if (has_dma_buf_import_modifier && !t1os_implicit_linear &&\n"
            "          modifier != gfx::NativePixmapHandle::kNoModifier) {\n",
            "ui/ozone/common/native_pixmap_egl_binding.cc",
        )
        return replace_once(
            text,
            "    attrs.push_back(EGL_DMA_BUF_PLANE0_PITCH_EXT);\n"
            "    attrs.push_back(pixmap->GetDmaBufPitch(pixmap_plane));\n"
            "    attrs.push_back(EGL_NONE);\n",
            "    attrs.push_back(EGL_DMA_BUF_PLANE0_PITCH_EXT);\n"
            "    attrs.push_back(pixmap->GetDmaBufPitch(pixmap_plane));\n"
            "\n"
            "    // Multiplanar SharedImages import each selected NV12/P010 plane\n"
            "    // as plane 0 of a single-plane EGLImage. NVIDIA's standalone plane\n"
            "    // objects can have different natural block heights, so select the\n"
            "    // modifier belonging to this exact DMA-BUF object.\n"
            "    gfx::NativePixmapHandle producer_handle = pixmap->ExportHandle();\n"
            "    uint64_t modifier = pixmap->GetFormatModifier();\n"
            "    if (producer_handle.plane_modifiers.size() ==\n"
            "            pixmap->GetNumberOfPlanes() &&\n"
            "        producer_handle.plane_modifiers[pixmap_plane] !=\n"
            "            gfx::NativePixmapHandle::kNoModifier) {\n"
            "      modifier = producer_handle.plane_modifiers[pixmap_plane];\n"
            "    }\n"
            "    VLOG(2) << \"T1OS_MEDIA_DECODER EGL plane=\" << pixmap_plane\n"
            "              << \" fourcc=\" << import_fourcc\n"
            "              << \" size=\" << size_.ToString()\n"
            "              << \" pitch=\" << pixmap->GetDmaBufPitch(pixmap_plane)\n"
            "              << \" offset=\" << pixmap->GetDmaBufOffset(pixmap_plane)\n"
            "              << \" modifier=\" << modifier;\n"
            "    if (gl::GLSurfaceEGL::GetGLDisplayEGL()\n"
            "            ->ext->b_EGL_EXT_image_dma_buf_import_modifiers &&\n"
            "        modifier != gfx::NativePixmapHandle::kNoModifier &&\n"
            "        modifier != 0) {\n"
            "      attrs.push_back(EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT);\n"
            "      PushEGLintOrDie(modifier & 0xffffffff, attrs);\n"
            "      attrs.push_back(EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT);\n"
            "      PushEGLintOrDie(static_cast<uint32_t>(modifier >> 32), attrs);\n"
            "    }\n"
            "    attrs.push_back(EGL_NONE);\n",
            "ui/ozone/common/native_pixmap_egl_binding.cc",
        )

    def linux_validating_command_decoder(text: str) -> str:
        text = replace_once(
            text,
            "#if !BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER)\n"
            "  if (switch_value == kCmdDecoderValidatingName) {",
            "// Linux already compiles GLES2DecoderImpl for its GPU fuzzer. T1OS\n"
            "// native NVIDIA EGL must be allowed to select that implementation:\n"
            "// passthrough adds ANGLE-only global texture-share-group attributes.\n"
            "#if !BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER) && \\\n"
            "    !BUILDFLAG(IS_LINUX)\n"
            "  if (switch_value == kCmdDecoderValidatingName) {",
            "ui/gl/gl_utils.cc",
        )
        return replace_once(
            text,
            "#endif  // !BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER)\n",
            "#endif  // !ENABLE_VALIDATING_COMMAND_DECODER && !IS_LINUX\n",
            "ui/gl/gl_utils.cc",
        )

    def linux_gpu_init_validating_decoder(text: str) -> str:
        text = replace_once(
            text,
            "#if BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER)\n"
            "  bool is_swangle = impl == gl::ANGLEImplementation::kSwiftShader;",
            "// T1OS selects Chromium's already-built Linux validating decoder for\n"
            "// native NVIDIA EGL; preserve the command-line preference here.\n"
            "#if BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER) || \\\n"
            "    BUILDFLAG(IS_LINUX)\n"
            "  bool is_swangle = impl == gl::ANGLEImplementation::kSwiftShader;",
            "gpu/ipc/service/gpu_init.cc",
        )
        return replace_once(
            text,
            "#endif  // BUILDFLAG(ENABLE_VALIDATING_COMMAND_DECODER)\n",
            "#endif  // ENABLE_VALIDATING_COMMAND_DECODER || IS_LINUX\n",
            "gpu/ipc/service/gpu_init.cc",
        )

    def x11_direct_dmabuf_import(text: str) -> str:
        text = replace_once(
            text,
            "#include <memory>\n",
            "#include <algorithm>\n"
            "#include <array>\n"
            "#include <cstdlib>\n"
            "#include <memory>\n"
            "#include <vector>\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            '#include "ui/gl/gl_surface_egl.h"\n',
            '#include "ui/gl/gl_surface_egl.h"\n'
            '#include "ui/gl/presenter.h"\n'
            '#include "ui/gl/scoped_egl_image.h"\n',
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            '#include "ui/gfx/linux/gbm_support_x11.h"\n',
            '#include "ui/gfx/linux/gbm_support_x11.h"\n'
            '#include "ui/gfx/linux/drm_util_linux.h"\n'
            '#include "ui/gfx/buffer_usage_util.h"\n',
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            '#include "ui/ozone/platform/x11/native_pixmap_egl_x11_binding.h"\n',
            '#include "ui/ozone/platform/x11/native_pixmap_egl_x11_binding.h"\n'
            '#include "ui/ozone/platform/x11/t1os_gbm_pixmap.h"\n'
            '#include "ui/ozone/platform/x11/t1os_surfaceless.h"\n',
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "namespace ui {\nnamespace {\n",
            "#ifndef EGL_PLATFORM_GBM_KHR\n"
            "#define EGL_PLATFORM_GBM_KHR 0x31D7\n"
            "#endif\n\n"
            "namespace ui {\nnamespace {\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "enum class NativePixmapSupportType {\n",
            "std::vector<uint64_t> GetT1OSDmaBufModifiers(\n"
            "    viz::SharedImageFormat format, bool allow_external_only) {\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") == nullptr) {\n"
            "    return {};\n"
            "  }\n"
            "  auto* display = gl::GLSurfaceEGL::GetGLDisplayEGL();\n"
            "  if (!display || !display->IsInitialized() ||\n"
            "      !display->ext->b_EGL_EXT_image_dma_buf_import_modifiers) {\n"
            "    return {};\n"
            "  }\n"
            "  const EGLint fourcc = static_cast<EGLint>(\n"
            "      ui::GetFourCCFormatFromSharedImageFormat(format));\n"
            "  EGLint format_count = 0;\n"
            "  if (!eglQueryDmaBufFormatsEXT(display->GetDisplay(), 0, nullptr,\n"
            "                                &format_count) ||\n"
            "      format_count <= 0) {\n"
            "    return {};\n"
            "  }\n"
            "  std::vector<EGLint> formats(format_count);\n"
            "  if (!eglQueryDmaBufFormatsEXT(display->GetDisplay(), format_count,\n"
            "                                formats.data(), &format_count) ||\n"
            "      !std::ranges::contains(formats, fourcc)) {\n"
            "    LOG(ERROR) << \"T1OS_PRESENTATION_BRIDGE EGL display does not \"\n"
            "                  \"advertise format=\"\n"
            "               << format.ToString() << \" fourcc=\" << fourcc;\n"
            "    return {};\n"
            "  }\n"
            "  EGLint count = 0;\n"
            "  if (!eglQueryDmaBufModifiersEXT(display->GetDisplay(), fourcc, 0,\n"
            "                                  nullptr, nullptr, &count) ||\n"
            "      count <= 0) {\n"
            "    return {};\n"
            "  }\n"
            "  std::vector<EGLuint64KHR> queried(count);\n"
            "  std::vector<EGLBoolean> external_only(count);\n"
            "  if (!eglQueryDmaBufModifiersEXT(\n"
            "          display->GetDisplay(), fourcc, count, queried.data(),\n"
            "          external_only.data(), &count) ||\n"
            "      count <= 0) {\n"
            "    return {};\n"
            "  }\n"
            "  std::vector<uint64_t> modifiers;\n"
            "  modifiers.reserve(count);\n"
            "  for (EGLint index = 0; index < count; ++index) {\n"
            "    if (allow_external_only || external_only[index] == EGL_FALSE) {\n"
            "      modifiers.push_back(queried[index]);\n"
            "    }\n"
            "  }\n"
            "  // Prefer NVIDIA block-linear layouts; keep linear as an\n"
            "  // advertised fallback instead of making it a requirement.\n"
            "  std::stable_partition(modifiers.begin(), modifiers.end(),\n"
            "                        [](uint64_t modifier) {\n"
            "                          return modifier != 0;\n"
            "                        });\n"
            "  return modifiers;\n"
            "}\n\n"
            "bool T1OSRootBufferImports(const GbmBuffer& buffer,\n"
            "                            viz::SharedImageFormat format,\n"
            "                            const gfx::Size& size) {\n"
            "  auto* display = gl::GLSurfaceEGL::GetGLDisplayEGL();\n"
            "  if (!display || !display->IsInitialized() ||\n"
            "      buffer.GetNumPlanes() != 1 || !buffer.AreFdsValid()) {\n"
            "    return false;\n"
            "  }\n"
            "  const uint64_t modifier = buffer.GetFormatModifier();\n"
            "  const std::array<EGLint, 17> attributes = {\n"
            "      EGL_WIDTH, size.width(), EGL_HEIGHT, size.height(),\n"
            "      EGL_LINUX_DRM_FOURCC_EXT,\n"
            "      static_cast<EGLint>(GetFourCCFormatFromSharedImageFormat(format)),\n"
            "      EGL_DMA_BUF_PLANE0_FD_EXT, buffer.GetPlaneFd(0),\n"
            "      EGL_DMA_BUF_PLANE0_OFFSET_EXT,\n"
            "      static_cast<EGLint>(buffer.GetPlaneOffset(0)),\n"
            "      EGL_DMA_BUF_PLANE0_PITCH_EXT,\n"
            "      static_cast<EGLint>(buffer.GetPlaneStride(0)),\n"
            "      EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT,\n"
            "      static_cast<EGLint>(modifier & 0xffffffffu),\n"
            "      EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT,\n"
            "      static_cast<EGLint>(modifier >> 32), EGL_NONE};\n"
            "  auto image = gl::MakeScopedEGLImage(\n"
            "      EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT,\n"
            "      static_cast<EGLClientBuffer>(nullptr), attributes.data());\n"
            "  if (!image.get()) {\n"
            "    LOG(WARNING) << \"T1OS_PRESENTATION_BRIDGE root import preflight \"\n"
            "                    \"rejected modifier=\"\n"
            "                 << modifier;\n"
            "    return false;\n"
            "  }\n"
            "  LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE root import preflight accepted modifier=\"\n"
            "            << modifier;\n"
            "  return true;\n"
            "}\n\n"
            "enum class NativePixmapSupportType {\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "      case NativePixmapSupportType::kDMABuf: {\n"
            "        return NativePixmapEGLBinding::IsSharedImageFormatSupported(format);\n"
            "      }\n",
            "      case NativePixmapSupportType::kDMABuf: {\n"
            "        if (!NativePixmapEGLBinding::IsSharedImageFormatSupported(format)) {\n"
            "          return false;\n"
            "        }\n"
            "        if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "          return !GetT1OSDmaBufModifiers(\n"
            "                      format, /*allow_external_only=*/true)\n"
            "                      .empty();\n"
            "        }\n"
            "        return true;\n"
            "      }\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  scoped_refptr<gl::GLSurface> CreateViewGLSurface(\n"
            "      gl::GLDisplay* display,\n"
            "      gfx::AcceleratedWidget window) override {\n"
            "    if (is_swiftshader_) {\n",
            "  scoped_refptr<gl::Presenter> CreateSurfacelessViewGLSurface(\n"
            "      gl::GLDisplay* display,\n"
            "      gfx::AcceleratedWidget window) override {\n"
            "    if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE surface request \"\n"
            "                   \"kind=surfaceless window=\"\n"
            "                << window << \" result=unsupported\";\n"
            "    }\n"
            "    return GLOzoneEGL::CreateSurfacelessViewGLSurface(display, window);\n"
            "  }\n\n"
            "  scoped_refptr<gl::GLSurface> CreateViewGLSurface(\n"
            "      gl::GLDisplay* display,\n"
            "      gfx::AcceleratedWidget window) override {\n"
            "    if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE surface request \"\n"
            "                   \"kind=view window=\"\n"
            "                << window << \" software=\" << is_swiftshader_\n"
            "                << \" owner_claimed=\"\n"
            "                << t1os_presentation_owner_claimed_;\n"
            "    }\n"
            "    if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "        !is_swiftshader_) {\n"
            "      auto* egl_display = display->GetAs<gl::GLDisplayEGL>();\n"
            "      if (!t1os_presentation_owner_claimed_) {\n"
            "        scoped_refptr<T1OSGbmSurface> root =\n"
            "            T1OSGbmSurface::Create(egl_display, window);\n"
            "        if (root) {\n"
            "          t1os_presentation_owner_claimed_ = true;\n"
            "        }\n"
            "        return root;\n"
            "      }\n"
            "      // Presentation v1 has one visible root. Keep a second\n"
            "      // DesktopWindowTreeHost on a valid same-display surface so\n"
            "      // it cannot turn into a persistent GPU context-loss loop.\n"
            "      return T1OSAuxiliarySurface::Create(egl_display, window);\n"
            "    }\n"
            "    if (is_swiftshader_) {\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  gl::EGLDisplayPlatform GetNativeDisplay() override {\n"
            "    return gl::EGLDisplayPlatform(reinterpret_cast<EGLNativeDisplayType>(\n"
            "        x11::Connection::Get()->GetXlibDisplay().display()));\n"
            "  }\n",
            "  gl::EGLDisplayPlatform GetNativeDisplay() override {\n"
            "    if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "      gbm_device* gbm_device =\n"
            "          ui::GBMSupportX11::GetInstance()->GetNativeDevice();\n"
            "      if (gbm_device) {\n"
            "        LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE EGL platform=gbm shared_device=1\";\n"
            "        return gl::EGLDisplayPlatform(\n"
            "            reinterpret_cast<EGLNativeDisplayType>(gbm_device),\n"
            "            EGL_PLATFORM_GBM_KHR);\n"
            "      }\n"
            "      LOG(ERROR) << \"T1OS_PRESENTATION_BRIDGE brokered GBM \"\n"
            "                    \"device unavailable; refusing path discovery\";\n"
            "      return gl::EGLDisplayPlatform(\n"
            "          EGLNativeDisplayType{},\n"
            "          EGL_PLATFORM_GBM_KHR);\n"
            "    }\n"
            "    return gl::EGLDisplayPlatform(reinterpret_cast<EGLNativeDisplayType>(\n"
            "        x11::Connection::Get()->GetXlibDisplay().display()));\n"
            "  }\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  scoped_refptr<gfx::NativePixmapDmaBuf> pixmap;\n"
            "  auto buffer =\n"
            "      ui::GBMSupportX11::GetInstance()->CreateBuffer(format, size, usage);\n"
            "  if (buffer) {\n"
            "    gfx::NativePixmapHandle handle = buffer->ExportHandle();\n"
            "    if (handle.planes.empty()) {\n"
            "      return nullptr;\n"
            "    }\n"
            "    pixmap = base::MakeRefCounted<gfx::NativePixmapDmaBuf>(size, format,\n"
            "                                                           std::move(handle));\n"
            "  }\n\n"
            "  // CreateNativePixmap is non-blocking operation. Thus, it is safe to call it\n"
            "  // and return the result with the provided callback.\n"
            "  return pixmap;\n",
            "  auto* gbm_support = ui::GBMSupportX11::GetInstance();\n"
            "  std::unique_ptr<GbmBuffer> buffer;\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    std::vector<uint64_t> modifiers = GetT1OSDmaBufModifiers(\n"
            "        format, /*allow_external_only=*/false);\n"
            "    if (modifiers.empty()) {\n"
            "      LOG(ERROR) << \"T1OS_PRESENTATION_BRIDGE no renderable EGL \"\n"
            "                    \"DMA-BUF modifier for format=\"\n"
            "                 << format.ToString();\n"
            "      return nullptr;\n"
            "    }\n"
            "    // Chromium's composed root is never scanned out by Chromium: it is\n"
            "    // exported to WindowServer and sampled there. Allocate it for GPU\n"
            "    // rendering, then test each advertised modifier with the exact EGL\n"
            "    // DMA-BUF import that Chromium will use. This prevents NVIDIA from\n"
            "    // accepting a GBM allocation that its EGL importer later rejects.\n"
            "    // Imported NVDEC NV12/P010 surfaces retain their native modifiers\n"
            "    // and do not use this root-allocation path.\n"
            "    if ((usage == gfx::BufferUsage::SCANOUT ||\n"
            "         usage == gfx::BufferUsage::GPU_READ) &&\n"
            "        format.is_single_plane()) {\n"
            "      for (const uint64_t modifier : modifiers) {\n"
            "        auto candidate = gbm_support->CreateBufferWithModifiers(\n"
            "            format, size, usage, std::vector<uint64_t>{modifier},\n"
            "            /*require_rendering=*/true);\n"
            "        if (candidate &&\n"
            "            T1OSRootBufferImports(*candidate, format, size)) {\n"
            "          buffer = std::move(candidate);\n"
            "          break;\n"
            "        }\n"
            "      }\n"
            "      if (!buffer) {\n"
            "        LOG(ERROR) << \"T1OS_PRESENTATION_BRIDGE native renderable \"\n"
            "                      \"root transport allocation failed\";\n"
            "        return nullptr;\n"
            "      }\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE root transport \"\n"
            "                   \"modifier policy=egl-preflighted \"\n"
            "                   \"render_target=1 scanout=0\";\n"
            "    }\n"
            "    if (!buffer) {\n"
            "      buffer = gbm_support->CreateBufferWithModifiers(\n"
            "          format, size, usage, modifiers,\n"
            "          /*require_rendering=*/false);\n"
            "    }\n"
            "  } else {\n"
            "    buffer = gbm_support->CreateBuffer(format, size, usage);\n"
            "  }\n"
            "  if (!buffer) {\n"
            "    return nullptr;\n"
            "  }\n"
            "  LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE GBM allocation format=\"\n"
            "            << format.ToString() << \" size=\" << size.ToString()\n"
            "            << \" usage=\" << gfx::BufferUsageToString(usage)\n"
            "            << \" modifier=\" << buffer->GetFormatModifier()\n"
            "            << \" planes=\" << buffer->GetNumPlanes();\n"
            "  return base::MakeRefCounted<T1OSGbmPixmap>(std::move(buffer));\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  scoped_refptr<gfx::NativePixmapDmaBuf> pixmap;\n"
            "  auto buffer = ui::GBMSupportX11::GetInstance()->"
            "CreateBufferFromHandle(\n"
            "      size, format, std::move(handle));\n"
            "  if (buffer) {\n"
            "    gfx::NativePixmapHandle buffer_handle = "
            "buffer->ExportHandle();\n"
            "    if (buffer_handle.planes.empty()) {\n"
            "      return nullptr;\n"
            "    }\n"
            "    pixmap = base::MakeRefCounted<gfx::NativePixmapDmaBuf>(\n"
            "        size, format, std::move(buffer_handle));\n"
            "  }\n"
            "  return pixmap;\n",
            "  scoped_refptr<gfx::NativePixmapDmaBuf> pixmap;\n"
            "  auto* gbm_support = ui::GBMSupportX11::GetInstance();\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "      format.is_multi_plane()) {\n"
            "    // Decoder surfaces already are producer-owned NVIDIA DMA-BUFs.\n"
            "    // Preserve their exact per-plane descriptors, pitches, offsets,\n"
            "    // and block-linear modifier for EGL. Re-importing the composed\n"
            "    // NV12/P010 handle through GBM changes that ownership/layout\n"
            "    // contract and corrupts NVIDIA's GL context during composition.\n"
            "    pixmap = base::MakeRefCounted<gfx::NativePixmapDmaBuf>(\n"
            "        size, format, std::move(handle));\n"
            "    if (!pixmap->AreDmaBufFdsValid()) {\n"
            "      return nullptr;\n"
            "    }\n"
            "    VLOG(2) << \"T1OS_MEDIA_DECODER native pixmap import=direct-dmabuf \"\n"
            "                 \"format=\"\n"
            "              << format.ToString() << \" planes=\"\n"
            "              << pixmap->GetNumberOfPlanes() << \" modifier=\"\n"
            "              << pixmap->GetFormatModifier();\n"
            "    return pixmap;\n"
            "  }\n"
            "  if (gbm_support->has_gbm_device()) {\n"
            "    auto buffer = gbm_support->CreateBufferFromHandle(\n"
            "        size, format, std::move(handle));\n"
            "    if (!buffer) {\n"
            "      return nullptr;\n"
            "    }\n"
            "    return base::MakeRefCounted<T1OSGbmPixmap>(std::move(buffer));\n"
            "  }\n"
            "\n"
            "  // X11/DRI3 is needed to allocate GBM buffers, but not to "
            "import an\n"
            "  // existing DMA-BUF through EGL_EXT_image_dma_buf_import. "
            "Mirror the\n"
            "  // direct NativePixmapDmaBuf fallback used by Ozone Wayland.\n"
            "  if (GetNativePixmapSupportType() != "
            "NativePixmapSupportType::kDMABuf) {\n"
            "    return nullptr;\n"
            "  }\n"
            "  pixmap = base::MakeRefCounted<gfx::NativePixmapDmaBuf>(\n"
            "      size, format, std::move(handle));\n"
            "  return pixmap->AreDmaBufFdsValid() ? pixmap : nullptr;\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "bool X11SurfaceFactory::CanCreateNativePixmapForFormat(\n"
            "    viz::SharedImageFormat format) {\n"
            "  return ui::GBMSupportX11::GetInstance()->CanCreateBufferForFormat(format);\n"
            "}\n",
            "bool X11SurfaceFactory::CanCreateNativePixmapForFormat(\n"
            "    viz::SharedImageFormat format) {\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr &&\n"
            "      GetT1OSDmaBufModifiers(\n"
            "          format, /*allow_external_only=*/false)\n"
            "          .empty()) {\n"
            "    return false;\n"
            "  }\n"
            "  return ui::GBMSupportX11::GetInstance()->CanCreateBufferForFormat(format);\n"
            "}\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  return std::vector<gl::GLImplementationParts>{\n"
            "      gl::GLImplementationParts(gl::kGLImplementationEGLANGLE),\n"
            "  };\n",
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    return {gl::GLImplementationParts(\n"
            "        gl::kGLImplementationEGLGLES2)};\n"
            "  }\n"
            "  return {gl::GLImplementationParts(\n"
            "      gl::kGLImplementationEGLANGLE)};\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        text = replace_once(
            text,
            "  bool is_swiftshader_ = false;\n",
            "  bool is_swiftshader_ = false;\n"
            "  bool t1os_presentation_owner_claimed_ = false;\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )
        return replace_once(
            text,
            "    case gl::kGLImplementationEGLANGLE:\n"
            "      return egl_implementation_.get();\n",
            "    case gl::kGLImplementationEGLGLES2:\n"
            "    case gl::kGLImplementationEGLANGLE:\n"
            "      return egl_implementation_.get();\n",
            "ui/ozone/platform/x11/x11_surface_factory.cc",
        )

    def x11_presentation_build(text: str) -> str:
        text = replace_once(
            text,
            '    "os_exchange_data_provider_x11.cc",\n',
            '    "os_exchange_data_provider_x11.cc",\n'
            '    "t1os_gbm_pixmap.cc",\n'
            '    "t1os_gbm_pixmap.h",\n'
            '    "t1os_surfaceless.cc",\n'
            '    "t1os_surfaceless.h",\n',
            "ui/ozone/platform/x11/BUILD.gn",
        )
        return replace_once(
            text,
            '    "//ui/gfx/linux:gbm",\n',
            '    "//build/config/linux/libdrm",\n'
            '    "//ui/gfx/linux:drm",\n'
            '    "//ui/gfx/linux:gbm",\n',
            "ui/ozone/platform/x11/BUILD.gn",
        )

    def x11_brokered_gbm(text: str) -> str:
        text = replace_once(
            text,
            '#include "base/debug/crash_logging.h"\n',
            '#include <cstdlib>\n\n'
            '#include "base/debug/crash_logging.h"\n'
            '#include "base/file_descriptor_store.h"\n'
            '#include "base/files/memory_mapped_file.h"\n',
            "ui/gfx/linux/gbm_support_x11.cc",
        )
        return replace_once(
            text,
            "std::unique_ptr<ui::GbmDevice> CreateX11GbmDevice() {\n",
            "std::unique_ptr<ui::GbmDevice> CreateX11GbmDevice() {\n"
            "  // T1OS's Xvfb deliberately has no DRI3 device. The browser opens\n"
            "  // the selected render node before sandbox entry and passes only\n"
            "  // that descriptor to the GPU process.\n"
            "  base::MemoryMappedFile::Region region;\n"
            "  base::ScopedFD render_node =\n"
            "      base::FileDescriptorStore::GetInstance().MaybeTakeFD(\n"
            "          \"t1os-presentation-render-node\", &region);\n"
            "  if (render_node.is_valid()) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE brokered GBM device\";\n"
            "    return ui::CreateGbmDevice(render_node.release());\n"
            "  }\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(ERROR) << \"T1OS_PRESENTATION_BRIDGE refuses unbrokered \"\n"
            "                  \"DRI3/device-path GBM discovery\";\n"
            "    return nullptr;\n"
            "  }\n\n",
            "ui/gfx/linux/gbm_support_x11.cc",
        )

    def x11_modifier_allocation_header(text: str) -> str:
        text = replace_once(
            text,
            "namespace gfx {\n",
            "struct gbm_device;\n\nnamespace gfx {\n",
            "ui/gfx/linux/gbm_support_x11.h",
        )
        return replace_once(
            text,
            "  std::unique_ptr<GbmBuffer> CreateBuffer(viz::SharedImageFormat format,\n"
            "                                          const gfx::Size& size,\n"
            "                                          gfx::BufferUsage usage);\n",
            "  std::unique_ptr<GbmBuffer> CreateBuffer(viz::SharedImageFormat format,\n"
            "                                          const gfx::Size& size,\n"
            "                                          gfx::BufferUsage usage);\n"
            "  std::unique_ptr<GbmBuffer> CreateBufferWithModifiers(\n"
            "      viz::SharedImageFormat format,\n"
            "      const gfx::Size& size,\n"
            "      gfx::BufferUsage usage,\n"
            "      const std::vector<uint64_t>& modifiers,\n"
            "      bool require_rendering);\n"
            "  gbm_device* GetNativeDevice() const;\n",
            "ui/gfx/linux/gbm_support_x11.h",
        )

    def x11_modifier_allocation_source(text: str) -> str:
        text = replace_once(
            text,
            '#include "ui/gfx/linux/gbm_buffer.h"\n',
            '#include "ui/gfx/linux/gbm_buffer.h"\n'
            '#include "ui/gfx/linux/gbm_defines.h"\n',
            "ui/gfx/linux/gbm_support_x11.cc",
        )
        return replace_once(
            text,
            "bool GBMSupportX11::CanCreateBufferForFormat(viz::SharedImageFormat format) {\n",
            "std::unique_ptr<GbmBuffer> GBMSupportX11::CreateBufferWithModifiers(\n"
            "    viz::SharedImageFormat format,\n"
            "    const gfx::Size& size,\n"
            "    gfx::BufferUsage usage,\n"
            "    const std::vector<uint64_t>& modifiers,\n"
            "    bool require_rendering) {\n"
            "  if (!device_ || modifiers.empty() ||\n"
            "      !std::ranges::contains(\n"
            "          supported_configs_, BufferUsageAndSIFormat(usage, format))) {\n"
            "    return nullptr;\n"
            "  }\n"
            "  uint32_t flags = BufferUsageToGbmFlags(usage);\n"
            "  if (require_rendering) {\n"
            "    // WindowServer, not Chromium, owns scan-out of the composed root.\n"
            "    // Retaining GBM_BO_USE_SCANOUT lets NVIDIA choose a BO layout that\n"
            "    // its EGL DMA-BUF texture importer cannot consume.\n"
            "    flags &= ~GBM_BO_USE_SCANOUT;\n"
            "    flags |= GBM_BO_USE_RENDERING;\n"
            "  }\n"
            "  return device_->CreateBufferWithModifiers(\n"
            "      GetFourCCFormatFromSharedImageFormat(format), size,\n"
            "      flags, modifiers);\n"
            "}\n\n"
            "gbm_device* GBMSupportX11::GetNativeDevice() const {\n"
            "  return device_ ? device_->GetNativeDevice() : nullptr;\n"
            "}\n\n"
            "bool GBMSupportX11::CanCreateBufferForFormat(viz::SharedImageFormat format) {\n",
            "ui/gfx/linux/gbm_support_x11.cc",
        )

    def gbm_native_device_access(text: str) -> str:
        return replace_once(
            text,
            "  virtual bool CanCreateBufferForFormat(uint32_t format) = 0;\n",
            "  virtual bool CanCreateBufferForFormat(uint32_t format) = 0;\n\n"
            "  // The T1OS EGL/GBM presentation path must create its EGLDisplay\n"
            "  // from the same persistent GBM device that owns its buffers.\n"
            "  virtual gbm_device* GetNativeDevice() const;\n",
            "ui/gfx/linux/gbm_device.h",
        )

    def x11_brokered_gbm_and_modifiers(text: str) -> str:
        return x11_modifier_allocation_source(x11_brokered_gbm(text))

    def gbm_flag_aware_modifier_allocation(text: str) -> str:
        text = replace_once(
            text,
            "int gbm_bo_get_fd_for_plane(struct gbm_bo* bo, int plane)\n"
            "    __attribute__((weak_import));\n",
            "int gbm_bo_get_fd_for_plane(struct gbm_bo* bo, int plane)\n"
            "    __attribute__((weak_import));\n"
            "// Chromium's pinned sysroot predates this ABI declaration, while\n"
            "// both GBM implementations shipped by T1OS export it. The legacy\n"
            "// gbm_bo_create_with_modifiers() API cannot carry rendering flags.\n"
            "struct gbm_bo* gbm_bo_create_with_modifiers2(\n"
            "    struct gbm_device* gbm,\n"
            "    uint32_t width,\n"
            "    uint32_t height,\n"
            "    uint32_t format,\n"
            "    const uint64_t* modifiers,\n"
            "    const unsigned int count,\n"
            "    uint32_t flags) __attribute__((weak_import));\n",
            "ui/gfx/linux/gbm_wrapper.cc",
        )
        text = replace_once(
            text,
            "  ~Device() override = default;\n\n"
            "  std::unique_ptr<ui::GbmBuffer> CreateBuffer",
            "  ~Device() override = default;\n\n"
            "  gbm_device* GetNativeDevice() const override { return device_.get(); }\n\n"
            "  std::unique_ptr<ui::GbmBuffer> CreateBuffer",
            "ui/gfx/linux/gbm_wrapper.cc",
        )
        text = replace_once(
            text,
            "}  // namespace gbm_wrapper\n\n"
            "std::unique_ptr<GbmDevice> CreateGbmDevice(int fd) {\n",
            "}  // namespace gbm_wrapper\n\n"
            "gbm_device* GbmDevice::GetNativeDevice() const {\n"
            "  return nullptr;\n"
            "}\n\n"
            "std::unique_ptr<GbmDevice> CreateGbmDevice(int fd) {\n",
            "ui/gfx/linux/gbm_wrapper.cc",
        )
        text = replace_once(
            text,
            "namespace {\n\nuint32_t GetHandleForPlane",
            "namespace {\n\n"
            "struct gbm_bo* CreateBoWithModifiers(\n"
            "    struct gbm_device* device,\n"
            "    uint32_t width,\n"
            "    uint32_t height,\n"
            "    uint32_t format,\n"
            "    const uint64_t* modifiers,\n"
            "    unsigned int modifier_count,\n"
            "    uint32_t flags) {\n"
            "  if (gbm_bo_create_with_modifiers2) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE GBM modifier allocator=\"\n"
            "                 \"gbm_bo_create_with_modifiers2 flags=0x\"\n"
            "              << std::hex << flags;\n"
            "    return gbm_bo_create_with_modifiers2(\n"
            "        device, width, height, format, modifiers, modifier_count,\n"
            "        flags);\n"
            "  }\n"
            "  return gbm_bo_create_with_modifiers(\n"
            "      device, width, height, format, modifiers, modifier_count);\n"
            "}\n\n"
            "uint32_t GetHandleForPlane",
            "ui/gfx/linux/gbm_wrapper.cc",
        )
        text = replace_once(
            text,
            "      created_bo = gbm_bo_create_with_modifiers(\n"
            "          device_.get(), size_for_verification.width(),\n"
            "          size_for_verification.height(), format, filtered_modifiers.data(),\n"
            "          filtered_modifiers.size());\n",
            "      created_bo = CreateBoWithModifiers(\n"
            "          device_.get(), size_for_verification.width(),\n"
            "          size_for_verification.height(), format, filtered_modifiers.data(),\n"
            "          filtered_modifiers.size(), flags);\n",
            "ui/gfx/linux/gbm_wrapper.cc",
        )
        return replace_once(
            text,
            "      created_bo = gbm_bo_create_with_modifiers(\n"
            "          device_.get(), requested_size.width(), requested_size.height(),\n"
            "          format, filtered_modifiers.data(), filtered_modifiers.size());\n",
            "      created_bo = CreateBoWithModifiers(\n"
            "          device_.get(), requested_size.width(), requested_size.height(),\n"
            "          format, filtered_modifiers.data(), filtered_modifiers.size(),\n"
            "          flags);\n",
            "ui/gfx/linux/gbm_wrapper.cc",
        )

    def x11_direct_dmabuf_runtime_support(text: str) -> str:
        text = replace_once(
            text,
            '#include "ui/gfx/switches.h"\n'
            '#include "ui/gfx/x/atom_cache.h"',
            '#include "ui/gfx/switches.h"\n'
            '#include "ui/gfx/x/atom_cache.h"\n'
            '#include "ui/gl/gl_bindings.h"\n'
            '#include "ui/gl/gl_surface_egl.h"',
            "ui/ozone/platform/x11/ozone_platform_x11.cc",
        )
        return replace_once(
            text,
            "    if (has_initialized_gpu() &&\n"
            "        ui::GBMSupportX11::GetInstance()->has_gbm_device()) {\n"
            "      // This property is set when the "
            "GetPlatformRuntimeProperties is\n"
            "      // called on the gpu process side.\n"
            "      properties.supports_native_pixmaps = true;\n"
            "    }\n",
            "    auto* gl_display = gl::GLSurfaceEGL::GetGLDisplayEGL();\n"
            "    const bool supports_direct_dma_buf_import =\n"
            "        gl_display && gl_display->IsInitialized() &&\n"
            "        gl_display->ext->b_EGL_EXT_image_dma_buf_import;\n"
            "    if (has_initialized_gpu() &&\n"
            "        (ui::GBMSupportX11::GetInstance()->has_gbm_device() ||\n"
            "         supports_direct_dma_buf_import)) {\n"
            "      // Imported DMA-BUFs do not require X11/DRI3 allocation. "
            "Advertise\n"
            "      // native pixmaps whenever EGL can import them directly "
            "so the Ozone\n"
            "      // SharedImage backing factory is registered on T1OS.\n"
            "      properties.supports_native_pixmaps = true;\n"
            "    }\n",
            "ui/ozone/platform/x11/ozone_platform_x11.cc",
        )

    def t1os_presentation_output_format(text: str) -> str:
        text = replace_once(
            text,
            "#include <limits.h>\n#include <stddef.h>\n",
            "#include <limits.h>\n#include <stddef.h>\n\n#include <cstdlib>\n",
            "components/viz/service/display/direct_renderer.cc",
        )
        text = replace_once(
            text,
            "namespace {\n\n// Enum used for UMA histogram.",
            "namespace {\n\n"
            "SharedImageFormat GetT1OSPresentationOutputFormat(\n"
            "    SharedImageFormat format) {\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") == nullptr) {\n"
            "    return format;\n"
            "  }\n\n"
            "  SharedImageFormat selected = format;\n"
            "  if (format == SinglePlaneFormat::kRGBA_8888 ||\n"
            "      format == SinglePlaneFormat::kRGBX_8888 ||\n"
            "      format == SinglePlaneFormat::kBGRA_8888) {\n"
            "    selected = SinglePlaneFormat::kBGRX_8888;\n"
            "  }\n"
            "  if (selected != format) {\n"
            "    static const bool logged = [] {\n"
            "      LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE root output format \"\n"
            "                   \"uses T1OS NVIDIA-native BGRX/XRGB8888\";\n"
            "      return true;\n"
            "    }();\n"
            "    (void)logged;\n"
            "  }\n"
            "  return selected;\n"
            "}\n\n"
            "// Enum used for UMA histogram.",
            "components/viz/service/display/direct_renderer.cc",
        )
        return replace_once(
            text,
            "  SharedImageFormat frame_si_format =\n"
            "      current_frame()->display_color_spaces.GetOutputFormat(\n"
            "          current_frame()->root_render_pass->content_color_usage,\n"
            "          current_frame()->root_render_pass->has_transparent_background);\n",
            "  SharedImageFormat frame_si_format =\n"
            "      current_frame()->display_color_spaces.GetOutputFormat(\n"
            "          current_frame()->root_render_pass->content_color_usage,\n"
            "          current_frame()->root_render_pass->has_transparent_background);\n"
            "  // T1OS presents through NVIDIA EGL/GBM. The driver advertises\n"
            "  // XRGB8888 (Chromium BGRX), matching WindowServer's proven root\n"
            "  // transport. Select\n"
            "  // the supported format before SharedImage allocation so Skia color\n"
            "  // semantics, DRM fourcc, modifier selection, and EGL import agree.\n"
            "  frame_si_format = GetT1OSPresentationOutputFormat(frame_si_format);\n",
            "components/viz/service/display/direct_renderer.cc",
        )

    def t1os_output_surface_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <memory>\n",
            "#include <cstdlib>\n"
            "#include <memory>\n",
            "components/viz/service/display_embedder/"
            "skia_output_surface_impl_on_gpu.cc",
        )
        text = replace_once(
            text,
            "  context_state_ = dependency_->GetSharedContextState();\n"
            "  DCHECK(context_state_);\n",
            "  context_state_ = dependency_->GetSharedContextState();\n"
            "  DCHECK(context_state_);\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE output initialize \"\n"
            "                 \"surface_handle=\"\n"
            "              << dependency_->GetSurfaceHandle()\n"
            "              << \" offscreen=\" << dependency_->IsOffscreen()\n"
            "              << \" vulkan=\" << is_using_vulkan()\n"
            "              << \" dawn=\" << context_state_->IsGraphiteDawn();\n"
            "  }\n",
            "components/viz/service/display_embedder/"
            "skia_output_surface_impl_on_gpu.cc",
        )
        return replace_once(
            text,
            "bool SkiaOutputSurfaceImplOnGpu::InitializeForGL() {\n"
            "  if (dependency_->IsOffscreen()) {\n",
            "bool SkiaOutputSurfaceImplOnGpu::InitializeForGL() {\n"
            "  if (getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE output branch kind=gl \"\n"
            "                 \"offscreen=\"\n"
            "              << dependency_->IsOffscreen();\n"
            "  }\n"
            "  if (dependency_->IsOffscreen()) {\n",
            "components/viz/service/display_embedder/"
            "skia_output_surface_impl_on_gpu.cc",
        )

    def t1os_gpu_host_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <utility>\n",
            "#include <cstdlib>\n#include <utility>\n",
            "components/viz/host/gpu_host_impl.cc",
        )
        text = replace_once(
            text,
            "      params_(std::move(params)) {\n"
            "  // Create a special GPU info collection service if the GPU process is used for\n",
            "      params_(std::move(params)) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU host constructed\";\n"
            "  }\n"
            "  // Create a special GPU info collection service if the GPU process is used for\n",
            "components/viz/host/gpu_host_impl.cc",
        )
        text = replace_once(
            text,
            "      use_shader_cache_shm_count_.CloneRegion(), std::move(gpu_service_params));\n"
            "  MaybeSendFontRenderParams();\n",
            "      use_shader_cache_shm_count_.CloneRegion(), std::move(gpu_service_params));\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU service requested\";\n"
            "  }\n"
            "  MaybeSendFontRenderParams();\n",
            "components/viz/host/gpu_host_impl.cc",
        )
        text = replace_once(
            text,
            "  TRACE_EVENT0(\"gpu\", \"GpuHostImpl::ConnectFrameSinkManager\");\n",
            "  TRACE_EVENT0(\"gpu\", \"GpuHostImpl::ConnectFrameSinkManager\");\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser frame sink manager requested\";\n"
            "  }\n",
            "components/viz/host/gpu_host_impl.cc",
        )
        return replace_once(
            text,
            "  TRACE_EVENT0(\"gpu\", \"GpuHostImpl::DidInitialize\");\n",
            "  TRACE_EVENT0(\"gpu\", \"GpuHostImpl::DidInitialize\");\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU host initialized\";\n"
            "  }\n",
            "components/viz/host/gpu_host_impl.cc",
        )

    def t1os_viz_transport_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <utility>\n",
            "#include <cstdlib>\n#include <utility>\n",
            "content/browser/compositor/viz_process_transport_factory.cc",
        )
        text = replace_once(
            text,
            "void VizProcessTransportFactory::ConnectHostFrameSinkManager() {\n",
            "void VizProcessTransportFactory::ConnectHostFrameSinkManager() {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser connect frame sink manager\";\n"
            "  }\n",
            "content/browser/compositor/viz_process_transport_factory.cc",
        )
        text = replace_once(
            text,
            "void VizProcessTransportFactory::CreateLayerTreeFrameSink(\n"
            "    base::WeakPtr<ui::Compositor> compositor) {\n",
            "void VizProcessTransportFactory::CreateLayerTreeFrameSink(\n"
            "    base::WeakPtr<ui::Compositor> compositor) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser layer tree sink requested\";\n"
            "  }\n",
            "content/browser/compositor/viz_process_transport_factory.cc",
        )
        text = replace_once(
            text,
            "    scoped_refptr<gpu::GpuChannelHost> gpu_channel_host) {\n"
            "  ui::Compositor* compositor = compositor_weak_ptr.get();\n",
            "    scoped_refptr<gpu::GpuChannelHost> gpu_channel_host) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser GPU channel callback valid=\"\n"
            "              << static_cast<bool>(gpu_channel_host);\n"
            "  }\n"
            "  ui::Compositor* compositor = compositor_weak_ptr.get();\n",
            "content/browser/compositor/viz_process_transport_factory.cc",
        )
        return replace_once(
            text,
            "  GetHostFrameSinkManager()->CreateRootCompositorFrameSink(\n"
            "      std::move(root_params));\n",
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE browser root sink submit gpu=\"\n"
            "              << gpu_compositing << \" widget=\" << compositor->widget();\n"
            "  }\n"
            "  GetHostFrameSinkManager()->CreateRootCompositorFrameSink(\n"
            "      std::move(root_params));\n",
            "content/browser/compositor/viz_process_transport_factory.cc",
        )

    def t1os_root_sink_diagnostics(text: str) -> str:
        text = replace_once(
            text,
            "#include <utility>\n",
            "#include <cstdlib>\n#include <utility>\n",
            "components/viz/service/frame_sinks/root_compositor_frame_sink_impl.cc",
        )
        text = replace_once(
            text,
            "    HintSessionFactory* hint_session_factory) {\n"
            "  // First create an output surface.\n",
            "    HintSessionFactory* hint_session_factory) {\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE service root sink create gpu=\"\n"
            "              << params->gpu_compositing << \" widget=\" << params->widget;\n"
            "  }\n"
            "  // First create an output surface.\n",
            "components/viz/service/frame_sinks/root_compositor_frame_sink_impl.cc",
        )
        return replace_once(
            text,
            "      display_controller.get(), params->renderer_settings, debug_settings);\n\n"
            "  // Creating output surface failed. The host can send a new request, possibly\n",
            "      display_controller.get(), params->renderer_settings, debug_settings);\n"
            "  if (std::getenv(\"T1OS_PRESENTATION_BRIDGE\") != nullptr) {\n"
            "    LOG(INFO) << \"T1OS_PRESENTATION_BRIDGE service output surface created=\"\n"
            "              << static_cast<bool>(output_surface);\n"
            "  }\n\n"
            "  // Creating output surface failed. The host can send a new request, possibly\n",
            "components/viz/service/frame_sinks/root_compositor_frame_sink_impl.cc",
        )

    return {
        "base/command_line.h": ("PrependWrapperPath", command_line_h),
        "base/command_line.cc": ("PrependWrapperPath", command_line_cc),
        "media/media_options.gni": ("enable_t1os_video_decoder = false", media_options),
        "media/BUILD.gn": ("ENABLE_T1OS_VIDEO_DECODER=", media_build),
        "media/base/BUILD.gn": ('"t1os_media_switches.cc"', media_base_build),
        "media/base/decoder.h": ("kT1OS = 20", decoder_h),
        "media/base/decoder.cc": ('return "T1OSVideoDecoder";', decoder_cc),
        "media/audio/alsa/alsa_output.h": (
            "T1OS's ALSA file PCM terminates at a FIFO/null slave",
            alsa_output_h,
        ),
        "media/audio/alsa/alsa_output.cc": (
            "T1OS audio presentation clock v1",
            alsa_output_cc,
        ),
        "media/gpu/BUILD.gn": (
            '"t1os/t1os_video_decoder_unittest.cc"',
            media_gpu_build,
        ),
        "media/mojo/services/BUILD.gn": ('"//media/gpu:t1os_video_decoder"', mojo_build),
        "media/mojo/services/gpu_mojo_media_client_linux.cc": (
            "T1OSVideoDecoder::Create(",
            mojo_linux,
        ),
        "media/mojo/services/gpu_mojo_media_client.cc": (
            "T1OS_MEDIA_DECODER gpu_service_gate",
            mojo_service_gate,
        ),
        "media/gpu/chromeos/mailbox_video_frame_converter.h": (
            "output_mappable_",
            mailbox_converter_h,
        ),
        "media/gpu/chromeos/mailbox_video_frame_converter.cc": (
            "output_mappable_",
            mailbox_converter_cc,
        ),
        "media/gpu/chromeos/native_pixmap_frame_resource.h": (
            "CreateForT1OS",
            native_pixmap_frame_resource_h,
        ),
        "media/gpu/chromeos/native_pixmap_frame_resource.cc": (
            "chroma_is_drm_rg",
            native_pixmap_frame_resource_cc,
        ),
        "ui/gfx/native_pixmap_handle.h": (
            "plane_modifiers",
            native_pixmap_handle_h,
        ),
        "ui/gfx/native_pixmap_handle.cc": (
            "clone.plane_modifiers",
            native_pixmap_handle_cc,
        ),
        "ui/gfx/mojom/native_handle_types.mojom": (
            "array<uint64> plane_modifiers",
            native_handle_types_mojom,
        ),
        "ui/gfx/mojom/native_handle_types_mojom_traits.h": (
            "plane_modifiers(",
            native_handle_types_traits_h,
        ),
        "ui/gfx/mojom/native_handle_types_mojom_traits.cc": (
            "ReadPlaneModifiers",
            native_handle_types_traits_cc,
        ),
        "media/mojo/mojom/stable/native_pixmap_handle.mojom": (
            "plane_modifiers@2",
            stable_native_pixmap_handle_mojom,
        ),
        "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.h": (
            "plane_modifiers(",
            stable_native_pixmap_handle_traits_h,
        ),
        "media/mojo/mojom/stable/native_pixmap_handle_mojom_traits.cc": (
            "ReadPlaneModifiers",
            stable_native_pixmap_handle_traits_cc,
        ),
        "media/mojo/clients/mojo_codec_factory.cc": (
            "late path must not notify twice",
            mojo_codec_factory_cc,
        ),
        "media/renderers/video_resource_updater.h": (
            "mappable_hardware_bridge_reported_",
            video_resource_updater_h,
        ),
        "media/renderers/video_resource_updater.cc": (
            "T1OS_MEDIA_DECODER presentation_bridge",
            video_resource_updater_cc,
        ),
        "content/renderer/render_thread_impl.cc": (
            "T1OS_MEDIA_DECODER renderer_gate",
            renderer_decoder_gate,
        ),
        "content/browser/BUILD.gn": (
            "if (enable_t1os_video_decoder) {\n"
            "    sources += [\n"
            '      "gpu/t1os_media_decode_broker.cc"',
            content_build,
        ),
        "content/browser/gpu/gpu_process_host.cc": (
            "Utility and renderer processes retain Chromium's normal zygotes",
            gpu_host,
        ),
        "content/browser/compositor/viz_process_transport_factory.cc": (
            "T1OS_PRESENTATION_BRIDGE browser root sink submit",
            t1os_viz_transport_diagnostics,
        ),
        "content/gpu/gpu_main.cc": (
            "T1OS_PRESENTATION_BRIDGE GPU init complete",
            gpu_main_diagnostics,
        ),
        "content/gpu/gpu_child_thread.cc": (
            "T1OS_PRESENTATION_BRIDGE GPU service connected",
            gpu_child_diagnostics,
        ),
        "content/child/child_thread_impl.cc": (
            "T1OS_PRESENTATION_BRIDGE child connection timeout",
            child_connection_diagnostics,
        ),
        "mojo/core/channel_posix.cc": (
            "T1OS_MOJO_CHANNEL start",
            mojo_channel_diagnostics,
        ),
        "content/browser/child_process_launcher_helper.cc": (
            "T1OS_PRESENTATION_BRIDGE child invitation sent",
            child_launcher_diagnostics,
        ),
        "content/common/zygote/zygote_communication_linux.cc": (
            "T1OS_PRESENTATION_BRIDGE zygote fork reply",
            zygote_communication_diagnostics,
        ),
        "content/browser/service_host/utility_sandbox_delegate.cc": (
            "T1OS routes Network Service through Chromium's existing unsandboxed",
            utility_sandbox_delegate,
        ),
        "content/common/gpu_pre_sandbox_hook_linux.cc": (
            "kT1OSNvidiaPresentationLibraries",
            gpu_pre_sandbox_hook,
        ),
        "sandbox/policy/linux/bpf_gpu_policy_linux.cc": (
            "F_SEAL_GROW |\n          F_SEAL_WRITE",
            gpu_policy,
        ),
        "sandbox/policy/BUILD.gn": (
            '"linux/t1os_gpu_seal_policy_unittest.cc"',
            sandbox_build,
        ),
        "net/dns/dns_config_service_linux.cc": (
            "/the one/settings/network/dns.txt",
            dns_config_linux,
        ),
        "services/network/network_sandbox_hook_linux.cc": (
            "/the one/settings/network/dns.txt",
            network_sandbox_linux,
        ),
        "tools/metrics/histograms/enums.xml": (
            '<int value="20" label="T1OS Video Decoder"/>',
            metrics_enums,
        ),
        "gpu/command_buffer/service/shared_image/"
        "ozone_image_backing_factory.cc": (
            "An imported NATIVE_PIXMAP already owns its allocation",
            ozone_imported_native_pixmap,
        ),
        "gpu/command_buffer/service/shared_image/"
        "ozone_image_gl_textures_holder.cc": (
            "composition=chromium-planar",
            t1os_nvdec_planar_textures,
        ),
        "ui/ozone/common/native_pixmap_egl_binding.cc": (
            "modifier policy=implicit-linear",
            t1os_implicit_linear_egl_import,
        ),
        "ui/gl/gl_utils.cc": (
            "ANGLE-only global texture-share-group attributes",
            linux_validating_command_decoder,
        ),
        "gpu/ipc/service/gpu_init.cc": (
            "T1OS selects Chromium's already-built Linux validating decoder",
            linux_gpu_init_validating_decoder,
        ),
        "ui/ozone/platform/x11/x11_surface_factory.cc": (
            "direct NativePixmapDmaBuf fallback used by Ozone Wayland",
            x11_direct_dmabuf_import,
        ),
        "ui/ozone/platform/x11/BUILD.gn": (
            '"t1os_gbm_pixmap.cc"',
            x11_presentation_build,
        ),
        "ui/gfx/linux/gbm_support_x11.h": (
            "CreateBufferWithModifiers",
            x11_modifier_allocation_header,
        ),
        "ui/gfx/linux/gbm_support_x11.cc": (
            "T1OS_PRESENTATION_BRIDGE brokered GBM device",
            x11_brokered_gbm_and_modifiers,
        ),
        "ui/gfx/linux/gbm_device.h": (
            "same persistent GBM device",
            gbm_native_device_access,
        ),
        "ui/gfx/linux/gbm_wrapper.cc": (
            "GBM modifier allocator=",
            gbm_flag_aware_modifier_allocation,
        ),
        "ui/ozone/platform/x11/ozone_platform_x11.cc": (
            "Imported DMA-BUFs do not require X11/DRI3 allocation",
            x11_direct_dmabuf_runtime_support,
        ),
        "components/viz/service/display/direct_renderer.cc": (
            "GetT1OSPresentationOutputFormat",
            t1os_presentation_output_format,
        ),
        "components/viz/service/display_embedder/"
        "skia_output_surface_impl_on_gpu.cc": (
            "T1OS_PRESENTATION_BRIDGE output initialize",
            t1os_output_surface_diagnostics,
        ),
        "components/viz/host/gpu_host_impl.cc": (
            "T1OS_PRESENTATION_BRIDGE browser GPU host initialized",
            t1os_gpu_host_diagnostics,
        ),
        "components/viz/service/frame_sinks/root_compositor_frame_sink_impl.cc": (
            "T1OS_PRESENTATION_BRIDGE service root sink create",
            t1os_root_sink_diagnostics,
        ),
    }


def nested_skia_transformations() -> dict[str, tuple[str, callable]]:
    def nvidia_manual_msaa(text: str) -> str:
        return replace_once(
            text,
            "    // https://skbug.com/503013389\n"
            "    if (ctxInfo.driver() == GrGLDriver::kNVIDIA) {\n"
            "        fMSAAResolvesAutomatically = false;\n"
            "    }",
            "    // https://skbug.com/503013389\n"
            "    if (ctxInfo.driver() == GrGLDriver::kNVIDIA) {\n"
            "        // NVIDIA's GLES implementation advertises implicit\n"
            "        // multisampled-render-to-texture, but the workaround\n"
            "        // below requires an explicit resolve. Leaving the\n"
            "        // implicit FBO type selected makes a render target both\n"
            "        // implicit and manually resolved, which violates\n"
            "        // GrGLRenderTarget::bindForResolve(). NVIDIA also loses\n"
            "        // the native GBM window-surface GL context when the standard\n"
            "        // blit resolve path targets the presentation surface, so neither\n"
            "        // multisample FBO implementation is safe here. This\n"
            "        // retains GPU raster while disabling framebuffer MSAA.\n"
            "        if (fMSFBOType == kES_EXT_MsToTexture_MSFBOType ||\n"
            "            fMSFBOType == kES_IMG_MsToTexture_MSFBOType) {\n"
            "            fMSFBOType = kNone_MSFBOType;\n"
            "        }\n"
            "        fMSAAResolvesAutomatically = false;\n"
            "        SkASSERT(!this->usesImplicitMSAAResolve());\n"
            "    }",
            "third_party/skia/src/gpu/ganesh/gl/GrGLCaps.cpp",
        )

    return {
        "src/gpu/ganesh/gl/GrGLCaps.cpp": (
            "NVIDIA's GLES implementation advertises implicit",
            nvidia_manual_msaa,
        ),
    }


def assert_revision(source: Path) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    )
    actual = result.stdout.strip()
    if actual != REVISION:
        raise RuntimeError(f"Chromium revision is {actual}; required {REVISION}")

    skia_source = source / SKIA_ROOT
    skia_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=skia_source,
        text=True,
        capture_output=True,
        check=True,
    )
    actual_skia = skia_result.stdout.strip()
    if actual_skia != SKIA_REVISION:
        raise RuntimeError(
            f"Skia revision is {actual_skia}; required {SKIA_REVISION}"
        )


def git_blob(source: Path, relative: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative}"],
        cwd=source,
    )


def expected_transformed_files(source: Path) -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    for relative, (sentinel, transform) in sorted(transformations().items()):
        upstream = git_blob(source, relative)
        upstream_digest = sha256(upstream)
        required_digest = UPSTREAM_SHA256[relative]
        if upstream_digest != required_digest:
            raise RuntimeError(
                f"{relative}: pinned Git blob fingerprint mismatch: "
                f"{upstream_digest}, expected {required_digest}"
            )
        updated = transform(upstream.decode("utf-8"))
        if sentinel not in updated:
            raise RuntimeError(f"{relative}: transform did not add sentinel")
        expected[relative] = updated.encode("utf-8")
    return expected


def expected_skia_transformed_files(source: Path) -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    skia_source = source / SKIA_ROOT
    for relative, (sentinel, transform) in sorted(
        nested_skia_transformations().items()
    ):
        upstream = git_blob(skia_source, relative)
        upstream_digest = sha256(upstream)
        required_digest = SKIA_UPSTREAM_SHA256[relative]
        if upstream_digest != required_digest:
            raise RuntimeError(
                f"third_party/skia/{relative}: pinned Git blob fingerprint "
                f"mismatch: {upstream_digest}, expected {required_digest}"
            )
        updated = transform(upstream.decode("utf-8"))
        if sentinel not in updated:
            raise RuntimeError(
                f"third_party/skia/{relative}: transform did not add sentinel"
            )
        expected[relative] = updated.encode("utf-8")
    return expected


def digest_named_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def normalized_build_marker_header(data: bytes) -> bytes:
    embedded_digest = MANIFEST.get("source_overlay_sha256", "").encode("ascii")
    if len(embedded_digest) != 64 or data.count(embedded_digest) != 1:
        raise RuntimeError(
            f"{BUILD_MARKER_OVERLAY_PATH}: expected exactly one embedded "
            "source-overlay fingerprint"
        )
    # Only the self-referential digest bytes are normalized. Feature names,
    # switches, descriptor-pool policy, protocol pin, and every other byte in
    # this compiled header remain covered by source_overlay_sha256.
    return data.replace(
        embedded_digest,
        b"<T1OS_SOURCE_OVERLAY_SHA256_NORMALIZED>",
        1,
    )


def source_overlay_sha256(
    source: Path,
    expected_edits: dict[str, bytes] | None = None,
    expected_skia_edits: dict[str, bytes] | None = None,
) -> str:
    expected_edits = expected_edits or expected_transformed_files(source)
    expected_skia_edits = (
        expected_skia_edits or expected_skia_transformed_files(source)
    )
    inputs = {
        f"patched/{relative}": data
        for relative, data in expected_edits.items()
    }
    inputs.update(
        {
            f"patched/{SKIA_ROOT.as_posix()}/{relative}": data
            for relative, data in expected_skia_edits.items()
        }
    )
    for overlay_path in sorted(p for p in OVERLAY.rglob("*") if p.is_file()):
        relative = overlay_path.relative_to(OVERLAY)
        data = overlay_path.read_bytes()
        if relative == BUILD_MARKER_OVERLAY_PATH:
            data = normalized_build_marker_header(data)
        inputs[f"overlay/{relative.as_posix()}"] = data
    return digest_named_files(inputs)


def validate_manifest_provenance(
    source: Path,
    expected_edits: dict[str, bytes],
    expected_skia_edits: dict[str, bytes],
) -> None:
    protocol = OVERLAY / PROTOCOL_OVERLAY_PATH
    protocol_digest = sha256(protocol.read_bytes())
    required_protocol_digest = MANIFEST.get("protocol_header_sha256")
    if protocol_digest != required_protocol_digest:
        raise RuntimeError(
            "shared T1MD protocol header fingerprint mismatch: "
            f"{protocol_digest}, expected {required_protocol_digest}"
        )
    actual_source_digest = source_overlay_sha256(
        source, expected_edits, expected_skia_edits
    )
    required_source_digest = MANIFEST.get("source_overlay_sha256")
    if actual_source_digest != required_source_digest:
        raise RuntimeError(
            "Chromium source-overlay fingerprint mismatch: "
            f"{actual_source_digest}, expected {required_source_digest}"
        )


def reconcile_transformed_files(
    source: Path,
    expected_edits: dict[str, bytes],
    upstream_edits: dict[str, bytes],
    check: bool,
) -> list[str]:
    errors: list[str] = []
    for relative, expected_data in expected_edits.items():
        path = source / relative
        data = path.read_bytes()
        if check:
            if data != expected_data:
                errors.append(
                    f"{relative}: patched bytes mismatch "
                    f"({sha256(data)} != {sha256(expected_data)})"
                )
            continue
        upstream = upstream_edits[relative]
        migratable = sha256(data) in MIGRATABLE_PATCHED_SHA256.get(
            relative, set()
        )
        if data != upstream and data != expected_data and not migratable:
            raise RuntimeError(
                f"{relative}: refusing to overwrite unrecognized dirty bytes: "
                f"{sha256(data)}"
            )
        if data != expected_data:
            path.write_bytes(expected_data)
    return errors


def parse_porcelain_status(data: bytes) -> list[tuple[str, str]]:
    fields = data.split(b"\0")
    records: list[tuple[str, str]] = []
    index = 0
    while index < len(fields) and fields[index]:
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise RuntimeError("malformed git porcelain status record")
        status = record[:2].decode("ascii")
        path = record[3:].decode("utf-8")
        records.append((status, path))
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise RuntimeError("malformed git rename/copy status record")
            records.append((status, fields[index].decode("utf-8")))
            index += 1
    return records


def validate_dirty_path_allowlist(
    records: list[tuple[str, str]], allowed_paths: set[str]
) -> list[str]:
    errors: list[str] = []
    for status, path in records:
        if path not in allowed_paths:
            errors.append(f"{path}: unexpected dirty Chromium source ({status})")
            continue
        if any(code in status for code in "DRCU"):
            errors.append(f"{path}: forbidden Git status {status}")
    return errors


def verify_root_checkout_allowlist(source: Path) -> list[str]:
    allowed = set(transformations())
    allowed.add(SKIA_ROOT.as_posix())
    allowed.update(
        path.relative_to(OVERLAY).as_posix()
        for path in OVERLAY.rglob("*")
        if path.is_file()
    )
    status = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=source,
    )
    return validate_dirty_path_allowlist(
        parse_porcelain_status(status), allowed
    )


def verify_skia_checkout_allowlist(source: Path) -> list[str]:
    status = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=source / SKIA_ROOT,
    )
    return validate_dirty_path_allowlist(
        parse_porcelain_status(status), set(nested_skia_transformations())
    )


def apply(source: Path, check: bool) -> None:
    assert_revision(source)
    expected_edits = expected_transformed_files(source)
    expected_skia_edits = expected_skia_transformed_files(source)
    validate_manifest_provenance(
        source, expected_edits, expected_skia_edits
    )
    upstream_edits = {
        relative: git_blob(source, relative) for relative in expected_edits
    }
    errors = reconcile_transformed_files(
        source, expected_edits, upstream_edits, check
    )
    skia_source = source / SKIA_ROOT
    upstream_skia_edits = {
        relative: git_blob(skia_source, relative)
        for relative in expected_skia_edits
    }
    errors.extend(
        reconcile_transformed_files(
            skia_source,
            expected_skia_edits,
            upstream_skia_edits,
            check,
        )
    )

    for overlay_path in sorted(p for p in OVERLAY.rglob("*") if p.is_file()):
        relative = overlay_path.relative_to(OVERLAY)
        destination = source / relative
        if check:
            if not destination.is_file() or destination.read_bytes() != overlay_path.read_bytes():
                errors.append(f"{relative.as_posix()}: overlay mismatch")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(overlay_path, destination)

    errors.extend(verify_root_checkout_allowlist(source))
    errors.extend(verify_skia_checkout_allowlist(source))
    if errors:
        raise RuntimeError("\n".join(errors))

    mode = "verified" if check else "applied"
    print(f"T1OS Chromium overlay {mode}: {source}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        apply(args.source.resolve(), args.check)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
