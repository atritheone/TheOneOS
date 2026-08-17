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

from pathlib import Path
import ast
import copy
import sys
import time


def require(source, text, label):
    if text not in source:
        raise RuntimeError(f"{label} is missing: {text}")


def function(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise RuntimeError(f"function is missing: {name}")


def main():
    root = Path(sys.argv[1]).resolve()
    animation_path = root / "source/boot/boot animation/boot animation.py"
    goddess_path = root / "source/build software/GODDESS/GODDESS.py"
    driverserver_path = root / "source/build software/drivers/driverserver.py"
    startup_path = root / "source/build software/startup/startup.py"
    lockscreen_path = root / "source/build software/lock screen/lock screen.py"
    graphics_path = root / "source/build software/graphics/graphics.py"
    qemu_path = root / "scripts/test hardware usb qemu.ps1"

    animation = animation_path.read_text(encoding="utf-8")
    goddess = goddess_path.read_text(encoding="utf-8")
    driverserver = driverserver_path.read_text(encoding="utf-8")
    startup = startup_path.read_text(encoding="utf-8")
    lockscreen = lockscreen_path.read_text(encoding="utf-8")
    graphics = graphics_path.read_text(encoding="utf-8")
    qemu = qemu_path.read_text(encoding="utf-8")
    windowserver_path = root / "source/build software/windows/windowserver.py"
    windowserver = windowserver_path.read_text(encoding="utf-8")

    animation_tree = ast.parse(animation, filename=str(animation_path))
    goddess_tree = ast.parse(goddess, filename=str(goddess_path))
    startup_tree = ast.parse(startup, filename=str(startup_path))
    lockscreen_tree = ast.parse(lockscreen, filename=str(lockscreen_path))
    graphics_tree = ast.parse(graphics, filename=str(graphics_path))
    windowserver_tree = ast.parse(windowserver, filename=str(windowserver_path))

    for tree, name in (
        (animation_tree, "main"),
        (animation_tree, "progressloop"),
        (animation_tree, "brandsequence"),
        (animation_tree, "animationtimeline"),
        (animation_tree, "fadein"),
        (animation_tree, "fadeout"),
        (animation_tree, "earlydots"),
        (goddess_tree, "startbootanimation"),
        (goddess_tree, "stopbootanimation"),
        (goddess_tree, "runstartup"),
        (goddess_tree, "lockscreenposthandoffreceipt"),
        (startup_tree, "bootanimationhandoff"),
        (startup_tree, "runlockscreenwithhandoff"),
        (startup_tree, "writeposthandoffstate"),
        (startup_tree, "wspresent"),
        (startup_tree, "wssend"),
        (startup_tree, "wsanimationpump"),
        (startup_tree, "graphicspresentationbarrier"),
        (startup_tree, "animationtimeline"),
        (startup_tree, "animatewelcometitle"),
        (startup_tree, "animatesetuplabel"),
        (startup_tree, "logopen"),
        (startup_tree, "notifysessionauthenticated"),
        (startup_tree, "sessionlockmain"),
        (lockscreen_tree, "lifecyclewrite"),
        (lockscreen_tree, "lockscreenreceiptphysicallyverified"),
        (lockscreen_tree, "unlockrequest"),
        (windowserver_tree, "locksession"),
        (windowserver_tree, "sessionlockactive"),
        (windowserver_tree, "sessionauthenticated"),
    ):
        function(tree, name)

    for text in (
        'CONTROLBASE = "/.ephemeral/boot animation"',
        'DOTMINIMUMTIME = 0.72',
        'BRANDFADETIME = 0.32',
        'ANIMATIONREFRESHHZ = 60.0',
        'controlstate("dots")',
        'action = progressloop(firstshown, firstdotframe)',
        'if action == "brand":',
        'controlstate("branding")',
        'controlstate("done")',
        'drawdotframe(dotframes()[0])',
        "gr.init('/the one/drivers/nodes/fb0', backend='framebuffer')",
        'if mode == "early-dots":',
        'graphicswaitinitial()',
        '{"op": "MAP", "winid": int(winid)}',
    ):
        require(animation, text, "boot animation lifecycle")

    for text in (
        "def gpuwindowretainedsystem(",
        'if not bool(win.get("_managed_only", False)):',
        '"boot animation", "system animation", "lockscreen", "startup"',
        "graphics system scene committed",
        "graphics startup compositor waiting for first mapped scene",
        "graphics first GPU frame begin",
        "graphics first GPU frame complete",
        "gpuwindowscenetexture(win)",
        "if managedonly and not dynamicvideo",
        "graphics retained system scene ready",
        "preserve=not (retainedsystemseen and requestedfull)",
    ):
        require(windowserver, text, "NVK managed boot-scene lifecycle")

    startup_gate = function(windowserver_tree, "gpustartupworkloadgate")
    startup_gate_source = ast.get_source_segment(windowserver, startup_gate) or ""
    if startup_gate_source.index("regions = gpubeginregions(") >= startup_gate_source.index(
        "targetstate = gputargetbegin("
    ):
        raise RuntimeError(
            "the startup health gate enters an off-screen target before its managed GPU frame"
        )

    if "bootwait(5)" in animation:
        raise RuntimeError("boot animation still contains the removed black five-second wait")

    fadein_source = ast.get_source_segment(
        animation, function(animation_tree, "fadein")
    ) or ""
    fadeout_source = ast.get_source_segment(
        animation, function(animation_tree, "fadeout")
    ) or ""

    for label, source in (("in", fadein_source), ("out", fadeout_source)):
        if "animationtimeline(BRANDFADETIME)" not in source:
            raise RuntimeError(f"boot title fade-{label} is not time-based")
        if "bootwait(0.032)" in source or "range(1, 11)" in source:
            raise RuntimeError(f"boot title fade-{label} retained coarse fixed steps")

    startup_present = ast.get_source_segment(
        startup, function(startup_tree, "wspresent")
    ) or ""

    for text in (
        "retainedrect = graphicsgetdirty()",
        "rect = retainedrect",
        "graphicsresetdirty()",
    ):
        require(startup_present, text, "Startup managed-only dirty presentation")

    if "rect = [0, 0, int(SCREEN_W), int(SCREEN_H)]" in startup_present:
        raise RuntimeError(
            "Startup managed-only presentation still forces full-screen damage"
        )

    startup_send = ast.get_source_segment(
        startup, function(startup_tree, "wssend")
    ) or ""

    for text in ("sent = WSSOCK.send(payload)", "return True", "return False"):
        require(startup_send, text, "Startup managed graphics send contract")

    startup_animation_pump = ast.get_source_segment(
        startup, function(startup_tree, "wsanimationpump")
    ) or ""

    for text in (
        "wsmanagedresponse(msg)",
        'GRAPHICSSTATE.get("need_submit")',
        "graphicspump()",
    ):
        require(
            startup_animation_pump,
            text,
            "Startup animation acknowledgement pump",
        )

    startup_presentation_barrier = ast.get_source_segment(
        startup, function(startup_tree, "graphicspresentationbarrier")
    ) or ""

    for text in (
        'GRAPHICSSTATE.get("pending")',
        'GRAPHICSSTATE.get("need_submit")',
        'GRAPHICSSTATE.get("presented", False)',
        "wsanimationpump(",
        "managed presentation barrier failed",
    ):
        require(
            startup_presentation_barrier,
            text,
            "Startup page-flip presentation barrier",
        )

    barrier_namespace = {
        "time": time,
        "GRAPHICSSTATE": {
            "available": True,
            "pending": False,
            "need_submit": False,
            "presented": False,
            "presentation_reason": "synthetic unpresented frame",
        },
        "wsanimationpump": lambda timeout=0.0: 0,
        "timestamp": lambda: "test",
        "log": lambda message: None,
    }
    barrier_module = ast.Module(
        body=[copy.deepcopy(function(startup_tree, "graphicspresentationbarrier"))],
        type_ignores=[],
    )
    ast.fix_missing_locations(barrier_module)
    exec(
        compile(barrier_module, str(startup_path), "exec"),
        barrier_namespace,
    )
    barrier = barrier_namespace["graphicspresentationbarrier"]

    if barrier(0.05):
        raise RuntimeError(
            "Startup accepted a completed managed request that was not "
            "physically presented"
        )

    barrier_namespace["GRAPHICSSTATE"]["presented"] = True

    if not barrier(0.05):
        raise RuntimeError(
            "Startup rejected a confirmed managed page-flip presentation"
        )

    barrier_namespace["GRAPHICSSTATE"].update({
        "available": False,
        "presented": False,
        "presentation_reason": "managed graphics commit timed out",
    })

    if barrier(0.05):
        raise RuntimeError(
            "Startup treated loss of its negotiated compositor as a CPU-only "
            "session with no presentation requirement"
        )

    barrier_namespace["GRAPHICSSTATE"]["presentation_reason"] = ""

    if not barrier(0.05):
        raise RuntimeError(
            "Startup rejected a session that began without managed graphics"
        )

    title_animation = ast.get_source_segment(
        startup, function(startup_tree, "animatewelcometitle")
    ) or ""
    label_animation = ast.get_source_segment(
        startup, function(startup_tree, "animatesetuplabel")
    ) or ""

    for text in (
        "for progress in animationtimeline(duration):",
        "title[:visiblecharacters]",
        "wspresent()",
    ):
        require(title_animation, text, "Startup title animation pacing")

    for text in (
        "for progress in animationtimeline(LABELFADETIME):",
        "wspresent()",
    ):
        require(label_animation, text, "Startup label animation pacing")

    startup_setup = ast.get_source_segment(
        startup, function(startup_tree, "setupuser")
    ) or ""

    for stale in ("time.sleep(0.12)", "FADE_STEPS", "FADE_DELAY"):
        if stale in startup_setup:
            raise RuntimeError(
                f"Startup account animation retained coarse pacing: {stale}"
            )

    if startup_setup.count("if not graphicspresentationbarrier():") < 5:
        raise RuntimeError(
            "Startup does not abort every first-run title, label, prompt, or "
            "success transition after an unconfirmed page flip"
        )

    startup_main = ast.get_source_segment(
        startup, function(startup_tree, "main")
    ) or ""

    for text in (
        "created = setupuser()",
        "if not created:",
        "preserving the last verified frame and aborting startup",
        'raise RuntimeError("first-run setup did not complete")',
    ):
        require(
            startup_main,
            text,
            "Startup fail-closed first-run presentation",
        )

    startup_logopen = ast.get_source_segment(
        startup, function(startup_tree, "logopen")
    ) or ""

    if "os.makedirs" in startup_logopen:
        raise RuntimeError(
            "Startup still attempts to create GODDESS-owned log directories"
        )

    for text in (
        'open(STARTLOGFILE, "a")',
        "permission denied opening startup log file",
        "error opening startup log file",
    ):
        require(startup_logopen, text, "Startup log-file ownership")

    first_dots = animation.index("drawdotframe(dotframes()[0])")
    first_map = animation.index('{"op": "MAP", "winid": int(winid)}')
    if first_dots >= first_map:
        raise RuntimeError("the first dots frame is not committed before the window is mapped")

    animation_main = function(animation_tree, "main")
    animation_main_source = ast.get_source_segment(animation, animation_main) or ""
    teardown = animation_main_source[animation_main_source.index("finally:"):]
    if teardown.index('controlstate("done")') >= teardown.index("wscursor(True)"):
        raise RuntimeError(
            "boot animation publishes visual handoff completion after cursor cleanup"
        )

    for text in (
        "earlybootanimation = startbootanimation('early-dots')",
        "'T1OS_EARLY_FRAMEBUFFER_GRAPHICS_OWNED'",
        "env=environment",
        "bootanimation = startbootanimation('dots')",
        "startupenvironment['T1OS_BOOT_ANIMATION_PID']",
        "runstartup(startupenvironment, wsproc)",
        "logpath=STARTUPLOG",
        "state = lockscreenlifecycle()",
        "LOCKSCREENPOSTHANDOFFTIMEOUT = 15.0",
        "receipt = lockscreenposthandoffreceipt(",
        "I verified the lock screen after the display handoff ",
        "current physically verified post-handoff receipt",
        "stopbootanimation(bootanimation)",
        "waitacceleratedbootpresentation(",
        "'boot-animation-client'",
        "'continuing directly to lock screen'",
        "while not stopbootanimation(earlybootanimation):",
        "'early-framebuffer-owner-retirement'",
        "'T1OS_EARLY_BOOT_ANIMATION_PID'",
        "'T1OS_BOOT_DOT_FRAME'",
    ):
        require(goddess, text, "GODDESS boot-progress integration")

    goddess_boot_launcher = ast.get_source_segment(
        goddess, function(goddess_tree, "startbootanimation")
    ) or ""
    startup_boot_handoff = ast.get_source_segment(
        startup, function(startup_tree, "bootanimationhandoff")
    ) or ""

    for source, command, profile, label in (
        (
            goddess_boot_launcher,
            "[BOOTANIMATIONSCRIPT, mode]",
            "security_profile='boot-animation'",
            "GODDESS boot-animation launcher",
        ),
        (
            startup_boot_handoff,
            '[BOOTANIMATIONSCRIPT, "brand"]',
            'security_profile="boot-animation"',
            "Startup boot-animation launcher",
        ),
    ):
        require(source, command, label)
        require(source, "softwarepath=BOOTANIMATIONSCRIPT", label)
        require(source, profile, label)
        if "sys.executable" in source:
            raise RuntimeError(
                f"{label} bypasses direct profiled execution through the Python interpreter"
            )

    goddess_main = function(goddess_tree, "main")
    goddess_main_source = ast.get_source_segment(goddess, goddess_main) or ""
    if goddess_main_source.index("earlybootanimation = startbootanimation('early-dots')") >= goddess_main_source.index(
        "birth(EARLYSYSTEMOPS)"
    ):
        raise RuntimeError("early framebuffer dots do not start before driver discovery")

    if goddess_main_source.index("if not waitwindowserver(wsproc)") >= goddess_main_source.index(
        "bootanimation = startbootanimation('dots')"
    ):
        raise RuntimeError("GODDESS starts boot progress before WindowServer is ready")

    early_start = goddess_main_source.index(
        "earlybootanimation = startbootanimation('early-dots')"
    )
    native_driver_birth = goddess_main_source.index(
        "birth(EARLYSYSTEMOPS)",
        early_start,
    )
    early_retirement = goddess_main_source.index(
        "while not stopbootanimation(earlybootanimation):",
        native_driver_birth,
    )
    managed_dots = goddess_main_source.index(
        "bootanimation = startbootanimation('dots')",
        native_driver_birth,
    )

    if not early_start < native_driver_birth < early_retirement < managed_dots:
        raise RuntimeError(
            "the early framebuffer writer does not remain active through "
            "driver discovery before managed boot progress"
        )

    for text in (
        "def retireearlybootanimation(",
        "PROCESSROOT = Path(os.environ.get(",
        "statpath = PROCESSROOT / str(int(pid)) / 'stat'",
        "if pcidisplayalias(alias) and not self.early_boot_animation_retired:",
        "self.early_boot_animation_retired = retireearlybootanimation()",
        "native display binding blocked while the early firmware",
    ):
        require(driverserver, text, "DriverServer display-owner handoff")

    for text in (
        'os.environ.get("T1OS_EARLY_FRAMEBUFFER_GRAPHICS_OWNED", "")',
        "and not EARLYFRAMEBUFFERGRAPHICSOWNED",
        "native DRM fbdev launch lacks confirmed KD_TEXT ownership",
        '"legacy_console_owned": bool(FRAMEBUFFERCONSOLEOWNED)',
    ):
        require(graphics, text, "early framebuffer console ownership")

    presentation_proof = function(
        graphics_tree,
        "framebufferpresentationproof",
    )
    presentation_proof_source = (
        ast.get_source_segment(graphics, presentation_proof) or ""
    )
    if "EARLYFRAMEBUFFERGRAPHICSOWNED" in presentation_proof_source:
        raise RuntimeError(
            "early KD_GRAPHICS ownership can certify a lock-screen fallback"
        )

    if goddess_main_source.index("bootanimation = startbootanimation('dots')") >= goddess_main_source.index(
        "runstartup(startupenvironment, wsproc)"
    ):
        raise RuntimeError("GODDESS does not start boot progress before startup")

    for text in (
        'bootanimationhandoff("lockscreen", 3.0)',
        'bootanimationhandoff("brand", 8.0)',
        "def runlockscreenwithhandoff(timeout=20.0):",
        'if state == "ready":',
        "process = popenisolated(",
        "softwarepath=LOCKSCREENSCRIPT",
        "logpath=LOCKSCREENLOG",
        'BOOTANIMATIONREQUEST = os.path.join(BOOTANIMATIONBASE, "request.json")',
        '"pid": int(pid)',
        "waitlockscreenposthandoff(firstreceipt)",
        "def lockscreenreceiptphysicallyverified(",
        '"write-combined-device-mapping"',
        '"native-drm-fbdev-write-combined-mapping"',
        'vblank.get("advanced") is True',
        'proof.get("legacy_page_zero") is True',
        "def currentvisiblelockscreen(",
        "boot animation process state ",
        "lagged verified lock-screen handoff",
        "boot animation already absent ",
        'LOCKSCREENPOSTHANDOFFSTATE = os.path.join(',
        '"post-handoff-ready.json"',
        "def writeposthandoffstate(",
        '"physically_verified": True',
        "os.replace(temporary, LOCKSCREENPOSTHANDOFFSTATE)",
        "post-handoff lock screen presentation verified",
    ):
        require(startup, text, "startup boot-animation handoff")

    require(
        qemu,
        "grep -Fq 'I VERIFIED THE LOCK SCREEN AFTER THE DISPLAY HANDOFF ON PROCESS '",
        "QEMU post-handoff acceptance gate",
    )

    verifier_node = function(
        startup_tree,
        "lockscreenreceiptphysicallyverified",
    )
    verifier_namespace = {}
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(body=[verifier_node], type_ignores=[])
            ),
            str(startup_path),
            "exec",
        ),
        verifier_namespace,
    )
    verify_receipt = verifier_namespace[
        "lockscreenreceiptphysicallyverified"
    ]
    kms_receipt = {
        "backend": "kms-framebuffer",
        "drm_driver": "nvidia-drm",
        "hardware_accelerated": False,
        "full_coverage": True,
        "frame_sequence": 8,
        "presentation_proof": {
            "verified": True,
            "nonblack": True,
            "scanout": True,
            "connector_connected": True,
            "connector_routed": True,
            "connector_link_status": "good",
            "vblank_sequence": {"advanced": True},
            "presentation_boundary": "drm-crtc-sequence",
            "write_committed": True,
            "mode_matches": True,
            "readback": False,
            "readback_skipped": "write-combined-device-mapping",
        },
    }
    if not verify_receipt(kms_receipt):
        raise RuntimeError(
            "startup rejects the bounded CPU-KMS presentation receipt"
        )

    stalled_kms_receipt = copy.deepcopy(kms_receipt)
    stalled_kms_receipt["presentation_proof"]["vblank_sequence"][
        "advanced"
    ] = False
    if verify_receipt(stalled_kms_receipt):
        raise RuntimeError(
            "startup accepts a CPU-KMS receipt without advancing scanout"
        )

    virtio_kms_receipt = copy.deepcopy(kms_receipt)
    virtio_kms_receipt["drm_driver"] = "virtio_gpu"
    virtio_kms_receipt["presentation_proof"].update({
        "vblank_sequence": {
            "advanced": False,
            "unsupported": True,
        },
        "presentation_boundary": "virtio-resource-flush",
        "dirty_status": "complete",
        "present_sequence": 2,
    })
    if not verify_receipt(virtio_kms_receipt):
        raise RuntimeError(
            "startup rejects the explicit virtio host-flush boundary"
        )

    physical_without_vblank = copy.deepcopy(virtio_kms_receipt)
    physical_without_vblank["drm_driver"] = "nvidia-drm"
    if verify_receipt(physical_without_vblank):
        raise RuntimeError(
            "startup lets a physical DRM driver bypass advancing scanout"
        )

    native_fbdev_receipt = {
        "backend": "framebuffer",
        "hardware_accelerated": False,
        "full_coverage": True,
        "frame_sequence": 4,
        "presentation_proof": {
            "verified": True,
            "nonblack": True,
            "scanout": True,
            "legacy_page_zero": True,
            "legacy_console_owned": True,
            "legacy_pan_committed": True,
            "legacy_owner_connected": True,
            "connector_link_status": "good",
            "vblank_sequence": {"advanced": True},
            "presentation_boundary": "drm-crtc-sequence",
            "readback": False,
            "readback_skipped":
                "native-drm-fbdev-write-combined-mapping",
        },
    }
    if not verify_receipt(native_fbdev_receipt):
        raise RuntimeError(
            "startup rejects the bounded native DRM fbdev receipt"
        )

    firmware_fb_receipt = {
        "backend": "framebuffer",
        "hardware_accelerated": False,
        "full_coverage": True,
        "frame_sequence": 2,
        "presentation_proof": {
            "verified": True,
            "nonblack": True,
            "scanout": True,
            "legacy_page_zero": True,
            "legacy_firmware_framebuffer": True,
            "firmware_framebuffer_boot": True,
            "readback": True,
        },
    }
    if not verify_receipt(firmware_fb_receipt):
        raise RuntimeError(
            "startup rejects the explicit firmware framebuffer receipt"
        )

    lockscreen_verifier_node = function(
        lockscreen_tree,
        "lockscreenreceiptphysicallyverified",
    )
    lockscreen_verifier_namespace = {}
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[lockscreen_verifier_node],
                    type_ignores=[],
                )
            ),
            str(lockscreen_path),
            "exec",
        ),
        lockscreen_verifier_namespace,
    )
    lockscreen_verify_receipt = lockscreen_verifier_namespace[
        "lockscreenreceiptphysicallyverified"
    ]

    for label, receipt, expected in (
        ("physical KMS", kms_receipt, True),
        ("stalled physical KMS", stalled_kms_receipt, False),
        ("virtio KMS", virtio_kms_receipt, True),
        ("spoofed physical host flush", physical_without_vblank, False),
        ("native fbdev", native_fbdev_receipt, True),
        ("firmware framebuffer", firmware_fb_receipt, True),
    ):
        if bool(lockscreen_verify_receipt(receipt)) != expected:
            raise RuntimeError(
                f"lock screen receipt verifier disagrees for {label}"
            )
        if bool(verify_receipt(receipt)) != expected:
            raise RuntimeError(
                f"startup receipt verifier disagrees for {label}"
            )

    startup_main = function(startup_tree, "main")
    startup_main_source = ast.get_source_segment(startup, startup_main) or ""
    if startup_main_source.index("runlockscreenwithhandoff()") >= startup_main_source.index(
        "loginuser()"
    ):
        raise RuntimeError("existing-account lock screen does not precede login")

    if startup_main_source.index('bootanimationhandoff("brand", 8.0)') >= startup_main_source.index(
        "setupuser()"
    ):
        raise RuntimeError("first-run branding is not completed before account setup")

    session_main = function(startup_tree, "sessionlockmain")
    session_main_source = ast.get_source_segment(startup, session_main) or ""
    session_lockscreen = session_main_source.index("runlockscreenwithhandoff()")
    session_login = session_main_source.index(
        "loginuser(sessionbroker=True)", session_lockscreen
    )
    session_notification = session_main_source.index(
        "notifysessionauthenticated()", session_login
    )

    if not session_lockscreen < session_login < session_notification:
        raise RuntimeError(
            "session locking does not preserve the lock-screen -> login -> "
            "authentication chain"
        )

    for text in (
        "while True:",
        "if not username:",
        "if not notifysessionauthenticated():",
        "resetsessionwindow()",
    ):
        require(session_main_source, text, "fail-closed session lock")

    create_startup_window = function(startup_tree, "wscreatewindow")
    create_startup_window_source = (
        ast.get_source_segment(startup, create_startup_window) or ""
    )
    require(
        create_startup_window_source,
        '"path": STARTUPSCRIPT',
        "startup authentication identity",
    )

    window_lock = function(windowserver_tree, "locksession")
    window_lock_source = ast.get_source_segment(windowserver, window_lock) or ""

    for text in (
        "SESSIONLOCKED or sessionlockactive()",
        'operationssend({"action": "SESSION_LOCK_START"})',
        'LOCKSCREENPID = int(response.get("pid", 0))',
        'LOCKSCREENPID, "lockscreen", timeout=1.0',
        "LOCKSCREENIDENTITY.get('starttime', 0)",
        "session-lock broker identity mismatch",
        "LOCKSESSIONPROCESS = None",
        "SESSIONLOCKED = True",
    ):
        require(window_lock_source, text, "WindowServer session lock launcher")

    for stale in (
        "popenisolated(",
        "softwarepath=",
        "operationsregisterpid(",
        "STARTUPPATH",
        '"session-lock"',
    ):
        if stale in window_lock_source:
            raise RuntimeError(
                f"WindowServer bypasses the Operations session-lock broker: {stale}"
            )

    broker_requests = []
    identity_waits = []
    closed_identities = []
    clipboard_clears = []
    lockscreen_identity = {
        "pid": 7301,
        "starttime": 44021,
        "domain": "lockscreen",
    }

    lock_namespace = {
        "LOCKSCREENPID": None,
        "LOCKSCREENLAST": 0.0,
        "LOCKSESSIONPROCESS": None,
        "LOCKSCREENIDENTITY": None,
        "SESSIONLOCKED": False,
        "LOCKSCREENCOOLDOWN": 0.35,
        "time": __import__("time"),
        "lockscreenactive": lambda: False,
        "startupactive": lambda: False,
        "operationssend": lambda request: (
            broker_requests.append(dict(request))
            or {"status": "ok", "pid": 7301, "identity": "7301:44021"}
        ),
        "waitforprocessidentity": lambda pid, domain, timeout=0.0: (
            identity_waits.append((int(pid), str(domain), float(timeout)))
            or copy.deepcopy(lockscreen_identity)
        ),
        "closeprocessidentity": lambda identity: closed_identities.append(
            copy.deepcopy(identity)
        ),
        "clearclipboard": lambda: clipboard_clears.append(True),
        "log": lambda message: None,
    }
    lock_namespace["sessionlockactive"] = lambda: False
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(body=[copy.deepcopy(window_lock)], type_ignores=[])
            ),
            str(windowserver_path),
            "exec",
        ),
        lock_namespace,
    )
    lock_namespace["locksession"]()
    lock_namespace["locksession"]()

    if broker_requests != [{"action": "SESSION_LOCK_START"}]:
        raise RuntimeError(
            "duplicate Win+L did not produce exactly one Operations broker request"
        )

    if identity_waits != [(7301, "lockscreen", 1.0)]:
        raise RuntimeError(
            "Win+L did not bind the broker child to its lockscreen domain identity"
        )

    if lock_namespace["LOCKSCREENPID"] != 7301:
        raise RuntimeError("Win+L did not retain the broker-owned lockscreen pid")

    if lock_namespace["LOCKSCREENIDENTITY"] != lockscreen_identity:
        raise RuntimeError(
            "Win+L did not retain the broker-owned pid/start/domain identity"
        )

    if lock_namespace["LOCKSESSIONPROCESS"] is not None:
        raise RuntimeError("WindowServer retained a direct session-lock process handle")

    if not lock_namespace["SESSIONLOCKED"]:
        raise RuntimeError("Operations-brokered Win+L did not lock the session")

    if clipboard_clears != [True] or closed_identities:
        raise RuntimeError(
            "successful brokered session lock did not preserve its identity lifecycle"
        )

    authentication = function(windowserver_tree, "sessionauthenticated")
    authentication_source = (
        ast.get_source_segment(windowserver, authentication) or ""
    )

    for text in (
        'state.get("peer_pid")',
        "LOCKSCREENPID",
        'clienthascapability(cid, "session_authentication")',
        'sameprocessidentity(state.get("identity"), LOCKSCREENIDENTITY)',
        "processidentitycurrent(LOCKSCREENIDENTITY)",
        'win.get("cid") == cid',
        'win.get("mapped")',
        'win.get("role", "")) == "lockscreen"',
        'win.get("path", "")) == os.path.realpath(STARTUPPATH)',
        "invalidatelockscreenpresentation()",
        "SESSIONLOCKED = False",
    ):
        require(
            authentication_source,
            text,
            "peer-bound session authentication",
        )

    if 'win.get("role", "")) == "startup"' in authentication_source:
        raise RuntimeError(
            "session authentication still trusts the obsolete startup window role"
        )

    authentication_messages = []
    presentation_invalidations = []
    authentication_namespace = {
        "SESSIONLOCKED": True,
        "LOCKSCREENPID": 7301,
        "LOCKSCREENIDENTITY": copy.deepcopy(lockscreen_identity),
        "STARTUPPATH": "/the one/build/startup/startup.py",
        "clients": {
            11: {
                "peer_pid": 7301,
                "identity": copy.deepcopy(lockscreen_identity),
            },
            12: {
                "peer_pid": 9999,
                "identity": {
                    "pid": 9999,
                    "starttime": 44021,
                    "domain": "lockscreen",
                },
            },
            13: {
                "peer_pid": 7301,
                "identity": {
                    "pid": 7301,
                    "starttime": 44020,
                    "domain": "lockscreen",
                },
            },
        },
        "windows": {
            81: {
                "cid": 11,
                "mapped": True,
                "role": "lockscreen",
                "path": "/the one/build/startup/startup.py",
            },
            82: {
                "cid": 13,
                "mapped": True,
                "role": "lockscreen",
                "path": "/the one/build/startup/startup.py",
            },
        },
        "sessionlockactive": lambda: True,
        "clienthascapability": lambda cid, capability: (
            capability == "session_authentication" and cid in (11, 12, 13)
        ),
        "sameprocessidentity": lambda left, right: left == right,
        "processidentitycurrent": lambda identity: identity == lockscreen_identity,
        "invalidatelockscreenpresentation": lambda: (
            presentation_invalidations.append(True) or True
        ),
        "os": __import__("os"),
        "sendjson": lambda cid, message: authentication_messages.append(
            (cid, dict(message))
        ),
        "log": lambda message: None,
    }
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[copy.deepcopy(authentication)],
                    type_ignores=[],
                )
            ),
            str(windowserver_path),
            "exec",
        ),
        authentication_namespace,
    )

    if authentication_namespace["sessionauthenticated"](
            12, {"winid": 81}):
        raise RuntimeError("an unrelated peer authenticated the locked session")

    if not authentication_namespace["SESSIONLOCKED"]:
        raise RuntimeError("denied session authentication unlocked the desktop")

    if authentication_namespace["sessionauthenticated"](
            13, {"winid": 82}):
        raise RuntimeError(
            "a reused lockscreen pid with the wrong start identity authenticated"
        )

    if not authentication_namespace["SESSIONLOCKED"]:
        raise RuntimeError("wrong-generation authentication unlocked the desktop")

    if not authentication_namespace["sessionauthenticated"](
            11, {"winid": 81}):
        raise RuntimeError("the owning lockscreen peer could not authenticate")

    if authentication_namespace["SESSIONLOCKED"]:
        raise RuntimeError("successful authentication left the session locked")

    if authentication_messages[-1][1] != {
            "op": "SESSION_AUTHENTICATED",
            "authenticated": True,
    }:
        raise RuntimeError("successful authentication did not receive an ack")

    if presentation_invalidations != [True]:
        raise RuntimeError(
            "session authentication did not invalidate the lockscreen presentation"
        )

    unlock_node = function(lockscreen_tree, "unlockrequest")
    unlock_source = ast.get_source_segment(lockscreen, unlock_node) or ""

    for text in (
        "time.monotonic() < _unlocknotbefore",
        "with open(POSTHANDOFFSTATE, 'r', encoding='utf-8')",
        "int(handoff.get('pid', 0)) == int(os.getpid())",
        "handoff.get('boot_active') is False",
        "handoff.get('physically_verified') is True",
    ):
        require(
            unlock_source,
            text,
            "lock-screen unlock authority",
        )

    handoff_receipt = {
        "format": 1,
        "state": "ready",
        "pid": 7301,
        "boot_active": False,
        "physically_verified": True,
    }
    json_module = __import__("json")
    io_module = __import__("io")

    class LockScreenProcessOS:
        @staticmethod
        def getpid():
            return 7301

    def openhandoff(*args, **kwargs):
        return io_module.StringIO(json_module.dumps(handoff_receipt))

    unlock_namespace = {
        "_winid": 81,
        "_unlocknotbefore": 0.0,
        "_lastdiagnostic": None,
        "POSTHANDOFFSTATE": "/.ephemeral/lock screen/post-handoff-ready.json",
        "time": time,
        "json": json_module,
        "os": LockScreenProcessOS,
        "open": openhandoff,
        "logline": lambda message: None,
    }
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(
                    body=[copy.deepcopy(unlock_node)],
                    type_ignores=[],
                )
            ),
            str(lockscreen_path),
            "exec",
        ),
        unlock_namespace,
    )
    unlock_request = unlock_namespace["unlockrequest"]

    unlock_namespace["_unlocknotbefore"] = time.monotonic() + 1.0
    if unlock_request(
            {"op": "KEY", "winid": 81, "key": "ENTER", "state": "down"}):
        raise RuntimeError("queued pre-handoff input bypassed the unlock grace period")
    unlock_namespace["_unlocknotbefore"] = 0.0

    def missinghandoff(*args, **kwargs):
        raise FileNotFoundError("synthetic missing post-handoff receipt")

    unlock_namespace["open"] = missinghandoff
    if unlock_request(
            {"op": "KEY", "winid": 81, "key": "ENTER", "state": "down"}):
        raise RuntimeError("lock screen unlocked without Startup's handoff receipt")
    unlock_namespace["open"] = openhandoff

    for event in (
        {"op": "KEY", "winid": 81, "key": "SPACE", "state": "down"},
        {"op": "KEY", "winid": 81, "key": "ENTER", "state": "down"},
    ):
        if not unlock_request(event):
            raise RuntimeError("Space/Enter lock-screen activation was ignored")

    for event in (
        {"op": "KEY", "winid": 81, "key": "A", "state": "down"},
        {"op": "POINTER_MOTION", "winid": 81},
        {"op": "KEY", "winid": 82, "key": "ENTER", "state": "down"},
        {
            "op": "POINTER_BUTTON",
            "winid": 81,
            "button": 1,
            "state": "down",
        },
        {
            "op": "POINTER_BUTTON",
            "winid": 81,
            "button": 1,
            "state": "up",
        },
    ):
        if unlock_request(event):
            raise RuntimeError("non-activation input advanced the lock screen")

    for text in (
        "LIFECYCLEBASE = '/.ephemeral/lock screen'",
        "lifecyclewrite('starting')",
        "lifecyclewrite('ready')",
        "lifecyclewrite('failed'",
        "lifecyclewrite('unlocked', 'verified activation request')",
    ):
        require(lockscreen, text, "lock-screen first-frame barrier")

    initlock = function(lockscreen_tree, "initlock")
    initlock_source = ast.get_source_segment(lockscreen, initlock) or ""
    if initlock_source.index("lifecyclewrite('ready')") <= initlock_source.index("ok = wsmap(_winid)"):
        raise RuntimeError("lock screen reports readiness before mapping its first frame")

    presentation_wait = function(
        lockscreen_tree,
        "waitacceleratedpresentation",
    )
    startup_wait = function(startup_tree, "runlockscreenwithhandoff")
    inner_timeout = ast.literal_eval(presentation_wait.args.defaults[-1])
    outer_timeout = ast.literal_eval(startup_wait.args.defaults[-1])

    if not 0 < float(inner_timeout) < float(outer_timeout):
        raise RuntimeError(
            "the lock-screen presentation barrier cannot publish its detailed "
            "failure before Startup's outer child timeout"
        )

    print("Boot animation lifecycle validation passed.")


if __name__ == "__main__":
    main()
