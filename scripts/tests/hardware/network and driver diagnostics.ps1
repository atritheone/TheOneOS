[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path

function ConvertTo-T1OSWslPath {
    param([Parameter(Mandatory)][string]$Path)

    $converted = & wsl.exe -d Ubuntu --exec wslpath -a $Path
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Could not translate test path for WSL: $Path"
    }
    return ([string]($converted | Select-Object -First 1)).Trim()
}

$wslProjectRoot = ConvertTo-T1OSWslPath -Path $projectRoot
$initScript = Join-Path $projectRoot 'source\entry\init\init hardware.sh'
$angelContract = Join-Path $projectRoot 'source\entry\init\ANGEL.md'
$angelVoiceTest = Join-Path $projectRoot 'scripts\tests\test angel voice.py'
$angelRecoveryTest = Join-Path $projectRoot 'scripts\tests\test angel recovery.ps1'
$initramfsBuilder = Join-Path $projectRoot 'scripts\build\build hardware initramfs.ps1'
$bootPolicyBuilder = Join-Path $projectRoot 'scripts\build\build boot protected roots.py'
$ntfsCheckerBuilder = Join-Path $projectRoot 'scripts\build\build roothealth.ps1'
$ntfsCheckerTest = Join-Path $projectRoot 'scripts\tests\test roothealth.ps1'
$ntfsChecker = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
$ntfsCheckerMetadata = Join-Path $projectRoot 'environment\hardware\tools\roothealth.json'
$ntfsCheckerLicense = Join-Path $projectRoot 'environment\hardware\tools\roothealth.COPYING'
$ntfsCheckerSourceArchive = Join-Path $projectRoot 'environment\hardware\tools\roothealth-source.tar.gz'
$ntfsCheckerProductPatch = Join-Path $projectRoot 'source\entry\roothealth\0001-roothealth-read-only-checker.patch'
$ntfsCheckerSecurityPatch = Join-Path $projectRoot 'source\entry\roothealth\0002-ntfs-3g-2026.7.7-index-hardening.patch'
$ntfsCheckerVerdictPatch = Join-Path $projectRoot 'source\entry\roothealth\0003-roothealth-verdict-hardening.patch'
$imageBuilder = Join-Path $projectRoot 'scripts\create hardware usb image.ps1'
$bundleBuilder = Join-Path $projectRoot 'scripts\create hardware usb bundle.ps1'
$bundleValidator = Join-Path $projectRoot 'scripts\test hardware usb bundle.ps1'
$flashScript = Join-Path $projectRoot 'scripts\flash hardware usb.ps1'
$imageValidator = Join-Path $projectRoot 'scripts\validate hardware usb image.ps1'
$productionPreparer = Join-Path $projectRoot 'scripts\build\prepare prod build.ps1'
$hardwareUsbWorkflow = Join-Path $projectRoot 'scripts\build\build hardware usb.ps1'
$kernelBuilder = Join-Path $projectRoot 'scripts\build\build hardware kernel.ps1'
$graphicsKernelBuilder = Join-Path $projectRoot 'scripts\build\build graphics kernel.ps1'
$rootPushScript = Join-Path $projectRoot 'scripts\deployment\push to disk.ps1'
$hardwareKernelPushScript = Join-Path $projectRoot 'scripts\deployment\push hardware kernel to usb.ps1'
$grubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware 0.2.cfg'
$encryptedGrubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware encrypted 0.2.cfg'
$grubTheme = Join-Path $projectRoot 'source\entry\grub\t1os hardware theme.txt'
$grubBackground = Join-Path $projectRoot 'source\entry\grub\t1os black background.png.base64'
$kernelConfig = Join-Path $projectRoot 'source\entry\kernel\T10Skernel hardware 0.19 settings.txt'
$kernelPolicy = Join-Path $projectRoot 'source\entry\kernel\t1os_lsm.c'
$goddessScript = Join-Path $projectRoot 'source\build software\GODDESS\GODDESS.py'
$expanseScript = Join-Path $projectRoot 'source\build software\expanse\expanse.py'
$authenticationBroker = Join-Path $projectRoot 'source\build software\broker\broker.py'
$inputServer = Join-Path $projectRoot 'source\build software\input\inputserver.py'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$kernel = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$initramfs = Join-Path $hardwareRoot 'boot\initramfs-hardware'
$pythonManifest = Join-Path $projectRoot 'source\software\python\manifest.json'
$pythonRelease = [string](
    Get-Content -LiteralPath $pythonManifest -Raw | ConvertFrom-Json
).release
if ($pythonRelease -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$') {
    throw 'The canonical Python manifest has an invalid release identifier.'
}
$firmwareArchive = Join-Path $hardwareRoot 'firmware.tar.zst'
$firmwareManifest = Join-Path $hardwareRoot 't1os-firmware-manifest.json'
$moduleArchive = Join-Path $hardwareRoot 'modules.tar.zst'
$driverServer = Join-Path $projectRoot 'source\build software\drivers\driverserver.py'
$operationsScript = Join-Path $projectRoot 'source\build software\operations\operations.py'
$moduleLoader = Join-Path $projectRoot 'source\drivers\tools\modprobe'
$driverPolicy = Join-Path $projectRoot 'source\drivers\settings\policy.json'
$desktopCompatibility = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
$compatibilityValidator = Join-Path $projectRoot 'scripts\audits\validate hardware compatibility.ps1'
$driverRuntime = Join-Path $projectRoot 'source\drivers\settings\runtime.json'
$networkServer = Join-Path $projectRoot 'source\build software\network\network.py'
$wirelessEngine = Join-Path $projectRoot 'source\software\network\wireless-engine'
$networkLoader = Join-Path $projectRoot 'source\catalogue\network\ld-linux-x86-64.so.2'
$networkCertificates = Join-Path $projectRoot 'source\settings\network\cacerts.pem'
$graphicsCatalogueRoot = Join-Path $projectRoot 'source\catalogue\graphics'
$graphicsCatalogue = Join-Path $graphicsCatalogueRoot 'catalogue.json'
$intelVaapi = Join-Path $graphicsCatalogueRoot 'drivers\iHD_drv_video.so'
$r600Vaapi = Join-Path $graphicsCatalogueRoot 'drivers\r600_drv_video.so'
$radeonsiVaapi = Join-Path $graphicsCatalogueRoot 'drivers\radeonsi_drv_video.so'
$nouveauVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nouveau_drv_video.so'
$virtioVaapi = Join-Path $graphicsCatalogueRoot 'drivers\virtio_gpu_drv_video.so'
$vmwgfxVaapi = Join-Path $graphicsCatalogueRoot 'drivers\vmwgfx_drv_video.so'
$nouveauDrm = Join-Path $graphicsCatalogueRoot 'libdrm_nouveau.so.2'
$nouveauVulkan = Join-Path $graphicsCatalogueRoot 'libvulkan_nouveau.so'
$vulkanLoader = Join-Path $projectRoot 'source\catalogue\graphics\libvulkan.so.1'
$nvidiaEgl = Join-Path $graphicsCatalogueRoot 'nvidia\libEGL.so.1'
$nvidiaGles = Join-Path $graphicsCatalogueRoot 'nvidia\libGLESv2.so.2'
$nvidiaEglVendor = Join-Path $graphicsCatalogueRoot 'nvidia\egl_vendor.d\10_nvidia.json'
$nvidiaGbmBackend = Join-Path $graphicsCatalogueRoot 'nvidia\gbm\nvidia-drm_gbm.so'
$nvidiaPathProvider = Join-Path $graphicsCatalogueRoot 'nvidia\t1os-nvidia-path-provider.so'
$nvidiaPathProviderSource = Join-Path $projectRoot 'source\entry\graphics\t1os_nvidia_path_provider.c'
$nvidiaRuntime = Join-Path $graphicsCatalogueRoot 'nvidia\runtime.json'
$nvidiaVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nvidia_drv_video.so'
$nvidiaCuda = Join-Path $graphicsCatalogueRoot 'nvidia\libcuda.so.1'
$nvidiaNvcuvid = Join-Path $graphicsCatalogueRoot 'nvidia\libnvcuvid.so.1'
$nvidiaPtxjit = Join-Path $graphicsCatalogueRoot 'nvidia\libnvidia-ptxjitcompiler.so.1'
$gstreamerCore = Join-Path $graphicsCatalogueRoot 'libgstreamer-1.0.so.0'
$gstreamerBase = Join-Path $graphicsCatalogueRoot 'libgstbase-1.0.so.0'
$gstreamerCodecParsers = Join-Path $graphicsCatalogueRoot 'libgstcodecparsers-1.0.so.0'
$mediaDecodeService = Join-Path $projectRoot 'source\software\audio\t1-media-decoderd'
$mediaDecodeWorker = Join-Path $projectRoot 'source\software\audio\t1-video-decode'
$audioRuntimeManifest = Join-Path $projectRoot 'source\software\audio\manifest.json'
$mediaDecodeServiceSource = Join-Path $projectRoot 'source\native\video\t1_media_decoded.c'
$mediaDecodeWorkerSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_worker.c'
$mediaDecodeProtocolSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_protocol.h'
$chromiumServer = Join-Path $projectRoot 'source\build software\chromium\chromium.py'
$chromiumEngine = Join-Path $projectRoot 'source\software\chromium\program\chrome'
$chromiumSandbox = Join-Path $projectRoot 'source\software\chromium\program\chrome-sandbox'
$chromiumLibc = Join-Path $projectRoot 'source\software\chromium\libraries\libc.so.6'
$chromiumLibasound = Join-Path $projectRoot 'source\software\chromium\libraries\libasound.so.2'
$chromiumProvider = Join-Path $projectRoot 'source\software\chromium\t1os-path-provider.so'
$chromiumProviderSource = Join-Path $projectRoot 'source\entry\chromium\t1os_path_provider.c'
$chromiumInputBridge = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xinput'
$chromiumInputBridgeSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xinput.c'
$chromiumWindowManager = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xwm'
$chromiumWindowManagerSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xwm.c'
$windowServer = Join-Path $projectRoot 'source\build software\windows\windowserver.py'
$brickScript = Join-Path $projectRoot 'source\build software\brick\brick.py'
$chromiumSubprocess = Join-Path $projectRoot 'source\software\chromium\tools\t1os-chrome-subprocess'
$chromiumSubprocessSource = Join-Path $projectRoot 'source\entry\chromium\t1os_chrome_subprocess.c'
$runtimePathContract = Join-Path $projectRoot 'source\settings\runtime paths.json'
$networkInitializationCheck = @'
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types

project_root = Path(sys.argv[1])
network_path = project_root / "source/build software/network/network.py"

pyroute2 = types.ModuleType("pyroute2")
pyroute2.IPRoute = object
sys.modules["pyroute2"] = pyroute2

reign_package = types.ModuleType("reign")
reign_module = types.ModuleType("reign.reign")
reign_module.timestamp = lambda: "test"
reign_module.formatlog = lambda software, message, epoch=None: f"[{software}] {message}"
sys.modules["reign"] = reign_package
sys.modules["reign.reign"] = reign_module

goddess_package = types.ModuleType("GODDESS")
goddess_module = types.ModuleType("GODDESS.GODDESS")
goddess_module.formatlog = reign_module.formatlog
goddess_module.popenisolated = lambda *args, **kwargs: None
sys.modules["GODDESS"] = goddess_package
sys.modules["GODDESS.GODDESS"] = goddess_module

operations_package = types.ModuleType("operations")
operations_module = types.ModuleType("operations.operations")
operations_module.service_secret_get = lambda *_args, **_kwargs: None
sys.modules["operations"] = operations_package
sys.modules["operations.operations"] = operations_module

spec = importlib.util.spec_from_file_location("t1os_network_test", network_path)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)
network.ensurehostfirewall = lambda: True

established_expressions = network._nftestablishedrelated()
bitwise_expression = next(
    expression for expression in established_expressions
    if dict(expression["attrs"])["NFTA_EXPR_NAME"] == "bitwise"
)
bitwise_attributes = dict(
    dict(bitwise_expression["attrs"])["NFTA_EXPR_DATA"]["attrs"]
)
state_mask = dict(
    bitwise_attributes["NFTA_BITWISE_MASK"]["attrs"]
)["NFTA_DATA_VALUE"]
expected_state_mask = (0x06).to_bytes(4, sys.byteorder)
if state_mask != expected_state_mask:
    raise SystemExit(
        "nftables conntrack state mask is not native-endian: "
        f"expected {expected_state_mask.hex()}, got {state_mask.hex()}"
    )

with tempfile.TemporaryDirectory() as temporary:
    network.NETDIR = temporary
    network.DNSCONF = os.path.join(temporary, "dns.txt")
    network.LOGFILE = os.path.join(temporary, "network.log")
    if not network.configuredns(["10.0.2.3", "invalid", "10.0.2.3", "1.1.1.1"]):
        raise SystemExit("DHCP DNS persistence rejected valid nameservers")
    expected_dns = (
        "nameserver 10.0.2.3\n"
        "nameserver 1.1.1.1\n"
        "options timeout:2 attempts:3\n"
    )
    actual_dns = Path(network.DNSCONF).read_text(encoding="utf-8")
    if actual_dns != expected_dns:
        raise SystemExit(f"DHCP DNS persistence regression: {actual_dns!r}")

    original_control = network.wirelesscontrolcommand
    network.wirelesscontrolcommand = lambda _iface, _command, timeout=2: (
        "wpa_state=COMPLETED\nssid=MyHomeWiFi-AX\n"
    )
    try:
        if network.connectedwirelessname("wlan0") != "MyHomeWiFi-AX":
            raise SystemExit("associated Wi-Fi name capitalization was not preserved")
    finally:
        network.wirelesscontrolcommand = original_control

    ethernet_id = network.ethernetconnectionid(
        "eth0", "192.168.1.1", "192.168.1.1", "d8:43:ae:53:56:ca"
    )
    if ethernet_id != network.ethernetconnectionid(
        "eth0", "192.168.1.1", "192.168.1.1", "d8:43:ae:53:56:ca"
    ):
        raise SystemExit("Ethernet connection identity was not stable")
    if ethernet_id == network.ethernetconnectionid(
        "eth0", "10.0.2.2", "10.0.2.2", "d8:43:ae:53:56:ca"
    ):
        raise SystemExit("distinct Ethernet connections received the same identity")

    virtualbox_dns = network.dnsserversforlease(
        "10.0.2.2", ["103.86.96.100"], isvirtualbox=True
    )
    if virtualbox_dns != ["10.0.2.3", "103.86.96.100"]:
        raise SystemExit(f"VirtualBox NAT DNS proxy regression: {virtualbox_dns!r}")

request = network.dhcprequestpacket(
    "d8:43:ae:53:56:ca", 0x12345678, "192.168.1.102", "192.168.1.1"
)
request_options = network.parsedhcpoptions(request)
if len(request) < 300:
    raise SystemExit(f"DHCPREQUEST is below the BOOTP minimum: {len(request)}")
if request[4:8] != bytes.fromhex("12345678"):
    raise SystemExit("DHCPREQUEST transaction identifier regression")
if request_options.get(53) != b"\x03":
    raise SystemExit("DHCPREQUEST message type regression")
if request_options.get(50) != bytes((192, 168, 1, 102)):
    raise SystemExit("DHCPREQUEST requested-address regression")
if request_options.get(54) != bytes((192, 168, 1, 1)):
    raise SystemExit("DHCPREQUEST server-identifier regression")
if request_options.get(61) != b"\x01" + bytes.fromhex("d843ae5356ca"):
    raise SystemExit("DHCPREQUEST did not preserve the DHCP client identifier")
if request_options.get(57) != bytes((2, 64)):
    raise SystemExit("DHCPREQUEST maximum-message-size regression")
if request_options.get(55) != bytes((1, 3, 6, 15, 28, 51, 58, 59)):
    raise SystemExit("DHCPREQUEST parameter request list regression")

ack = bytearray(network.dhcpbasepacket("d8:43:ae:53:56:ca", 0x12345678))
ack[0] = 2
ack.extend(b"\x35\x01\x05\xff")
ack = network.padbootp(bytes(ack))
socket_events = []

class FakeRoute:
    def link_lookup(self, ifname):
        socket_events.append(("lookup", ifname))
        return [2]

    def route(self, operation, **values):
        socket_events.append(("route", operation, values))

    def close(self):
        socket_events.append(("route-close",))

class FakeSocket:
    def setsockopt(self, *values):
        socket_events.append(("setsockopt",) + values)

    def bind(self, address):
        socket_events.append(("bind", address))

    def settimeout(self, value):
        socket_events.append(("timeout", value))

    def sendto(self, packet, address):
        socket_events.append(("send", packet, address))
        return len(packet)

    def recvfrom(self, _size):
        return ack, ("192.168.1.1", 67)

    def close(self):
        socket_events.append(("socket-close",))

original_socket = network.socket.socket
original_route = network.IPRoute
original_log = network.log
original_bind_to_device = getattr(network.socket, "SO_BINDTODEVICE", None)
try:
    network.socket.socket = lambda *_args, **_values: FakeSocket()
    network.socket.SO_BINDTODEVICE = 25
    network.IPRoute = FakeRoute
    network.dhcppacketlistener = lambda _iface: None
    network.log = lambda message: socket_events.append(("log", message))
    if not network.dhcprequest(
        "eth0", "d8:43:ae:53:56:ca", 0x12345678,
        "192.168.1.102", "192.168.1.1"
    ):
        raise SystemExit(f"DHCPREQUEST rejected a matching DHCPACK: {socket_events!r}")
finally:
    network.socket.socket = original_socket
    if original_bind_to_device is None:
        del network.socket.SO_BINDTODEVICE
    else:
        network.socket.SO_BINDTODEVICE = original_bind_to_device
    network.IPRoute = original_route
    network.log = original_log

sent = [event for event in socket_events if event[0] == "send"]
if len(sent) != 1 or len(sent[0][1]) < 300:
    raise SystemExit("DHCPREQUEST transaction did not send one padded packet")
if not any(event[:2] == ("route", "replace") for event in socket_events):
    raise SystemExit("DHCPREQUEST transaction did not install a link broadcast route")

ethernet = bytes.fromhex("ffffffffffffd843ae5356ca0800")
ipv4 = bytearray(20)
ipv4[0] = 0x45
ipv4[9] = 17
ipv4[12:16] = bytes((192, 168, 1, 1))
ipv4[16:20] = bytes((192, 168, 1, 102))
udp = bytearray(8)
udp[0:2] = (67).to_bytes(2, "big")
udp[2:4] = (68).to_bytes(2, "big")
udp[4:6] = (8 + len(ack)).to_bytes(2, "big")
payload, peer = network.dhcpframepayload(ethernet + ipv4 + udp + ack)
if payload != ack or peer != ("192.168.1.1", 67):
    raise SystemExit("DHCP link-layer unicast ACK extraction regression")

network.NETDIR = "/the one/settings/network"
network.DNSCONF = "/the one/settings/network/dns.txt"
network.LOGFILE = os.devnull

events = []
link_up = False

def inventory():
    return [{
        "name": "eth0",
        "index": 2,
        "carrier": link_up,
        "operstate": "UP" if link_up else "DOWN",
        "up": link_up,
        "wireless": False,
        "mac": "08:00:27:81:ba:ca",
    }]

def bring_up(iface):
    global link_up
    events.append(("up", iface))
    link_up = True
    return "08:00:27:81:ba:ca"

network.linkinventory = inventory
network.upinterface = bring_up
network.configdhcp = lambda iface: events.append(("dhcp", iface))
network.time.sleep = lambda _seconds: None
network.os.path.exists = lambda _path: False
network.main()

expected = [("up", "eth0"), ("dhcp", "eth0")]
if events != expected:
    raise SystemExit(
        f"wired initialization regression: expected {expected!r}, got {events!r}"
    )

# The wired selector must never mistake an associated Wi-Fi interface for
# Ethernet, even if the Wi-Fi driver reports carrier and operstate UP.
network.linkinventory = lambda: [{
    "name": "wlan0",
    "index": 3,
    "carrier": True,
    "operstate": "UP",
    "up": True,
    "wireless": True,
    "mac": "e4:c7:67:9a:2e:9b",
}]
if network.detectinterface() is not None:
    raise SystemExit("wireless interface was accepted by the wired-only selector")

# With no carrier-ready Ethernet, configured Wi-Fi association starts
# immediately instead of waiting through the Ethernet settling interval.
events.clear()
wireless = {
    "name": "wlan0",
    "index": 3,
    "carrier": False,
    "operstate": "DOWN",
    "up": True,
    "wireless": True,
    "mac": "e4:c7:67:9a:2e:9b",
}
network.linkinventory = lambda: [wireless]
network.activatewirelessinterfaces = lambda _links: []
network.configuredwirelesslinks = lambda _links: [wireless]

def associate(iface):
    events.append(("associate", iface))
    wireless["carrier"] = True
    wireless["operstate"] = "UP"
    return True

network.ensurewireless = associate
network.waitforwirelessready = lambda iface: events.append(("late-wait", iface)) or True
network.detectinterface = lambda allowwireless=False: None
network.main()
expected = [
    ("associate", "wlan0"),
    ("dhcp", "wlan0"),
]
if events != expected:
    raise SystemExit(
        f"Wi-Fi fallback regression: expected {expected!r}, got {events!r}"
    )

# A Settings reconfiguration request must reapply an already-connected Wi-Fi
# interface instead of publishing a false disconnected state.
events.clear()
network.loadjson = lambda _path, _default=None: {
    "connected": True,
    "interface": "wlan0",
}
network.main(force=True)
expected = [
    ("associate", "wlan0"),
    ("dhcp", "wlan0"),
]
if events != expected:
    raise SystemExit(
        f"Wi-Fi reconfiguration regression: expected {expected!r}, got {events!r}"
    )
network.loadjson = lambda _path, default=None: {} if default is None else default

# If both links are ready, Ethernet must pre-empt Wi-Fi.
events.clear()
ethernet_ready = {
    "name": "eth0",
    "index": 2,
    "carrier": True,
    "operstate": "UP",
    "up": True,
    "wireless": False,
    "mac": "d8:43:ae:53:56:ca",
}
wireless_ready = dict(wireless, carrier=True, operstate="UP")
network.linkinventory = lambda: [wireless_ready, ethernet_ready]
network.main()
if events != [("dhcp", "eth0")]:
    raise SystemExit(
        f"Ethernet priority regression: expected DHCP on eth0, got {events!r}"
    )

# Ethernet carrier may disappear briefly when the interface is brought up.
# Verify that main keeps retrying the wired NIC and eventually runs DHCP on it.
events.clear()
inventory_calls = 0

def settling_inventory():
    global inventory_calls
    inventory_calls += 1
    carrier = inventory_calls >= 5
    return [{
        "name": "eth0",
        "index": 2,
        "carrier": carrier,
        "operstate": "UP" if carrier else "DOWN",
        "up": inventory_calls > 1,
        "wireless": False,
        "mac": "d8:43:ae:53:56:ca",
    }]

network.linkinventory = settling_inventory
network.upinterface = lambda iface: events.append(("up", iface)) or "d8:43:ae:53:56:ca"
network.configdhcp = lambda iface: events.append(("dhcp", iface))
network.configuredwirelesslinks = lambda _links: []
network.detectinterface = lambda allowwireless=False: next(
    (
        link["name"] for link in settling_inventory()
        if not link["wireless"] and network.linkready(link)
    ),
    None,
)
network.main()

expected = [("up", "eth0"), ("dhcp", "eth0")]
if events != expected or inventory_calls < 5:
    raise SystemExit(
        f"wired carrier settle regression: expected {expected!r}, "
        f"got {events!r} after {inventory_calls} inventories"
    )
'@
$networkInitializationCheck | wsl.exe -d Ubuntu --exec python3 -B - $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'T1OS wired network initialization validation failed.'
}

$buildSoftwareRoot = Join-Path $projectRoot 'source\build software'
$wslDriverServer = (
    & wsl.exe -d Ubuntu --exec wslpath -a $driverServer |
        Select-Object -First 1
).Trim()
$wslBuildSoftwareRoot = (
    & wsl.exe -d Ubuntu --exec wslpath -a $buildSoftwareRoot |
        Select-Object -First 1
).Trim()
$driverDiagnosticOutput = & wsl.exe -d Ubuntu --exec env "PYTHONPATH=$wslBuildSoftwareRoot" python3 $wslDriverServer --diagnostic
$driverDiagnosticExitCode = $LASTEXITCODE
if ($driverDiagnosticExitCode -ne 0) {
    throw "T1OS Driver Server diagnostic failed (exit code $driverDiagnosticExitCode)."
}
$driverDiagnosticJson = $driverDiagnosticOutput |
    Where-Object { $_ -match '^\s*\{.*\}\s*$' } |
    Select-Object -Last 1
if (-not $driverDiagnosticJson) {
    throw 'T1OS Driver Server diagnostic did not emit its JSON result.'
}
try {
    $driverDiagnosticResult = $driverDiagnosticJson | ConvertFrom-Json
}
catch {
    throw "T1OS Driver Server diagnostic emitted invalid JSON: $driverDiagnosticJson"
}
if ($driverDiagnosticResult.passed -ne $true) {
    throw 'T1OS Driver Server diagnostic did not report passed=true.'
}
foreach ($check in @(
    'nvidia_uvm_device_registration',
    'nvidia_uvm_module_load_order',
    'nvidia_uvm_primary_node'
)) {
    if ($driverDiagnosticResult.checks.$check -ne $true) {
        throw "T1OS Driver Server diagnostic did not pass its UVM check: $check"
    }
}

Write-Host 'Hardware network and driver diagnostics validation passed.'
