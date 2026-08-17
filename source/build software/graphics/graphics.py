

"""
graphics.py

manages graphical output for The One OS.
"""



# imports
import os
import re
import sys
import errno
import json
import time
import math
import hashlib
import select
import stat
import zlib
from collections import OrderedDict

sys.path.insert(0, '/the one/build')

import mmap
import fcntl
import struct
import ctypes
import freetype
from freetype import FT_LOAD_DEFAULT

# UI outlines benefit from FreeType's light target: it keeps vertical grid
# fitting for crisp baselines while avoiding the harsh horizontal snapping of
# the default target.  Keep a fallback for older freetype-py builds.
FT_LOAD_T1OS_TEXT = getattr(freetype, "FT_LOAD_TARGET_LIGHT", FT_LOAD_DEFAULT)
from reign.reign import currentdatetime, timestamp
from GODDESS.GODDESS import formatlog


class PackedAdvances:

    """Compact cumulative text advances with copy-on-write 4K blocks."""

    itemsize = 4
    blocksize = 4096
    __slots__ = ('blocks', 'length', 'shared')

    def __init__(self):

        self.blocks = []
        self.length = 0
        self.shared = False

    def __len__(self):

        return int(self.length)

    def __bool__(self):

        return self.length > 0

    def __getitem__(self, index):

        if isinstance(index, slice):

            start, stop, step = index.indices(self.length)

            if step == 1 and start == 0:
                result = PackedAdvances()
                result.blocks = list(self.blocks[:((stop + self.blocksize - 1) // self.blocksize)])
                result.length = stop
                result.shared = True
                self.shared = True
                return result

            result = PackedAdvances()

            for position in range(start, stop, step):
                result.append(self[position])

            return result

        position = int(index)

        if position < 0:
            position += self.length

        if position < 0 or position >= self.length:
            raise IndexError(position)

        block, offset = divmod(position, self.blocksize)
        return int(self.blocks[block][offset])

    def append(self, value):

        blockoffset = self.length % self.blocksize

        if self.shared:
            self.blocks = list(self.blocks)

            if blockoffset and self.blocks:
                blocktype = ctypes.c_uint32 * self.blocksize
                clone = blocktype()
                ctypes.memmove(clone, self.blocks[-1], ctypes.sizeof(blocktype))
                self.blocks[-1] = clone

            self.shared = False

        if blockoffset == 0:
            self.blocks.append((ctypes.c_uint32 * self.blocksize)())

        self.blocks[-1][blockoffset] = max(0, min(0xffffffff, int(value)))
        self.length += 1
from ctypes import Structure, c_uint32, c_uint16, c_char



# globals
LOGFILE = '/the one/logs/graphics.py.log'
FB_DEVICE = '/the one/drivers/nodes/fb0'
DISPLAYSETTINGS = '/the one/settings/display/settings.json'
MOUSESETTINGS = '/the one/settings/mouse/settings.json'
VBOXDRMCLIENT = '/the one/software/virtualbox/VBoxDRMClient'
VBOXGUESTNODE = '/the one/drivers/nodes/vboxguest'
_DEBUG_GRAPHICS = False
FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
FBIOPAN_DISPLAY = 0x4606
FBIOBLANK = 0x4611
FB_ACTIVATE_NOW = 0
FB_BLANK_UNBLANK = 0
FB_BLANK_POWERDOWN = 4
DRM_IOCTL_MODE_CREATE_DUMB = 0xC02064B2
DRM_IOCTL_MODE_MAP_DUMB = 0xC01064B3
DRM_IOCTL_MODE_DESTROY_DUMB = 0xC00464B4
FB_FIX_SCREENINFO_SIZE = 80 if ctypes.sizeof(ctypes.c_ulong) == 8 else 64
FRAMEBUFFERMAXBYTES = 512 * 1024 * 1024
_pan_idx = 0
_page_pitch = 0
_has_double = False
_first_present = True
_framebufferpagezero = False
_framebuffernativedrm = False
_framebufferwritesequence = 0
_framebufferpansequence = 0
MS_SYNC = 0x0004
_IS_FILE_BUFFER = False
_FILE_FD = None
_FILE_MAP = None
FILEBUFFERFLUSH = str(os.environ.get("T1OS_GRAPHICS_MMAP_FLUSH", "")).strip().lower() in ("1", "true", "yes", "on")

STANDARDCONTROLBACKGROUND = 0x000000
STANDARDCONTROLTEXT = 0xEFEFEF
STANDARDCONTROLBORDER = 0x3C3C3C


def uiscalefactor(default=1.0):

    try:
        with open(DISPLAYSETTINGS, 'r', encoding='utf-8') as stream:
            settings = json.load(stream)
        value = float(settings.get('ui_scale', default))
    except Exception:
        value = float(default)

    return max(0.5, min(3.0, value))


def displayuiscale(width, height, preference=None, basewidth=1920, baseheight=1080):

    """Return one uniform UI scale for the complete display.

    The smaller axis ratio fits the logical desktop into any aspect ratio
    without stretching it.  ``preference`` remains the user's multiplier on
    top of automatic high-DPI scaling.
    """

    try:
        preference = uiscalefactor() if preference is None else float(preference)
        preference = max(0.5, min(3.0, preference))
        width = float(width)
        height = float(height)
        basewidth = float(basewidth)
        baseheight = float(baseheight)

        if width <= 0.0 or height <= 0.0 or basewidth <= 0.0 or baseheight <= 0.0:
            return preference

        automatic = min(width / basewidth, height / baseheight)
        return max(0.5, min(3.0, automatic * preference))

    except Exception:
        return 1.0


def dropdownstyle():

    return {
        'background': STANDARDCONTROLBACKGROUND,
        'text': STANDARDCONTROLTEXT,
        'border': STANDARDCONTROLBORDER,
    }


def dropdownpopuprect(control, optioncount, windowheight, rowheight=34, maximumvisible=8):

    x, y, width, height = [int(value) for value in control]
    count = max(0, int(optioncount))
    visible = min(count, max(1, int(maximumvisible)))
    rowheight = max(1, int(rowheight))
    menuheight = visible * rowheight + 2
    below = max(0, int(windowheight) - (y + height))
    above = max(0, y)

    if menuheight <= below:
        top = y + height
    elif menuheight <= above:
        top = max(0, y - menuheight)
    else:
        space = max(below, above)
        visible = min(visible, max(1, (space - 2) // rowheight))
        menuheight = visible * rowheight + 2
        top = y + height if below >= above else max(0, y - menuheight)

    return [x, top, width, menuheight], visible


def dropdownindexat(x, y, popup, optioncount, offset=0, rowheight=34):

    left, top, width, height = [int(value) for value in popup]
    x, y = int(x), int(y)
    if not (left < x < left + width and top < y < top + height):
        return None
    local = (y - top - 1) // max(1, int(rowheight))
    index = max(0, int(offset)) + int(local)
    return index if 0 <= index < int(optioncount) else None


def drawdropdowncontrol(x, y, width, height, text, fontpath, fontsize=15, opened=False):

    style = dropdownstyle()
    x, y, width, height = int(x), int(y), int(width), int(height)
    fillrectfast(x, y, width, height, style['background'])
    drawrect(x, y, width, height, style['border'])
    texty = y + max(1, (height - int(fontsize)) // 2)
    drawtextttf(x + max(4, height // 4), texty, str(text), style['text'], int(fontsize), fontpath=fontpath)
    centrex = x + width - max(8, height // 2)
    centrey = y + height // 2
    arrow = max(3, height // 9)
    if opened:
        drawline(centrex - arrow, centrey + arrow // 2, centrex, centrey - arrow // 2, style['text'])
        drawline(centrex, centrey - arrow // 2, centrex + arrow, centrey + arrow // 2, style['text'])
    else:
        drawline(centrex - arrow, centrey - arrow // 2, centrex, centrey + arrow // 2, style['text'])
        drawline(centrex, centrey + arrow // 2, centrex + arrow, centrey - arrow // 2, style['text'])


def drawdropdownmenu(rect, labels, fontpath, fontsize=15, rowheight=34, selected=None, hovered=None):

    style = dropdownstyle()
    x, y, width, height = [int(value) for value in rect]
    fillrectfast(x, y, width, height, style['background'])
    drawrect(x, y, width, height, style['border'])

    count = len(labels)
    contentheight = max(1, height - 2)
    for index, label in enumerate(labels):
        # Divide the physical popup height between the logical rows.  This
        # avoids losing the last item when fractional UI scaling rounds each
        # row up independently.
        rowy = y + 1 + int(round(index * contentheight / max(1, count)))
        rowbottom = y + 1 + int(round((index + 1) * contentheight / max(1, count)))
        actualheight = max(1, rowbottom - rowy)
        if index == hovered:
            drawrect(x + 2, rowy + 1, max(1, width - 4), max(1, actualheight - 2), style['border'])
        if index == selected:
            fillrectfast(x + 3, rowy + 4, 2, max(1, actualheight - 8), style['text'])
        texty = rowy + max(1, (actualheight - int(fontsize)) // 2)
        drawtextttf(x + max(8, actualheight // 3), texty, str(label), style['text'], int(fontsize), fontpath=fontpath)

# text
FONT8x8 = {}
TTFFACES = {}
TTFGLYPHS = {}
TTFGLYPHSCAP = 8192
TTFADVANCES = {}
TTFADVANCESCAP = 8192
TEXTTABWIDTH = 4
TEXTGAMMA = 1.8
TEXTLIGHTCOVERAGE = tuple(
    int(round(((value / 255.0) ** (1.0 / TEXTGAMMA)) * 255.0))
    for value in range(256)
)
TEXTDARKCOVERAGE = tuple(
    int(round((1.0 - ((1.0 - (value / 255.0)) ** (1.0 / TEXTGAMMA))) * 255.0))
    for value in range(256)
)
MSGCOLOUR = 0xEFEFEF
ERRORCOLOUR = 0xFF0000
_ttfface = None
_ttffacepath = None
ADV_ROW = -1
ADV_TEXT = None
ADV_FONT = None
ADV_SIZE = None
ADV_LIST = None
ADVCACHE = OrderedDict()
ADVCACHECAP = 512
ADVCACHEBYTES = 0
ADVCACHESIZES = {}
ADVCACHEBYTELIMIT = 32 * 1024 * 1024
ADVRECENT = OrderedDict()
ADVRECENTBYTES = 0
ADVRECENTLIMIT = 32 * 1024 * 1024
TTFOPAQUECACHE = OrderedDict()
TTFOPAQUECACHEBYTES = 0
TTFOPAQUECACHELIMIT = 64 * 1024 * 1024

# cursor
CURSORS = {}
CURSORBASE = "/the one/resources/graphics/mouse cursors"
IMAGECATALOGUE = "/the one/catalogue/image"
CURSORTIERS = [
    (1080, "1080"),
    (1440, "1440"),
    (1800, "1800"),
    (2160, "4k"),
    (2880, "4kplus"),
]
CURSORBUCKETS = {
    "1080": {
        "arrow": (14, 23),
        "link": (23, 23),
        "text": (23, 23),
        "busy": (23, 23),
        "resize_h": (24, 13),
        "resize_v": (13, 21),
        "resize_diag1": (17, 17),
        "resize_diag2": (17, 17),
    },
    "1440": {
        "arrow": (16, 26),
        "link": (26, 26),
        "text": (26, 26),
        "busy": (26, 26),
        "resize_h": (26, 14),
        "resize_v": (14, 26),
        "resize_diag1": (19, 19),
        "resize_diag2": (19, 19),
    },
    "1800": {
        "arrow": (18, 29),
        "link": (29, 29),
        "text": (29, 29),
        "busy": (29, 29),
        "resize_h": (28, 15),
        "resize_v": (15, 28),
        "resize_diag1": (21, 21),
        "resize_diag2": (21, 21),
    },
    "4k": {
        "arrow": (19, 31),
        "link": (31, 31),
        "text": (31, 31),
        "busy": (31, 31),
        "resize_h": (32, 17),
        "resize_v": (17, 32),
        "resize_diag1": (23, 23),
        "resize_diag2": (23, 23),
    },
    "4kplus": {
        "arrow": (21, 34),
        "link": (34, 34),
        "text": (34, 34),
        "busy": (34, 34),
        "resize_h": (35, 19),
        "resize_v": (19, 35),
        "resize_diag1": (25, 25),
        "resize_diag2": (25, 25),
    },
}
CURSORSIZEMIN = 16
CURSORSIZEMAX = 48
TEXTCURSORSCALE = 1.5
CURSORTIER = "1080"
CURSORW = 0
CURSORH = 0
PILIMAGE = None

try:

    libc = ctypes.CDLL(None)
    _msync = libc.msync
    _msync.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    _msync.restype = ctypes.c_int

except Exception:

    _msync = None


class fb_bitfield(Structure):
    _fields_ = [("offset", c_uint32), ("length", c_uint32), ("msb_right", c_uint32)]


class fb_var_screeninfo(Structure):
    _fields_ = [
        ("xres", c_uint32), ("yres", c_uint32),
        ("xres_virtual", c_uint32), ("yres_virtual", c_uint32),
        ("xoffset", c_uint32), ("yoffset", c_uint32),
        ("bits_per_pixel", c_uint32), ("grayscale", c_uint32),
        ("red", fb_bitfield), ("green", fb_bitfield), ("blue", fb_bitfield), ("transp", fb_bitfield),
        ("nonstd", c_uint32), ("activate", c_uint32),
        ("height", c_uint32), ("width", c_uint32),
        ("accel_flags", c_uint32),
        ("pixclock", c_uint32), ("left_margin", c_uint32), ("right_margin", c_uint32),
        ("upper_margin", c_uint32), ("lower_margin", c_uint32),
        ("hsync_len", c_uint32), ("vsync_len", c_uint32),
        ("sync", c_uint32), ("vmode", c_uint32),
        ("rotate", c_uint32), ("colorspace", c_uint32),
        ("reserved0", c_uint32), ("reserved1", c_uint32),
        ("reserved2", c_uint32), ("reserved3", c_uint32),
    ]


class drmModeModeInfo(Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),
        ("hdisplay", ctypes.c_uint16), ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16), ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16), ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16), ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
    ]


class drmModeRes(Structure):
    _fields_ = [
        ("count_fbs", ctypes.c_int), ("fbs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_crtcs", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
        ("count_connectors", ctypes.c_int), ("connectors", ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(ctypes.c_uint32)),
        ("min_width", ctypes.c_uint32), ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32), ("max_height", ctypes.c_uint32),
    ]


class drmModeConnector(Structure):
    _fields_ = [
        ("connector_id", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_int),
        ("mmWidth", ctypes.c_uint32),
        ("mmHeight", ctypes.c_uint32),
        ("subpixel", ctypes.c_int),
        ("count_modes", ctypes.c_int),
        ("modes", ctypes.POINTER(drmModeModeInfo)),
        ("count_props", ctypes.c_int),
        ("props", ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int),
        ("encoders", ctypes.POINTER(ctypes.c_uint32)),
    ]


class drmModeEncoder(Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


class drmModeCrtc(Structure):
    _fields_ = [
        ("crtc_id", ctypes.c_uint32),
        ("buffer_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("mode_valid", ctypes.c_int),
        ("mode", drmModeModeInfo),
        ("gamma_size", ctypes.c_int),
    ]


class drmModeClip(Structure):
    _fields_ = [
        ("x1", ctypes.c_uint16),
        ("y1", ctypes.c_uint16),
        ("x2", ctypes.c_uint16),
        ("y2", ctypes.c_uint16),
    ]


class drmModePropertyRes(Structure):
    _fields_ = [
        ("prop_id", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
        ("count_values", ctypes.c_int),
        ("values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_enums", ctypes.c_int),
        ("enums", ctypes.c_void_p),
        ("count_blobs", ctypes.c_int),
        ("blob_ids", ctypes.POINTER(ctypes.c_uint32)),
    ]


class drmVersion(Structure):
    _fields_ = [
        ("version_major", ctypes.c_int),
        ("version_minor", ctypes.c_int),
        ("version_patchlevel", ctypes.c_int),
        ("name_len", ctypes.c_int),
        ("name", ctypes.c_void_p),
        ("date_len", ctypes.c_int),
        ("date", ctypes.c_void_p),
        ("desc_len", ctypes.c_int),
        ("desc", ctypes.c_void_p),
    ]


class drmEventContext(Structure):
    _fields_ = [
        ("version", ctypes.c_int),
        ("vblank_handler", ctypes.c_void_p),
        ("page_flip_handler", ctypes.c_void_p),
        ("page_flip_handler2", ctypes.c_void_p),
        ("sequence_handler", ctypes.c_void_p),
    ]


class gbm_bo_handle(ctypes.Union):
    _fields_ = [
        ("ptr", ctypes.c_void_p),
        ("s32", ctypes.c_int32),
        ("u32", ctypes.c_uint32),
        ("s64", ctypes.c_int64),
        ("u64", ctypes.c_uint64),
    ]


# module state
_fd = None
_map = None
_buffer = None
_scaled_file_frame_cache = None
_scaled_file_frame_metrics = None
_scaled_file_last_metrics = {
    "calls": 0,
    "regions": 0,
    "source_reads": 0,
    "cache_hits": 0,
}
_xres = 0
_yres = 0
_yvirt = 0
_bpp = 0
_bpp_bytes = 0
_pack = None
_packint = None
_unpack = None
_line = 0
_size = 0
_roff = _rlen = 0
_goff = _glen = 0
_boff = _blen = 0
_aoff = _alen = 0
_dirtyX0 = None
_dirtyY0 = None
_dirtyX1 = None
_dirtyY1 = None

# OpenGL
GRAPHICSCATALOGUE = "/the one/catalogue/graphics"
GBMBACKENDPATH = "/the one/catalogue/graphics/gbm"
NVIDIAGRAPHICSCATALOGUE = os.path.join(GRAPHICSCATALOGUE, "nvidia")
NVIDIAPATHPROVIDERSOURCE = os.path.join(
    NVIDIAGRAPHICSCATALOGUE,
    "t1os-nvidia-path-provider.so",
)
NVIDIAPATHPROVIDER = "/.ephemeral/graphics/nvidia-path-provider.so"
NVIDIAEGLVENDORPATH = os.path.join(
    NVIDIAGRAPHICSCATALOGUE,
    "egl_vendor.d",
    "10_nvidia.json",
)
NVIDIAGBMPATH = os.path.join(NVIDIAGRAPHICSCATALOGUE, "gbm")
NVIDIAEGLEXTERNALPATH = os.path.join(
    NVIDIAGBMPATH,
    "15_nvidia_gbm.json",
)
DRMNODEPATH = "/the one/drivers/nodes/dri"
DRMSTATEPATH = "/the one/drivers/state/class/drm"
FRAMEBUFFERSTATEPATH = "/the one/drivers/state/class/graphics/fb0"
DRMDEVICE = os.environ.get("T1OS_DRM_DEVICE", "").strip()
FIRMWAREFRAMEBUFFERBOOT = str(
    os.environ.get("T1OS_FIRMWARE_FRAMEBUFFER_BOOT", "")
).strip().lower() in ("1", "true", "yes", "on")
FRAMEBUFFERCONSOLEOWNED = str(
    os.environ.get("T1OS_FRAMEBUFFER_CONSOLE_OWNED", "")
).strip().lower() in ("1", "true", "yes", "on")
EARLYFRAMEBUFFERGRAPHICSOWNED = str(
    os.environ.get("T1OS_EARLY_FRAMEBUFFER_GRAPHICS_OWNED", "")
).strip().lower() in ("1", "true", "yes", "on")
_backend = "none"
_egl = None
_gles = None
_gbm = None
_drm = None
_openglprovider = None
_opengldependencies = []
_egldisplay = None
_eglconfig = None
_eglsurface = None
_eglcontext = None
_eglmajor = 0
_eglminor = 0
_eglvendor = None
_eglextensions = frozenset()
_eglextensionsqueried = False
_glextensions = None
_eglswapinterval = None
_eglminswapinterval = None
_eglmaxswapinterval = None
_egldeferredswapstate = "inactive"
_egldeferredswaperror = None
_drmfd = None
_drmdriver = None
_drmdriverversion = None
_drmdriverdate = None
_drmdriverdescription = None
_drmbinding = None
_drmconnector = 0
_drmcrtc = 0
_drmmode = None
_drmoriginal = None
_drmflip = False
_drmeventdriven = False
_drmpendingbo = None
_drmpendingsurface = None
_drmpendingfb = 0
_drmpendingstarted = 0
_drmlastflipsequence = None
_drmlastfliptimestampus = None
_drmdumbhandle = 0
_drmdumbfb = 0
_drmdumbsize = 0
_drmdumbpresentsequence = 0
_drmdumbmodesetsequence = 0
_drmdumbflushstatus = "not-attempted"
_drmdumbdirtystatus = "not-attempted"
_drmdumblastpresenterror = None
_gbmdevice = None
_gbmsurface = None
_gbmbo = None
_gbmbosurface = None
_gbmfb = 0
_kmsresizes = 0
_kmsresizefailures = 0
_glprogram = 0
_gltexture = 0
_glrenderer = None
_glversion = None
_gluploadbytes = 0
_gluploadfull = False
_eglcreateimage = None
_egldestroyimage = None
_glimage_target_texture = None
_eglquerydmabufformats = None
_eglquerydmabufmodifiers = None
_glgetgraphicsresetstatus = None
_glrobust = False
_gpuhealthlast = 0.0
GPUHEALTHINTERVAL = 0.5

# managed GPU compositor
GPUAPIVERSION = 4
GPUMAXTEXTURES = 512
GPUMAXTEXTUREBYTES = 512 * 1024 * 1024
GPUVIDEOMAXOBJECTS = 4
GPUAATARGETCAP = 8
GPUAAMAXDIMENSION = 4096
GPUAASCALE = 2
GPUTEXTCACHECAP = 256
GPUIMAGECACHECAP = 128
GPUGLYPHATLASCAP = 32
GPUGLYPHATLASSIZE = 1024
GPUBATCHQUADLIMIT = 2048
GPUFRAMEHISTORYCAP = 240
# A 3840x2160 BGRA frame is just under 32 MiB. Keeping one complete 4K
# snapshot in staging avoids dividing a browser frame into independently-read
# bands, which can combine two Xvfb frames and show a horizontal tear.
GPUUPLOADSTAGINGLIMIT = 32 * 1024 * 1024
KMSMODEWIDTH = 2560
KMSMODEHEIGHT = 1440
KMSMODEEXPLICIT = False
KMSMINWIDTH = 320
KMSMINHEIGHT = 200
KMSMAXWIDTH = 8192
KMSMAXHEIGHT = 8192
KMSMAXBUFFERBYTES = 512 * 1024 * 1024
DISPLAYBRIGHTNESS = 100
DISPLAYCONTRAST = 100
DISPLAYSATURATION = 100
DISPLAYEFFECTIVESATURATION = 100
DISPLAYTEMPERATURE = 6500
DISPLAYCHANNELS = (1.0, 1.0, 1.0)
DISPLAYNIGHTLIGHT = {
    'night_light_enabled': False,
    'night_light_mode': 'automatic',
    'night_light_manual_temperature': 3400,
    'night_light_day_temperature': 6500,
    'night_light_sunset_temperature': 4500,
    'night_light_bedtime_temperature': 3400,
    'night_light_day_time': '06:00',
    'night_light_evening_time': '18:00',
    'night_light_bedtime_time': '22:00',
    'night_light_transition_minutes': 10,
    'night_light_preview': False,
}
_displaypreviewstarted = 0.0
_displayoutputlut = bytes(range(256))
_displaychannelluts = (bytes(range(256)), bytes(range(256)), bytes(range(256)))
_displaysaturationlut = None
_gpuprogram = 0
_gpuvideoprogram = 0
_gpuvideoplanarprogram = 0
_gpuvideoimportcapabilitiescache = None
_gpublurprogram = 0
_gpueffectprogram = 0
_gpulineprogram = 0
_gpu3dprogram = 0
_gpu3dlineprogram = 0
_gpuuniforms = {}
_gpuuniformvalues = {}
_gpubuffer = 0
_gpubufferbytes = 0
_gputextures = {}
_gpuvideosurfaces = {}
_gputexturebytes = 0
_gpuhandle = 1
_gpuframeactive = False
_gpuframestart = 0
_gpuframerenderms = 0.0
_gpuframedraws = 0
_gpuframeuploads = 0
_gpuframeuploadbytes = 0
_gpuframeregions = []
_gpuframedamagepixels = 0
_gpuframefull = True
_gpuframepersistent = False
_gpuframesyncpersistent = False
_gpuframeclip = None
_gpuimagecache = {}
_gputextcache = {}
_gpuglyphatlases = {}
_gpucursorcache = {}
_gpublurcache = {}
_gpuuploadstaging = bytearray()
_gpuframehistory = []
_gpupresentationhistory = []
_gpuframeprofiles = []
_gpuframebudgetms = 16.667
_gpucompositorfbo = 0
_gpucompositorhandle = 0
_gpucompositorwidth = 0
_gpucompositorheight = 0
_gpucompositorvalid = False
_gputargets = {}
_gputargetdepths = {}
_gpu3daatargets = {}
_gputargetactive = False
_gpurenderwidth = 0
_gpurenderheight = 0
_gputelemetry = {
    "frames": 0,
    "failed_frames": 0,
    "frame_ms": 0.0,
    "render_ms": 0.0,
    "average_render_ms": 0.0,
    "maximum_render_ms": 0.0,
    "average_frame_ms": 0.0,
    "maximum_frame_ms": 0.0,
    "missed_frame_budget": 0,
    "draw_calls": 0,
    "batch_draws": 0,
    "batched_quads": 0,
    "maximum_batch_quads": 0,
    "rectangle_batch_draws": 0,
    "rectangle_batched_quads": 0,
    "rounded_batch_draws": 0,
    "rounded_batched_quads": 0,
    "circle_batch_draws": 0,
    "circle_batched_quads": 0,
    "line_batch_draws": 0,
    "line_batched_quads": 0,
    "gradient_batch_draws": 0,
    "gradient_batched_quads": 0,
    "vertex_upload_bytes": 0,
    "uploads": 0,
    "upload_bytes": 0,
    "upload_calls": 0,
    "upload_staging_bytes": 0,
    "maximum_upload_staging_bytes": 0,
    "full_uploads": 0,
    "partial_uploads": 0,
    "maximum_texture_count": 0,
    "maximum_texture_bytes": 0,
    "video_surface_imports": 0,
    "video_surface_composed_imports": 0,
    "video_surface_planar_imports": 0,
    "video_surface_gpu_scaled_imports": 0,
    "video_surface_modifier_imports": 0,
    "video_surface_releases": 0,
    "presentation_dmabuf_imports": 0,
    "presentation_dmabuf_releases": 0,
    "presentation_consumer_glfinish": 0,
    "video_surface_draws": 0,
    "video_surface_draw_failures": 0,
    "video_surface_last_draw_failure": "",
    "video_surface_import_failures": 0,
    "video_surface_last_import_failure": "",
    "maximum_depth_buffer_count": 0,
    "maximum_depth_buffer_bytes": 0,
    "page_flips": 0,
    "page_flip_submissions": 0,
    "page_flip_waits": 0,
    "page_flip_timeouts": 0,
    "page_flip_recoveries": 0,
    "page_flip_ms": 0.0,
    "average_page_flip_ms": 0.0,
    "maximum_page_flip_ms": 0.0,
    "page_flip_sequence": 0,
    "page_flip_timestamp_us": 0,
    "page_flip_sequence_delta": 0,
    "page_flip_interval_ms": 0.0,
    "page_flip_timestamp_clock": "kernel-drm-event-unspecified",
    "page_flip_timeout_age_ms": 0.0,
    "maximum_page_flip_timeout_age_ms": 0.0,
    "blocking_page_flip_wait_ms": 0.0,
    "maximum_blocking_page_flip_wait_ms": 0.0,
    "prior_flip_wait_samples": 0,
    "prior_flip_wait_ms": 0.0,
    "average_prior_flip_wait_ms": 0.0,
    "maximum_prior_flip_wait_ms": 0.0,
    "egl_swap_samples": 0,
    "egl_swap_ms": 0.0,
    "average_egl_swap_ms": 0.0,
    "maximum_egl_swap_ms": 0.0,
    "gbm_lock_samples": 0,
    "gbm_lock_ms": 0.0,
    "average_gbm_lock_ms": 0.0,
    "maximum_gbm_lock_ms": 0.0,
    "drm_framebuffer_samples": 0,
    "drm_framebuffer_ms": 0.0,
    "average_drm_framebuffer_ms": 0.0,
    "maximum_drm_framebuffer_ms": 0.0,
    "page_flip_submit_samples": 0,
    "page_flip_submit_ms": 0.0,
    "average_page_flip_submit_ms": 0.0,
    "maximum_page_flip_submit_ms": 0.0,
    "gpu_health_samples": 0,
    "gpu_health_sample_interval": GPUHEALTHINTERVAL,
    "fallbacks": 0,
    "full_frames": 0,
    "partial_frames": 0,
    "persistent_frames": 0,
    "persistent_sync_frames": 0,
    "persistent_fallbacks": 0,
    "damage_regions": 0,
    "damage_pixels": 0,
    "scissored_pixels": 0,
    "glyph_atlases": 0,
    "glyphs": 0,
    "glyph_uploads": 0,
    "glyph_upload_bytes": 0,
    "glyph_prewarm_runs": 0,
    "glyph_prewarm_requests": 0,
    "glyph_prewarmed": 0,
    "glyph_prewarm_ms": 0.0,
    "text_cache_hits": 0,
    "text_cache_misses": 0,
    "blur_copies": 0,
    "blur_pixels": 0,
    "mesh_3d_draws": 0,
    "mesh_3d_triangles": 0,
    "mesh_3d_vertices": 0,
    "mesh_3d_depth_clears": 0,
    "aa_2d_line_draws": 0,
    "aa_2d_line_segments": 0,
    "aa_3d_wire_draws": 0,
    "aa_3d_wire_segments": 0,
    "aa_analytic_scenes": 0,
    "aa_supersample_scenes": 0,
    "aa_supersample_pixels": 0,
    "aa_supersample_resolve_ms": 0.0,
    "aa_quality_fallbacks": 0,
    "maximum_aa_target_bytes": 0,
}

# EGL
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
EGL_PLATFORM_GBM_KHR = 0x31D7
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_WINDOW_BIT = 0x0004
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_ES2_BIT = 0x0004
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_CONTEXT_OPENGL_ROBUST_ACCESS_EXT = 0x30BF
EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_EXT = 0x3138
EGL_LOSE_CONTEXT_ON_RESET_EXT = 0x31BF
EGL_OPENGL_ES_API = 0x30A0
EGL_NATIVE_VISUAL_ID = 0x302E
EGL_MIN_SWAP_INTERVAL = 0x303B
EGL_MAX_SWAP_INTERVAL = 0x303C
EGL_CONTEXT_LOST = 0x300E
EGL_NONE = 0x3038
EGL_VENDOR = 0x3053
EGL_EXTENSIONS = 0x3055
EGL_NO_CONTEXT = None
EGL_LINUX_DMA_BUF_EXT = 0x3270
EGL_LINUX_DRM_FOURCC_EXT = 0x3271
EGL_DMA_BUF_PLANE0_FD_EXT = 0x3272
EGL_DMA_BUF_PLANE0_OFFSET_EXT = 0x3273
EGL_DMA_BUF_PLANE0_PITCH_EXT = 0x3274
EGL_YUV_COLOR_SPACE_HINT_EXT = 0x327B
EGL_SAMPLE_RANGE_HINT_EXT = 0x327C
EGL_ITU_REC601_EXT = 0x327F
EGL_ITU_REC709_EXT = 0x3275
EGL_ITU_REC2020_EXT = 0x3280
EGL_YUV_FULL_RANGE_EXT = 0x3282
EGL_YUV_NARROW_RANGE_EXT = 0x3283
EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT = 0x3443
EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT = 0x3444
DRM_FORMAT_MOD_INVALID = 0x00FFFFFFFFFFFFFF
DRM_FORMAT_MOD_LINEAR = 0
DRM_FORMAT_XRGB8888 = 0x34325258
DRM_FORMAT_ARGB8888 = 0x34325241

# GLES
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_NO_ERROR = 0
GL_CONTEXT_LOST = 0x0507
GL_GUILTY_CONTEXT_RESET = 0x8253
GL_INNOCENT_CONTEXT_RESET = 0x8254
GL_UNKNOWN_CONTEXT_RESET = 0x8255
GL_FLOAT = 0x1406
GL_RGB = 0x1907
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_EXTENSIONS = 0x1F03
GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_TRIANGLE_STRIP = 0x0005
GL_TRIANGLES = 0x0004
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE_EXTERNAL_OES = 0x8D65
GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F
GL_UNPACK_ALIGNMENT = 0x0CF5
GL_PACK_ALIGNMENT = 0x0D05
GL_BLEND = 0x0BE2
GL_DEPTH_TEST = 0x0B71
GL_SCISSOR_TEST = 0x0C11
GL_ONE = 0x0001
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_FRAMEBUFFER = 0x8D40
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_DEPTH_ATTACHMENT = 0x8D00
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_RENDERBUFFER = 0x8D41
GL_DEPTH_COMPONENT16 = 0x81A5
GL_LEQUAL = 0x0203
GL_ARRAY_BUFFER = 0x8892
GL_DYNAMIC_DRAW = 0x88E8

# DRM and GBM
DRM_MODE_CONNECTED = 1
DRM_MODE_TYPE_PREFERRED = 1 << 3
DRM_MODE_PAGE_FLIP_EVENT = 0x01
GBM_FORMAT_XRGB8888 = 0x34325258
GBM_BO_USE_SCANOUT = 1 << 0
GBM_BO_USE_RENDERING = 1 << 2

# baseline
BASELINEPATH = "/.ephemeral/graphicsbaseline"
BASELINEFONT = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"



# OpenGL functions
def _graphicscataloguefile(path, description):

    root = os.path.realpath(NVIDIAGRAPHICSCATALOGUE)
    resolved = os.path.realpath(path)

    try:
        contained = os.path.commonpath((root, resolved)) == root
    except ValueError:
        contained = False

    if not contained:
        raise RuntimeError(
            f"NVIDIA {description} escapes its catalogue root path={path} "
            f"resolved={resolved}"
        )

    if not os.path.isfile(path):
        raise RuntimeError(f"NVIDIA {description} is missing path={path}")

    if not os.access(path, os.R_OK):
        raise RuntimeError(f"NVIDIA {description} is not readable path={path}")

    return path


def _graphicsnvidiajson(path, expectedlibrary, description):

    _graphicscataloguefile(path, description)

    try:
        with open(path, "r", encoding="utf-8") as stream:
            record = json.load(stream)
    except Exception as error:
        raise RuntimeError(
            f"NVIDIA {description} is invalid path={path} error={error}"
        ) from error

    library = str(
        record.get("ICD", {}).get("library_path", "")
        if isinstance(record, dict)
        else ""
    ).strip()

    if os.path.basename(library) != expectedlibrary:
        raise RuntimeError(
            f"NVIDIA {description} selects an unexpected library "
            f"path={path} library={library!r} expected={expectedlibrary!r}"
        )

    if os.path.isabs(library):
        _graphicscataloguefile(library, f"{description} library")
    elif library != expectedlibrary:
        raise RuntimeError(
            f"NVIDIA {description} contains an unsafe relative library "
            f"path={path} library={library!r}"
        )

    return record


def _graphicsnvidiaversioned(prefix, description):

    try:
        names = sorted(
            name
            for name in os.listdir(NVIDIAGRAPHICSCATALOGUE)
            if name.startswith(prefix)
        )
    except OSError as error:
        raise RuntimeError(
            f"NVIDIA runtime catalogue is unavailable "
            f"path={NVIDIAGRAPHICSCATALOGUE} error={error}"
        ) from error

    paths = OrderedDict()

    for name in names:

        path = os.path.join(NVIDIAGRAPHICSCATALOGUE, name)

        try:
            _graphicscataloguefile(path, description)
        except RuntimeError:
            continue

        paths.setdefault(os.path.realpath(path), path)

    if len(paths) != 1:
        raise RuntimeError(
            f"NVIDIA {description} must resolve to exactly one runtime "
            f"library prefix={prefix!r} matches={list(paths.values())}"
        )

    return next(iter(paths.values()))


def _graphicsnvidiaruntime():

    pathprovidersource = _graphicscataloguefile(
        NVIDIAPATHPROVIDERSOURCE,
        "T1OS NVIDIA device-path provider",
    )

    if (
        os.environ.get("T1OS_NVIDIA_PATH_PROVIDER_SOURCE", "").strip()
        != pathprovidersource
        or os.environ.get("T1OS_NVIDIA_PATH_PROVIDER", "").strip()
        != NVIDIAPATHPROVIDER
    ):
        raise RuntimeError(
            "NVIDIA device-path provider was not selected before process start"
        )

    def digest(path):
        state = hashlib.sha256()
        with open(path, "rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                state.update(block)
        return state.hexdigest()

    try:
        if (
            not os.path.isfile(NVIDIAPATHPROVIDER)
            or not os.access(NVIDIAPATHPROVIDER, os.R_OK)
            or digest(NVIDIAPATHPROVIDER) != digest(pathprovidersource)
        ):
            raise RuntimeError(
                "NVIDIA device-path provider does not match its catalogue source"
            )
    except OSError as error:
        raise RuntimeError(
            f"NVIDIA device-path provider could not be verified: {error}"
        ) from error

    try:
        with open(
            "/the one/drivers/processes/self/maps",
            "r",
            encoding="ascii",
            errors="replace",
        ) as stream:
            mappings = stream.read(4 * 1024 * 1024)
    except OSError as error:
        raise RuntimeError(
            f"NVIDIA device-path provider mappings are unavailable: {error}"
        ) from error

    if NVIDIAPATHPROVIDER not in mappings:
        raise RuntimeError(
            "NVIDIA device-path provider is not loaded in WindowServer"
        )

    runtime = {
        "path_provider": NVIDIAPATHPROVIDER,
        "path_provider_source": pathprovidersource,
        "egl": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libEGL.so.1"),
            "GLVND EGL client library",
        ),
        "gles": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libGLESv2.so.2"),
            "GLVND GLES client library",
        ),
        "dispatch": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libGLdispatch.so.0"),
            "GLVND dispatch library",
        ),
        "egl_vendor": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libEGL_nvidia.so.0"),
            "EGL vendor library",
        ),
        "gles_vendor": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libGLESv2_nvidia.so.2"),
            "GLES vendor library",
        ),
        "egl_gbm": _graphicscataloguefile(
            os.path.join(NVIDIAGRAPHICSCATALOGUE, "libnvidia-egl-gbm.so.1"),
            "EGL GBM external-platform library",
        ),
        "gbm_backend": _graphicscataloguefile(
            os.path.join(NVIDIAGBMPATH, "nvidia-drm_gbm.so"),
            "GBM allocation backend",
        ),
        "glsi": _graphicsnvidiaversioned(
            "libnvidia-glsi.so.",
            "GLSI implementation library",
        ),
        "gpucomp": _graphicsnvidiaversioned(
            "libnvidia-gpucomp.so.",
            "GPU compiler library",
        ),
        "eglcore": _graphicsnvidiaversioned(
            "libnvidia-eglcore.so.",
            "EGL core library",
        ),
    }

    _graphicsnvidiajson(
        NVIDIAEGLVENDORPATH,
        "libEGL_nvidia.so.0",
        "EGL vendor manifest",
    )
    _graphicsnvidiajson(
        NVIDIAEGLEXTERNALPATH,
        "libnvidia-egl-gbm.so.1",
        "EGL GBM external-platform manifest",
    )
    return runtime


def _graphicsconfigureprovider(provider):

    provider = str(provider or "mesa").strip().lower()

    if provider == "nvidia":
        runtime = _graphicsnvidiaruntime()
        os.environ["EGL_PLATFORM"] = "gbm"
        os.environ["GBM_BACKENDS_PATH"] = NVIDIAGBMPATH
        os.environ["__EGL_VENDOR_LIBRARY_FILENAMES"] = NVIDIAEGLVENDORPATH
        os.environ["__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS"] = NVIDIAGBMPATH
        os.environ.pop("GALLIUM_DRIVER", None)
        os.environ.pop("VK_DRIVER_FILES", None)
        log(
            f"> graphics OpenGL provider configured provider=nvidia "
            f"egl_vendor={NVIDIAEGLVENDORPATH} "
            f"egl_external={NVIDIAEGLEXTERNALPATH} "
            f"gbm_backends={NVIDIAGBMPATH}"
        )
        return runtime

    if provider != "mesa":
        raise RuntimeError(f"unsupported OpenGL provider {provider!r}")

    # Mesa is the T1OS default for Nouveau, AMD, Intel, and virtual DRM
    # drivers.  Remove NVIDIA's process-wide GLVND selectors so a previous
    # environment cannot redirect these absolute catalogue libraries.
    os.environ.pop("EGL_PLATFORM", None)
    os.environ.pop("__EGL_VENDOR_LIBRARY_FILENAMES", None)
    os.environ.pop("__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS", None)
    os.environ["GBM_BACKENDS_PATH"] = GBMBACKENDPATH
    return {
        "egl": os.path.join(GRAPHICSCATALOGUE, "libEGL.so.1"),
        "gles": os.path.join(GRAPHICSCATALOGUE, "libGLESv2.so.2"),
    }


def _graphicsdrmroots(device):

    card = str(device or "").strip()
    cardname = os.path.basename(card)
    roots = []

    if cardname:
        roots.append(os.path.join(DRMSTATEPATH, cardname, "device"))

    try:
        status = os.stat(card)
        identifier = f"{os.major(status.st_rdev)}:{os.minor(status.st_rdev)}"
        roots.append(os.path.join(
            "/the one/drivers/state/dev/char",
            identifier,
            "device",
        ))
    except Exception:
        pass

    result = []

    for root in roots:
        if root not in result:
            result.append(root)

    return result


def _graphicsdrmbinding(device):

    for root in _graphicsdrmroots(device):

        driverpath = os.path.join(root, "driver")

        try:
            if os.path.lexists(driverpath):
                target = os.path.realpath(driverpath).rstrip(os.sep)
                name = os.path.basename(target).strip().lower()

                if name:
                    return name
        except OSError:
            pass

        try:
            with open(
                os.path.join(root, "uevent"),
                "r",
                encoding="utf-8",
                errors="replace",
            ) as stream:
                for line in stream:
                    key, separator, value = line.partition("=")

                    if separator and key.strip().upper() == "DRIVER":
                        name = value.strip().lower()

                        if name:
                            return name
        except OSError:
            pass

    return None


def _graphicsdrmprovider(device, binding, reported):

    binding = str(binding or "").strip().lower()
    reported = str(reported or "").strip().lower()
    nvidianames = {"nvidia", "nvidia_drm", "nvidia-drm"}
    bindingnvidia = binding in nvidianames
    reportednvidia = reported in nvidianames

    if binding and reported and bindingnvidia != reportednvidia:
        raise RuntimeError(
            f"DRM provider identity mismatch device={device} "
            f"binding={binding} reported={reported}"
        )

    return "nvidia" if bindingnvidia or reportednvidia else "mesa"


def _graphicsnvidiapreload(runtime):

    # GLVND and the NVIDIA libraries use SONAME dependencies.  Loading the
    # exact, validated catalogue objects first makes those dependencies
    # resolve inside T1OS even though Python was started before a provider was
    # selected and therefore cannot rely on a late LD_LIBRARY_PATH change.
    order = (
        "dispatch",
        "glsi",
        "gpucomp",
        "eglcore",
        "gbm_backend",
        "egl_vendor",
        "gles_vendor",
        "egl_gbm",
    )
    loaded = []

    for name in order:

        path = runtime[name]

        try:
            loaded.append(ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL))
        except Exception as error:
            raise RuntimeError(
                f"NVIDIA runtime dependency load failed "
                f"component={name} path={path} error={error}"
            ) from error

    return loaded


def openglload(provider="mesa", runtime=None):

    global _egl, _gles, _eglcreateimage, _egldestroyimage, _glimage_target_texture
    global _eglquerydmabufformats, _eglquerydmabufmodifiers
    global _openglprovider, _opengldependencies

    provider = str(provider or "mesa").strip().lower()

    if (
        _egl is not None
        and _gles is not None
        and _openglprovider is not None
    ):
        if _openglprovider != provider:
            log(
                f"> graphics OpenGL provider switch refused "
                f"loaded={_openglprovider or 'unknown'} requested={provider}"
            )
            return False
        return True

    # A provider is committed only after every dependency, client library,
    # and required symbol has loaded.  Clear any incomplete state left by an
    # interrupted/older load before trying another DRM candidate.  In
    # particular, an NVIDIA preload failure must not pin this process to the
    # NVIDIA provider and prevent a later Mesa candidate from being tried.
    if (
        _egl is not None
        or _gles is not None
        or _openglprovider is not None
        or _opengldependencies
    ):
        log(
            f"> graphics rolling back incomplete OpenGL provider state "
            f"provider={_openglprovider or 'uncommitted'}"
        )

    _egl = None
    _gles = None
    _openglprovider = None
    _opengldependencies = []
    _eglcreateimage = None
    _egldestroyimage = None
    _glimage_target_texture = None
    _eglquerydmabufformats = None
    _eglquerydmabufmodifiers = None

    try:

        if runtime is None:
            runtime = _graphicsconfigureprovider(provider)

        dependencies = []

        if provider == "nvidia":
            dependencies = _graphicsnvidiapreload(runtime)

        # Use absolute T1OS catalogue paths so host libraries cannot leak in.
        _egl = ctypes.CDLL(runtime["egl"], mode=ctypes.RTLD_GLOBAL)
        _gles = ctypes.CDLL(runtime["gles"], mode=ctypes.RTLD_GLOBAL)
        log(
            f"> graphics OpenGL libraries loaded provider={provider} "
            f"egl={runtime['egl']} gles={runtime['gles']}"
        )

        # EGL display and context functions
        _egl.eglGetPlatformDisplay.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        _egl.eglGetPlatformDisplay.restype = ctypes.c_void_p
        _egl.eglInitialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        _egl.eglInitialize.restype = ctypes.c_uint
        _egl.eglChooseConfig.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p), ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        _egl.eglChooseConfig.restype = ctypes.c_uint
        _egl.eglBindAPI.argtypes = [ctypes.c_uint]
        _egl.eglBindAPI.restype = ctypes.c_uint
        _egl.eglCreatePbufferSurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        _egl.eglCreatePbufferSurface.restype = ctypes.c_void_p
        _egl.eglCreateWindowSurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        _egl.eglCreateWindowSurface.restype = ctypes.c_void_p
        _egl.eglCreateContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        _egl.eglCreateContext.restype = ctypes.c_void_p
        _egl.eglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        _egl.eglMakeCurrent.restype = ctypes.c_uint
        _egl.eglGetError.argtypes = []
        _egl.eglGetError.restype = ctypes.c_uint
        _egl.eglGetConfigAttrib.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        _egl.eglGetConfigAttrib.restype = ctypes.c_uint
        _egl.eglSwapBuffers.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _egl.eglSwapBuffers.restype = ctypes.c_uint
        _egl.eglSwapInterval.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _egl.eglSwapInterval.restype = ctypes.c_uint
        _egl.eglDestroyContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _egl.eglDestroyContext.restype = ctypes.c_uint
        _egl.eglDestroySurface.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _egl.eglDestroySurface.restype = ctypes.c_uint
        _egl.eglTerminate.argtypes = [ctypes.c_void_p]
        _egl.eglTerminate.restype = ctypes.c_uint
        _egl.eglQueryString.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _egl.eglQueryString.restype = ctypes.c_char_p
        _egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        _egl.eglGetProcAddress.restype = ctypes.c_void_p

        # GLES rendering and shader functions
        _gles.glClearColor.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        _gles.glClear.argtypes = [ctypes.c_uint]
        _gles.glFinish.argtypes = []
        _gles.glGetError.argtypes = []
        _gles.glGetError.restype = ctypes.c_uint
        _gles.glReadPixels.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        _gles.glGetString.argtypes = [ctypes.c_uint]
        _gles.glGetString.restype = ctypes.c_char_p
        _gles.glViewport.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        _gles.glCreateShader.argtypes = [ctypes.c_uint]
        _gles.glCreateShader.restype = ctypes.c_uint
        _gles.glShaderSource.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_int)]
        _gles.glCompileShader.argtypes = [ctypes.c_uint]
        _gles.glGetShaderiv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
        _gles.glGetShaderInfoLog.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p]
        _gles.glDeleteShader.argtypes = [ctypes.c_uint]
        _gles.glCreateProgram.argtypes = []
        _gles.glCreateProgram.restype = ctypes.c_uint
        _gles.glAttachShader.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glBindAttribLocation.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p]
        _gles.glLinkProgram.argtypes = [ctypes.c_uint]
        _gles.glGetProgramiv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
        _gles.glGetProgramInfoLog.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p]
        _gles.glUseProgram.argtypes = [ctypes.c_uint]
        _gles.glDeleteProgram.argtypes = [ctypes.c_uint]
        _gles.glEnableVertexAttribArray.argtypes = [ctypes.c_uint]
        _gles.glDisableVertexAttribArray.argtypes = [ctypes.c_uint]
        _gles.glVertexAttribPointer.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_void_p]
        _gles.glDrawArrays.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        _gles.glGenBuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glDeleteBuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glBindBuffer.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glBufferData.argtypes = [ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint]
        _gles.glBufferSubData.argtypes = [ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
        _gles.glGetUniformLocation.argtypes = [ctypes.c_uint, ctypes.c_char_p]
        _gles.glGetUniformLocation.restype = ctypes.c_int
        _gles.glUniform1i.argtypes = [ctypes.c_int, ctypes.c_int]
        _gles.glUniform1f.argtypes = [ctypes.c_int, ctypes.c_float]
        _gles.glUniform2f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float]
        _gles.glUniform3f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        _gles.glUniform4f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        _gles.glUniformMatrix4fv.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]
        _gles.glEnable.argtypes = [ctypes.c_uint]
        _gles.glDisable.argtypes = [ctypes.c_uint]
        _gles.glDepthFunc.argtypes = [ctypes.c_uint]
        _gles.glDepthMask.argtypes = [ctypes.c_uint]
        _gles.glBlendFunc.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glBlendFuncSeparate.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        _gles.glScissor.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        _gles.glActiveTexture.argtypes = [ctypes.c_uint]
        _gles.glGenTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glDeleteTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glBindTexture.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glTexParameteri.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
        _gles.glPixelStorei.argtypes = [ctypes.c_uint, ctypes.c_int]
        _gles.glTexImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        _gles.glTexSubImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        _gles.glCopyTexSubImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        _gles.glGenFramebuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glDeleteFramebuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glBindFramebuffer.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glFramebufferTexture2D.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
        _gles.glCheckFramebufferStatus.argtypes = [ctypes.c_uint]
        _gles.glCheckFramebufferStatus.restype = ctypes.c_uint
        _gles.glGenRenderbuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glDeleteRenderbuffers.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        _gles.glBindRenderbuffer.argtypes = [ctypes.c_uint, ctypes.c_uint]
        _gles.glRenderbufferStorage.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        _gles.glFramebufferRenderbuffer.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]

        createimagepointer = _egl.eglGetProcAddress(b"eglCreateImageKHR")
        destroyimagepointer = _egl.eglGetProcAddress(b"eglDestroyImageKHR")
        imagetargetpointer = _egl.eglGetProcAddress(b"glEGLImageTargetTexture2DOES")
        queryformatspointer = _egl.eglGetProcAddress(b"eglQueryDmaBufFormatsEXT")
        querymodifierspointer = _egl.eglGetProcAddress(b"eglQueryDmaBufModifiersEXT")
        if createimagepointer and destroyimagepointer and imagetargetpointer:
            _eglcreateimage = ctypes.CFUNCTYPE(
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
            )(createimagepointer)
            _egldestroyimage = ctypes.CFUNCTYPE(
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )(destroyimagepointer)
            _glimage_target_texture = ctypes.CFUNCTYPE(
                None,
                ctypes.c_uint,
                ctypes.c_void_p,
            )(imagetargetpointer)
        if queryformatspointer:
            _eglquerydmabufformats = ctypes.CFUNCTYPE(
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            )(queryformatspointer)
        if querymodifierspointer:
            _eglquerydmabufmodifiers = ctypes.CFUNCTYPE(
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint64),
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_int),
            )(querymodifierspointer)
        # Commit provider identity and the dependency handles last.  Until
        # this point every mutation above is provisional and the exception
        # path below can return the loader to its neutral state.
        _openglprovider = provider
        _opengldependencies = dependencies
        return True

    except Exception as e:

        _egl = None
        _gles = None
        _openglprovider = None
        _opengldependencies = []
        _eglcreateimage = None
        _egldestroyimage = None
        _glimage_target_texture = None
        _eglquerydmabufformats = None
        _eglquerydmabufmodifiers = None
        log(f"> graphics OpenGL load error provider={provider} error={e}")
        return False


def openglrequire(value, operation):

    if value:
        return value

    error = 0

    try:
        error = int(_egl.eglGetError())
    except Exception:
        pass

    if error == EGL_CONTEXT_LOST:
        raise GPUDeviceLostError(
            f"{operation} lost the EGL context (0x{error:04x})"
        )

    raise RuntimeError(f"{operation} failed with EGL error 0x{error:04x}")


def _eglconfiginteger(attribute, default=None):

    if _egl is None or not _egldisplay or not _eglconfig:
        return default

    value = ctypes.c_int()

    try:

        if _egl.eglGetConfigAttrib(
            _egldisplay,
            _eglconfig,
            int(attribute),
            ctypes.byref(value),
        ):
            return int(value.value)

    except Exception:
        pass

    return default


def _eglchoosexrgbconfig(configs, count):

    limit = min(max(0, int(count)), len(configs))

    if limit < 1:
        raise RuntimeError("EGL returned no GBM configurations")

    selected = configs[0]
    selectedindex = 0
    selectedvisual = None

    # Preserve the first native XRGB8888 configuration returned by the
    # provider. Querying and ranking every NVIDIA configuration during cold
    # boot needlessly enters vendor code dozens of times and was the only
    # changed work in the region where the physical boot stopped progressing.
    for index in range(limit):
        visual = ctypes.c_int()

        if (
            _egl.eglGetConfigAttrib(
                _egldisplay,
                configs[index],
                EGL_NATIVE_VISUAL_ID,
                ctypes.byref(visual),
            )
            and int(visual.value) == GBM_FORMAT_XRGB8888
        ):
            selected = configs[index]
            selectedindex = index
            selectedvisual = int(visual.value)
            break

    return selected, selectedindex, selectedvisual


def _eglconfigurekmspresentation():

    global _eglswapinterval, _eglminswapinterval, _eglmaxswapinterval
    global _egldeferredswapstate, _egldeferredswaperror

    _eglminswapinterval = _eglconfiginteger(EGL_MIN_SWAP_INTERVAL)
    _eglmaxswapinterval = _eglconfiginteger(EGL_MAX_SWAP_INTERVAL)
    _egldeferredswaperror = None

    # NVIDIA's EGL-GBM implementation already hands completed buffers to the
    # DRM page-flip owner. Keep its specified default interval during cold
    # initialization: the 610 stack has been observed to stop making progress
    # in this initialization region, and a latency preference must never be a
    # boot dependency. Mesa providers retain the explicit zero-interval policy.
    if _openglprovider == "nvidia":
        defaultinterval = 1

        if _eglminswapinterval is not None:
            defaultinterval = max(
                defaultinterval,
                int(_eglminswapinterval),
            )

        if _eglmaxswapinterval is not None:
            defaultinterval = min(
                defaultinterval,
                int(_eglmaxswapinterval),
            )

        _eglswapinterval = int(defaultinterval)
        requested = 0
        if _eglminswapinterval is not None:
            requested = max(requested, int(_eglminswapinterval))
        if _eglmaxswapinterval is not None:
            requested = min(requested, int(_eglmaxswapinterval))
        _egldeferredswapstate = (
            "pending-first-page-flip"
            if int(requested) != int(defaultinterval)
            else "not-supported"
        )
        return int(defaultinterval)

    requested = 0

    # DRM page flips are this compositor's sole vblank owner.  Leaving EGL at
    # its specified default interval of one can add an implementation-specific
    # second wait before the explicitly vblank-synchronised DRM submission.
    if _eglminswapinterval is not None:
        requested = max(requested, int(_eglminswapinterval))
    if _eglmaxswapinterval is not None:
        requested = min(requested, int(_eglmaxswapinterval))

    if not _egl.eglSwapInterval(_egldisplay, int(requested)):
        error = int(_egl.eglGetError())
        raise RuntimeError(
            f"eglSwapInterval({requested}) failed with EGL error 0x{error:04x}"
        )

    _eglswapinterval = int(requested)
    _egldeferredswapstate = "not-required"
    return int(requested)


def _eglapplydeferredkmspresentation():

    global _eglswapinterval, _egldeferredswapstate, _egldeferredswaperror

    if _egldeferredswapstate != "pending-first-page-flip":
        return False

    # The NVIDIA 610 GBM stack is left at its specified interval during cold
    # initialization. Once a real DRM event has completed, the display,
    # context, surface and scanout path are all known healthy and it is safe to
    # remove EGL's second refresh wait. DRM page flips remain the sole vblank
    # owner.
    _egldeferredswapstate = "applying"
    requested = 0
    if _eglminswapinterval is not None:
        requested = max(requested, int(_eglminswapinterval))
    if _eglmaxswapinterval is not None:
        requested = min(requested, int(_eglmaxswapinterval))

    try:
        if not _egl.eglSwapInterval(_egldisplay, int(requested)):
            error = int(_egl.eglGetError())
            raise RuntimeError(
                f"eglSwapInterval({requested}) failed with EGL error "
                f"0x{error:04x}"
            )

        _eglswapinterval = int(requested)
        _egldeferredswapstate = "applied-after-first-page-flip"
        _egldeferredswaperror = None
        log(
            f"> graphics EGL deferred presentation interval applied "
            f"interval={requested} owner=DRM-page-flip"
        )
        return True

    except Exception as error:
        _egldeferredswapstate = "failed"
        _egldeferredswaperror = f"{type(error).__name__}: {error}"
        log(
            f"> graphics EGL deferred presentation interval failed "
            f"error={_egldeferredswaperror}; retaining interval="
            f"{_eglswapinterval}"
        )
        return False


class GPUDeviceLostError(RuntimeError):
    pass


class WindowBufferAccessError(RuntimeError):

    """A client could not validate, open, or map its WindowServer buffer."""

    def __init__(self, stage, path, error, metadata=None):

        self.stage = str(stage)
        self.path = str(path)
        self.errno = getattr(error, "errno", None)
        self.metadata = dict(metadata or {})
        identity = (
            f"uid={getattr(os, 'geteuid', lambda: -1)()} "
            f"gid={getattr(os, 'getegid', lambda: -1)()}"
        )
        status = ""

        if self.metadata:
            status = " " + " ".join(
                f"{name}={value}"
                for name, value in sorted(self.metadata.items())
            )

        super().__init__(
            f"window buffer {self.stage} failed path={self.path!r} "
            f"{identity}{status}: {type(error).__name__}: {error}"
        )


def kmsraise(error, operation):

    error = int(error or 0)

    if error in (errno.ENODEV, errno.EIO):
        raise GPUDeviceLostError(
            f"{operation} reported a lost or unusable DRM device "
            f"(errno={error} {os.strerror(error)})"
        )

    raise OSError(error, operation)


def openglloadresetstatus(required=False):

    global _glgetgraphicsresetstatus, _glrobust, _gpuhealthlast

    _glgetgraphicsresetstatus = None
    _glrobust = False
    _gpuhealthlast = 0.0

    for name in (
        b"glGetGraphicsResetStatusKHR",
        b"glGetGraphicsResetStatusEXT",
        b"glGetGraphicsResetStatus",
    ):
        pointer = _egl.eglGetProcAddress(name)

        if pointer:
            _glgetgraphicsresetstatus = ctypes.CFUNCTYPE(ctypes.c_uint)(pointer)
            _glrobust = True
            break

    if required and _glgetgraphicsresetstatus is None:
        raise RuntimeError(
            "NVK requires a robust OpenGL reset-status entry point"
        )

    return bool(_glrobust)


def openglresetstatus(operation):

    if _glgetgraphicsresetstatus is None:
        return GL_NO_ERROR

    status = int(_glgetgraphicsresetstatus())

    if status == GL_NO_ERROR:
        return status

    names = {
        GL_GUILTY_CONTEXT_RESET: "guilty",
        GL_INNOCENT_CONTEXT_RESET: "innocent",
        GL_UNKNOWN_CONTEXT_RESET: "unknown",
    }
    name = names.get(status, f"0x{status:04x}")
    raise GPUDeviceLostError(
        f"{operation} detected a {name} GPU context reset"
    )


def gpuhealthcheck(synchronize=True, operation="GPU health check"):

    if not gpuavailable():
        raise RuntimeError(f"{operation} failed because the GPU backend is unavailable")

    openglresetstatus(operation)

    if synchronize:
        _gles.glFinish()
        openglresetstatus(operation)

    errors = []

    for _ in range(32):

        error = int(_gles.glGetError())

        if error == GL_NO_ERROR:
            break

        errors.append(error)

    if errors:

        detail = ",".join(f"0x{value:04x}" for value in errors)

        if GL_CONTEXT_LOST in errors:
            raise GPUDeviceLostError(
                f"{operation} detected a lost GPU context ({detail})"
            )

        raise RuntimeError(f"{operation} detected OpenGL errors ({detail})")

    return True


def gpuhealthsample(operation="GPU health sample", force=False):

    global _gpuhealthlast

    now = time.monotonic()

    if not force and (now - _gpuhealthlast) < GPUHEALTHINTERVAL:
        return True

    _gpuhealthlast = now
    _gputelemetry["gpu_health_samples"] += 1
    return gpuhealthcheck(synchronize=False, operation=operation)


def openglshader(kind, source):

    shader = int(_gles.glCreateShader(int(kind)))

    if shader == 0:
        raise RuntimeError("glCreateShader failed")

    sourcebytes = source.encode("utf-8")
    sourcepointer = ctypes.c_char_p(sourcebytes)
    sourcelength = ctypes.c_int(len(sourcebytes))
    _gles.glShaderSource(shader, 1, ctypes.byref(sourcepointer), ctypes.byref(sourcelength))
    _gles.glCompileShader(shader)

    compiled = ctypes.c_int()
    _gles.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(compiled))

    if compiled.value:
        return shader

    output = ctypes.create_string_buffer(4096)
    length = ctypes.c_int()
    _gles.glGetShaderInfoLog(shader, len(output), ctypes.byref(length), output)
    _gles.glDeleteShader(shader)
    detail = output.value.decode("utf-8", errors="replace")
    raise RuntimeError(f"OpenGL shader compile failed {detail}")


def openglprogram(vertexsource, fragmentsource):

    vertex = openglshader(GL_VERTEX_SHADER, vertexsource)
    fragment = openglshader(GL_FRAGMENT_SHADER, fragmentsource)
    program = int(_gles.glCreateProgram())

    if program == 0:
        _gles.glDeleteShader(vertex)
        _gles.glDeleteShader(fragment)
        raise RuntimeError("glCreateProgram failed")

    _gles.glAttachShader(program, vertex)
    _gles.glAttachShader(program, fragment)
    _gles.glBindAttribLocation(program, 0, b"position")
    _gles.glBindAttribLocation(program, 1, b"texcoord")
    _gles.glBindAttribLocation(program, 2, b"vertexcolor")
    _gles.glBindAttribLocation(program, 3, b"normal")
    _gles.glBindAttribLocation(program, 4, b"other")
    _gles.glLinkProgram(program)

    linked = ctypes.c_int()
    _gles.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(linked))
    _gles.glDeleteShader(vertex)
    _gles.glDeleteShader(fragment)

    if linked.value:
        return program

    output = ctypes.create_string_buffer(4096)
    length = ctypes.c_int()
    _gles.glGetProgramInfoLog(program, len(output), ctypes.byref(length), output)
    _gles.glDeleteProgram(program)
    detail = output.value.decode("utf-8", errors="replace")
    raise RuntimeError(f"OpenGL program link failed {detail}")


def opengloffscreen(width=8, height=8):

    global _backend, _egldisplay, _eglconfig, _eglsurface, _eglcontext, _eglmajor, _eglminor
    global _eglvendor, _eglswapinterval, _eglminswapinterval, _eglmaxswapinterval
    global _xres, _yres

    openglclose()

    if not openglload():
        raise RuntimeError("OpenGL catalogue libraries did not load")

    os.environ["EGL_PLATFORM"] = "surfaceless"
    os.environ["GALLIUM_DRIVER"] = "softpipe"
    os.environ["GBM_BACKENDS_PATH"] = GBMBACKENDPATH

    _egldisplay = openglrequire(
        _egl.eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, None, None),
        "eglGetPlatformDisplay",
    )

    major = ctypes.c_int()
    minor = ctypes.c_int()
    openglrequire(_egl.eglInitialize(_egldisplay, ctypes.byref(major), ctypes.byref(minor)), "eglInitialize")
    _eglmajor = major.value
    _eglminor = minor.value
    vendorvalue = _egl.eglQueryString(_egldisplay, EGL_VENDOR)
    _eglvendor = (
        vendorvalue.decode("utf-8", errors="replace")
        if vendorvalue
        else None
    )

    attributes = (ctypes.c_int * 13)(
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8,
        EGL_ALPHA_SIZE, 8,
        EGL_NONE,
    )
    config = ctypes.c_void_p()
    count = ctypes.c_int()
    openglrequire(
        _egl.eglChooseConfig(_egldisplay, attributes, ctypes.byref(config), 1, ctypes.byref(count)),
        "eglChooseConfig",
    )

    if count.value != 1:
        raise RuntimeError("eglChooseConfig returned no matching configuration")

    _eglconfig = config
    openglrequire(_egl.eglBindAPI(EGL_OPENGL_ES_API), "eglBindAPI")
    surfaceattributes = (ctypes.c_int * 5)(EGL_WIDTH, int(width), EGL_HEIGHT, int(height), EGL_NONE)
    _eglsurface = openglrequire(
        _egl.eglCreatePbufferSurface(_egldisplay, _eglconfig, surfaceattributes),
        "eglCreatePbufferSurface",
    )
    contextattributes = (ctypes.c_int * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
    _eglcontext = openglrequire(
        _egl.eglCreateContext(_egldisplay, _eglconfig, None, contextattributes),
        "eglCreateContext",
    )
    openglrequire(
        _egl.eglMakeCurrent(_egldisplay, _eglsurface, _eglsurface, _eglcontext),
        "eglMakeCurrent",
    )
    _xres = int(width)
    _yres = int(height)
    _backend = "opengloffscreen"
    return True


def openglclose():

    global _backend, _egldisplay, _eglconfig, _eglsurface, _eglcontext, _eglmajor, _eglminor
    global _eglvendor, _eglswapinterval, _eglminswapinterval, _eglmaxswapinterval
    global _egldeferredswapstate, _egldeferredswaperror
    global _eglextensions, _eglextensionsqueried, _glextensions
    global _glgetgraphicsresetstatus, _glrobust

    gpurelease()

    try:

        if _egl is not None and _egldisplay:
            _egl.eglMakeCurrent(_egldisplay, None, None, None)

            if _eglcontext:
                _egl.eglDestroyContext(_egldisplay, _eglcontext)

            if _eglsurface:
                _egl.eglDestroySurface(_egldisplay, _eglsurface)

            _egl.eglTerminate(_egldisplay)

    except Exception:
        pass

    _egldisplay = None
    _eglconfig = None
    _eglsurface = None
    _eglcontext = None
    _eglmajor = 0
    _eglminor = 0
    _eglvendor = None
    _eglextensions = frozenset()
    _eglextensionsqueried = False
    _glextensions = None
    _eglswapinterval = None
    _eglminswapinterval = None
    _eglmaxswapinterval = None
    _egldeferredswapstate = "inactive"
    _egldeferredswaperror = None
    _glgetgraphicsresetstatus = None
    _glrobust = False

    if _backend == "opengloffscreen":
        _backend = "none"


def opengldiagnostic():

    result = {
        "format": 1,
        "passed": False,
        "egl": None,
        "renderer": None,
        "version": None,
        "pixel": None,
        "compositor": None,
        "layers": None,
        "errors": [],
    }
    program = 0

    try:

        opengloffscreen(8, 8)
        vertexsource = "attribute vec2 position; void main() { gl_Position = vec4(position, 0.0, 1.0); }"
        fragmentsource = "precision mediump float; void main() { gl_FragColor = vec4(0.25, 0.5, 0.75, 1.0); }"
        program = openglprogram(vertexsource, fragmentsource)
        vertices = (ctypes.c_float * 6)(-1.0, -1.0, 3.0, -1.0, -1.0, 3.0)
        _gles.glViewport(0, 0, 8, 8)
        _gles.glClearColor(0.0, 0.0, 0.0, 1.0)
        _gles.glClear(GL_COLOR_BUFFER_BIT)
        _gles.glUseProgram(program)
        _gles.glEnableVertexAttribArray(0)
        _gles.glVertexAttribPointer(0, 2, GL_FLOAT, 0, 0, ctypes.cast(vertices, ctypes.c_void_p))
        _gles.glDrawArrays(0x0004, 0, 3)
        _gles.glDisableVertexAttribArray(0)
        _gles.glFinish()

        pixel = (ctypes.c_ubyte * 4)()
        _gles.glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
        values = list(pixel)
        expected = (64, 128, 191, 255)

        if any(abs(actual - wanted) > 1 for actual, wanted in zip(values, expected)):
            raise RuntimeError(f"unexpected OpenGL pixel {values}")

        renderer = _gles.glGetString(GL_RENDERER)
        version = _gles.glGetString(GL_VERSION)
        result["egl"] = f"{_eglmajor}.{_eglminor}"
        result["renderer"] = renderer.decode("utf-8") if renderer else None
        result["version"] = version.decode("utf-8") if version else None
        result["pixel"] = values
        result["compositor"] = openglcompositordiagnostic()
        result["layers"] = gpulayerdiagnostic()
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    finally:

        try:
            if program:
                _gles.glDeleteProgram(program)
        except Exception:
            pass

        openglclose()

    return result


def openglcommand():

    result = opengldiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


def drmload():

    global _drm

    if _drm is not None:
        return True

    try:

        _drm = ctypes.CDLL(
            os.path.join(GRAPHICSCATALOGUE, "libdrm.so.2"),
            mode=ctypes.RTLD_GLOBAL,
            use_errno=True,
        )
        _drm.drmGetVersion.argtypes = [ctypes.c_int]
        _drm.drmGetVersion.restype = ctypes.POINTER(drmVersion)
        _drm.drmFreeVersion.argtypes = [ctypes.POINTER(drmVersion)]
        _drm.drmFreeVersion.restype = None
        _drm.drmModeGetResources.argtypes = [ctypes.c_int]
        _drm.drmModeGetResources.restype = ctypes.POINTER(drmModeRes)
        _drm.drmModeFreeResources.argtypes = [ctypes.POINTER(drmModeRes)]
        _drm.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
        _drm.drmModeGetConnector.restype = ctypes.POINTER(drmModeConnector)
        _drm.drmModeFreeConnector.argtypes = [ctypes.POINTER(drmModeConnector)]
        _drm.drmModeGetEncoder.argtypes = [ctypes.c_int, ctypes.c_uint32]
        _drm.drmModeGetEncoder.restype = ctypes.POINTER(drmModeEncoder)
        _drm.drmModeFreeEncoder.argtypes = [ctypes.POINTER(drmModeEncoder)]
        _drm.drmModeGetCrtc.argtypes = [ctypes.c_int, ctypes.c_uint32]
        _drm.drmModeGetCrtc.restype = ctypes.POINTER(drmModeCrtc)
        _drm.drmModeFreeCrtc.argtypes = [ctypes.POINTER(drmModeCrtc)]
        if hasattr(_drm, "drmCrtcGetSequence"):
            _drm.drmCrtcGetSequence.argtypes = [
                ctypes.c_int,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint64),
                ctypes.POINTER(ctypes.c_uint64),
            ]
            _drm.drmCrtcGetSequence.restype = ctypes.c_int
        if hasattr(_drm, "drmModeGetProperty"):
            _drm.drmModeGetProperty.argtypes = [
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            _drm.drmModeGetProperty.restype = ctypes.POINTER(
                drmModePropertyRes
            )
            _drm.drmModeFreeProperty.argtypes = [
                ctypes.POINTER(drmModePropertyRes)
            ]
            _drm.drmModeFreeProperty.restype = None
        _drm.drmModeAddFB.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        _drm.drmModeAddFB.restype = ctypes.c_int
        _drm.drmModeRmFB.argtypes = [ctypes.c_int, ctypes.c_uint32]
        _drm.drmModeRmFB.restype = ctypes.c_int
        if hasattr(_drm, "drmModeDirtyFB"):
            _drm.drmModeDirtyFB.argtypes = [
                ctypes.c_int,
                ctypes.c_uint32,
                ctypes.POINTER(drmModeClip),
                ctypes.c_uint32,
            ]
            _drm.drmModeDirtyFB.restype = ctypes.c_int
        _drm.drmModeSetCrtc.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int, ctypes.POINTER(drmModeModeInfo)]
        _drm.drmModeSetCrtc.restype = ctypes.c_int
        _drm.drmModePageFlip.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        _drm.drmModePageFlip.restype = ctypes.c_int
        _drm.drmHandleEvent.argtypes = [ctypes.c_int, ctypes.POINTER(drmEventContext)]
        _drm.drmHandleEvent.restype = ctypes.c_int
        return True

    except Exception as error:

        _drm = None
        log(f"> graphics DRM load error {error}")
        return False


def kmsload(provider="mesa"):

    global _gbm

    if not drmload():
        return False

    try:
        # GBM may inspect its backend path while the neutral loader is being
        # opened, so establish the selected provider's environment first.
        runtime = _graphicsconfigureprovider(provider)
    except Exception as error:
        log(
            f"> graphics KMS provider configuration failed "
            f"provider={provider} error={error}"
        )
        return False

    if _gbm is None:

        try:

            _gbm = ctypes.CDLL(
                os.path.join(GRAPHICSCATALOGUE, "libgbm.so.1"),
                mode=ctypes.RTLD_GLOBAL,
                use_errno=True,
            )

            # GBM device, surface, and buffer functions
            _gbm.gbm_create_device.argtypes = [ctypes.c_int]
            _gbm.gbm_create_device.restype = ctypes.c_void_p
            _gbm.gbm_device_destroy.argtypes = [ctypes.c_void_p]
            _gbm.gbm_surface_create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
            _gbm.gbm_surface_create.restype = ctypes.c_void_p
            _gbm.gbm_surface_destroy.argtypes = [ctypes.c_void_p]
            _gbm.gbm_surface_lock_front_buffer.argtypes = [ctypes.c_void_p]
            _gbm.gbm_surface_lock_front_buffer.restype = ctypes.c_void_p
            _gbm.gbm_surface_release_buffer.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            _gbm.gbm_bo_get_handle.argtypes = [ctypes.c_void_p]
            _gbm.gbm_bo_get_handle.restype = gbm_bo_handle
            _gbm.gbm_bo_get_stride.argtypes = [ctypes.c_void_p]
            _gbm.gbm_bo_get_stride.restype = ctypes.c_uint32

        except Exception as error:

            _gbm = None
            log(f"> graphics KMS/GBM load error {error}")
            return False

    # The neutral Mesa GBM loader and libdrm must already be resident when
    # NVIDIA's external EGL GBM platform is preloaded.
    return bool(openglload(provider, runtime=runtime))


def kmsstructure(pointer, structuretype):

    size = ctypes.sizeof(structuretype)
    data = ctypes.string_at(pointer, size)
    return structuretype.from_buffer_copy(data)


def kmsdriverinfo():

    result = {
        "name": None,
        "version": None,
        "date": None,
        "description": None,
    }
    versionpointer = None

    try:

        versionpointer = _drm.drmGetVersion(_drmfd)

        if not versionpointer:
            return result

        version = versionpointer.contents

        if version.name and version.name_len:
            result["name"] = ctypes.string_at(version.name, version.name_len).decode("utf-8", errors="replace")

        result["version"] = f"{int(version.version_major)}.{int(version.version_minor)}.{int(version.version_patchlevel)}"

        if version.date and version.date_len:
            result["date"] = ctypes.string_at(version.date, version.date_len).decode("utf-8", errors="replace")

        if version.desc and version.desc_len:
            result["description"] = ctypes.string_at(version.desc, version.desc_len).decode("utf-8", errors="replace")

    except Exception as e:

        log(f"> graphics DRM version query failed {e!r}")

    finally:

        try:
            if versionpointer:
                _drm.drmFreeVersion(versionpointer)
        except Exception:
            pass

    return result


def _displaybool(value, default=False):

    if isinstance(value, bool):
        return value

    lowered = str(value).strip().lower()

    if lowered in ('1', 'true', 'yes', 'on'):
        return True

    if lowered in ('0', 'false', 'no', 'off'):
        return False

    return bool(default)


def _displayclockminutes(value, default):

    match = re.fullmatch(r'\s*([01]?\d|2[0-3]):([0-5]\d)\s*', str(value))

    if not match:
        return int(default)

    return int(match.group(1)) * 60 + int(match.group(2))


def _displaytemperature(moment=None):

    settings = DISPLAYNIGHTLIGHT
    moment = time.time() if moment is None else float(moment)

    if not _displaybool(settings.get('night_light_enabled')):
        return 6500

    preview = _displaybool(settings.get('night_light_preview'))
    mode = str(settings.get(
        'night_light_mode',
        'manual' if str(settings.get('night_light_schedule', '')).lower() == 'always' else 'automatic',
    )).strip().lower()
    if mode == 'manual':
        return max(1000, min(
            6500, int(settings.get('night_light_manual_temperature',
                                   settings.get('night_light_bedtime_temperature', 3400)))))

    # Use the same timezone-aware system clock as Expanse's taskbar.  A plain
    # datetime.fromtimestamp() follows the process timezone (normally UTC on
    # T1OS), which makes an automatic evening schedule look like daytime.
    local = currentdatetime(moment)
    minute = local.hour * 60 + local.minute + (local.second / 60.0)
    if preview and _displaypreviewstarted:
        elapsed = max(0.0, time.monotonic() - float(_displaypreviewstarted))
        minute = (elapsed / 15.0) * 1440.0

    daytemperature = max(1000, min(6500, int(settings.get('night_light_day_temperature', 6500))))
    eveningtemperature = max(1000, min(6500, int(settings.get('night_light_sunset_temperature', 4500))))
    bedtimetemperature = max(1000, min(6500, int(settings.get('night_light_bedtime_temperature', 3400))))
    events = sorted((
        (_displayclockminutes(settings.get('night_light_day_time'), 6 * 60), daytemperature),
        (_displayclockminutes(settings.get('night_light_evening_time'), 18 * 60), eveningtemperature),
        (_displayclockminutes(settings.get('night_light_bedtime_time'), 22 * 60), bedtimetemperature),
    ), key=lambda event: event[0])
    latestindex = max(
        (index for index, event in enumerate(events) if event[0] <= minute),
        default=len(events) - 1)
    eventminute, target = events[latestindex]
    previous = events[(latestindex - 1) % len(events)][1]
    elapsed = (minute - eventminute) % 1440.0
    transition = max(
        1, min(30, int(settings.get('night_light_transition_minutes', 10))))

    if elapsed < transition:
        amount = elapsed / float(transition)
        target = int(round(previous + ((target - previous) * amount)))

    return max(1000, min(6500, int(target)))


def _displaytemperaturechannels(kelvin):

    temperature = max(1000.0, min(6500.0, float(kelvin))) / 100.0

    if temperature <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
    else:
        red = 329.698727446 * ((temperature - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60.0) ** -0.0755148492)

    if temperature >= 66.0:
        blue = 255.0
    elif temperature <= 19.0:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temperature - 10.0) - 305.0447927307

    reference = (255.0, 254.1100838756, 250.0419083427)
    return tuple(
        max(0.0, min(1.0, value / baseline))
        for value, baseline in zip((red, green, blue), reference))


def _rebuilddisplayadjustment():

    global DISPLAYEFFECTIVESATURATION, DISPLAYTEMPERATURE, DISPLAYCHANNELS
    global _displayoutputlut, _displaychannelluts, _displaysaturationlut

    DISPLAYTEMPERATURE = _displaytemperature()
    DISPLAYCHANNELS = _displaytemperaturechannels(DISPLAYTEMPERATURE)
    DISPLAYEFFECTIVESATURATION = int(DISPLAYSATURATION)

    output = []

    for value in range(256):
        adjusted = 128 + ((value - 128) * int(DISPLAYCONTRAST)) // 100
        adjusted = (adjusted * int(DISPLAYBRIGHTNESS)) // 100
        output.append(max(0, min(255, adjusted)))

    _displayoutputlut = bytes(output)
    _displaychannelluts = tuple(
        bytes(max(0, min(255, int(round(value * multiplier)))) for value in output)
        for multiplier in DISPLAYCHANNELS)

    if int(DISPLAYEFFECTIVESATURATION) == 100:
        _displaysaturationlut = None
    else:
        tables = []

        for channel in range(3):
            saturationtable = bytearray(256 * 256)

            for luminance in range(256):
                base = luminance << 8

                for value in range(256):
                    saturated = luminance + ((value - luminance) * int(DISPLAYEFFECTIVESATURATION)) // 100
                    saturationtable[base + value] = _displaychannelluts[channel][max(0, min(255, saturated))]

            tables.append(bytes(saturationtable))

        _displaysaturationlut = tuple(tables)


def setdisplayadjustment(brightness=100, contrast=100, saturation=100, **settings):

    global DISPLAYBRIGHTNESS, DISPLAYCONTRAST, DISPLAYSATURATION, _displaypreviewstarted

    DISPLAYBRIGHTNESS = max(0, min(200, int(round(float(brightness)))))
    DISPLAYCONTRAST = max(0, min(200, int(round(float(contrast)))))
    DISPLAYSATURATION = max(0, min(200, int(round(float(saturation)))))

    # Accept display files written by the previous schedule model so night
    # light still behaves predictably before Settings rewrites the file.
    legacyschedule = str(settings.get('night_light_schedule', '')).lower()
    if 'night_light_mode' not in settings and legacyschedule:
        settings['night_light_mode'] = (
            'manual' if legacyschedule == 'always' else 'automatic')
    if legacyschedule == 'always' and 'night_light_manual_temperature' not in settings:
        settings['night_light_manual_temperature'] = settings.get(
            'night_light_bedtime_temperature', 3400)
    if legacyschedule == 'custom':
        settings.setdefault(
            'night_light_day_time', settings.get('night_light_custom_end', '06:00'))
        settings.setdefault(
            'night_light_evening_time', settings.get('night_light_custom_start', '18:00'))

    for key in tuple(DISPLAYNIGHTLIGHT):
        if key in settings:
            DISPLAYNIGHTLIGHT[key] = settings[key]

    if _displaybool(DISPLAYNIGHTLIGHT.get('night_light_preview')):
        _displaypreviewstarted = time.monotonic()

    _rebuilddisplayadjustment()
    return displayadjustment()


def refreshdisplayadjustment():
    """Advance schedules and previews; return True when the output changed."""

    global _displaypreviewstarted

    if (
        _displaybool(DISPLAYNIGHTLIGHT.get('night_light_preview')) and
        _displaypreviewstarted and
        time.monotonic() - float(_displaypreviewstarted) >= 15.0
    ):
        DISPLAYNIGHTLIGHT['night_light_preview'] = False
        _displaypreviewstarted = 0.0

    temperature = _displaytemperature()
    channels = _displaytemperaturechannels(temperature)
    effectivesaturation = int(DISPLAYSATURATION)
    changed = (
        int(temperature) != int(DISPLAYTEMPERATURE) or
        int(effectivesaturation) != int(DISPLAYEFFECTIVESATURATION) or
        any(
            abs(float(actual) - float(previous)) >= 0.0001
            for actual, previous in zip(channels, DISPLAYCHANNELS))
    )

    if changed:
        _rebuilddisplayadjustment()

    return changed


def displayadjustment():

    return {
        'brightness': int(DISPLAYBRIGHTNESS),
        'contrast': int(DISPLAYCONTRAST),
        'saturation': int(DISPLAYSATURATION),
        'temperature': int(DISPLAYTEMPERATURE),
        'red': float(DISPLAYCHANNELS[0]),
        'green': float(DISPLAYCHANNELS[1]),
        'blue': float(DISPLAYCHANNELS[2]),
        'night_light_enabled': _displaybool(DISPLAYNIGHTLIGHT.get('night_light_enabled')),
    }


def displayadjustactive():

    return not (
        int(DISPLAYBRIGHTNESS) == 100
        and int(DISPLAYCONTRAST) == 100
        and int(DISPLAYEFFECTIVESATURATION) == 100
        and all(abs(float(value) - 1.0) < 0.0001 for value in DISPLAYCHANNELS)
    )


def displayadjustpixel(red, green, blue):

    red = max(0, min(255, int(red)))
    green = max(0, min(255, int(green)))
    blue = max(0, min(255, int(blue)))
    luminance = ((77 * red) + (150 * green) + (29 * blue)) >> 8

    if _displaysaturationlut is None:
        return _displaychannelluts[0][red], _displaychannelluts[1][green], _displaychannelluts[2][blue]

    base = luminance << 8
    return (
        _displaysaturationlut[0][base + red],
        _displaysaturationlut[1][base + green],
        _displaysaturationlut[2][base + blue],
    )


def displayadjustregions(regions):

    if not displayadjustactive() or not _buffer:
        return 0

    normalised = []

    for region in regions or []:

        try:
            x, y, width, height = [int(value) for value in region]
        except Exception:
            continue

        if x < 0:
            width += x
            x = 0

        if y < 0:
            height += y
            y = 0

        width = min(width, int(_xres) - x)
        height = min(height, int(_yres) - y)

        if width > 0 and height > 0:
            normalised.append((x, y, width, height))

    if not normalised:
        return 0

    fast32 = (
        int(_bpp_bytes) == 4
        and int(_rlen) == 8
        and int(_glen) == 8
        and int(_blen) == 8
        and int(_roff) % 8 == 0
        and int(_goff) % 8 == 0
        and int(_boff) % 8 == 0
    )
    changed = 0

    if fast32:

        redbyte = int(_roff) // 8
        greenbyte = int(_goff) // 8
        bluebyte = int(_boff) // 8
        fast32 = len({redbyte, greenbyte, bluebyte}) == 3 and max(redbyte, greenbyte, bluebyte) <= 3

    if fast32 and _displaysaturationlut is None:

        for x, y, width, height in normalised:

            rowbytes = width * 4

            for row in range(y, y + height):

                start = (row * int(_line)) + (x * 4)
                end = start + rowbytes

                for channelbyte, channellut in (
                    (redbyte, _displaychannelluts[0]),
                    (greenbyte, _displaychannelluts[1]),
                    (bluebyte, _displaychannelluts[2]),
                ):
                    channel = _buffer[start + channelbyte:end:4]
                    _buffer[start + channelbyte:end:4] = channel.translate(channellut)

                changed += width

        return changed

    for x, y, width, height in normalised:

        for row in range(y, y + height):

            offset = (row * int(_line)) + (x * int(_bpp_bytes))
            end = offset + (width * int(_bpp_bytes))

            while offset < end:

                if fast32:
                    red = _buffer[offset + redbyte]
                    green = _buffer[offset + greenbyte]
                    blue = _buffer[offset + bluebyte]
                    luminance = ((77 * red) + (150 * green) + (29 * blue)) >> 8
                    base = luminance << 8
                    red = _displaysaturationlut[0][base + red]
                    green = _displaysaturationlut[1][base + green]
                    blue = _displaysaturationlut[2][base + blue]
                    _buffer[offset + redbyte] = red
                    _buffer[offset + greenbyte] = green
                    _buffer[offset + bluebyte] = blue
                else:
                    red, green, blue = unpackrgb(_buffer[offset:offset + int(_bpp_bytes)])
                    _buffer[offset:offset + int(_bpp_bytes)] = packrgb(displayadjustpixel(red, green, blue))

                offset += int(_bpp_bytes)
                changed += 1

    return changed


def virtualboxcontrolsresolution():

    try:

        return (
            os.path.isfile(VBOXDRMCLIENT)
            and os.access(VBOXDRMCLIENT, os.X_OK)
            and os.path.exists(VBOXGUESTNODE)
        )

    except Exception:

        return False


def loaddisplaysettings(path=None):

    global KMSMODEWIDTH, KMSMODEHEIGHT, KMSMODEEXPLICIT

    target = str(path or DISPLAYSETTINGS)
    virtualbox = path is None and virtualboxcontrolsresolution()
    KMSMODEEXPLICIT = False

    try:

        with open(target, 'r', encoding='utf-8') as stream:
            settings = json.load(stream)

        width = int(settings.get('width', KMSMODEWIDTH))
        height = int(settings.get('height', KMSMODEHEIGHT))
        adjustment = setdisplayadjustment(
            settings.get('brightness', 100),
            settings.get('contrast', 100),
            settings.get('saturation', 100),
            **{
                key: value for key, value in settings.items()
                if str(key).startswith('night_light_')
            },
        )

        if width < KMSMINWIDTH or width > KMSMAXWIDTH:
            raise ValueError(f'display width {width} is outside the supported range')

        if height < KMSMINHEIGHT or height > KMSMAXHEIGHT:
            raise ValueError(f'display height {height} is outside the supported range')

        if width * height * 4 > KMSMAXBUFFERBYTES:
            raise ValueError('display mode would exceed the framebuffer memory limit')

        if not virtualbox and "width" in settings and "height" in settings:
            KMSMODEWIDTH = width
            KMSMODEHEIGHT = height
            KMSMODEEXPLICIT = True
        else:
            if virtualbox:
                log("> graphics display resolution controlled by VirtualBox Guest Additions")

        return {
            'width': int(KMSMODEWIDTH),
            'height': int(KMSMODEHEIGHT),
            'controller': 'virtualbox' if virtualbox else 'settings',
            **adjustment,
        }

    except FileNotFoundError:

        return {'width': int(KMSMODEWIDTH), 'height': int(KMSMODEHEIGHT), **displayadjustment()}

    except Exception as error:

        log(f"> graphics display settings ignored {error}")
        return {'width': int(KMSMODEWIDTH), 'height': int(KMSMODEHEIGHT), **displayadjustment()}


def kmsmoderefresh(mode):

    try:
        reported = max(0, int(mode.vrefresh))

        if reported:
            return float(reported)

        clock = max(0, int(mode.clock))
        htotal = max(0, int(mode.htotal))
        vtotal = max(0, int(mode.vtotal))

        if clock and htotal and vtotal:
            return (float(clock) * 1000.0) / float(htotal * vtotal)

    except Exception:
        pass

    return 0.0


def kmsmoderefreshrank(mode):

    try:
        return (
            int(round(kmsmoderefresh(mode) * 1000.0)),
            max(0, int(mode.clock)),
        )
    except Exception:
        return (0, 0)


def kmsfindmode(resize=False, preserve_current=False):

    resourcespointer = _drm.drmModeGetResources(_drmfd)

    if not resourcespointer:
        raise RuntimeError("drmModeGetResources returned no resources")

    selectedconnector = 0
    selectedcrtc = 0
    selectedmode = None
    dynamicpreferred = bool(
        resize
        and (
            str(_drmdriver or "").lower() in ("virtio_gpu", "vmwgfx")
            or virtualboxcontrolsresolution()
        )
    )

    try:

        resources = resourcespointer.contents

        for connectorindex in range(resources.count_connectors):

            connectorid = int(resources.connectors[connectorindex])
            connectorpointer = _drm.drmModeGetConnector(_drmfd, connectorid)

            if not connectorpointer:
                continue

            try:

                connector = connectorpointer.contents

                if connector.connection != DRM_MODE_CONNECTED or connector.count_modes < 1:
                    continue

                modeindex = 0
                preferredindex = None
                targetindex = None
                aspectindex = None
                aspectarea = -1
                fallbackindex = None
                fallbackarea = -1
                largestindex = 0
                largestarea = -1
                currentindex = None
                currentresolutionindex = None

                for index in range(connector.count_modes):

                    mode = connector.modes[index]
                    width = int(mode.hdisplay)
                    height = int(mode.vdisplay)
                    area = width * height

                    if int(mode.type) & DRM_MODE_TYPE_PREFERRED:

                        if (
                            preferredindex is None
                            or kmsmoderefreshrank(mode)
                            > kmsmoderefreshrank(connector.modes[preferredindex])
                        ):
                            preferredindex = index

                    if width == KMSMODEWIDTH and height == KMSMODEHEIGHT:

                        if (
                            targetindex is None
                            or kmsmoderefreshrank(mode)
                            > kmsmoderefreshrank(connector.modes[targetindex])
                        ):
                            targetindex = index

                    if width <= KMSMODEWIDTH and height <= KMSMODEHEIGHT and width * KMSMODEHEIGHT == height * KMSMODEWIDTH:

                        if (
                            area > aspectarea
                            or (
                                area == aspectarea
                                and (
                                    aspectindex is None
                                    or kmsmoderefreshrank(mode)
                                    > kmsmoderefreshrank(connector.modes[aspectindex])
                                )
                            )
                        ):
                            aspectindex = index
                            aspectarea = area

                    if width <= KMSMODEWIDTH and height <= KMSMODEHEIGHT:

                        if (
                            area > fallbackarea
                            or (
                                area == fallbackarea
                                and (
                                    fallbackindex is None
                                    or kmsmoderefreshrank(mode)
                                    > kmsmoderefreshrank(connector.modes[fallbackindex])
                                )
                            )
                        ):
                            fallbackindex = index
                            fallbackarea = area

                    if (
                        area > largestarea
                        or (
                            area == largestarea
                            and kmsmoderefreshrank(mode)
                            > kmsmoderefreshrank(connector.modes[largestindex])
                        )
                    ):
                        largestindex = index
                        largestarea = area

                crtcid = 0

                if connector.encoder_id:

                    encoderpointer = _drm.drmModeGetEncoder(_drmfd, connector.encoder_id)

                    if encoderpointer:

                        try:
                            crtcid = int(encoderpointer.contents.crtc_id)
                        finally:
                            _drm.drmModeFreeEncoder(encoderpointer)

                if crtcid == 0:

                    for encoderindex in range(connector.count_encoders):

                        encoderpointer = _drm.drmModeGetEncoder(_drmfd, connector.encoders[encoderindex])

                        if not encoderpointer:
                            continue

                        try:

                            encoder = encoderpointer.contents

                            for crtcindex in range(resources.count_crtcs):

                                if int(encoder.possible_crtcs) & (1 << crtcindex):
                                    crtcid = int(resources.crtcs[crtcindex])
                                    break

                        finally:
                            _drm.drmModeFreeEncoder(encoderpointer)

                        if crtcid:
                            break

                # Physical hardware starts with the mode already established
                # by firmware/DRM rather than a compiled resolution. Match the
                # active CRTC mode back to this connector's advertised modes.
                # If no active mode exists, use the connector's preferred mode.
                if crtcid:
                    crtcpointer = _drm.drmModeGetCrtc(_drmfd, crtcid)

                    if crtcpointer:

                        try:
                            crtc = crtcpointer.contents

                            if int(crtc.mode_valid):
                                currentkey = kmsmodekey(crtc.mode)
                                currentwidth = int(crtc.mode.hdisplay)
                                currentheight = int(crtc.mode.vdisplay)

                                for index in range(connector.count_modes):

                                    if kmsmodekey(connector.modes[index]) == currentkey:
                                        currentindex = index

                                    mode = connector.modes[index]

                                    if (
                                        int(mode.hdisplay) == currentwidth
                                        and int(mode.vdisplay) == currentheight
                                        and (
                                            currentresolutionindex is None
                                            or kmsmoderefreshrank(mode)
                                            > kmsmoderefreshrank(
                                                connector.modes[currentresolutionindex]
                                            )
                                        )
                                    ):
                                        currentresolutionindex = index

                        finally:
                            _drm.drmModeFreeCrtc(crtcpointer)

                # Explicit T1OS display settings remain a user-requested mode.
                # Accelerated startup retains the active resolution but can
                # adopt its highest advertised refresh rate. A CPU recovery
                # owner instead preserves the exact active timing: changing
                # timing while replacing a failed owner can retrain HDMI and
                # remove the only visible recovery path. Virtual display
                # drivers continue to follow host-controlled preferred modes.
                if dynamicpreferred and preferredindex is not None:
                    modeindex = preferredindex
                elif KMSMODEEXPLICIT and targetindex is not None:
                    modeindex = targetindex
                elif KMSMODEEXPLICIT and aspectindex is not None:
                    modeindex = aspectindex
                elif KMSMODEEXPLICIT and fallbackindex is not None:
                    modeindex = fallbackindex
                elif preserve_current and currentindex is not None:
                    modeindex = currentindex
                elif currentresolutionindex is not None:
                    modeindex = currentresolutionindex
                elif currentindex is not None:
                    modeindex = currentindex
                elif preferredindex is not None:
                    modeindex = preferredindex
                else:
                    modeindex = largestindex

                if crtcid:
                    selectedconnector = connectorid
                    selectedcrtc = crtcid
                    selectedmode = drmModeModeInfo.from_buffer_copy(
                        ctypes.string_at(ctypes.byref(connector.modes[modeindex]), ctypes.sizeof(drmModeModeInfo))
                    )
                    break

            finally:
                _drm.drmModeFreeConnector(connectorpointer)

    finally:
        _drm.drmModeFreeResources(resourcespointer)

    if not selectedconnector or not selectedcrtc or selectedmode is None:
        raise RuntimeError("no connected DRM connector with an available CRTC")

    return selectedconnector, selectedcrtc, selectedmode


def kmsmodekey(mode):

    if mode is None:
        return None

    try:

        return (
            int(mode.clock),
            int(mode.hdisplay),
            int(mode.hsync_start),
            int(mode.hsync_end),
            int(mode.htotal),
            int(mode.hskew),
            int(mode.vdisplay),
            int(mode.vsync_start),
            int(mode.vsync_end),
            int(mode.vtotal),
            int(mode.vscan),
            int(mode.vrefresh),
            int(mode.flags),
            bytes(mode.name).split(b"\x00", 1)[0],
        )

    except Exception:
        return None


def kmsmodeproofkey(mode):

    key = kmsmodekey(mode)

    if key is None:
        return None

    values = list(key)
    values[-1] = values[-1].decode("ascii", errors="replace")
    return values


def kmsvalidmode(mode):

    try:

        width = int(mode.hdisplay)
        height = int(mode.vdisplay)
        size = width * height * 4

        if width < KMSMINWIDTH or height < KMSMINHEIGHT:
            return False

        if width > KMSMAXWIDTH or height > KMSMAXHEIGHT:
            return False

        if size < 1 or size > KMSMAXBUFFERBYTES:
            return False

        return True

    except Exception:
        return False


def drmpageflip(fd, sequence, seconds, microseconds, userdata):

    global _drmflip, _drmlastflipsequence, _drmlastfliptimestampus

    currentsequence = int(sequence) & 0xFFFFFFFF
    currenttimestampus = (
        max(0, int(seconds)) * 1000000
        + max(0, min(999999, int(microseconds)))
    )
    sequencedelta = 0
    intervalms = 0.0

    if (
        currenttimestampus > 0
        and _drmlastfliptimestampus is not None
        and currenttimestampus > int(_drmlastfliptimestampus)
    ):
        # NVIDIA's DRM callback supplies a useful monotonically increasing
        # timestamp while reporting sequence zero. Cadence is therefore a
        # timestamp property; sequence remains optional diagnostic metadata.
        intervalms = (
            currenttimestampus - int(_drmlastfliptimestampus)
        ) / 1000.0

        if _drmlastflipsequence is not None:
            candidate = (
                currentsequence - int(_drmlastflipsequence)
            ) & 0xFFFFFFFF

            # A small positive modulo delta includes the uint32 wrap case. A
            # large delta means the CRTC sequence restarted or moved
            # backwards.
            if 0 < candidate < 0x80000000:
                sequencedelta = int(candidate)

        # Long gaps normally mean there was no new damage, not a slow active
        # compositor. Retain intervals through six refresh periods so 30/20/
        # 15/10 fps faults remain visible while idle desktops do not distort
        # the active presentation rate.
        activeceilingms = max(100.0, float(_gpuframebudgetms) * 6.0)
        if 0.0 < intervalms <= activeceilingms:
            _gpupresentationhistory.append(float(intervalms))
            if len(_gpupresentationhistory) > GPUFRAMEHISTORYCAP:
                del _gpupresentationhistory[
                    0:len(_gpupresentationhistory) - GPUFRAMEHISTORYCAP
                ]

    _gputelemetry["page_flip_sequence"] = currentsequence
    _gputelemetry["page_flip_timestamp_us"] = currenttimestampus
    _gputelemetry["page_flip_sequence_delta"] = sequencedelta
    _gputelemetry["page_flip_interval_ms"] = round(intervalms, 3)
    _drmlastflipsequence = currentsequence
    _drmlastfliptimestampus = (
        currenttimestampus if currenttimestampus > 0 else None
    )

    _drmflip = False


def _kmsresetpresentationcadence():

    global _drmlastflipsequence, _drmlastfliptimestampus

    _drmlastflipsequence = None
    _drmlastfliptimestampus = None
    _gpupresentationhistory.clear()
    _gputelemetry["page_flip_sequence"] = 0
    _gputelemetry["page_flip_timestamp_us"] = 0
    _gputelemetry["page_flip_sequence_delta"] = 0
    _gputelemetry["page_flip_interval_ms"] = 0.0


def kmspresentationfd():

    if _backend != "opengl" or _drmfd is None:
        return None

    return int(_drmfd)


def kmsseteventdriven(enabled=True):

    global _drmeventdriven

    _drmeventdriven = bool(enabled and kmspresentationfd() is not None)
    return bool(_drmeventdriven)


def _gpurecordkmsstage(name, started):

    elapsed = max(
        0.0,
        (time.monotonic_ns() - int(started)) / 1000000.0,
    )
    sampleskey = f"{name}_samples"
    lastkey = f"{name}_ms"
    averagekey = f"average_{name}_ms"
    maximumkey = f"maximum_{name}_ms"
    samples = int(_gputelemetry.get(sampleskey, 0)) + 1
    previous = float(_gputelemetry.get(averagekey, 0.0))
    _gputelemetry[sampleskey] = samples
    _gputelemetry[lastkey] = round(elapsed, 3)
    _gputelemetry[averagekey] = round(
        ((previous * max(0, samples - 1)) + elapsed) / samples,
        3,
    )
    _gputelemetry[maximumkey] = round(
        max(float(_gputelemetry.get(maximumkey, 0.0)), elapsed),
        3,
    )
    return elapsed


def kmspresentationpending():

    state = (
        bool(_drmflip),
        bool(_drmpendingbo),
        bool(_drmpendingsurface),
        bool(_drmpendingfb),
    )

    if any(state) and not all(state):
        raise RuntimeError(
            "inconsistent DRM page-flip ownership state "
            f"flip={state[0]} bo={state[1]} surface={state[2]} fb={state[3]}"
        )

    return all(state)


def kmspresentationage():

    if not kmspresentationpending() or not _drmpendingstarted:
        return 0.0

    return max(
        0.0,
        (time.monotonic_ns() - int(_drmpendingstarted)) / 1000000000.0,
    )


def _kmsrecordpresentationtimeout(elapsed, blocking=True):

    elapsed = max(0.0, float(elapsed))
    _gputelemetry["page_flip_timeouts"] += 1
    _gputelemetry["page_flip_timeout_age_ms"] = round(elapsed, 3)
    _gputelemetry["maximum_page_flip_timeout_age_ms"] = round(
        max(
            float(_gputelemetry["maximum_page_flip_timeout_age_ms"]),
            elapsed,
        ),
        3,
    )

    if blocking:
        _gputelemetry["blocking_page_flip_wait_ms"] = round(elapsed, 3)
        _gputelemetry["maximum_blocking_page_flip_wait_ms"] = round(
            max(
                float(_gputelemetry["maximum_blocking_page_flip_wait_ms"]),
                elapsed,
            ),
            3,
        )
    log(
        "> graphics DRM page flip completion timed out; "
        "GPU owner replacement required"
    )


def kmspresentationstalled(timeout=1.0):

    if not kmspresentationpending():
        return False

    age = kmspresentationage()

    if age < max(0.0, float(timeout)):
        return False

    _kmsrecordpresentationtimeout(age * 1000.0, blocking=False)
    return True


def _kmsreleasebuffer(framebuffer, surface, bo):

    try:

        if _drmfd is not None and framebuffer:
            _drm.drmModeRmFB(_drmfd, int(framebuffer))

    except Exception as error:
        log(f"> graphics DRM framebuffer release failed {error}")

    try:

        if bo:
            _gbm.gbm_surface_release_buffer(surface or _gbmsurface, bo)

    except Exception as error:
        log(f"> graphics GBM buffer release failed {error}")


def _kmsreplacecurrent(bo, surface, framebuffer):

    global _gbmbo, _gbmbosurface, _gbmfb

    oldbo = _gbmbo
    oldsurface = _gbmbosurface
    oldframebuffer = _gbmfb
    _gbmbo = bo
    _gbmbosurface = surface
    _gbmfb = int(framebuffer)
    _kmsreleasebuffer(oldframebuffer, oldsurface, oldbo)
    resetdirty()


def _kmscommitpendingflip():

    global _drmpendingbo, _drmpendingsurface, _drmpendingfb, _drmpendingstarted

    if not _drmpendingbo or not _drmpendingfb:
        return False

    bo = _drmpendingbo
    surface = _drmpendingsurface
    framebuffer = _drmpendingfb
    started = _drmpendingstarted
    _drmpendingbo = None
    _drmpendingsurface = None
    _drmpendingfb = 0
    _drmpendingstarted = 0
    _kmsreplacecurrent(bo, surface, framebuffer)

    elapsed = max(0.0, (time.monotonic_ns() - int(started)) / 1000000.0) if started else 0.0
    completed = int(_gputelemetry["page_flips"]) + 1
    _gputelemetry["page_flips"] = completed
    _gputelemetry["page_flip_ms"] = round(elapsed, 3)
    _gputelemetry["average_page_flip_ms"] = round(
        (
            float(_gputelemetry["average_page_flip_ms"]) * max(0, completed - 1)
            + elapsed
        )
        / completed,
        3,
    )
    _gputelemetry["maximum_page_flip_ms"] = round(
        max(float(_gputelemetry["maximum_page_flip_ms"]), elapsed),
        3,
    )
    return True


def kmshandlepresentationevent():

    global _drmflip

    if _drmfd is None or not _drmflip:
        return False

    callbacktype = ctypes.CFUNCTYPE(
        None,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
    )
    callback = callbacktype(drmpageflip)
    context = drmEventContext()
    context.version = 2
    context.page_flip_handler = ctypes.cast(callback, ctypes.c_void_p).value
    result = _drm.drmHandleEvent(_drmfd, ctypes.byref(context))

    if result != 0:
        error = ctypes.get_errno()
        kmsraise(error, "drmHandleEvent failed")

    if _drmflip:
        return False

    committed = _kmscommitpendingflip()
    _eglapplydeferredkmspresentation()
    return committed


def kmswaitflip(timeout=1.0, waitpulse=None, pulseinterval=0.002):

    if not _drmflip:
        return not bool(_drmpendingbo or _drmpendingfb)

    started = time.monotonic()
    deadline = started + max(0.0, float(timeout))
    interval = max(0.0005, min(0.02, float(pulseinterval)))
    _gputelemetry["page_flip_waits"] += 1

    while _drmflip:

        remaining = deadline - time.monotonic()

        if remaining <= 0.0:
            elapsed = (time.monotonic() - started) * 1000.0
            # A missing completion event is not evidence that the submitted
            # framebuffer reached scan-out.  In particular, forcing the
            # pending FB with drmModeSetCrtc after an NVK render hang promoted
            # an unconfirmed buffer, left the original event outstanding, and
            # allowed WindowServer to publish a false presentation receipt.
            # Keep the pending BO owned until kmsclose() tears down this GPU
            # owner, and require the supervisor to start with a fresh device.
            _kmsrecordpresentationtimeout(elapsed)
            return False

        readable, writable, exceptional = select.select(
            [_drmfd],
            [],
            [],
            min(interval, remaining),
        )

        if readable:
            kmshandlepresentationevent()

        if callable(waitpulse):
            waitpulse()

    elapsed = (time.monotonic() - started) * 1000.0
    _gputelemetry["blocking_page_flip_wait_ms"] = round(elapsed, 3)
    _gputelemetry["maximum_blocking_page_flip_wait_ms"] = round(
        max(float(_gputelemetry["maximum_blocking_page_flip_wait_ms"]), elapsed),
        3,
    )
    return not bool(_drmpendingbo or _drmpendingfb)


def packbgra(color):

    try:
        r, g, b = color
    except Exception:
        value = int(color)
        r = (value >> 16) & 0xFF
        g = (value >> 8) & 0xFF
        b = value & 0xFF

    return bytes((int(b) & 0xFF, int(g) & 0xFF, int(r) & 0xFF, 0xFF))


def openglpreparepresent():

    global _glprogram, _gltexture

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; varying vec2 texturecoord; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); texturecoord = texcoord; }"
    )
    fragmentsource = (
        "precision mediump float; uniform sampler2D canvas; uniform float displaybrightness; "
        "uniform float displaycontrast; uniform float displaysaturation; uniform vec3 displaychannels; varying vec2 texturecoord; "
        "void main() { vec4 colour = texture2D(canvas, texturecoord).bgra; "
        "float luminance = dot(colour.rgb, vec3(0.299, 0.587, 0.114)); "
        "colour.rgb = mix(vec3(luminance), colour.rgb, displaysaturation); "
        "colour.rgb = ((colour.rgb - vec3(0.5)) * displaycontrast) + vec3(0.5); "
        "colour.rgb = clamp(colour.rgb * displaybrightness * displaychannels, 0.0, 1.0); gl_FragColor = colour; }"
    )
    _glprogram = openglprogram(vertexsource, fragmentsource)
    texture = ctypes.c_uint()
    _gles.glGenTextures(1, ctypes.byref(texture))
    _gltexture = int(texture.value)

    if _gltexture == 0:
        raise RuntimeError("glGenTextures failed")

    _gles.glActiveTexture(GL_TEXTURE0)
    _gles.glBindTexture(GL_TEXTURE_2D, _gltexture)
    _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    _gles.glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
    _gles.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, _xres, _yres, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)


def openglreleasepresent():

    global _glprogram, _gltexture

    try:

        if _gles is not None and _gltexture:
            texture = ctypes.c_uint(_gltexture)
            _gles.glDeleteTextures(1, ctypes.byref(texture))

        if _gles is not None and _glprogram:
            _gles.glDeleteProgram(_glprogram)

    except Exception:
        pass

    _glprogram = 0
    _gltexture = 0


def gpuapi():

    video = gpuvideoavailable()
    videobasis = (
        "egl-extension"
        if "EGL_EXT_image_dma_buf_import" in _eglextensions
        else (
            "certified-nvidia-entry-points"
            if video
            and _openglprovider == "nvidia"
            and not _eglextensionsqueried
            else "unavailable"
        )
    )
    return {
        "version": GPUAPIVERSION,
        "available": gpuavailable(),
        "managed_resources": True,
        "raw_shaders": False,
        "maximum_textures": GPUMAXTEXTURES,
        "maximum_texture_bytes": GPUMAXTEXTUREBYTES,
        "features": [
            "textures",
            "rectangles",
            "partial_uploads",
            "clipping",
            "alpha_blending",
            "opaque_surfaces",
            "per_pixel_alpha",
            "scaling",
            "shadows",
            "images",
            "text",
            "frame_percentiles",
            "persistent_composition",
            "damage_regions",
            "atomic_scenes",
            "managed_only_surfaces",
            "quad_batching",
            "persistent_vertex_buffer",
            "glyph_atlases",
            "retained_scene_patches",
            "scene_groups",
            "scene_transforms",
            "rounded_rectangles",
            "gradients",
            "offscreen_layers",
            "backdrop_blur",
            "controlled_color_effects",
            "controlled_scene_api",
            "controlled_3d_scenes",
            "depth_buffered_meshes",
            "perspective_cameras",
            "orthographic_cameras",
            "directional_lighting",
            "server_driven_3d_animation",
            "analytic_line_antialiasing",
            "analytic_wireframe_antialiasing",
            "controlled_3d_supersampling",
            *(["dma_buf_video_surfaces", "timestamped_video_frames"] if video else []),
        ],
        "video_surfaces": {
            "available": bool(video),
            "transport": "dma_buf",
            "zero_copy": bool(video),
            "capability_basis": videobasis,
            "maximum_in_flight": 16,
        },
    }


def managedstate(cpu=False):

    return {
        "capabilities": {},
        "available": False,
        "active": False,
        "pending": False,
        "pending_at": 0.0,
        "need_submit": False,
        "cpu": bool(cpu),
        "strict_gpu": False,
        "batch": False,
        "command_limit": 0,
        "text_limit": 1024,
        "damage_limit": 64,
        "damage": [],
        "failure": "",
        "errors": 0,
        "frames": 0,
        "maximum_commands": 0,
        "last_commands": 0,
        "winid": None,
        "managed_only": False,
        "scene": [],
        "pending_scene": None,
        "pending_patch": False,
        "generation": 0,
        "submitted_generation": 0,
        "pending_generation": 0,
        "pending_clear_generation": 0,
        "patches": 0,
        "presented": False,
        "presentation_frame_sequence": 0,
        "presentation_reason": "",
    }


def managedconfigure(state, capabilities, required=("rectangle", "text"), cpu=None):

    if not isinstance(state, dict):
        raise TypeError("managed graphics state must be a dictionary")

    if cpu is not None:
        state["cpu"] = bool(cpu)

    caps = capabilities if isinstance(capabilities, dict) else {}
    state["capabilities"] = dict(caps)
    state["strict_gpu"] = False
    state["active"] = False
    state["pending"] = False
    state["pending_at"] = 0.0
    state["need_submit"] = False
    state["damage"] = []
    state["failure"] = ""
    state["winid"] = None
    state["managed_only"] = False
    state["scene"] = []
    state["pending_scene"] = None
    state["pending_patch"] = False
    state["generation"] = 0
    state["submitted_generation"] = 0
    state["pending_generation"] = 0
    state["pending_clear_generation"] = 0
    state["patches"] = 0
    state["presented"] = False
    state["presentation_frame_sequence"] = 0
    state["presentation_reason"] = ""

    try:

        commands = set(str(value) for value in caps.get("commands", []))
        version = int(caps.get("version", 0))
        state["command_limit"] = max(1, int(caps.get("command_limit", 1024)))
        state["text_limit"] = max(1, int(caps.get("text_limit", 1024)))
        state["damage_limit"] = max(1, int(caps.get("damage_limit", 64)))
        state["batch"] = bool(caps.get("atomic_scene", False))
        state["strict_gpu"] = (
            not bool(state.get("cpu", False))
            and version >= 1
            and bool(caps.get("accelerated", False))
            and bool(caps.get("managed_resources", False))
        )
        # Accelerated managed graphics is a one-way rendering contract.  A
        # missing optional command may leave a surface unable to draw, but it
        # must never make that client silently rasterize with the CPU.
        state["available"] = bool(state["strict_gpu"])
        if state["strict_gpu"] and not all(str(value) in commands for value in required):
            state["failure"] = "managed graphics is missing required commands"

    except Exception:

        state["available"] = False
        state["strict_gpu"] = False
        state["batch"] = False
        state["command_limit"] = 0
        state["text_limit"] = 1024
        state["damage_limit"] = 64

    if state["available"]:
        state["need_submit"] = True

    elif state.get("cpu"):
        state["failure"] = "CPU graphics override"

    else:
        state["failure"] = "managed graphics unavailable"

    return bool(state["available"])


def manageddisable(state, reason):

    wasmanaged = bool(state.get("available") or state.get("active") or state.get("pending"))

    if state.get("strict_gpu") and not state.get("cpu"):
        # Keep the last GPU frame and force the next submission to be a full
        # retained scene.  Returning true tells every client that CPU fallback
        # is forbidden while the accelerated managed path remains selected.
        state["available"] = True
        state["active"] = True
        state["pending"] = False
        state["pending_at"] = 0.0
        state["need_submit"] = True
        state["damage"] = []
        state["failure"] = str(reason)
        state["managed_only"] = True
        state["scene"] = []
        state["pending_scene"] = None
        state["pending_patch"] = False
        state["pending_generation"] = 0
        state["pending_clear_generation"] = 0
        state["presented"] = False
        state["presentation_frame_sequence"] = 0
        state["presentation_reason"] = str(reason)
        if wasmanaged:
            state["errors"] = int(state.get("errors", 0)) + 1
        return True

    state["available"] = False
    state["active"] = False
    state["pending"] = False
    state["pending_at"] = 0.0
    state["need_submit"] = False
    state["damage"] = []
    state["failure"] = str(reason)
    state["managed_only"] = False
    state["pending_scene"] = None
    state["pending_patch"] = False
    state["pending_generation"] = 0
    state["pending_clear_generation"] = 0
    state["presented"] = False
    state["presentation_frame_sequence"] = 0
    state["presentation_reason"] = str(reason)

    if wasmanaged:
        state["errors"] = int(state.get("errors", 0)) + 1

    return False


def managedstrict(state):

    return bool(
        isinstance(state, dict)
        and state.get("strict_gpu")
        and not state.get("cpu")
    )


def managedmarkdamage(state, rect, bounds=None):

    try:

        x, y, width, height = [int(value) for value in rect]

        if bounds is not None:

            limitwidth, limitheight = [int(value) for value in bounds]

            if x < 0:
                width += x
                x = 0

            if y < 0:
                height += y
                y = 0

            width = min(width, limitwidth - x)
            height = min(height, limitheight - y)

        if width < 1 or height < 1:
            return False

        incoming = [x, y, width, height]
        damage = list(state.get("damage", []))
        merged = []

        for current in damage:

            cx, cy, cw, ch = [int(value) for value in current]

            if not (x > cx + cw or cx > x + width or y > cy + ch or cy > y + height):

                left = min(x, cx)
                top = min(y, cy)
                right = max(x + width, cx + cw)
                bottom = max(y + height, cy + ch)
                incoming = [left, top, right - left, bottom - top]
                x, y, width, height = incoming

            else:
                merged.append([cx, cy, cw, ch])

        merged.append(incoming)
        limit = max(1, int(state.get("damage_limit", 64)))

        if len(merged) > limit:

            left = min(value[0] for value in merged)
            top = min(value[1] for value in merged)
            right = max(value[0] + value[2] for value in merged)
            bottom = max(value[1] + value[3] for value in merged)
            merged = [[left, top, right - left, bottom - top]]

        state["damage"] = merged
        state["need_submit"] = True
        return True

    except Exception:
        return False


def managedclear(state, sender, winid):

    nextgeneration = max(
        int(state.get("generation", 0)),
        int(state.get("submitted_generation", 0)),
    ) + 1
    state["winid"] = int(winid)
    state["active"] = False
    state["pending"] = False
    state["pending_at"] = 0.0
    state["need_submit"] = bool(state.get("available"))
    state["managed_only"] = False
    state["scene"] = []
    state["pending_scene"] = None
    state["pending_patch"] = False
    state["pending_generation"] = 0
    state["presented"] = False
    state["presentation_frame_sequence"] = 0
    state["presentation_reason"] = "pending clear"

    try:
        sent = bool(sender({"op": "GRAPHICS_CLEAR", "winid": int(winid)}))
    except Exception:
        return False

    if sent:
        state["submitted_generation"] = int(nextgeneration)
        state["pending_clear_generation"] = int(nextgeneration)

    return sent


def managedanimate(state, sender, winid, nodeid, propertyname, target, duration=180, easing="ease_out", start=None):

    if not managedtick(state) or not state.get("active"):
        return False

    capabilities = state.get("capabilities", {}).get("node_animation", {})
    properties = set(str(value) for value in capabilities.get("properties", []))
    easings = set(str(value) for value in capabilities.get("easings", []))
    propertyname = str(propertyname).lower()
    easing = str(easing).lower()

    if propertyname not in properties:
        raise ValueError(f"unsupported managed animation property {propertyname}")

    if easing not in easings:
        raise ValueError(f"unsupported managed animation easing {easing}")

    request = {
        "op": "GRAPHICS_ANIMATE",
        "winid": int(winid),
        "id": str(nodeid),
        "property": propertyname,
        "to": target,
        "duration_ms": max(1, min(int(capabilities.get("duration_limit_ms", 5000)), int(duration))),
        "easing": easing,
    }

    if start is not None:
        request["from"] = start

    return bool(sender(request))


def managedtick(state, timeout=5.0):

    if state.get("pending") and state.get("pending_at"):

        if time.monotonic() - float(state["pending_at"]) > max(0.1, float(timeout)):
            manageddisable(state, "managed graphics commit timed out")

    return bool(state.get("available"))


def managedsubmit(state, sender, winid, commands):

    if not managedtick(state):
        return False

    if state.get("pending") or not state.get("need_submit"):
        return bool(state.get("active"))

    if not isinstance(commands, list) or not commands:
        return manageddisable(state, "managed scene is empty")

    limit = max(1, int(state.get("command_limit", 1)))

    if len(commands) > limit:
        return manageddisable(state, f"managed scene command limit exceeded {len(commands)}/{limit}")

    allowed = set(str(value) for value in state.get("capabilities", {}).get("commands", []))

    for command in commands:

        if not isinstance(command, dict) or str(command.get("kind", "")) not in allowed:
            return manageddisable(state, "managed scene contains an unsupported command")

    damage = [list(value) for value in state.get("damage", [])]
    scene = [dict(command) for command in commands]

    try:

        retained = (
            bool(state.get("active"))
            and bool(state.get("capabilities", {}).get("retained_scene", False))
            and isinstance(state.get("scene"), list)
            and bool(state.get("scene"))
        )

        if retained:

            previous = {}
            current = {}
            order = []

            for index, command in enumerate(state.get("scene", [])):
                nodeid = str(command.get("id", f"legacy:{index}"))[:128]
                value = dict(command)
                value["id"] = nodeid
                previous[nodeid] = value

            for index, command in enumerate(scene):

                value = dict(command)
                nodeid = str(value.get("id", f"legacy:{index}"))[:128]
                value["id"] = nodeid
                current[nodeid] = value
                order.append(nodeid)

            upsert = [value for nodeid, value in current.items() if previous.get(nodeid) != value]
            remove = [nodeid for nodeid in previous if nodeid not in current]

            if not upsert and not remove and order == list(previous) and not damage:

                # A retained caller may poll its presentation path even when
                # neither the scene nor its damage changed.  Keep the local
                # scene current without spending a socket round trip or a GPU
                # compositor frame on that no-op.
                state["scene"] = [current[nodeid] for nodeid in order]
                state["need_submit"] = False
                state["damage"] = []
                return bool(state.get("active"))

            request = {
                "op": "GRAPHICS_PATCH",
                "winid": int(winid),
                "generation": int(state.get("generation", 0)),
                "upsert": upsert,
                "remove": remove,
                "order": order,
            }

            if damage:
                request["damage"] = damage

            if not sender(request):
                return manageddisable(state, "managed scene patch could not be queued")

            scene = [current[nodeid] for nodeid in order]
            state["pending_patch"] = True

        elif state.get("batch"):

            request = {
                "op": "GRAPHICS_SCENE",
                "winid": int(winid),
                "commands": scene,
            }

            if damage:
                request["damage"] = damage

            if not sender(request):
                return manageddisable(state, "managed scene could not be queued")

        else:

            if not sender({"op": "GRAPHICS_BEGIN", "winid": int(winid)}):
                return manageddisable(state, "managed graphics begin could not be queued")

            for command in commands:

                request = dict(command)
                kind = str(request.pop("kind", ""))
                request["op"] = {
                    "rectangle": "GRAPHICS_RECTANGLE",
                    "image": "GRAPHICS_IMAGE",
                    "text": "GRAPHICS_TEXT",
                }[kind]
                request["winid"] = int(winid)

                if not sender(request):
                    return manageddisable(state, "managed graphics command could not be queued")

            if not sender({"op": "GRAPHICS_COMMIT", "winid": int(winid)}):
                return manageddisable(state, "managed graphics commit could not be queued")

        nextgeneration = max(
            int(state.get("generation", 0)),
            int(state.get("submitted_generation", 0)),
        ) + 1
        state["submitted_generation"] = int(nextgeneration)
        state["pending_generation"] = int(nextgeneration)
        state["pending"] = True
        state["pending_at"] = time.monotonic()
        state["winid"] = int(winid)
        state["pending_scene"] = scene
        state["need_submit"] = False
        state["damage"] = []
        state["presented"] = False
        state["presentation_frame_sequence"] = 0
        state["presentation_reason"] = "pending"
        state["maximum_commands"] = max(int(state.get("maximum_commands", 0)), len(commands))

        if managedstrict(state):
            # Queuing the retained scene transfers ownership of this surface
            # to the GPU path immediately.  GRAPHICS_COMMITTED confirms
            # presentation, but the acknowledgement delay must never be
            # interpreted by a caller as permission to rasterize a competing
            # CPU frame into the shared buffer.
            state["active"] = True
            state["managed_only"] = True

        return bool(state.get("active"))

    except Exception as e:
        return manageddisable(state, f"managed graphics submit failed {e}")


def managedresponse(state, message):

    if not isinstance(message, dict):
        return False

    operation = str(message.get("op", ""))

    try:

        if state.get("winid") is not None and "winid" in message and int(message.get("winid")) != int(state.get("winid")):
            return False

    except Exception:
        return False

    if operation == "GRAPHICS_COMMITTED":

        responsegeneration = max(
            0,
            int(message.get("generation", 0) or 0),
        )
        pendinggeneration = max(
            0,
            int(state.get("pending_generation", 0) or 0),
        )

        # Delayed physical receipts can outlive managedclear(), which is
        # allowed to queue a replacement full scene immediately. An older
        # superseded COMMITTED response must not release or publish that newer
        # pending scene.
        if (
            state.get("pending")
            and responsegeneration > 0
            and pendinggeneration > 0
            and responsegeneration < pendinggeneration
        ):
            return True

        state["pending"] = False
        state["pending_at"] = 0.0
        state["pending_generation"] = 0
        presented = bool(message.get("presented", True))
        state["presented"] = presented
        state["presentation_frame_sequence"] = max(
            0,
            int(message.get("frame_sequence", 0) or 0),
        )
        state["presentation_reason"] = (
            ""
            if presented
            else str(
                message.get(
                    "presentation_reason",
                    "managed scene was not presented",
                )
            )
        )

        if state.get("available") and bool(message.get("accelerated", False)):

            state["active"] = True
            state["frames"] = int(state.get("frames", 0)) + 1
            state["last_commands"] = max(0, int(message.get("count", 0)))
            committedmanagedonly = bool(message.get("managed_only", False))
            state["managed_only"] = bool(
                committedmanagedonly or managedstrict(state)
            )
            state["scene"] = list(state.get("pending_scene") or state.get("scene") or [])
            state["pending_scene"] = None
            state["generation"] = max(0, int(message.get("generation", state.get("generation", 0))))
            state["submitted_generation"] = max(
                int(state.get("submitted_generation", 0)),
                int(state.get("generation", 0)),
            )

            if bool(message.get("patch", False)) or state.get("pending_patch"):
                state["patches"] = int(state.get("patches", 0)) + 1

            state["pending_patch"] = False

            if managedstrict(state) and not committedmanagedonly:
                # A resize may land between submission and commit, leaving an
                # opaque background sized for the previous surface.  Keep GPU
                # ownership and rebuild from a complete scene at the current
                # geometry instead of exposing a CPU fallback opportunity.
                state["scene"] = []
                state["need_submit"] = True
                state["failure"] = "managed scene geometry changed during commit"
                state["presentation_reason"] = state["failure"]
                state["presented"] = False

            return True

        return manageddisable(state, "managed graphics lost acceleration")

    if operation == "GRAPHICS_CLEARED":

        responsegeneration = max(
            0,
            int(message.get("generation", 0) or 0),
        )

        if responsegeneration > 0:
            state["generation"] = max(
                int(state.get("generation", 0)),
                responsegeneration,
            )
            state["submitted_generation"] = max(
                int(state.get("submitted_generation", 0)),
                responsegeneration,
            )

            if responsegeneration >= int(
                state.get("pending_clear_generation", 0)
            ):
                state["pending_clear_generation"] = 0

        state["active"] = bool(managedstrict(state))
        state["managed_only"] = bool(managedstrict(state))
        presented = bool(message.get("presented", True))
        state["presented"] = presented
        state["presentation_frame_sequence"] = max(
            0,
            int(message.get("frame_sequence", 0) or 0),
        )
        state["presentation_reason"] = (
            ""
            if presented
            else str(
                message.get(
                    "presentation_reason",
                    "managed clear was not presented",
                )
            )
        )

        # A resize can queue CLEAR and then submit its rebuilt scene before
        # the clear acknowledgement is read.  Preserve that newer in-flight
        # scene so the following COMMITTED response can publish it.
        if state.get("pending") and state.get("pending_scene"):
            return True

        state["pending"] = False
        state["pending_at"] = 0.0
        state["pending_generation"] = 0
        state["need_submit"] = bool(state.get("available"))
        state["scene"] = []
        state["pending_scene"] = None
        state["pending_patch"] = False
        return True

    if operation == "GRAPHICS_ANIMATING":
        return True

    if operation == "ERROR" and str(message.get("code", "")) == "graphics_animation_failed":
        state["errors"] = int(state.get("errors", 0)) + 1
        state["failure"] = str(message.get("detail", "managed animation failed"))
        return True

    if operation == "ERROR" and str(message.get("code", "")).startswith("graphics_"):
        return manageddisable(state, f"{message.get('code', '')}: {message.get('detail', '')}")

    return False


def managednode(kind, nodeid=None, parent=None, **properties):

    kind = str(kind).lower()
    allowed = {
        "rectangle": {"rect", "color"},
        "rounded_rectangle": {"rect", "color", "radius"},
        "border": {"rect", "color", "width"},
        "line": {"points", "color", "width"},
        "circle": {"cx", "cy", "radius", "color"},
        "gradient": {"rect", "color", "color2", "direction"},
        "image": {"path", "source_width", "source_height", "format", "rect", "revision"},
        "text": {"x", "y", "text", "size", "font", "color"},
        "group": set(),
        "layer": {"rect"},
        "scene3d": {"rect", "camera", "meshes", "ambient", "light", "fog", "postprocess", "antialias"},
    }

    if kind not in allowed:
        raise ValueError(f"unsupported managed graphics node {kind}")

    common = {"clip", "opacity", "translate", "scale", "scroll", "rotation", "effect"}
    unexpected = set(properties) - allowed[kind] - common

    if unexpected:
        raise ValueError(f"unsupported {kind} properties {', '.join(sorted(unexpected))}")

    if str(properties.get("effect", "none")).lower() not in ("none", "grayscale", "invert", "sepia"):
        raise ValueError(f"unsupported managed graphics effect {properties.get('effect')}")

    command = {"kind": kind}

    if nodeid is not None:
        command["id"] = str(nodeid)

    if parent is not None:
        command["parent"] = str(parent)

    command.update(properties)
    return command


def managedscene(*nodes):

    if len(nodes) == 1 and isinstance(nodes[0], (list, tuple)):
        nodes = tuple(nodes[0])

    output = []

    for node in nodes:

        if not isinstance(node, dict) or "kind" not in node:
            raise ValueError("managed scene nodes must be command dictionaries")

        output.append(dict(node))

    return output


def managedgroup(nodeid, parent=None, **properties):

    return managednode("group", nodeid=nodeid, parent=parent, **properties)


def managedlayer(nodeid, rect, parent=None, **properties):

    return managednode("layer", nodeid=nodeid, parent=parent, rect=list(rect), **properties)


def managedrectangle(rect, color, nodeid=None, parent=None, **properties):

    return managednode("rectangle", nodeid=nodeid, parent=parent, rect=list(rect), color=color, **properties)


def managedtext(x, y, text, size, font, color, nodeid=None, parent=None, **properties):

    return managednode(
        "text",
        nodeid=nodeid,
        parent=parent,
        x=int(x),
        y=int(y),
        text=str(text),
        size=int(size),
        font=str(font),
        color=color,
        **properties,
    )


def managedimage(path, source_width, source_height, rect, nodeid=None, parent=None, fmt="BGRA32", **properties):

    return managednode(
        "image",
        nodeid=nodeid,
        parent=parent,
        path=str(path),
        source_width=int(source_width),
        source_height=int(source_height),
        format=str(fmt),
        rect=list(rect),
        **properties,
    )


def managedcamera3d(position=(0.0, 0.0, 6.0), target=(0.0, 0.0, 0.0), up=(0.0, 1.0, 0.0), projection="perspective", fov=50.0, near=0.1, far=100.0, orthographic_size=5.0):

    projection = str(projection).lower()

    if projection not in ("perspective", "orthographic"):
        raise ValueError("controlled 3D camera projection must be perspective or orthographic")

    for name, value in (("position", position), ("target", target), ("up", up)):

        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"controlled 3D camera {name} must contain x, y, and z")

    return {
        "position": [float(value) for value in position],
        "target": [float(value) for value in target],
        "up": [float(value) for value in up],
        "projection": projection,
        "fov": float(fov),
        "near": float(near),
        "far": float(far),
        "orthographic_size": float(orthographic_size),
    }


def managedmaterial3d(color=0xFFFFFF, opacity=1.0, texture=None, texture_width=0, texture_height=0, texture_format="BGRA32", shininess=24.0, unlit=False):

    material = {
        "color": color,
        "opacity": float(opacity),
        "shininess": float(shininess),
        "unlit": bool(unlit),
    }

    if texture is not None:
        material.update({
            "texture": str(texture),
            "texture_width": int(texture_width),
            "texture_height": int(texture_height),
            "texture_format": str(texture_format),
        })

    return material


def managedmesh3d(primitive="cube", position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), rotation_speed=(0.0, 0.0, 0.0), material=None, vertices=None, indices=None, wireframe=False, line_width=1.0, subdivisions=16):

    primitive = str(primitive).lower()

    if primitive not in ("cube", "plane", "sphere", "custom"):
        raise ValueError(f"unsupported controlled 3D primitive {primitive}")

    for name, value in (("position", position), ("rotation", rotation), ("scale", scale), ("rotation_speed", rotation_speed)):

        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"controlled 3D mesh {name} must contain x, y, and z")

    mesh = {
        "primitive": primitive,
        "position": [float(value) for value in position],
        "rotation": [float(value) for value in rotation],
        "scale": [float(value) for value in scale],
        "rotation_speed": [float(value) for value in rotation_speed],
        "material": dict(material or managedmaterial3d()),
        "wireframe": bool(wireframe),
        "line_width": float(line_width),
        "subdivisions": int(subdivisions),
    }

    if primitive == "custom":
        mesh["vertices"] = [list(value) for value in (vertices or [])]
        mesh["indices"] = [int(value) for value in (indices or [])]

    return mesh


def managedscene3d(rect, camera, meshes, nodeid=None, parent=None, ambient=None, light=None, fog=None, postprocess="none", antialias="auto", **properties):

    antialias = str(antialias).lower()

    if antialias not in ("auto", "analytic", "quality"):
        raise ValueError("controlled 3D antialiasing must be auto, analytic, or quality")

    return managednode(
        "scene3d",
        nodeid=nodeid,
        parent=parent,
        rect=list(rect),
        camera=dict(camera),
        meshes=[dict(value) for value in meshes],
        ambient=dict(ambient or {"color": 0xFFFFFF, "intensity": 0.25}),
        light=dict(light or {"direction": [-0.4, -0.8, -0.6], "color": 0xFFFFFF, "intensity": 0.9}),
        fog=dict(fog or {"enabled": False}),
        postprocess=str(postprocess).lower(),
        antialias=antialias,
        **properties,
    )


def gpuavailable():

    return bool(_gles is not None and _eglcontext and _backend in ("opengl", "opengloffscreen"))


def gpumetrics():

    result = dict(_gputelemetry)
    history = sorted(float(value) for value in _gpuframehistory)
    presentationhistory = sorted(
        float(value) for value in _gpupresentationhistory
    )

    if history:
        percentile50 = max(0, min(len(history) - 1, ((len(history) * 50 + 99) // 100) - 1))
        percentile95 = max(0, min(len(history) - 1, ((len(history) * 95 + 99) // 100) - 1))
        percentile99 = max(0, min(len(history) - 1, ((len(history) * 99 + 99) // 100) - 1))
        result["minimum_frame_ms"] = round(history[0], 3)
        result["percentile_50_frame_ms"] = round(history[percentile50], 3)
        result["percentile_95_frame_ms"] = round(history[percentile95], 3)
        result["percentile_99_frame_ms"] = round(history[percentile99], 3)
    else:
        result["minimum_frame_ms"] = 0.0
        result["percentile_50_frame_ms"] = 0.0
        result["percentile_95_frame_ms"] = 0.0
        result["percentile_99_frame_ms"] = 0.0

    frames = max(0, int(result.get("frames", 0)))
    result["frame_budget_ms"] = round(float(_gpuframebudgetms), 3)
    result["frame_samples"] = len(history)
    result["presentation_samples"] = len(presentationhistory)

    if presentationhistory:
        presentation50 = max(
            0,
            min(
                len(presentationhistory) - 1,
                ((len(presentationhistory) * 50 + 99) // 100) - 1,
            ),
        )
        presentation95 = max(
            0,
            min(
                len(presentationhistory) - 1,
                ((len(presentationhistory) * 95 + 99) // 100) - 1,
            ),
        )
        presentation99 = max(
            0,
            min(
                len(presentationhistory) - 1,
                ((len(presentationhistory) * 99 + 99) // 100) - 1,
            ),
        )
        averagepresentation = sum(presentationhistory) / len(
            presentationhistory
        )
        refreshhz = (
            kmsmoderefresh(_drmmode)
            if _drmmode is not None
            else (
                1000.0 / float(_gpuframebudgetms)
                if float(_gpuframebudgetms) > 0.0
                else 0.0
            )
        )
        refreshbudgetms = (
            1000.0 / float(refreshhz) if float(refreshhz) > 0.0 else 0.0
        )
        latepresentations = sum(
            1
            for value in presentationhistory
            if refreshbudgetms > 0.0
            and value > refreshbudgetms * 1.10
        )
        result["minimum_presentation_interval_ms"] = round(
            presentationhistory[0],
            3,
        )
        result["average_presentation_interval_ms"] = round(
            averagepresentation,
            3,
        )
        result["percentile_50_presentation_interval_ms"] = round(
            presentationhistory[presentation50],
            3,
        )
        result["percentile_95_presentation_interval_ms"] = round(
            presentationhistory[presentation95],
            3,
        )
        result["percentile_99_presentation_interval_ms"] = round(
            presentationhistory[presentation99],
            3,
        )
        result["maximum_presentation_interval_ms"] = round(
            presentationhistory[-1],
            3,
        )
        result["presented_fps"] = round(
            1000.0 / averagepresentation
            if averagepresentation > 0.0
            else 0.0,
            3,
        )
        result["presentation_late_refresh_percent"] = round(
            latepresentations * 100.0 / len(presentationhistory),
            3,
        )
    else:
        result["minimum_presentation_interval_ms"] = 0.0
        result["average_presentation_interval_ms"] = 0.0
        result["percentile_50_presentation_interval_ms"] = 0.0
        result["percentile_95_presentation_interval_ms"] = 0.0
        result["percentile_99_presentation_interval_ms"] = 0.0
        result["maximum_presentation_interval_ms"] = 0.0
        result["presented_fps"] = 0.0
        result["presentation_late_refresh_percent"] = 0.0

    result["missed_frame_percent"] = round((int(result.get("missed_frame_budget", 0)) * 100.0 / frames), 3) if frames else 0.0
    result["draw_calls_per_frame"] = round(int(result.get("draw_calls", 0)) / frames, 3) if frames else 0.0
    result["upload_bytes_per_frame"] = round(int(result.get("upload_bytes", 0)) / frames, 3) if frames else 0.0
    result["frame_draw_calls"] = int(_gpuframedraws)
    result["frame_uploads"] = int(_gpuframeuploads)
    result["frame_upload_bytes"] = int(_gpuframeuploadbytes)
    result["frame_damage_regions"] = len(_gpuframeregions)
    result["frame_damage_pixels"] = int(_gpuframedamagepixels)
    result["frame_scissored_pixels"] = int(_gpuframedamagepixels) if _gpuframepersistent else 0
    result["frame_full"] = bool(_gpuframefull)
    result["frame_persistent"] = bool(_gpuframepersistent)
    result["frame_persistent_sync"] = bool(_gpuframesyncpersistent)
    result["damage_pixels_per_frame"] = round(int(result.get("damage_pixels", 0)) / frames, 3) if frames else 0.0
    result["scissored_pixels_per_frame"] = round(int(result.get("scissored_pixels", 0)) / frames, 3) if frames else 0.0
    screenpixels = max(1, int(_xres) * int(_yres))
    result["frame_damage_percent"] = round((int(_gpuframedamagepixels) * 100.0) / screenpixels, 3)
    result["texture_count"] = len(_gputextures)
    result["texture_bytes"] = int(_gputexturebytes)
    result["texture_limit"] = int(GPUMAXTEXTURES)
    result["texture_byte_limit"] = int(GPUMAXTEXTUREBYTES)
    result["render_target_count"] = len(_gputargets)
    depthbytes = sum(
        int(_gputextures[handle]["width"]) * int(_gputextures[handle]["height"]) * 2
        for handle in _gputargetdepths
        if handle in _gputextures
    )
    result["depth_buffer_count"] = len(_gputargetdepths)
    result["depth_buffer_bytes"] = int(depthbytes)
    result["managed_gpu_bytes"] = int(_gputexturebytes) + int(depthbytes)
    aatargethandles = {
        int(value.get("handle", 0))
        for value in _gpu3daatargets.values()
        if isinstance(value, dict) and value.get("handle")
    }
    aatargetbytes = sum(
        int(_gputextures[handle]["width"]) * int(_gputextures[handle]["height"]) * 6
        for handle in aatargethandles
        if handle in _gputextures
    )
    result["aa_target_count"] = len(aatargethandles)
    result["aa_target_bytes"] = int(aatargetbytes)
    result["aa_supersample_average_resolve_ms"] = round(
        float(result.get("aa_supersample_resolve_ms", 0.0)) / max(1, int(result.get("aa_supersample_scenes", 0))),
        3,
    )
    profiles = list(_gpuframeprofiles)
    screenpixels = max(1, int(_xres) * int(_yres))

    def profilesummary(values):

        ordered = sorted(float(value.get("ms", 0.0)) for value in values)

        if not ordered:
            return {
                "samples": 0,
                "average_ms": 0.0,
                "percentile_50_ms": 0.0,
                "percentile_95_ms": 0.0,
                "maximum_ms": 0.0,
                "over_budget": 0,
            }

        midpoint = max(0, min(len(ordered) - 1, ((len(ordered) * 50 + 99) // 100) - 1))
        percentile = max(0, min(len(ordered) - 1, ((len(ordered) * 95 + 99) // 100) - 1))
        return {
            "samples": len(ordered),
            "average_ms": round(sum(ordered) / len(ordered), 3),
            "percentile_50_ms": round(ordered[midpoint], 3),
            "percentile_95_ms": round(ordered[percentile], 3),
            "maximum_ms": round(ordered[-1], 3),
            "over_budget": sum(1 for value in ordered if value > float(_gpuframebudgetms)),
        }

    result["frame_profiles"] = {
        "steady_partial": profilesummary([
            value for value in profiles
            if bool(value.get("persistent"))
            and not bool(value.get("full"))
            and int(value.get("uploads", 0)) == 0
            and int(value.get("damage_pixels", 0)) <= int(screenpixels * 0.05)
        ]),
        "upload": profilesummary([value for value in profiles if int(value.get("uploads", 0)) > 0]),
        "full": profilesummary([value for value in profiles if bool(value.get("full"))]),
        "high_draw": profilesummary([value for value in profiles if int(value.get("draw_calls", 0)) > 32]),
    }
    result["worst_frame_profiles"] = sorted(
        [dict(value) for value in profiles],
        key=lambda value: float(value.get("ms", 0.0)),
        reverse=True,
    )[:12]
    result["recent_frames"] = [
        {
            "sequence": int(value.get("sequence", 0)),
            "ms": round(float(value.get("ms", 0.0)), 3),
            "render_ms": round(float(value.get("render_ms", value.get("ms", 0.0))), 3),
            "draw_calls": int(value.get("draw_calls", 0)),
            "uploads": int(value.get("uploads", 0)),
            "damage_pixels": int(value.get("damage_pixels", 0)),
            "full": bool(value.get("full", False)),
            "persistent": bool(value.get("persistent", False)),
        }
        for value in profiles
    ]
    return result


def gpusetframebudget(milliseconds):

    global _gpuframebudgetms

    _gpuframebudgetms = max(1.0, min(1000.0, float(milliseconds)))
    return float(_gpuframebudgetms)


def gpuinitialise():

    global _gpuprogram

    if _gpuprogram:
        return True

    if not gpuavailable():
        return False

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; attribute vec4 vertexcolor; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); texturecoord = texcoord; drawcolor = vertexcolor; }"
    )
    fragmentsource = (
        "precision mediump float; uniform sampler2D surface; "
        "uniform float texturemode; uniform float swizzle; uniform float texturealpha; uniform float textmode; uniform float shadowmode; uniform float unpremultiply; uniform float premultiplied; "
        "uniform float roundedmode; uniform float cornerradius; uniform vec2 shapesize; "
        "uniform float displayadjust; uniform float displaybrightness; uniform float displaycontrast; uniform float displaysaturation; uniform vec3 displaychannels; "
        "uniform float opacity; varying vec2 texturecoord; varying vec4 drawcolor; void main() { "
        "vec4 colour = drawcolor; "
        "if (shadowmode > 0.5) { "
        "vec2 edge = abs(texturecoord - vec2(0.5, 0.56)) * 2.0; "
        "float fade = 1.0 - smoothstep(0.52, 1.0, max(edge.x, edge.y)); "
        "fade *= fade; "
        "colour = vec4(drawcolor.rgb, drawcolor.a * fade); "
        "} else if (texturemode > 0.5) { "
        "vec4 sampled = texture2D(surface, texturecoord); "
        "sampled = mix(sampled, sampled.bgra, step(0.5, swizzle)); "
        "sampled.a = mix(1.0, sampled.a, step(0.5, texturealpha)); "
        "if (textmode > 0.5) { float coverage = sampled.a; float exponent = 0.5555556; "
        "float lightcoverage = pow(coverage, exponent); float darkcoverage = 1.0 - pow(1.0 - coverage, exponent); "
        "float polarity = step(0.5, dot(drawcolor.rgb, vec3(0.299, 0.587, 0.114))); sampled.a = mix(darkcoverage, lightcoverage, polarity); } "
        "if (unpremultiply > 0.5 && sampled.a > 0.0001) { sampled.rgb /= sampled.a; } "
        "colour = sampled * drawcolor; if (premultiplied > 0.5) { colour.rgb *= drawcolor.a; } "
        "} "
        "if (roundedmode > 0.5) { "
        "vec2 halfsize = shapesize * 0.5; vec2 point = abs((texturecoord - vec2(0.5)) * shapesize); "
        "vec2 delta = max(point - (halfsize - vec2(cornerradius)), vec2(0.0)); "
        "float distance = length(delta) - cornerradius; "
        "float coverage = 1.0 - smoothstep(-0.75, 0.75, distance); colour.a *= coverage; "
        "} "
        "if (displayadjust > 0.5) { float luminance = dot(colour.rgb, vec3(0.299, 0.587, 0.114)); "
        "colour.rgb = mix(vec3(luminance), colour.rgb, displaysaturation); "
        "colour.rgb = ((colour.rgb - vec3(0.5)) * displaycontrast) + vec3(0.5); "
        "colour.rgb = clamp(colour.rgb * displaybrightness * displaychannels, 0.0, 1.0); } "
        "gl_FragColor = vec4(colour.rgb, colour.a * opacity); }"
    )
    _gpuprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpuprogram)


def gpuvideoinitialise():

    global _gpuvideoprogram, _gpuvideoplanarprogram

    if _gpuvideoprogram and _gpuvideoplanarprogram:
        return True

    if not gpuinitialise() or not gpuvideoavailable():
        return False

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; attribute vec4 vertexcolor; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); "
        "texturecoord = texcoord; drawcolor = vertexcolor; }"
    )
    fragmentsource = (
        "#extension GL_OES_EGL_image_external : require\n"
        "precision mediump float; uniform samplerExternalOES videosurface; "
        "uniform float opacity; uniform float videoheight; uniform float deinterlace; "
        "uniform float hdrtransfer; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "vec3 t1tonemap(vec3 signal) { "
        "if (hdrtransfer < 15.5 || (hdrtransfer > 16.5 && hdrtransfer < 17.5) || "
        "hdrtransfer > 18.5) return signal; vec3 linear; "
        "if (hdrtransfer < 17.0) { "
        "vec3 power = pow(max(signal, vec3(0.0)), vec3(1.0 / 78.84375)); "
        "linear = pow(max(power - vec3(0.8359375), vec3(0.0)) / "
        "max(vec3(18.8515625) - vec3(18.6875) * power, vec3(0.00001)), "
        "vec3(1.0 / 0.1593017578)) * 100.0; "
        "} else { vec3 low = signal * signal / 3.0; "
        "vec3 high = (exp((signal - vec3(0.55991073)) / 0.17883277) + "
        "vec3(0.28466892)) / 12.0; "
        "linear = mix(low, high, step(vec3(0.5), signal)) * 10.0; } "
        "vec3 mapped = linear / (vec3(1.0) + linear); "
        "return pow(clamp(mapped, 0.0, 1.0), vec3(1.0 / 2.2)); } "
        "void main() { vec4 colour = texture2D(videosurface, texturecoord); "
        "if (deinterlace > 0.5 && videoheight > 1.0) { "
        "float line = floor(texturecoord.y * videoheight); "
        "float direction = mix(-1.0, 1.0, step(0.5, mod(line, 2.0))); "
        "vec2 neighbour = clamp(texturecoord + vec2(0.0, direction / videoheight), vec2(0.0), vec2(1.0)); "
        "colour = mix(colour, texture2D(videosurface, neighbour), 0.5); } "
        "colour.rgb = t1tonemap(colour.rgb); "
        "gl_FragColor = vec4(colour.rgb * drawcolor.rgb, "
        "colour.a * drawcolor.a * opacity); }"
    )
    _gpuvideoprogram = openglprogram(vertexsource, fragmentsource)
    planarfragment = (
        "#extension GL_OES_EGL_image_external : require\n"
        "precision mediump float; uniform samplerExternalOES ysurface; "
        "uniform samplerExternalOES uvsurface; uniform float opacity; "
        "uniform float videoheight; uniform float deinterlace; "
        "uniform float hdrtransfer; "
        "uniform vec3 yuvoffset; uniform vec3 redrow; "
        "uniform vec3 greenrow; uniform vec3 bluerow; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "vec3 t1tonemap(vec3 signal) { "
        "if (hdrtransfer < 15.5 || (hdrtransfer > 16.5 && hdrtransfer < 17.5) || "
        "hdrtransfer > 18.5) return signal; vec3 linear; "
        "if (hdrtransfer < 17.0) { "
        "vec3 power = pow(max(signal, vec3(0.0)), vec3(1.0 / 78.84375)); "
        "linear = pow(max(power - vec3(0.8359375), vec3(0.0)) / "
        "max(vec3(18.8515625) - vec3(18.6875) * power, vec3(0.00001)), "
        "vec3(1.0 / 0.1593017578)) * 100.0; "
        "} else { vec3 low = signal * signal / 3.0; "
        "vec3 high = (exp((signal - vec3(0.55991073)) / 0.17883277) + "
        "vec3(0.28466892)) / 12.0; "
        "linear = mix(low, high, step(vec3(0.5), signal)) * 10.0; } "
        "vec3 mapped = linear / (vec3(1.0) + linear); "
        "return pow(clamp(mapped, 0.0, 1.0), vec3(1.0 / 2.2)); } "
        "void main() { vec2 coordinate = texturecoord; "
        "float y = texture2D(ysurface, coordinate).r; "
        "vec2 uv = texture2D(uvsurface, coordinate).rg; "
        "if (deinterlace > 0.5 && videoheight > 1.0) { "
        "float line = floor(coordinate.y * videoheight); "
        "float direction = mix(-1.0, 1.0, step(0.5, mod(line, 2.0))); "
        "vec2 neighbour = clamp(coordinate + vec2(0.0, direction / videoheight), "
        "vec2(0.0), vec2(1.0)); "
        "y = mix(y, texture2D(ysurface, neighbour).r, 0.5); "
        "uv = mix(uv, texture2D(uvsurface, neighbour).rg, 0.5); } "
        "vec3 yuv = vec3(y, uv) - yuvoffset; "
        "vec3 colour = vec3(dot(redrow, yuv), dot(greenrow, yuv), dot(bluerow, yuv)); "
        "colour = t1tonemap(colour); "
        "gl_FragColor = vec4(clamp(colour, 0.0, 1.0) * drawcolor.rgb, "
        "drawcolor.a * opacity); }"
    )
    _gpuvideoplanarprogram = openglprogram(vertexsource, planarfragment)
    return bool(_gpuvideoprogram and _gpuvideoplanarprogram)


def gpuvideoavailable():

    global _glextensions

    if (
        _backend != "opengl"
        or _egldisplay is None
        or _eglcreateimage is None
        or _egldestroyimage is None
        or _glimage_target_texture is None
    ):
        return False

    # Never turn a capability-reporting call into a vendor-driver cold-boot
    # barrier. NVIDIA deliberately skips its early extension-string query,
    # but the pinned provider exposes the complete DMA-BUF import entry-point
    # set through eglGetProcAddress. Accept that certified function path and
    # let the later format query plus real EGLImage import validate it.
    extensionadvertised = (
        "EGL_EXT_image_dma_buf_import" in _eglextensions
    )
    nvidiafunctionpath = bool(
        _openglprovider == "nvidia"
        and not _eglextensionsqueried
        and "nvidia" in str(_eglvendor or "").casefold()
        and _eglquerydmabufformats is not None
    )

    if not extensionadvertised and not nvidiafunctionpath:
        return False

    try:
        if _glextensions is None:
            extensionvalue = _gles.glGetString(GL_EXTENSIONS)
            _glextensions = frozenset(
                extensionvalue.decode("ascii", errors="ignore").split()
                if extensionvalue
                else ()
            )

        return "GL_OES_EGL_image_external" in _glextensions
    except Exception:
        return False


def gpupresentationbufferavailable():

    return bool(gpuvideoavailable())


def gpupresentationbuffercreate(descriptor, fds):

    descriptor = dict(descriptor or {})
    objects = descriptor.get("objects", [])
    layers = descriptor.get("layers", [])

    if str(descriptor.get("transport", "")) != "rgb-gbm-dmabuf-v1":
        raise ValueError("Chromium presentation transport is not RGB GBM DMA-BUF v1")

    if str(descriptor.get("sync_mode", "")) != "glfinish-producer-consumer":
        raise ValueError("Chromium presentation must declare the GL finish ownership mode")

    if str(descriptor.get("origin", "")) != "bottom-left":
        raise ValueError("Chromium presentation has an unsupported image origin")

    if len(fds) != 1 or len(objects) != 1 or len(layers) != 1:
        raise ValueError("Chromium presentation must contain one RGB DMA-BUF object")

    layer = layers[0] if isinstance(layers[0], dict) else {}
    planes = layer.get("planes", [])
    fourcc = int(layer.get("fourcc", 0))
    width = int(descriptor.get("width", 0))
    height = int(descriptor.get("height", 0))
    imagewidth = int(layer.get("width", 0))
    imageheight = int(layer.get("height", 0))
    item = objects[0] if isinstance(objects[0], dict) else {}
    modifier = int(item.get("modifier", DRM_FORMAT_MOD_INVALID))
    plane = planes[0] if isinstance(planes, list) and len(planes) == 1 else {}
    offset = int(plane.get("offset", -1)) if isinstance(plane, dict) else -1
    pitch = int(plane.get("pitch", 0)) if isinstance(plane, dict) else 0
    objectsize = int(item.get("size", 0))

    if (
        fourcc not in (DRM_FORMAT_XRGB8888, DRM_FORMAT_ARGB8888)
        or len(planes) != 1
        or not isinstance(planes[0], dict)
        or int(planes[0].get("object", -1)) != 0
        or width < 1
        or height < 1
        or imagewidth != width
        or imageheight != height
        or modifier == DRM_FORMAT_MOD_INVALID
        or offset != 0
        or pitch < width * 4
        or objectsize < pitch * height
    ):
        raise ValueError(
            "Chromium presentation is not a bounded single-plane RGB buffer"
        )

    handle = gpuvideosurfacecreate(descriptor, fds)
    resource = _gpuvideosurfaces.get(int(handle))

    if not isinstance(resource, dict):
        raise RuntimeError("Chromium presentation DMA-BUF import disappeared")

    resource.update({
        "presentation_dmabuf": True,
        "origin": "bottom-left",
        # The protocol origin describes Chromium's OpenGL producer
        # coordinate system.  EGL_LINUX_DMA_BUF_EXT still exposes the DRM
        # image in plane row order, whose first row is the top of the image.
        # Keep those two concepts separate so the retained-target copy does
        # not invert the complete browser frame.
        "row_order": "top-left",
        "sync_mode": "glfinish-producer-consumer",
        "generation": int(descriptor.get("generation", 0)),
    })
    _gputelemetry["presentation_dmabuf_imports"] += 1
    return int(handle)


def gpupresentationbufferrelease(handle):

    resource = _gpuvideosurfaces.get(int(handle))

    if not isinstance(resource, dict) or not resource.get("presentation_dmabuf"):
        raise ValueError("unknown Chromium presentation DMA-BUF surface")

    # Native sync-file export is intentionally not claimed by protocol v1.
    # Finish every consumer read before destroying the EGLImage and returning
    # ownership to Chromium. The producer performs the matching finish before
    # sending each DMA-BUF.
    _gles.glFinish()
    _gputelemetry["presentation_consumer_glfinish"] += 1
    released = gpuvideosurfacedestroy(handle, wait=False)

    if released:
        _gputelemetry["presentation_dmabuf_releases"] += 1

    return bool(released)


def _gpuvideomodifierimportavailable():
    """Return whether EGL can consume explicit DMA-BUF modifier attributes."""
    if "EGL_EXT_image_dma_buf_import_modifiers" in _eglextensions:
        return True

    # NVIDIA's cold-start path intentionally does not enumerate the EGL
    # extension string because that vendor call can hang before the desktop is
    # visible. The pinned provider is instead certified by its resolved
    # modifier-query entry point. This is the same measured exception used by
    # gpuvideoavailable(); do not reject a real tiled NVDEC surface merely
    # because the unsafe string query was skipped.
    return bool(
        _openglprovider == "nvidia"
        and not _eglextensionsqueried
        and "nvidia" in str(_eglvendor or "").casefold()
        and _eglquerydmabufmodifiers is not None
    )


def gpuvideoimportcapabilities(include_modifiers=True, probe=True):

    global _gpuvideoimportcapabilitiescache

    if not probe and not isinstance(_gpuvideoimportcapabilitiescache, dict):
        return {
            "available": bool(gpuvideoavailable()),
            "formats": [],
            "modifier_query": bool(_eglquerydmabufmodifiers is not None),
            "deferred": True,
        }

    if not isinstance(_gpuvideoimportcapabilitiescache, dict):

        result = {
            "available": bool(gpuvideoavailable()),
            "formats": [],
            "modifier_query": bool(_eglquerydmabufmodifiers is not None),
            "_formats_complete": False,
        }

        if result["available"] and _eglquerydmabufformats is not None:

            try:
                count = ctypes.c_int()

                if (
                    _eglquerydmabufformats(
                        _egldisplay,
                        0,
                        None,
                        ctypes.byref(count),
                    )
                    and 0 < count.value <= 4096
                ):
                    values = (ctypes.c_int * count.value)()
                    written = ctypes.c_int()

                    if _eglquerydmabufformats(
                        _egldisplay,
                        count.value,
                        values,
                        ctypes.byref(written),
                    ):
                        result["formats"] = [
                            {
                                "fourcc": int(values[index]) & 0xFFFFFFFF,
                                "modifiers": [],
                                "_modifiers_queried": False,
                            }
                            for index in range(max(
                                0,
                                min(count.value, written.value),
                            ))
                        ]
                        result["_formats_complete"] = True

            except Exception as error:
                result["error"] = str(error)

        _gpuvideoimportcapabilitiescache = result

    if include_modifiers:
        for entry in _gpuvideoimportcapabilitiescache.get("formats", []):
            _gpuvideoformatmodifiers(int(entry.get("fourcc", 0)))

    result = {
        key: value
        for key, value in _gpuvideoimportcapabilitiescache.items()
        if not str(key).startswith("_")
    }
    result["deferred"] = not bool(
        _gpuvideoimportcapabilitiescache.get("_formats_complete", False)
    )
    result["formats"] = [
        (
            {
                "fourcc": int(entry.get("fourcc", 0)),
                "modifiers": [
                    dict(item)
                    for item in entry.get("modifiers", [])
                    if isinstance(item, dict)
                ],
            }
            if include_modifiers
            else {
                "fourcc": int(entry.get("fourcc", 0)),
                "modifier_count": (
                    len(entry.get("modifiers", []))
                    if bool(entry.get("_modifiers_queried"))
                    else None
                ),
            }
        )
        for entry in _gpuvideoimportcapabilitiescache.get("formats", [])
    ]
    return result


def _gpuvideoformatmodifiers(fourcc):

    global _gpuvideoimportcapabilitiescache

    if not isinstance(_gpuvideoimportcapabilitiescache, dict):
        _gpuvideoimportcapabilitiescache = {
            "available": bool(gpuvideoavailable()),
            "formats": [],
            "modifier_query": bool(_eglquerydmabufmodifiers is not None),
            "_formats_complete": False,
        }

    entry = next(
        (
            item
            for item in _gpuvideoimportcapabilitiescache.get("formats", [])
            if int(item.get("fourcc", 0)) == int(fourcc)
        ),
        None,
    )

    if entry is None:
        entry = {
            "fourcc": int(fourcc),
            "modifiers": [],
            "_modifiers_queried": False,
        }
        _gpuvideoimportcapabilitiescache["formats"].append(entry)

    if bool(entry.get("_modifiers_queried")):
        return list(entry.get("modifiers", []))

    entry["_modifiers_queried"] = True

    if _eglquerydmabufmodifiers is None:
        return []

    try:
        modifiercount = ctypes.c_int()

        if not _eglquerydmabufmodifiers(
            _egldisplay,
            ctypes.c_int(int(fourcc)).value,
            0,
            None,
            None,
            ctypes.byref(modifiercount),
        ):
            return []

        if modifiercount.value < 1 or modifiercount.value > 4096:
            return []

        modifiers = (ctypes.c_uint64 * modifiercount.value)()
        external = (ctypes.c_uint * modifiercount.value)()
        modifierwritten = ctypes.c_int()

        if not _eglquerydmabufmodifiers(
            _egldisplay,
            ctypes.c_int(int(fourcc)).value,
            modifiercount.value,
            modifiers,
            external,
            ctypes.byref(modifierwritten),
        ):
            return []

        entry["modifiers"] = [
            {
                "modifier": int(modifiers[index]),
                "external_only": bool(external[index]),
            }
            for index in range(max(
                0,
                min(modifiercount.value, modifierwritten.value),
            ))
        ]

    except Exception as error:
        entry["modifier_error"] = str(error)

    return list(entry.get("modifiers", []))


def _gpuvideosigned32(value):

    return ctypes.c_int(int(value) & 0xFFFFFFFF).value


def _gpuvideovalidatedescriptor(descriptor, fds):

    width = int(descriptor.get("width", 0))
    height = int(descriptor.get("height", 0))

    if width < 1 or height < 1 or width > KMSMAXWIDTH or height > KMSMAXHEIGHT:
        raise ValueError("decoded video dimensions exceed the compositor limit")

    objects = descriptor.get("objects", [])
    layers = descriptor.get("layers", [])

    if (
        not isinstance(objects, list)
        or not objects
        or len(objects) > GPUVIDEOMAXOBJECTS
        or len(objects) != len(fds)
    ):
        raise ValueError("decoded video object handles do not match the descriptor")

    if not isinstance(layers, list) or len(layers) not in (1, 2):
        raise ValueError("decoded video must contain one composed layer or two Y/UV layers")

    objectsizes = []

    for item in objects:

        if not isinstance(item, dict):
            raise ValueError("decoded video contains a malformed DMA-BUF object")

        size = int(item.get("size", 0))

        if size < 1 or size > KMSMAXBUFFERBYTES:
            raise ValueError("decoded video DMA-BUF object size is invalid")

        modifier = int(item.get("modifier", DRM_FORMAT_MOD_INVALID))

        if modifier < 0 or modifier > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("decoded video DMA-BUF modifier is invalid")

        objectsizes.append(size)

    capabilities = gpuvideoimportcapabilities(
        include_modifiers=False,
        probe=False,
    )
    capabilityformats = {
        int(entry.get("fourcc", 0)): entry
        for entry in capabilities.get("formats", [])
        if isinstance(entry, dict)
    }

    for layer in layers:

        if not isinstance(layer, dict):
            raise ValueError("decoded video contains a malformed image layer")

        layerwidth = int(layer.get("width", width))
        layerheight = int(layer.get("height", height))
        fourcc = int(layer.get("fourcc", 0))
        planes = layer.get("planes", [])

        if (
            layerwidth < 1
            or layerheight < 1
            or layerwidth > width
            or layerheight > height
            or not fourcc
        ):
            raise ValueError("decoded video image-layer bounds are invalid")

        if not isinstance(planes, list) or not planes or len(planes) > 4:
            raise ValueError("decoded video image-layer plane count is invalid")

        if (
            not bool(capabilities.get("deferred", False))
            and fourcc not in capabilityformats
        ):
            raise ValueError(
                f"decoded video fourcc {fourcc} is not advertised by the EGL importer"
            )

        acceptedmodifiers = None

        for plane in planes:

            if not isinstance(plane, dict):
                raise ValueError("decoded video contains a malformed image plane")

            objectindex = int(plane.get("object", -1))
            offset = int(plane.get("offset", -1))
            pitch = int(plane.get("pitch", 0))

            if objectindex < 0 or objectindex >= len(objectsizes):
                raise ValueError("decoded video image plane names an invalid object")

            if (
                offset < 0
                or pitch < 1
                or pitch > KMSMAXBUFFERBYTES
                or offset >= objectsizes[objectindex]
                or offset + pitch > objectsizes[objectindex]
            ):
                raise ValueError("decoded video image plane storage is out of bounds")

            modifier = int(
                objects[objectindex].get("modifier", DRM_FORMAT_MOD_INVALID)
            )

            if (
                bool(capabilities.get("modifier_query"))
                and modifier not in (DRM_FORMAT_MOD_INVALID, DRM_FORMAT_MOD_LINEAR)
            ):
                if acceptedmodifiers is None:
                    acceptedmodifiers = {
                        int(item.get("modifier", DRM_FORMAT_MOD_INVALID))
                        for item in _gpuvideoformatmodifiers(fourcc)
                        if isinstance(item, dict)
                    }

                # Some proprietary EGL implementations expose the modifier
                # query entry point yet return an empty list for external-only
                # R8/GR88 video planes. An empty answer is not proof that an
                # explicit eglCreateImageKHR import will fail; let EGL validate
                # that descriptor. A non-empty advertised set remains strict.
                if acceptedmodifiers and modifier not in acceptedmodifiers:
                    raise ValueError(
                        "decoded video DMA-BUF modifier is not advertised for its fourcc"
                    )


def _gpuvideoattributes(
    descriptor,
    fds,
    modifiers=True,
    colour=True,
    layerindex=0,
):

    layers = descriptor.get("layers", [])
    objects = descriptor.get("objects", [])

    if (
        not isinstance(layers, list)
        or not layers
        or len(layers) > 4
        or layerindex < 0
        or layerindex >= len(layers)
    ):
        raise ValueError("video DMA-BUF has an invalid image-layer layout")

    layer = layers[layerindex]
    width = int(layer.get("width", descriptor.get("width", 0)))
    height = int(layer.get("height", descriptor.get("height", 0)))

    if width < 1 or height < 1:
        raise ValueError("video DMA-BUF layer is not bounded")

    planes = layer.get("planes", [])

    if not isinstance(planes, list) or not planes or len(planes) > 4:
        raise ValueError("video DMA-BUF has an invalid plane count")

    if len(fds) != len(objects) or not fds:
        raise ValueError("video DMA-BUF object descriptors do not match received handles")

    attributes = [
        EGL_WIDTH, width,
        EGL_HEIGHT, height,
        EGL_LINUX_DRM_FOURCC_EXT, _gpuvideosigned32(layer.get("fourcc", 0)),
    ]

    for planeindex, plane in enumerate(planes):

        objectindex = int(plane.get("object", -1))

        if objectindex < 0 or objectindex >= len(fds):
            raise ValueError("video DMA-BUF plane names an invalid object")

        fdkey = EGL_DMA_BUF_PLANE0_FD_EXT + planeindex * 3
        offsetkey = EGL_DMA_BUF_PLANE0_OFFSET_EXT + planeindex * 3
        pitchkey = EGL_DMA_BUF_PLANE0_PITCH_EXT + planeindex * 3
        attributes.extend([
            fdkey, int(fds[objectindex]),
            offsetkey, int(plane.get("offset", 0)),
            pitchkey, int(plane.get("pitch", 0)),
        ])

        modifier = int(objects[objectindex].get("modifier", DRM_FORMAT_MOD_INVALID))

        if modifiers and modifier != DRM_FORMAT_MOD_INVALID:
            lowkey = EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT + planeindex * 2
            highkey = EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT + planeindex * 2
            attributes.extend([
                lowkey, _gpuvideosigned32(modifier),
                highkey, _gpuvideosigned32(modifier >> 32),
            ])

    if colour and len(layers) == 1:

        metadata = descriptor.get("color", {})
        space = int(metadata.get("space", 0))
        rangevalue = int(metadata.get("range", 0))

        if space in (5, 6):
            colourspace = EGL_ITU_REC601_EXT
        elif space in (9, 10):
            colourspace = EGL_ITU_REC2020_EXT
        else:
            colourspace = EGL_ITU_REC709_EXT

        attributes.extend([
            EGL_YUV_COLOR_SPACE_HINT_EXT, colourspace,
            EGL_SAMPLE_RANGE_HINT_EXT,
            EGL_YUV_FULL_RANGE_EXT if rangevalue == 2 else EGL_YUV_NARROW_RANGE_EXT,
        ])

    attributes.append(EGL_NONE)
    return (ctypes.c_int * len(attributes))(*attributes)


def gpuvideosurfacecreate(descriptor, fds):

    global _gpuhandle

    if not gpuvideoinitialise():
        raise RuntimeError("OpenGL DMA-BUF video import is unavailable")

    descriptor = dict(descriptor or {})
    fds = [int(value) for value in fds]
    try:
        _gpuvideovalidatedescriptor(descriptor, fds)
    except Exception as error:
        _gputelemetry["video_surface_last_import_failure"] = str(error)
        _gputelemetry["video_surface_import_failures"] += 1
        raise
    layers = descriptor.get("layers", [])

    if not isinstance(layers, list) or not layers or len(layers) > 2:
        _gputelemetry["video_surface_import_failures"] += 1
        _gputelemetry["video_surface_last_import_failure"] = (
            "decoded video must export one composed layer or two Y/UV layers"
        )
        raise RuntimeError(
            "decoded video must export one composed layer or two Y/UV layers"
        )

    images = []
    textures = []
    objects = descriptor.get("objects", [])
    nonlinearmodifier = any(
        int(item.get("modifier", DRM_FORMAT_MOD_INVALID))
        not in (DRM_FORMAT_MOD_INVALID, DRM_FORMAT_MOD_LINEAR)
        for item in objects
        if isinstance(item, dict)
    )
    modifierimportavailable = _gpuvideomodifierimportavailable()

    if nonlinearmodifier and not modifierimportavailable:
        _gputelemetry["video_surface_import_failures"] += 1
        _gputelemetry["video_surface_last_import_failure"] = (
            "decoded video uses a non-linear DMA-BUF modifier that EGL cannot import"
        )
        raise RuntimeError(
            "decoded video uses a non-linear DMA-BUF modifier that EGL cannot import"
        )

    attempts = (
        ((True, True), (True, False))
        if nonlinearmodifier
        else (
            (modifierimportavailable, True),
            (modifierimportavailable, False),
            (False, False),
        )
    )

    try:

        for layerindex in range(len(layers)):

            image = None

            for modifiers, colour in attempts:

                attributes = _gpuvideoattributes(
                    descriptor,
                    fds,
                    modifiers=modifiers,
                    colour=colour,
                    layerindex=layerindex,
                )
                image = _eglcreateimage(
                    _egldisplay,
                    EGL_NO_CONTEXT,
                    EGL_LINUX_DMA_BUF_EXT,
                    None,
                    attributes,
                )

                if image:
                    break

            if not image:
                eglerror = int(_egl.eglGetError()) if _egl is not None else 0
                raise RuntimeError(
                    "eglCreateImageKHR could not import decoded video layer "
                    f"{layerindex} (EGL 0x{eglerror:04x})"
                )

            images.append(image)
            value = ctypes.c_uint()
            _gles.glGenTextures(1, ctypes.byref(value))
            texture = int(value.value)

            if not texture:
                raise RuntimeError(
                    f"glGenTextures failed for decoded video layer {layerindex}"
                )

            textures.append(texture)
            _gles.glActiveTexture(GL_TEXTURE0 + layerindex)
            _gles.glBindTexture(GL_TEXTURE_EXTERNAL_OES, texture)
            _gles.glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            _gles.glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            _gles.glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            _gles.glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            _glimage_target_texture(GL_TEXTURE_EXTERNAL_OES, image)

        _gles.glActiveTexture(GL_TEXTURE0)

        handle = int(_gpuhandle)
        _gpuhandle += 1
        _gpuvideosurfaces[handle] = {
            "image": images[0],
            "texture": textures[0],
            "images": list(images),
            "textures": list(textures),
            "planar": len(images) == 2,
            "width": int(descriptor.get("width", 0)),
            "height": int(descriptor.get("height", 0)),
            "frame": int(descriptor.get("frame", 0)),
            "pts_ns": int(descriptor.get("pts_ns", 0)),
            "format": str(descriptor.get("format", "drm_prime")),
            "color": dict(descriptor.get("color", {})),
            "bit_depth": int(descriptor.get("bit_depth", 0)),
            "export_mode": str(descriptor.get("export_mode", "composed")),
            "gpu_scaled": bool(descriptor.get("gpu_scaled", False)),
            "interlaced": bool(descriptor.get("interlaced", False)),
            "top_field_first": bool(descriptor.get("top_field_first", False)),
        }
        _gputelemetry["video_surface_imports"] += 1
        if len(images) == 2:
            _gputelemetry["video_surface_planar_imports"] += 1
        else:
            _gputelemetry["video_surface_composed_imports"] += 1
        if bool(descriptor.get("gpu_scaled", False)):
            _gputelemetry["video_surface_gpu_scaled_imports"] += 1
        if nonlinearmodifier:
            _gputelemetry["video_surface_modifier_imports"] += 1
        _gputelemetry["video_surface_last_import_failure"] = ""
        return handle

    except Exception as error:

        for texture in textures:

            texturevalue = ctypes.c_uint(int(texture))
            _gles.glDeleteTextures(1, ctypes.byref(texturevalue))

        for image in images:

            _egldestroyimage(_egldisplay, image)

        _gles.glActiveTexture(GL_TEXTURE0)
        _gputelemetry["video_surface_import_failures"] += 1
        _gputelemetry["video_surface_last_import_failure"] = str(error)
        raise


def gpuvideosurfaceinfo(handle):

    resource = _gpuvideosurfaces.get(int(handle))
    return dict(resource) if isinstance(resource, dict) else None


def gpuvideosurfacedestroy(handle, wait=False):

    resource = _gpuvideosurfaces.pop(int(handle), None)

    if resource is None:
        return False

    if wait:
        _gles.glFinish()

    textures = resource.get("textures")

    if not isinstance(textures, list):
        textures = [resource.get("texture", 0)]

    for texture in textures:

        texturevalue = ctypes.c_uint(int(texture or 0))

        if texturevalue.value:
            _gles.glDeleteTextures(1, ctypes.byref(texturevalue))

    images = resource.get("images")

    if not isinstance(images, list):
        images = [resource.get("image")]

    for image in images:

        if image:
            _egldestroyimage(_egldisplay, image)

    _gputelemetry["video_surface_releases"] += 1
    return True


def _gpuvideocolourtransform(resource):

    metadata = resource.get("color", {})
    space = int(metadata.get("space", 0))
    rangevalue = int(metadata.get("range", 0))
    depth = int(resource.get("bit_depth", 0))

    if space in (5, 6):
        rows = (
            (1.0, 0.0, 1.402),
            (1.0, -0.344136, -0.714136),
            (1.0, 1.772, 0.0),
        )
    elif space in (9, 10):
        rows = (
            (1.0, 0.0, 1.4746),
            (1.0, -0.164553, -0.571353),
            (1.0, 1.8814, 0.0),
        )
    else:
        rows = (
            (1.0, 0.0, 1.5748),
            (1.0, -0.187324, -0.468124),
            (1.0, 1.8556, 0.0),
        )

    if rangevalue == 2:
        offset = (0.0, 0.5, 0.5)
        return offset, rows

    if depth >= 12:
        offset = (256.0 / 4095.0, 2048.0 / 4095.0, 2048.0 / 4095.0)
        yscale = 4095.0 / 3504.0
        chromascale = 4095.0 / 3584.0
    elif depth >= 10:
        offset = (64.0 / 1023.0, 512.0 / 1023.0, 512.0 / 1023.0)
        yscale = 1023.0 / 876.0
        chromascale = 1023.0 / 896.0
    else:
        offset = (16.0 / 255.0, 128.0 / 255.0, 128.0 / 255.0)
        yscale = 255.0 / 219.0
        chromascale = 255.0 / 224.0

    transformed = tuple(
        (
            row[0] * yscale,
            row[1] * chromascale,
            row[2] * chromascale,
        )
        for row in rows
    )
    return offset, transformed


def _gpuvideosurfaceverticalcoordinates(resource):

    # EGL DMA-BUF imports are sampled in DRM plane row order.  Chromium's
    # presentation packet records the GL producer origin separately; it does
    # not change the exported plane's row order.  Off-screen render targets
    # receive their required GL framebuffer correction later in
    # gpudrawwindowlayer, after this copy.
    return (
        (1.0, 0.0)
        if str(resource.get("row_order", "top-left")) == "bottom-left"
        else (0.0, 1.0)
    )


def gpudrawvideosurface(handle, x, y, width, height, opacity=1.0, clip=None):

    global _gpuframedraws

    resource = _gpuvideosurfaces.get(int(handle))

    if resource is None:
        _gputelemetry["video_surface_draw_failures"] += 1
        _gputelemetry["video_surface_last_draw_failure"] = "unknown-surface"
        return False

    if not _gpuframeactive:
        _gputelemetry["video_surface_draw_failures"] += 1
        _gputelemetry["video_surface_last_draw_failure"] = "inactive-frame"
        return False

    if not gpuvideoinitialise():
        _gputelemetry["video_surface_draw_failures"] += 1
        _gputelemetry["video_surface_last_draw_failure"] = "video-program"
        return False

    if not _gpuclip(clip):
        _gputelemetry["video_surface_draw_failures"] += 1
        _gputelemetry["video_surface_last_draw_failure"] = "empty-clip"
        return False

    texturev0, texturev1 = _gpuvideosurfaceverticalcoordinates(resource)
    values = _gpuquadvertices(
        float(x),
        float(y),
        float(width),
        float(height),
        0.0,
        texturev0,
        1.0,
        texturev1,
        (255, 255, 255, 255),
        opacity=max(0.0, min(1.0, float(opacity))),
    )

    if not values:
        _gputelemetry["video_surface_draw_failures"] += 1
        _gputelemetry["video_surface_last_draw_failure"] = "empty-geometry"
        return False

    vertices = (ctypes.c_float * len(values))(*values)
    size = ctypes.sizeof(vertices)
    _gpubufferensure(size)
    _gles.glBlendFuncSeparate(
        GL_SRC_ALPHA,
        GL_ONE_MINUS_SRC_ALPHA,
        GL_ONE,
        GL_ONE_MINUS_SRC_ALPHA,
    )
    _gles.glBindBuffer(GL_ARRAY_BUFFER, int(_gpubuffer))
    _gles.glBufferSubData(
        GL_ARRAY_BUFFER,
        0,
        size,
        ctypes.cast(vertices, ctypes.c_void_p),
    )
    planar = bool(resource.get("planar", False))
    program = _gpuvideoplanarprogram if planar else _gpuvideoprogram
    _gles.glUseProgram(program)
    _gles.glActiveTexture(GL_TEXTURE0)

    if planar:
        textures = resource.get("textures", [])

        if not isinstance(textures, list) or len(textures) != 2:
            _gputelemetry["video_surface_draw_failures"] += 1
            _gputelemetry["video_surface_last_draw_failure"] = "planar-textures"
            return False

        offset, rows = _gpuvideocolourtransform(resource)
        _gles.glBindTexture(GL_TEXTURE_EXTERNAL_OES, int(textures[0]))
        _gles.glActiveTexture(GL_TEXTURE1)
        _gles.glBindTexture(GL_TEXTURE_EXTERNAL_OES, int(textures[1]))
        _gpusetuniform1i(program, b"ysurface", 0)
        _gpusetuniform1i(program, b"uvsurface", 1)
        _gpusetuniform3f(program, b"yuvoffset", *offset)
        _gpusetuniform3f(program, b"redrow", *rows[0])
        _gpusetuniform3f(program, b"greenrow", *rows[1])
        _gpusetuniform3f(program, b"bluerow", *rows[2])
        _gles.glActiveTexture(GL_TEXTURE0)
    else:
        _gles.glBindTexture(GL_TEXTURE_EXTERNAL_OES, int(resource["texture"]))
        _gpusetuniform1i(program, b"videosurface", 0)

    _gpusetuniform1f(program, b"opacity", 1.0)
    _gpusetuniform1f(program, b"videoheight", float(resource.get("height", 1)))
    _gpusetuniform1f(program, b"deinterlace", 1.0 if resource.get("interlaced") else 0.0)
    _gpusetuniform1f(
        program,
        b"hdrtransfer",
        float((resource.get("color") or {}).get("transfer", 0)),
    )

    stride = ctypes.sizeof(ctypes.c_float) * 8
    _gles.glEnableVertexAttribArray(0)
    _gles.glEnableVertexAttribArray(1)
    _gles.glEnableVertexAttribArray(2)
    _gles.glVertexAttribPointer(0, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(0))
    _gles.glVertexAttribPointer(
        1,
        2,
        GL_FLOAT,
        0,
        stride,
        ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 2),
    )
    _gles.glVertexAttribPointer(
        2,
        4,
        GL_FLOAT,
        0,
        stride,
        ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 4),
    )
    _gles.glDrawArrays(GL_TRIANGLES, 0, len(values) // 8)
    _gles.glDisableVertexAttribArray(0)
    _gles.glDisableVertexAttribArray(1)
    _gles.glDisableVertexAttribArray(2)
    _gles.glBindBuffer(GL_ARRAY_BUFFER, 0)
    _gpuframedraws += 1
    _gputelemetry["draw_calls"] += 1
    _gputelemetry["video_surface_draws"] += 1
    _gputelemetry["video_surface_last_draw_failure"] = ""
    _gputelemetry["vertex_upload_bytes"] += int(size)
    return True


def gpulineinitialise():

    global _gpulineprogram

    if _gpulineprogram:
        return True

    if not gpuinitialise():
        return False

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; attribute vec4 vertexcolor; attribute vec2 normal; "
        "varying vec2 linepoint; varying vec2 linehalfsize; varying vec4 drawcolor; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); linepoint = texcoord; "
        "linehalfsize = normal; drawcolor = vertexcolor; }"
    )
    fragmentsource = (
        "precision mediump float; uniform float effectmode; "
        "varying vec2 linepoint; varying vec2 linehalfsize; varying vec4 drawcolor; "
        "void main() { float beyond = max(abs(linepoint.x) - linehalfsize.x, 0.0); "
        "float distancevalue = length(vec2(beyond, linepoint.y)) - linehalfsize.y; "
        "float coverage = 1.0 - smoothstep(-0.75, 0.75, distancevalue); vec3 colour = drawcolor.rgb; "
        "if (effectmode > 0.5 && effectmode < 1.5) { float value = dot(colour, vec3(0.299, 0.587, 0.114)); colour = vec3(value); } "
        "else if (effectmode > 1.5 && effectmode < 2.5) { colour = vec3(1.0) - colour; } "
        "else if (effectmode > 2.5) { vec3 source = colour; colour.r = dot(source, vec3(0.393, 0.769, 0.189)); "
        "colour.g = dot(source, vec3(0.349, 0.686, 0.168)); colour.b = dot(source, vec3(0.272, 0.534, 0.131)); } "
        "gl_FragColor = vec4(clamp(colour, 0.0, 1.0), drawcolor.a * coverage); }"
    )
    _gpulineprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpulineprogram)


def gpublurinitialise():

    global _gpublurprogram

    if _gpublurprogram:
        return True

    if not gpuinitialise():
        return False

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; attribute vec4 vertexcolor; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); texturecoord = texcoord; drawcolor = vertexcolor; }"
    )
    fragmentsource = (
        "precision mediump float; uniform sampler2D surface; uniform vec2 blurstep; uniform float opacity; "
        "varying vec2 texturecoord; varying vec4 drawcolor; void main() { "
        "vec4 sampled = texture2D(surface, texturecoord) * 0.20; "
        "sampled += texture2D(surface, texturecoord + vec2(blurstep.x, 0.0)) * 0.12; "
        "sampled += texture2D(surface, texturecoord - vec2(blurstep.x, 0.0)) * 0.12; "
        "sampled += texture2D(surface, texturecoord + vec2(0.0, blurstep.y)) * 0.12; "
        "sampled += texture2D(surface, texturecoord - vec2(0.0, blurstep.y)) * 0.12; "
        "sampled += texture2D(surface, texturecoord + blurstep) * 0.08; "
        "sampled += texture2D(surface, texturecoord - blurstep) * 0.08; "
        "sampled += texture2D(surface, texturecoord + vec2(blurstep.x, -blurstep.y)) * 0.08; "
        "sampled += texture2D(surface, texturecoord + vec2(-blurstep.x, blurstep.y)) * 0.08; "
        "gl_FragColor = sampled * drawcolor * vec4(1.0, 1.0, 1.0, opacity); }"
    )
    _gpublurprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpublurprogram)


def gpueffectinitialise():

    global _gpueffectprogram

    if _gpueffectprogram:
        return True

    if not gpuinitialise():
        return False

    vertexsource = (
        "attribute vec2 position; attribute vec2 texcoord; attribute vec4 vertexcolor; "
        "varying vec2 texturecoord; varying vec4 drawcolor; "
        "void main() { gl_Position = vec4(position, 0.0, 1.0); texturecoord = texcoord; drawcolor = vertexcolor; }"
    )
    fragmentsource = (
        "precision mediump float; uniform sampler2D surface; uniform float texturemode; uniform float swizzle; uniform float texturealpha; uniform float textmode; "
        "uniform float unpremultiply; uniform float premultiplied; uniform float roundedmode; uniform float cornerradius; uniform vec2 shapesize; uniform float effectmode; uniform float opacity; "
        "varying vec2 texturecoord; varying vec4 drawcolor; void main() { vec4 colour = drawcolor; "
        "if (texturemode > 0.5) { vec4 sampled = texture2D(surface, texturecoord); sampled = mix(sampled, sampled.bgra, step(0.5, swizzle)); "
        "sampled.a = mix(1.0, sampled.a, step(0.5, texturealpha)); "
        "if (textmode > 0.5) { float coverage = sampled.a; float exponent = 0.5555556; float lightcoverage = pow(coverage, exponent); "
        "float darkcoverage = 1.0 - pow(1.0 - coverage, exponent); float polarity = step(0.5, dot(drawcolor.rgb, vec3(0.299, 0.587, 0.114))); "
        "sampled.a = mix(darkcoverage, lightcoverage, polarity); } "
        "if ((unpremultiply > 0.5 || premultiplied > 0.5) && sampled.a > 0.0001) { sampled.rgb /= sampled.a; } colour = sampled * drawcolor; } "
        "if (effectmode < 1.5) { float luminance = dot(colour.rgb, vec3(0.299, 0.587, 0.114)); colour.rgb = vec3(luminance); } "
        "else if (effectmode < 2.5) { colour.rgb = vec3(1.0) - colour.rgb; } "
        "else { vec3 source = colour.rgb; colour.r = dot(source, vec3(0.393, 0.769, 0.189)); colour.g = dot(source, vec3(0.349, 0.686, 0.168)); colour.b = dot(source, vec3(0.272, 0.534, 0.131)); colour.rgb = min(colour.rgb, vec3(1.0)); } "
        "if (roundedmode > 0.5) { vec2 halfsize = shapesize * 0.5; vec2 point = abs((texturecoord - vec2(0.5)) * shapesize); "
        "vec2 delta = max(point - (halfsize - vec2(cornerradius)), vec2(0.0)); float distance = length(delta) - cornerradius; "
        "float coverage = 1.0 - smoothstep(-0.75, 0.75, distance); colour.a *= coverage; } "
        "if (premultiplied > 0.5) { colour.rgb *= colour.a; } "
        "gl_FragColor = vec4(colour.rgb, colour.a * opacity); }"
    )
    _gpueffectprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpueffectprogram)


def gpu3dinitialise():

    global _gpu3dprogram

    if _gpu3dprogram:
        return True

    if not gpuinitialise():
        return False

    vertexsource = (
        "attribute vec3 position; attribute vec3 normal; attribute vec2 texcoord; "
        "uniform mat4 model; uniform mat4 view; uniform mat4 projection; "
        "varying vec3 worldposition; varying vec3 worldnormal; varying vec2 texturecoord; "
        "void main() { vec4 world = model * vec4(position, 1.0); worldposition = world.xyz; "
        "worldnormal = normalize(mat3(model) * normal); texturecoord = texcoord; "
        "gl_Position = projection * view * world; }"
    )
    fragmentsource = (
        "precision mediump float; uniform sampler2D surface; uniform float texturemode; uniform float swizzle; "
        "uniform vec4 materialcolor; uniform float unlit; uniform float shininess; "
        "uniform vec3 ambientcolor; uniform float ambientintensity; "
        "uniform vec3 lightdirection; uniform vec3 lightcolor; uniform float lightintensity; "
        "uniform vec3 cameraposition; uniform float fogenabled; uniform vec3 fogcolor; "
        "uniform float fognear; uniform float fogfar; uniform float postprocess; "
        "varying vec3 worldposition; varying vec3 worldnormal; varying vec2 texturecoord; "
        "void main() { vec4 base = materialcolor; if (texturemode > 0.5) { vec4 sampled = texture2D(surface, texturecoord); "
        "sampled = mix(sampled, sampled.bgra, step(0.5, swizzle)); base *= sampled; } "
        "vec3 colour = base.rgb; if (unlit < 0.5) { vec3 normalvalue = normalize(worldnormal); "
        "vec3 lightvalue = normalize(-lightdirection); float diffuse = max(dot(normalvalue, lightvalue), 0.0); "
        "vec3 viewvalue = normalize(cameraposition - worldposition); vec3 halfway = normalize(lightvalue + viewvalue); "
        "float specular = pow(max(dot(normalvalue, halfway), 0.0), max(1.0, shininess)); "
        "colour *= ambientcolor * ambientintensity + lightcolor * lightintensity * diffuse; "
        "colour += lightcolor * lightintensity * specular * 0.35; } "
        "if (postprocess > 0.5 && postprocess < 1.5) { float value = dot(colour, vec3(0.299, 0.587, 0.114)); colour = vec3(value); } "
        "else if (postprocess < 2.5 && postprocess > 1.5) { colour = vec3(1.0) - colour; } "
        "else if (postprocess > 2.5) { vec3 source = colour; colour.r = dot(source, vec3(0.393, 0.769, 0.189)); "
        "colour.g = dot(source, vec3(0.349, 0.686, 0.168)); colour.b = dot(source, vec3(0.272, 0.534, 0.131)); } "
        "if (fogenabled > 0.5) { float distancevalue = length(cameraposition - worldposition); "
        "float fogamount = smoothstep(fognear, fogfar, distancevalue); colour = mix(colour, fogcolor, fogamount); } "
        "gl_FragColor = vec4(clamp(colour, 0.0, 1.0), base.a); }"
    )
    _gpu3dprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpu3dprogram)


def gpu3dlineinitialise():

    global _gpu3dlineprogram

    if _gpu3dlineprogram:
        return True

    if not gpu3dinitialise():
        return False

    vertexsource = (
        "attribute vec3 position; attribute vec3 other; attribute vec2 texcoord; attribute vec3 normal; "
        "uniform mat4 model; uniform mat4 view; uniform mat4 projection; uniform vec2 viewport; uniform float linewidth; "
        "varying vec2 linepoint; varying vec2 linehalfsize; varying vec3 worldposition; varying vec3 worldnormal; "
        "void main() { vec4 world0 = model * vec4(position, 1.0); vec4 world1 = model * vec4(other, 1.0); "
        "vec4 clip0 = projection * view * world0; vec4 clip1 = projection * view * world1; "
        "vec2 ndc0 = clip0.xy / max(abs(clip0.w), 0.0001); vec2 ndc1 = clip1.xy / max(abs(clip1.w), 0.0001); "
        "vec2 delta = (ndc1 - ndc0) * viewport * 0.5; float screenlength = max(length(delta), 0.001); "
        "vec2 direction = delta / screenlength; vec2 sidenormal = vec2(-direction.y, direction.x); "
        "float extent = linewidth * 0.5 + 1.0; float endpoint = texcoord.x; vec4 selected = mix(clip0, clip1, endpoint); "
        "float along = mix(-extent, extent, endpoint); vec2 pixeloffset = direction * along + sidenormal * texcoord.y * extent; "
        "selected.xy += pixeloffset * 2.0 / viewport * selected.w; gl_Position = selected; "
        "linepoint = vec2((endpoint - 0.5) * (screenlength + extent * 2.0), texcoord.y * extent); "
        "linehalfsize = vec2(screenlength * 0.5, linewidth * 0.5); worldposition = mix(world0.xyz, world1.xyz, endpoint); "
        "worldnormal = normalize(mat3(model) * normal); }"
    )
    fragmentsource = (
        "precision mediump float; uniform vec4 materialcolor; uniform float unlit; uniform float shininess; "
        "uniform vec3 ambientcolor; uniform float ambientintensity; uniform vec3 lightdirection; uniform vec3 lightcolor; "
        "uniform float lightintensity; uniform vec3 cameraposition; uniform float fogenabled; uniform vec3 fogcolor; "
        "uniform float fognear; uniform float fogfar; uniform float postprocess; "
        "varying vec2 linepoint; varying vec2 linehalfsize; varying vec3 worldposition; varying vec3 worldnormal; "
        "void main() { float beyond = max(abs(linepoint.x) - linehalfsize.x, 0.0); "
        "float distancevalue = length(vec2(beyond, linepoint.y)) - linehalfsize.y; "
        "float coverage = 1.0 - smoothstep(-0.75, 0.75, distancevalue); vec3 colour = materialcolor.rgb; "
        "if (unlit < 0.5) { vec3 normalvalue = normalize(worldnormal); vec3 lightvalue = normalize(-lightdirection); "
        "float diffuse = max(dot(normalvalue, lightvalue), 0.0); vec3 viewvalue = normalize(cameraposition - worldposition); "
        "vec3 halfway = normalize(lightvalue + viewvalue); float specular = pow(max(dot(normalvalue, halfway), 0.0), max(1.0, shininess)); "
        "colour *= ambientcolor * ambientintensity + lightcolor * lightintensity * diffuse; "
        "colour += lightcolor * lightintensity * specular * 0.35; } "
        "if (postprocess > 0.5 && postprocess < 1.5) { float value = dot(colour, vec3(0.299, 0.587, 0.114)); colour = vec3(value); } "
        "else if (postprocess > 1.5 && postprocess < 2.5) { colour = vec3(1.0) - colour; } "
        "else if (postprocess > 2.5) { vec3 source = colour; colour.r = dot(source, vec3(0.393, 0.769, 0.189)); "
        "colour.g = dot(source, vec3(0.349, 0.686, 0.168)); colour.b = dot(source, vec3(0.272, 0.534, 0.131)); } "
        "if (fogenabled > 0.5) { float fogdistance = length(cameraposition - worldposition); "
        "float fogamount = smoothstep(fognear, fogfar, fogdistance); colour = mix(colour, fogcolor, fogamount); } "
        "gl_FragColor = vec4(clamp(colour, 0.0, 1.0), materialcolor.a * coverage); }"
    )
    _gpu3dlineprogram = openglprogram(vertexsource, fragmentsource)
    return bool(_gpu3dlineprogram)


def gpurelease():

    global _gpuprogram, _gpublurprogram, _gpueffectprogram, _gpulineprogram
    global _gpuvideoprogram, _gpuvideoplanarprogram, _gpuvideosurfaces
    global _gpuvideoimportcapabilitiescache
    global _gpu3dprogram, _gpu3dlineprogram, _gpuuniforms, _gpuuniformvalues
    global _gpubuffer, _gpubufferbytes, _gputextures, _gputexturebytes, _gpuhandle
    global _gpuframeactive, _gpuimagecache, _gputextcache, _gpuglyphatlases, _gpucursorcache, _gpublurcache
    global _gpucompositorfbo, _gpucompositorhandle, _gpucompositorwidth
    global _gpucompositorheight, _gpucompositorvalid, _gpuframepersistent
    global _gpuframesyncpersistent, _gpuframeclip, _gputargets, _gputargetdepths, _gpu3daatargets, _gputargetactive
    global _gpurenderwidth, _gpurenderheight, _gpuuploadstaging

    try:

        if _gles is not None:

            if _gpucompositorfbo:
                framebuffer = ctypes.c_uint(int(_gpucompositorfbo))
                _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))

            for framebufferid in list(_gputargets.values()):

                if framebufferid:
                    framebuffer = ctypes.c_uint(int(framebufferid))
                    _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))

            for renderbufferid in list(_gputargetdepths.values()):

                if renderbufferid:
                    renderbuffer = ctypes.c_uint(int(renderbufferid))
                    _gles.glDeleteRenderbuffers(1, ctypes.byref(renderbuffer))

            for resource in list(_gputextures.values()):

                texture = int(resource.get("texture", 0))

                if texture:
                    value = ctypes.c_uint(texture)
                    _gles.glDeleteTextures(1, ctypes.byref(value))

            for resource in list(_gpuvideosurfaces.values()):

                textures = resource.get("textures")

                if not isinstance(textures, list):
                    textures = [resource.get("texture", 0)]

                for texture in textures:

                    if texture:
                        value = ctypes.c_uint(int(texture))
                        _gles.glDeleteTextures(1, ctypes.byref(value))

                images = resource.get("images")

                if not isinstance(images, list):
                    images = [resource.get("image")]

                if _egldestroyimage is not None:

                    for image in images:

                        if image:
                            _egldestroyimage(_egldisplay, image)

            if _gpuprogram:
                _gles.glDeleteProgram(_gpuprogram)

            if _gpublurprogram:
                _gles.glDeleteProgram(_gpublurprogram)

            if _gpueffectprogram:
                _gles.glDeleteProgram(_gpueffectprogram)

            if _gpulineprogram:
                _gles.glDeleteProgram(_gpulineprogram)

            if _gpuvideoprogram:
                _gles.glDeleteProgram(_gpuvideoprogram)

            if _gpuvideoplanarprogram:
                _gles.glDeleteProgram(_gpuvideoplanarprogram)

            if _gpu3dprogram:
                _gles.glDeleteProgram(_gpu3dprogram)

            if _gpu3dlineprogram:
                _gles.glDeleteProgram(_gpu3dlineprogram)

            if _gpubuffer:
                value = ctypes.c_uint(int(_gpubuffer))
                _gles.glDeleteBuffers(1, ctypes.byref(value))

    except Exception:
        pass

    _gpuprogram = 0
    _gpublurprogram = 0
    _gpueffectprogram = 0
    _gpulineprogram = 0
    _gpuvideoprogram = 0
    _gpuvideoplanarprogram = 0
    _gpuvideoimportcapabilitiescache = None
    _gpuvideosurfaces = {}
    _gpu3dprogram = 0
    _gpu3dlineprogram = 0
    _gpuuniforms = {}
    _gpuuniformvalues = {}
    _gpubuffer = 0
    _gpubufferbytes = 0
    _gputextures = {}
    _gputexturebytes = 0
    _gpuhandle = 1
    _gpuframeactive = False
    _gpuimagecache = {}
    _gputextcache = {}
    _gpuglyphatlases = {}
    _gpucursorcache = {}
    _gpublurcache = {}
    _gpucompositorfbo = 0
    _gpucompositorhandle = 0
    _gpucompositorwidth = 0
    _gpucompositorheight = 0
    _gpucompositorvalid = False
    _gputargets = {}
    _gputargetdepths = {}
    _gpu3daatargets = {}
    _gputargetactive = False
    _gpurenderwidth = 0
    _gpurenderheight = 0
    _gpuuploadstaging = bytearray()
    _gpuframepersistent = False
    _gpuframesyncpersistent = False
    _gpuframeclip = None


def gputextureinfo(handle):

    resource = _gputextures.get(int(handle))

    if resource is None:
        return None

    return {
        "handle": int(handle),
        "width": int(resource["width"]),
        "height": int(resource["height"]),
        "format": str(resource["format"]),
        "storage": str(resource.get("storage", "RGBA")),
        "alpha": bool(resource.get("alpha", True)),
        "premultiplied": bool(resource.get("premultiplied", False)),
        "owner": str(resource["owner"]),
        "bytes": int(resource["bytes"]),
        "updates": int(resource["updates"]),
        "upload_bytes": int(resource["upload_bytes"]),
    }


def gputexturecreate(
    width,
    height,
    fmt="BGRA32",
    data=None,
    owner="system",
    alpha=True,
    storage="RGBA",
):

    global _gpuhandle, _gputexturebytes

    if not gpuinitialise():
        raise RuntimeError("managed GPU renderer is unavailable")

    width = int(width)
    height = int(height)
    fmt = str(fmt).upper()
    storage = str(storage).upper()

    if width < 1 or height < 1:
        raise ValueError("texture dimensions must be positive")

    if fmt not in ("BGRA32", "RGBA32"):
        raise ValueError(f"unsupported texture format {fmt}")

    if storage not in ("RGB", "RGBA"):
        raise ValueError(f"unsupported texture storage format {storage}")

    if storage == "RGB" and data is not None:
        raise ValueError(
            "RGB copy-target textures do not accept RGBA CPU upload data"
        )

    if len(_gputextures) >= GPUMAXTEXTURES:
        raise RuntimeError("managed GPU texture limit reached")

    size = width * height * 4

    if size > GPUMAXTEXTUREBYTES or _gputexturebytes + size > GPUMAXTEXTUREBYTES:
        raise RuntimeError("managed GPU texture memory limit reached")

    value = ctypes.c_uint()
    _gles.glGenTextures(1, ctypes.byref(value))
    texture = int(value.value)
    handle = None

    if texture == 0:
        raise RuntimeError("glGenTextures failed")

    try:

        _gles.glActiveTexture(GL_TEXTURE0)
        _gles.glBindTexture(GL_TEXTURE_2D, texture)
        _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        _gles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        _gles.glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
        storageformat = GL_RGB if storage == "RGB" else GL_RGBA
        _gles.glTexImage2D(
            GL_TEXTURE_2D,
            0,
            storageformat,
            width,
            height,
            0,
            storageformat,
            GL_UNSIGNED_BYTE,
            None,
        )

        handle = int(_gpuhandle)
        _gpuhandle += 1
        _gputextures[handle] = {
            "texture": texture,
            "width": width,
            "height": height,
            "format": fmt,
            "storage": storage,
            "alpha": bool(alpha),
            "owner": str(owner)[:128],
            "bytes": size,
            "updates": 0,
            "upload_bytes": 0,
        }
        _gputexturebytes += size
        _gputelemetry["maximum_texture_count"] = max(int(_gputelemetry["maximum_texture_count"]), len(_gputextures))
        _gputelemetry["maximum_texture_bytes"] = max(int(_gputelemetry["maximum_texture_bytes"]), int(_gputexturebytes))

        if data is not None:
            gputextureupdate(handle, 0, 0, width, height, data=data)

        return handle

    except Exception:

        if handle is not None and handle in _gputextures:
            resource = _gputextures.pop(handle)
            _gputexturebytes -= int(resource.get("bytes", 0))

        value = ctypes.c_uint(texture)
        _gles.glDeleteTextures(1, ctypes.byref(value))
        raise


def gputexturedestroy(handle):

    global _gputexturebytes

    handle = int(handle)

    for key, value in list(_gpu3daatargets.items()):

        if isinstance(value, dict) and int(value.get("handle", 0)) == handle:
            _gpu3daatargets.pop(key, None)

    renderbufferid = _gputargetdepths.pop(handle, 0)

    if renderbufferid:

        try:
            renderbuffer = ctypes.c_uint(int(renderbufferid))
            _gles.glDeleteRenderbuffers(1, ctypes.byref(renderbuffer))
        except Exception:
            pass

    framebufferid = _gputargets.pop(handle, 0)

    if framebufferid:

        try:
            framebuffer = ctypes.c_uint(int(framebufferid))
            _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))
        except Exception:
            pass

    resource = _gputextures.pop(handle, None)

    if resource is None:
        return False

    try:

        texture = ctypes.c_uint(int(resource.get("texture", 0)))

        if texture.value and _gles is not None:
            _gles.glDeleteTextures(1, ctypes.byref(texture))

    finally:

        _gputexturebytes -= int(resource.get("bytes", 0))

        if _gputexturebytes < 0:
            _gputexturebytes = 0

    return True


def _gputextureregion(resource, x, y, width, height, data, path, stride, source_offset=0):

    global _gpuuploadstaging

    rowbytes = int(width) * 4
    size = rowbytes * int(height)

    if data is not None:

        result = memoryview(data)

        if result.nbytes != size:
            raise ValueError(f"texture update expected {size} bytes, received {result.nbytes}")

        return result

    if path is None:
        raise ValueError("texture update needs data or a path")

    stridebytes = int(stride) if stride is not None else int(resource["width"]) * 4
    source_offset = int(source_offset)

    if stridebytes < (int(x) + int(width)) * 4:
        raise ValueError("texture source stride is too small")
    if source_offset < 0:
        raise ValueError("texture source offset cannot be negative")

    if size > int(GPUUPLOADSTAGINGLIMIT):
        raise ValueError(f"texture upload staging limit reached {size}/{GPUUPLOADSTAGINGLIMIT}")

    if len(_gpuuploadstaging) < size:
        _gpuuploadstaging = bytearray(size)

        _gputelemetry["maximum_upload_staging_bytes"] = max(
            int(_gputelemetry.get("maximum_upload_staging_bytes", 0)),
            int(size),
        )

    result = memoryview(_gpuuploadstaging)[:size]

    with open(path, "rb") as source:
        locked = lockbuffer(source)

        try:

            if int(x) == 0 and rowbytes == stridebytes:

                source.seek(source_offset + int(y) * stridebytes)
                offset = 0

                while offset < size:

                    count = source.readinto(result[offset:size])

                    if not count:
                        break

                    offset += int(count)

                if offset != size:
                    raise RuntimeError(f"short texture read from {path}")

            else:

                for row in range(int(height)):
                    source.seek(
                        source_offset
                        + ((int(y) + row) * stridebytes)
                        + (int(x) * 4)
                    )
                    offset = row * rowbytes
                    count = source.readinto(result[offset:offset + rowbytes])

                    if count != rowbytes:
                        raise RuntimeError(f"short texture read from {path}")

        finally:

            if locked:
                unlockbuffer(source)

    _gputelemetry["upload_staging_bytes"] = int(size)
    return result


def gputextureupdate(
    handle, x=0, y=0, width=None, height=None, data=None, path=None,
    stride=None, fmt=None, source_offset=0,
):

    global _gpuframeuploads, _gpuframeuploadbytes

    handle = int(handle)
    resource = _gputextures.get(handle)

    if resource is None:
        raise KeyError(f"unknown managed GPU texture {handle}")

    if str(resource.get("storage", "RGBA")).upper() != "RGBA":
        raise ValueError(
            "CPU texture updates require RGBA storage; RGB textures are "
            "framebuffer-copy targets"
        )

    x = int(x)
    y = int(y)
    width = int(resource["width"] - x if width is None else width)
    height = int(resource["height"] - y if height is None else height)

    if x < 0 or y < 0 or width < 1 or height < 1:
        raise ValueError("invalid texture update rectangle")

    if x + width > int(resource["width"]) or y + height > int(resource["height"]):
        raise ValueError("texture update rectangle is outside the resource")

    if fmt is not None and str(fmt).upper() != str(resource["format"]):
        raise ValueError("texture update format does not match the resource")

    _gles.glActiveTexture(GL_TEXTURE0)
    _gles.glBindTexture(GL_TEXTURE_2D, int(resource["texture"]))
    _gles.glPixelStorei(GL_UNPACK_ALIGNMENT, 4)

    rowbytes = int(width) * 4
    bandrows = max(1, int(GPUUPLOADSTAGINGLIMIT) // max(1, rowbytes))
    row = 0

    while row < height:

        rows = min(int(bandrows), int(height) - int(row))
        banddata = data

        if data is not None and (row > 0 or rows != height):

            start = int(row) * int(rowbytes)
            finish = start + int(rows) * int(rowbytes)
            banddata = memoryview(data)[start:finish]

        pixels = _gputextureregion(
            resource, x, y + row, width, rows, banddata, path, stride,
            source_offset=source_offset,
        )

        try:
            array = (ctypes.c_ubyte * len(pixels)).from_buffer(pixels)
        except (TypeError, BufferError):
            array = (ctypes.c_ubyte * len(pixels)).from_buffer_copy(pixels)

        _gles.glTexSubImage2D(
            GL_TEXTURE_2D,
            0,
            x,
            y + row,
            width,
            rows,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            ctypes.cast(array, ctypes.c_void_p),
        )

        _gputelemetry["upload_calls"] = int(_gputelemetry.get("upload_calls", 0)) + 1
        row += rows

    uploaded = width * height * 4
    full = x == 0 and y == 0 and width == int(resource["width"]) and height == int(resource["height"])
    resource["updates"] += 1
    resource["upload_bytes"] += uploaded
    _gputelemetry["uploads"] += 1
    _gputelemetry["upload_bytes"] += uploaded
    _gputelemetry["full_uploads" if full else "partial_uploads"] += 1

    if _gpuframeactive:
        _gpuframeuploads += 1
        _gpuframeuploadbytes += uploaded

    return uploaded


def gputargetcreate(width, height, owner="system-layer"):

    handle = gputexturecreate(width, height, fmt="RGBA32", owner=owner, alpha=True)
    framebuffer = ctypes.c_uint()

    try:

        resource = _gputextures[int(handle)]
        # Offscreen targets use premultiplied alpha.  This keeps source-over
        # associative when a completed scene or layer is composited again.
        resource["premultiplied"] = True
        _gles.glGenFramebuffers(1, ctypes.byref(framebuffer))

        if not framebuffer.value:
            raise RuntimeError("glGenFramebuffers failed")

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, int(framebuffer.value))
        _gles.glFramebufferTexture2D(
            GL_FRAMEBUFFER,
            GL_COLOR_ATTACHMENT0,
            GL_TEXTURE_2D,
            int(resource["texture"]),
            0,
        )

        status = int(_gles.glCheckFramebufferStatus(GL_FRAMEBUFFER))

        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"render target framebuffer incomplete 0x{status:04x}")

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, int(_gpucompositorfbo) if _gpuframepersistent else 0)
        _gputargets[int(handle)] = int(framebuffer.value)
        return int(handle)

    except Exception:

        try:

            if framebuffer.value:
                _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))

        except Exception:
            pass

        gputexturedestroy(handle)
        raise


def _gputargetdepthensure(handle):

    handle = int(handle)
    resource = _gputextures.get(handle)
    framebuffer = int(_gputargets.get(handle, 0))

    if resource is None or not framebuffer:
        raise KeyError(f"unknown managed GPU render target {handle}")

    existing = int(_gputargetdepths.get(handle, 0))

    if existing:
        return existing

    depthbytes = int(resource["width"]) * int(resource["height"]) * 2
    allocateddepthbytes = sum(
        int(_gputextures[target]["width"]) * int(_gputextures[target]["height"]) * 2
        for target in _gputargetdepths
        if target in _gputextures
    )

    if int(_gputexturebytes) + int(allocateddepthbytes) + int(depthbytes) > GPUMAXTEXTUREBYTES:
        raise MemoryError("managed GPU texture and depth buffer memory limit exceeded")

    renderbuffer = ctypes.c_uint()

    try:
        _gles.glGenRenderbuffers(1, ctypes.byref(renderbuffer))

        if not renderbuffer.value:
            raise RuntimeError("glGenRenderbuffers failed")

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
        _gles.glBindRenderbuffer(GL_RENDERBUFFER, int(renderbuffer.value))
        _gles.glRenderbufferStorage(
            GL_RENDERBUFFER,
            GL_DEPTH_COMPONENT16,
            int(resource["width"]),
            int(resource["height"]),
        )
        _gles.glFramebufferRenderbuffer(
            GL_FRAMEBUFFER,
            GL_DEPTH_ATTACHMENT,
            GL_RENDERBUFFER,
            int(renderbuffer.value),
        )
        status = int(_gles.glCheckFramebufferStatus(GL_FRAMEBUFFER))

        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"depth render target framebuffer incomplete 0x{status:04x}")

        _gles.glBindRenderbuffer(GL_RENDERBUFFER, 0)
        _gputargetdepths[handle] = int(renderbuffer.value)
        _gputelemetry["maximum_depth_buffer_count"] = max(
            int(_gputelemetry["maximum_depth_buffer_count"]),
            len(_gputargetdepths),
        )
        _gputelemetry["maximum_depth_buffer_bytes"] = max(
            int(_gputelemetry["maximum_depth_buffer_bytes"]),
            int(allocateddepthbytes) + int(depthbytes),
        )
        return int(renderbuffer.value)

    except Exception:

        try:

            if renderbuffer.value:
                _gles.glDeleteRenderbuffers(1, ctypes.byref(renderbuffer))

        except Exception:
            pass

        raise


def gputargetdestroy(handle):

    return gputexturedestroy(handle)


def gputargetbegin(handle, clearcolor=(0, 0, 0, 0), clear=True):

    global _gputargetactive, _gpurenderwidth, _gpurenderheight, _gpuframeclip

    handle = int(handle)
    resource = _gputextures.get(handle)
    framebuffer = int(_gputargets.get(handle, 0))

    if not _gpuframeactive:
        raise RuntimeError("render target drawing requires an active managed frame")

    if resource is None or not framebuffer:
        raise KeyError(f"unknown managed GPU render target {handle}")

    activehandle = int(_gputargetactive or 0)
    state = {
        "width": int(_gpurenderwidth or _xres),
        "height": int(_gpurenderheight or _yres),
        "clip": list(_gpuframeclip) if _gpuframeclip is not None else None,
        "active": activehandle,
        "framebuffer": (
            int(_gputargets.get(activehandle, 0))
            if activehandle
            else (int(_gpucompositorfbo) if _gpuframepersistent else 0)
        ),
    }
    red, green, blue, alpha = _gpucolor(clearcolor)
    _gputargetactive = handle
    _gpurenderwidth = int(resource["width"])
    _gpurenderheight = int(resource["height"])
    _gpuframeclip = None
    _gles.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
    _gles.glViewport(0, 0, _gpurenderwidth, _gpurenderheight)
    _gles.glDisable(GL_SCISSOR_TEST)
    _gles.glEnable(GL_BLEND)
    _gles.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)

    if clear:
        # glClear bypasses blending, so store the clear colour in the target's
        # premultiplied representation explicitly.
        _gles.glClearColor(red * alpha, green * alpha, blue * alpha, alpha)
        _gles.glClear(GL_COLOR_BUFFER_BIT)

    return state


def gputargetend(state):

    global _gputargetactive, _gpurenderwidth, _gpurenderheight, _gpuframeclip

    if not _gputargetactive:
        return False

    state = state if isinstance(state, dict) else {}
    _gputargetactive = int(state.get("active", 0)) or False
    _gpurenderwidth = max(1, int(state.get("width", _xres)))
    _gpurenderheight = max(1, int(state.get("height", _yres)))
    savedclip = state.get("clip")
    _gpuframeclip = list(savedclip) if savedclip is not None else None
    _gles.glBindFramebuffer(GL_FRAMEBUFFER, int(state.get("framebuffer", 0)))
    _gles.glViewport(0, 0, _gpurenderwidth, _gpurenderheight)
    _gles.glDisable(GL_SCISSOR_TEST)
    return True


def _gpurendersize():

    return max(1, int(_gpurenderwidth or _xres)), max(1, int(_gpurenderheight or _yres))


def _gpucolor(color):

    if isinstance(color, int):
        return (
            ((color >> 16) & 0xFF) / 255.0,
            ((color >> 8) & 0xFF) / 255.0,
            (color & 0xFF) / 255.0,
            1.0,
        )

    values = list(color)

    if len(values) < 3:
        raise ValueError("GPU colour needs at least three channels")

    alpha = values[3] if len(values) > 3 else 255
    return (
        max(0.0, min(1.0, float(values[0]) / 255.0)),
        max(0.0, min(1.0, float(values[1]) / 255.0)),
        max(0.0, min(1.0, float(values[2]) / 255.0)),
        max(0.0, min(1.0, float(alpha) / 255.0)),
    )


def _gpucompositorrelease():

    global _gpucompositorfbo, _gpucompositorhandle, _gpucompositorwidth
    global _gpucompositorheight, _gpucompositorvalid

    try:

        if _gles is not None:
            _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)

            if _gpucompositorfbo:
                framebuffer = ctypes.c_uint(int(_gpucompositorfbo))
                _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))

    except Exception:
        pass

    try:

        if _gpucompositorhandle:
            gputexturedestroy(_gpucompositorhandle)

    except Exception:
        pass

    _gpucompositorfbo = 0
    _gpucompositorhandle = 0
    _gpucompositorwidth = 0
    _gpucompositorheight = 0
    _gpucompositorvalid = False


def _gpucompositorensure():

    global _gpucompositorfbo, _gpucompositorhandle, _gpucompositorwidth
    global _gpucompositorheight, _gpucompositorvalid

    if (
        _gpucompositorfbo
        and _gpucompositorhandle
        and _gpucompositorwidth == int(_xres)
        and _gpucompositorheight == int(_yres)
        and gputextureinfo(_gpucompositorhandle) is not None
    ):
        return False

    _gpucompositorrelease()
    framebuffer = ctypes.c_uint()
    handle = 0

    try:

        handle = gputexturecreate(
            int(_xres),
            int(_yres),
            fmt="RGBA32",
            owner="compositor-surface",
            alpha=False,
            storage="RGB",
        )
        resource = _gputextures[int(handle)]
        _gles.glGenFramebuffers(1, ctypes.byref(framebuffer))

        if not framebuffer.value:
            raise RuntimeError("glGenFramebuffers failed")

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, int(framebuffer.value))
        _gles.glFramebufferTexture2D(
            GL_FRAMEBUFFER,
            GL_COLOR_ATTACHMENT0,
            GL_TEXTURE_2D,
            int(resource["texture"]),
            0,
        )
        status = int(_gles.glCheckFramebufferStatus(GL_FRAMEBUFFER))

        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"compositor framebuffer incomplete 0x{status:04x}")

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)
        _gpucompositorfbo = int(framebuffer.value)
        _gpucompositorhandle = int(handle)
        _gpucompositorwidth = int(_xres)
        _gpucompositorheight = int(_yres)
        _gpucompositorvalid = False
        return True

    except Exception:

        try:
            _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)
        except Exception:
            pass

        try:

            if framebuffer.value:
                _gles.glDeleteFramebuffers(1, ctypes.byref(framebuffer))

        except Exception:
            pass

        try:

            if handle:
                gputexturedestroy(handle)

        except Exception:
            pass

        raise


def _gpunormaliseregions(regions):

    output = []

    if not isinstance(regions, (list, tuple)):
        regions = []

    for region in regions[:64]:

        try:
            x, y, width, height = [int(value) for value in region]
        except Exception:
            continue

        if x < 0:
            width += x
            x = 0

        if y < 0:
            height += y
            y = 0

        width = min(width, int(_xres) - x)
        height = min(height, int(_yres) - y)

        if width > 0 and height > 0:
            output.append([x, y, width, height])

    if not output:
        output = [[0, 0, int(_xres), int(_yres)]]

    merged = []

    for value in output:

        x, y, width, height = value
        index = 0

        while index < len(merged):

            currentx, currenty, currentwidth, currentheight = merged[index]

            if not (
                x > currentx + currentwidth
                or currentx > x + width
                or y > currenty + currentheight
                or currenty > y + height
            ):

                left = min(x, currentx)
                top = min(y, currenty)
                right = max(x + width, currentx + currentwidth)
                bottom = max(y + height, currenty + currentheight)
                x, y, width, height = left, top, right - left, bottom - top
                del merged[index]
                index = 0
                continue

            index += 1

        merged.append([x, y, width, height])

    return merged


def _gpubeginstate(regions, full, persistent):

    global _gpuframeactive, _gpuframestart, _gpuframedraws, _gpuframeuploads
    global _gpuframeuploadbytes, _gpuframeregions, _gpuframedamagepixels
    global _gpuframefull, _gpuframepersistent, _gpuframesyncpersistent, _gpuframeclip
    global _gputargetactive, _gpurenderwidth, _gpurenderheight, _gpuframerenderms

    _gpuframeactive = True
    _gpuframestart = time.monotonic_ns()
    _gpuframerenderms = 0.0
    _gpuframedraws = 0
    _gpuframeuploads = 0
    _gpuframeuploadbytes = 0
    _gpuframeregions = [list(region) for region in regions]
    _gpuframedamagepixels = sum(int(region[2]) * int(region[3]) for region in regions)
    _gpuframefull = bool(full)
    _gpuframepersistent = bool(persistent)
    _gpuframesyncpersistent = False
    _gpuframeclip = None
    _gputargetactive = False
    _gpurenderwidth = int(_xres)
    _gpurenderheight = int(_yres)
    _gles.glViewport(0, 0, int(_xres), int(_yres))
    _gles.glDisable(GL_SCISSOR_TEST)
    _gles.glEnable(GL_BLEND)
    _gles.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)


def gpubegin(clearcolor=(0, 0, 0, 255)):

    global _gpucompositorvalid

    if not gpuinitialise():
        return False

    if _xres < 1 or _yres < 1:
        raise RuntimeError("GPU frame has no display geometry")

    red, green, blue, alpha = _gpucolor(clearcolor)
    _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)
    _gpubeginstate([[0, 0, int(_xres), int(_yres)]], True, False)
    _gles.glClearColor(red, green, blue, alpha)
    _gles.glClear(GL_COLOR_BUFFER_BIT)
    _gpucompositorvalid = False
    return True


def gpubeginregions(regions, clearcolor=(0, 0, 0, 255)):

    global _gpuframeactive, _gpucompositorvalid, _gpuframesyncpersistent

    if not gpuinitialise():
        return []

    if _xres < 1 or _yres < 1:
        raise RuntimeError("GPU frame has no display geometry")

    red, green, blue, alpha = _gpucolor(clearcolor)

    try:

        recreated = _gpucompositorensure()
        actual = _gpunormaliseregions(regions)

        if recreated or not _gpucompositorvalid:
            actual = [[0, 0, int(_xres), int(_yres)]]

        full = len(actual) == 1 and actual[0] == [0, 0, int(_xres), int(_yres)]

        if full and not displayadjustactive():

            _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)
            _gpubeginstate(actual, True, False)
            _gpuframesyncpersistent = True
            _gles.glClearColor(red, green, blue, alpha)
            _gles.glClear(GL_COLOR_BUFFER_BIT)
            return [list(region) for region in actual]

        _gles.glBindFramebuffer(GL_FRAMEBUFFER, int(_gpucompositorfbo))
        _gpubeginstate(actual, full, True)
        _gles.glClearColor(red, green, blue, alpha)

        if full:

            _gles.glClear(GL_COLOR_BUFFER_BIT)
            return [list(region) for region in actual]

        for x, y, width, height in actual:
            _gles.glEnable(GL_SCISSOR_TEST)
            _gles.glScissor(int(x), int(_yres) - (int(y) + int(height)), int(width), int(height))
            _gles.glClear(GL_COLOR_BUFFER_BIT)

        _gles.glDisable(GL_SCISSOR_TEST)
        return [list(region) for region in actual]

    except GPUDeviceLostError:
        raise

    except Exception:

        _gpuframeactive = False
        _gpucompositorrelease()
        _gputelemetry["persistent_fallbacks"] += 1

        if not gpubegin(clearcolor):
            return []

        return [[0, 0, int(_xres), int(_yres)]]


def gpusetregion(region):

    global _gpuframeclip

    normalised = _gpunormaliseregions([region])
    _gpuframeclip = list(normalised[0]) if normalised else None
    return _gpuframeclip is not None


def gpuframestats():

    return {
        "draw_calls": int(_gpuframedraws),
        "uploads": int(_gpuframeuploads),
        "upload_bytes": int(_gpuframeuploadbytes),
        "regions": [list(region) for region in _gpuframeregions],
        "damage_pixels": int(_gpuframedamagepixels),
        "full": bool(_gpuframefull),
        "persistent": bool(_gpuframepersistent),
        "persistent_sync": bool(_gpuframesyncpersistent),
    }


def gpuinvalidatesurface():

    global _gpucompositorvalid

    _gpucompositorvalid = False
    return True


def _gpuclip(clip):

    renderwidth, renderheight = _gpurendersize()

    if clip is None and _gpuframeclip is None:
        _gles.glDisable(GL_SCISSOR_TEST)
        return True

    if clip is None:
        x, y, width, height = [int(value) for value in _gpuframeclip]

    else:
        x, y, width, height = [int(value) for value in clip]

        if _gpuframeclip is not None:

            framex, framey, framewidth, frameheight = [int(value) for value in _gpuframeclip]
            left = max(x, framex)
            top = max(y, framey)
            right = min(x + width, framex + framewidth)
            bottom = min(y + height, framey + frameheight)
            x = left
            y = top
            width = right - left
            height = bottom - top

    if x < 0:
        width += x
        x = 0

    if y < 0:
        height += y
        y = 0

    if x + width > renderwidth:
        width = renderwidth - x

    if y + height > renderheight:
        height = renderheight - y

    if width < 1 or height < 1:
        return False

    _gles.glEnable(GL_SCISSOR_TEST)
    _gles.glScissor(x, int(renderheight) - (y + height), width, height)
    return True


def _gpubufferensure(size):

    global _gpubuffer, _gpubufferbytes

    size = max(1, int(size))

    if not _gpubuffer:

        value = ctypes.c_uint()
        _gles.glGenBuffers(1, ctypes.byref(value))
        _gpubuffer = int(value.value)

        if not _gpubuffer:
            raise RuntimeError("glGenBuffers failed")

    if size > int(_gpubufferbytes):

        capacity = 4096

        while capacity < size:
            capacity *= 2

        _gles.glBindBuffer(GL_ARRAY_BUFFER, int(_gpubuffer))
        _gles.glBufferData(GL_ARRAY_BUFFER, capacity, None, GL_DYNAMIC_DRAW)
        _gpubufferbytes = int(capacity)

    return int(_gpubuffer)


def _gpuquadvertices(x, y, width, height, u0, v0, u1, v1, tint, opacity=1.0, rotation=0.0, origin=None):

    x = float(x)
    y = float(y)
    width = float(width)
    height = float(height)

    if width <= 0.0 or height <= 0.0:
        return []

    red, green, blue, alpha = _gpucolor(tint)
    alpha *= max(0.0, min(1.0, float(opacity)))
    renderwidth, renderheight = _gpurendersize()

    def position(px, py):

        if float(rotation):

            if origin is None:
                ox = x + width * 0.5
                oy = y + height * 0.5
            else:
                ox, oy = [float(value) for value in origin]

            radians = math.radians(float(rotation))
            cosine = math.cos(radians)
            sine = math.sin(radians)
            dx = px - ox
            dy = py - oy
            px = ox + dx * cosine - dy * sine
            py = oy + dx * sine + dy * cosine

        return (px / float(renderwidth)) * 2.0 - 1.0, 1.0 - (py / float(renderheight)) * 2.0

    def vertex(px, py, pu, pv):

        screenx, screeny = position(px, py)
        return [float(screenx), float(screeny), float(pu), float(pv), red, green, blue, alpha]

    return (
        vertex(x, y + height, u0, v1)
        + vertex(x + width, y + height, u1, v1)
        + vertex(x, y, u0, v0)
        + vertex(x, y, u0, v0)
        + vertex(x + width, y + height, u1, v1)
        + vertex(x + width, y, u1, v0)
    )


def _gpuuniformlocation(program, name):

    key = (int(program), bytes(name))

    if key not in _gpuuniforms:
        _gpuuniforms[key] = int(_gles.glGetUniformLocation(int(program), bytes(name)))

    return int(_gpuuniforms[key])


def _gpusetuniform1i(program, name, value):

    key = (int(program), bytes(name))
    wanted = (int(value),)

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        _gles.glUniform1i(location, wanted[0])

    _gpuuniformvalues[key] = wanted


def _gpusetuniform1f(program, name, value):

    key = (int(program), bytes(name))
    wanted = (float(value),)

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        _gles.glUniform1f(location, wanted[0])

    _gpuuniformvalues[key] = wanted


def _gpusetuniform2f(program, name, value0, value1):

    key = (int(program), bytes(name))
    wanted = (float(value0), float(value1))

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        _gles.glUniform2f(location, wanted[0], wanted[1])

    _gpuuniformvalues[key] = wanted


def _gpusetuniform3f(program, name, value0, value1, value2):

    key = (int(program), bytes(name))
    wanted = (float(value0), float(value1), float(value2))

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        _gles.glUniform3f(location, *wanted)

    _gpuuniformvalues[key] = wanted


def _gpusetuniform4f(program, name, value0, value1, value2, value3):

    key = (int(program), bytes(name))
    wanted = (float(value0), float(value1), float(value2), float(value3))

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        _gles.glUniform4f(location, *wanted)

    _gpuuniformvalues[key] = wanted


def _gpusetuniformmatrix4(program, name, values):

    wanted = tuple(float(value) for value in values)

    if len(wanted) != 16:
        raise ValueError("OpenGL matrix uniform requires sixteen values")

    key = (int(program), bytes(name))

    if _gpuuniformvalues.get(key) == wanted:
        return

    location = _gpuuniformlocation(program, name)

    if location >= 0:
        matrix = (ctypes.c_float * 16)(*wanted)
        _gles.glUniformMatrix4fv(location, 1, 0, matrix)

    _gpuuniformvalues[key] = wanted


def _gpudrawvertices(values, texture, clip, swizzle, texturealpha, mode, quads=1, rounded=False, shapesize=(1.0, 1.0), radius=0.0, unpremultiply=False, premultiplied=False, textmode=False, effect="none", blurstep=(0.0, 0.0), displayadjust=False):

    global _gpuframedraws

    if not _gpuframeactive:
        raise RuntimeError("GPU drawing requires an active managed frame")

    if not values or not _gpuclip(clip):
        return False

    # Straight-alpha primitives need separate alpha factors or every
    # translucent edge reduces the destination alpha.  Premultiplied scene
    # textures already contain RGB * alpha and therefore use ONE for the
    # source term when they are resolved onto another target.
    if premultiplied:
        _gles.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
    else:
        _gles.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)

    vertices = (ctypes.c_float * len(values))(*values)
    if mode == "blur" and gpublurinitialise():
        program = _gpublurprogram
    elif str(effect).lower() != "none" and gpueffectinitialise():
        program = _gpueffectprogram
    else:
        program = _gpuprogram

    if not program:
        raise RuntimeError("GPU drawing program is unavailable")

    size = ctypes.sizeof(vertices)
    _gpubufferensure(size)
    _gles.glBindBuffer(GL_ARRAY_BUFFER, int(_gpubuffer))
    _gles.glBufferSubData(GL_ARRAY_BUFFER, 0, size, ctypes.cast(vertices, ctypes.c_void_p))
    _gles.glUseProgram(program)
    _gles.glActiveTexture(GL_TEXTURE0)
    _gles.glBindTexture(GL_TEXTURE_2D, int(texture))

    _gpusetuniform1i(program, b"surface", 0)

    for name, value in (
        (b"texturemode", 1.0 if mode in ("texture", "blur") else 0.0),
        (b"swizzle", 1.0 if swizzle else 0.0),
        (b"texturealpha", 1.0 if texturealpha else 0.0),
        (b"textmode", 1.0 if textmode else 0.0),
        (b"shadowmode", 1.0 if mode == "shadow" else 0.0),
        (b"effectmode", float({"none": 0, "grayscale": 1, "invert": 2, "sepia": 3}.get(str(effect).lower(), 0))),
        (b"unpremultiply", 1.0 if unpremultiply else 0.0),
        (b"premultiplied", 1.0 if premultiplied else 0.0),
        (b"roundedmode", 1.0 if rounded else 0.0),
        (b"cornerradius", max(0.0, float(radius))),
        (b"displayadjust", 1.0 if displayadjust else 0.0),
        (b"displaybrightness", float(DISPLAYBRIGHTNESS) / 100.0),
        (b"displaycontrast", float(DISPLAYCONTRAST) / 100.0),
        (b"displaysaturation", float(DISPLAYEFFECTIVESATURATION) / 100.0),
        (b"opacity", 1.0),
    ):

        _gpusetuniform1f(program, name, value)

    _gpusetuniform3f(
        program, b"displaychannels",
        float(DISPLAYCHANNELS[0]),
        float(DISPLAYCHANNELS[1]),
        float(DISPLAYCHANNELS[2]))
    _gpusetuniform2f(program, b"shapesize", max(1.0, float(shapesize[0])), max(1.0, float(shapesize[1])))
    _gpusetuniform2f(program, b"blurstep", max(0.0, float(blurstep[0])), max(0.0, float(blurstep[1])))

    stride = ctypes.sizeof(ctypes.c_float) * 8
    _gles.glEnableVertexAttribArray(0)
    _gles.glEnableVertexAttribArray(1)
    _gles.glEnableVertexAttribArray(2)
    _gles.glVertexAttribPointer(0, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(0))
    _gles.glVertexAttribPointer(1, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 2))
    _gles.glVertexAttribPointer(2, 4, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 4))
    _gles.glDrawArrays(GL_TRIANGLES, 0, len(values) // 8)
    _gles.glDisableVertexAttribArray(0)
    _gles.glDisableVertexAttribArray(1)
    _gles.glDisableVertexAttribArray(2)
    _gles.glBindBuffer(GL_ARRAY_BUFFER, 0)
    _gpuframedraws += 1
    _gputelemetry["draw_calls"] += 1
    _gputelemetry["batch_draws"] += 1
    _gputelemetry["batched_quads"] += int(quads)
    _gputelemetry["maximum_batch_quads"] = max(int(_gputelemetry["maximum_batch_quads"]), int(quads))
    _gputelemetry["vertex_upload_bytes"] += int(size)
    return True


def gpubatchquads(quads, texture=0, clip=None, swizzle=False, texturealpha=False, mode="solid", effect="none", textmode=False):

    if not isinstance(quads, (list, tuple)) or not quads:
        return 0

    drawn = 0

    for start in range(0, len(quads), GPUBATCHQUADLIMIT):

        values = []
        chunk = quads[start:start + GPUBATCHQUADLIMIT]

        for quad in chunk:

            values.extend(_gpuquadvertices(
                quad.get("x", 0),
                quad.get("y", 0),
                quad.get("width", 0),
                quad.get("height", 0),
                quad.get("u0", 0.0),
                quad.get("v0", 0.0),
                quad.get("u1", 1.0),
                quad.get("v1", 1.0),
                quad.get("color", (255, 255, 255, 255)),
                quad.get("opacity", 1.0),
                quad.get("rotation", 0.0),
                quad.get("origin"),
            ))

        if values and _gpudrawvertices(values, texture, clip, swizzle, texturealpha, mode, quads=len(chunk), textmode=textmode, effect=effect):
            drawn += len(chunk)

    return drawn


def gpubatchrects(rectangles, clip=None, effect="none"):

    quads = []

    for value in rectangles or []:

        try:
            x, y, width, height, color = value[:5]
            opacity = value[5] if len(value) > 5 else 1.0
        except Exception:
            continue

        quads.append({
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "color": color,
            "opacity": opacity,
        })

    drawn = gpubatchquads(quads, texture=0, clip=clip, mode="solid", effect=effect)

    if drawn:
        _gputelemetry["rectangle_batch_draws"] += 1
        _gputelemetry["rectangle_batched_quads"] += int(drawn)

    return drawn


def gpubatchroundedrects(rectangles, clip=None, effect="none"):

    if not isinstance(rectangles, (list, tuple)) or not rectangles:
        return 0

    drawn = 0

    for start in range(0, len(rectangles), GPUBATCHQUADLIMIT):

        values = []
        chunk = rectangles[start:start + GPUBATCHQUADLIMIT]
        shapesize = None
        radius = None

        for value in chunk:

            try:
                x, y, width, height, color, cornerradius = value[:6]
                opacity = value[6] if len(value) > 6 else 1.0
                rotation = value[7] if len(value) > 7 else 0.0
                origin = value[8] if len(value) > 8 else None
                width = float(width)
                height = float(height)
                cornerradius = max(0.0, min(float(cornerradius), min(width, height) * 0.5))
            except Exception:
                continue

            current = (round(width, 4), round(height, 4), round(cornerradius, 4))

            if shapesize is None:
                shapesize = (width, height)
                radius = cornerradius
            elif current != (round(shapesize[0], 4), round(shapesize[1], 4), round(radius, 4)):
                raise ValueError("rounded rectangle batches require matching dimensions and radii")

            values.extend(_gpuquadvertices(
                x,
                y,
                width,
                height,
                0.0,
                0.0,
                1.0,
                1.0,
                color,
                opacity,
                rotation=rotation,
                origin=origin,
            ))

        quads = len(values) // (6 * 8)

        if values and _gpudrawvertices(
            values,
            0,
            clip,
            False,
            False,
            "solid",
            quads=quads,
            rounded=True,
            shapesize=shapesize,
            radius=radius,
            effect=effect,
        ):
            drawn += quads
            _gputelemetry["rounded_batch_draws"] += 1
            _gputelemetry["rounded_batched_quads"] += int(quads)

    return drawn


def gpubatchcircles(circles, clip=None, effect="none"):

    rectangles = []

    for value in circles or []:

        try:
            cx, cy, radius, color = value[:4]
            opacity = value[4] if len(value) > 4 else 1.0
            radius = max(0.5, float(radius))
        except Exception:
            continue

        rectangles.append((
            float(cx) - radius,
            float(cy) - radius,
            radius * 2.0,
            radius * 2.0,
            color,
            radius,
            opacity,
        ))

    before = int(_gputelemetry["rounded_batch_draws"])
    drawn = gpubatchroundedrects(rectangles, clip=clip, effect=effect)

    if drawn:
        _gputelemetry["circle_batch_draws"] += max(1, int(_gputelemetry["rounded_batch_draws"]) - before)
        _gputelemetry["circle_batched_quads"] += int(drawn)

    return drawn


def _gpudrawquad(texture, x, y, width, height, u0, v0, u1, v1, tint, opacity, clip, swizzle, texturealpha, mode, effect="none", shapesize=(1.0, 1.0), radius=0.0, blurstep=(0.0, 0.0), premultiplied=False, displayadjust=False):

    values = _gpuquadvertices(x, y, width, height, u0, v0, u1, v1, tint, opacity=opacity)
    return _gpudrawvertices(values, texture, clip, swizzle, texturealpha, mode, quads=1, shapesize=shapesize, radius=radius, premultiplied=premultiplied, effect=effect, blurstep=blurstep, displayadjust=displayadjust)


def gpudrawtexture(handle, x, y, width=None, height=None, src=None, opacity=1.0, clip=None, scale=1.0, tint=(255, 255, 255, 255), rotation=0.0, origin=None, flip_y=False, unpremultiply=False, effect="none", premultiplied=None):

    resource = _gputextures.get(int(handle))

    if resource is None:
        raise KeyError(f"unknown managed GPU texture {handle}")

    if premultiplied is None:
        premultiplied = bool(resource.get("premultiplied", False))

    width = float(resource["width"] if width is None else width)
    height = float(resource["height"] if height is None else height)
    scale = max(0.01, min(16.0, float(scale)))
    scaledwidth = width * scale
    scaledheight = height * scale
    x = float(x) - (scaledwidth - width) * 0.5
    y = float(y) - (scaledheight - height) * 0.5

    if src is None:
        sx = 0.0
        sy = 0.0
        sw = float(resource["width"])
        sh = float(resource["height"])
    else:
        sx, sy, sw, sh = [float(value) for value in src]

    if sw <= 0.0 or sh <= 0.0:
        return False

    u0 = sx / float(resource["width"])
    v0 = sy / float(resource["height"])
    u1 = (sx + sw) / float(resource["width"])
    v1 = (sy + sh) / float(resource["height"])

    if flip_y:
        v0, v1 = v1, v0

    values = _gpuquadvertices(x, y, scaledwidth, scaledheight, u0, v0, u1, v1, tint, opacity, rotation=rotation, origin=origin)
    return _gpudrawvertices(
        values,
        resource["texture"],
        clip,
        str(resource["format"]).upper() == "BGRA32",
        bool(resource.get("alpha", True)),
        "texture",
        quads=1,
        unpremultiply=unpremultiply,
        premultiplied=premultiplied,
        effect=effect,
    )


def gpudrawrect(x, y, width, height, color, opacity=1.0, clip=None, rotation=0.0, origin=None, effect="none"):

    values = _gpuquadvertices(x, y, width, height, 0.0, 0.0, 1.0, 1.0, color, opacity, rotation=rotation, origin=origin)
    return _gpudrawvertices(values, 0, clip, False, False, "solid", quads=1, effect=effect)


def gpudrawroundedrect(x, y, width, height, color, radius=8.0, opacity=1.0, clip=None, rotation=0.0, origin=None, effect="none"):

    width = float(width)
    height = float(height)
    radius = max(0.0, min(float(radius), min(width, height) * 0.5))
    values = _gpuquadvertices(x, y, width, height, 0.0, 0.0, 1.0, 1.0, color, opacity=opacity, rotation=rotation, origin=origin)
    return _gpudrawvertices(
        values,
        0,
        clip,
        False,
        False,
        "solid",
        quads=1,
        rounded=True,
        shapesize=(width, height),
        radius=radius,
        effect=effect,
    )


def gpudrawcircle(cx, cy, radius, color, opacity=1.0, clip=None, effect="none"):

    radius = max(0.5, float(radius))
    return gpudrawroundedrect(
        float(cx) - radius,
        float(cy) - radius,
        radius * 2.0,
        radius * 2.0,
        color,
        radius=radius,
        opacity=opacity,
        clip=clip,
        effect=effect,
    )


def _gpuvertexvalue(x, y, u, v, color, opacity=1.0):

    renderwidth, renderheight = _gpurendersize()
    px = (float(x) / float(renderwidth)) * 2.0 - 1.0
    py = 1.0 - (float(y) / float(renderheight)) * 2.0
    red, green, blue, alpha = _gpucolor(color)
    alpha *= max(0.0, min(1.0, float(opacity)))
    return [px, py, float(u), float(v), red, green, blue, alpha]


def _gpugradientvertices(x, y, width, height, color, color2, direction="vertical", opacity=1.0, rotation=0.0, origin=None):

    x = float(x)
    y = float(y)
    width = float(width)
    height = float(height)

    if width <= 0.0 or height <= 0.0:
        return []

    if str(direction).lower() == "horizontal":
        topleft = bottomleft = color
        topright = bottomright = color2
    else:
        topleft = topright = color
        bottomleft = bottomright = color2

    def point(px, py):

        if not float(rotation):
            return px, py

        if origin is None:
            ox = x + width * 0.5
            oy = y + height * 0.5
        else:
            ox, oy = [float(value) for value in origin]

        radians = math.radians(float(rotation))
        cosine = math.cos(radians)
        sine = math.sin(radians)
        dx = px - ox
        dy = py - oy
        return ox + dx * cosine - dy * sine, oy + dx * sine + dy * cosine

    bottomleftpoint = point(x, y + height)
    bottomrightpoint = point(x + width, y + height)
    topleftpoint = point(x, y)
    toprightpoint = point(x + width, y)

    return (
        _gpuvertexvalue(*bottomleftpoint, 0.0, 1.0, bottomleft, opacity)
        + _gpuvertexvalue(*bottomrightpoint, 1.0, 1.0, bottomright, opacity)
        + _gpuvertexvalue(*topleftpoint, 0.0, 0.0, topleft, opacity)
        + _gpuvertexvalue(*topleftpoint, 0.0, 0.0, topleft, opacity)
        + _gpuvertexvalue(*bottomrightpoint, 1.0, 1.0, bottomright, opacity)
        + _gpuvertexvalue(*toprightpoint, 1.0, 0.0, topright, opacity)
    )


def gpudrawgradient(x, y, width, height, color, color2, direction="vertical", opacity=1.0, clip=None, rotation=0.0, origin=None, effect="none"):

    vertices = _gpugradientvertices(
        x,
        y,
        width,
        height,
        color,
        color2,
        direction=direction,
        opacity=opacity,
        rotation=rotation,
        origin=origin,
    )
    return _gpudrawvertices(vertices, 0, clip, False, False, "solid", quads=1, effect=effect)


def gpubatchgradients(gradients, clip=None, effect="none"):

    if not isinstance(gradients, (list, tuple)) or not gradients:
        return 0

    drawn = 0

    for start in range(0, len(gradients), GPUBATCHQUADLIMIT):

        values = []
        chunk = gradients[start:start + GPUBATCHQUADLIMIT]

        for value in chunk:

            try:
                x, y, width, height, color, color2 = value[:6]
                direction = value[6] if len(value) > 6 else "vertical"
                opacity = value[7] if len(value) > 7 else 1.0
                rotation = value[8] if len(value) > 8 else 0.0
                origin = value[9] if len(value) > 9 else None
            except Exception:
                continue

            values.extend(_gpugradientvertices(
                x,
                y,
                width,
                height,
                color,
                color2,
                direction=direction,
                opacity=opacity,
                rotation=rotation,
                origin=origin,
            ))

        quads = len(values) // (6 * 8)

        if values and _gpudrawvertices(values, 0, clip, False, False, "solid", quads=quads, effect=effect):
            drawn += quads
            _gputelemetry["gradient_batch_draws"] += 1
            _gputelemetry["gradient_batched_quads"] += int(quads)

    return drawn


def _gpulinevertices(x0, y0, x1, y1, color, width=1.0, opacity=1.0):

    x0 = float(x0)
    y0 = float(y0)
    x1 = float(x1)
    y1 = float(y1)
    linewidth = max(0.5, float(width))
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)

    if length <= 0.0001:
        return []

    directionx = dx / length
    directiony = dy / length
    normalx = -directiony
    normaly = directionx
    halfwidth = linewidth * 0.5
    halflength = length * 0.5
    antialias = 1.0
    extentx = halflength + halfwidth + antialias
    extenty = halfwidth + antialias
    centerx = (x0 + x1) * 0.5
    centery = (y0 + y1) * 0.5
    red, green, blue, alpha = _gpucolor(color)
    alpha *= max(0.0, min(1.0, float(opacity)))
    renderwidth, renderheight = _gpurendersize()

    def vertex(localx, localy):

        px = centerx + directionx * localx + normalx * localy
        py = centery + directiony * localx + normaly * localy
        screenx = (px / float(renderwidth)) * 2.0 - 1.0
        screeny = 1.0 - (py / float(renderheight)) * 2.0
        return [screenx, screeny, localx, localy, red, green, blue, alpha, halflength, halfwidth]

    a = vertex(-extentx, extenty)
    b = vertex(extentx, extenty)
    c = vertex(-extentx, -extenty)
    d = vertex(extentx, -extenty)
    return (
        a + c + b + b + c + d
    )


def _gpudrawlinevertices(values, clip=None, effect="none", segments=1):

    global _gpuframedraws

    if not values or not _gpuclip(clip):
        return False

    if not gpulineinitialise():
        raise RuntimeError("analytic GPU line program is unavailable")

    vertices = (ctypes.c_float * len(values))(*values)
    size = ctypes.sizeof(vertices)
    _gpubufferensure(size)
    _gles.glBindBuffer(GL_ARRAY_BUFFER, int(_gpubuffer))
    _gles.glBufferSubData(GL_ARRAY_BUFFER, 0, size, ctypes.cast(vertices, ctypes.c_void_p))
    _gles.glUseProgram(int(_gpulineprogram))
    _gpusetuniform1f(
        _gpulineprogram,
        b"effectmode",
        float({"none": 0, "grayscale": 1, "invert": 2, "sepia": 3}.get(str(effect).lower(), 0)),
    )
    stride = ctypes.sizeof(ctypes.c_float) * 10
    _gles.glEnableVertexAttribArray(0)
    _gles.glEnableVertexAttribArray(1)
    _gles.glEnableVertexAttribArray(2)
    _gles.glEnableVertexAttribArray(3)
    _gles.glVertexAttribPointer(0, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(0))
    _gles.glVertexAttribPointer(1, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 2))
    _gles.glVertexAttribPointer(2, 4, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 4))
    _gles.glVertexAttribPointer(3, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 8))
    _gles.glDrawArrays(GL_TRIANGLES, 0, len(values) // 10)
    _gles.glDisableVertexAttribArray(0)
    _gles.glDisableVertexAttribArray(1)
    _gles.glDisableVertexAttribArray(2)
    _gles.glDisableVertexAttribArray(3)
    _gles.glBindBuffer(GL_ARRAY_BUFFER, 0)
    _gpuframedraws += 1
    _gputelemetry["draw_calls"] += 1
    _gputelemetry["batch_draws"] += 1
    _gputelemetry["batched_quads"] += int(segments)
    _gputelemetry["maximum_batch_quads"] = max(int(_gputelemetry["maximum_batch_quads"]), int(segments))
    _gputelemetry["vertex_upload_bytes"] += int(size)
    _gputelemetry["aa_2d_line_draws"] += 1
    _gputelemetry["aa_2d_line_segments"] += int(segments)
    return True


def gpudrawline(x0, y0, x1, y1, color, width=1.0, opacity=1.0, clip=None, effect="none"):

    vertices = _gpulinevertices(x0, y0, x1, y1, color, width=width, opacity=opacity)

    if not vertices:
        return gpudrawcircle(x0, y0, max(0.5, float(width)) * 0.5, color, opacity=opacity, clip=clip, effect=effect)

    return _gpudrawlinevertices(vertices, clip=clip, effect=effect, segments=1)


def gpubatchlines(lines, clip=None, effect="none"):

    if not isinstance(lines, (list, tuple)) or not lines:
        return 0

    drawn = 0

    for start in range(0, len(lines), GPUBATCHQUADLIMIT):

        values = []
        points = 0
        chunk = lines[start:start + GPUBATCHQUADLIMIT]

        for value in chunk:

            try:
                x0, y0, x1, y1, color = value[:5]
                width = value[5] if len(value) > 5 else 1.0
                opacity = value[6] if len(value) > 6 else 1.0
            except Exception:
                continue

            vertices = _gpulinevertices(x0, y0, x1, y1, color, width=width, opacity=opacity)

            if vertices:
                values.extend(vertices)
                points += 1
            else:
                gpudrawcircle(x0, y0, max(0.5, float(width)) * 0.5, color, opacity=opacity, clip=clip, effect=effect)
                drawn += 1

        if values and _gpudrawlinevertices(values, clip=clip, effect=effect, segments=points):
            drawn += points
            _gputelemetry["line_batch_draws"] += 1
            _gputelemetry["line_batched_quads"] += int(points)

    return drawn


def gpudrawshadow(x, y, width, height, radius=16, opacity=0.35, color=(0, 0, 0, 255), clip=None):

    radius = max(1.0, min(128.0, float(radius)))
    return _gpudrawquad(
        0,
        float(x) - radius,
        float(y) - radius,
        float(width) + radius * 2.0,
        float(height) + radius * 2.0,
        0.0,
        0.0,
        1.0,
        1.0,
        color,
        opacity,
        clip,
        False,
        False,
        "shadow",
        shapesize=(float(width) + radius * 2.0, float(height) + radius * 2.0),
        radius=radius,
    )


def gpudrawblur(x, y, width, height, radius=12, opacity=1.0, clip=None):

    global _gpublurcache

    if not _gpuframeactive:
        raise RuntimeError("GPU backdrop blur requires an active managed frame")

    renderwidth, renderheight = _gpurendersize()
    left = max(0, int(math.floor(float(x))))
    top = max(0, int(math.floor(float(y))))
    right = min(int(renderwidth), int(math.ceil(float(x) + float(width))))
    bottom = min(int(renderheight), int(math.ceil(float(y) + float(height))))

    if clip is not None:
        clipx, clipy, clipwidth, clipheight = [int(value) for value in clip]
        left = max(left, clipx)
        top = max(top, clipy)
        right = min(right, clipx + clipwidth)
        bottom = min(bottom, clipy + clipheight)

    if _gpuframeclip is not None:
        clipx, clipy, clipwidth, clipheight = [int(value) for value in _gpuframeclip]
        left = max(left, clipx)
        top = max(top, clipy)
        right = min(right, clipx + clipwidth)
        bottom = min(bottom, clipy + clipheight)

    copywidth = right - left
    copyheight = bottom - top

    if copywidth < 1 or copyheight < 1:
        return False

    key = (copywidth, copyheight)
    cached = _gpublurcache.get(key)

    if cached is None or gputextureinfo(cached.get("handle", 0)) is None:
        cached = {
            "handle": gputexturecreate(
                copywidth,
                copyheight,
                fmt="RGBA32",
                owner="backdrop-blur",
                alpha=False,
                storage="RGB",
            ),
            "used": 0.0,
        }
        _gpublurcache[key] = cached

    cached["used"] = time.monotonic()

    while len(_gpublurcache) > 4:
        oldkey = min(_gpublurcache, key=lambda value: float(_gpublurcache[value].get("used", 0.0)))
        old = _gpublurcache.pop(oldkey)
        gputexturedestroy(old.get("handle", 0))

    resource = _gputextures.get(int(cached["handle"]))

    if resource is None:
        return False

    _gles.glActiveTexture(GL_TEXTURE0)
    _gles.glBindTexture(GL_TEXTURE_2D, int(resource["texture"]))
    _gles.glCopyTexSubImage2D(
        GL_TEXTURE_2D,
        0,
        0,
        0,
        int(left),
        int(renderheight) - int(bottom),
        int(copywidth),
        int(copyheight),
    )
    gpuhealthsample(
        operation="backdrop-blur framebuffer preservation copy",
    )
    _gputelemetry["blur_copies"] += 1
    _gputelemetry["blur_pixels"] += int(copywidth * copyheight)
    sample = max(0.5, min(32.0, float(radius)))
    return _gpudrawquad(
        int(resource["texture"]),
        left,
        top,
        copywidth,
        copyheight,
        0.0,
        1.0,
        1.0,
        0.0,
        (255, 255, 255, 255),
        max(0.0, min(1.0, float(opacity))),
        [left, top, copywidth, copyheight],
        False,
        False,
        "blur",
        blurstep=(sample / float(copywidth), sample / float(copyheight)),
    )


def _gpuimagehandle(path, sourcewidth, sourceheight, fmt="BGRA32", revision=None):

    path = str(path)
    key = (path, int(sourcewidth), int(sourceheight), str(fmt).upper())
    state = None

    try:
        stat = os.stat(path)
        state = (int(stat.st_size), int(stat.st_mtime_ns), None if revision is None else int(revision))
    except Exception:
        state = None

    cached = _gpuimagecache.get(key)

    if cached is None or gputextureinfo(cached.get("handle", 0)) is None:

        if cached is not None:
            gputexturedestroy(cached.get("handle", 0))

        handle = gputexturecreate(sourcewidth, sourceheight, fmt=fmt, owner="image")

        try:
            gputextureupdate(handle, path=path, stride=int(sourcewidth) * 4)
        except Exception:
            gputexturedestroy(handle)
            raise

        cached = {"handle": handle, "state": state}
        _gpuimagecache[key] = cached

        while len(_gpuimagecache) > GPUIMAGECACHECAP:

            oldkey = next(iter(_gpuimagecache))
            old = _gpuimagecache.pop(oldkey)
            gputexturedestroy(old.get("handle", 0))

    elif cached.get("state") != state:

        gputextureupdate(cached.get("handle", 0), path=path, stride=int(sourcewidth) * 4)
        cached["state"] = state

    return int(cached["handle"])


def gpudrawimage(path, sourcewidth, sourceheight, x, y, width=None, height=None, fmt="BGRA32", opacity=1.0, clip=None, scale=1.0, rotation=0.0, origin=None, effect="none", revision=None):

    return gpudrawtexture(
        _gpuimagehandle(path, sourcewidth, sourceheight, fmt=fmt, revision=revision),
        x,
        y,
        sourcewidth if width is None else width,
        sourceheight if height is None else height,
        opacity=opacity,
        clip=clip,
        scale=scale,
        rotation=rotation,
        origin=origin,
        effect=effect,
    )


def _gpu3dvector(value, default):

    try:
        values = [float(item) for item in value]

        if len(values) == 3:
            return values

    except Exception:
        pass

    return [float(item) for item in default]


def _gpu3dnormalise(value, default=(0.0, 0.0, 0.0)):

    x, y, z = _gpu3dvector(value, default)
    length = math.sqrt(x * x + y * y + z * z)

    if length <= 0.000001:
        return [float(item) for item in default]

    return [x / length, y / length, z / length]


def _gpu3dcross(left, right):

    return [
        float(left[1]) * float(right[2]) - float(left[2]) * float(right[1]),
        float(left[2]) * float(right[0]) - float(left[0]) * float(right[2]),
        float(left[0]) * float(right[1]) - float(left[1]) * float(right[0]),
    ]


def _gpu3ddot(left, right):

    return sum(float(left[index]) * float(right[index]) for index in range(3))


def _gpu3dmultiply(left, right):

    output = [0.0] * 16

    for column in range(4):

        for row in range(4):
            output[column * 4 + row] = sum(
                float(left[index * 4 + row]) * float(right[column * 4 + index])
                for index in range(4)
            )

    return output


def _gpu3dmodel(position, rotation, scale):

    px, py, pz = _gpu3dvector(position, (0.0, 0.0, 0.0))
    rx, ry, rz = [math.radians(value) for value in _gpu3dvector(rotation, (0.0, 0.0, 0.0))]
    sx, sy, sz = _gpu3dvector(scale, (1.0, 1.0, 1.0))
    translation = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, px, py, pz, 1.0]
    scaling = [sx, 0.0, 0.0, 0.0, 0.0, sy, 0.0, 0.0, 0.0, 0.0, sz, 0.0, 0.0, 0.0, 0.0, 1.0]
    rotationx = [1.0, 0.0, 0.0, 0.0, 0.0, math.cos(rx), math.sin(rx), 0.0, 0.0, -math.sin(rx), math.cos(rx), 0.0, 0.0, 0.0, 0.0, 1.0]
    rotationy = [math.cos(ry), 0.0, -math.sin(ry), 0.0, 0.0, 1.0, 0.0, 0.0, math.sin(ry), 0.0, math.cos(ry), 0.0, 0.0, 0.0, 0.0, 1.0]
    rotationz = [math.cos(rz), math.sin(rz), 0.0, 0.0, -math.sin(rz), math.cos(rz), 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    return _gpu3dmultiply(translation, _gpu3dmultiply(rotationz, _gpu3dmultiply(rotationy, _gpu3dmultiply(rotationx, scaling))))


def _gpu3dview(position, target, up):

    eye = _gpu3dvector(position, (0.0, 0.0, 6.0))
    wanted = _gpu3dvector(target, (0.0, 0.0, 0.0))
    forward = _gpu3dnormalise([wanted[index] - eye[index] for index in range(3)], (0.0, 0.0, -1.0))
    side = _gpu3dnormalise(_gpu3dcross(forward, _gpu3dnormalise(up, (0.0, 1.0, 0.0))), (1.0, 0.0, 0.0))
    upward = _gpu3dcross(side, forward)
    return [
        side[0], upward[0], -forward[0], 0.0,
        side[1], upward[1], -forward[1], 0.0,
        side[2], upward[2], -forward[2], 0.0,
        -_gpu3ddot(side, eye), -_gpu3ddot(upward, eye), _gpu3ddot(forward, eye), 1.0,
    ]


def _gpu3dprojection(camera, aspect):

    near = max(0.001, float(camera.get("near", 0.1)))
    far = max(near + 0.01, float(camera.get("far", 100.0)))
    aspect = max(0.01, float(aspect))

    if str(camera.get("projection", "perspective")) == "orthographic":
        size = max(0.01, float(camera.get("orthographic_size", 5.0)))
        right = size * aspect
        left = -right
        top = size
        bottom = -top
        return [
            2.0 / (right - left), 0.0, 0.0, 0.0,
            0.0, 2.0 / (top - bottom), 0.0, 0.0,
            0.0, 0.0, -2.0 / (far - near), 0.0,
            -(right + left) / (right - left), -(top + bottom) / (top - bottom), -(far + near) / (far - near), 1.0,
        ]

    fov = max(10.0, min(150.0, float(camera.get("fov", 50.0))))
    scale = 1.0 / math.tan(math.radians(fov) * 0.5)
    return [
        scale / aspect, 0.0, 0.0, 0.0,
        0.0, scale, 0.0, 0.0,
        0.0, 0.0, (far + near) / (near - far), -1.0,
        0.0, 0.0, (2.0 * far * near) / (near - far), 0.0,
    ]


def _gpu3dvertex(position, normal, texcoord):

    return tuple(float(value) for value in (*position, *normal, *texcoord))


def _gpu3dmeshvertices(mesh):

    cached = mesh.get("_gpu_vertices")

    if isinstance(cached, tuple):
        return cached

    primitive = str(mesh.get("primitive", "cube"))
    values = []

    if primitive == "cube":

        faces = (
            ((0, 0, 1), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
            ((0, 0, -1), ((1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1))),
            ((1, 0, 0), ((1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1))),
            ((-1, 0, 0), ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1))),
            ((0, 1, 0), ((-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1))),
            ((0, -1, 0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
        )
        texcoords = ((0, 1), (1, 1), (1, 0), (0, 0))

        for normal, corners in faces:

            for index in (0, 1, 2, 0, 2, 3):
                values.extend(_gpu3dvertex(corners[index], normal, texcoords[index]))

    elif primitive == "plane":

        corners = ((-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1))
        texcoords = ((0, 0), (1, 0), (1, 1), (0, 1))

        for index in (0, 1, 2, 0, 2, 3):
            values.extend(_gpu3dvertex(corners[index], (0, 1, 0), texcoords[index]))

    elif primitive == "sphere":

        segments = max(6, min(32, int(mesh.get("subdivisions", 16))))
        rings = max(4, segments // 2)

        for ring in range(rings):

            latitude0 = math.pi * (-0.5 + ring / rings)
            latitude1 = math.pi * (-0.5 + (ring + 1) / rings)

            for segment in range(segments):

                longitude0 = math.pi * 2.0 * segment / segments
                longitude1 = math.pi * 2.0 * (segment + 1) / segments
                points = []

                for latitude, longitude, u, v in (
                    (latitude0, longitude0, segment / segments, ring / rings),
                    (latitude0, longitude1, (segment + 1) / segments, ring / rings),
                    (latitude1, longitude1, (segment + 1) / segments, (ring + 1) / rings),
                    (latitude1, longitude0, segment / segments, (ring + 1) / rings),
                ):
                    normal = (math.cos(latitude) * math.cos(longitude), math.sin(latitude), math.cos(latitude) * math.sin(longitude))
                    points.append(_gpu3dvertex(normal, normal, (u, v)))

                for index in (0, 1, 2, 0, 2, 3):
                    values.extend(points[index])

    else:

        source = [tuple(float(item) for item in vertex[:8]) for vertex in mesh.get("vertices", [])]
        indices = [int(value) for value in mesh.get("indices", [])]

        if not indices:
            indices = list(range(len(source)))

        for index in indices:
            values.extend(source[index])

    mesh["_gpu_vertices"] = tuple(values)
    return mesh["_gpu_vertices"]


def _gpu3dwirevertices(values):

    stride = 8
    output = []
    edges = {}

    for start in range(0, len(values), stride * 3):

        triangle = [values[start + stride * index:start + stride * (index + 1)] for index in range(3)]

        if len(triangle[-1]) != stride:
            continue

        for left, right in ((0, 1), (1, 2), (2, 0)):

            first = triangle[left]
            second = triangle[right]
            firstkey = tuple(round(float(value), 6) for value in first[:3])
            secondkey = tuple(round(float(value), 6) for value in second[:3])
            key = tuple(sorted((firstkey, secondkey)))

            if firstkey == secondkey or key in edges:
                continue

            edges[key] = (first, second)

    corners = ((0.0, -1.0), (1.0, -1.0), (0.0, 1.0), (0.0, 1.0), (1.0, -1.0), (1.0, 1.0))

    for first, second in edges.values():

        for endpoint, side in corners:

            normal = first[3:6] if endpoint < 0.5 else second[3:6]
            output.extend((*first[:3], endpoint, side, *normal, *second[:3]))

    return output, len(edges)


def _gpu3daatarget(width, height):

    width = max(1, int(width))
    height = max(1, int(height))

    if width > GPUAAMAXDIMENSION or height > GPUAAMAXDIMENSION:
        return None

    key = (width, height)
    cached = _gpu3daatargets.get(key)

    if isinstance(cached, dict) and gputextureinfo(cached.get("handle")) is not None:
        cached["used"] = time.monotonic()
        return int(cached["handle"])

    _gpu3daatargets.pop(key, None)

    while len(_gpu3daatargets) >= GPUAATARGETCAP:

        oldkey = min(_gpu3daatargets, key=lambda value: float(_gpu3daatargets[value].get("used", 0.0)))
        old = _gpu3daatargets.pop(oldkey)
        gputargetdestroy(old.get("handle", 0))

    try:

        handle = gputargetcreate(width, height, owner=f"controlled-3d-aa:{width}x{height}")

    except (MemoryError, RuntimeError):

        return None

    _gpu3daatargets[key] = {"handle": int(handle), "used": time.monotonic()}
    targetbytes = sum(
        int(keyvalue[0]) * int(keyvalue[1]) * 6
        for keyvalue in _gpu3daatargets
    )
    _gputelemetry["maximum_aa_target_bytes"] = max(int(_gputelemetry["maximum_aa_target_bytes"]), int(targetbytes))
    return int(handle)


def _gpu3daamode(scene):

    requested = str(scene.get("antialias", "auto")).lower()

    if requested not in ("auto", "analytic", "quality"):
        requested = "auto"

    renderer = str(_glrenderer or "").lower()
    software = any(value in renderer for value in ("softpipe", "llvmpipe", "swrast", "software rasterizer"))

    if requested == "analytic":
        return "analytic"

    if requested == "quality":
        return "quality"

    return "analytic" if software else "quality"


def _gpudrawscene3dcore(scene, x, y, width, height, opacity=1.0, clip=None, elapsed=0.0, pixel_scale=1.0):

    global _gpuframedraws

    if not _gpuframeactive or not _gputargetactive:
        raise RuntimeError("controlled 3D drawing requires an active managed render target")

    if not gpu3dinitialise() or not _gpuclip(clip):
        return 0

    _gputargetdepthensure(int(_gputargetactive))
    renderwidth, renderheight = _gpurendersize()
    viewportx = max(0, int(round(float(x))))
    viewporttop = max(0, int(round(float(y))))
    viewportwidth = max(1, min(int(renderwidth) - viewportx, int(round(float(width)))))
    viewportheight = max(1, min(int(renderheight) - viewporttop, int(round(float(height)))))
    viewporty = max(0, int(renderheight) - viewporttop - viewportheight)
    camera = scene.get("camera", {})
    cameraposition = _gpu3dvector(camera.get("position", [0, 0, 6]), (0, 0, 6))
    view = _gpu3dview(cameraposition, camera.get("target", [0, 0, 0]), camera.get("up", [0, 1, 0]))
    projection = _gpu3dprojection(camera, viewportwidth / max(1.0, float(viewportheight)))
    ambient = scene.get("ambient", {})
    light = scene.get("light", {})
    fog = scene.get("fog", {})
    ambientcolor = _gpucolor(ambient.get("color", [255, 255, 255, 255]))
    lightcolor = _gpucolor(light.get("color", [255, 255, 255, 255]))
    fogcolor = _gpucolor(fog.get("color", [17, 19, 24, 255]))
    lightdirection = _gpu3dnormalise(light.get("direction", [-0.4, -0.8, -0.6]), (-0.4, -0.8, -0.6))
    postprocess = float({"none": 0, "grayscale": 1, "invert": 2, "sepia": 3}.get(str(scene.get("postprocess", "none")), 0))
    meshes = list(scene.get("meshes", []))
    meshes.sort(key=lambda value: float(value.get("material", {}).get("opacity", 1.0)) < 0.999)
    drawn = 0

    try:
        _gles.glViewport(viewportx, viewporty, viewportwidth, viewportheight)
        _gles.glEnable(GL_DEPTH_TEST)
        _gles.glDepthFunc(GL_LEQUAL)
        _gles.glDepthMask(1)
        _gles.glClear(GL_DEPTH_BUFFER_BIT)
        _gputelemetry["mesh_3d_depth_clears"] += 1
        def setsceneprogram(program):

            _gles.glUseProgram(int(program))
            _gpusetuniformmatrix4(program, b"view", view)
            _gpusetuniformmatrix4(program, b"projection", projection)
            _gpusetuniform3f(program, b"cameraposition", *cameraposition)
            _gpusetuniform3f(program, b"ambientcolor", *ambientcolor[:3])
            _gpusetuniform1f(program, b"ambientintensity", max(0.0, min(4.0, float(ambient.get("intensity", 0.25)))))
            _gpusetuniform3f(program, b"lightdirection", *lightdirection)
            _gpusetuniform3f(program, b"lightcolor", *lightcolor[:3])
            _gpusetuniform1f(program, b"lightintensity", max(0.0, min(8.0, float(light.get("intensity", 0.9)))))
            _gpusetuniform1f(program, b"fogenabled", 1.0 if fog.get("enabled", False) else 0.0)
            _gpusetuniform3f(program, b"fogcolor", *fogcolor[:3])
            _gpusetuniform1f(program, b"fognear", max(0.0, float(fog.get("near", 5.0))))
            _gpusetuniform1f(program, b"fogfar", max(0.01, float(fog.get("far", 14.0))))
            _gpusetuniform1f(program, b"postprocess", postprocess)

        setsceneprogram(_gpu3dprogram)
        _gpusetuniform1i(_gpu3dprogram, b"surface", 0)

        for mesh in meshes:

            values = _gpu3dmeshvertices(mesh)

            if not values:
                continue

            wireframe = bool(mesh.get("wireframe", False))
            wiresegments = 0

            if wireframe:

                if not gpu3dlineinitialise():
                    raise RuntimeError("analytic controlled 3D wireframe program is unavailable")

                drawvalues = mesh.get("_gpu_wire_vertices")

                if drawvalues is None:
                    drawvalues, wiresegments = _gpu3dwirevertices(values)
                    drawvalues = tuple(drawvalues)
                    mesh["_gpu_wire_vertices"] = drawvalues
                    mesh["_gpu_wire_segments"] = int(wiresegments)
                else:
                    wiresegments = int(mesh.get("_gpu_wire_segments", 0))

                program = _gpu3dlineprogram
                stridevalues = 11
                setsceneprogram(program)
                _gpusetuniform2f(program, b"viewport", float(viewportwidth), float(viewportheight))
                _gpusetuniform1f(program, b"linewidth", max(1.0, min(8.0, float(mesh.get("line_width", 1.0)))) * float(pixel_scale))

            else:

                drawvalues = values
                program = _gpu3dprogram
                stridevalues = 8
                setsceneprogram(program)

            if not drawvalues:
                continue

            arraykey = (
                "_gpu_wire_vertex_array"
                if wireframe
                else "_gpu_vertex_array"
            )
            vertices = mesh.get(arraykey)

            if vertices is None:
                vertices = (ctypes.c_float * len(drawvalues))(*drawvalues)
                mesh[arraykey] = vertices

            size = ctypes.sizeof(vertices)
            _gpubufferensure(size)
            _gles.glBindBuffer(GL_ARRAY_BUFFER, int(_gpubuffer))
            _gles.glBufferSubData(GL_ARRAY_BUFFER, 0, size, ctypes.cast(vertices, ctypes.c_void_p))
            rotation = _gpu3dvector(mesh.get("rotation", [0, 0, 0]), (0, 0, 0))
            speed = _gpu3dvector(mesh.get("rotation_speed", [0, 0, 0]), (0, 0, 0))
            rotation = [rotation[index] + speed[index] * float(elapsed) for index in range(3)]
            _gpusetuniformmatrix4(program, b"model", _gpu3dmodel(mesh.get("position", [0, 0, 0]), rotation, mesh.get("scale", [1, 1, 1])))
            material = mesh.get("material", {})
            materialcolor = _gpucolor(material.get("color", [255, 255, 255, 255]))
            materialopacity = max(0.0, min(1.0, float(material.get("opacity", 1.0)) * float(opacity)))
            _gpusetuniform4f(program, b"materialcolor", materialcolor[0], materialcolor[1], materialcolor[2], materialcolor[3] * materialopacity)
            _gpusetuniform1f(program, b"shininess", max(1.0, min(256.0, float(material.get("shininess", 24.0)))))
            _gpusetuniform1f(program, b"unlit", 1.0 if material.get("unlit", False) else 0.0)
            texturehandle = material.get("texture_handle")

            if not wireframe and (texturehandle is None or gputextureinfo(texturehandle) is None) and material.get("texture"):
                texturehandle = _gpuimagehandle(
                    material["texture"],
                    int(material.get("texture_width", 0)),
                    int(material.get("texture_height", 0)),
                    fmt=material.get("texture_format", "BGRA32"),
                )
                material["texture_handle"] = int(texturehandle)

            textureresource = _gputextures.get(int(texturehandle)) if not wireframe and texturehandle is not None else None
            _gles.glActiveTexture(GL_TEXTURE0)
            _gles.glBindTexture(GL_TEXTURE_2D, int(textureresource["texture"]) if textureresource else 0)
            _gpusetuniform1f(program, b"texturemode", 1.0 if textureresource else 0.0)
            _gpusetuniform1f(program, b"swizzle", 1.0 if textureresource and str(textureresource.get("format", "")).upper() == "BGRA32" else 0.0)
            _gles.glDepthMask(0 if materialopacity < 0.999 else 1)
            stride = ctypes.sizeof(ctypes.c_float) * stridevalues
            _gles.glEnableVertexAttribArray(0)
            _gles.glEnableVertexAttribArray(1)
            _gles.glEnableVertexAttribArray(3)

            if wireframe:

                _gles.glEnableVertexAttribArray(4)
                _gles.glVertexAttribPointer(0, 3, GL_FLOAT, 0, stride, ctypes.c_void_p(0))
                _gles.glVertexAttribPointer(1, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 3))
                _gles.glVertexAttribPointer(3, 3, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 5))
                _gles.glVertexAttribPointer(4, 3, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 8))

            else:

                _gles.glVertexAttribPointer(0, 3, GL_FLOAT, 0, stride, ctypes.c_void_p(0))
                _gles.glVertexAttribPointer(3, 3, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 3))
                _gles.glVertexAttribPointer(1, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(ctypes.sizeof(ctypes.c_float) * 6))

            _gles.glDrawArrays(GL_TRIANGLES, 0, len(drawvalues) // stridevalues)
            _gles.glDisableVertexAttribArray(0)
            _gles.glDisableVertexAttribArray(1)
            _gles.glDisableVertexAttribArray(3)

            if wireframe:
                _gles.glDisableVertexAttribArray(4)

            _gpuframedraws += 1
            drawn += 1
            triangles = len(values) // 24
            _gputelemetry["draw_calls"] += 1
            _gputelemetry["mesh_3d_draws"] += 1
            _gputelemetry["mesh_3d_triangles"] += triangles
            _gputelemetry["mesh_3d_vertices"] += len(drawvalues) // stridevalues
            _gputelemetry["vertex_upload_bytes"] += int(size)

            if wireframe:

                _gputelemetry["aa_3d_wire_draws"] += 1
                _gputelemetry["aa_3d_wire_segments"] += int(wiresegments)

    finally:
        _gles.glDepthMask(1)
        _gles.glDisable(GL_DEPTH_TEST)
        _gles.glBindBuffer(GL_ARRAY_BUFFER, 0)
        _gles.glViewport(0, 0, int(renderwidth), int(renderheight))

    return drawn


def gpudrawscene3d(scene, x, y, width, height, opacity=1.0, clip=None, elapsed=0.0):

    mode = _gpu3daamode(scene)

    if mode == "quality":

        targetwidth = max(1, int(round(float(width) * GPUAASCALE)))
        targetheight = max(1, int(round(float(height) * GPUAASCALE)))
        target = _gpu3daatarget(targetwidth, targetheight)

        if target is not None:

            targetstate = gputargetbegin(target, clearcolor=(0, 0, 0, 0), clear=True)
            _gles.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)

            try:

                drawn = _gpudrawscene3dcore(
                    scene,
                    0,
                    0,
                    targetwidth,
                    targetheight,
                    opacity=1.0,
                    clip=[0, 0, targetwidth, targetheight],
                    elapsed=elapsed,
                    pixel_scale=float(GPUAASCALE),
                )

            finally:

                gputargetend(targetstate)
                _gles.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            resolvestarted = time.monotonic_ns()

            try:

                _gles.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
                gpudrawtexture(
                    target,
                    x,
                    y,
                    width=width,
                    height=height,
                    opacity=opacity,
                    clip=clip,
                    flip_y=True,
                    premultiplied=True,
                )

            finally:

                _gles.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            resolvems = (time.monotonic_ns() - resolvestarted) / 1000000.0
            _gputelemetry["aa_supersample_scenes"] += 1
            _gputelemetry["aa_supersample_pixels"] += int(targetwidth) * int(targetheight)
            _gputelemetry["aa_supersample_resolve_ms"] = round(float(_gputelemetry["aa_supersample_resolve_ms"]) + resolvems, 3)
            return drawn

        _gputelemetry["aa_quality_fallbacks"] += 1

    _gputelemetry["aa_analytic_scenes"] += 1
    return _gpudrawscene3dcore(scene, x, y, width, height, opacity=opacity, clip=clip, elapsed=elapsed)


def _gpuglyphpage(atlas, width, height):

    width = int(width)
    height = int(height)

    for page in atlas["pages"]:

        x = int(page["x"])
        y = int(page["y"])
        rowheight = int(page["row_height"])

        if x + width + 1 > GPUGLYPHATLASSIZE:
            x = 1
            y += rowheight + 1
            rowheight = 0

        if y + height + 1 <= GPUGLYPHATLASSIZE:
            page["x"] = x + width + 1
            page["y"] = y
            page["row_height"] = max(rowheight, height)
            return page, x, y

    if width + 2 > GPUGLYPHATLASSIZE or height + 2 > GPUGLYPHATLASSIZE:
        return None, 0, 0

    _gpuglyphevict(exclude=atlas)

    if sum(len(value.get("pages", [])) for value in _gpuglyphatlases.values()) >= GPUGLYPHATLASCAP:

        for oldpage in atlas.get("pages", []):
            gputexturedestroy(oldpage.get("handle", 0))

        atlas["pages"] = []
        atlas["glyphs"] = {}

    page = {
        "handle": gputexturecreate(
            GPUGLYPHATLASSIZE,
            GPUGLYPHATLASSIZE,
            fmt="RGBA32",
            owner="glyph-atlas",
            alpha=True,
        ),
        "x": width + 2,
        "y": 1,
        "row_height": height,
    }
    atlas["pages"].append(page)
    _gputelemetry["glyph_atlases"] = sum(len(value.get("pages", [])) for value in _gpuglyphatlases.values())
    return page, 1, 1


def _gpuglyphevict(exclude=None):

    while sum(len(value.get("pages", [])) for value in _gpuglyphatlases.values()) >= GPUGLYPHATLASCAP:

        candidates = [key for key, value in _gpuglyphatlases.items() if value is not exclude]

        if not candidates:
            return

        oldkey = min(candidates, key=lambda key: float(_gpuglyphatlases[key].get("used", 0.0)))
        old = _gpuglyphatlases.pop(oldkey)

        for page in old.get("pages", []):
            gputexturedestroy(page.get("handle", 0))


def _gpuglyphatlas(size, fontpath=None):

    size = max(1, min(256, int(size)))
    key = (ttffontkey(fontpath), size)
    atlas = _gpuglyphatlases.get(key)

    if atlas is not None:
        atlas["used"] = time.monotonic()
        return atlas

    face = getttfface(fontpath) if fontpath else _ttfface

    if face is None:
        return None

    _gpuglyphevict()
    face.set_pixel_sizes(0, size)
    ascender = max(1, int(face.size.ascender >> 6))
    descender = max(0, int(-(face.size.descender >> 6)))
    atlas = {
        "key": key,
        "face": face,
        "size": size,
        "ascender": ascender,
        "descender": descender,
        "height": max(1, int(face.size.height >> 6), ascender + descender),
        "loadflags": ttfloadflags(fontpath, face),
        "glyphs": {},
        "pages": [],
        "used": time.monotonic(),
    }
    _gpuglyphatlases[key] = atlas
    return atlas


def _gpuglyph(atlas, character):

    cached = atlas["glyphs"].get(character)

    if cached is not None:
        _gputelemetry["text_cache_hits"] += 1
        return cached

    _gputelemetry["text_cache_misses"] += 1
    face = atlas["face"]
    face.set_pixel_sizes(0, int(atlas["size"]))
    face.load_char(character, int(atlas.get("loadflags", FT_LOAD_T1OS_TEXT)))
    face.glyph.render(freetype.FT_RENDER_MODE_NORMAL)
    bitmap = face.glyph.bitmap
    width = int(bitmap.width)
    height = int(bitmap.rows)
    glyph = {
        "handle": None,
        "x": 0,
        "y": 0,
        "width": width,
        "height": height,
        "left": int(face.glyph.bitmap_left),
        "top": int(face.glyph.bitmap_top),
        "advance": int(face.glyph.advance.x >> 6),
    }

    if width > 0 and height > 0:

        page, x, y = _gpuglyphpage(atlas, width, height)

        if page is None:
            return None

        # glTexImage2D has already allocated the atlas. Do not upload a blank
        # four-megabyte image for every font size: that startup burst can
        # overwhelm an otherwise healthy NVK/Zink submission queue. Upload a
        # transparent one-pixel border with each glyph instead. The border
        # makes linear filtering deterministic without initialising unused
        # atlas storage.
        uploadwidth = width + 2
        uploadheight = height + 2
        pixels = bytearray(uploadwidth * uploadheight * 4)
        pitch = int(bitmap.pitch)
        source = bitmap.buffer

        for row in range(height):

            sourcerow = row if pitch >= 0 else height - row - 1
            sourceoffset = sourcerow * abs(pitch)

            for column in range(width):

                alpha = int(source[sourceoffset + column])
                offset = ((row + 1) * uploadwidth + column + 1) * 4
                pixels[offset:offset + 4] = bytes((255, 255, 255, alpha))

        gputextureupdate(
            page["handle"],
            x - 1,
            y - 1,
            uploadwidth,
            uploadheight,
            data=pixels,
            fmt="RGBA32",
        )
        glyph.update({"handle": int(page["handle"]), "x": x, "y": y})
        uploaded = uploadwidth * uploadheight * 4
        _gputelemetry["glyph_uploads"] += 1
        _gputelemetry["glyph_upload_bytes"] += uploaded

    atlas["glyphs"][character] = glyph
    _gputelemetry["glyphs"] = sum(len(value.get("glyphs", {})) for value in _gpuglyphatlases.values())
    return glyph


def gpuprewarmtext(text, sizes=(16,), fontpath=None, limit=256, budget_ms=None):

    if not gpuavailable():
        return 0

    if isinstance(sizes, (int, float)):
        sizes = (sizes,)

    characters = []
    seen = set()

    for character in str(text):

        if character in seen:
            continue

        seen.add(character)
        characters.append(character)

        if len(characters) >= max(1, min(1024, int(limit))):
            break

    if not characters:
        return 0

    started = time.monotonic_ns()
    deadline = None

    if budget_ms is not None:
        deadline = time.monotonic() + max(0.0, float(budget_ms)) / 1000.0

    warmed = 0
    requests = 0
    exhausted = False

    for value in list(sizes)[:32]:

        if deadline is not None and time.monotonic() >= deadline:
            break

        atlas = _gpuglyphatlas(value, fontpath=fontpath)

        if atlas is None:
            continue

        for character in characters:

            if deadline is not None and time.monotonic() >= deadline:
                exhausted = True
                break

            requests += 1

            if character in atlas["glyphs"]:
                continue

            if _gpuglyph(atlas, character) is not None:
                warmed += 1

        if exhausted:
            break

    elapsed = (time.monotonic_ns() - started) / 1000000.0
    _gputelemetry["glyph_prewarm_runs"] += 1
    _gputelemetry["glyph_prewarm_requests"] += requests
    _gputelemetry["glyph_prewarmed"] += warmed
    _gputelemetry["glyph_prewarm_ms"] = round(float(_gputelemetry["glyph_prewarm_ms"]) + elapsed, 3)
    return warmed


def gpudrawtext(x, y, text, color, size, fontpath=None, opacity=1.0, clip=None, scale=1.0, rotation=0.0, origin=None, effect="none"):

    text = str(text)[:1024]
    atlas = _gpuglyphatlas(size, fontpath=fontpath)

    if atlas is None or not text:
        return (0, 0)

    tint = list(color) if not isinstance(color, int) else [
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
        255,
    ]

    if len(tint) == 3:
        tint.append(255)

    scale = max(0.01, min(16.0, float(scale)))
    pen = 0
    runs = []
    currenthandle = None
    current = []

    def flush():

        nonlocal currenthandle, current

        if currenthandle is not None and current:
            runs.append((currenthandle, current))

        currenthandle = None
        current = []

    for character in text:

        glyph = _gpuglyph(atlas, character)

        if glyph is None:
            continue

        handle = glyph.get("handle")

        if handle is not None:

            if currenthandle is not None and int(handle) != int(currenthandle):
                flush()

            currenthandle = int(handle)
            current.append({
                "x": float(x) + (pen + int(glyph["left"])) * scale,
                "y": float(y) + (int(atlas["ascender"]) - int(glyph["top"])) * scale,
                "width": int(glyph["width"]) * scale,
                "height": int(glyph["height"]) * scale,
                "u0": int(glyph["x"]) / float(GPUGLYPHATLASSIZE),
                "v0": int(glyph["y"]) / float(GPUGLYPHATLASSIZE),
                "u1": (int(glyph["x"]) + int(glyph["width"])) / float(GPUGLYPHATLASSIZE),
                "v1": (int(glyph["y"]) + int(glyph["height"])) / float(GPUGLYPHATLASSIZE),
                "color": tint,
                "opacity": opacity,
            })

        pen += int(glyph["advance"])

    flush()

    if float(rotation):

        if origin is None:
            origin = (
                float(x) + (pen * scale) * 0.5,
                float(y) + (int(atlas["height"]) * scale) * 0.5,
            )

        for _, quads in runs:

            for quad in quads:
                quad["rotation"] = float(rotation)
                quad["origin"] = origin

    for handle, quads in runs:

        resource = _gputextures.get(int(handle))

        if resource is None:
            continue

        # Glyph pages retain T1OS texture handles.  OpenGL must receive the
        # backing texture object, which is not guaranteed to have the same
        # numeric value after textures have been created or released.
        gpubatchquads(
            quads,
            texture=int(resource["texture"]),
            clip=clip,
            swizzle=False,
            texturealpha=True,
            mode="texture",
            effect=effect,
            textmode=True,
        )

    return (max(0, int(round(pen * scale))), max(1, int(round(int(atlas["height"]) * scale))))


def gpubatchtexts(items, clip=None, effect="none"):

    if not isinstance(items, (list, tuple)) or not items:
        return 0

    runs = []
    currenthandle = None
    current = []
    itemcount = 0

    def flush():

        nonlocal currenthandle, current

        if currenthandle is not None and current:
            runs.append((currenthandle, current))

        currenthandle = None
        current = []

    for item in items:

        try:

            text = str(item.get("text", ""))[:1024]
            atlas = _gpuglyphatlas(item.get("size", 16), fontpath=item.get("font"))

            if atlas is None or not text:
                continue

            color = item.get("color", (255, 255, 255, 255))
            tint = list(color) if not isinstance(color, int) else [
                (color >> 16) & 0xFF,
                (color >> 8) & 0xFF,
                color & 0xFF,
                255,
            ]

            if len(tint) == 3:
                tint.append(255)

            x = float(item.get("x", 0.0))
            y = float(item.get("y", 0.0))
            opacity = max(0.0, min(1.0, float(item.get("opacity", 1.0))))
            scale = max(0.01, min(16.0, float(item.get("scale", 1.0))))
            rotation = float(item.get("rotation", 0.0))
            origin = item.get("origin")
            pen = 0

            if rotation and origin is None:
                # The width is only needed for the uncommon implicit rotation
                # origin.  Calculate advances without creating another set of
                # vertices, then perform the normal ordered pass below.
                width = 0

                for character in text:

                    glyph = _gpuglyph(atlas, character)

                    if glyph is not None:
                        width += int(glyph["advance"])

                origin = (
                    x + (width * scale) * 0.5,
                    y + (int(atlas["height"]) * scale) * 0.5,
                )

            appended = False

            for character in text:

                glyph = _gpuglyph(atlas, character)

                if glyph is None:
                    continue

                handle = glyph.get("handle")

                if handle is not None:

                    if currenthandle is not None and int(handle) != int(currenthandle):
                        flush()

                    currenthandle = int(handle)
                    quad = {
                        "x": x + (pen + int(glyph["left"])) * scale,
                        "y": y + (int(atlas["ascender"]) - int(glyph["top"])) * scale,
                        "width": int(glyph["width"]) * scale,
                        "height": int(glyph["height"]) * scale,
                        "u0": int(glyph["x"]) / float(GPUGLYPHATLASSIZE),
                        "v0": int(glyph["y"]) / float(GPUGLYPHATLASSIZE),
                        "u1": (int(glyph["x"]) + int(glyph["width"])) / float(GPUGLYPHATLASSIZE),
                        "v1": (int(glyph["y"]) + int(glyph["height"])) / float(GPUGLYPHATLASSIZE),
                        "color": tint,
                        "opacity": opacity,
                    }

                    if rotation:
                        quad["rotation"] = rotation
                        quad["origin"] = origin

                    current.append(quad)
                    appended = True

                pen += int(glyph["advance"])

            if appended:
                itemcount += 1

        except Exception:
            continue

    flush()

    for handle, quads in runs:

        resource = _gputextures.get(int(handle))

        if resource is None:
            continue

        gpubatchquads(
            quads,
            texture=int(resource["texture"]),
            clip=clip,
            swizzle=False,
            texturealpha=True,
            mode="texture",
            effect=effect,
            textmode=True,
        )

    return itemcount


def gpudrawcursor(x, y, name="arrow", opacity=1.0, clip=None):

    info = CURSORS.get(name)

    if info is None or not info.get("data") or int(info.get("w", 0)) < 1 or int(info.get("h", 0)) < 1:
        return False

    key = (str(CURSORTIER), str(name), int(info["w"]), int(info["h"]))
    handle = _gpucursorcache.get(key)

    if handle is None or gputextureinfo(handle) is None:
        handle = gputexturecreate(info["w"], info["h"], fmt="BGRA32", data=info["data"], owner="cursor")
        _gpucursorcache[key] = handle

    return gpudrawtexture(handle, x, y, info["w"], info["h"], opacity=opacity, clip=clip)


def _gpurecordframe(success):

    global _gpuframestart

    elapsed = 0.0

    if _gpuframestart:
        elapsed = (time.monotonic_ns() - _gpuframestart) / 1000000.0

    if success:

        frames = int(_gputelemetry["frames"]) + 1
        previous = float(_gputelemetry["average_frame_ms"])
        _gputelemetry["frames"] = frames
        _gputelemetry["frame_ms"] = round(elapsed, 3)
        _gputelemetry["render_ms"] = round(float(_gpuframerenderms or elapsed), 3)
        _gputelemetry["average_frame_ms"] = round(previous + ((elapsed - previous) / frames), 3)
        _gputelemetry["maximum_frame_ms"] = round(max(float(_gputelemetry["maximum_frame_ms"]), elapsed), 3)
        previousrender = float(_gputelemetry["average_render_ms"])
        renderms = float(_gpuframerenderms or elapsed)
        _gputelemetry["average_render_ms"] = round(previousrender + ((renderms - previousrender) / frames), 3)
        _gputelemetry["maximum_render_ms"] = round(max(float(_gputelemetry["maximum_render_ms"]), renderms), 3)

        _gpuframehistory.append(float(elapsed))

        _gpuframeprofiles.append({
            "sequence": frames,
            "ms": round(float(elapsed), 3),
            "render_ms": round(float(_gpuframerenderms or elapsed), 3),
            "draw_calls": int(_gpuframedraws),
            "uploads": int(_gpuframeuploads),
            "upload_bytes": int(_gpuframeuploadbytes),
            "damage_regions": len(_gpuframeregions),
            "damage_pixels": int(_gpuframedamagepixels),
            "full": bool(_gpuframefull),
            "persistent": bool(_gpuframepersistent),
            "persistent_sync": bool(_gpuframesyncpersistent),
        })

        if len(_gpuframehistory) > GPUFRAMEHISTORYCAP:
            del _gpuframehistory[0:len(_gpuframehistory) - GPUFRAMEHISTORYCAP]

        if len(_gpuframeprofiles) > GPUFRAMEHISTORYCAP:
            del _gpuframeprofiles[0:len(_gpuframeprofiles) - GPUFRAMEHISTORYCAP]

        if elapsed > float(_gpuframebudgetms):
            _gputelemetry["missed_frame_budget"] += 1

        _gputelemetry["full_frames" if _gpuframefull else "partial_frames"] += 1
        _gputelemetry["damage_regions"] += len(_gpuframeregions)
        _gputelemetry["damage_pixels"] += int(_gpuframedamagepixels)

        if _gpuframepersistent:
            _gputelemetry["persistent_frames"] += 1
            _gputelemetry["scissored_pixels"] += int(_gpuframedamagepixels)

        if _gpuframesyncpersistent:
            _gputelemetry["persistent_sync_frames"] += 1

    else:
        _gputelemetry["failed_frames"] += 1

    _gpuframestart = 0


def gpuend(present=True, waitpulse=None, preserve=True):

    global _gpuframeactive, _gpuframeclip, _gpucompositorvalid, _gpuframerenderms

    if not _gpuframeactive:
        return False

    try:

        if _gpuframepersistent:

            resource = _gputextures.get(int(_gpucompositorhandle))

            if resource is None:
                raise RuntimeError("persistent compositor surface was released during a frame")

            _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)
            _gpuframeclip = None
            _gles.glDisable(GL_SCISSOR_TEST)
            _gpudrawquad(
                int(resource["texture"]),
                0,
                0,
                int(_xres),
                int(_yres),
                0.0,
                1.0,
                1.0,
                0.0,
                (255, 255, 255, 255),
                1.0,
                None,
                False,
                False,
                "texture",
                displayadjust=displayadjustactive(),
            )

        elif _gpuframesyncpersistent and preserve:

            resource = _gputextures.get(int(_gpucompositorhandle))

            if resource is None:
                raise RuntimeError("persistent compositor surface was released before synchronisation")

            _gles.glActiveTexture(GL_TEXTURE0)
            _gles.glBindTexture(GL_TEXTURE_2D, int(resource["texture"]))
            _gles.glCopyTexSubImage2D(
                GL_TEXTURE_2D,
                0,
                0,
                0,
                0,
                0,
                int(_xres),
                int(_yres),
            )
            gpuhealthsample(
                operation="default-framebuffer preservation copy",
            )

        _gles.glDisable(GL_SCISSOR_TEST)

        if _gpuframestart:
            _gpuframerenderms = (time.monotonic_ns() - _gpuframestart) / 1000000.0

        if present and _backend == "opengl":
            kmsscanout(waitpulse=waitpulse)
        else:
            _gles.glFinish()

        _gpurecordframe(True)
        _gpucompositorvalid = bool(
            _gpuframepersistent
            or (_gpuframesyncpersistent and preserve)
        )
        _gpuframeactive = False
        _gpuframeclip = None
        return True

    except Exception:

        _gpurecordframe(False)
        _gpucompositorvalid = False
        _gpuframeactive = False
        _gpuframeclip = None
        raise


def gpuabort():

    global _gpuframeactive, _gpuframeclip, _gpucompositorvalid

    try:
        _gles.glDisable(GL_SCISSOR_TEST)
    except Exception:
        pass

    wasactive = bool(_gpuframeactive)

    if wasactive:
        _gpurecordframe(False)

    if wasactive and (_gpuframepersistent or _gpuframesyncpersistent):
        _gpucompositorvalid = False

    _gpuframeactive = False
    _gpuframeclip = None


def gpureadpixel(x, y):

    if not gpuavailable():
        raise RuntimeError("managed GPU renderer is unavailable")

    x = int(x)
    y = int(y)
    renderwidth, renderheight = _gpurendersize()

    if x < 0 or y < 0 or x >= int(renderwidth) or y >= int(renderheight):
        raise ValueError("GPU readback coordinate is outside the surface")

    pixel = (ctypes.c_ubyte * 4)()
    _gles.glFinish()
    _gles.glReadPixels(x, int(renderheight) - y - 1, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
    return list(pixel)


def gpufallback():

    _gputelemetry["fallbacks"] += 1
    gpuabort()


def openglcompositordiagnostic():

    global _buffer, _xres, _yres, _line, _size, _bpp_bytes

    oldbuffer = _buffer
    oldxres = _xres
    oldyres = _yres
    oldline = _line
    oldsize = _size
    oldbytes = _bpp_bytes

    try:

        _xres = 8
        _yres = 8
        _bpp_bytes = 4
        _line = _xres * _bpp_bytes
        _size = _line * _yres
        _buffer = bytearray(bytes((191, 128, 64, 255)) * (_xres * _yres))
        openglpreparepresent()
        resetdirty()
        markdirty(0, 0, _xres, _yres)
        openglupload()
        _gles.glFinish()
        pixel = (ctypes.c_ubyte * 4)()
        _gles.glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)

        if list(pixel) != [64, 128, 191, 255]:
            raise RuntimeError(f"unexpected compositor full pixel {list(pixel)}")

        patch = bytes((30, 20, 10, 255))

        for row in range(3, 5):

            for column in range(3, 5):
                offset = (row * _line) + (column * _bpp_bytes)
                _buffer[offset:offset + _bpp_bytes] = patch

        resetdirty()
        markdirty(3, 3, 5, 5)
        openglupload()
        _gles.glFinish()
        _gles.glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)

        if list(pixel) != [10, 20, 30, 255]:
            raise RuntimeError(f"unexpected compositor partial pixel {list(pixel)}")

        if _gluploadbytes != 16 or _gluploadfull:
            raise RuntimeError(f"unexpected compositor upload {_gluploadbytes} bytes full={_gluploadfull}")

        return {
            "full_pixel": [64, 128, 191, 255],
            "partial_pixel": list(pixel),
            "partial_bytes": int(_gluploadbytes),
        }

    finally:

        openglreleasepresent()
        _buffer = oldbuffer
        _xres = oldxres
        _yres = oldyres
        _line = oldline
        _size = oldsize
        _bpp_bytes = oldbytes
        resetdirty()


def gpulayerdiagnostic():

    global _xres, _yres

    oldxres = _xres
    oldyres = _yres
    texture = None
    opaquetexture = None
    alphatexture = None
    scenetarget = None
    coveragetexture = None
    revisionpath = f"/.ephemeral/graphics-frame-revision-{os.getpid()}.bgra"
    revisionpixel = None
    rawtexture = ctypes.c_uint()

    def pixelat(x, y):

        pixel = (ctypes.c_ubyte * 4)()
        _gles.glReadPixels(int(x), int(_yres) - int(y) - 1, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
        return list(pixel)

    def near(actual, expected, tolerance=2):

        return all(abs(int(value) - int(wanted)) <= tolerance for value, wanted in zip(actual, expected))

    try:

        _xres = 8
        _yres = 8
        texture = gputexturecreate(2, 2, fmt="BGRA32", data=bytes((0, 0, 255, 255)) * 4, owner="diagnostic")

        with open(revisionpath, "wb") as stream:
            stream.write(bytes((0, 0, 255, 255)) * 4)

        revisionstat = os.stat(revisionpath)
        gpubegin((0, 0, 0, 255))
        gpudrawimage(revisionpath, 2, 2, 0, 0, revision=1)
        gpuend(present=False)

        with open(revisionpath, "r+b") as stream:
            stream.write(bytes((0, 255, 0, 255)) * 4)

        os.utime(revisionpath, ns=(revisionstat.st_atime_ns, revisionstat.st_mtime_ns))
        gpubegin((0, 0, 0, 255))
        gpudrawimage(revisionpath, 2, 2, 0, 0, revision=2)
        gpuend(present=False)
        revisionpixel = pixelat(1, 1)

        if not near(revisionpixel, [0, 255, 0, 255]):
            raise RuntimeError(f"managed frame revision reused a stale texture {revisionpixel}")

        opaquetexture = gputexturecreate(
            1,
            1,
            fmt="BGRA32",
            data=bytes((30, 20, 10, 0)),
            owner="diagnostic-opaque",
            alpha=False,
        )
        alphatexture = gputexturecreate(
            1,
            1,
            fmt="BGRA32",
            data=bytes((255, 255, 255, 0)),
            owner="diagnostic-alpha",
            alpha=True,
        )
        # Reserve an OpenGL texture name outside the managed texture table so
        # the following glyph-atlas handle cannot accidentally equal its
        # backing OpenGL object.  Runtime texture churn naturally creates the
        # same condition; the diagnostic makes it deterministic.
        _gles.glGenTextures(1, ctypes.byref(rawtexture))

        if not rawtexture.value:
            raise RuntimeError("managed text diagnostic could not reserve a raw texture name")

        gpubegin((0, 0, 0, 255))
        gpudrawrect(0, 0, 4, 4, (20, 40, 60, 255))
        gpudrawtexture(texture, 4, 0, 4, 4)
        gpudrawrect(0, 4, 4, 4, (255, 255, 255, 255), opacity=0.5)
        gpudrawrect(4, 4, 4, 4, (0, 255, 0, 255), clip=(6, 4, 2, 4))
        gpuend(present=False)
        rectangle = pixelat(1, 2)
        texturepixel = pixelat(5, 2)
        blended = pixelat(1, 6)
        clippedout = pixelat(5, 6)
        clippedin = pixelat(7, 6)

        if not near(rectangle, [20, 40, 60, 255]):
            raise RuntimeError(f"unexpected managed rectangle pixel {rectangle}")

        if not near(texturepixel, [255, 0, 0, 255]):
            raise RuntimeError(f"unexpected managed texture pixel {texturepixel}")

        if not near(blended, [128, 128, 128, 255]):
            raise RuntimeError(f"unexpected managed blend pixel {blended}")

        if not near(clippedout, [0, 0, 0, 255]):
            raise RuntimeError(f"unexpected managed clip outside pixel {clippedout}")

        if not near(clippedin, [0, 255, 0, 255]):
            raise RuntimeError(f"unexpected managed clip inside pixel {clippedin}")

        gpubegin((70, 80, 90, 255))
        gpudrawtexture(opaquetexture, 0, 0, 4, 4)
        gpudrawtexture(alphatexture, 4, 0, 4, 4)
        gpuend(present=False)
        opaquepixel = pixelat(1, 2)
        alphapixel = pixelat(5, 2)

        if not near(opaquepixel, [10, 20, 30, 255]):
            raise RuntimeError(f"managed opaque surface used source alpha {opaquepixel}")

        if not near(alphapixel, [70, 80, 90, 255]):
            raise RuntimeError(f"managed alpha surface ignored source alpha {alphapixel}")

        # A retained scene must preserve coverage across both passes.  The
        # target pixel is premultiplied; resolving it over black must match a
        # direct source-over draw instead of multiplying its alpha twice.
        gpubegin((0, 0, 0, 255))
        scenetarget = gputargetcreate(1, 1, owner="diagnostic-premultiplied-scene")
        targetstate = gputargetbegin(scenetarget, clearcolor=(0, 0, 0, 0), clear=True)
        gpudrawrect(0, 0, 1, 1, (255, 255, 255, 255), opacity=0.5)
        retainedpixel = gpureadpixel(0, 0)
        gputargetend(targetstate)
        gpudrawtexture(scenetarget, 0, 0, 4, 4, flip_y=True)
        gpudrawrect(4, 0, 4, 4, (255, 255, 255, 255), opacity=0.5)
        gpuend(present=False)
        resolvedpixel = pixelat(1, 2)
        directpixel = pixelat(5, 2)

        if not near(retainedpixel, [128, 128, 128, 128]):
            raise RuntimeError(f"retained scene is not premultiplied {retainedpixel}")

        if not near(resolvedpixel, directpixel, tolerance=1):
            raise RuntimeError(f"retained scene attenuated coverage {resolvedpixel}/{directpixel}")

        sceneinfo = gputextureinfo(scenetarget)

        if not sceneinfo or not bool(sceneinfo.get("premultiplied", False)):
            raise RuntimeError(f"retained scene lost its alpha representation {sceneinfo}")

        # Exercise the polarity-aware text gamma path with exactly 50 per cent
        # source coverage.  Light-on-dark and dark-on-light should resolve to
        # the same neutral intensity rather than one polarity looking heavier.
        coveragetexture = gputexturecreate(
            1,
            1,
            fmt="RGBA32",
            data=bytes((255, 255, 255, 128)),
            owner="diagnostic-text-coverage",
            alpha=True,
        )
        coverageresource = _gputextures[int(coveragetexture)]
        gpubegin((0, 0, 0, 255))
        gpudrawrect(4, 0, 4, 4, (255, 255, 255, 255))
        gpubatchquads(
            [{"x": 0, "y": 0, "width": 4, "height": 4, "color": (255, 255, 255, 255)}],
            texture=int(coverageresource["texture"]),
            texturealpha=True,
            mode="texture",
            textmode=True,
        )
        gpubatchquads(
            [{"x": 4, "y": 0, "width": 4, "height": 4, "color": (0, 0, 0, 255)}],
            texture=int(coverageresource["texture"]),
            texturealpha=True,
            mode="texture",
            textmode=True,
        )
        gpuend(present=False)
        lighttextpixel = pixelat(1, 2)
        darktextpixel = pixelat(5, 2)
        expectedlight = int(TEXTLIGHTCOVERAGE[128])
        expecteddark = 255 - int(TEXTDARKCOVERAGE[128])

        if not near(lighttextpixel, [expectedlight, expectedlight, expectedlight, 255]):
            raise RuntimeError(f"light text gamma coverage changed {lighttextpixel}/{expectedlight}")

        if not near(darktextpixel, [expecteddark, expecteddark, expecteddark, 255]):
            raise RuntimeError(f"dark text gamma coverage changed {darktextpixel}/{expecteddark}")

        if not near(lighttextpixel, darktextpixel, tolerance=2):
            raise RuntimeError(f"text gamma polarity is asymmetric {lighttextpixel}/{darktextpixel}")

        prewarmed = gpuprewarmtext("Warm 123", sizes=(6,), fontpath=BASELINEFONT)
        prewarmedagain = gpuprewarmtext("Warm 123", sizes=(6,), fontpath=BASELINEFONT)

        if prewarmed < 1 or prewarmedagain != 0:
            raise RuntimeError(f"managed glyph prewarming did not populate and reuse its atlas {prewarmed}/{prewarmedagain}")

        gpubegin((0, 0, 0, 255))
        textsize = gpudrawtext(0, 0, "A", (255, 255, 255, 255), 6, fontpath=BASELINEFONT)
        gpuend(present=False)
        textpixel = max(
            (pixelat(column, row) for row in range(8) for column in range(8)),
            key=lambda value: sum(int(channel) for channel in value[:3]),
        )

        if int(textsize[0]) < 1 or int(textsize[1]) < 1:
            raise RuntimeError(f"managed text returned invalid size {textsize}")

        if max(int(channel) for channel in textpixel[:3]) < 64:
            raise RuntimeError(f"managed text did not sample its glyph atlas {textpixel}")

        gpubegin((255, 255, 255, 255))
        gpudrawshadow(2, 2, 4, 4, radius=2, opacity=0.5)
        gpuend(present=False)
        shadowcentre = pixelat(4, 4)
        shadowedge = pixelat(0, 0)

        if shadowcentre[0] >= shadowedge[0]:
            raise RuntimeError(f"managed shadow did not fade {shadowcentre} {shadowedge}")

        publicscene = managedscene(
            managedrectangle([0, 0, 8, 8], 0x000000, nodeid="background"),
            managedgroup("content", translate=[1, 1]),
            managedlayer("overlay", [0, 0, 8, 8], opacity=0.75),
            managedtext(1, 1, "A", 6, BASELINEFONT, 0xFFFFFF, nodeid="label", parent="content"),
        )

        if [node.get("kind") for node in publicscene] != ["rectangle", "group", "layer", "text"]:
            raise RuntimeError("controlled public scene API changed node ordering or kinds")

        try:
            managednode("shader", source="not allowed")
            raise RuntimeError("controlled public scene API accepted a raw shader")
        except ValueError:
            pass

        return {
            "api": gpuapi(),
            "rectangle_pixel": rectangle,
            "texture_pixel": texturepixel,
            "frame_revision_pixel": revisionpixel,
            "blend_pixel": blended,
            "clip_outside_pixel": clippedout,
            "clip_inside_pixel": clippedin,
            "opaque_surface_pixel": opaquepixel,
            "alpha_surface_pixel": alphapixel,
            "retained_scene_pixel": retainedpixel,
            "resolved_scene_pixel": resolvedpixel,
            "direct_scene_pixel": directpixel,
            "light_text_gamma_pixel": lighttextpixel,
            "dark_text_gamma_pixel": darktextpixel,
            "shadow_centre_pixel": shadowcentre,
            "shadow_edge_pixel": shadowedge,
            "text_size": [int(textsize[0]), int(textsize[1])],
            "text_pixel": textpixel,
            "glyph_prewarm": {"created": int(prewarmed), "reused": int(prewarmedagain)},
            "public_scene_api": [node.get("kind") for node in publicscene],
            "telemetry": gpumetrics(),
        }

    finally:

        gpuabort()

        if texture is not None:
            gputexturedestroy(texture)

        revisionkey = (revisionpath, 2, 2, "BGRA32")
        revisionresource = _gpuimagecache.pop(revisionkey, None)

        if revisionresource is not None:
            gputexturedestroy(revisionresource.get("handle", 0))

        try:
            os.unlink(revisionpath)
        except Exception:
            pass

        if opaquetexture is not None:
            gputexturedestroy(opaquetexture)

        if alphatexture is not None:
            gputexturedestroy(alphatexture)

        if scenetarget is not None:
            gputargetdestroy(scenetarget)

        if coveragetexture is not None:
            gputexturedestroy(coveragetexture)

        if rawtexture.value:
            _gles.glDeleteTextures(1, ctypes.byref(rawtexture))

        gpurelease()
        _xres = oldxres
        _yres = oldyres


def openglupload():

    global _gluploadbytes, _gluploadfull

    if not _buffer or not _glprogram or not _gltexture:
        return False

    dirty = getdirty()
    x = 0
    y = 0
    width = 0
    height = 0
    pixels = None
    region = None

    if dirty:

        x = max(0, int(dirty[0]))
        y = max(0, int(dirty[1]))
        width = min(_xres - x, int(dirty[2]))
        height = min(_yres - y, int(dirty[3]))

    if width <= 0 or height <= 0:
        width = 0
        height = 0

    fullarea = int(_xres) * int(_yres)
    dirtyarea = int(width) * int(height)

    if dirtyarea and dirtyarea < (fullarea * 3) // 4:

        rowbytes = int(width) * int(_bpp_bytes)
        region = bytearray(rowbytes * int(height))
        source = (ctypes.c_ubyte * len(_buffer)).from_buffer(_buffer)
        target = (ctypes.c_ubyte * len(region)).from_buffer(region)
        sourceaddress = ctypes.addressof(source)
        targetaddress = ctypes.addressof(target)

        for row in range(int(height)):
            sourceoffset = ((int(y) + row) * int(_line)) + (int(x) * int(_bpp_bytes))
            ctypes.memmove(targetaddress + (row * rowbytes), sourceaddress + sourceoffset, rowbytes)

        pixels = target
        _gluploadfull = False

    elif dirtyarea:

        x = 0
        y = 0
        width = _xres
        height = _yres
        pixels = (ctypes.c_ubyte * len(_buffer)).from_buffer(_buffer)
        _gluploadfull = True

    else:

        _gluploadfull = False

    _gluploadbytes = int(width) * int(height) * int(_bpp_bytes)
    vertices = (ctypes.c_float * 16)(
        -1.0, -1.0, 0.0, 1.0,
         1.0, -1.0, 1.0, 1.0,
        -1.0,  1.0, 0.0, 0.0,
         1.0,  1.0, 1.0, 0.0,
    )
    stride = ctypes.sizeof(ctypes.c_float) * 4
    base = ctypes.addressof(vertices)
    _gles.glViewport(0, 0, _xres, _yres)
    _gles.glUseProgram(_glprogram)
    _gles.glActiveTexture(GL_TEXTURE0)
    _gles.glBindTexture(GL_TEXTURE_2D, _gltexture)

    if pixels is not None:

        _gles.glTexSubImage2D(
            GL_TEXTURE_2D,
            0,
            int(x),
            int(y),
            int(width),
            int(height),
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            ctypes.cast(pixels, ctypes.c_void_p),
        )

    _gpusetuniform1i(_glprogram, b"canvas", 0)
    _gpusetuniform1f(_glprogram, b"displaybrightness", float(DISPLAYBRIGHTNESS) / 100.0)
    _gpusetuniform1f(_glprogram, b"displaycontrast", float(DISPLAYCONTRAST) / 100.0)
    _gpusetuniform1f(_glprogram, b"displaysaturation", float(DISPLAYEFFECTIVESATURATION) / 100.0)
    _gpusetuniform3f(
        _glprogram, b"displaychannels",
        float(DISPLAYCHANNELS[0]),
        float(DISPLAYCHANNELS[1]),
        float(DISPLAYCHANNELS[2]))

    _gles.glEnableVertexAttribArray(0)
    _gles.glEnableVertexAttribArray(1)
    _gles.glVertexAttribPointer(0, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(base))
    _gles.glVertexAttribPointer(1, 2, GL_FLOAT, 0, stride, ctypes.c_void_p(base + (ctypes.sizeof(ctypes.c_float) * 2)))
    _gles.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
    _gles.glDisableVertexAttribArray(0)
    _gles.glDisableVertexAttribArray(1)
    _gputelemetry["draw_calls"] += 1

    if _gluploadbytes:
        _gputelemetry["uploads"] += 1
        _gputelemetry["upload_bytes"] += int(_gluploadbytes)
        _gputelemetry["full_uploads" if _gluploadfull else "partial_uploads"] += 1

    return True


def kmsframebuffer(bo):

    handle = _gbm.gbm_bo_get_handle(bo)
    stride = int(_gbm.gbm_bo_get_stride(bo))
    framebuffer = ctypes.c_uint32()
    result = _drm.drmModeAddFB(
        _drmfd,
        _xres,
        _yres,
        24,
        32,
        stride,
        int(handle.u32),
        ctypes.byref(framebuffer),
    )

    if result != 0:
        error = ctypes.get_errno()
        kmsraise(error, f"drmModeAddFB failed for handle {int(handle.u32)}")

    return int(framebuffer.value)


def kmspresent():

    global _gpuframestart, _gpuframedraws, _gpuframeuploads, _gpuframeuploadbytes

    if not openglupload():
        return False

    _gpuframestart = time.monotonic_ns()
    _gpuframedraws = 1
    _gpuframeuploads = 1 if _gluploadbytes else 0
    _gpuframeuploadbytes = int(_gluploadbytes)

    try:

        result = kmsscanout()
        _gpurecordframe(True)
        return result

    except Exception:

        _gpurecordframe(False)
        raise


def kmsscanout(force_modeset=False, waitpulse=None):

    global _drmflip, _drmpendingbo, _drmpendingsurface, _drmpendingfb, _drmpendingstarted

    # A second GBM front buffer must not be locked while the previous buffer is
    # still owned by an outstanding page flip. Event-driven compositors normally
    # complete the flip through their selector before reaching this point. The
    # fallback wait continues servicing their input callback if a driver is late.
    if _drmflip:

        waitstarted = time.monotonic_ns()

        if not kmswaitflip(waitpulse=waitpulse):
            raise RuntimeError("DRM page flip timed out before the next presentation")

        _gpurecordkmsstage("prior_flip_wait", waitstarted)

    swapstarted = time.monotonic_ns()
    swapped = _egl.eglSwapBuffers(_egldisplay, _eglsurface)
    _gpurecordkmsstage("egl_swap", swapstarted)

    if not swapped:
        error = 0

        try:
            error = int(_egl.eglGetError())
        except Exception:
            pass

        # A robust reset status is authoritative when available. EGL also
        # reports EGL_CONTEXT_LOST directly, including on implementations
        # where no GL reset-status entry point was exposed.
        openglresetstatus("eglSwapBuffers")

        if error == EGL_CONTEXT_LOST:
            raise GPUDeviceLostError(
                "eglSwapBuffers reported a lost GPU context "
                f"(EGL error 0x{error:04x})"
            )

        raise RuntimeError(
            f"eglSwapBuffers failed with EGL error 0x{error:04x}"
        )

    # Robust reset/error polling is intentionally sampled. Querying both GL
    # error state and graphics-reset status on every frame serializes some
    # physical and virtual drivers. Swap failures, DRM failures and the
    # half-second sample still detect a lost device and enter recovery.
    gpuhealthsample(operation="eglSwapBuffers")
    lockstarted = time.monotonic_ns()
    newbo = _gbm.gbm_surface_lock_front_buffer(_gbmsurface)
    _gpurecordkmsstage("gbm_lock", lockstarted)

    if not newbo:
        raise RuntimeError("gbm_surface_lock_front_buffer failed")

    newfb = 0
    owned = True

    try:

        framebufferstarted = time.monotonic_ns()
        newfb = kmsframebuffer(newbo)
        _gpurecordkmsstage("drm_framebuffer", framebufferstarted)
        connector = ctypes.c_uint32(_drmconnector)

        if force_modeset or not _gbmbo:

            result = _drm.drmModeSetCrtc(
                _drmfd,
                _drmcrtc,
                newfb,
                0,
                0,
                ctypes.byref(connector),
                1,
                ctypes.byref(_drmmode),
            )

            if result != 0:
                error = ctypes.get_errno()
                kmsraise(error, "drmModeSetCrtc failed")

            _kmsresetpresentationcadence()

        else:

            _drmflip = True
            _drmpendingbo = newbo
            _drmpendingsurface = _gbmsurface
            _drmpendingfb = newfb
            _drmpendingstarted = time.monotonic_ns()
            submitstarted = time.monotonic_ns()
            result = _drm.drmModePageFlip(
                _drmfd,
                _drmcrtc,
                newfb,
                DRM_MODE_PAGE_FLIP_EVENT,
                None,
            )
            _gpurecordkmsstage("page_flip_submit", submitstarted)

            if result == 0:

                owned = False
                _gputelemetry["page_flip_submissions"] += 1

                if _drmeventdriven:
                    return True

                if not kmswaitflip(waitpulse=waitpulse):
                    raise RuntimeError("DRM page flip timed out")

                return True

            else:

                fliperror = int(ctypes.get_errno() or 0)
                _drmflip = False
                _drmpendingbo = None
                _drmpendingsurface = None
                _drmpendingfb = 0
                _drmpendingstarted = 0

                if fliperror in (errno.ENODEV, errno.EIO):
                    kmsraise(fliperror, "DRM page flip submission")

                recoverable = {
                    errno.EINVAL,
                    errno.ENOSYS,
                    getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
                    errno.ENOTTY,
                }

                if fliperror not in recoverable:
                    raise OSError(
                        fliperror,
                        "DRM page flip submission failed without a safe "
                        "modeset fallback",
                    )

                result = _drm.drmModeSetCrtc(
                    _drmfd,
                    _drmcrtc,
                    newfb,
                    0,
                    0,
                    ctypes.byref(connector),
                    1,
                    ctypes.byref(_drmmode),
                )

                if result != 0:
                    error = ctypes.get_errno()
                    kmsraise(error, "DRM page flip and modeset both failed")

                _kmsresetpresentationcadence()

        owned = False
        _kmsreplacecurrent(newbo, _gbmsurface, newfb)
        return True

    except Exception:

        if owned:
            _kmsreleasebuffer(newfb, _gbmsurface, newbo)

        raise


def kmsframebufferclose():

    global _backend, _drmfd, _drmconnector, _drmcrtc, _drmmode, _drmoriginal
    global _drmdriver, _drmdriverversion, _drmdriverdate, _drmdriverdescription
    global _drmdumbhandle, _drmdumbfb, _drmdumbsize, _map, _buffer
    global _drmdumbpresentsequence, _drmdumbmodesetsequence
    global _drmdumbflushstatus, _drmdumbdirtystatus
    global _drmdumblastpresenterror

    # This backend is entered after an accelerated display owner has failed.
    # Its inherited CRTC framebuffer can therefore refer to the dead owner's
    # scanout.  Never restore that framebuffer here: doing so can put the
    # display straight back onto the black scanout which recovery replaced.
    # A succeeding KMS owner will set its own CRTC, while the final fbdev tier
    # explicitly returns the display VT to KD_TEXT/fbcon before it starts.

    try:

        if _map is not None:
            _map.close()

    except Exception:
        pass

    _map = None
    _buffer = None

    try:

        if _drmfd is not None and _drmdumbfb:
            _drm.drmModeRmFB(_drmfd, int(_drmdumbfb))

    except Exception:
        pass

    try:

        if _drmfd is not None and _drmdumbhandle:
            destroy = bytearray(4)
            struct.pack_into("<I", destroy, 0, int(_drmdumbhandle))
            fcntl.ioctl(
                _drmfd,
                DRM_IOCTL_MODE_DESTROY_DUMB,
                destroy,
                True,
            )

    except Exception:
        pass

    try:

        if _drmfd is not None:
            os.close(_drmfd)

    except Exception:
        pass

    _drmfd = None
    _drmconnector = 0
    _drmcrtc = 0
    _drmmode = None
    _drmoriginal = None
    _drmdriver = None
    _drmdriverversion = None
    _drmdriverdate = None
    _drmdriverdescription = None
    _drmdumbhandle = 0
    _drmdumbfb = 0
    _drmdumbsize = 0
    _drmdumbpresentsequence = 0
    _drmdumbmodesetsequence = 0
    _drmdumbflushstatus = "not-attempted"
    _drmdumbdirtystatus = "not-attempted"
    _drmdumblastpresenterror = None

    if _backend == "kms-framebuffer":
        _backend = "none"


def _kmsframebufferinitdevice(device, resize=False):

    global _backend, _drmfd, _drmconnector, _drmcrtc, _drmmode, _drmoriginal
    global _drmdriver, _drmdriverversion, _drmdriverdate, _drmdriverdescription
    global _drmdumbhandle, _drmdumbfb, _drmdumbsize
    global _drmdumbpresentsequence, _drmdumbmodesetsequence
    global _drmdumbflushstatus, _drmdumbdirtystatus
    global _drmdumblastpresenterror
    global _map, _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes
    global _line, _size, _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen
    global _pack, _packint, _unpack, _IS_FILE_BUFFER

    try:

        if not drmload():
            raise RuntimeError("DRM modesetting library did not load")

        _drmfd = os.open(device, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        driverinfo = kmsdriverinfo()
        _drmdriver = driverinfo.get("name")
        _drmdriverversion = driverinfo.get("version")
        _drmdriverdate = driverinfo.get("date")
        _drmdriverdescription = driverinfo.get("description")
        log(
            f"> graphics software KMS DRM driver "
            f"{_drmdriver or 'unknown'} {_drmdriverversion or 'unknown'}"
        )

        _drmconnector, _drmcrtc, _drmmode = kmsfindmode(
            resize=resize,
            preserve_current=True,
        )
        originalpointer = _drm.drmModeGetCrtc(_drmfd, _drmcrtc)

        if originalpointer:

            try:
                _drmoriginal = kmsstructure(originalpointer, drmModeCrtc)
            finally:
                _drm.drmModeFreeCrtc(originalpointer)

        if not kmsvalidmode(_drmmode):
            raise RuntimeError("software KMS selected an invalid display mode")

        width = int(_drmmode.hdisplay)
        height = int(_drmmode.vdisplay)
        create = bytearray(32)
        struct.pack_into("<IIII", create, 0, height, width, 32, 0)
        fcntl.ioctl(
            _drmfd,
            DRM_IOCTL_MODE_CREATE_DUMB,
            create,
            True,
        )
        handle = int(struct.unpack_from("<I", create, 16)[0])
        pitch = int(struct.unpack_from("<I", create, 20)[0])
        size = int(struct.unpack_from("<Q", create, 24)[0])

        if (
            handle <= 0
            or pitch < width * 4
            or size < pitch * height
            or size > FRAMEBUFFERMAXBYTES
        ):
            raise RuntimeError(
                f"software KMS returned an invalid dumb buffer "
                f"handle={handle} pitch={pitch} size={size}"
            )

        _drmdumbhandle = handle
        _drmdumbsize = size
        framebuffer = ctypes.c_uint32()
        result = _drm.drmModeAddFB(
            _drmfd,
            width,
            height,
            24,
            32,
            pitch,
            handle,
            ctypes.byref(framebuffer),
        )

        if result != 0 or not framebuffer.value:
            error = ctypes.get_errno()
            raise OSError(error, "software KMS drmModeAddFB failed")

        _drmdumbfb = int(framebuffer.value)
        mapping = bytearray(16)
        struct.pack_into("<I", mapping, 0, handle)
        fcntl.ioctl(
            _drmfd,
            DRM_IOCTL_MODE_MAP_DUMB,
            mapping,
            True,
        )
        offset = int(struct.unpack_from("<Q", mapping, 8)[0])
        _map = mmap.mmap(
            _drmfd,
            size,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=offset,
        )
        _buffer = bytearray(size)
        _xres = width
        _yres = height
        _yvirt = height
        _bpp = 32
        _bpp_bytes = 4
        _line = pitch
        _size = size
        _roff, _rlen = 16, 8
        _goff, _glen = 8, 8
        _boff, _blen = 0, 8
        _aoff, _alen = 24, 0
        packer = struct.Struct("<I")
        _unpack = packer.unpack
        _packint = packer.pack
        _pack = lambda color: packrgb(normalisecolor(color))
        _IS_FILE_BUFFER = False
        _drmdumbpresentsequence = 0
        _drmdumbmodesetsequence = 0
        _drmdumbflushstatus = "not-attempted"
        _drmdumbdirtystatus = "not-attempted"
        _drmdumblastpresenterror = None
        _backend = "kms-framebuffer"
        resetdirty()
        log(
            f"> graphics software KMS buffer ready "
            f"{width}x{height} pitch={pitch} bytes={size} "
            f"framebuffer={_drmdumbfb} "
            f"scanout=pending-first-written-frame"
        )
        return True

    except GPUDeviceLostError as error:
        log(
            f"> graphics software KMS init reported device loss "
            f"device={device} error={error}"
        )
        kmsframebufferclose()
        raise

    except OSError as error:
        if int(getattr(error, "errno", 0) or 0) in (errno.ENODEV, errno.EIO):
            lost = GPUDeviceLostError(
                f"software KMS initialization reported a lost DRM device "
                f"(errno={int(error.errno)} {os.strerror(int(error.errno))})"
            )
            log(
                f"> graphics software KMS init reported device loss "
                f"device={device} error={lost}"
            )
            kmsframebufferclose()
            raise lost from error

        log(f"> graphics software KMS init failed device={device} error={error}")
        kmsframebufferclose()
        return False

    except Exception as error:
        log(f"> graphics software KMS init failed device={device} error={error}")
        kmsframebufferclose()
        return False


def kmsframebufferinit(device=None):

    global DRMDEVICE

    selected = str(device or DRMDEVICE or "").strip()
    candidates = [selected] if selected else drmcandidates()

    if not candidates:
        log("> graphics software KMS found no DRM card devices")
        return False

    log(f"> graphics software KMS candidates {', '.join(candidates)}")
    devicelosses = []

    for candidate in candidates:

        try:

            if _kmsframebufferinitdevice(candidate):
                DRMDEVICE = candidate
                log(f"> graphics software KMS selected DRM device {candidate}")
                return True

        except GPUDeviceLostError as error:
            devicelosses.append((candidate, error))
            log(
                f"> graphics software KMS candidate lost "
                f"device={candidate} error={error}; trying next card"
            )

    if devicelosses:
        summary = "; ".join(
            f"{candidate}: {error}"
            for candidate, error in devicelosses
        )
        raise GPUDeviceLostError(
            f"all software KMS candidates failed after device loss: {summary}"
        )

    return False


def kmsframebufferrefresh():

    global _drmconnector, _drmcrtc, _drmmode
    global _drmdumbmodesetsequence

    if _backend != "kms-framebuffer" or _drmfd is None:
        return False

    # VBoxDRMClient updates the connector's preferred mode before the active
    # CRTC changes.  Preserving only the current CRTC therefore hides every
    # host resize from the software compositor.  Let virtual display drivers
    # select their new preferred mode while physical displays still preserve
    # the exact active timing.
    connector, crtc, mode = kmsfindmode(
        resize=True,
        preserve_current=True,
    )

    if (
        int(connector) == int(_drmconnector)
        and int(crtc) == int(_drmcrtc)
        and kmsmodekey(mode) == kmsmodekey(_drmmode)
    ):
        return False

    width = int(mode.hdisplay)
    height = int(mode.vdisplay)

    if width == int(_xres) and height == int(_yres):
        oldconnector = int(_drmconnector)
        oldcrtc = int(_drmcrtc)
        _drmconnector = int(connector)
        _drmcrtc = int(crtc)
        _drmmode = mode
        _drmdumbmodesetsequence = 0
        log(
            f"> graphics software KMS display route changed "
            f"connector={oldconnector}->{_drmconnector} "
            f"crtc={oldcrtc}->{_drmcrtc} size={width}x{height}; "
            f"next written frame will re-latch scanout"
        )
        return True

    device = str(DRMDEVICE or "").strip()
    oldwidth = int(_xres)
    oldheight = int(_yres)
    kmsframebufferclose()

    if not device or not _kmsframebufferinitdevice(device, resize=True):
        raise RuntimeError(
            f"software KMS could not rebuild for display route "
            f"{width}x{height}"
        )

    log(
        f"> graphics software KMS display rebuilt "
        f"{oldwidth}x{oldheight}->{int(_xres)}x{int(_yres)}"
    )
    return True


def _kmsframebuffercommitwrittenframe():

    global _drmdumbpresentsequence, _drmdumbmodesetsequence
    global _drmdumbflushstatus, _drmdumbdirtystatus
    global _drmdumblastpresenterror

    if (
        _backend != "kms-framebuffer"
        or _drmfd is None
        or not _drmdumbfb
        or not _drmcrtc
        or _drmmode is None
    ):
        _drmdumblastpresenterror = "software KMS commit state is incomplete"
        return False

    sequence = int(_drmdumbpresentsequence) + 1
    unsupported = {
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        errno.ENOTTY,
    }

    try:

        # Do not msync a full write-combined device mapping on every frame.
        # The following DRM ioctl is the ordering/commit boundary; msync on
        # NVIDIA video memory is unsupported and can itself stop recovery.
        _drmdumbflushstatus = "not-required:drm-ioctl-boundary"

        currentframebuffer = 0
        currentmodevalid = False
        pointer = _drm.drmModeGetCrtc(_drmfd, _drmcrtc)

        if pointer:

            try:
                current = kmsstructure(pointer, drmModeCrtc)
                currentframebuffer = int(current.buffer_id)
                currentmodevalid = bool(current.mode_valid)
            finally:
                _drm.drmModeFreeCrtc(pointer)

        # Do not take the connector with a zero-filled buffer during backend
        # initialization. The first modeset now follows the first complete CPU
        # frame; a detached or replaced CRTC is reasserted on later presents.
        modeset = bool(
            int(_drmdumbmodesetsequence) == 0
            or currentframebuffer != int(_drmdumbfb)
            or not currentmodevalid
        )

        if modeset:
            connector = ctypes.c_uint32(_drmconnector)
            result = _drm.drmModeSetCrtc(
                _drmfd,
                _drmcrtc,
                _drmdumbfb,
                0,
                0,
                ctypes.byref(connector),
                1,
                ctypes.byref(_drmmode),
            )

            if result != 0:
                error = int(ctypes.get_errno() or 0)
                kmsraise(error, "software KMS written-frame modeset")

            _drmdumbmodesetsequence = sequence

        # Notify manual-update drivers only after this framebuffer is attached
        # to the CRTC. Drivers without a dirty callback return ENOSYS and
        # continuously observe their mapped scanout memory instead.
        dirtyfunction = getattr(_drm, "drmModeDirtyFB", None)

        if callable(dirtyfunction):
            clip = drmModeClip(
                0,
                0,
                max(0, min(0xFFFF, int(_xres))),
                max(0, min(0xFFFF, int(_yres))),
            )
            dirtyresult = dirtyfunction(
                _drmfd,
                int(_drmdumbfb),
                ctypes.byref(clip),
                1,
            )

            if dirtyresult == 0:
                _drmdumbdirtystatus = "complete"
            else:
                dirtyerror = int(ctypes.get_errno() or 0)

                if dirtyerror in (errno.ENODEV, errno.EIO):
                    kmsraise(
                        dirtyerror,
                        "software KMS framebuffer damage commit",
                    )

                if dirtyerror in unsupported:
                    _drmdumbdirtystatus = f"unsupported:{dirtyerror}"
                else:
                    _drmdumbdirtystatus = f"failed:{dirtyerror}"
                    raise OSError(
                        dirtyerror or errno.EPROTO,
                        "software KMS framebuffer damage commit failed",
                    )
        else:
            _drmdumbdirtystatus = "unavailable"

        _drmdumbpresentsequence = sequence
        _drmdumblastpresenterror = None

        if sequence == 1 or modeset:
            log(
                f"> graphics software KMS written frame committed "
                f"framebuffer={_drmdumbfb} sequence={sequence} "
                f"modeset={modeset} flush={_drmdumbflushstatus} "
                f"dirty={_drmdumbdirtystatus}"
            )

        return True

    except GPUDeviceLostError:
        raise
    except Exception as error:
        _drmdumblastpresenterror = f"{type(error).__name__}: {error}"
        log(
            f"> graphics software KMS written-frame commit failed "
            f"framebuffer={_drmdumbfb} sequence={sequence} "
            f"error={_drmdumblastpresenterror}"
        )
        return False


def kmsclose():

    global _backend, _drmfd, _drmconnector, _drmcrtc, _drmmode, _drmoriginal
    global _drmdriver, _drmdriverversion, _drmdriverdate, _drmdriverdescription
    global _drmbinding
    global _gbmdevice, _gbmsurface, _gbmbo, _gbmbosurface, _gbmfb, _drmflip, _drmeventdriven
    global _drmpendingbo, _drmpendingsurface, _drmpendingfb, _drmpendingstarted
    global _glrenderer, _glversion, _gluploadbytes, _gluploadfull
    global _glgetgraphicsresetstatus, _glrobust

    try:

        if _drmfd is not None and _drmoriginal is not None and _drmoriginal.mode_valid:
            connector = ctypes.c_uint32(_drmconnector)
            _drm.drmModeSetCrtc(
                _drmfd,
                _drmoriginal.crtc_id,
                _drmoriginal.buffer_id,
                _drmoriginal.x,
                _drmoriginal.y,
                ctypes.byref(connector),
                1,
                ctypes.byref(_drmoriginal.mode),
            )

    except Exception:
        pass

    openglreleasepresent()
    _kmsreleasebuffer(_drmpendingfb, _drmpendingsurface, _drmpendingbo)
    _drmpendingbo = None
    _drmpendingsurface = None
    _drmpendingfb = 0
    _drmpendingstarted = 0
    _kmsresetpresentationcadence()

    try:
        if _drmfd is not None and _gbmfb:
            _drm.drmModeRmFB(_drmfd, _gbmfb)
    except Exception:
        pass

    try:
        if _gbmbo:
            _gbm.gbm_surface_release_buffer(_gbmbosurface or _gbmsurface, _gbmbo)
    except Exception:
        pass

    openglclose()

    try:
        if _gbmsurface:
            _gbm.gbm_surface_destroy(_gbmsurface)
    except Exception:
        pass

    try:
        if _gbmdevice:
            _gbm.gbm_device_destroy(_gbmdevice)
    except Exception:
        pass

    try:
        if _drmfd is not None:
            os.close(_drmfd)
    except Exception:
        pass

    _drmfd = None
    _drmdriver = None
    _drmdriverversion = None
    _drmdriverdate = None
    _drmdriverdescription = None
    _drmbinding = None
    _drmconnector = 0
    _drmcrtc = 0
    _drmmode = None
    _drmoriginal = None
    _drmflip = False
    _drmeventdriven = False
    _gbmdevice = None
    _gbmsurface = None
    _gbmbo = None
    _gbmbosurface = None
    _gbmfb = 0
    _glrenderer = None
    _glversion = None
    _gluploadbytes = 0
    _gluploadfull = False
    _glgetgraphicsresetstatus = None
    _glrobust = False

    if _backend == "opengl":
        _backend = "none"


def _drmcardkey(path):

    name = os.path.basename(path)
    suffix = name[4:] if name.startswith("card") else name

    try:
        return (0, int(suffix))
    except ValueError:
        return (1, suffix)


def drmcandidates():

    candidates = []
    override = os.environ.get("T1OS_DRM_DEVICE", "").strip()

    if override:
        candidates.append(override)

    try:
        cards = [
            os.path.join(DRMNODEPATH, name)
            for name in os.listdir(DRMNODEPATH)
            if name.startswith("card") and name[4:].isdigit()
        ]
    except OSError:
        cards = []

    cards.sort(key=_drmcardkey)
    connected = []
    disconnected = []

    for card in cards:

        cardname = os.path.basename(card)
        isconnected = False

        try:

            for stateentry in os.listdir(DRMSTATEPATH):

                if not stateentry.startswith(cardname + "-"):
                    continue

                statuspath = os.path.join(DRMSTATEPATH, stateentry, "status")

                try:

                    with open(statuspath, "r", encoding="utf-8") as statusfile:
                        isconnected = statusfile.read().strip().lower() == "connected"

                except OSError:
                    continue

                if isconnected:
                    break

        except OSError:
            pass

        (connected if isconnected else disconnected).append(card)

    for card in connected + disconnected:

        if card not in candidates:
            candidates.append(card)

    return candidates


def drmrendernode(device=None):

    card = str(device or DRMDEVICE or "").strip()

    if not card:
        return None

    cardname = os.path.basename(card)
    roots = [
        os.path.join(DRMSTATEPATH, cardname, "device", "drm"),
    ]

    try:
        status = os.stat(card)
        identifier = f"{os.major(status.st_rdev)}:{os.minor(status.st_rdev)}"
        roots.append(os.path.join(
            "/the one/drivers/state/dev/char",
            identifier,
            "device",
            "drm",
        ))
    except Exception:
        pass

    candidates = []

    for root in roots:

        try:
            names = os.listdir(root)
        except OSError:
            continue

        for name in names:

            if not name.startswith("renderD") or not name[7:].isdigit():
                continue

            node = os.path.join(DRMNODEPATH, name)

            if os.path.exists(node) and node not in candidates:
                candidates.append(node)

    if candidates:
        candidates.sort(key=lambda path: int(os.path.basename(path)[7:]))
        return candidates[0]

    try:
        carddevice = os.path.realpath(os.path.join(DRMSTATEPATH, cardname, "device"))
        names = os.listdir(DRMNODEPATH)
    except OSError:
        carddevice = ""
        names = []

    for name in sorted(names):

        if not name.startswith("renderD") or not name[7:].isdigit():
            continue

        statedevice = os.path.realpath(os.path.join(DRMSTATEPATH, name, "device"))

        if carddevice and statedevice == carddevice:
            node = os.path.join(DRMNODEPATH, name)

            if os.path.exists(node):
                return node

    # A number of virtual DRM stacks expose the card and render nodes through
    # incomplete sysfs mirrors.  A single card plus a single render node is
    # still an unambiguous same-device topology; using it avoids inventing a
    # cross-GPU fallback while keeping VirtualBox and other one-GPU guests
    # usable.
    try:
        rendernodes = sorted(
            os.path.join(DRMNODEPATH, name)
            for name in os.listdir(DRMNODEPATH)
            if name.startswith("renderD")
            and name[7:].isdigit()
            and os.path.exists(os.path.join(DRMNODEPATH, name))
        )
        if len(rendernodes) == 1 and bool(_drmdriver):
            return rendernodes[0]

    except OSError:
        pass

    return None


def _kmsinitdevice(device):

    global _backend, _drmfd, _drmconnector, _drmcrtc, _drmmode, _drmoriginal
    global _drmdriver, _drmdriverversion, _drmdriverdate, _drmdriverdescription
    global _drmbinding
    global _gbmdevice, _gbmsurface, _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes
    global _line, _size, _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen
    global _pack, _packint, _unpack, _IS_FILE_BUFFER, _eglconfig
    global _egldisplay, _eglsurface, _eglcontext, _eglmajor, _eglminor
    global _eglvendor, _eglextensions, _eglextensionsqueried, _glextensions
    global _glrenderer, _glversion, _glrobust

    kmsclose()

    try:

        if not drmload():
            raise RuntimeError("DRM library did not load")

        _drmbinding = _graphicsdrmbinding(device)
        # Mesa's abort-on-loss switch is a developer diagnostic. In a display
        # server it bypasses robust-context reporting and turns a supervised
        # GPU-owner restart into an unexplained process abort.
        os.environ.pop("MESA_VK_ABORT_ON_DEVICE_LOSS", None)
        _drmfd = os.open(device, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        driverinfo = kmsdriverinfo()
        _drmdriver = driverinfo.get("name")
        _drmdriverversion = driverinfo.get("version")
        _drmdriverdate = driverinfo.get("date")
        _drmdriverdescription = driverinfo.get("description")
        provider = _graphicsdrmprovider(device, _drmbinding, _drmdriver)
        log(
            f"> graphics DRM driver {_drmdriver or 'unknown'} "
            f"{_drmdriverversion or 'unknown'} binding={_drmbinding or 'unknown'} "
            f"provider={provider}"
        )

        # Provider selection is complete before any EGL client or vendor
        # library is loaded.  The official NVIDIA DRM driver cannot be driven
        # through Mesa/NVK; Nouveau and every non-NVIDIA DRM driver retain the
        # existing Mesa path.
        if not kmsload(provider):
            raise RuntimeError(
                f"KMS libraries did not load provider={provider}"
            )

        os.environ.pop("GALLIUM_DRIVER", None)

        if _drmdriver == "nouveau":
            os.environ["GALLIUM_DRIVER"] = "zink"
            os.environ["VK_DRIVER_FILES"] = os.path.join(
                GRAPHICSCATALOGUE,
                "vulkan/icd.d/nouveau_icd.x86_64.json",
            )
            # Use upstream Zink scheduling. The old noreorder debugging option
            # serialized this command stream and made cold NVK presentation
            # substantially more likely to outlive WindowServer's watchdog.
        else:
            os.environ.pop("VK_DRIVER_FILES", None)

        shadercache = "/.ephemeral/cache/graphics"
        nvidiacache = "/.ephemeral/cache/nvidia"

        try:
            os.makedirs(shadercache, exist_ok=True)
            os.environ.setdefault("MESA_SHADER_CACHE_DIR", shadercache)
            os.environ.setdefault("MESA_SHADER_CACHE_MAX_SIZE", "256M")
            # The proprietary driver otherwise derives HOME/.nv/GLCache. The
            # directory itself is prepared as a shared sticky runtime cache by
            # GODDESS before NVIDIA graphics clients are launched.
            if _drmdriver in ("nvidia", "nvidia_drm"):
                os.environ["__GL_SHADER_DISK_CACHE_PATH"] = nvidiacache
            else:
                os.environ.pop("__GL_SHADER_DISK_CACHE_PATH", None)
        except OSError as error:
            log(f"> graphics shader cache directory unavailable {error}")

        _drmconnector, _drmcrtc, _drmmode = kmsfindmode()
        originalpointer = _drm.drmModeGetCrtc(_drmfd, _drmcrtc)

        if originalpointer:

            try:
                _drmoriginal = kmsstructure(originalpointer, drmModeCrtc)
            finally:
                _drm.drmModeFreeCrtc(originalpointer)

        _xres = int(_drmmode.hdisplay)
        _yres = int(_drmmode.vdisplay)
        modetarget = (
            f"{KMSMODEWIDTH}x{KMSMODEHEIGHT}"
            if KMSMODEEXPLICIT
            else "active-framebuffer"
        )
        log(
            f"> graphics DRM mode {_xres}x{_yres}"
            f"@{kmsmoderefresh(_drmmode):.3f}Hz target {modetarget}"
        )
        _yvirt = _yres
        _bpp = 32
        _bpp_bytes = 4
        _line = _xres * 4
        _size = _line * _yres
        _boff = 0
        _blen = 8
        _goff = 8
        _glen = 8
        _roff = 16
        _rlen = 8
        _aoff = 24
        _alen = 8
        packer = struct.Struct("<I")
        _unpack = packer.unpack
        _packint = packer.pack
        _pack = packbgra
        _buffer = bytearray(_size)
        _IS_FILE_BUFFER = False

        _gbmdevice = openglrequire(_gbm.gbm_create_device(_drmfd), "gbm_create_device")
        log("> graphics GBM device ready")
        _gbmsurface = openglrequire(
            _gbm.gbm_surface_create(
                _gbmdevice,
                _xres,
                _yres,
                GBM_FORMAT_XRGB8888,
                GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING,
            ),
            "gbm_surface_create",
        )
        log("> graphics GBM surface ready")
        _egldisplay = openglrequire(
            _egl.eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, _gbmdevice, None),
            "eglGetPlatformDisplay GBM",
        )
        major = ctypes.c_int()
        minor = ctypes.c_int()
        openglrequire(_egl.eglInitialize(_egldisplay, ctypes.byref(major), ctypes.byref(minor)), "eglInitialize GBM")
        _eglmajor = major.value
        _eglminor = minor.value
        vendorvalue = openglrequire(
            _egl.eglQueryString(_egldisplay, EGL_VENDOR),
            "eglQueryString EGL_VENDOR",
        )
        _eglvendor = (
            vendorvalue.decode("utf-8", errors="replace")
            if vendorvalue
            else None
        )
        log(
            f"> graphics EGL display ready {_eglmajor}.{_eglminor} "
            f"provider={provider} vendor={_eglvendor or 'unknown'}"
        )

        if (
            provider == "nvidia"
            and "nvidia" not in str(_eglvendor or "").casefold()
        ):
            raise RuntimeError(
                f"NVIDIA EGL vendor verification failed "
                f"vendor={_eglvendor!r}"
            )

        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=extension-query state=begin")

        if provider == "nvidia":
            # The failed hardware trace reaches NVIDIA eglInitialize and the
            # vendor query, then stops before the next log. The first unlogged
            # call in that image is eglQueryString(EGL_EXTENSIONS). Robust EGL
            # context discovery is required only by the Nouveau/NVK path, so
            # do not make NVIDIA's cold-start extension enumeration a boot
            # barrier. Reset/loss detection remains available through EGL/GL
            # errors and the supervised owner.
            extensions = []
            extensionstate = "skipped-nvidia-cold-start"
            _eglextensionsqueried = False
        else:
            extensionvalue = _egl.eglQueryString(
                _egldisplay,
                EGL_EXTENSIONS,
            )
            extensions = (
                extensionvalue.decode("ascii", errors="ignore").split()
                if extensionvalue
                else []
            )
            extensionstate = "queried"
            _eglextensionsqueried = True

        _eglextensions = frozenset(extensions)
        _glextensions = None

        log(
            f"> graphics EGL init stage=extension-query state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f} "
            f"operation={extensionstate}"
        )
        robustcontext = "EGL_EXT_create_context_robustness" in extensions

        if _drmdriver == "nouveau" and not robustcontext:
            raise RuntimeError(
                "NVK requires EGL_EXT_create_context_robustness"
            )

        attributes = (ctypes.c_int * 13)(
            EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
            EGL_RED_SIZE, 8,
            EGL_GREEN_SIZE, 8,
            EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 0,
            EGL_NONE,
        )
        configs = (ctypes.c_void_p * 64)()
        count = ctypes.c_int()
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=config-choose state=begin")
        openglrequire(
            _egl.eglChooseConfig(_egldisplay, attributes, configs, len(configs), ctypes.byref(count)),
            "eglChooseConfig GBM",
        )

        _eglconfig, selectedindex, selectedvisual = _eglchoosexrgbconfig(
            configs,
            count.value,
        )

        log(
            f"> graphics EGL init stage=config-choose state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f} "
            f"configs={int(count.value)} selected={selectedindex} "
            f"visual={selectedvisual if selectedvisual is not None else 'default'}"
        )
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=bind-api state=begin")
        openglrequire(_egl.eglBindAPI(EGL_OPENGL_ES_API), "eglBindAPI GBM")
        log(
            f"> graphics EGL init stage=bind-api state=complete elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        surfaceattributes = (ctypes.c_int * 1)(EGL_NONE)
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=window-surface state=begin")
        _eglsurface = openglrequire(
            _egl.eglCreateWindowSurface(_egldisplay, _eglconfig, _gbmsurface, surfaceattributes),
            "eglCreateWindowSurface",
        )
        log(
            f"> graphics EGL init stage=window-surface state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        if robustcontext:
            contextattributes = (ctypes.c_int * 7)(
                EGL_CONTEXT_CLIENT_VERSION, 2,
                EGL_CONTEXT_OPENGL_ROBUST_ACCESS_EXT, 1,
                EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_EXT,
                EGL_LOSE_CONTEXT_ON_RESET_EXT,
                EGL_NONE,
            )
        else:
            contextattributes = (ctypes.c_int * 3)(
                EGL_CONTEXT_CLIENT_VERSION,
                2,
                EGL_NONE,
            )
        eglstagestarted = time.monotonic_ns()
        log(
            f"> graphics EGL init stage=context-create state=begin "
            f"robust={bool(robustcontext)}"
        )
        _eglcontext = openglrequire(
            _egl.eglCreateContext(_egldisplay, _eglconfig, None, contextattributes),
            "eglCreateContext GBM",
        )
        log(
            f"> graphics EGL init stage=context-create state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=make-current state=begin")
        openglrequire(
            _egl.eglMakeCurrent(_egldisplay, _eglsurface, _eglsurface, _eglcontext),
            "eglMakeCurrent GBM",
        )
        log(
            f"> graphics EGL init stage=make-current state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=presentation-interval state=begin")
        _eglconfigurekmspresentation()
        log(
            f"> graphics EGL init stage=presentation-interval state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f} "
            f"interval={_eglswapinterval} "
            f"range={_eglminswapinterval}..{_eglmaxswapinterval} "
            f"owner=DRM-page-flip "
            f"explicit={_openglprovider != 'nvidia'}"
        )
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=reset-status-load state=begin")
        openglloadresetstatus(required=_drmdriver == "nouveau")
        log(
            f"> graphics EGL init stage=reset-status-load state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=presentation-resources state=begin")
        openglpreparepresent()
        log(
            f"> graphics EGL init stage=presentation-resources state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        resetdirty()
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=cursor-load state=begin")
        loadcursor()
        log(
            f"> graphics EGL init stage=cursor-load state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        _backend = "opengl"
        eglstagestarted = time.monotonic_ns()
        log("> graphics EGL init stage=renderer-query state=begin")
        renderer = _gles.glGetString(GL_RENDERER)
        version = _gles.glGetString(GL_VERSION)
        log(
            f"> graphics EGL init stage=renderer-query state=complete "
            f"elapsed_ms="
            f"{(time.monotonic_ns() - eglstagestarted) / 1000000.0:.3f}"
        )
        renderertext = renderer.decode("utf-8", errors="replace") if renderer else "unknown"
        versiontext = version.decode("utf-8", errors="replace") if version else "unknown"

        if provider == "nvidia" and "nvidia" not in renderertext.casefold():
            raise RuntimeError(
                f"NVIDIA renderer verification failed "
                f"renderer={renderertext!r}"
            )

        _glrenderer = renderertext
        _glversion = versiontext
        log(
            f"> graphics OpenGL ready {_xres}x{_yres} "
            f"EGL {_eglmajor}.{_eglminor} robust={bool(_glrobust)} "
            f"{renderertext}"
        )
        return True

    except GPUDeviceLostError as e:

        log(f"> graphics OpenGL init reported device loss {e}")
        kmsclose()
        raise

    except OSError as e:

        if int(getattr(e, "errno", 0) or 0) in (errno.ENODEV, errno.EIO):
            log(f"> graphics OpenGL init reported DRM device loss {e}")
            kmsclose()
            raise GPUDeviceLostError(
                f"OpenGL init lost DRM device during system call: {e}"
            ) from e

        log(f"> graphics OpenGL init failed {e}")
        kmsclose()
        return False

    except Exception as e:

        log(f"> graphics OpenGL init failed {e}")
        kmsclose()
        return False

    finally:

        # NVIDIA's documented GBM trace switch is useful while constructing
        # the provider, surface and context.  Do not leave verbose vendor
        # tracing enabled for every buffer operation during the desktop
        # session.
        if "provider" in locals() and provider == "nvidia":
            os.environ.pop("__NV_GBM_TRACE_ENABLED", None)


def kmsinit(device=None):

    global DRMDEVICE

    selected = str(device or DRMDEVICE or "").strip()
    # T1OS launches one WindowServer per selected DRM device. This keeps
    # NVIDIA GLVND and Mesa in separate processes: neither provider can be
    # safely dlclosed and replaced after initialization has begun.
    candidates = [selected] if selected else drmcandidates()

    if not candidates:
        log("> graphics found no DRM card devices")
        return False

    log(f"> graphics DRM candidates {', '.join(candidates)}")

    for candidate in candidates:

        if _kmsinitdevice(candidate):
            DRMDEVICE = candidate
            log(f"> graphics selected DRM device {candidate}")
            return True

    return False


def kmsresize(waitpulse=None):

    global _drmconnector, _drmcrtc, _drmmode, _drmflip
    global _gbmsurface, _gbmbo, _gbmbosurface, _gbmfb
    global _eglsurface, _buffer, _xres, _yres, _yvirt, _line, _size
    global _kmsresizes, _kmsresizefailures

    newgbmsurface = None
    neweglsurface = None
    changed = False
    oldconnector = _drmconnector
    oldcrtc = _drmcrtc
    oldmode = _drmmode
    oldgbmsurface = _gbmsurface
    oldeglsurface = _eglsurface
    oldbuffer = _buffer
    oldwidth = _xres
    oldheight = _yres
    oldyvirt = _yvirt
    oldline = _line
    oldsize = _size

    try:

        connector, crtc, mode = kmsfindmode(resize=True)

        if (
            int(connector) == int(_drmconnector)
            and int(crtc) == int(_drmcrtc)
            and kmsmodekey(mode) == kmsmodekey(_drmmode)
        ):
            return False

        if not kmsvalidmode(mode):
            raise RuntimeError(f"invalid DRM resize mode {int(mode.hdisplay)}x{int(mode.vdisplay)}")

        width = int(mode.hdisplay)
        height = int(mode.vdisplay)
        modetarget = (
            f"{KMSMODEWIDTH}x{KMSMODEHEIGHT}"
            if KMSMODEEXPLICIT
            else "active-framebuffer"
        )
        log(
            f"> graphics DRM mode change requested "
            f"{int(oldwidth)}x{int(oldheight)}"
            f"@{kmsmoderefresh(oldmode):.3f}Hz -> "
            f"{width}x{height}@{kmsmoderefresh(mode):.3f}Hz "
            f"target {modetarget}"
        )
        newbuffer = bytearray(width * height * 4)

        if _drmflip:

            if not kmswaitflip(waitpulse=waitpulse):
                raise RuntimeError("DRM page flip did not complete before display resize")

        gpuabort()

        newgbmsurface = openglrequire(
            _gbm.gbm_surface_create(
                _gbmdevice,
                width,
                height,
                GBM_FORMAT_XRGB8888,
                GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING,
            ),
            "gbm_surface_create resize",
        )
        surfaceattributes = (ctypes.c_int * 1)(EGL_NONE)
        neweglsurface = openglrequire(
            _egl.eglCreateWindowSurface(_egldisplay, _eglconfig, newgbmsurface, surfaceattributes),
            "eglCreateWindowSurface resize",
        )
        openglrequire(
            _egl.eglMakeCurrent(_egldisplay, neweglsurface, neweglsurface, _eglcontext),
            "eglMakeCurrent resize",
        )
        _eglconfigurekmspresentation()

        _gpucompositorrelease()
        openglreleasepresent()
        _drmconnector = int(connector)
        _drmcrtc = int(crtc)
        _drmmode = mode
        _gbmsurface = newgbmsurface
        _eglsurface = neweglsurface
        _buffer = newbuffer
        _xres = width
        _yres = height
        _yvirt = height
        _line = width * 4
        _size = _line * height
        openglpreparepresent()
        resetdirty()
        markdirty(0, 0, width, height)

        if not openglupload():
            raise RuntimeError("OpenGL resize upload failed")

        if not kmsscanout(force_modeset=True, waitpulse=waitpulse):
            raise RuntimeError("KMS resize scanout failed")

        changed = True
        _kmsresizes += 1
        gpuinvalidatesurface()

        try:
            _egl.eglDestroySurface(_egldisplay, oldeglsurface)
        except Exception:
            pass

        try:
            _gbm.gbm_surface_destroy(oldgbmsurface)
        except Exception:
            pass

        log(
            f"> graphics DRM resize {oldwidth}x{oldheight}"
            f"@{kmsmoderefresh(oldmode):.3f}Hz -> "
            f"{width}x{height}@{kmsmoderefresh(mode):.3f}Hz"
        )
        return True

    except GPUDeviceLostError as e:

        _kmsresizefailures += 1
        log(f"> graphics DRM resize aborted by device loss {e}")
        raise

    except Exception as e:

        _kmsresizefailures += 1

        if changed:
            log(f"> graphics DRM resize committed with cleanup error {e}")
            return True

        try:
            openglreleasepresent()
        except Exception:
            pass

        rollbackfailure = None

        try:
            _drmconnector = oldconnector
            _drmcrtc = oldcrtc
            _drmmode = oldmode
            _gbmsurface = oldgbmsurface
            _eglsurface = oldeglsurface
            _buffer = oldbuffer
            _xres = oldwidth
            _yres = oldheight
            _yvirt = oldyvirt
            _line = oldline
            _size = oldsize
            openglrequire(
                _egl.eglMakeCurrent(_egldisplay, oldeglsurface, oldeglsurface, _eglcontext),
                "eglMakeCurrent resize rollback",
            )
            _eglconfigurekmspresentation()
            openglpreparepresent()
            resetdirty()
            markdirty(0, 0, oldwidth, oldheight)
            gpuinvalidatesurface()
        except Exception as rollbackerror:
            rollbackfailure = rollbackerror
            log(f"> graphics DRM resize rollback failed {rollbackerror}")

        try:
            if neweglsurface:
                _egl.eglDestroySurface(_egldisplay, neweglsurface)
        except Exception:
            pass

        try:
            if newgbmsurface:
                _gbm.gbm_surface_destroy(newgbmsurface)
        except Exception:
            pass

        if rollbackfailure is not None:
            if isinstance(rollbackfailure, GPUDeviceLostError):
                raise rollbackfailure

            raise RuntimeError(
                f"DRM resize failed ({e}) and rollback could not restore "
                f"the compositor: {rollbackfailure}"
            ) from rollbackfailure

        log(f"> graphics DRM resize failed {e}")
        return False


def backendname():

    return str(_backend)


def _graphicsdriverfamily(value):

    identity = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    for family, aliases in (
        ("nvidia", ("nvidia", "nvidiadrm", "nvidiadrmfb")),
        ("amdgpu", ("amdgpu", "amdgpudrmfb")),
        ("nouveau", ("nouveau", "nouveaudrmfb")),
        ("intel", ("i915", "xe", "inteldrm", "inteldrmfb")),
        ("vmwgfx", ("vmwgfx", "svgadrmfb")),
        (
            "virtio",
            ("virtiogpu", "virtiodrm", "virtiodrmfb", "virtiopci"),
        ),
        ("bochs", ("bochs", "bochsdrm", "bochsdrmfb")),
        ("ast", ("ast", "astdrm", "astdrmfb")),
    ):

        if identity in aliases:
            return family

    return identity


def _relateddevicepaths(first, second):

    first = os.path.normcase(os.path.normpath(str(first or "")))
    second = os.path.normcase(os.path.normpath(str(second or "")))

    if not first or not second:
        return False

    return bool(
        first == second
        or first.startswith(second + os.sep)
        or second.startswith(first + os.sep)
    )


def _drmcrtcsequenceproof(descriptor, crtc, timeout=0.12):

    result = {
        "supported": False,
        "unsupported": False,
        "advanced": False,
        "before": None,
        "after": None,
        "timestamp_ns": None,
        "errno": None,
        "error": None,
    }
    operation = getattr(_drm, "drmCrtcGetSequence", None)

    if operation is None:
        result["unsupported"] = True
        result["error"] = "drmCrtcGetSequence unavailable"
        return result

    before = ctypes.c_uint64()
    timestamp = ctypes.c_uint64()
    status = operation(
        int(descriptor),
        int(crtc),
        ctypes.byref(before),
        ctypes.byref(timestamp),
    )

    if status != 0:
        error = int(
            ctypes.get_errno()
            or (-int(status) if int(status) < 0 else 0)
        )
        result["errno"] = error or None

        if error in (errno.ENODEV, errno.EIO):
            kmsraise(error, "initial CRTC sequence query")

        unsupported = {
            errno.EINVAL,
            errno.ENOSYS,
            errno.ENOTTY,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }

        if error in unsupported:
            result["unsupported"] = True
            result["error"] = (
                f"drmCrtcGetSequence unsupported errno={error} "
                f"{os.strerror(error) if error else 'unknown'}"
            )
            return result

        result["supported"] = True
        result["error"] = (
            f"initial drmCrtcGetSequence failed errno={error} "
            f"{os.strerror(error) if error else 'unknown'}"
        )
        return result

    result["supported"] = True
    result["before"] = int(before.value)
    result["after"] = int(before.value)
    result["timestamp_ns"] = int(timestamp.value)
    deadline = time.monotonic() + max(0.01, float(timeout))

    while time.monotonic() < deadline:
        time.sleep(0.005)
        after = ctypes.c_uint64()
        timestamp = ctypes.c_uint64()
        status = operation(
            int(descriptor),
            int(crtc),
            ctypes.byref(after),
            ctypes.byref(timestamp),
        )

        if status != 0:
            error = int(
                ctypes.get_errno()
                or (-int(status) if int(status) < 0 else 0)
            )

            if error in (errno.ENODEV, errno.EIO):
                kmsraise(error, "follow-up CRTC sequence query")

            result["error"] = (
                f"follow-up drmCrtcGetSequence failed errno={error} "
                f"{os.strerror(error) if error else 'unknown'}"
            )
            return result

        result["after"] = int(after.value)
        result["timestamp_ns"] = int(timestamp.value)

        if int(after.value) > int(before.value):
            result["advanced"] = True
            return result

    result["error"] = (
        f"CRTC sequence did not advance within {float(timeout):.3f}s"
    )
    return result


def _drmconnectorlinkstatus(descriptor, connector):

    operation = getattr(_drm, "drmModeGetProperty", None)
    freeoperation = getattr(_drm, "drmModeFreeProperty", None)

    if operation is None or freeoperation is None:
        return None

    for index in range(max(0, int(connector.count_props))):
        propertypointer = None

        try:
            propertyid = int(connector.props[index])
            propertyvalue = int(connector.prop_values[index])
            propertypointer = operation(int(descriptor), propertyid)

            if not propertypointer:
                continue

            prop = propertypointer.contents
            name = bytes(prop.name).split(b"\0", 1)[0].decode(
                "ascii",
                errors="replace",
            ).strip().lower()

            if name == "link-status":
                return "good" if propertyvalue == 0 else "bad"

        except Exception:
            continue
        finally:

            if propertypointer:

                try:
                    freeoperation(propertypointer)
                except Exception:
                    pass

    return None


def _drmdevicevblankproof(device):

    result = {
        "device": str(device),
        "connector": None,
        "crtc": None,
        "connector_connected": False,
        "connector_routed": False,
        "connector_link_status": None,
        "vblank": {
            "supported": False,
            "advanced": False,
            "before": None,
            "after": None,
            "timestamp_ns": None,
            "error": "DRM device was not queried",
        },
    }
    descriptor = None
    resourcespointer = None

    try:

        if not drmload():
            result["error"] = "DRM library unavailable"
            return result

        descriptor = os.open(
            str(device),
            os.O_RDWR | getattr(os, "O_CLOEXEC", 0),
        )
        resourcespointer = _drm.drmModeGetResources(descriptor)

        if not resourcespointer:
            result["error"] = "drmModeGetResources returned no resources"
            return result

        resources = resourcespointer.contents

        for index in range(max(0, int(resources.count_connectors))):
            connectorpointer = None
            encoderpointer = None

            try:
                connectorpointer = _drm.drmModeGetConnector(
                    descriptor,
                    int(resources.connectors[index]),
                )

                if not connectorpointer:
                    continue

                connector = connectorpointer.contents

                if int(connector.connection) != DRM_MODE_CONNECTED:
                    continue

                result["connector"] = int(connector.connector_id)
                result["connector_connected"] = True
                result["connector_link_status"] = (
                    _drmconnectorlinkstatus(descriptor, connector)
                )

                if not int(connector.encoder_id or 0):
                    continue

                encoderpointer = _drm.drmModeGetEncoder(
                    descriptor,
                    int(connector.encoder_id),
                )

                if not encoderpointer:
                    continue

                crtc = int(encoderpointer.contents.crtc_id or 0)

                if not crtc:
                    continue

                result["crtc"] = crtc
                result["connector_routed"] = True
                result["vblank"] = _drmcrtcsequenceproof(
                    descriptor,
                    crtc,
                )
                return result

            finally:

                if encoderpointer:
                    _drm.drmModeFreeEncoder(encoderpointer)

                if connectorpointer:
                    _drm.drmModeFreeConnector(connectorpointer)

        result["error"] = "no connected routed connector"
        return result

    except GPUDeviceLostError:
        raise
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result

    finally:

        if resourcespointer:

            try:
                _drm.drmModeFreeResources(resourcespointer)
            except Exception:
                pass

        if descriptor is not None:

            try:
                os.close(descriptor)
            except OSError:
                pass


def _legacyframebufferowners():

    evidence = {
        "identity": "",
        "name": "",
        "device": "",
        "driver": "",
        "native": [],
        "matched": [],
        "owner_connected": False,
        "drm_probe_complete": False,
        "drm_nodes": [],
        "firmware_framebuffer": False,
    }

    try:
        fixed = bytearray(FB_FIX_SCREENINFO_SIZE)
        fcntl.ioctl(_fd, FBIOGET_FSCREENINFO, fixed, True)
        evidence["identity"] = bytes(fixed[:16]).split(b"\0", 1)[0].decode(
            "ascii",
            errors="replace",
        ).strip()
    except Exception as error:
        evidence["identity_error"] = str(error)

    try:
        with open(
            os.path.join(FRAMEBUFFERSTATEPATH, "name"),
            "r",
            encoding="ascii",
            errors="replace",
        ) as stream:
            evidence["name"] = stream.read(256).strip()
    except OSError:
        pass

    framebufferdevice = os.path.join(FRAMEBUFFERSTATEPATH, "device")

    try:

        if os.path.lexists(framebufferdevice):
            evidence["device"] = os.path.realpath(framebufferdevice)

        framebufferdriver = os.path.join(framebufferdevice, "driver")

        if os.path.lexists(framebufferdriver):
            evidence["driver"] = os.path.basename(
                os.path.realpath(framebufferdriver).rstrip(os.sep)
            ).strip().lower()
    except OSError:
        pass

    framebufferfamilies = {
        _graphicsdriverfamily(evidence["identity"]),
        _graphicsdriverfamily(evidence["name"]),
        _graphicsdriverfamily(evidence["driver"]),
    }
    framebufferfamilies.discard("")
    framebufferidentity = re.sub(
        r"[^a-z0-9]+",
        "",
        " ".join(
            (
                evidence["identity"],
                evidence["name"],
                evidence["driver"],
            )
        ).lower(),
    )
    evidence["firmware_framebuffer"] = any(
        marker in framebufferidentity
        for marker in (
            "efivga",
            "efifb",
            "efiframebuffer",
            "simpleframebuffer",
            "simpledrmfb",
            "vesafb",
            "vesaframebuffer",
        )
    )

    try:
        drmstateentries = os.listdir(DRMSTATEPATH)
        evidence["drm_probe_complete"] = True
    except OSError as error:
        drmstateentries = []
        evidence["drm_probe_error"] = str(error)

    try:
        evidence["drm_nodes"] = sorted(
            name
            for name in os.listdir(DRMNODEPATH)
            if re.fullmatch(r"card[0-9]+", name)
        )
    except OSError as error:
        evidence["drm_node_probe_error"] = str(error)

    try:
        candidates = drmcandidates()
    except Exception as error:
        evidence["drm_probe_error"] = str(error)
        evidence["drm_probe_complete"] = False
        candidates = []

    # The state mirror is authoritative for driver ownership even when a
    # failed or partially recovered devtmpfs has not recreated /nodes/dri.
    # Otherwise a native card with a missing node can make stale efifb memory
    # look like the only display device and incorrectly certify it.
    for entry in drmstateentries:

        if not re.fullmatch(r"card[0-9]+", entry):
            continue

        candidate = os.path.join(DRMNODEPATH, entry)

        if candidate not in candidates:
            candidates.append(candidate)

    possibleowners = []

    for candidate in candidates:
        card = os.path.basename(candidate)
        binding = str(_graphicsdrmbinding(candidate) or "").strip().lower()

        if not binding or binding in (
            "simpledrm",
            "simple-framebuffer",
            "efifb",
            "vesafb",
        ):
            continue

        nativeentry = f"{card}:{binding}"
        evidence["native"].append(nativeentry)
        carddevices = []

        for root in _graphicsdrmroots(candidate):

            try:

                if os.path.lexists(root):
                    carddevices.append(os.path.realpath(root))
            except OSError:
                pass

        devicematch = any(
            _relateddevicepaths(evidence["device"], carddevice)
            for carddevice in carddevices
        )
        familymatch = bool(
            _graphicsdriverfamily(binding) in framebufferfamilies
        )
        statuses = []

        for entry in drmstateentries:

            if not entry.startswith(card + "-"):
                continue

            try:
                with open(
                    os.path.join(DRMSTATEPATH, entry, "status"),
                    "r",
                    encoding="ascii",
                    errors="replace",
                ) as stream:
                    statuses.append(stream.read(64).strip().lower())
            except OSError:
                pass

        connected = "connected" in statuses

        if devicematch or familymatch:
            possibleowners.append({
                "card": card,
                "binding": binding,
                "device_match": bool(devicematch),
                "family_match": bool(familymatch),
                "connector_states": statuses,
                "connected": bool(connected),
            })

    # PCI/sysfs ancestry is authoritative when fb0 exposes it. Family names
    # are only a compatibility fallback for incomplete sysfs mirrors, and only
    # when they identify exactly one native card. Otherwise two same-vendor
    # adapters could let a connected sibling certify the wrong framebuffer.
    if evidence["device"]:
        evidence["matched"] = [
            owner for owner in possibleowners
            if owner.get("device_match")
        ]
    else:
        familyowners = [
            owner for owner in possibleowners
            if owner.get("family_match")
        ]
        evidence["matched"] = familyowners if len(familyowners) == 1 else []

    evidence["owner_connected"] = any(
        owner.get("connected")
        for owner in evidence["matched"]
    )

    return evidence


def framebufferpresentationproof(require_nonblack=True):

    result = {
        "verified": False,
        "backend": str(_backend),
        "scanout": False,
        "readback": False,
        "nonblack": False,
        "framebuffer": None,
        "expected_framebuffer": None,
        "mode_valid": False,
        "expected_mode": None,
        "current_mode": None,
        "mode_matches": False,
        "connector": None,
        "connector_connected": False,
        "connector_encoder": None,
        "connector_crtc": None,
        "connector_routed": False,
        "connector_link_status": None,
        "vblank_sequence": {
            "supported": False,
            "unsupported": False,
            "advanced": False,
            "before": None,
            "after": None,
            "timestamp_ns": None,
            "errno": None,
            "error": None,
        },
        "write_committed": False,
        "present_sequence": 0,
        "modeset_sequence": 0,
        "flush_status": None,
        "dirty_status": None,
        "last_present_error": None,
        "presentation_boundary": None,
        "readback_mismatch_offset": None,
        "legacy_conflicting_drm": [],
        "legacy_page_zero": False,
        "legacy_framebuffer_identity": None,
        "legacy_framebuffer_name": None,
        "legacy_framebuffer_device": None,
        "legacy_framebuffer_driver": None,
        "legacy_drm_owner": [],
        "legacy_owner_connected": False,
        "legacy_drm_probe_complete": False,
        "legacy_firmware_framebuffer": False,
        "legacy_native_scanout": None,
        "firmware_framebuffer_boot": bool(FIRMWAREFRAMEBUFFERBOOT),
        "legacy_console_owned": bool(FRAMEBUFFERCONSOLEOWNED),
        "legacy_write_sequence": int(_framebufferwritesequence),
        "legacy_pan_sequence": int(_framebufferpansequence),
        "legacy_pan_committed": bool(
            int(_framebufferwritesequence) > 0
            and int(_framebufferpansequence) == int(_framebufferwritesequence)
        ),
    }

    if _backend not in ("framebuffer", "kms-framebuffer"):
        return result

    if _backend == "kms-framebuffer":
        result["expected_framebuffer"] = int(_drmdumbfb or 0)
        result["expected_mode"] = kmsmodeproofkey(_drmmode)
        result["present_sequence"] = int(_drmdumbpresentsequence)
        result["modeset_sequence"] = int(_drmdumbmodesetsequence)
        result["flush_status"] = str(_drmdumbflushstatus)
        result["dirty_status"] = str(_drmdumbdirtystatus)
        result["last_present_error"] = _drmdumblastpresenterror
        result["write_committed"] = bool(
            int(_drmdumbpresentsequence) > 0
            and int(_drmdumbmodesetsequence) > 0
            and not _drmdumblastpresenterror
        )

        # CRTC state is authoritative and must be reported even if reading a
        # write-combined device mapping is unsupported or returns stale data.
        result["connector"] = int(_drmconnector or 0)

        try:
            connectorpointer = _drm.drmModeGetConnector(
                _drmfd,
                _drmconnector,
            )

            if connectorpointer:

                try:
                    connector = connectorpointer.contents
                    result["connector_connected"] = bool(
                        int(connector.connection) == DRM_MODE_CONNECTED
                    )
                    result["connector_encoder"] = int(
                        connector.encoder_id or 0
                    )
                    result["connector_link_status"] = (
                        _drmconnectorlinkstatus(_drmfd, connector)
                    )
                finally:
                    _drm.drmModeFreeConnector(connectorpointer)
            else:
                result["connector_error"] = (
                    "drmModeGetConnector returned no connector"
                )

            if result["connector_encoder"]:
                encoderpointer = _drm.drmModeGetEncoder(
                    _drmfd,
                    int(result["connector_encoder"]),
                )

                if encoderpointer:

                    try:
                        encoder = encoderpointer.contents
                        result["connector_crtc"] = int(
                            encoder.crtc_id or 0
                        )
                        result["connector_routed"] = bool(
                            int(encoder.crtc_id or 0) == int(_drmcrtc)
                        )
                    finally:
                        _drm.drmModeFreeEncoder(encoderpointer)
                else:
                    result["encoder_error"] = (
                        "drmModeGetEncoder returned no encoder"
                    )
        except Exception as error:
            result["connector_error"] = (
                f"{type(error).__name__}: {error}"
            )

        try:
            pointer = _drm.drmModeGetCrtc(_drmfd, _drmcrtc)

            if pointer:

                try:
                    current = kmsstructure(pointer, drmModeCrtc)
                    result["framebuffer"] = int(current.buffer_id)
                    result["mode_valid"] = bool(current.mode_valid)
                    result["current_mode"] = (
                        kmsmodeproofkey(current.mode)
                        if result["mode_valid"]
                        else None
                    )
                    result["mode_matches"] = bool(
                        result["expected_mode"] is not None
                        and result["current_mode"] == result["expected_mode"]
                    )
                    result["scanout"] = bool(
                        int(_drmdumbfb) > 0
                        and int(current.buffer_id) == int(_drmdumbfb)
                        and result["mode_valid"]
                        and result["mode_matches"]
                    )
                finally:
                    _drm.drmModeFreeCrtc(pointer)
            else:
                result["crtc_error"] = "drmModeGetCrtc returned no CRTC"
        except Exception as error:
            result["crtc_error"] = f"{type(error).__name__}: {error}"

        if result["scanout"]:
            result["vblank_sequence"] = _drmcrtcsequenceproof(
                _drmfd,
                _drmcrtc,
            )

    if _map is None or not _buffer or _size < 1:
        result["error"] = "framebuffer mapping or shadow buffer unavailable"
        return result

    size = min(int(_size), len(_buffer))
    pixelbytes = max(1, int(_bpp_bytes))

    try:
        black = bytes(packrgb((0, 0, 0)))
    except Exception:
        black = bytes(pixelbytes)

    if len(black) != pixelbytes:
        black = bytes(pixelbytes)

    content = False
    nonblackoffset = None
    activebytes = max(
        0,
        min(int(_line), int(_xres) * pixelbytes),
    )

    # Establish content from the CPU compositor's source buffer. Device mmap
    # reads are diagnostic only for KMS because NVIDIA and other drivers may
    # expose scanout through write-combined video memory.
    for row in range(max(0, int(_yres))):
        start = row * int(_line)
        pixels = _buffer[start:start + activebytes]

        if (
            len(pixels) == activebytes
            and pixels.count(black) != activebytes // pixelbytes
        ):
            content = True

            for column in range(0, activebytes, pixelbytes):

                if pixels[column:column + pixelbytes] != black:
                    nonblackoffset = start + column
                    break

            break

    result["nonblack"] = bool(content)

    try:
        if _backend == "kms-framebuffer":
            # Never read a write-combined GEM/video-memory mapping on the
            # lock-screen recovery path. Even a one-pixel read can block in a
            # wedged vendor driver. The CPU shadow, completed DRM commit,
            # connected connector route and current CRTC are the bounded
            # presentation proof.
            result["readback_skipped"] = (
                "write-combined-device-mapping"
            )
            if result["vblank_sequence"].get("advanced") is True:
                result["presentation_boundary"] = "drm-crtc-sequence"
            elif (
                str(_drmdriver or "").strip().lower()
                in ("virtio_gpu", "vmwgfx")
                and result["vblank_sequence"].get("unsupported") is True
                and str(result["dirty_status"]) == "complete"
                and int(result["present_sequence"]) >= 2
            ):
                # virtio_gpu and vmwgfx may deliberately omit DRM vblank
                # sequence support. A successful DIRTYFB on the exact active
                # resource is their host-transfer boundary, not a weaker
                # assumption that a connector alone proves presentation.
                result["presentation_boundary"] = (
                    "virtio-resource-flush"
                    if str(_drmdriver or "").strip().lower() == "virtio_gpu"
                    else "vmwgfx-dirtyfb-flush"
                )
            elif (
                str(_drmdriver or "").strip().lower() == "nvidia-drm"
                and result["vblank_sequence"].get("unsupported") is True
                and int(result["vblank_sequence"].get("errno") or 0)
                == int(getattr(errno, "EOPNOTSUPP", errno.ENOTSUP))
                and str(result["dirty_status"])
                == f"unsupported:{int(errno.ENOSYS)}"
                and str(result["flush_status"])
                == "not-required:drm-ioctl-boundary"
                and int(result["present_sequence"]) >= 2
                and int(result["modeset_sequence"]) > 0
            ):
                # NVIDIA's dumb-buffer scanout continuously consumes the
                # write-combined mapping, while its current DRM implementation
                # exposes neither CRTC sequence nor DIRTYFB completion.  Accept
                # this driver-specific boundary only after repeated writes to
                # the exact framebuffer which drmModeGetCrtc still reports as
                # active.  Connector routing, mode identity and link health are
                # checked below; other drivers cannot enter this fallback.
                result["presentation_boundary"] = (
                    "nvidia-continuous-scanout"
                )
            result["verified"] = bool(
                result["scanout"]
                and result["connector_connected"]
                and result["connector_routed"]
                and result["connector_link_status"] != "bad"
                and result["presentation_boundary"] is not None
                and result["write_committed"]
                and (result["nonblack"] or not bool(require_nonblack))
            )

        else:
            result["legacy_page_zero"] = bool(
                framebufferactivatepagezero()
            )
            # fb0 can either be a stale EFI aperture or the fbdev client of the
            # native DRM driver which currently owns HDMI. Correlate fb0's
            # sysfs device/driver before touching its mmap. Native DRM fbdev can
            # expose write-combined video memory, so reading it may block in the
            # same wedged vendor driver that forced recovery. Native ownership
            # is instead proved by exact device correlation, connected routing,
            # good link status when exposed, and an advancing CRTC sequence.
            # Firmware/system-memory fb is read back only on an explicitly
            # selected firmware-only boot.
            owners = _legacyframebufferowners()
            native = list(owners.get("native", []))
            matched = list(owners.get("matched", []))
            ownerconnected = bool(owners.get("owner_connected"))
            result["legacy_framebuffer_identity"] = owners.get("identity")
            result["legacy_framebuffer_name"] = owners.get("name")
            result["legacy_framebuffer_device"] = owners.get("device")
            result["legacy_framebuffer_driver"] = owners.get("driver")
            result["legacy_drm_owner"] = matched
            result["legacy_owner_connected"] = ownerconnected
            result["legacy_drm_probe_complete"] = bool(
                owners.get("drm_probe_complete")
            )
            result["legacy_firmware_framebuffer"] = bool(
                owners.get("firmware_framebuffer")
            )
            result["legacy_conflicting_drm"] = (
                [] if matched else native
            )
            result["legacy_drm_probe_error"] = owners.get("drm_probe_error")
            firmwareproof = bool(
                not native
                and result["legacy_drm_probe_complete"]
                and result["legacy_firmware_framebuffer"]
                and FIRMWAREFRAMEBUFFERBOOT
            )
            nativeproof = False

            if matched and ownerconnected:
                owner = matched[0]
                device = os.path.join(
                    DRMNODEPATH,
                    str(owner.get("card", "")),
                )
                nativescanout = _drmdevicevblankproof(device)
                result["legacy_native_scanout"] = nativescanout
                result["connector"] = nativescanout.get("connector")
                result["connector_connected"] = bool(
                    nativescanout.get("connector_connected")
                )
                result["connector_crtc"] = nativescanout.get("crtc")
                result["connector_routed"] = bool(
                    nativescanout.get("connector_routed")
                )
                result["connector_link_status"] = (
                    nativescanout.get("connector_link_status")
                )
                result["vblank_sequence"] = dict(
                    nativescanout.get("vblank") or {}
                )
                result["legacy_driver_family"] = (
                    _graphicsdriverfamily(owner.get("binding"))
                )
                result["readback_skipped"] = (
                    "native-drm-fbdev-write-combined-mapping"
                )
                if result["vblank_sequence"].get("advanced") is True:
                    result["presentation_boundary"] = (
                        "drm-crtc-sequence"
                    )
                elif (
                    result["legacy_driver_family"] == "virtio"
                    and result["vblank_sequence"].get("unsupported") is True
                ):
                    # FBIOPAN_DISPLAY is the native virtio fbdev resource
                    # flush. It is tied to this exact write sequence by
                    # legacy_pan_committed below.
                    result["presentation_boundary"] = (
                        "virtio-fbdev-pan"
                    )
                nativeproof = bool(
                    result["legacy_console_owned"]
                    and result["legacy_pan_committed"]
                    and result["connector_connected"]
                    and result["connector_routed"]
                    and result["connector_link_status"] != "bad"
                    and result["presentation_boundary"] is not None
                )

            elif firmwareproof:
                _map.seek(0)
                offset = 0
                chunksize = max(
                    pixelbytes,
                    (1024 * 1024 // pixelbytes) * pixelbytes,
                )
                result["readback"] = True

                while offset < size:
                    length = min(chunksize, size - offset)
                    visible = _map.read(length)
                    expected = bytes(_buffer[offset:offset + length])

                    if visible != expected:
                        result["readback"] = False
                        result["readback_mismatch_offset"] = int(offset)
                        break

                    offset += length

            else:
                result["readback_skipped"] = (
                    "framebuffer-owner-not-authoritative"
                )

            result["scanout"] = bool(
                result["legacy_page_zero"]
                and (
                    nativeproof
                    or (firmwareproof and result["readback"])
                )
            )
            result["mode_valid"] = bool(result["scanout"])
            result["verified"] = bool(
                result["scanout"]
                and (result["nonblack"] or not bool(require_nonblack))
            )

        return result

    except GPUDeviceLostError:
        raise
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result


def backendinfo():

    renderer = str(_glrenderer or "")
    software = any(value in renderer.lower() for value in ("softpipe", "llvmpipe", "swrast", "software rasterizer"))
    rendernode = drmrendernode()
    renderidentity = None

    try:

        if rendernode:

            status = os.stat(rendernode)
            renderidentity = {
                "major": int(os.major(status.st_rdev)),
                "minor": int(os.minor(status.st_rdev)),
            }

    except Exception:
        renderidentity = None

    return {
        "backend": str(_backend),
        "width": int(_xres),
        "height": int(_yres),
        "egl": f"{_eglmajor}.{_eglminor}" if _eglmajor else None,
        "egl_vendor": _eglvendor,
        "egl_swap_interval": _eglswapinterval,
        "egl_min_swap_interval": _eglminswapinterval,
        "egl_max_swap_interval": _eglmaxswapinterval,
        "egl_deferred_swap_state": _egldeferredswapstate,
        "egl_deferred_swap_error": _egldeferredswaperror,
        "drm_driver": _drmdriver,
        "drm_binding": _drmbinding,
        "drm_version": _drmdriverversion,
        "drm_date": _drmdriverdate,
        "drm_description": _drmdriverdescription,
        "provider": _openglprovider if _backend == "opengl" else None,
        "renderer": _glrenderer,
        "hardware_accelerated": bool(gpuavailable() and not software),
        "software_renderer": bool(software),
        "robust_context": bool(_glrobust),
        "version": _glversion,
        "upload_bytes": int(_gluploadbytes),
        "upload_full": bool(_gluploadfull),
        "kms_resizes": int(_kmsresizes),
        "kms_resize_failures": int(_kmsresizefailures),
        "event_driven_presentation": bool(_drmeventdriven),
        "presentation_pending": bool(kmspresentationpending()),
        "connector": int(_drmconnector) if _backend in ("opengl", "kms-framebuffer") and _drmconnector else None,
        "refresh_hz": round(kmsmoderefresh(_drmmode), 3) if _drmmode is not None else None,
        "display_adjustment": displayadjustment(),
        "gpu_api": gpuapi(),
        "telemetry": gpumetrics(),
        "device": DRMDEVICE if _backend in ("opengl", "kms-framebuffer") else FB_DEVICE,
        "render_node": rendernode,
        "render_identity": renderidentity,
    }


def _pngchunk(kind, data):

    kind = bytes(kind)
    data = bytes(data)
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def screenshotpng(path):

    """Save the currently composed display as a PNG file."""

    width = int(_xres)
    height = int(_yres)

    if width < 1 or height < 1:
        raise RuntimeError("screenshot display geometry is unavailable")

    bytecount = width * height * 4

    if bytecount < 1 or bytecount > FRAMEBUFFERMAXBYTES:
        raise RuntimeError(f"unsafe screenshot size {bytecount}")

    compressor = zlib.compressobj(level=6)
    compressed = bytearray()

    def appendrow(row):
        compressed.extend(compressor.compress(b"\x00" + row))

    if _backend == "opengl":

        if not gpuavailable():
            raise RuntimeError("screenshot GPU renderer is unavailable")

        if _gpuframeactive:
            raise RuntimeError("screenshot requested during an active GPU frame")

        pixels = (ctypes.c_ubyte * bytecount)()
        framebuffer = (
            int(_gpucompositorfbo)
            if _gpucompositorvalid and int(_gpucompositorfbo or 0)
            else 0
        )

        try:
            _gles.glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
            _gles.glPixelStorei(GL_PACK_ALIGNMENT, 4)
            _gles.glFinish()
            _gles.glReadPixels(
                0,
                0,
                width,
                height,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                pixels,
            )
            raw = bytes(pixels)
        finally:
            _gles.glBindFramebuffer(GL_FRAMEBUFFER, 0)

        stride = width * 4

        # OpenGL readback starts at the lower-left; PNG rows start at the top.
        for row in range(height - 1, -1, -1):
            offset = row * stride
            appendrow(raw[offset:offset + stride])

    else:

        if _buffer is None or _line < width * _bpp_bytes:
            raise RuntimeError("screenshot framebuffer is unavailable")

        if len(_buffer) < int(_line) * height:
            raise RuntimeError("screenshot framebuffer is incomplete")

        commonbgra = bool(
            int(_bpp_bytes) == 4
            and int(_roff) == 16 and int(_rlen) == 8
            and int(_goff) == 8 and int(_glen) == 8
            and int(_boff) == 0 and int(_blen) == 8
        )

        for row in range(height):
            offset = row * int(_line)

            if commonbgra:
                source = bytes(_buffer[offset:offset + width * 4])
                rgba = bytearray(width * 4)
                rgba[0::4] = source[2::4]
                rgba[1::4] = source[1::4]
                rgba[2::4] = source[0::4]
                rgba[3::4] = b"\xFF" * width
                appendrow(bytes(rgba))
                continue

            rgba = bytearray(width * 4)

            for column in range(width):
                sourceoffset = offset + column * int(_bpp_bytes)
                red, green, blue = unpackrgb(
                    _buffer[sourceoffset:sourceoffset + int(_bpp_bytes)]
                )
                targetoffset = column * 4
                rgba[targetoffset:targetoffset + 4] = bytes(
                    (red, green, blue, 255)
                )

            appendrow(bytes(rgba))

    compressed.extend(compressor.flush())
    destination = os.path.abspath(str(path))
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    temporary = f"{destination}.tmp-{os.getpid()}"

    try:
        with open(temporary, "wb") as output:
            output.write(b"\x89PNG\r\n\x1a\n")
            output.write(_pngchunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
            output.write(_pngchunk(b"IDAT", compressed))
            output.write(_pngchunk(b"IEND", b""))
            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary, destination)
    finally:

        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass

    return {
        "path": destination,
        "width": width,
        "height": height,
        "bytes": int(os.path.getsize(destination)),
    }



# misc functions
def log(msg, flush=False):

    line = formatlog('graphics', msg)
    critical = bool(
        flush
        or any(
            token in str(msg).casefold()
            for token in (
                "device loss",
                "context lost",
                "gpu reset",
                "failed",
                "failure",
                "fatal",
            )
        )
    )

    # WindowServer owns the central graphics log.  Graphical clients import
    # this module too, but deliberately run without authority to modify the
    # root-owned log tier.  Their stdout/stderr is already drained into a
    # separate root-owned process log by GODDESS, so use that channel and never
    # turn a diagnostic write into an application or presentation failure.
    privileged = getattr(os, 'geteuid', lambda: 0)() == 0

    if privileged:

        try:
            os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)

            with open(LOGFILE, "a", buffering=1) as stream:
                stream.write(line + "\n")
                stream.flush()

                if critical:

                    try:
                        os.fsync(stream.fileno())
                    except OSError:
                        pass

            return True

        except OSError as error:
            fallback = (
                f"{line} [central graphics log unavailable: "
                f"{type(error).__name__}: {error}]"
            )

    else:
        fallback = line

    try:
        print(fallback, file=sys.stderr, flush=True)
    except BaseException:
        pass

    return False

def normalisecolor(c):


    r, g, b = c

    return (int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF)


def packrgb(rgb):

    try:

        r, g, b = rgb

        rp = ((r * ((1 << _rlen) - 1) + 127) // 255) if _rlen else 0

        gp = ((g * ((1 << _glen) - 1) + 127) // 255) if _glen else 0

        bp = ((b * ((1 << _blen) - 1) + 127) // 255) if _blen else 0

        val = (rp << _roff) | (gp << _goff) | (bp << _boff) | ((((1 << _alen) - 1) if _alen else 0) << _aoff)

        return _packint(val)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] packrgb error {e}", flush=True)
        return b'\x00' * max(1, _bpp_bytes)


def unpackrgb(packed):

    try:

        val = _unpack(packed)[0]

    except Exception:

        val = 0

    rm = (1 << _rlen) - 1 if _rlen else 0

    gm = (1 << _glen) - 1 if _glen else 0

    bm = (1 << _blen) - 1 if _blen else 0

    r = (((val >> _roff) & rm) * 255 + (rm // 2)) // rm if rm else 0

    g = (((val >> _goff) & gm) * 255 + (gm // 2)) // gm if gm else 0

    b = (((val >> _boff) & bm) * 255 + (bm // 2)) // bm if bm else 0

    return (r, g, b)


def loadfont8x8(path):

    try:

        text = open(path, 'r').read()

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] loadfont error {e}", flush=True)
        return

    try:

        blocks = re.findall(r"\{([^}]+)\}", text)

        for code, blk in enumerate(blocks):

            bytes8 = re.findall(r"0x[0-9A-Fa-f]+", blk)

            FONT8x8[code] = [int(b, 16) for b in bytes8]

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] loadfont parse error {e}", flush=True)


def cursorcatalogue():

    global PILIMAGE

    if PILIMAGE is not None:
        return PILIMAGE

    if IMAGECATALOGUE not in sys.path:
        sys.path.insert(0, IMAGECATALOGUE)

    from PIL import Image as loadedimage

    PILIMAGE = loadedimage
    return PILIMAGE


def registercursor(name, imagepath, width, height):

    global CURSORW, CURSORH

    try:
        w = int(width)
        h = int(height)

        if w <= 0 or h <= 0:
            raise ValueError("cursor dimensions must be positive")

        imagemodule = cursorcatalogue()

        with imagemodule.open(imagepath) as opened:

            opened.load()

            if str(opened.format or "").upper() != "PNG":
                raise ValueError("cursor source is not a PNG")

            image = opened.convert("RGBA")

            if image.size != (w, h):
                image = image.resize(
                    (w, h),
                    imagemodule.Resampling.LANCZOS,
                    reducing_gap=3.0,
                )

            data = image.tobytes("raw", "BGRA")

        if len(data) != w * h * 4:
            raise ValueError("cursor decoder returned an invalid pixel buffer")

    except Exception as error:

        log(f"> graphics cursor load failed name={name} path={imagepath} error={error}")
        CURSORS[name] = {"w": 0, "h": 0, "data": None, "stride": 0}

        return

    stride = w * 4

    CURSORS[name] = {"w": w, "h": h, "data": data, "stride": stride}

    if name == "arrow":

        CURSORW = w

        CURSORH = h


def pickcursortier(screenh):

    best = CURSORTIERS[0][1]
    bestd = None

    for h, tier in CURSORTIERS:

        d = abs(int(screenh) - int(h))

        if bestd is None or d < bestd:
            bestd = d
            best = tier

    return best


def configuredcursorsize(path=None):

    try:
        with open(str(path or MOUSESETTINGS), "r", encoding="utf-8") as stream:
            settings = json.load(stream)

        value = settings.get("cursor_size")

        if value is None:
            return None

        return max(CURSORSIZEMIN, min(CURSORSIZEMAX, int(round(float(value)))))

    except Exception:
        return None


def cursorsizesforheight(height):

    target = max(CURSORSIZEMIN, min(CURSORSIZEMAX, int(round(float(height)))))
    points = sorted(
        (int(CURSORBUCKETS[tier]["arrow"][1]), CURSORBUCKETS[tier])
        for _, tier in CURSORTIERS
    )

    lower, upper = points[0], points[1]

    for left, right in zip(points, points[1:]):
        lower, upper = left, right

        if left[0] <= target <= right[0]:
            break
    else:
        if target < points[0][0]:
            lower, upper = points[0], points[1]
        else:
            lower, upper = points[-2], points[-1]

    span = float(max(1, upper[0] - lower[0]))
    amount = (float(target) - float(lower[0])) / span
    result = {}

    for name in lower[1]:
        width = lower[1][name][0] + amount * (
            upper[1][name][0] - lower[1][name][0])
        cursorheight = lower[1][name][1] + amount * (
            upper[1][name][1] - lower[1][name][1])
        result[name] = (
            max(1, int(round(width))),
            max(1, int(round(cursorheight))),
        )

    # The setting is defined by the arrow height, so preserve it exactly even
    # when interpolation and rounding are involved.
    result["arrow"] = (result["arrow"][0], target)
    return result


def cursorpaths():

    base = CURSORBASE

    return {
        "arrow": os.path.join(base, "mousecursor.png"),
        "link": os.path.join(base, "mousecursorlink.png"),
        "text": os.path.join(base, "mousecursortext.png"),
        "busy": os.path.join(base, "mousecurosrbusy.png"),
        "resize_h": os.path.join(base, "mousecursorhorizontal.png"),
        "resize_v": os.path.join(base, "mousecursorvertical.png"),
        "resize_diag1": os.path.join(base, "mousecursordiagonal.png"),
        "resize_diag2": os.path.join(base, "mousecursordiagonal2.png"),
    }


def loadcursor(mousepath=None):

    global CURSORTIER, CURSORS, CURSORW, CURSORH

    tier = pickcursortier(_yres if _yres else 1080)
    customsize = configuredcursorsize(mousepath)

    CURSORTIER = tier if customsize is None else "custom-" + str(customsize)

    CURSORS.clear()
    CURSORW = 0
    CURSORH = 0

    paths = cursorpaths()
    sizes = (
        CURSORBUCKETS[tier]
        if customsize is None else
        cursorsizesforheight(customsize)
    )

    for name, imagepath in paths.items():

        width, height = sizes[name]

        if name == "text":
            width = max(1, int(round(width * TEXTCURSORSCALE)))
            height = max(1, int(round(height * TEXTCURSORSCALE)))

        registercursor(name, imagepath, width, height)


def framebufferactivatepagezero():

    global _framebufferpagezero, _framebufferpansequence

    _framebufferpagezero = False

    if _fd is None:
        return False

    variable = bytearray(ctypes.sizeof(fb_var_screeninfo))

    try:
        fcntl.ioctl(_fd, FBIOGET_VSCREENINFO, variable, True)
        xoffset = int(struct.unpack_from("<I", variable, 16)[0])
        yoffset = int(struct.unpack_from("<I", variable, 20)[0])

        # A native DRM fbdev client needs an explicit pan commit after the
        # completed lock-screen write even when it already reports page zero.
        # Observing zero offsets alone can describe stale fbcon state while a
        # different KMS framebuffer remains on the CRTC.
        if _framebuffernativedrm or xoffset != 0 or yoffset != 0:
            struct.pack_into("<I", variable, 16, 0)
            struct.pack_into("<I", variable, 20, 0)
            struct.pack_into("<I", variable, 84, FB_ACTIVATE_NOW)
            fcntl.ioctl(_fd, FBIOPAN_DISPLAY, variable, True)
            verify = bytearray(ctypes.sizeof(fb_var_screeninfo))
            fcntl.ioctl(_fd, FBIOGET_VSCREENINFO, verify, True)
            xoffset = int(struct.unpack_from("<I", verify, 16)[0])
            yoffset = int(struct.unpack_from("<I", verify, 20)[0])

            if xoffset == 0 and yoffset == 0:
                log(
                    "> graphics framebuffer scanout committed to virtual page 0"
                )

        _framebufferpagezero = xoffset == 0 and yoffset == 0

        if _framebufferpagezero:
            _framebufferpansequence = int(_framebufferwritesequence)

        return bool(_framebufferpagezero)

    except Exception as error:
        log(
            f"> graphics framebuffer page-zero activation failed {error}"
        )
        return False


def cursorbox(x, y, name="arrow"):

    try:

        cx = int(x)

        cy = int(y)

        info = CURSORS.get(name)

        if info and int(info.get("w", 0)) > 0 and int(info.get("h", 0)) > 0:

            return [cx, cy, int(info["w"]), int(info["h"])]

        if CURSORW > 0 and CURSORH > 0:

            return [cx, cy, CURSORW, CURSORH]

        return [cx, cy, 1, 1]

    except Exception:

        return [int(x), int(y), 1, 1]


def refreshfb(waitpulse=None, force_physical=False):

    global _map, _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes, _line, _size
    global _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen, _has_double
    global _unpack, _packint

    if _backend == "opengl":

        # drmModeGetConnector may synchronously probe a physical output.  On
        # proprietary NVIDIA this has repeatedly blocked the single
        # compositor/input thread for roughly 100 ms even though the mode did
        # not change.  Dynamic virtual displays still need polling; physical
        # displays receive one forced stability check before WindowServer
        # advertises its protocol sockets.
        dynamicdisplay = bool(
            str(_drmdriver or "").strip().lower()
            in ("virtio_gpu", "vmwgfx")
            or virtualboxcontrolsresolution()
        )

        if not force_physical and not dynamicdisplay:
            return False

        return kmsresize(waitpulse=waitpulse)

    if _backend == "kms-framebuffer":
        return kmsframebufferrefresh()

    if _IS_FILE_BUFFER:
        return False

    if _fd is None:
        return False

    # read current variable screeninfo
    varbuf = bytearray(160)

    try:

        fcntl.ioctl(_fd, FBIOGET_VSCREENINFO, varbuf, True)

        nxres = struct.unpack_from('<I', varbuf, 0)[0]

        nyres = struct.unpack_from('<I', varbuf, 4)[0]

        nyvirt = struct.unpack_from('<I', varbuf, 12)[0]

        nbpp  = struct.unpack_from('<I', varbuf, 24)[0]

        nroff = struct.unpack_from('<I', varbuf, 32)[0]

        nrlen = struct.unpack_from('<I', varbuf, 36)[0]

        ngoff = struct.unpack_from('<I', varbuf, 44)[0]

        nglen = struct.unpack_from('<I', varbuf, 48)[0]

        nboff = struct.unpack_from('<I', varbuf, 56)[0]

        nblen = struct.unpack_from('<I', varbuf, 60)[0]

        naoff = struct.unpack_from('<I', varbuf, 68)[0]

        nalen = struct.unpack_from('<I', varbuf, 72)[0]

    except Exception:

        return False

    # no change
    if int(nxres) == int(_xres) and int(nyres) == int(_yres) and int(nbpp) == int(_bpp) and int(nyvirt) == int(_yvirt):
        return False

    # read fixinfo for new line length
    fixbuf = bytearray(FB_FIX_SCREENINFO_SIZE)

    try:

        fcntl.ioctl(_fd, FBIOGET_FSCREENINFO, fixbuf, True)

        nline = struct.unpack_from('<I', fixbuf, 48)[0]

    except Exception:

        return False

    # remap using new geometry
    try:

        if _map:
            _map.close()

    except Exception:
        pass

    _xres = int(nxres)

    _yres = int(nyres)

    _yvirt = int(nyvirt)

    _bpp = int(nbpp)

    _roff = int(nroff)

    _rlen = int(nrlen)

    _goff = int(ngoff)

    _glen = int(nglen)

    _boff = int(nboff)

    _blen = int(nblen)

    _aoff = int(naoff)

    _alen = int(nalen)

    _has_double = (_yvirt >= (_yres * 2))

    _bpp_bytes = _bpp // 8

    _line = int(nline)

    _size = _line * _yres

    try:

        _map = mmap.mmap(_fd, _size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)

    except Exception:

        _map = None

        return False

    try:

        _buffer = bytearray(_size)

    except Exception:

        _buffer = None

        return False

    try:

        fmt = {2: '<H', 4: '<I'}.get(_bpp_bytes)

        if not fmt:
            return True

        packer = struct.Struct(fmt)

        globals()['_unpack'] = packer.unpack

        globals()['_packint'] = packer.pack

    except Exception:
        pass

    resetdirty()

    return True


def getscreensize():

    try:

        return (int(_xres), int(_yres))

    except Exception:

        return (0, 0)


# init functions
def init(node=FB_DEVICE, backend="framebuffer"):

    global _fd, _map, _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes, _pack, _packint, _unpack, _line, _size
    global _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen, _has_double
    global _backend, _IS_FILE_BUFFER, _framebuffernativedrm
    global _framebufferwritesequence, _framebufferpansequence

    loaddisplaysettings()

    requested = str(backend).strip().lower()

    if requested not in ("auto", "opengl", "framebuffer", "kms-framebuffer"):
        requested = "auto"

    drmstate = "missing"
    framebufferstate = "missing"

    candidates = drmcandidates()

    if candidates:
        readable = [candidate for candidate in candidates if os.access(candidate, os.R_OK | os.W_OK)]
        drmstate = "read-write" if readable else "permission-denied"

    if os.path.exists(node):
        framebufferstate = "read-write" if os.access(node, os.R_OK | os.W_OK) else "permission-denied"

    log(f"> graphics init {requested} DRM {drmstate} framebuffer {framebufferstate}")

    if requested == "kms-framebuffer":

        if kmsframebufferinit():
            return

        raise RuntimeError("requested software KMS framebuffer is unavailable")

    if requested in ("auto", "opengl"):

        if kmsinit():
            return

        if requested == "opengl":
            raise RuntimeError("requested OpenGL/KMS backend is unavailable")

        log("> graphics falling back to framebuffer")

    _backend = "none"
    _IS_FILE_BUFFER = False
    _framebuffernativedrm = False
    _framebufferwritesequence = 0
    _framebufferpansequence = 0

    try:

        _fd = os.open(node, os.O_RDWR)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] open {node} -> fd={_fd}", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer open failed {e}")
        raise RuntimeError(f"could not open framebuffer {node}: {e}") from e


    varbuf = bytearray(160)

    try:

        fcntl.ioctl(_fd, FBIOGET_VSCREENINFO, varbuf, True)

        _xres = struct.unpack_from('<I', varbuf, 0)[0]

        _yres = struct.unpack_from('<I', varbuf, 4)[0]

        _yvirt = struct.unpack_from('<I', varbuf, 12)[0]

        _bpp  = struct.unpack_from('<I', varbuf, 24)[0]

        _roff = struct.unpack_from('<I', varbuf, 32)[0]
        _rlen = struct.unpack_from('<I', varbuf, 36)[0]
        _goff = struct.unpack_from('<I', varbuf, 44)[0]
        _glen = struct.unpack_from('<I', varbuf, 48)[0]
        _boff = struct.unpack_from('<I', varbuf, 56)[0]
        _blen = struct.unpack_from('<I', varbuf, 60)[0]
        _aoff = struct.unpack_from('<I', varbuf, 68)[0]
        _alen = struct.unpack_from('<I', varbuf, 72)[0]

        _has_double = (_yvirt >= (_yres * 2))

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] varinfo {_xres}x{_yres} virtY={_yvirt} @ {_bpp}bpp double={_has_double}", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer variable-info query failed {e}")
        raise RuntimeError(f"framebuffer variable-info query failed: {e}") from e

    # fb_fix_screeninfo is 80 bytes on the x86-64 ABI because both physical
    # addresses are unsigned long.  A 64-byte buffer lets the legacy ioctl
    # overwrite Python-owned memory and can terminate Window Server without a
    # traceback.
    fixbuf = bytearray(FB_FIX_SCREENINFO_SIZE)

    try:

        fcntl.ioctl(_fd, FBIOGET_FSCREENINFO, fixbuf, True)

        _line = struct.unpack_from('<I', fixbuf, 48)[0]

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fixinfo line_length={_line}", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer fixed-info query failed {e}")
        raise RuntimeError(f"framebuffer fixed-info query failed: {e}") from e

    # Resolve fb0 ownership before mmap. A stale EFI aperture must never be
    # mapped as a same-boot fallback after a native DRM driver has bound, and a
    # native fbdev client must not be touched unless PID 1 first reclaimed the
    # inherited VT through a successful, bounded KD_TEXT transition.
    try:
        framebufferowners = _legacyframebufferowners()
        matchedowners = list(framebufferowners.get("matched", []))
        nativeowners = list(framebufferowners.get("native", []))

        if not framebufferowners.get("drm_probe_complete"):
            raise RuntimeError(
                "DRM ownership enumeration did not complete"
            )

        if len(matchedowners) > 1:
            raise RuntimeError(
                "framebuffer ownership is ambiguous across native DRM cards"
            )

        _framebuffernativedrm = len(matchedowners) == 1

        if nativeowners and not _framebuffernativedrm:
            raise RuntimeError(
                "framebuffer does not belong to the active native DRM device"
            )

        if (
            not nativeowners
            and not framebufferowners.get("firmware_framebuffer")
        ):
            raise RuntimeError(
                "framebuffer is neither a known firmware aperture nor an "
                "exact native DRM fbdev owner"
            )

        if (
            _framebuffernativedrm
            and not FRAMEBUFFERCONSOLEOWNED
            and not EARLYFRAMEBUFFERGRAPHICSOWNED
        ):
            raise RuntimeError(
                "native DRM fbdev launch lacks confirmed KD_TEXT ownership"
            )

        log(
            f"> graphics framebuffer memory classification "
            f"native_drm={_framebuffernativedrm} "
            f"console_owned={FRAMEBUFFERCONSOLEOWNED} "
            f"early_graphics_owned={EARLYFRAMEBUFFERGRAPHICSOWNED} "
            f"identity={framebufferowners.get('identity') or 'unknown'} "
            f"driver={framebufferowners.get('driver') or 'unknown'}"
        )
    except Exception as error:
        _framebuffernativedrm = False
        log(f"> graphics framebuffer ownership rejected {error}")

        try:
            os.close(_fd)
        except OSError:
            pass

        _fd = None
        raise RuntimeError(
            f"framebuffer ownership could not be made authoritative: {error}"
        ) from error

    try:
        fcntl.ioctl(_fd, FBIOBLANK, FB_BLANK_UNBLANK)
    except OSError as error:
        # Several firmware framebuffers reject FBIOBLANK while still allowing
        # FBIOGET_* and mmap. Unblank only after ownership is authoritative.
        log(f"> graphics framebuffer unblank not supported {error}")

    try:

        _size = _line * _yres

        if _xres < 1 or _yres < 1 or _line < 1 or _bpp not in (16, 32):
            raise RuntimeError(
                f"invalid framebuffer geometry {_xres}x{_yres} "
                f"line={_line} bpp={_bpp}"
            )

        if _size < 1 or _size > FRAMEBUFFERMAXBYTES:
            raise RuntimeError(f"unsafe framebuffer mapping size {_size}")

        log(
            f"> graphics framebuffer mode {_xres}x{_yres} "
            f"line={_line} bpp={_bpp} bytes={_size}"
        )

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] map size={_size}", flush=True)

        _map = mmap.mmap(_fd, _size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] mmap ok", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer mapping failed {e}")
        raise RuntimeError(f"framebuffer mapping failed: {e}") from e

    try:

        _buffer = bytearray(_size)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] offscreen buffer allocated size={_size}", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer allocation failed {e}")
        raise RuntimeError(f"framebuffer allocation failed: {e}") from e

    try:

        _bpp_bytes = _bpp // 8

        fmt = {2: '<H', 4: '<I'}.get(_bpp_bytes)

        if not fmt:
            raise RuntimeError(f"unsupported framebuffer bytes per pixel {_bpp_bytes}")

        packer = struct.Struct(fmt)

        _unpack = packer.unpack

        _packint = packer.pack

        def _pack_fn(c):

            return packrgb(normalisecolor(c))

        globals()['_pack'] = _pack_fn

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] channel layout r(off={_roff},len={_rlen}) g(off={_goff},len={_glen}) b(off={_boff},len={_blen}) a(off={_aoff},len={_alen})", flush=True)

    except Exception as e:

        log(f"> graphics framebuffer pixel-format setup failed {e}")
        raise RuntimeError(f"framebuffer pixel-format setup failed: {e}") from e

    try:

        resetdirty()

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] dirty rects initialized", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] resetdirty error {e}", flush=True)

    loadcursor()

    _backend = "framebuffer"


def initbuffer(path, w, h):

    global _fd, _map, _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes, _pack, _packint, _unpack, _line, _size
    global _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen
    global _IS_FILE_BUFFER, _FILE_FD, _FILE_MAP
    global _backend

    if _backend == "opengl":
        kmsclose()

    if _backend == "kms-framebuffer":
        kmsframebufferclose()


    # close any prior mapping
    try:
        if _map:
            _map.close()
    except Exception:
        pass
    try:
        if _fd:
            os.close(_fd)
    except Exception:
        pass
    try:
        if _FILE_MAP:
            _FILE_MAP.close()
    except Exception:
        pass
    try:
        if _FILE_FD:
            os.close(_FILE_FD)
    except Exception:
        pass

    _fd = None
    _map = None
    _FILE_MAP = None
    _FILE_FD = None
    _IS_FILE_BUFFER = False
    _buffer = None
    _size = 0
    _backend = "none"
    descriptor = None
    mapping = None
    metadata = {}
    stage = "validate"

    try:

        path = os.fspath(path)
        width = int(w)
        height = int(h)

        if not path or width < 1 or height < 1:
            raise ValueError("window buffer path and dimensions must be positive")

        expectedsize = width * height * 4

        if expectedsize > FRAMEBUFFERMAXBYTES:
            raise ValueError(
                f"window buffer requires {expectedsize} bytes, above the "
                f"{FRAMEBUFFERMAXBYTES}-byte limit"
            )

        # Open the exact unguessable path supplied by WindowServer without
        # following a replacement link.  Keep each stage distinct so a future
        # DAC, path-lifetime, or mmap regression reports the original syscall.
        stage = "open"
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)

        stage = "fstat"
        status = os.fstat(descriptor)
        metadata = {
            "owner": int(status.st_uid),
            "group": int(status.st_gid),
            "mode": f"{stat.S_IMODE(status.st_mode):04o}",
            "size": int(status.st_size),
            "expected_size": int(expectedsize),
        }

        if not stat.S_ISREG(status.st_mode):
            raise PermissionError(errno.EACCES, "window buffer is not a regular file")

        # WindowServer retains the largest allocation reached by a window so
        # clients that are still replacing an older mapping cannot fault when
        # the logical window shrinks.  Only the logical width/height prefix is
        # mapped here, so a larger retained capacity is valid; a short file is
        # never valid.
        if int(status.st_size) < expectedsize:
            raise ValueError(
                f"window buffer size is {status.st_size}, expected at least {expectedsize}"
            )

        stage = "mmap"
        mapping = mmap.mmap(
            descriptor,
            expectedsize,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=0,
        )

        stage = "backbuffer"
        backbuffer = bytearray(expectedsize)

        # Commit process-global state only after every fallible resource and
        # allocation has succeeded.  A failed replacement cannot leave a stale
        # buffer marked ready.
        _FILE_FD = descriptor
        _FILE_MAP = mapping
        _IS_FILE_BUFFER = True
        _buffer = backbuffer
        _size = expectedsize
        descriptor = None
        mapping = None

        # geometry and format: BGRA32 with 8 bits per channel
        _xres = width
        _yres = height
        _yvirt = _yres
        _bpp = 32
        _bpp_bytes = 4
        _line = _xres * _bpp_bytes

        # BGRA bit layout in little-endian 32-bit word
        _boff = 0;  _blen = 8
        _goff = 8;  _glen = 8
        _roff = 16; _rlen = 8
        _aoff = 24; _alen = 8

        # packers for 32-bit little endian
        packer = struct.Struct('<I')
        globals()['_unpack'] = packer.unpack
        globals()['_packint'] = packer.pack

        def _pack_fn(c):

            # normalize to (r,g,b)
            try:
                r, g, b = c
            except Exception:
                r = (int(c) >> 16) & 0xFF
                g = (int(c) >> 8)  & 0xFF
                b = int(c) & 0xFF

            # assemble BGRA with A=0xFF
            return bytes((b & 0xFF, g & 0xFF, r & 0xFF, 0xFF))

        globals()['_pack'] = _pack_fn

        resetdirty()
        _backend = "filebuffer"
        return True

    except Exception as error:

        if mapping is not None:

            try:
                mapping.close()
            except Exception:
                pass

        if descriptor is not None:

            try:
                os.close(descriptor)
            except Exception:
                pass

        _FILE_FD = None
        _FILE_MAP = None
        _IS_FILE_BUFFER = False
        _buffer = None
        _size = 0
        _backend = "none"
        raise WindowBufferAccessError(stage, path, error, metadata) from error


def blankconsole():

    try:

        fcntl.ioctl(_fd, FBIOBLANK, FB_BLANK_POWERDOWN)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] console blanked via FBIOBLANK", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] FBIOBLANK error {e}", flush=True)


def unblankconsole():

    try:

        fcntl.ioctl(_fd, FBIOBLANK, FB_BLANK_UNBLANK)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] console unblanked via FBIOBLANK", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] FBIOBLANK unblank error {e}", flush=True)


def close():

    global _fd, _map, _backend, _framebuffernativedrm

    if _backend == "opengl":
        kmsclose()

    if _backend == "kms-framebuffer":
        kmsframebufferclose()

    try:

        if _map:

            _map.close()

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] unmapped", flush=True)

            _map = None

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] unmap error {e}", flush=True)

    try:

        if _fd:

            os.close(_fd)

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] closed fd={_fd}", flush=True)

            _fd = None

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] close fd error {e}", flush=True)

    _backend = "none"
    _framebuffernativedrm = False


# drawing functions
def setpixel(x, y, color):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] setpixel no buffer", flush=True)
        return

    if x < 0 or y < 0 or x >= _xres or y >= _yres:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] setpixel OOB x={x} y={y} (res={_xres}x{_yres})", flush=True)
        return

    if _pack is None:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] setpixel _pack is None", flush=True)
        return

    try:

        offset = y * _line + x * _bpp_bytes

        _buffer[offset:offset + _bpp_bytes] = _pack(color)

        markdirty(x, y, x + 1, y + 1)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] setpixel error {e}", flush=True)


def drawline(x0, y0, x1, y1, color):

    try:

        if isinstance(color, int):
            sr = (color >> 16) & 0xFF
            sg = (color >> 8) & 0xFF
            sb = color & 0xFF
        else:
            sr, sg, sb = color

    except Exception:

        sr = sg = sb = 0

    if _pack is None or _unpack is None:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawline pack/unpack missing", flush=True)
        return

    if x0 == x1 and y0 == y1:

        if 0 <= x0 < _xres and 0 <= y0 < _yres:

            setpixel(x0, y0, (sr, sg, sb))

        else:

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawline point OOB x={x0} y={y0}", flush=True)

        return

    try:

        steep = abs(y1 - y0) > abs(x1 - x0)

        if steep:
            x0, y0, x1, y1 = y0, x0, y1, x1

        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0

        dx = x1 - x0
        dy = y1 - y0
        gradient = dy / dx if dx != 0 else 0.0

        xend = int(x0 + 0.5)
        yend = y0 + gradient * (xend - x0)
        xgap = 1.0 - ((x0 + 0.5) - int(x0 + 0.5))
        xpxl1 = xend
        ypxl1 = int(yend)

        coords = []

        if steep:
            coords.append((ypxl1,     xpxl1, (1.0 - (yend - int(yend))) * xgap))
            coords.append((ypxl1 + 1, xpxl1, (yend - int(yend)) * xgap))
        else:
            coords.append((xpxl1, ypxl1,     (1.0 - (yend - int(yend))) * xgap))
            coords.append((xpxl1, ypxl1 + 1, (yend - int(yend)) * xgap))

        intery = yend + gradient

        xend2 = int(x1 + 0.5)
        yend2 = y1 + gradient * (xend2 - x1)
        xgap2 = (x1 + 0.5) - int(x1 + 0.5)
        xpxl2 = xend2
        ypxl2 = int(yend2)

        if steep:

            for x in range(xpxl1 + 1, xpxl2):

                fy = intery - int(intery)

                coords.append((int(intery),     x, 1.0 - fy))
                coords.append((int(intery) + 1, x, fy))

                intery += gradient

            coords.append((ypxl2,     xpxl2, (1.0 - (yend2 - int(yend2))) * xgap2))
            coords.append((ypxl2 + 1, xpxl2, (yend2 - int(yend2)) * xgap2))

        else:

            for x in range(xpxl1 + 1, xpxl2):

                fy = intery - int(intery)

                coords.append((x, int(intery),     1.0 - fy))
                coords.append((x, int(intery) + 1, fy))

                intery += gradient

            coords.append((xpxl2, ypxl2,     (1.0 - (yend2 - int(yend2))) * xgap2))
            coords.append((xpxl2, ypxl2 + 1, (yend2 - int(yend2)) * xgap2))

        blended = 0
        oob = 0

        for (px, py, a) in coords:

            if a <= 0.0:
                continue

            if px < 0 or py < 0 or px >= _xres or py >= _yres:
                oob += 1
                continue

            try:
                off = py * _line + px * _bpp_bytes
                bg_r, bg_g, bg_b = unpackrgb(_buffer[off:off + _bpp_bytes])
            except Exception:
                bg_r = bg_g = bg_b = 0

            inv = 1.0 - a

            rr = int(sr * a + bg_r * inv + 0.5)
            rg = int(sg * a + bg_g * inv + 0.5)
            rb = int(sb * a + bg_b * inv + 0.5)

            setpixel(px, py, (rr, rg, rb))
            blended += 1

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawline done blended={blended} oob={oob}", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawline error {e}", flush=True)


def drawrect(x, y, w, h, color):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect no buffer", flush=True)
        return

    x0 = x
    y0 = y
    x1 = x + w - 1
    y1 = y + h - 1

    if w <= 0 or h <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect zero/neg size w={w} h={h}", flush=True)
        return

    if x1 < 0 or y1 < 0 or x0 >= _xres or y0 >= _yres:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect fully OOB ({x0},{y0})-({x1},{y1}) res={_xres}x{_yres}", flush=True)
        return

    ox0, oy0, ox1, oy1 = x0, y0, x1, y1

    if x0 < 0: x0 = 0
    if y0 < 0: y0 = 0
    if x1 >= _xres: x1 = _xres - 1
    if y1 >= _yres: y1 = _yres - 1

    if (x0, y0, x1, y1) != (ox0, oy0, ox1, oy1):
        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect clipped to ({x0},{y0})-({x1},{y1})", flush=True)

    if x0 > x1 or y0 > y1:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect empty after clip", flush=True)
        return

    try:


        if isinstance(color, int):

            rgb = ((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)

        else:

            rgb = color

        packed = _pack(normalisecolor(rgb))

        top_w = (x1 - x0 + 1)

        off = y0 * _line + x0 * _bpp_bytes
        _buffer[off:off + top_w * _bpp_bytes] = packed * top_w

        if y1 != y0:

            off = y1 * _line + x0 * _bpp_bytes
            _buffer[off:off + top_w * _bpp_bytes] = packed * top_w

        side_count = 0
        if x1 != x0:

            for yy in range(y0 + 1, y1):

                setpixel(x0, yy, rgb)
                setpixel(x1, yy, rgb)
                side_count += 2

        markdirty(x0, y0, x1 + 1, y1 + 1)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect edges top/bot={top_w*2 if y1!=y0 else top_w} sides={side_count}", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawrect error {e}", flush=True)


def fillrect(x, y, w, h, color):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect no buffer", flush=True)
        return

    ox, oy, ow, oh = x, y, w, h

    if x < 0:
        w += x; x = 0
    if y < 0:
        h += y; y = 0
    if x + w > _xres:
        w = _xres - x
    if y + h > _yres:
        h = _yres - y

    if (x, y, w, h) != (ox, oy, ow, oh):
        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect clipped from ({ox},{oy},{ow},{oh}) to ({x},{y},{w},{h})", flush=True)

    if w <= 0 or h <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect zero/neg after clip w={w} h={h}", flush=True)
        return

    if _pack is None or _bpp_bytes <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect bad state", flush=True)
        return

    try:

        rowdat = _pack(normalisecolor(color)) * w

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect pack error {e}", flush=True)
        return

    span = w * _bpp_bytes

    try:

        for row in range(y, y + h):

            off = row * _line + x * _bpp_bytes

            _buffer[off:off + span] = rowdat

        markdirty(x, y, x + w, y + h)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect done rows={h} w={w}", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillrect error {e}", flush=True)


def drawcircle(cx, cy, radius, color):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle no buffer", flush=True)
        return

    try:

        if isinstance(color, int):
            sr = (color >> 16) & 0xFF
            sg = (color >> 8) & 0xFF
            sb = color & 0xFF
        else:
            sr, sg, sb = color

    except Exception:

        sr = sg = sb = 0

    if _unpack is None or _bpp_bytes <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle _unpack/bpp invalid", flush=True)
        return

    if radius <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle non-positive radius r={radius}", flush=True)
        return

    try:

        stroke = 2.0
        half   = stroke * 0.5
        r = float(radius)
        pad = int(half) + 1
        x0 = cx - radius - pad
        y0 = cy - radius - pad
        x1 = cx + radius + pad
        y1 = cy + radius + pad
        if x0 < 0: x0 = 0
        if y0 < 0: y0 = 0
        if x1 >= _xres: x1 = _xres - 1
        if y1 >= _yres: y1 = _yres - 1
        if x0 > x1 or y0 > y1:
            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle bbox empty", flush=True)
            return

        blended = 0

        for y in range(y0, y1 + 1):

            cyc = (y + 0.5) - cy
            yy2 = cyc * cyc
            rowoff = y * _line

            for x in range(x0, x1 + 1):

                cxc = (x + 0.5) - cx
                dist = (cxc * cxc + yy2) ** 0.5
                delta = abs(dist - r)

                if delta > (half + 0.5):
                    continue

                if delta < (half - 0.5):
                    a = 1.0
                else:
                    a = (half + 0.5) - delta

                off = rowoff + x * _bpp_bytes

                try:
                    bg_r, bg_g, bg_b = unpackrgb(_buffer[off:off + _bpp_bytes])
                except Exception:
                    bg_r = bg_g = bg_b = 0

                inv = 1.0 - a

                rr = int(sr * a + bg_r * inv + 0.5)
                rg = int(sg * a + bg_g * inv + 0.5)
                rb = int(sb * a + bg_b * inv + 0.5)

                setpixel(x, y, (rr, rg, rb))
                blended += 1

        markdirty(x0, y0, x1 + 1, y1 + 1)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle stroke={stroke}px blended={blended} bbox=({x0},{y0})-({x1+1},{y1+1})", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawcircle error {e}", flush=True)


def fillcircle(cx, cy, radius, color):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle no buffer", flush=True)
        return

    if _bpp_bytes <= 0 or _pack is None or _unpack is None:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle bad state bpp={_bpp_bytes} pack={_pack is not None} unpack={_unpack is not None}", flush=True)
        return

    if radius <= 0:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle non-positive radius r={radius}", flush=True)
        return

    try:

        if isinstance(color, int):
            sr = (color >> 16) & 0xFF
            sg = (color >> 8) & 0xFF
            sb = color & 0xFF
        else:
            sr, sg, sb = color

    except Exception:

        sr = sg = sb = 0

    try:

        packed = _pack((sr, sg, sb))

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle pack error {e}", flush=True)
        return

    try:

        r = float(radius)
        r_in  = r - 0.5
        r_out = r + 0.5
        r_out2 = r_out * r_out

        x0 = max(0, int(cx - r_out) - 1)
        y0 = max(0, int(cy - r_out) - 1)
        x1 = min(_xres - 1, int(cx + r_out) + 1)
        y1 = min(_yres - 1, int(cy + r_out) + 1)

        if x0 > x1 or y0 > y1:
            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle bbox empty", flush=True)
            return

        blended = 0
        rows_filled = 0
        y = y0

        while y <= y1:

            yc = (y + 0.5) - cy
            yy2 = yc * yc

            if yy2 > r_out2:
                y += 1
                continue

            t = r * r - yy2
            xr = t ** 0.5 if t >= 0 else 0.0

            t_in = r_in * r_in - yy2

            if t_in > 0:
                xin = t_in ** 0.5
                ix0 = int((cx - xin - 0.5) + 1.0)
                ix1 = int((cx + xin - 0.5))
                if ix0 < 0: ix0 = 0
                if ix1 > _xres - 1: ix1 = _xres - 1
            else:
                ix0 = 1
                ix1 = 0

            xL_real = cx - xr
            lx_start = max(x0, int(xL_real - 0.5) - 1)
            lx_end   = min(_xres - 1, ix0 - 1)

            if lx_start <= lx_end:

                rowoff = y * _line
                x = lx_start

                while x <= lx_end:

                    xc = (x + 0.5) - cx
                    dist = (xc * xc + yy2) ** 0.5

                    if dist < r_out:

                        a = r_out - dist
                        if a > 1.0: a = 1.0

                        if a > 0.0:

                            off = rowoff + x * _bpp_bytes

                            try:
                                bg_r, bg_g, bg_b = unpackrgb(_buffer[off:off + _bpp_bytes])
                            except Exception:
                                bg_r = bg_g = bg_b = 0

                            inv = 1.0 - a

                            rr = int(sr * a + bg_r * inv + 0.5)
                            rg = int(sg * a + bg_g * inv + 0.5)
                            rb = int(sb * a + bg_b * inv + 0.5)

                            setpixel(x, y, (rr, rg, rb))
                            blended += 1

                    x += 1

            if ix0 <= ix1 and 0 <= y < _yres:

                w = ix1 - ix0 + 1

                off = y * _line + ix0 * _bpp_bytes

                _buffer[off:off + w * _bpp_bytes] = packed * w

                rows_filled += 1

            xR_real = cx + xr
            rx_start = max(ix1 + 1, x0)
            rx_end   = min(_xres - 1, int(xR_real + 0.5) + 1)

            if rx_start <= rx_end:

                rowoff = y * _line
                x = rx_start

                while x <= rx_end:

                    xc = (x + 0.5) - cx
                    dist = (xc * xc + yy2) ** 0.5

                    if dist < r_out:

                        a = r_out - dist
                        if a > 1.0: a = 1.0

                        if a > 0.0:

                            off = rowoff + x * _bpp_bytes

                            try:
                                bg_r, bg_g, bg_b = unpackrgb(_buffer[off:off + _bpp_bytes])
                            except Exception:
                                bg_r = bg_g = bg_b = 0

                            inv = 1.0 - a

                            rr = int(sr * a + bg_r * inv + 0.5)
                            rg = int(sg * a + bg_g * inv + 0.5)
                            rb = int(sb * a + bg_b * inv + 0.5)

                            setpixel(x, y, (rr, rg, rb))
                            blended += 1

                    x += 1

            y += 1

        markdirty(x0, y0, x1 + 1, y1 + 1)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle aa rows_filled={rows_filled} blended={blended} bbox=({x0},{y0})-({x1+1},{y1+1})", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] fillcircle error {e}", flush=True)


def drawcursor(x, y, name="arrow"):


    info = CURSORS.get(name)

    if info is None or not info.get("data") or int(info.get("w", 0)) <= 0 or int(info.get("h", 0)) <= 0:

        info = CURSORS.get("arrow")

    if info is None or not info.get("data") or int(info.get("w", 0)) <= 0 or int(info.get("h", 0)) <= 0:

        return

    w = int(info["w"])
    h = int(info["h"])
    data = info["data"]
    stride = int(info.get("stride", w * 4))

    ix = int(x)
    iy = int(y)

    row = 0

    while row < h:

        dy = iy + row

        if dy < 0 or dy >= _yres:

            row += 1
            continue

        sy = row

        off = sy * stride
        end = off + w * 4

        if off < 0 or end > len(data):

            break

        rowdata = data[off:end]

        p = 0
        col = 0

        while col < w:

            dx = ix + col

            if dx < 0 or dx >= _xres:

                p += 4
                col += 1
                continue

            b = rowdata[p + 0]
            g = rowdata[p + 1]
            r = rowdata[p + 2]
            a = rowdata[p + 3]

            if a == 0:

                p += 4
                col += 1
                continue

            if a == 255:

                setpixel(dx, dy, (r, g, b))

            else:

                try:

                    offpix = dy * _line + dx * _bpp_bytes

                    bg_r, bg_g, bg_b = unpackrgb(_buffer[offpix:offpix + _bpp_bytes])

                except Exception:

                    bg_r = bg_g = bg_b = 0

                try:

                    af = a / 255.0

                    inv = 1.0 - af

                    rr = int(r * af + bg_r * inv + 0.5)
                    rg = int(g * af + bg_g * inv + 0.5)
                    rb = int(b * af + bg_b * inv + 0.5)

                    setpixel(dx, dy, (rr, rg, rb))

                except Exception:

                    setpixel(dx, dy, (r, g, b))

            p += 4
            col += 1

        row += 1

def blitfilepart(path, totalw, srcx, srcy, w, h, dstx, dsty, fmt="BGRA32"):


    # validate sizes
    if w <= 0 or h <= 0 or totalw <= 0:
        return

    # open source buffer file
    with open(path, "rb") as f:
        locked = lockbuffer(f)

        try:

            # iterate rows
            for row in range(h):

                # compute source row start (in pixels)
                wy = srcy + row
                wx = srcx
                offpix = (wy * totalw + wx)

                # seek to start of this row slice
                try:
                    f.seek(offpix * 4)
                except Exception:
                    break

                # read exactly w pixels
                data = f.read(w * 4)

                if not data or len(data) < w * 4:
                    break

                # copy pixels to destination
                p = 0
                for col in range(w):

                    if fmt == "RGBA32":
                        r = data[p + 0]
                        g = data[p + 1]
                        b = data[p + 2]
                    else:
                        b = data[p + 0]
                        g = data[p + 1]
                        r = data[p + 2]

                    # draw pixel
                    setpixel(dstx + col, dsty + row, (r, g, b))

                    p += 4

        finally:

            if locked:
                unlockbuffer(f)

def blitfilepartfast(
    path, totalw, srcx, srcy, w, h, dstx, dsty, fmt="BGRA32",
    stride=None, source_offset=0,
):

    if not _buffer:
        return


    if w <= 0 or h <= 0 or totalw <= 0:
        return

    if dstx < 0:
        cut = -dstx
        if cut >= w:
            return
        srcx += cut
        w -= cut
        dstx = 0

    if dsty < 0:
        cut = -dsty
        if cut >= h:
            return
        srcy += cut
        h -= cut
        dsty = 0

    if dstx + w > _xres:
        w = _xres - dstx

    if dsty + h > _yres:
        h = _yres - dsty

    if w <= 0 or h <= 0:
        return

    if fmt != "BGRA32":
        return

    rowbytes = w * 4
    stridebytes = int(stride) if stride is not None else int(totalw) * 4
    source_offset = int(source_offset)

    if stridebytes < int(totalw) * 4 or source_offset < 0:
        return

    with open(path, "rb") as f:
        locked = lockbuffer(f)

        try:
            row = 0

            while row < h:

                sy = srcy + row

                sx = srcx

                src_off = source_offset + sy * stridebytes + sx * 4

                try:
                    f.seek(src_off)
                    data = f.read(rowbytes)
                    if not data or len(data) < rowbytes:
                        break
                except Exception:
                    break

                dy = dsty + row

                dst_off = dy * _line + dstx * _bpp_bytes

                _buffer[dst_off:dst_off + rowbytes] = data

                row += 1

        finally:

            if locked:
                unlockbuffer(f)

    markdirty(dstx, dsty, dstx + w, dsty + h)


def beginscaledfileframe():

    global _scaled_file_frame_cache, _scaled_file_frame_metrics

    _scaled_file_frame_cache = {}
    _scaled_file_frame_metrics = {
        "calls": 0,
        "regions": 0,
        "source_reads": 0,
        "cache_hits": 0,
    }
    return True


def endscaledfileframe():

    global _scaled_file_frame_cache, _scaled_file_frame_metrics
    global _scaled_file_last_metrics

    result = dict(_scaled_file_frame_metrics or _scaled_file_last_metrics)
    _scaled_file_frame_cache = None
    _scaled_file_frame_metrics = None
    _scaled_file_last_metrics = dict(result)
    return result


def scaledfileframemetrics():

    return dict(_scaled_file_frame_metrics or _scaled_file_last_metrics)


def _scaledfilesource(path, sourcew, sourceh, stridebytes, sourcebase):

    global _scaled_file_frame_cache, _scaled_file_frame_metrics

    key = (
        os.path.abspath(str(path)),
        int(sourcew),
        int(sourceh),
        int(stridebytes),
        int(sourcebase),
    )
    if _scaled_file_frame_cache is not None and key in _scaled_file_frame_cache:
        if _scaled_file_frame_metrics is not None:
            _scaled_file_frame_metrics["cache_hits"] += 1
        return _scaled_file_frame_cache[key]

    with open(path, "rb") as stream:
        locked = lockbuffer(stream)

        try:
            source = bytearray(sourcew * sourceh * 4)
            view = memoryview(source)

            for sourcerow in range(sourceh):
                stream.seek(sourcebase + sourcerow * stridebytes)
                rowstart = sourcerow * sourcew * 4
                rowend = rowstart + sourcew * 4
                if stream.readinto(view[rowstart:rowend]) != sourcew * 4:
                    raise RuntimeError(
                        f"short scaled image read from {path}"
                    )

        finally:
            if locked:
                unlockbuffer(stream)

    if _scaled_file_frame_metrics is not None:
        _scaled_file_frame_metrics["source_reads"] += 1
    if _scaled_file_frame_cache is not None:
        _scaled_file_frame_cache[key] = source
    return source


def blitfilescaledfast(
    path, sourcew, sourceh, dstx, dsty, dstw, dsth, fmt="BGRA32",
    clip=None, stride=None, source_offset=0,
):

    if not _buffer or fmt != "BGRA32":
        return False

    try:

        sourcew = int(sourcew)
        sourceh = int(sourceh)
        originalx = int(dstx)
        originaly = int(dsty)
        originalw = int(dstw)
        originalh = int(dsth)
        stridebytes = int(stride) if stride is not None else sourcew * 4
        sourcebase = int(source_offset)

    except Exception:

        return False

    if (
        sourcew < 1
        or sourceh < 1
        or originalw < 1
        or originalh < 1
        or stridebytes < sourcew * 4
        or sourcebase < 0
    ):
        return False

    left = max(0, originalx)
    top = max(0, originaly)
    right = min(int(_xres), originalx + originalw)
    bottom = min(int(_yres), originaly + originalh)

    if clip is not None:

        try:

            clipx, clipy, clipw, cliph = [int(value) for value in clip]
            left = max(left, clipx)
            top = max(top, clipy)
            right = min(right, clipx + clipw)
            bottom = min(bottom, clipy + cliph)

        except Exception:

            return False

    if right <= left or bottom <= top:
        return False

    try:

        source = _scaledfilesource(
            path, sourcew, sourceh, stridebytes, sourcebase,
        )

    except Exception:

        return False

    if len(source) != sourcew * sourceh * 4:
        return False

    if _scaled_file_frame_metrics is not None:
        _scaled_file_frame_metrics["calls"] += 1
        _scaled_file_frame_metrics["regions"] += 1

    visiblew = right - left
    columns = [
        min(sourcew - 1, max(0, ((left - originalx + column) * sourcew) // originalw))
        for column in range(visiblew)
    ]
    row = top

    while row < bottom:

        sourcey = min(sourceh - 1, max(0, ((row - originaly) * sourceh) // originalh))
        sourcerow = sourcey * sourcew * 4
        output = bytearray(visiblew * 4)

        for column, sourcex in enumerate(columns):

            pixeloffset = sourcerow + sourcex * 4
            outputoffset = column * 4
            output[outputoffset:outputoffset + 4] = source[pixeloffset:pixeloffset + 4]

        destination = row * _line + left * _bpp_bytes
        _buffer[destination:destination + len(output)] = output
        row += 1

    markdirty(left, top, right, bottom)
    return True

def blitbytesfast(data, totalw, totalh, srcx, srcy, w, h, dstx, dsty, fmt="BGRA32"):

    if not _buffer:
        return False

    if fmt != "BGRA32":
        return False

    try:
        totalw = int(totalw)
        totalh = int(totalh)
        srcx = int(srcx)
        srcy = int(srcy)
        w = int(w)
        h = int(h)
        dstx = int(dstx)
        dsty = int(dsty)

    except Exception:
        return False

    if totalw <= 0 or totalh <= 0 or w <= 0 or h <= 0:
        return False

    try:
        source = memoryview(data)

    except Exception:
        return False

    required = totalw * totalh * 4

    if len(source) != required:
        return False

    if srcx < 0:
        cut = -srcx
        srcx = 0
        dstx += cut
        w -= cut

    if srcy < 0:
        cut = -srcy
        srcy = 0
        dsty += cut
        h -= cut

    if dstx < 0:
        cut = -dstx
        dstx = 0
        srcx += cut
        w -= cut

    if dsty < 0:
        cut = -dsty
        dsty = 0
        srcy += cut
        h -= cut

    if srcx + w > totalw:
        w = totalw - srcx

    if srcy + h > totalh:
        h = totalh - srcy

    if dstx + w > _xres:
        w = _xres - dstx

    if dsty + h > _yres:
        h = _yres - dsty

    if w <= 0 or h <= 0:
        return False

    rowbytes = w * 4
    row = 0

    while row < h:
        sourceoff = ((srcy + row) * totalw + srcx) * 4
        targetoff = (dsty + row) * _line + dstx * _bpp_bytes
        _buffer[targetoff:targetoff + rowbytes] = source[sourceoff:sourceoff + rowbytes]
        row += 1

    markdirty(dstx, dsty, dstx + w, dsty + h)

    return True

def fillbufferfile(path, totalw, x, y, w, h, color):

    try:

        if w <= 0 or h <= 0:
            return

        try:
            r, g, b = color
            r = int(r) & 0xFF
            g = int(g) & 0xFF
            b = int(b) & 0xFF
        except Exception:
            r = (int(color) >> 16) & 0xFF
            g = (int(color) >> 8) & 0xFF
            b = int(color) & 0xFF

        if x < 0:
            w += x
            x = 0

        if y < 0:
            h += y
            y = 0

        rowpix = w
        if rowpix <= 0:
            return

        span = bytes((b, g, r, 0xFF)) * rowpix

        with open(path, 'r+b') as f:

            for row in range(h):

                off = ((y + row) * totalw + x) * 4

                f.seek(off)

                f.write(span)

    except PermissionError:

        log(f"{timestamp()} [graphics] fillbufferfile denied {path}", flush=True)
    except Exception as e:

        log(f"{timestamp()} [graphics] fillbufferfile error {e}", flush=True)
def fillrectfast(x, y, w, h, rgb):

    if not _buffer:
        return


    if w <= 0 or h <= 0:
        return

    try:
        r, g, b = rgb
    except Exception:
        r = (int(rgb) >> 16) & 0xFF
        g = (int(rgb) >> 8) & 0xFF
        b = int(rgb) & 0xFF

    if x < 0:
        w += x
        x = 0

    if y < 0:
        h += y
        y = 0

    if x + w > _xres:
        w = _xres - x

    if y + h > _yres:
        h = _yres - y

    if w <= 0 or h <= 0:
        return

    row = bytes((b & 0xFF, g & 0xFF, r & 0xFF, 0xFF)) * w

    span = w * _bpp_bytes

    yy = y
    while yy < y + h:

        off = yy * _line + x * _bpp_bytes

        _buffer[off:off + span] = row

        yy += 1

    markdirty(x, y, x + w, y + h)


def scrollrect(x, y, w, h, dx=0, dy=0):

    if not _buffer:
        return False

    try:
        x = max(0, int(x))
        y = max(0, int(y))
        w = min(int(w), int(_xres) - x)
        h = min(int(h), int(_yres) - y)
        dx = int(dx)
        dy = int(dy)

        if w <= 0 or h <= 0 or (dx == 0 and dy == 0):
            return False

        sourceleft = x + max(0, -dx)
        sourcetop = y + max(0, -dy)
        targetleft = x + max(0, dx)
        targettop = y + max(0, dy)
        copywidth = w - abs(dx)
        copyheight = h - abs(dy)

        if copywidth <= 0 or copyheight <= 0:
            return False

        rowbytes = copywidth * int(_bpp_bytes)
        rows = range(copyheight - 1, -1, -1) if dy > 0 else range(copyheight)

        for rowindex in rows:
            sourceoff = (sourcetop + rowindex) * _line + sourceleft * _bpp_bytes
            targetoff = (targettop + rowindex) * _line + targetleft * _bpp_bytes
            _buffer[targetoff:targetoff + rowbytes] = _buffer[sourceoff:sourceoff + rowbytes]

        markdirty(targetleft, targettop, targetleft + copywidth, targettop + copyheight)
        return True

    except Exception:
        return False


def clear(color=0):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] clear no buffer", flush=True)
        return

    try:

        markdirty(0, 0, _xres, _yres)

        if _pack is None:

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] clear _pack is None", flush=True)
            return

        packed = _pack(normalisecolor(color))

        span = _xres * _bpp_bytes

        rowdata = packed * _xres

        for y in range(_yres):

            off = y * _line

            _buffer[off:off + span] = rowdata

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] clear done", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] clear error {e}", flush=True)


# font functions
def ttfloadflags(path=None, face=None):

    try:

        name = os.path.basename(str(path or "")).lower()

        if "atkinsonhyperlegiblenext" in name:
            return FT_LOAD_DEFAULT

        family = getattr(face, "family_name", b"") if face is not None else b""

        if isinstance(family, bytes):
            family = family.decode("utf-8", errors="ignore")

        if "atkinson hyperlegible next" in str(family).lower():
            return FT_LOAD_DEFAULT

    except Exception:
        pass

    return FT_LOAD_T1OS_TEXT


def getttfface(path):

    global TTFFACES

    if not path:
        return None


    face = TTFFACES.get(path)

    if face is not None:
        return face

    try:

        face = freetype.Face(path)

        TTFFACES[path] = face

        return face

    except FileNotFoundError:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF not found {path}", flush=True)
        return None

    except PermissionError:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF permission denied {path}", flush=True)
        return None

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF load error {e}", flush=True)
        return None


def ttffontkey(path=None):

    try:

        if path:
            return str(path)

        if _ttffacepath:
            return str(_ttffacepath)

    except Exception:
        pass

    return "__default__"


def initttffont(path, size):

    global _ttfface, _ttffacepath

    try:

        face = freetype.Face(path)

        face.set_pixel_sizes(0, size)

        _ttfface = face
        _ttffacepath = str(path)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] loaded TTF {path} @ {size}px", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF load error {e}", flush=True)


def drawtextttf(x, y, text, color, size, fontpath=None, clip=None):

    global _ttfface, _buffer, _line, _bpp_bytes, _pack, _unpack, _xres, _yres
    global _roff, _goff, _boff, _rlen, _glen, _blen
    global TTFGLYPHS

    if not _buffer:
        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtextttf no buffer", flush=True)
        return

    clipbounds = None

    if clip is not None:

        try:

            clipx, clipy, clipw, cliph = [int(value) for value in clip]
            clipbounds = (
                max(0, clipx),
                max(0, clipy),
                min(int(_xres), clipx + max(0, clipw)),
                min(int(_yres), clipy + max(0, cliph)),
            )

            if clipbounds[2] <= clipbounds[0] or clipbounds[3] <= clipbounds[1]:
                return

        except Exception:

            return

    try:

        if fontpath:

            face = getttfface(fontpath)

        else:

            face = _ttfface

    except Exception:

        face = _ttfface

    if face is None:
        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtextttf no font", flush=True)
        return

    try:

        face.set_pixel_sizes(0, size)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF set size error {e}", flush=True)
        return

    try:

        pen_x = x
        loadflags = ttfloadflags(fontpath, face)

        pen_y = y + size

        dirty = False

        minx = x
        miny = y
        maxx = x
        maxy = y

        r_fg = (color >> 16) & 0xFF
        g_fg = (color >>  8) & 0xFF
        b_fg =  color        & 0xFF
        coveragelut = (
            TEXTLIGHTCOVERAGE
            if (r_fg * 299) + (g_fg * 587) + (b_fg * 114) >= 127500
            else TEXTDARKCOVERAGE
        )

        fast32 = False

        rbyte = 0
        gbyte = 1
        bbyte = 2

        if _bpp_bytes == 4 and _rlen == 8 and _glen == 8 and _blen == 8:

            if (_roff % 8) == 0 and (_goff % 8) == 0 and (_boff % 8) == 0:

                rbyte = _roff // 8
                gbyte = _goff // 8
                bbyte = _boff // 8

                if 0 <= rbyte <= 3 and 0 <= gbyte <= 3 and 0 <= bbyte <= 3:

                    if rbyte != gbyte and rbyte != bbyte and gbyte != bbyte:

                        fast32 = True

        fontkey = ttffontkey(fontpath)

        for ch in text:

            glyph = None

            try:

                cachekey = (fontkey, int(size), ch)

            except Exception:

                cachekey = None

            if cachekey is not None:

                glyph = TTFGLYPHS.get(cachekey)


                if len(TTFGLYPHS) > TTFGLYPHSCAP:

                    TTFGLYPHS.clear()

                    if _DEBUG_GRAPHICS: log(
                        f"{timestamp()} [graphics] TTF glyph cache cleared cap={TTFGLYPHSCAP}", flush=True)

            if glyph is None:

                try:

                    face.load_char(ch, loadflags)
                    face.glyph.render(freetype.FT_RENDER_MODE_NORMAL)

                except Exception as e:

                    if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF glyph '{ch}' render error {e}", flush=True)
                    continue

                try:

                    bitmap = face.glyph.bitmap
                    buf = bitmap.buffer
                    pitch = bitmap.pitch
                    w = bitmap.width
                    h = bitmap.rows
                    top = face.glyph.bitmap_top
                    left = face.glyph.bitmap_left


                    adv    = int(face.glyph.advance.x >> 6)

                    glyph = (buf, pitch, w, h, top, left, adv)

                except Exception as e:

                    if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] TTF glyph '{ch}' cache pack error {e}", flush=True)
                    continue

                if cachekey is not None:


                    TTFGLYPHS[cachekey] = glyph


            buf, pitch, w, h, top, left, adv = glyph

            # Cached glyphs are still painted into the backbuffer and must be
            # included in the dirty rectangle.  Previously these bounds were
            # updated only on a cache miss, so later text made mostly from
            # cached letters was drawn but never copied to the window surface.
            if w > 0 and h > 0:

                gx0 = pen_x + left
                gy0 = pen_y - top
                gx1 = gx0 + w
                gy1 = gy0 + h

                if not dirty:

                    minx = gx0
                    miny = gy0
                    maxx = gx1
                    maxy = gy1
                    dirty = True

                else:

                    if gx0 < minx: minx = gx0
                    if gy0 < miny: miny = gy0
                    if gx1 > maxx: maxx = gx1
                    if gy1 > maxy: maxy = gy1

            for row in range(h):

                rowStart = row * pitch

                for col in range(w):

                    idx = rowStart + col

                    try:
                        a8 = buf[idx]
                    except Exception:
                        a8 = 0

                    a8 = coveragelut[a8]

                    if a8 <= 0:
                        continue

                    fx = pen_x + left + col
                    fy = pen_y - top  + row

                    if fx < 0 or fx >= _xres or fy < 0 or fy >= _yres:
                        continue

                    if clipbounds is not None and (
                        fx < clipbounds[0] or fx >= clipbounds[2]
                        or fy < clipbounds[1] or fy >= clipbounds[3]
                    ):
                        continue

                    off = fy * _line + fx * _bpp_bytes
                    if fast32:

                        bg_r = _buffer[off + rbyte]
                        bg_g = _buffer[off + gbyte]
                        bg_b = _buffer[off + bbyte]
                        inv = 255 - a8

                        r = (r_fg * a8 + bg_r * inv + 127) // 255
                        g = (g_fg * a8 + bg_g * inv + 127) // 255
                        b = (b_fg * a8 + bg_b * inv + 127) // 255

                        _buffer[off + rbyte] = r
                        _buffer[off + gbyte] = g
                        _buffer[off + bbyte] = b
                    else:

                        try:
                            bg_r, bg_g, bg_b = unpackrgb(_buffer[off:off + _bpp_bytes])
                        except Exception:
                            bg_r = bg_g = bg_b = 0

                        inv = 255 - a8

                        r = (r_fg * a8 + bg_r * inv + 127) // 255
                        g = (g_fg * a8 + bg_g * inv + 127) // 255
                        b = (b_fg * a8 + bg_b * inv + 127) // 255

                        _buffer[off:off + _bpp_bytes] = _pack((r, g, b))
            pen_x += adv

        if dirty:


            if minx < 0: minx = 0
            if miny < 0: miny = 0
            if maxx > _xres: maxx = _xres
            if maxy > _yres: maxy = _yres

            if clipbounds is not None:

                minx = max(minx, clipbounds[0])
                miny = max(miny, clipbounds[1])
                maxx = min(maxx, clipbounds[2])
                maxy = min(maxy, clipbounds[3])

            if maxx > minx and maxy > miny:
                markdirty(minx, miny, maxx, maxy)

        else:

            if clipbounds is None:
                markdirty(x, y, pen_x, y + size)

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtextttf (grayscale) text='{text}' box=({x},{y})-({pen_x},{y+size})", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtextttf error {e}", flush=True)


def drawtextttfopaque(x, y, text, color, background, size, fontpath=None, height=None, clip=None):

    global TTFOPAQUECACHEBYTES

    if not _buffer:
        return

    text = str(text)

    if not text:
        return

    try:
        if isinstance(color, int):
            foreground = ((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)
        else:
            foreground = normalisecolor(color)

        if isinstance(background, int):
            back = ((background >> 16) & 0xFF, (background >> 8) & 0xFF, background & 0xFF)
        else:
            back = normalisecolor(background)
        size = max(1, int(size))
        surfaceheight = max(size, int(height if height is not None else size))
        fontkey = ttffontkey(fontpath)
        cachekey = (fontkey, size, surfaceheight, text, tuple(foreground), tuple(back))
        cached = TTFOPAQUECACHE.get(cachekey)

        if cached is not None:
            TTFOPAQUECACHE.move_to_end(cachekey)
            surfacewidth, pixels = cached

        else:
            face = getttfface(fontpath) if fontpath else _ttfface

            if face is None:
                drawtextttf(x, y, text, color, size, fontpath=fontpath, clip=clip)
                return

            face.set_pixel_sizes(0, size)
            loadflags = ttfloadflags(fontpath, face)
            glyphs = []
            surfacewidth = 0

            for character in text:
                glyphkey = (fontkey, size, character)
                glyph = TTFGLYPHS.get(glyphkey)

                if glyph is None:
                    face.load_char(character, loadflags)
                    face.glyph.render(freetype.FT_RENDER_MODE_NORMAL)
                    bitmap = face.glyph.bitmap
                    glyph = (
                        bitmap.buffer,
                        bitmap.pitch,
                        bitmap.width,
                        bitmap.rows,
                        face.glyph.bitmap_top,
                        face.glyph.bitmap_left,
                        int(face.glyph.advance.x >> 6),
                    )
                    TTFGLYPHS[glyphkey] = glyph

                glyphs.append(glyph)
                surfacewidth += int(glyph[6])

            surfacewidth = max(1, int(surfacewidth))
            br, bg, bb = [int(value) & 0xFF for value in back]
            fr, fg, fb = [int(value) & 0xFF for value in foreground]
            backgroundpixel = bytes((bb, bg, br, 0xFF))
            pixels = bytearray(backgroundpixel * (surfacewidth * surfaceheight))
            coverage = TEXTLIGHTCOVERAGE if (fr * 299) + (fg * 587) + (fb * 114) >= 127500 else TEXTDARKCOVERAGE
            penx = 0

            for glyph in glyphs:
                buffer, pitch, glyphwidth, glyphheight, top, left, advance = glyph
                glyphx = penx + int(left)
                glyphy = size - int(top)

                for glyphrow in range(int(glyphheight)):
                    targety = glyphy + glyphrow

                    if targety < 0 or targety >= surfaceheight:
                        continue

                    rowstart = glyphrow * int(pitch)

                    for glyphcolumn in range(int(glyphwidth)):
                        targetx = glyphx + glyphcolumn

                        if targetx < 0 or targetx >= surfacewidth:
                            continue

                        alpha = coverage[buffer[rowstart + glyphcolumn]]

                        if alpha <= 0:
                            continue

                        inverse = 255 - alpha
                        red = (fr * alpha + br * inverse + 127) // 255
                        green = (fg * alpha + bg * inverse + 127) // 255
                        blue = (fb * alpha + bb * inverse + 127) // 255
                        offset = (targety * surfacewidth + targetx) * 4
                        pixels[offset:offset + 4] = bytes((blue, green, red, 0xFF))

                penx += int(advance)

            pixels = bytes(pixels)
            entrybytes = len(pixels) + len(text.encode('utf-8', errors='replace')) + 128
            TTFOPAQUECACHE[cachekey] = (surfacewidth, pixels)
            TTFOPAQUECACHEBYTES += entrybytes

            while TTFOPAQUECACHE and TTFOPAQUECACHEBYTES > TTFOPAQUECACHELIMIT:
                oldkey, oldvalue = TTFOPAQUECACHE.popitem(last=False)
                TTFOPAQUECACHEBYTES -= len(oldvalue[1]) + len(str(oldkey[3]).encode('utf-8', errors='replace')) + 128

        left = max(0, int(x))
        top = max(0, int(y))
        right = min(int(_xres), int(x) + int(surfacewidth))
        bottom = min(int(_yres), int(y) + int(surfaceheight))

        if clip is not None:
            clipx, clipy, clipwidth, clipheight = [int(value) for value in clip]
            left = max(left, clipx)
            top = max(top, clipy)
            right = min(right, clipx + clipwidth)
            bottom = min(bottom, clipy + clipheight)

        if right <= left or bottom <= top:
            return

        copywidth = right - left
        rowbytes = copywidth * 4
        sourcestartx = left - int(x)

        for targety in range(top, bottom):
            sourcey = targety - int(y)
            sourceoff = (sourcey * surfacewidth + sourcestartx) * 4
            targetoff = targety * _line + left * _bpp_bytes
            _buffer[targetoff:targetoff + rowbytes] = pixels[sourceoff:sourceoff + rowbytes]

        markdirty(left, top, right, bottom)

    except Exception:
        drawtextttf(x, y, text, color, size, fontpath=fontpath, clip=clip)


def drawchar(x, y, ch, color, scale=1):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawchar no buffer", flush=True)
        return

    try:

        if _pack is None:
            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawchar _pack is None", flush=True)
            return

        packed = _pack(color)

        glyph = FONT8x8.get(ord(ch), FONT8x8.get(32, [0]*8))

        for row in range(8):

            bits = glyph[row]

            for bit in range(8):

                if bits & (1 << bit):

                    for dx in range(scale):

                        for dy in range(scale):

                            px = x + bit * scale + dx
                            py = y + row * scale + dy

                            if px < 0 or py < 0 or px >= _xres or py >= _yres:
                                continue

                            off = py * _line + px * _bpp_bytes
                            _buffer[off:off + _bpp_bytes] = packed
        markdirty(x, y, x + 8 * scale, y + 8 * scale)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawchar error {e}", flush=True)


def drawtext(x, y, text, color, spacing=1, scale=1):

    if not _buffer:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtext no buffer", flush=True)
        return

    try:

        cx = x

        for ch in text:

            drawchar(cx, y, ch, color, scale=scale)

            cx += (8 + spacing) * scale

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] drawtext error {e}", flush=True)


def ttfbbox(text, size, fontpath=None):

    try:

        if fontpath:

            face = getttfface(fontpath)

        else:

            face = _ttfface

    except Exception:

        face = _ttfface

    try:

        if face is None:
            return (0, 0)

        face.set_pixel_sizes(0, int(size))

    except Exception:

        return (0, 0)

    try:

        pen_y = int(size)
        loadflags = ttfloadflags(fontpath, face)

        miny = 0
        maxy = 0
        dirty = False

        for ch in text:


            face.load_char(ch, loadflags)


            bitmap = face.glyph.bitmap
            h = int(bitmap.rows)

            top = int(face.glyph.bitmap_top)

            gy0 = pen_y - top
            gy1 = gy0 + h

            if not dirty:

                miny = gy0
                maxy = gy1
                dirty = True

            else:

                if gy0 < miny: miny = gy0
                if gy1 > maxy: maxy = gy1

        if not dirty:
            return (0, int(size))

        return (int(miny), int(maxy))

    except Exception:

        return (0, int(size))


def ttflinebox(size, fontpath=None):

    try:

        # worst-case sample: ascenders + descenders
        miny, maxy = ttfbbox("AgjpqyQ|", size, fontpath=fontpath)

        yoff = int(miny)
        h = int(maxy - miny)

        if h < 1:
            h = int(size)

        return (yoff, h)

    except Exception:

        return (0, int(size))


def measuretext(text, size, fontpath=None):

    try:

        if fontpath:

            face = getttfface(fontpath)

        else:

            face = _ttfface

    except Exception:

        face = _ttfface

    try:

        if face is None:
            return 0

        face.set_pixel_sizes(0, size)

    except Exception:

        return 0

    try:

        width = 0
        loadflags = ttfloadflags(fontpath, face)

        fontkey = ttffontkey(fontpath)

        for ch in text:

            cachekey = (fontkey, int(size), ch)
            advance = TTFADVANCES.get(cachekey)

            if advance is None:

                face.load_char(ch, loadflags)
                advance = int(face.glyph.advance.x >> 6)
                TTFADVANCES[cachekey] = advance

                if len(TTFADVANCES) > TTFADVANCESCAP:

                    TTFADVANCES.clear()
                    TTFADVANCES[cachekey] = advance

            width += int(advance)

        return width

    except Exception:

        return 0


def measurelineadvances(row, text, size, fontpath=None):

    global ADV_ROW
    global ADV_TEXT
    global ADV_FONT
    global ADV_SIZE
    global ADV_LIST
    global ADVCACHE
    global ADVCACHEBYTES
    global ADVCACHESIZES
    global ADVRECENTBYTES

    text = str(text)
    fontkey = ttffontkey(fontpath)
    metricfontkey = (fontkey, max(1, int(TEXTTABWIDTH)))
    cachekey = (row, text, metricfontkey, size)
    recentidentity = row

    if (
        isinstance(row, tuple)
        and len(row) >= 3
        and str(row[0]) in ('metrics', 'wrap-line', 'hit-wrap', 'visible-wrap', 'line-wrap')
    ):
        recentidentity = (row[0], row[1], *row[3:])

    recentkey = (recentidentity, metricfontkey, int(size))

    cached = ADVCACHE.get(cachekey)

    if cached is not None:

        try:
            ADVCACHE.move_to_end(cachekey)
        except Exception:
            pass

        return cached

    if ADV_ROW == row and ADV_TEXT == text and ADV_FONT == metricfontkey and ADV_SIZE == size:

        if ADV_LIST is not None:
            return ADV_LIST

    try:

        if fontpath:

            face = getttfface(fontpath)

        else:

            face = _ttfface

    except Exception:

        face = _ttfface

    try:

        if face is None:
            return []

        face.set_pixel_sizes(0, size)

    except Exception:

        return []

    advances = None
    xpos = 0
    visualcolumn = 0
    loadflags = ttfloadflags(fontpath, face)

    try:

        recent = ADVRECENT.get(recentkey)
        suffix = text

        if recent is not None:
            oldtext, oldadvances, _ = recent

            if len(text) >= len(oldtext) and text.startswith(oldtext):
                advances = oldadvances[:]
                xpos = int(advances[-1]) if advances else 0
                visualcolumn = len(oldtext) if '\t' not in oldtext else len(oldtext.expandtabs(max(1, int(TEXTTABWIDTH))))
                suffix = text[len(oldtext):]
            elif len(oldtext) > len(text) and oldtext.startswith(text):
                advances = oldadvances[:len(text)]
                suffix = ''

        if advances is None:
            advances = PackedAdvances()
            suffix = text

        for ch in suffix:

            measuredcharacter = ' ' if ch == '\t' else ch
            advancekey = (fontkey, int(size), measuredcharacter)
            advance = TTFADVANCES.get(advancekey)

            if advance is None:

                face.load_char(measuredcharacter, loadflags)
                advance = int(face.glyph.advance.x >> 6)
                TTFADVANCES[advancekey] = advance

                if len(TTFADVANCES) > TTFADVANCESCAP:

                    TTFADVANCES.clear()
                    TTFADVANCES[advancekey] = advance

            if ch == '\t':
                spaces = max(1, int(TEXTTABWIDTH)) - (visualcolumn % max(1, int(TEXTTABWIDTH)))
                xpos += int(advance) * spaces
                visualcolumn += spaces
            else:
                xpos += int(advance)
                visualcolumn += 1

            advances.append(xpos)

    except Exception:

        return []


    ADV_ROW = row
    ADV_TEXT = text
    ADV_FONT = metricfontkey
    ADV_SIZE = size
    ADV_LIST = advances
    if not ADVCACHE:
        ADVCACHEBYTES = 0
        ADVCACHESIZES.clear()

    # Cumulative advances are non-negative pixel offsets.  A packed uint32
    # sequence keeps million-character lines practical (4 bytes per column
    # instead of one Python integer object per column) while retaining the
    # sequence interface used by bisect and cursor hit testing.
    estimated = max(128, len(str(text).encode('utf-8', errors='replace')) + (len(advances) * advances.itemsize))
    previoussize = int(ADVCACHESIZES.pop(cachekey, 0))
    ADVCACHEBYTES -= previoussize
    ADVCACHE[cachekey] = advances
    ADVCACHESIZES[cachekey] = estimated
    ADVCACHEBYTES += estimated

    while ADVCACHE and (
        len(ADVCACHE) > ADVCACHECAP
        or ADVCACHEBYTES > ADVCACHEBYTELIMIT
    ):

        try:
            oldest, _ = ADVCACHE.popitem(last=False)
            ADVCACHEBYTES -= int(ADVCACHESIZES.pop(oldest, 0))
        except Exception:
            ADVCACHE.clear()
            ADVCACHESIZES.clear()
            ADVCACHEBYTES = 0
            break

    previousrecent = ADVRECENT.pop(recentkey, None)

    if previousrecent is not None:
        ADVRECENTBYTES -= int(previousrecent[2])

    ADVRECENT[recentkey] = (text, advances, estimated)
    ADVRECENTBYTES += estimated

    while ADVRECENT and ADVRECENTBYTES > ADVRECENTLIMIT:
        _, removed = ADVRECENT.popitem(last=False)
        ADVRECENTBYTES -= int(removed[2])

    return advances


# surface management
def supersample(factor, drawfn, *args, **kwargs):

    global _buffer, _line, _xres, _yres

    if factor <= 1:

        try:

            drawfn(*args, **kwargs)

        except Exception as e:

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample drawfn error {e}", flush=True)

        return

    if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample start factor={factor}", flush=True)

    try:

        hi_x = _xres * factor
        hi_y = _yres * factor
        hi_line = hi_x * _bpp_bytes
        hi_size = hi_line * hi_y
        hi_buf = bytearray(hi_size)

        old_buf  = _buffer
        old_line = _line
        old_xres = _xres
        old_yres = _yres

        _buffer = hi_buf
        _line   = hi_line
        _xres   = hi_x
        _yres   = hi_y

        try:

            drawfn(*args, **kwargs)

        except Exception as e:

            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample drawfn error {e}", flush=True)

        _buffer = old_buf
        _line   = old_line
        _xres   = old_xres
        _yres   = old_yres

        for y in range(_yres):

            yy = y * factor

            for x in range(_xres):

                xx = x * factor

                rs = gs = bs = 0

                for dy in range(factor):

                    rowoff = (yy + dy) * hi_line

                    for dx in range(factor):

                        off = rowoff + (xx + dx) * _bpp_bytes

                        try:
                            r, g, b = unpackrgb(hi_buf[off:off + _bpp_bytes])
                        except Exception as e:
                            if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample read error at ({x},{y}) {e}", flush=True)
                            r = g = b = 0

                        rs += r
                        gs += g
                        bs += b

                n = factor * factor
                avr = rs // n
                avg = gs // n
                avb = bs // n

                setpixel(x, y, (avr, avg, avb))

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample done", flush=True)

    except Exception as e:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] supersample error {e}", flush=True)


# present functions
def lockbuffer(stream, exclusive=False):

    try:
        descriptor = stream if isinstance(stream, int) else stream.fileno()
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

        return True

    except Exception:
        return False


def unlockbuffer(stream):

    try:
        descriptor = stream if isinstance(stream, int) else stream.fileno()
        fcntl.flock(descriptor, fcntl.LOCK_UN)

    except Exception:
        pass


def present():

    global _IS_FILE_BUFFER, _FILE_MAP, _map, _buffer, _size
    global _drmdumblastpresenterror
    global _framebufferwritesequence

    try:

        if _backend == "opengl":

            try:
                return bool(kmspresent())
            except GPUDeviceLostError:
                raise
            except Exception as e:
                log(f"> graphics OpenGL present error {e}")

            return False

        # file-buffer mode → copy backbuffer to mapped file
        if _IS_FILE_BUFFER:

            if not _FILE_MAP or not _buffer:
                return False

            locked = lockbuffer(_FILE_FD, exclusive=True)

            try:
                _FILE_MAP.seek(0)
                _FILE_MAP.write(_buffer)

                if FILEBUFFERFLUSH:
                    _FILE_MAP.flush()
                return True
            except Exception as e:
                log(f"> graphics present file-map error {e}")
                return False

            finally:

                if locked:
                    unlockbuffer(_FILE_FD)

            return False

        # default framebuffer mode (existing behaviour)
        if _map and _buffer:

            try:
                _map.seek(0)
                written = _map.write(_buffer)

                if written is not None and int(written) != len(_buffer):
                    raise OSError(
                        f"short framebuffer write "
                        f"{int(written)}/{len(_buffer)}"
                    )

                if _backend == "kms-framebuffer":
                    return bool(_kmsframebuffercommitwrittenframe())

                # Native DRM fbdev commonly maps write-combined video memory.
                # msync/mmap.flush can block indefinitely in a wedged vendor
                # driver and is not its presentation boundary. FBIOPAN plus an
                # advancing DRM CRTC sequence proves that path instead.
                if not _framebuffernativedrm:
                    _map.flush()

                if _backend == "framebuffer":
                    _framebufferwritesequence += 1

                if (
                    _backend == "framebuffer"
                    and not framebufferactivatepagezero()
                ):
                    raise RuntimeError(
                        "framebuffer scanout did not select written page 0"
                    )

                return True
            except GPUDeviceLostError:
                raise
            except Exception as e:
                if _backend == "kms-framebuffer":
                    _drmdumblastpresenterror = (
                        f"{type(e).__name__}: {e}"
                    )
                log(f"> graphics present fb error {e}")
                return False

        return False

    except GPUDeviceLostError:
        raise
    except Exception as e:

        log(f"> graphics present error {e}")
        return False


def presentdirty(x, y, w, h):

    global _IS_FILE_BUFFER, _FILE_MAP, _buffer, _line, _bpp_bytes, _xres, _yres

    try:

        if not _IS_FILE_BUFFER:
            present()
            return

    except GPUDeviceLostError:
        raise
    except Exception:

        present()
        return


    if not _FILE_MAP or not _buffer:
        return


    x0 = int(x)
    y0 = int(y)
    ww = int(w)
    hh = int(h)


    if ww <= 0 or hh <= 0:
        return

    if x0 < 0:
        ww += x0
        x0 = 0

    if y0 < 0:
        hh += y0
        y0 = 0

    if x0 + ww > _xres:
        ww = _xres - x0

    if y0 + hh > _yres:
        hh = _yres - y0

    if ww <= 0 or hh <= 0:
        return


    locked = lockbuffer(_FILE_FD, exclusive=True)

    try:

        if x0 == 0 and y0 == 0 and ww == _xres and hh == _yres:
            _FILE_MAP.seek(0)
            _FILE_MAP.write(_buffer)

        else:
            rowbytes = int(ww) * int(_bpp_bytes)
            row = 0

            while row < hh:
                sy = y0 + row
                src_off = sy * _line + (x0 * _bpp_bytes)
                dst_off = sy * _line + (x0 * _bpp_bytes)
                _FILE_MAP.seek(dst_off)
                _FILE_MAP.write(_buffer[src_off:src_off + rowbytes])
                row += 1

        if FILEBUFFERFLUSH:
            _FILE_MAP.flush()

    finally:

        if locked:
            unlockbuffer(_FILE_FD)

def panflush():

    global _pan_idx


    buf = bytearray(160)

    fcntl.ioctl(_fd, FBIOGET_VSCREENINFO, buf, True)

    yres    = struct.unpack_from('<I', buf, 4)[0]
    yoffset = struct.unpack_from('<I', buf, 20)[0]

    if _has_double:

        new_yoff = (_pan_idx * yres) & 0xFFFFFFFF

        struct.pack_into('<I', buf, 20, new_yoff)

        fcntl.ioctl(_fd, FBIOPAN_DISPLAY, buf, True)

        _pan_idx ^= 1

    else:

        fcntl.ioctl(_fd, FBIOPAN_DISPLAY, buf, True)

def getdirty():

    try:

        if _dirtyX0 is None or _dirtyY0 is None or _dirtyX1 is None or _dirtyY1 is None:
            return None

        x0 = int(_dirtyX0)
        y0 = int(_dirtyY0)
        x1 = int(_dirtyX1)
        y1 = int(_dirtyY1)

        if x1 <= x0 or y1 <= y0:
            return None

        return (x0, y0, x1 - x0, y1 - y0)

    except Exception:

        return None

def resetdirty():

    global _dirtyX0, _dirtyY0, _dirtyX1, _dirtyY1

    _dirtyX0 = _xres
    _dirtyY0 = _yres
    _dirtyX1 = 0
    _dirtyY1 = 0

    if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] resetdirty -> x0={_dirtyX0} y0={_dirtyY0} x1={_dirtyX1} y1={_dirtyY1}", flush=True)


def markdirty(x0, y0, x1, y1):

    global _dirtyX0, _dirtyY0, _dirtyX1, _dirtyY1

    if _dirtyX0 is None:

        if _DEBUG_GRAPHICS: log(f"{timestamp()} [graphics] markdirty called before resetdirty; initializing", flush=True)

        resetdirty()

    if x0 < _dirtyX0: _dirtyX0 = x0
    if y0 < _dirtyY0: _dirtyY0 = y0
    if x1 > _dirtyX1: _dirtyX1 = x1
    if y1 > _dirtyY1: _dirtyY1 = y1



# baseline functions
def baselinehash(data):

    try:

        # calculate deterministic data hash
        return hashlib.sha256(bytes(data)).hexdigest()

    except Exception as e:

        # baseline hash error
        raise RuntimeError(f"baseline hash error {e}")


def baselinefilehash(path):

    try:

        # read complete baseline file
        with open(path, "rb") as f:
            data = f.read()

        # calculate deterministic file hash
        return baselinehash(data)

    except Exception as e:

        # baseline file hash error
        raise RuntimeError(f"baseline file hash error {e}")


def baselinewrite(path, data):

    try:

        # create baseline directory
        os.makedirs(BASELINEPATH, exist_ok=True)

        # write exact baseline bytes
        with open(path, "wb") as f:
            f.write(data)
            f.flush()

    except PermissionError:

        # baseline write permission error
        raise RuntimeError(f"baseline write permission denied {path}")

    except Exception as e:

        # baseline write error
        raise RuntimeError(f"baseline write error {e}")


def baselineclose():

    global _fd, _map, _FILE_FD, _FILE_MAP, _IS_FILE_BUFFER

    try:

        # close framebuffer mapping
        if _map is not None:
            _map.close()

    except Exception:
        pass

    try:

        # close framebuffer descriptor
        if _fd is not None:
            os.close(_fd)

    except Exception:
        pass

    try:

        # close file-buffer mapping
        if _FILE_MAP is not None:
            _FILE_MAP.close()

    except Exception:
        pass

    try:

        # close file-buffer descriptor
        if _FILE_FD is not None:
            os.close(_FILE_FD)

    except Exception:
        pass

    # clear closed state
    _fd = None
    _map = None
    _FILE_FD = None
    _FILE_MAP = None
    _IS_FILE_BUFFER = False


def baselinesetup(name, width, height, value=0):

    try:

        # close the previous baseline surface
        baselineclose()

        # build exact baseline path
        path = os.path.join(BASELINEPATH, name)

        # create initial surface bytes
        size = int(width) * int(height) * 4
        data = bytes((int(value) & 0xFF,)) * size

        baselinewrite(path, data)

        # initialise current graphics file-buffer mode
        initbuffer(path, int(width), int(height))

        if _buffer is None or len(_buffer) != size:
            raise RuntimeError("baseline surface did not initialise")

        return path

    except Exception as e:

        # baseline setup error
        raise RuntimeError(f"baseline setup error {e}")


def baselinepixel(x, y):

    try:

        # calculate pixel offset
        offset = int(y) * int(_line) + int(x) * int(_bpp_bytes)

        # decode current buffer pixel
        return list(unpackrgb(_buffer[offset:offset + _bpp_bytes]))

    except Exception as e:

        # baseline pixel error
        raise RuntimeError(f"baseline pixel error {e}")


def baselinefilepixel(path, width, x, y):

    try:

        # read BGRA file pixel
        with open(path, "rb") as f:
            f.seek((int(y) * int(width) + int(x)) * 4)
            pixel = f.read(4)

        if len(pixel) != 4:
            raise RuntimeError("short pixel")

        return [int(pixel[2]), int(pixel[1]), int(pixel[0]), int(pixel[3])]

    except Exception as e:

        # baseline file pixel error
        raise RuntimeError(f"baseline file pixel error {e}")


def baselinepack(color):

    try:

        # use current framebuffer channel layout
        return packrgb(normalisecolor(color))

    except Exception as e:

        # baseline pack error
        raise RuntimeError(f"baseline pack error {e}")


def baselineprimitives():

    global CURSORS

    # create 32-bit baseline surface
    path = baselinesetup("primitives.raw", 64, 48)

    # establish deterministic background and shapes
    clear((4, 8, 12))
    drawrect(-3, -2, 18, 15, (250, 10, 20))
    fillrect(5, 6, 13, 9, (20, 180, 40))
    drawline(-7, 44, 69, 2, (210, 120, 50))
    drawcircle(33, 23, 10, (80, 120, 250))
    fillcircle(50, 33, 7, (190, 30, 160))
    fillrectfast(58, 40, 10, 10, (17, 33, 65))

    # install deterministic cursor pixels
    CURSORS["baseline"] = {
        "w": 3,
        "h": 3,
        "stride": 12,
        "data": bytes((
            0, 0, 255, 255, 0, 255, 0, 128, 255, 0, 0, 0,
            255, 255, 255, 64, 0, 0, 0, 255, 0, 255, 255, 192,
            10, 20, 30, 255, 70, 80, 90, 128, 100, 110, 120, 255,
        )),
    }

    drawcursor(1, 1, "baseline")

    # capture dirty state and present complete surface
    dirty = getdirty()
    present()

    result = {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "dirty": list(dirty) if dirty is not None else None,
        "samples": {
            "background": baselinepixel(63, 0),
            "cursoropaque": baselinepixel(1, 1),
            "cursoralpha": baselinepixel(2, 1),
            "rectangle": baselinepixel(6, 8),
            "circle": baselinepixel(50, 33),
            "clipped": baselinepixel(63, 47),
        },
    }

    # remove deterministic cursor resource
    CURSORS.pop("baseline", None)

    return result


def baselinepartial():

    # create nonzero file and zero software backbuffer
    path = baselinesetup("partial.raw", 24, 18, value=113)

    resetdirty()

    # draw one region and present only that region
    fillrectfast(7, 5, 9, 6, (1, 2, 3))

    dirty = getdirty()

    presentdirty(7, 5, 9, 6)

    return {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "dirty": list(dirty) if dirty is not None else None,
        "inside": baselinefilepixel(path, 24, 8, 6),
        "outside": baselinefilepixel(path, 24, 1, 1),
    }


def baselineblit():

    # create patterned source surface
    sourcepath = os.path.join(BASELINEPATH, "source.raw")
    source = bytearray()

    for y in range(12):

        for x in range(16):

            b = (x * 13 + y * 3) & 0xFF
            g = (x * 5 + y * 17) & 0xFF
            r = (x * 19 + y * 7) & 0xFF

            source.extend((b, g, r, 255))

    baselinewrite(sourcepath, source)

    # create destination and exercise both blit implementations
    path = baselinesetup("blit.raw", 32, 24)

    clear((2, 4, 6))
    resetdirty()

    blitfilepart(sourcepath, 16, 2, 2, 6, 5, 3, 4, "BGRA32")
    blitfilepartfast(sourcepath, 16, 0, 0, 10, 8, -2, 14, "BGRA32")

    dirty = getdirty()

    present()

    return {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "sourcehash": baselinefilehash(sourcepath),
        "dirty": list(dirty) if dirty is not None else None,
        "samples": {
            "slow": baselinepixel(3, 4),
            "fast": baselinepixel(0, 14),
            "background": baselinepixel(31, 23),
        },
    }


def baselinetext():

    global TTFFACES, TTFGLYPHS, TTFADVANCES, ADVCACHE, _ttfface, _ttffacepath

    if not os.path.exists(BASELINEFONT):
        raise RuntimeError(f"baseline font missing {BASELINEFONT}")

    # clear font state for deterministic cache results
    TTFFACES.clear()
    TTFGLYPHS.clear()
    TTFADVANCES.clear()
    ADVCACHE.clear()
    _ttfface = None
    _ttffacepath = None

    # create text surface
    path = baselinesetup("text.raw", 160, 48)

    clear((9, 11, 15))
    resetdirty()

    # render normal and clipped text
    drawtextttf(2, 2, "T1OS Ag", 0xE0C080, 18, fontpath=BASELINEFONT)
    drawtextttf(-4, 25, "clip", 0x40A0F0, 12, fontpath=BASELINEFONT)

    width = measuretext("T1OS Ag", 18, fontpath=BASELINEFONT)
    linebox = ttflinebox(18, fontpath=BASELINEFONT)
    dirty = getdirty()

    present()

    return {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "dirty": list(dirty) if dirty is not None else None,
        "width": int(width),
        "linebox": list(linebox),
        "glyphs": int(len(TTFGLYPHS)),
    }


def baselinetextquality():

    global TTFFACES, TTFGLYPHS, TTFADVANCES, ADVCACHE, _ttfface, _ttffacepath

    cambria = "/the one/resources/fonts/cambria.ttf"

    if not os.path.exists(BASELINEFONT):
        raise RuntimeError(f"text-quality font missing {BASELINEFONT}")

    if not os.path.exists(cambria):
        raise RuntimeError(f"text-quality control font missing {cambria}")

    # Begin with cold caches so the resulting native-resolution fixture is
    # independent of earlier diagnostic ordering.
    TTFFACES.clear()
    TTFGLYPHS.clear()
    TTFADVANCES.clear()
    ADVCACHE.clear()
    _ttfface = None
    _ttffacepath = None

    path = baselinesetup("text-quality.raw", 1024, 416)
    clear((0, 0, 0))
    resetdirty()

    backgrounds = (
        ((0, 0, 0), 0xEFEFEF),
        ((255, 255, 255), 0x202020),
        ((96, 96, 96), 0xF4F4F4),
        ((24, 64, 96), 0xF0D080),
    )
    sizes = (12, 16, 20, 24, 32, 48, 64)
    sample = "Ag0O1Il"
    y = 4

    for size in sizes:

        rowheight = max(32, int(size) + 12)

        for column, value in enumerate(backgrounds):

            background, foreground = value
            x = int(column) * 256
            fillrectfast(x, y - 4, 256, rowheight, background)
            drawtextttf(x + 8, y, sample, foreground, int(size), fontpath=BASELINEFONT)

        y += rowheight

    # Cambria remains a branding control and deliberately uses its existing
    # light-hinting path rather than Atkinson's native static-TTF policy.
    fillrectfast(0, 340, 1024, 76, (0, 0, 0))
    drawtextttf(16, 346, "The One OS", 0xEFEFEF, 48, fontpath=cambria)

    dirty = getdirty()
    present()
    lightcoverage = int(TEXTLIGHTCOVERAGE[128])
    darkresult = 255 - int(TEXTDARKCOVERAGE[128])

    if abs(lightcoverage - darkresult) > 2:
        raise RuntimeError(f"text gamma coverage is asymmetric {lightcoverage}/{darkresult}")

    if ttfloadflags(BASELINEFONT) != FT_LOAD_DEFAULT:
        raise RuntimeError("Atkinson text-quality fixture did not use native TrueType hinting")

    if ttfloadflags(cambria) != FT_LOAD_T1OS_TEXT:
        raise RuntimeError("Cambria text-quality fixture changed its branding hinting policy")

    return {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "dirty": list(dirty) if dirty is not None else None,
        "resolution": [1024, 416],
        "sizes": list(sizes),
        "backgrounds": [list(value[0]) for value in backgrounds],
        "sample": sample,
        "gamma": {
            "value": float(TEXTGAMMA),
            "light_coverage_128": lightcoverage,
            "dark_result_128": darkresult,
        },
        "atkinson_hinting": "native",
        "cambria_hinting": "light",
    }


def baselinetextfaces():

    global TTFFACES, TTFGLYPHS, TTFADVANCES, ADVCACHE, _ttfface, _ttffacepath

    alternate = "/the one/resources/fonts/cambria.ttf"

    for fontpath in (BASELINEFONT, alternate):

        if not os.path.exists(fontpath):
            raise RuntimeError(f"font-face cache fixture missing {fontpath}")

    TTFFACES.clear()
    TTFGLYPHS.clear()
    TTFADVANCES.clear()
    ADVCACHE.clear()
    _ttfface = None
    _ttffacepath = None

    path = baselinesetup("text-faces.raw", 256, 96)
    clear((0, 0, 0))
    resetdirty()
    sample = "Ag0O1Ilwm"

    initttffont(BASELINEFONT, 30)
    drawtextttf(4, 4, sample, 0xEFEFEF, 30)
    first = hashlib.sha256(bytes(_buffer[:48 * _line])).hexdigest()

    initttffont(alternate, 30)
    drawtextttf(4, 52, sample, 0xEFEFEF, 30)
    second = hashlib.sha256(bytes(_buffer[48 * _line:96 * _line])).hexdigest()
    fontkeys = sorted({str(key[0]) for key in TTFGLYPHS})

    if BASELINEFONT not in fontkeys or alternate not in fontkeys:
        raise RuntimeError(f"default-face glyph cache did not retain distinct font identities {fontkeys}")

    if first == second:
        raise RuntimeError("default-face glyph cache reused one rendered face for two installed fonts")

    present()

    return {
        "bufferhash": baselinehash(_buffer),
        "filehash": baselinefilehash(path),
        "fontkeys": fontkeys,
        "sample": sample,
        "rowhashes": [first, second],
    }


def baseline565():

    global _buffer, _xres, _yres, _yvirt, _bpp, _bpp_bytes, _line, _size
    global _roff, _rlen, _goff, _glen, _boff, _blen, _aoff, _alen
    global _pack, _packint, _unpack, _IS_FILE_BUFFER

    # close file-backed baseline state
    baselineclose()

    # configure in-memory RGB565 framebuffer state
    _xres = 31
    _yres = 19
    _yvirt = 19
    _bpp = 16
    _bpp_bytes = 2
    _line = _xres * _bpp_bytes
    _size = _line * _yres
    _buffer = bytearray(_size)
    _IS_FILE_BUFFER = False

    _roff = 11
    _rlen = 5
    _goff = 5
    _glen = 6
    _boff = 0
    _blen = 5
    _aoff = 0
    _alen = 0

    packer = struct.Struct("<H")
    _packint = packer.pack
    _unpack = packer.unpack
    _pack = baselinepack

    resetdirty()

    # exercise 16-bit packing, blending and clipping
    clear((3, 7, 11))
    fillrect(-2, 2, 11, 8, (250, 120, 30))
    drawline(0, 18, 30, 0, (20, 200, 245))
    drawcircle(17, 10, 6, (180, 40, 210))

    dirty = getdirty()

    return {
        "bufferhash": baselinehash(_buffer),
        "dirty": list(dirty) if dirty is not None else None,
        "samples": {
            "background": baselinepixel(30, 18),
            "rectangle": baselinepixel(2, 4),
            "line": baselinepixel(15, 9),
        },
    }


def baselinecleanup():

    # close all active mappings before removing files
    baselineclose()

    paths = (
        "primitives.raw",
        "partial.raw",
        "source.raw",
        "blit.raw",
        "text.raw",
        "text-faces.raw",
    )

    for name in paths:

        path = os.path.join(BASELINEPATH, name)

        try:

            # remove temporary baseline file
            if os.path.exists(path):
                os.remove(path)

        except Exception:
            pass

    try:

        # remove empty baseline directory
        os.rmdir(BASELINEPATH)

    except Exception:
        pass


def graphicsbaseline():

    result = {
        "format": 1,
        "passed": True,
        "contract": {},
        "metrics": {},
        "errors": [],
    }

    cases = (
        ("primitives32", baselineprimitives),
        ("partialpresent32", baselinepartial),
        ("blit32", baselineblit),
        ("text32", baselinetext),
        ("textquality32", baselinetextquality),
        ("textfaces32", baselinetextfaces),
        ("rgb565", baseline565),
    )

    try:

        # execute each deterministic baseline case
        for name, case in cases:

            started = time.monotonic()

            try:

                result["contract"][name] = case()

            except Exception as e:

                # record case failure
                result["passed"] = False
                result["errors"].append(f"{name}: {e}")

            elapsed = (time.monotonic() - started) * 1000.0
            result["metrics"][name] = round(elapsed, 3)

    finally:

        # clean all temporary baseline state
        baselinecleanup()

    return result


def baselinecommand():

    try:

        # run baseline and print machine-readable result
        result = graphicsbaseline()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))

        if result.get("passed"):
            return 0

        return 1

    except Exception as e:

        # print machine-readable command failure
        result = {
            "format": 1,
            "passed": False,
            "contract": {},
            "metrics": {},
            "errors": [f"baseline command: {e}"],
        }

        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1



# direct execution
if __name__ == "__main__":

    if len(sys.argv) > 1 and sys.argv[1] == "baseline":
        raise SystemExit(baselinecommand())

    if len(sys.argv) > 1 and sys.argv[1] == "opengl":
        raise SystemExit(openglcommand())
