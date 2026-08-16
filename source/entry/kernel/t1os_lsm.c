// SPDX-License-Identifier: GPL-2.0-only
/*
 * t1os_lsm.c  —  The One OS LSM module (t1os)
 *
 * Enforces per-process security domains, protected-path rules, module-loader
 * ownership, and signal boundaries in the kernel.  Python service identity is
 * assigned by a trusted launcher using an open script descriptor and never by
 * inspecting userspace argv.
 *
 * Only specific immutable domains may write core paths.  There is no ambient
 * role-file or first-run bypass; bootstrap uses the same Startup ACL.
 */

#include <linux/init.h>
#include <linux/module.h>
#include <linux/security.h>
#include <linux/lsm_hooks.h>
#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/dcache.h>
#include <linux/ctype.h>
#include <linux/mount.h>
#include <linux/mman.h>
#include <uapi/linux/mount.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/sched/coredump.h>
#include <linux/binfmts.h>
#include <linux/mm.h>
#include <linux/uaccess.h>
#include <linux/kernel_read_file.h>
#include <linux/file.h>
#include <linux/cred.h>
#include <linux/capability.h>
#include <linux/ptrace.h>
#include <linux/user_namespace.h>
#include <uapi/linux/lsm.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("slayer");
MODULE_DESCRIPTION("T1OS LSM: descriptor-bound process domains and fail-closed runtime policy");

/* ------------------------------------------------------------------ */
/*  Policy arrays (restored to original)                              */
/* ------------------------------------------------------------------ */

static const char *prot_nonrec[] = {
	"/software",
	"/master",
	"/the one",
	"/.rubbish",
	"/.remainder",
	"/the one/settings",
	"/the one/logs",
	"/the one/resources",
	"/the one/drivers",
};

static const char *prot_rec[] = {
	"/boot",
	"/the one/master",
	"/the one/build",
	"/the one/software",
	"/the one/catalogue",
};

/* Conventional Linux filesystem roots are not part of the T1OS runtime.
 * The pre-T1OS initramfs is intentionally out of scope; PID 1 activates this
 * guard only when it executes the T1OS Python entry after switch_root. */
static const char *forbidden_runtime_roots[] = {
	"/bin", "/sbin", "/lib", "/lib64", "/usr", "/etc",
	"/dev", "/proc", "/sys", "/run", "/var", "/tmp",
	"/home", "/root", "/media", "/mnt", "/opt", "/srv",
};

/* One-way boot boundary. A plain flag is required here: path hooks can run
 * while VFS directory locks are held and therefore must never perform a
 * nested pathname lookup to detect the real root. */
static bool t1os_runtime_active;


enum t1os_domain {
	T1OS_DOMAIN_UNTRUSTED = 0,
	T1OS_DOMAIN_GODDESS = 1,
	T1OS_DOMAIN_STARTUP = 2,
	T1OS_DOMAIN_ARCHITECT_HELPER = 3,
	T1OS_DOMAIN_OPERATIONS = 4,
	T1OS_DOMAIN_PROCEDURES = 5,
	T1OS_DOMAIN_WINDOW = 6,
	T1OS_DOMAIN_BRICK = 7,
	T1OS_DOMAIN_AUDIO = 8,
	T1OS_DOMAIN_DRIVER = 9,
	T1OS_DOMAIN_INPUT = 10,
	T1OS_DOMAIN_NETWORK = 11,
	T1OS_DOMAIN_REIGN = 12,
	T1OS_DOMAIN_PYTHON_SERVICE = 13,
	T1OS_DOMAIN_EXCHANGE = 14,
	T1OS_DOMAIN_EXPANSE = 15,
	T1OS_DOMAIN_VIRTUALBOX = 16,
	T1OS_DOMAIN_BOOT_ANIMATION = 17,
	T1OS_DOMAIN_DESKTOP = 18,
	T1OS_DOMAIN_VIDEO = 19,
	T1OS_DOMAIN_SETTINGS = 20,
	T1OS_DOMAIN_MAINTENANCE = 21,
	T1OS_DOMAIN_MODULE_LOADER = 22,
	T1OS_DOMAIN_SNAP = 23,
	T1OS_DOMAIN_CHROMIUM = 24,
	T1OS_DOMAIN_PICKER = 25,
	T1OS_DOMAIN_LOCKSCREEN = 26,
};

struct t1os_task_security {
	u16 domain;
	u16 pending_domain;
	dev_t pending_device;
	unsigned long pending_inode;
	dev_t pending_interpreter_device;
	unsigned long pending_interpreter_inode;
	bool pending;
};

enum t1os_exec_state {
	T1OS_EXEC_NONE = 0,
	T1OS_EXEC_SCRIPT,
	T1OS_EXEC_READY,
};

enum t1os_cred_class {
	T1OS_CRED_ROOT = 0,
	T1OS_CRED_UNPRIVILEGED,
	T1OS_CRED_CHROMIUM,
	T1OS_CRED_CHROMIUM_SANDBOX,
};

struct t1os_cred_security {
	u16 domain;
	u8 state;
	u8 cred_class;
	dev_t interpreter_device;
	unsigned long interpreter_inode;
};

static struct lsm_blob_sizes t1os_blob_sizes __ro_after_init = {
	.lbs_task = sizeof(struct t1os_task_security),
	.lbs_cred = sizeof(struct t1os_cred_security),
};

#define T1OS_PR_SET_DOMAIN       0x54510001
#define LSM_ID_T1OS_LOCAL        114
#define T1OS_RTC_RD_TIME          0x80247009U
#define T1OS_RTC_SET_TIME         0x4024700aU

/* ------------------------------------------------------------------ */
/*  Script path constants (adjust if your install paths differ)       */
/* ------------------------------------------------------------------ */

#define T1OS_STARTUP_SCRIPT          "/the one/build/startup/startup.py"
#define T1OS_ARCHITECT_SCRIPT        "/the one/build/architect/architect.py"
#define T1OS_GODDESS_SCRIPT          "/the one/build/GODDESS/GODDESS.py"
#define T1OS_OPERATIONSSERVER_SCRIPT "/the one/build/operations/operationsserver.py"
#define T1OS_OPERATIONS_SCRIPT       "/the one/build/operations/operations.py"
#define T1OS_PROCEDURES_SCRIPT       "/the one/build/procedures/procedures.py"
#define T1OS_WINDOWSERVER_SCRIPT     "/the one/build/windows/windowserver.py"
#define T1OS_BRICK_SCRIPT            "/the one/build/brick/brick.py"
#define T1OS_AUDIOSERVER_SCRIPT      "/the one/build/audio/audioserver.py"
#define T1OS_DRIVERSERVER_SCRIPT     "/the one/build/drivers/driverserver.py"
#define T1OS_PLAYER_SCRIPT           "/the one/build/player/player.py"
#define T1OS_MEDIA_SCRIPT            "/the one/build/media/media.py"
#define T1OS_PYTHON_BINARY           "/the one/software/python/bin/python"
#define T1OS_FFMPEG_BINARY           "/the one/software/audio/ffmpeg"
#define T1OS_FFPROBE_BINARY          "/the one/software/audio/ffprobe"
#define T1OS_VIDEO_DECODER_BINARY    "/the one/software/audio/t1-video-decode"
#define T1OS_MEDIA_DECODER_DAEMON    "/the one/software/audio/t1-media-decoderd"
#define T1OS_CHROMIUM_BINARY         "/the one/software/chromium/program/chrome"
#define T1OS_CHROMIUM_SANDBOX        "/the one/software/chromium/program/chrome-sandbox"
#define T1OS_CHROMIUM_XSERVER        "/the one/software/chromium/tools/Xvfb"
#define T1OS_CHROMIUM_WINDOWMANAGER  "/the one/software/chromium/tools/matchbox-window-manager"
#define T1OS_CHROMIUM_T1_WINDOWMANAGER "/the one/software/chromium/tools/t1os-xwm"
#define T1OS_CHROMIUM_INPUT_BRIDGE   "/the one/software/chromium/tools/t1os-xinput"
#define T1OS_CHROMIUM_SUBPROCESS     "/the one/software/chromium/tools/t1os-chrome-subprocess"
#define T1OS_CHROMIUM_DASH           "/the one/software/chromium/tools/dash"
#define T1OS_CHROMIUM_XCLIP          "/the one/software/chromium/tools/xclip"
#define T1OS_CHROMIUM_XDOTOOL        "/the one/software/chromium/tools/xdotool"
#define T1OS_CHROMIUM_XKBCOMP        "/the one/software/chromium/tools/xkbcomp"
#define T1OS_CHROMIUM_XRANDR         "/the one/software/chromium/tools/xrandr"
#define T1OS_WIRELESS_ENGINE         "/the one/software/network/wireless-engine"
#define T1OS_MODPROBE_BINARY         "/the one/drivers/tools/modprobe"
#define T1OS_LOCKSCREEN_SCRIPT       "/the one/build/lock screen/lock screen.py"
#define T1OS_BOOTANIM_SCRIPT         "/boot/boot animation/boot animation.py"
#define T1OS_VIRTUALBOX_CLIENT       "/the one/software/virtualbox/VBoxDRMClient"
#define T1OS_VIRTUALBOX_CLIPBOARD    "/the one/software/virtualbox/VBoxT1Clipboard"
#define T1OS_VIRTUALBOX_SERVICE      "/the one/software/virtualbox/VBoxT1Service"
#define T1OS_NETWORK_SCRIPT          "/the one/build/network/network.py"
#define T1OS_REIGN_SCRIPT            "/the one/build/reign/reign.py"
#define T1OS_PYTHON_SERVICE_SCRIPT   "/the one/build/python/python.py"
#define T1OS_INPUT_SCRIPT            "/the one/build/input/inputserver.py"
#define T1OS_EXCHANGE_SCRIPT         "/the one/build/exchange/exchange.py"
#define T1OS_EXPANSE_SCRIPT          "/the one/build/expanse/expanse.py"
#define T1OS_VIRTUALBOX_SCRIPT       "/the one/software/virtualbox/guestadditions.py"
#define T1OS_SETTINGS_SCRIPT         "/the one/build/settings/settings.py"
#define T1OS_ARRAY_SCRIPT            "/the one/build/array/array.py"
#define T1OS_CALCULATOR_SCRIPT       "/the one/build/calculator/calculator.py"
#define T1OS_OPERATIONSCENTRE_SCRIPT "/the one/build/operations/operationscentre.py"
#define T1OS_CHROMIUM_SCRIPT         "/the one/build/chromium/chromium.py"
#define T1OS_SNAP_SCRIPT             "/the one/build/snap/snap.py"
#define T1OS_VIEWER_SCRIPT           "/the one/build/viewer/viewer.py"
#define T1OS_WRITE_SCRIPT            "/the one/build/write/write.py"
#define T1OS_PICKER_SCRIPT           T1OS_ARRAY_SCRIPT

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

static struct t1os_task_security *t1os_task(const struct task_struct *task)
{
	if (!task || !task->security)
		return NULL;
	return task->security + t1os_blob_sizes.lbs_task;
}

static enum t1os_domain t1os_task_domain(const struct task_struct *task)
{
	struct t1os_task_security *security = t1os_task(task);

	return security ? security->domain : T1OS_DOMAIN_UNTRUSTED;
}

static struct t1os_cred_security *t1os_cred(const struct cred *cred)
{
	if (!cred || !cred->security)
		return NULL;
	return cred->security + t1os_blob_sizes.lbs_cred;
}

static bool t1os_domain_is(enum t1os_domain domain)
{
	return t1os_task_domain(current) == domain;
}

static int t1os_task_alloc(struct task_struct *task, u64 clone_flags)
{
	struct t1os_task_security *source = t1os_task(current);
	struct t1os_task_security *target = t1os_task(task);

	(void)clone_flags;
	if (!target)
		return -ENOMEM;
	target->domain = source ? source->domain : T1OS_DOMAIN_UNTRUSTED;
	/* A transition is one-shot and never crosses fork/clone. */
	target->pending_domain = T1OS_DOMAIN_UNTRUSTED;
	target->pending_device = 0;
	target->pending_inode = 0;
	target->pending_interpreter_device = 0;
	target->pending_interpreter_inode = 0;
	target->pending = false;
	return 0;
}

static bool t1os_domain_valid(unsigned long domain)
{
	return domain <= T1OS_DOMAIN_LOCKSCREEN;
}

static const char *t1os_domain_name(enum t1os_domain domain)
{
	switch (domain) {
	case T1OS_DOMAIN_GODDESS: return "goddess";
	case T1OS_DOMAIN_STARTUP: return "startup";
	case T1OS_DOMAIN_ARCHITECT_HELPER: return "architect";
	case T1OS_DOMAIN_OPERATIONS: return "operations";
	case T1OS_DOMAIN_PROCEDURES: return "procedures";
	case T1OS_DOMAIN_WINDOW: return "window";
	case T1OS_DOMAIN_BRICK: return "brick";
	case T1OS_DOMAIN_AUDIO: return "audio";
	case T1OS_DOMAIN_DRIVER: return "driver";
	case T1OS_DOMAIN_INPUT: return "input";
	case T1OS_DOMAIN_NETWORK: return "network";
	case T1OS_DOMAIN_REIGN: return "reign";
	case T1OS_DOMAIN_PYTHON_SERVICE: return "python";
	case T1OS_DOMAIN_EXCHANGE: return "exchange";
	case T1OS_DOMAIN_EXPANSE: return "expanse";
	case T1OS_DOMAIN_VIRTUALBOX: return "virtualbox";
	case T1OS_DOMAIN_BOOT_ANIMATION: return "boot-animation";
	case T1OS_DOMAIN_DESKTOP: return "desktop";
	case T1OS_DOMAIN_VIDEO: return "video";
	case T1OS_DOMAIN_SETTINGS: return "settings";
	case T1OS_DOMAIN_MAINTENANCE: return "maintenance";
	case T1OS_DOMAIN_MODULE_LOADER: return "module-loader";
	case T1OS_DOMAIN_SNAP: return "snap";
	case T1OS_DOMAIN_CHROMIUM: return "chromium";
	case T1OS_DOMAIN_PICKER: return "picker";
	case T1OS_DOMAIN_LOCKSCREEN: return "lockscreen";
	default: return "untrusted";
	}
}

/*
 * d_path() renders an executable outside the caller's chroot as
 * "(unreachable)/path". Chromium's setuid sandbox intentionally chroots its
 * zygote into an empty directory while the zygote continues to execute the
 * measured, open Chrome image. Preserve that file-backed identity across the
 * confinement boundary; the prefix is generated by the VFS, not argv.
 */
static bool t1os_executable_path_matches(const char *path, const char *target)
{
	static const char unreachable[] = "(unreachable)";

	if (!strcmp(path, target))
		return true;

	return !strncmp(path, unreachable, sizeof(unreachable) - 1) &&
	       !strcmp(path + sizeof(unreachable) - 1, target);
}

static bool t1os_unreachable_path(const char *path)
{
	static const char prefix[] = "(unreachable)";

	return path && !strncmp(path, prefix, sizeof(prefix) - 1);
}

/* Identify native services by their executed image, not by spoofable argv. */
static bool t1os_is_executable_process(const char *target)
{
	struct mm_struct *mm = current->mm;
	struct file *exe;
	char *tmp, *name;
	bool matched = false;

	if (!mm)
		return false;

	exe = get_mm_exe_file(mm);
	if (!exe)
		return false;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (tmp) {
		name = d_path(&exe->f_path, tmp, PAGE_SIZE);
		if (!IS_ERR(name))
			matched = t1os_executable_path_matches(name, target);
		free_page((unsigned long)tmp);
	}

	fput(exe);
	return matched;
}

static bool t1os_is_startup_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_STARTUP);
}

static bool t1os_is_goddess_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_GODDESS);
}

static bool t1os_is_operationsserver_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_OPERATIONS);
}

static bool t1os_is_procedures_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_PROCEDURES);
}

static bool t1os_is_windowserver_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_WINDOW);
}

static bool t1os_is_brick_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_BRICK);
}

static bool t1os_is_audioserver_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_AUDIO);
}

static bool t1os_is_network_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_NETWORK);
}

static bool t1os_is_driverserver_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_DRIVER);
}

static bool t1os_is_video_client_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_VIDEO) ||
	       t1os_is_executable_process(T1OS_VIDEO_DECODER_BINARY);
}

static bool t1os_is_media_decoder_daemon_process(void)
{
	return t1os_is_executable_process(T1OS_MEDIA_DECODER_DAEMON);
}

static bool t1os_is_chromium_engine_process(void)
{
	return t1os_is_executable_process(T1OS_CHROMIUM_BINARY) ||
	       t1os_is_executable_process(T1OS_CHROMIUM_SANDBOX) ||
	       t1os_is_executable_process(T1OS_CHROMIUM_XSERVER) ||
	       t1os_is_executable_process(T1OS_CHROMIUM_WINDOWMANAGER);
}

static bool t1os_is_chromium_uvm_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_CHROMIUM) &&
	       t1os_is_executable_process(T1OS_CHROMIUM_BINARY);
}

static bool t1os_is_wireless_engine_process(void)
{
	return t1os_is_executable_process(T1OS_WIRELESS_ENGINE);
}

static bool t1os_is_virtualbox_resize_process(void)
{
	return t1os_is_executable_process(T1OS_VIRTUALBOX_CLIENT);
}

static bool t1os_is_virtualbox_clipboard_process(void)
{
	return t1os_is_executable_process(T1OS_VIRTUALBOX_CLIPBOARD);
}

static bool t1os_is_virtualbox_service_process(void)
{
	return t1os_is_executable_process(T1OS_VIRTUALBOX_SERVICE);
}

static bool t1os_is_virtualbox_process(void)
{
	return t1os_is_virtualbox_resize_process() ||
	       t1os_is_virtualbox_clipboard_process() ||
	       t1os_is_virtualbox_service_process();
}

static bool t1os_is_lockscreen_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_LOCKSCREEN);
}

static bool t1os_is_bootanim_process(void)
{
	return t1os_domain_is(T1OS_DOMAIN_BOOT_ANIMATION);
}

/* ------------------------------------------------------------------ */
/*  Generic path check (original behaviour)                           */
/* ------------------------------------------------------------------ */

static bool t1os_check_path(const char *path)
{
	int i;

	/* exact match blocked for master role */
	for (i = 0; i < ARRAY_SIZE(prot_nonrec); i++) {
		if (!strcmp(path, prot_nonrec[i]))
			return false;
	}

	/* recursive prefixes blocked for master role */
	for (i = 0; i < ARRAY_SIZE(prot_rec); i++) {
		size_t plen = strlen(prot_rec[i]);

		if (!strcmp(path, prot_rec[i]))
			return false;

		if (!strncmp(path, prot_rec[i], plen) &&
		    path[plen] == '/')
			return false;
	}

	return true;
}

static bool t1os_runtime_root_active(void)
{
	return READ_ONCE(t1os_runtime_active);
}

static bool t1os_is_forbidden_runtime_path(const char *path)
{
	int i;

	if (!t1os_runtime_root_active())
		return false;

	for (i = 0; i < ARRAY_SIZE(forbidden_runtime_roots); i++) {
		size_t len = strlen(forbidden_runtime_roots[i]);

		if (!strcmp(path, forbidden_runtime_roots[i]))
			return true;
		if (!strncmp(path, forbidden_runtime_roots[i], len) &&
		    path[len] == '/')
			return true;
	}

	return false;
}

/* ------------------------------------------------------------------ */
/*  Special write ACL for key paths (your table)                      */
/* ------------------------------------------------------------------ */

static bool t1os_is_graphics_recovery_marker(const char *path);
static bool t1os_is_efi_bootnext(const char *path);
static int t1os_file_path(struct file *file, char *buffer, char **resolved);

static bool t1os_is_brick_diagnostic_path(const char *path)
{
	static const char root[] = "/.ephemeral/brick";

	return path &&
	       (!strcmp(path, root) ||
		(!strncmp(path, root, sizeof(root) - 1) &&
		 path[sizeof(root) - 1] == '/'));
}

static bool t1os_is_operations_runtime_path(const char *path)
{
	static const char root[] = "/.ephemeral/operations";

	return path &&
	       (!strcmp(path, root) ||
	       (!strncmp(path, root, sizeof(root) - 1) &&
		 path[sizeof(root) - 1] == '/'));
}

static bool t1os_is_expanse_runtime_path(const char *path)
{
	static const char root[] = "/.ephemeral/expanse";

	return path &&
	       (!strcmp(path, root) ||
		(!strncmp(path, root, sizeof(root) - 1) &&
		 path[sizeof(root) - 1] == '/'));
}

static bool t1os_is_python_management_path(const char *path)
{
	static const char root[] = "/the one/software/python/.t1pip";

	return path &&
	       (!strcmp(path, root) ||
		(!strncmp(path, root, sizeof(root) - 1) &&
		 path[sizeof(root) - 1] == '/'));
}

/* /.ephemeral is a boot-scoped tmpfs scratch tier, not an authority boundary.
 * DAC ownership and modes still apply, but this LSM must never prevent an
 * ordinary read, write, metadata operation, or executable mapping anywhere in
 * the tier.  Mounting or replacing the tier remains separately restricted by
 * the mount hooks below. */
static bool t1os_is_ephemeral_path(const char *path)
{
	static const char root[] = "/.ephemeral";

	return path &&
	       (!strcmp(path, root) ||
		(!strncmp(path, root, sizeof(root) - 1) &&
		 path[sizeof(root) - 1] == '/'));
}

/* is this path one of the specifically restricted ones? */
static bool t1os_is_special_path(const char *path)
{
	if (t1os_is_ephemeral_path(path))
		return false;

	if (!strcmp(path, "/the one/settings") ||
	    !strcmp(path, "/the one/settings/"))
		return true;

	if (!strcmp(path, "/.ephemeral/authentication") ||
	    !strcmp(path, "/.ephemeral/authentication/") ||
	    !strncmp(path, "/.ephemeral/authentication/", 27))
		return true;
	if (!strcmp(path, "/.ephemeral/network") ||
	    !strcmp(path, "/.ephemeral/network/") ||
	    !strncmp(path, "/.ephemeral/network/", 20))
		return true;
	if (!strcmp(path, "/.ephemeral/windowserver/state") ||
	    !strcmp(path, "/.ephemeral/windowserver/state/") ||
	    !strncmp(path, "/.ephemeral/windowserver/state/", 31))
		return true;
	if (!strcmp(path, "/.ephemeral/lock screen") ||
	    !strcmp(path, "/.ephemeral/lock screen/") ||
	    !strncmp(path, "/.ephemeral/lock screen/", 24))
		return true;
	if (!strcmp(path, "/.ephemeral/media") ||
	    !strcmp(path, "/.ephemeral/media/") ||
	    !strncmp(path, "/.ephemeral/media/", 18))
		return true;
	if (t1os_is_brick_diagnostic_path(path))
		return true;
	if (t1os_is_operations_runtime_path(path))
		return true;
	if (t1os_is_expanse_runtime_path(path))
		return true;
	if (t1os_is_python_management_path(path))
		return true;

	/* Obsolete graphics state may be removed once during an upgraded boot. */
	if (t1os_is_graphics_recovery_marker(path))
		return true;

	/* Exact EFI BootNext aliases for the one-shot recovery reboot. */
	if (t1os_is_efi_bootnext(path))
		return true;

	/* ===== /the one/master ===== */

	/* exact directory, without slash */
	if (!strcmp(path, "/the one/master"))
		return true;

	/* exact directory, with slash */
	if (!strcmp(path, "/the one/master/"))
		return true;

	/* children: /the one/master/... */
	if (!strncmp(path, "/the one/master/", 16))
		return true;

	/* file: /the one/master/master.txt */
	if (!strcmp(path, "/the one/master/master.txt"))
		return true;


	/* ===== /master ===== */

	/* exact directory (without slash) */
	if (!strcmp(path, "/master"))
		return true;

	/* exact directory (with slash) */
	if (!strcmp(path, "/master/"))
		return true;

	/* children: /master/<username>/... */
	if (!strncmp(path, "/master/", 8))
		return true;


	/* ===== /the one/settings/operations ===== */

	/* exact dir without slash */
	if (!strcmp(path, "/the one/settings/operations"))
		return true;

	/* exact dir with slash */
	if (!strcmp(path, "/the one/settings/operations/"))
		return true;

	/* children: /the one/settings/operations/... */
	if (!strncmp(path, "/the one/settings/operations/", 29))
		return true;

	/* ===== /the one/settings/windowserver ===== */

	if (!strcmp(path, "/the one/settings/windowserver"))
		return true;

	if (!strcmp(path, "/the one/settings/windowserver/"))
		return true;

	if (!strncmp(path, "/the one/settings/windowserver/", 31))
		return true;

	/* Ordinary Settings UI state is writable only by the Settings domain. */
	if (!strcmp(path, "/the one/settings/audio") ||
	    !strncmp(path, "/the one/settings/audio/", 24) ||
	    !strcmp(path, "/the one/settings/display") ||
	    !strncmp(path, "/the one/settings/display/", 26) ||
	    !strcmp(path, "/the one/settings/mouse") ||
	    !strncmp(path, "/the one/settings/mouse/", 24) ||
	    !strcmp(path, "/the one/settings/network") ||
	    !strncmp(path, "/the one/settings/network/", 26) ||
	    !strcmp(path, "/the one/settings/master") ||
	    !strncmp(path, "/the one/settings/master/", 25) ||
	    !strcmp(path, "/the one/settings/time") ||
	    !strncmp(path, "/the one/settings/time/", 23) ||
	    !strcmp(path, "/the one/settings/terminal") ||
	    !strncmp(path, "/the one/settings/terminal/", 27) ||
	    !strcmp(path, "/the one/settings/session") ||
	    !strncmp(path, "/the one/settings/session/", 26))
		return true;


	/* ===== /the one/drivers ===== */

	if (!strcmp(path, "/the one/drivers"))
		return true;

	if (!strcmp(path, "/the one/drivers/"))
		return true;

	/* All driver assets and mounted device/state/control trees are governed
	 * by the process-aware ACL below. */
	if (!strncmp(path, "/the one/drivers/", 17))
		return true;


	return false;
}


/* NVIDIA's installer normally relies on udev for these nodes. T1OS does not
 * run udev, so match only the exact flat node names its measured Driver Server
 * creates. No NVIDIA subdirectory or suffix is accepted. */
static bool t1os_is_nvidia_device_node_name(const char *path)
{
	static const char prefix[] = "/the one/drivers/nodes/";
	const char *name;
	const char *digit;

	if (strncmp(path, prefix, sizeof(prefix) - 1))
		return false;

	name = path + sizeof(prefix) - 1;
	if (!strcmp(name, "nvidiactl") ||
	    !strcmp(name, "nvidia-modeset") ||
	    !strcmp(name, "nvidia-uvm"))
		return true;

	if (strncmp(name, "nvidia", 6))
		return false;
	digit = name + 6;
	if (*digit < '0' || *digit > '9')
		return false;
	while (*digit >= '0' && *digit <= '9')
		digit++;
	return *digit == '\0';
}

static bool t1os_is_nvidia_decode_device_node_name(const char *path)
{
	static const char modeset[] =
		"/the one/drivers/nodes/nvidia-modeset";
	static const char uvm[] =
		"/the one/drivers/nodes/nvidia-uvm";

	return t1os_is_nvidia_device_node_name(path) &&
	       strcmp(path, modeset) &&
	       strcmp(path, uvm);
}

static bool t1os_is_nvidia_uvm_device_node_name(const char *path)
{
	return !strcmp(path, "/the one/drivers/nodes/nvidia-uvm");
}

static bool t1os_is_console_device_node_name(const char *path)
{
	static const char prefix[] = "/the one/drivers/nodes/pts/";
	const char *name;

	if (strncmp(path, prefix, sizeof(prefix) - 1))
		return false;

	name = path + sizeof(prefix) - 1;
	if (!strcmp(name, "ptmx"))
		return true;
	if (*name < '0' || *name > '9')
		return false;
	while (*name >= '0' && *name <= '9')
		name++;
	return *name == '\0';
}

static bool t1os_is_console_multiplexer_name(const char *path)
{
	return !strcmp(path, "/the one/drivers/nodes/pts/ptmx");
}


/* Older releases persisted a next-boot framebuffer decision here. The current
 * release never creates it, but PID 1 may remove the exact stale leaf so it
 * cannot influence downgraded tooling or diagnostics. */
static bool t1os_is_graphics_recovery_marker(const char *path)
{
	static const char marker[] =
		"/the one/settings/graphics recovery boot.json";

	return path && !strcmp(path, marker);
}


/* A negative dentry passed to path_mknod() is rendered by d_path() with the
 * exact synthetic suffix " (deleted)" until efivarfs instantiates it. Accept
 * that one VFS spelling as well as the live name; do not use a prefix match
 * which could grant a sibling EFI variable. */
static bool t1os_is_efi_bootnext_name(const char *name)
{
	static const char variable[] =
		"BootNext-8be4df61-93ca-11d2-aa0d-00e098032b8c";
	static const char negative_suffix[] = " (deleted)";
	const size_t variable_len = sizeof(variable) - 1;

	if (strncmp(name, variable, variable_len))
		return false;

	return name[variable_len] == '\0' ||
		!strcmp(name + variable_len, negative_suffix);
}


/* BootNext is the only firmware variable PID 1 may modify. BootCurrent and
 * Boot#### remain read-only inputs, and no other EFI variable receives this
 * exception. */
static bool t1os_is_efi_bootnext(const char *path)
{
	static const char control_prefix[] =
		"/the one/drivers/control/firmware/efi/efivars/";
	static const char sysfs_prefix[] =
		"/sys/firmware/efi/efivars/";
	static const char mount_root_prefix[] =
		"/firmware/efi/efivars/";

	/*
	 * d_path() can report a nested efivarfs file through the T1OS control
	 * mount, through the original sysfs mount, or relative to the sysfs
	 * superblock root depending on which mount was used to instantiate the
	 * file. These are three names for the same exact EFI variable. Keep the
	 * exception exact and do not grant access to any sibling variable.
	 */
	return
		(!strncmp(path, control_prefix, sizeof(control_prefix) - 1) &&
		 t1os_is_efi_bootnext_name(
			 path + sizeof(control_prefix) - 1)) ||
		(!strncmp(path, sysfs_prefix, sizeof(sysfs_prefix) - 1) &&
		 t1os_is_efi_bootnext_name(
			 path + sizeof(sysfs_prefix) - 1)) ||
		(!strncmp(path, mount_root_prefix,
			  sizeof(mount_root_prefix) - 1) &&
		 t1os_is_efi_bootnext_name(
			 path + sizeof(mount_root_prefix) - 1));
}


/*
 * Return true if the CURRENT process is allowed to write this path,
 * according to your table.
 *
 * NOTE: architect "role" itself does NOT automatically allow these;
 * access is granted only if the running process matches the daemon
 * for that path (or the bootstrap exception).
 */
 
static bool t1os_special_write_allowed(const char *path)
{
	static const char dns_temporary[] =
		"/the one/settings/network/dns.txt.temporary-";

	if (t1os_is_ephemeral_path(path))
		return true;
	/* Network owns the generated resolver file and its PID-suffixed atomic
	 * replacement.  It does not receive authority over user-authored interface,
	 * wireless, or certificate settings in the same directory. */
	if ((!strcmp(path, "/the one/settings/network/dns.txt") ||
	     !strncmp(path, dns_temporary, sizeof(dns_temporary) - 1)) &&
	    t1os_is_network_process())
		return true;

	if (!strcmp(path, "/.ephemeral/authentication") ||
	    !strcmp(path, "/.ephemeral/authentication/") ||
	    !strncmp(path, "/.ephemeral/authentication/", 27))
		return t1os_is_startup_process() ||
		       t1os_is_operationsserver_process();
	if (!strcmp(path, "/.ephemeral/network") ||
	    !strcmp(path, "/.ephemeral/network/") ||
	    !strncmp(path, "/.ephemeral/network/", 20))
		return t1os_is_network_process();
	if (!strcmp(path, "/.ephemeral/windowserver/state") ||
	    !strcmp(path, "/.ephemeral/windowserver/state/") ||
	    !strncmp(path, "/.ephemeral/windowserver/state/", 31))
		return t1os_is_windowserver_process() ||
		       t1os_is_goddess_process();
	if (!strcmp(path, "/.ephemeral/lock screen") ||
	    !strcmp(path, "/.ephemeral/lock screen/") ||
	    !strncmp(path, "/.ephemeral/lock screen/", 24))
		return t1os_is_goddess_process() ||
		       t1os_is_startup_process() ||
		       t1os_is_operationsserver_process() ||
		       t1os_is_lockscreen_process();
	/* Media sessions, software-decoded frames and the preload sandbox are
	 * confined to this boot-only private directory.  Player and the measured
	 * decoder need file lifecycle access; GODDESS owns the optional native
	 * daemon socket, and Audio owns its fixed playback control integration. */
	if (!strcmp(path, "/.ephemeral/media") ||
	    !strcmp(path, "/.ephemeral/media/") ||
	    !strncmp(path, "/.ephemeral/media/", 18))
		return t1os_is_goddess_process() ||
		       t1os_is_video_client_process() ||
		       t1os_is_audioserver_process() ||
		       t1os_is_media_decoder_daemon_process();
	/* Brick's self-tests use only these boot-scoped, PID-suffixed scratch
	 * names. No other application domain receives write access to them. */
	if (t1os_is_brick_diagnostic_path(path))
		return t1os_is_brick_process();
	if (t1os_is_operations_runtime_path(path))
		return t1os_is_operationsserver_process();
	/* Expanse owns its boot-scoped icon, surface-staging and search handoff
	 * hierarchy. Other uid-1000 applications share its DAC identity, so the
	 * immutable process domain remains the write boundary. */
	if (t1os_is_expanse_runtime_path(path))
		return t1os_domain_is(T1OS_DOMAIN_EXPANSE);
	/* The measured Python package service is the sole writer of its private
	 * state beneath the otherwise immutable system interpreter tree. */
	if (t1os_is_python_management_path(path))
		return t1os_domain_is(T1OS_DOMAIN_PYTHON_SERVICE);

	if (!strcmp(path, "/the one/settings") ||
	    !strcmp(path, "/the one/settings/"))
		return t1os_is_goddess_process();

	/* Permit PID 1 to remove the exact obsolete graphics recovery marker. */
	if (t1os_is_graphics_recovery_marker(path))
		return t1os_is_goddess_process();

	/* A verified recovery marker may be followed by one narrowly scoped EFI
	 * boot pin so a one-time USB launch returns to the same T1OS entry. */
	if (t1os_is_efi_bootnext(path))
		return t1os_is_goddess_process();

	/* The broker-owned credential directory itself is created and hardened only
	 * by Startup. Operations may update its fixed credential record through an
	 * already validated descriptor, but cannot mutate this directory object.
	 * Children remain governed by the narrower rules below. */
	if (!strcmp(path, "/the one/master") ||
	    !strcmp(path, "/the one/master/"))
		return t1os_is_startup_process();

	if (!strcmp(path, "/the one/settings/audio") ||
	    !strncmp(path, "/the one/settings/audio/", 24) ||
	    !strcmp(path, "/the one/settings/display") ||
	    !strncmp(path, "/the one/settings/display/", 26) ||
	    !strcmp(path, "/the one/settings/mouse") ||
	    !strncmp(path, "/the one/settings/mouse/", 24) ||
	    !strcmp(path, "/the one/settings/network") ||
	    !strncmp(path, "/the one/settings/network/", 26))
		return t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		       t1os_is_operationsserver_process() ||
		       t1os_is_goddess_process();

	/* Reign owns only the two generated display-clock leaves.  It must never
	 * inherit authority over timezone, internet, VirtualBox, or future time
	 * settings merely because they share this directory. */
	if (!strcmp(path, "/the one/settings/time/common.txt") ||
	    !strcmp(path, "/the one/settings/time/atreyan.txt"))
		return t1os_domain_is(T1OS_DOMAIN_REIGN) ||
		       t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		       t1os_is_operationsserver_process() ||
		       t1os_is_goddess_process();

	if (!strcmp(path, "/the one/settings/time") ||
	    !strncmp(path, "/the one/settings/time/", 23))
		return t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		       t1os_is_operationsserver_process() ||
		       t1os_is_goddess_process();

	if (!strcmp(path, "/the one/settings/master") ||
	    !strncmp(path, "/the one/settings/master/", 25) ||
	    !strcmp(path, "/the one/settings/terminal") ||
	    !strncmp(path, "/the one/settings/terminal/", 27))
		return t1os_is_operationsserver_process();

	if (!strcmp(path, "/the one/settings/session") ||
	    !strncmp(path, "/the one/settings/session/", 26))
		return t1os_is_goddess_process() ||
		       t1os_is_operationsserver_process();

	/* The devpts instance is mode-restricted and contains only interactive
	 * console endpoints. Brick opens the multiplexer; its executed children
	 * must retain read/write access to the inherited numbered endpoint. */
	if (t1os_is_console_device_node_name(path)) {
		if (t1os_is_console_multiplexer_name(path))
			return t1os_is_brick_process();
		if (t1os_is_brick_process())
			return true;
		return current->signal && READ_ONCE(current->signal->tty);
	}

	/* /the one/master/master.txt */
	if (!strcmp(path, "/the one/master/master.txt")) {
		if (t1os_is_startup_process())
			return true;
		if (t1os_is_operationsserver_process())
			return true;
		return false;
	}

	/* /the one/master/ and children → startup only (plus architect via role above) */
	if (!strncmp(path, "/the one/master/", 16)) {
		if (t1os_is_startup_process())
			return true;
		if (t1os_is_operationsserver_process())
			return true;
		return false;
	}

	/* /master root dir → startup only (plus architect via role above) */
	if (!strcmp(path, "/master") || !strcmp(path, "/master/")) {
		if (t1os_is_startup_process())
			return true;
		if (t1os_is_goddess_process())
			return true;
		return false;
	}

	/* /master/<username>/... → startup only (plus architect via role above) */
	if (!strncmp(path, "/master/", 8)) {
		if (t1os_is_startup_process())
			return true;
		if (t1os_is_operationsserver_process())
			return true;
		if (t1os_is_goddess_process())
			return true;
		if (t1os_domain_is(T1OS_DOMAIN_DESKTOP) ||
		    t1os_domain_is(T1OS_DOMAIN_BRICK) ||
		    t1os_domain_is(T1OS_DOMAIN_VIDEO) ||
		    t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		    t1os_domain_is(T1OS_DOMAIN_SNAP) ||
		    t1os_domain_is(T1OS_DOMAIN_CHROMIUM) ||
		    t1os_domain_is(T1OS_DOMAIN_PICKER))
			return true;
		return false;
	}

	/* /the one/settings/windowserver/ and children */
	if (!strncmp(path, "/the one/settings/windowserver/", 31)) {
		if (t1os_is_windowserver_process())
			return true;
		return false;
	}

	/* WindowServer owns NVIDIA's display nodes. Hardware video clients get
	 * nvidiactl, a numeric per-GPU node, and the one primary UVM node required
	 * by CUDA/NVDEC. Chromium receives UVM only in its measured GPU or zygote
	 * process, never in Xvfb, its window manager, or an arbitrary renderer.
	 * No client receives nvidia-uvm-tools or nvidia-caps authority. Driver
	 * Server's authority remains metadata-only below. */
	if (t1os_is_nvidia_device_node_name(path)) {
		if (!t1os_is_nvidia_uvm_device_node_name(path) &&
		    t1os_is_windowserver_process())
			return true;
		if (t1os_is_nvidia_decode_device_node_name(path) &&
		    (t1os_is_video_client_process() ||
		     t1os_is_executable_process(T1OS_CHROMIUM_BINARY)))
			return true;
		if (t1os_is_nvidia_uvm_device_node_name(path) &&
		    (t1os_is_video_client_process() ||
		     t1os_is_chromium_uvm_process()))
			return true;
		return false;
	}
	
	/* Render nodes expose command submission and decode but no KMS display
	 * ownership. Player/media, the measured native video decoder, and
	 * Chromium's measured GPU executable may submit decode work. */
	if (!strncmp(path, "/the one/drivers/nodes/dri/renderD", 34)) {
		if (t1os_is_video_client_process() ||
		    t1os_is_executable_process(T1OS_CHROMIUM_BINARY))
			return true;
	}

	/* DRM/KMS devices are owned by the window server and the narrowly
	 * scoped VirtualBox layout bridge.  This also handles render nodes for
	 * those two processes without granting video clients primary-card access. */
	if (!strcmp(path, "/the one/drivers/nodes/dri") ||
	    !strcmp(path, "/the one/drivers/nodes/dri/"))
		return t1os_is_windowserver_process() ||
		       t1os_domain_is(T1OS_DOMAIN_VIRTUALBOX);
	if (!strncmp(path, "/the one/drivers/nodes/dri/card", 31) ||
	    !strncmp(path, "/the one/drivers/nodes/dri/renderD", 34)) {
		if (t1os_is_windowserver_process())
			return true;
		if (t1os_is_virtualbox_resize_process())
			return true;
		return false;
	}

	/* Only Driver Server may write the sysfs control view. */
	if (!strcmp(path, "/the one/drivers/control") ||
	    !strcmp(path, "/the one/drivers/control/") ||
	    !strncmp(path, "/the one/drivers/control/", 25)) {
		if (t1os_is_driverserver_process())
			return true;
		return false;
	}

	/* Packaged modules, firmware, loader, policy, and the read-only state
	 * view are immutable to ordinary runtime processes. */
	if (!strcmp(path, "/the one/drivers/modules") ||
	    !strncmp(path, "/the one/drivers/modules/", 25) ||
	    !strcmp(path, "/the one/drivers/firmware") ||
	    !strncmp(path, "/the one/drivers/firmware/", 26) ||
	    !strcmp(path, "/the one/drivers/tools") ||
	    !strncmp(path, "/the one/drivers/tools/", 23) ||
	    !strcmp(path, "/the one/drivers/settings") ||
	    !strncmp(path, "/the one/drivers/settings/", 26) ||
	    !strcmp(path, "/the one/drivers/state") ||
	    !strncmp(path, "/the one/drivers/state/", 23) ||
	    !strcmp(path, "/the one/drivers/processes") ||
	    !strncmp(path, "/the one/drivers/processes/", 27))
		return false;

	/* The narrowly scoped VirtualBox clients need only the guest devices,
	 * not blanket device-node access. */
	if (!strcmp(path, "/the one/drivers/nodes/vboxguest") ||
	    !strcmp(path, "/the one/drivers/nodes/vboxuser")) {
		if (t1os_is_virtualbox_process())
			return true;
		return false;
	}

	/* Chromium's upstream engine and the measured native video service may
	 * use only these harmless character devices. The decoder daemon needs the
	 * null node solely to establish closed standard streams before it drops to
	 * the unprivileged worker identity; this does not grant another device. */
	if (!strcmp(path, "/the one/drivers/nodes/null")) {
		if (t1os_is_chromium_engine_process() ||
		    t1os_is_media_decoder_daemon_process())
			return true;
		return false;
	}
	if (!strcmp(path, "/the one/drivers/nodes/zero") ||
	    !strcmp(path, "/the one/drivers/nodes/full") ||
	    !strcmp(path, "/the one/drivers/nodes/random") ||
	    !strcmp(path, "/the one/drivers/nodes/urandom") ||
	    !strcmp(path, "/the one/drivers/nodes/tty")) {
		if (t1os_is_chromium_engine_process())
			return true;
		return false;
	}

	/* The packaged wireless engine needs the radio kill-switch node, but no
	 * broader driver-tree write access. */
	if (!strcmp(path, "/the one/drivers/nodes/rfkill")) {
		if (t1os_is_wireless_engine_process())
			return true;
		return false;
	}

	/* GODDESS may restore the inherited local console after every graphics
	 * backend has failed. This exact node is the visible last-resort login
	 * diagnostic; no other tty or general device-node authority is implied. */
	if (!strcmp(path, "/the one/drivers/nodes/tty0")) {
		if (t1os_is_goddess_process())
			return true;
		return false;
	}

	/* ALSA is the audio service's entire device authority.  The devtmpfs is
	 * mounted at this parent, so a generic nodes wildcard would include raw
	 * disks, input event streams and kernel diagnostic devices. */
	if (!strcmp(path, "/the one/drivers/nodes/snd") ||
	    !strcmp(path, "/the one/drivers/nodes/snd/") ||
	    !strncmp(path, "/the one/drivers/nodes/snd/", 27))
		return t1os_is_audioserver_process();

	/* /the one/drivers/nodes/fb0 */
	if (!strcmp(path, "/the one/drivers/nodes/fb0")) {
		if (t1os_is_windowserver_process())
			return true;
		if (t1os_is_startup_process())
			return true;
		if (t1os_is_lockscreen_process())
			return true;
		if (t1os_is_bootanim_process())
			return true;
		return false;
	}
	
	/* /the one/drivers/nodes/ttyS0 */
	if (!strcmp(path, "/the one/drivers/nodes/ttyS0")) {
		if (t1os_is_goddess_process())
			return true;
		return false;
	}

	/* The driver root itself cannot be modified by master-role processes. */
	if (!strcmp(path, "/the one/drivers") ||
	    !strcmp(path, "/the one/drivers/"))
		return false;

	/* if it wasn't matched above, it's not a special path here */
	return false;
}


static void t1os_log_denial(const char *operation, const char *path)
{
	pr_warn_ratelimited(
		"T1OS LSM: denied %s path=%s pid=%d comm=%s\n",
		operation, path, current->pid, current->comm);
}

static bool t1os_confidential_read_path(const char *path)
{
	if (t1os_is_ephemeral_path(path))
		return false;

	return !strcmp(path, "/the one/master") ||
	       !strcmp(path, "/the one/master/") ||
	       !strncmp(path, "/the one/master/", 16) ||
	       !strcmp(path, "/master") ||
	       !strcmp(path, "/master/") ||
	       !strncmp(path, "/master/", 8) ||
	       !strcmp(path, "/.ephemeral/authentication") ||
	       !strcmp(path, "/.ephemeral/authentication/") ||
	       !strncmp(path, "/.ephemeral/authentication/", 27) ||
	       !strcmp(path, "/.ephemeral/network") ||
	       !strcmp(path, "/.ephemeral/network/") ||
	       !strncmp(path, "/.ephemeral/network/", 20) ||
	       !strcmp(path, "/the one/settings/session/identity.json");
}

static bool t1os_confidential_read_allowed(const char *path)
{
	if (t1os_is_ephemeral_path(path))
		return true;

	if (!strcmp(path, "/master") || !strcmp(path, "/master/") ||
	    !strncmp(path, "/master/", 8))
		return t1os_is_goddess_process() ||
		       t1os_is_startup_process() ||
		       t1os_is_operationsserver_process() ||
		       t1os_domain_is(T1OS_DOMAIN_EXPANSE) ||
		       t1os_domain_is(T1OS_DOMAIN_DESKTOP) ||
		       t1os_domain_is(T1OS_DOMAIN_BRICK) ||
		       t1os_domain_is(T1OS_DOMAIN_VIDEO) ||
		       t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		       t1os_domain_is(T1OS_DOMAIN_SNAP) ||
		       t1os_domain_is(T1OS_DOMAIN_CHROMIUM) ||
		       t1os_domain_is(T1OS_DOMAIN_PICKER);
	/* This exact receipt contains only the bounded first-attempt result which
	 * PID 1 waits for.  Every sibling remains private to Network. */
	if (!strcmp(path, "/.ephemeral/network/initial.json"))
		return t1os_is_network_process() || t1os_is_goddess_process();

	if (!strcmp(path, "/.ephemeral/network") ||
	    !strcmp(path, "/.ephemeral/network/") ||
	    !strncmp(path, "/.ephemeral/network/", 20))
		return t1os_is_network_process();

	if (!strcmp(path, "/the one/settings/session/identity.json"))
		return t1os_is_goddess_process() ||
		       t1os_is_startup_process() ||
		       t1os_is_operationsserver_process() ||
		       t1os_is_windowserver_process() ||
		       t1os_domain_is(T1OS_DOMAIN_EXPANSE) ||
		       t1os_domain_is(T1OS_DOMAIN_DESKTOP) ||
		       t1os_domain_is(T1OS_DOMAIN_BRICK) ||
		       t1os_domain_is(T1OS_DOMAIN_VIDEO) ||
		       t1os_domain_is(T1OS_DOMAIN_SETTINGS) ||
		       t1os_domain_is(T1OS_DOMAIN_SNAP) ||
		       t1os_domain_is(T1OS_DOMAIN_CHROMIUM) ||
		       t1os_domain_is(T1OS_DOMAIN_PICKER) ||
		       t1os_domain_is(T1OS_DOMAIN_LOCKSCREEN);

	/* Credentials, service secrets, recovery authorizations, and authentication
	 * throttle state stay behind the root broker.  Network retrieves a secret
	 * only through SERVICE_SECRET_GET; no service receives a direct read. */
	return t1os_is_goddess_process() ||
	       t1os_is_startup_process() ||
	       t1os_is_operationsserver_process();
}

static bool t1os_process_reader_domain(void)
{
	switch (t1os_task_domain(current)) {
	case T1OS_DOMAIN_GODDESS:
	case T1OS_DOMAIN_STARTUP:
	case T1OS_DOMAIN_OPERATIONS:
	case T1OS_DOMAIN_WINDOW:
	case T1OS_DOMAIN_AUDIO:
	case T1OS_DOMAIN_DRIVER:
	case T1OS_DOMAIN_INPUT:
	case T1OS_DOMAIN_PYTHON_SERVICE:
	case T1OS_DOMAIN_VIRTUALBOX:
	case T1OS_DOMAIN_CHROMIUM:
		return true;
	default:
		return false;
	}
}

static bool t1os_decimal_component(const char *value, size_t length)
{
	size_t i;

	if (!length)
		return false;
	for (i = 0; i < length; ++i)
		if (!isdigit(value[i]))
			return false;
	return true;
}

static bool t1os_process_component_is_current(const char *value, size_t length)
{
	unsigned long parsed = 0;
	pid_t current_pid = task_pid_nr(current);
	size_t i;

	if (current_pid <= 0 || !t1os_decimal_component(value, length))
		return false;
	for (i = 0; i < length; ++i) {
		parsed = parsed * 10 + (value[i] - '0');
		/* PID components longer than the current PID cannot become equal.
		 * Stop here as well as bounding arithmetic on hostile path text. */
		if (parsed > (unsigned long)current_pid)
			return false;
	}
	return parsed == (unsigned long)current_pid;
}

/* The procfs bind is an identity oracle, not a general process-inspection API.
 * Keep both the reader-domain and leaf set explicit.  In particular, mem,
 * fd, map_files, pagemap, syscall, stack and namespace handles stay denied. */
static bool t1os_process_read_allowed(const char *path)
{
	static const char prefix[] = "/the one/drivers/processes/";
	const char *relative, *slash, *leaf;
	size_t component_length;

	/* libkmod reads only the global kernel command line to apply fixed module
	 * options and blacklists before finit_module().  Keep this exception on the
	 * measured module-loader domain and this one non-process-specific leaf; it
	 * does not grant access to any per-PID identity or memory surface. */
	if (!strcmp(path, "/the one/drivers/processes/cmdline") &&
	    t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER))
		return true;
	if (!t1os_process_reader_domain())
		return false;
	if (!strcmp(path, "/the one/drivers/processes") ||
	    !strcmp(path, "/the one/drivers/processes/"))
		return true;
	if (strncmp(path, prefix, sizeof(prefix) - 1))
		return false;
	relative = path + sizeof(prefix) - 1;

	if (!strcmp(relative, "stat") || !strcmp(relative, "meminfo") ||
	    !strcmp(relative, "cmdline") || !strcmp(relative, "uptime") ||
	    !strcmp(relative, "loadavg") || !strcmp(relative, "mounts") ||
	    !strcmp(relative, "sys/kernel/random/boot_id"))
		return true;
	/* DriverServer reconstructs the NVIDIA nodes normally created by udev from
	 * these two read-only kernel inventories. GODDESS reads modules only when it
	 * captures a bounded graphics-failure diagnostic. */
	if (!strcmp(relative, "modules"))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process();
	if (!strcmp(relative, "devices"))
		return t1os_is_driverserver_process();
	if (!strcmp(relative, "driver/nvidia/gpus") ||
	    !strncmp(relative, "driver/nvidia/gpus/", 19))
		return t1os_is_driverserver_process();
	if (!strcmp(relative, "asound") || !strncmp(relative, "asound/", 7))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process() ||
		       t1os_is_audioserver_process();

	slash = strchr(relative, '/');
	if (!slash)
		return t1os_decimal_component(relative, strlen(relative)) ||
		       !strcmp(relative, "self") || !strcmp(relative, "thread-self");
	component_length = slash - relative;
	if (!t1os_decimal_component(relative, component_length) &&
	    !(component_length == 4 && !strncmp(relative, "self", 4)) &&
	    !(component_length == 11 && !strncmp(relative, "thread-self", 11)))
		return false;
	leaf = slash;
	if (!strcmp(leaf, "/stat") || !strcmp(leaf, "/status") ||
	    !strcmp(leaf, "/cmdline") || !strcmp(leaf, "/comm") ||
	    !strcmp(leaf, "/wchan") || !strcmp(leaf, "/attr") ||
	    !strcmp(leaf, "/attr/current") || !strcmp(leaf, "/exe") ||
	    !strcmp(leaf, "/cwd") || !strcmp(leaf, "/mounts") ||
	    !strcmp(leaf, "/mountinfo"))
		return true;
	/* WindowServer verifies its preloaded NVIDIA path provider through its own
	 * mappings. procfs resolves the spelling "self" to the numeric current PID
	 * before this hook receives the canonical path, so accept either spelling
	 * only when it identifies current. Other processes' maps remain denied.
	 * Chromium's readiness validator additionally needs same-domain child maps
	 * and environment; the ptrace hook below enforces that domain boundary. */
	if (!strcmp(leaf, "/io"))
		return t1os_is_goddess_process() ||
		       t1os_is_operationsserver_process();
	if (!strcmp(leaf, "/maps") && t1os_is_windowserver_process() &&
	    ((component_length == 4 && !strncmp(relative, "self", 4)) ||
	     t1os_process_component_is_current(relative, component_length)))
		return true;
	if (!strcmp(leaf, "/maps") || !strcmp(leaf, "/environ"))
		return t1os_domain_is(T1OS_DOMAIN_CHROMIUM);
	if (!strncmp(leaf, "/fdinfo/", 8))
		return t1os_is_goddess_process();
	return false;
}

static bool t1os_kernel_firmware_worker(void)
{
	return !current->mm && (current->flags & PF_KTHREAD) &&
	       (current->flags & PF_WQ_WORKER);
}

static bool t1os_special_read_allowed(const char *path)
{
	if (t1os_confidential_read_path(path))
		return t1os_confidential_read_allowed(path);

	/* Device and process-control trees are authoritative even when opened
	 * O_RDONLY: input nodes expose keystrokes, display nodes expose pixels, and
	 * read-only descriptors can still carry ioctls.  Reuse the exact per-domain
	 * device policy rather than treating read as harmless. */
	if (!strcmp(path, "/the one/drivers/processes") ||
	    !strncmp(path, "/the one/drivers/processes/", 27))
		return t1os_process_read_allowed(path);

	if (!strcmp(path, "/the one/drivers/state") ||
	    !strncmp(path, "/the one/drivers/state/", 23))
		return t1os_task_domain(current) != T1OS_DOMAIN_UNTRUSTED;

	/* request_module() opens the fixed native loader while still executing in
	 * a kernel worker with no mm. bprm_check subsequently assigns the measured
	 * module-loader domain before the image can run. Userspace callers always
	 * have an mm and receive no exception here. */
	if (!strcmp(path, T1OS_MODPROBE_BINARY) && !current->mm)
		return true;

	/* Asynchronous request_firmware() reads execute in a kernel workqueue,
	 * after the measured module-loader process has returned from module init.
	 * Recognize only that kernel-only continuation here; kernel_read_file still
	 * validates the read purpose, packaged path, owner, type, link count, and
	 * mode before firmware contents are accepted by a driver. */
	if ((!strcmp(path, "/the one/drivers/firmware") ||
	     !strncmp(path, "/the one/drivers/firmware/", 26)) &&
	    t1os_kernel_firmware_worker())
		return true;

	if (!strcmp(path, "/the one/drivers/modules") ||
	    !strncmp(path, "/the one/drivers/modules/", 25) ||
	    !strcmp(path, "/the one/drivers/firmware") ||
	    !strncmp(path, "/the one/drivers/firmware/", 26) ||
	    !strcmp(path, "/the one/drivers/tools") ||
	    !strncmp(path, "/the one/drivers/tools/", 23) ||
	    !strcmp(path, "/the one/drivers/settings") ||
	    !strncmp(path, "/the one/drivers/settings/", 26))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process() ||
		       t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER);

	if (!strcmp(path, "/the one/drivers/control") ||
	    !strncmp(path, "/the one/drivers/control/", 25))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process();

	if (!strcmp(path, "/the one/drivers/nodes") ||
	    !strcmp(path, "/the one/drivers/nodes/"))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process() ||
		       t1os_is_audioserver_process() ||
		       t1os_is_windowserver_process() ||
		       t1os_domain_is(T1OS_DOMAIN_INPUT);

	if (!strcmp(path, "/the one/drivers/nodes/input") ||
	    !strcmp(path, "/the one/drivers/nodes/input/") ||
	    !strncmp(path, "/the one/drivers/nodes/input/", 29))
		return t1os_domain_is(T1OS_DOMAIN_INPUT);

	/* Operations may open only the two RTC aliases needed by its typed clock
	 * broker.  The ioctl hook below independently restricts the command set. */
	if ((!strcmp(path, "/the one/drivers/nodes/rtc0") ||
	     !strcmp(path, "/the one/drivers/nodes/rtc")) &&
	    t1os_is_operationsserver_process())
		return true;

	if (!strncmp(path, "/the one/drivers/nodes/", 23))
		return t1os_special_write_allowed(path) ||
		       t1os_is_goddess_process() ||
		       t1os_is_driverserver_process();

	if (!strcmp(path, "/the one/drivers") ||
	    !strcmp(path, "/the one/drivers/"))
		return t1os_is_goddess_process() ||
		       t1os_is_driverserver_process();

	return true;
}

/* Common helper: enforce master/architect and special-path rules
 * for operations identified by a struct path (mkdir, unlink, etc.).
 */
 
static int t1os_check_struct_path(const struct path *p)
{
	char *tmp, *name;
	int ret = 0;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return -ENOMEM;

	name = d_path(p, tmp, PAGE_SIZE);
	if (IS_ERR(name)) {
		free_page((unsigned long)tmp);
		return PTR_ERR(name);
	}
	if (t1os_unreachable_path(name)) {
		t1os_log_denial("unreachable path", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	/* The runtime layout invariant applies even to the architect role. */
	if (t1os_is_forbidden_runtime_path(name) &&
	    !t1os_is_efi_bootnext(name)) {
		t1os_log_denial("path operation", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (t1os_is_ephemeral_path(name)) {
		free_page((unsigned long)tmp);
		return 0;
	}

	/* Special paths use the per-process ACL. */
	if (t1os_is_special_path(name)) {
		if (!t1os_special_write_allowed(name))
			ret = -EACCES;
	} else {
		/* Otherwise use generic protected/non-protected logic. */
		if (!t1os_check_path(name))
			ret = -EACCES;
	}

	if (ret)
		t1os_log_denial("path operation", name);
	free_page((unsigned long)tmp);
	return ret;
}

static bool t1os_struct_path_is_ephemeral(const struct path *path)
{
	char *buffer, *name;
	bool matched = false;

	if (!path)
		return false;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return false;
	name = d_path(path, buffer, PAGE_SIZE);
	if (!IS_ERR(name))
		matched = t1os_is_ephemeral_path(name);
	free_page((unsigned long)buffer);
	return matched;
}

/* devtmpfs materializes kernel-registered devices from its own kernel worker.
 * Its direct vfs_mknod() call is gated by capable(CAP_MKNOD), not by the path
 * hooks used for the mknod syscall.  Once the T1OS runtime boundary is active,
 * the dedicated worker has no userspace domain and must be recognized before
 * the ordinary domain capability ACL.  A userspace task cannot satisfy this
 * identity: require a kernel thread with no mm and the fixed kdevtmpfs name. */
static bool t1os_kernel_devtmpfs_worker(void)
{
	return !current->mm && (current->flags & PF_KTHREAD) &&
	       !strcmp(current->comm, "kdevtmpfs");
}

static bool t1os_kernel_devtmpfs_dentry(const struct dentry *dentry)
{
	return t1os_kernel_devtmpfs_worker() && dentry && dentry->d_sb &&
	       dentry->d_sb->s_type &&
	       !strcmp(dentry->d_sb->s_type->name, "devtmpfs") &&
	       (dentry->d_sb->s_flags & SB_KERNMOUNT);
}

/* Retain path-hook coverage as defense in depth if devtmpfs changes to use a
 * syscall-style helper in a future kernel.  Linux 7.1.5 reaches the capability
 * hook above through vfs_mknod() before it reaches inode_mknod. */
static bool t1os_kernel_devtmpfs_parent(const struct path *dir)
{
	return dir && t1os_kernel_devtmpfs_dentry(dir->dentry);
}

/* Driver Server may adjust ownership and mode on render-only DRM nodes so
 * unprivileged graphics clients can submit work.  Keep this exception out of
 * the general special-path ACL: it must not grant Driver Server open, unlink,
 * rename, or primary KMS card-node authority. */
static bool t1os_is_drm_render_node_path(const struct path *p)
{
	static const char prefix[] = "/the one/drivers/nodes/dri/renderD";
	char *tmp, *name;
	bool matched = false;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return false;

	name = d_path(p, tmp, PAGE_SIZE);
	if (!IS_ERR(name) &&
	    !strncmp(name, prefix, sizeof(prefix) - 1) &&
	    name[sizeof(prefix) - 1] >= '0' &&
	    name[sizeof(prefix) - 1] <= '9')
		matched = true;

	free_page((unsigned long)tmp);
	return matched;
}

/* Driver Server may assign Chromium's unprivileged group to the null and
 * entropy nodes named in its device policy.  This is metadata authority only:
 * the general device-tree ACL still prevents Driver Server from opening,
 * writing, replacing, or linking the nodes. */
static bool t1os_is_chromium_device_node_path(const struct path *p)
{
	char *tmp, *name;
	bool matched = false;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return false;

	name = d_path(p, tmp, PAGE_SIZE);
	if (!IS_ERR(name)) {
		matched =
			!strcmp(name, "/the one/drivers/nodes/null") ||
			!strcmp(name, "/the one/drivers/nodes/random") ||
			!strcmp(name, "/the one/drivers/nodes/urandom");
	}

	free_page((unsigned long)tmp);
	return matched;
}

static bool t1os_is_nvidia_device_node_path(const struct path *p)
{
	char *tmp, *name;
	bool matched = false;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return false;

	name = d_path(p, tmp, PAGE_SIZE);
	if (!IS_ERR(name))
		matched = t1os_is_nvidia_device_node_name(name);

	free_page((unsigned long)tmp);
	return matched;
}

/* ------------------------------------------------------------------ */
/*  Hooks                                                             */
/* ------------------------------------------------------------------ */

/* Delete: unlink */
static int t1os_path_unlink(const struct path *dir, struct dentry *dentry)
{
	struct path p;

	p.mnt = dir->mnt;
	p.dentry = dentry;

	return t1os_check_struct_path(&p);
}

/* Delete: rmdir */
static int t1os_path_rmdir(const struct path *dir, struct dentry *dentry)
{
	struct path p;

	p.mnt = dir->mnt;
	p.dentry = dentry;

	return t1os_check_struct_path(&p);
}

/* Make directory: mkdir */
static int t1os_path_mkdir(const struct path *dir,
			   struct dentry *dentry,
			   umode_t mode)
{
	struct path p;

	p.mnt = dir->mnt;
	p.dentry = dentry;
	if (t1os_kernel_devtmpfs_parent(dir))
		return 0;

	return t1os_check_struct_path(&p);
}

/* Make node: mknod */
static bool t1os_reign_time_output_create_allowed(const struct path *dir,
						  struct dentry *dentry,
						  umode_t mode)
{
	static const char parent[] = "/the one/settings/time";
	static const char common[] = "common.txt";
	static const char atreyan[] = "atreyan.txt";
	char *buffer, *path;
	bool name_allowed, allowed = false;

	if (!t1os_domain_is(T1OS_DOMAIN_REIGN) || !S_ISREG(mode) ||
	    !dir || !dir->dentry || !dentry ||
	    dentry->d_parent != dir->dentry)
		return false;
	name_allowed =
		(dentry->d_name.len == sizeof(common) - 1 &&
		 !memcmp(dentry->d_name.name, common, sizeof(common) - 1)) ||
		(dentry->d_name.len == sizeof(atreyan) - 1 &&
		 !memcmp(dentry->d_name.name, atreyan, sizeof(atreyan) - 1));
	if (!name_allowed)
		return false;

	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return false;
	path = d_path(dir, buffer, PAGE_SIZE);
	if (!IS_ERR(path) && !strcmp(path, parent))
		allowed = true;
	free_page((unsigned long)buffer);
	return allowed;
}

static int t1os_path_mknod(const struct path *dir,
			   struct dentry *dentry,
			   umode_t mode,
			   unsigned int dev)
{
	struct path p;

	p.mnt = dir->mnt;
	p.dentry = dentry;

	if ((S_ISCHR(mode) || S_ISBLK(mode)) &&
	    t1os_kernel_devtmpfs_parent(dir))
		return 0;
	if (t1os_is_driverserver_process() &&
	    S_ISCHR(mode) &&
	    t1os_is_nvidia_device_node_path(&p))
		return 0;
	if (t1os_reign_time_output_create_allowed(dir, dentry, mode))
		return 0;

	return t1os_check_struct_path(&p);
}

static int t1os_path_truncate(const struct path *path)
{
	return t1os_check_struct_path(path);
}

/* Links remain forbidden outside the scratch tier because path ACLs have no
 * persistent inode label.  Inside /.ephemeral they are ordinary boot-scoped
 * filesystem objects and must not be blocked by this LSM. */
static int t1os_path_symlink(const struct path *dir,
			     struct dentry *dentry,
			     const char *old_name)
{
	struct path destination;

	(void)old_name;
	destination.mnt = dir->mnt;
	destination.dentry = dentry;
	return t1os_struct_path_is_ephemeral(&destination) ? 0 : -EACCES;
}

/* Make hard link: link */
static int t1os_path_link(struct dentry *old_dentry,
			  const struct path *new_dir,
			  struct dentry *new_dentry)
{
	struct path source, destination;

	/* Path ACLs have no persistent inode label, so a hard link could alias a
	 * protected credential or executable into an unprotected pathname. Permit
	 * links only when both names stay wholly within the ephemeral tier. */
	source.mnt = new_dir->mnt;
	source.dentry = old_dentry;
	destination.mnt = new_dir->mnt;
	destination.dentry = new_dentry;
	if (t1os_struct_path_is_ephemeral(&source) &&
	    t1os_struct_path_is_ephemeral(&destination))
		return 0;
	return -EACCES;
}

/* Move/rename: rename */
static int t1os_path_rename(const struct path *old_dir,
			    struct dentry *old_dentry,
			    const struct path *new_dir,
			    struct dentry *new_dentry,
			    unsigned int flags)
{
	struct path old_path;
	struct path new_path;
	int ret;

	/* First protect the source path. */
	old_path.mnt = old_dir->mnt;
	old_path.dentry = old_dentry;

	ret = t1os_check_struct_path(&old_path);
	if (ret)
		return ret;

	/* Then protect the destination path. */
	new_path.mnt = new_dir->mnt;
	new_path.dentry = new_dentry;

	return t1os_check_struct_path(&new_path);
}

/* Metadata: chmod */
static int t1os_path_chmod(const struct path *path, umode_t mode)
{
	if (t1os_is_driverserver_process() &&
	    (t1os_is_drm_render_node_path(path) ||
	     t1os_is_chromium_device_node_path(path) ||
	     t1os_is_nvidia_device_node_path(path)))
		return 0;

	return t1os_check_struct_path(path);
}

/* Metadata: chown */
static int t1os_path_chown(const struct path *path,
			   kuid_t uid,
			   kgid_t gid)
{
	if (t1os_is_driverserver_process() &&
	    (t1os_is_drm_render_node_path(path) ||
	     t1os_is_chromium_device_node_path(path) ||
	     t1os_is_nvidia_device_node_path(path)))
		return 0;

	return t1os_check_struct_path(path);
}

/* Mount topology becomes immutable at the PID 1 T1OS handoff.  This closes
 * pathname-policy aliasing through bind, overlay, pivot_root, and chroot. */
static int t1os_mount_topology_allowed(void)
{
	return t1os_runtime_root_active() ? -EACCES : 0;
}

static bool t1os_safe_mount_component(const char *value)
{
	const char *cursor = value;
	unsigned int length = 0;

	if (!cursor || !*cursor)
		return false;
	while (*cursor) {
		if (!(isalnum(*cursor) || *cursor == '.' || *cursor == '_' ||
		      *cursor == '-'))
			return false;
		cursor++;
		if (++length > 96)
			return false;
	}
	return true;
}

static bool t1os_external_volume_target(const char *path)
{
	static const char prefix[] = "/.ephemeral/volumes/";

	return path && !strncmp(path, prefix, sizeof(prefix) - 1) &&
	       t1os_safe_mount_component(path + sizeof(prefix) - 1);
}

static bool t1os_external_volume_source(const char *source)
{
	static const char prefix[] = "/the one/drivers/nodes/";

	return source && !strncmp(source, prefix, sizeof(prefix) - 1) &&
	       t1os_safe_mount_component(source + sizeof(prefix) - 1);
}

static bool t1os_external_volume_options(const void *data)
{
	return data && !strcmp((const char *)data,
		"uid=1000,gid=1000,dmask=0077,fmask=0177");
}

static int t1os_mount_path(const struct path *path, char *buffer,
			   char **resolved)
{
	char *name;

	if (!path || !buffer || !resolved)
		return -EINVAL;
	name = d_path(path, buffer, PAGE_SIZE);
	if (IS_ERR(name))
		return PTR_ERR(name);
	if (t1os_unreachable_path(name))
		return -EACCES;
	*resolved = name;
	return 0;
}

static int t1os_sb_mount(const char *dev_name, const struct path *path,
			 const char *type, unsigned long flags, void *data)
{
	char *buffer, *target;
	unsigned long volume_flags = MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC;
	int ret;

	if (!t1os_runtime_root_active())
		return 0;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	ret = t1os_mount_path(path, buffer, &target);
	if (ret)
		goto out;

	/* PID 1's only runtime mount operations are the compatibility tmpfs
	 * fallback and the final read-only root remount. */
	if (t1os_is_goddess_process() &&
	    !strcmp(target, "/.ephemeral") && dev_name && type &&
	    !strcmp(dev_name, "tmpfs") && !strcmp(type, "tmpfs") &&
	    flags == 0 && !data) {
		ret = 0;
		goto out;
	}
	if (t1os_is_goddess_process() && !strcmp(target, "/") &&
	    !dev_name && !type && !data &&
	    flags == (MS_RDONLY | MS_REMOUNT)) {
		ret = 0;
		goto out;
	}

	/* Driver Server's removable-media feature is the sole post-handoff new
	 * mount.  Bind/overlay/remount/move are excluded, the source and target
	 * each have one safe component, and the mount is always nosuid/nodev/noexec. */
	if (t1os_is_driverserver_process() && dev_name && type &&
	    t1os_external_volume_options(data) &&
	    t1os_external_volume_source(dev_name) &&
	    t1os_external_volume_target(target) &&
	    (!strcmp(type, "ntfs3") || !strcmp(type, "exfat") ||
	     !strcmp(type, "vfat")) &&
	    (flags & (MS_NOSUID | MS_NODEV | MS_NOEXEC)) ==
		(MS_NOSUID | MS_NODEV | MS_NOEXEC) &&
	    !(flags & ~volume_flags)) {
		ret = 0;
		goto out;
	}
	/* VirtualBox shared folders are transient external volumes.  Keep both
	 * source names and mount targets to one safe component, require the exact
	 * ownership/mode contract used by Guest Additions, and never allow files
	 * from a host share to execute or carry device/set-id authority. */
	if (t1os_domain_is(T1OS_DOMAIN_VIRTUALBOX) &&
	    dev_name && type && data &&
	    t1os_safe_mount_component(dev_name) &&
	    t1os_external_volume_target(target) &&
	    !strcmp(type, "vboxsf") &&
	    !strcmp((const char *)data, "uid=0,gid=0,dmode=0770,fmode=0660") &&
	    (flags & (MS_NOSUID | MS_NODEV | MS_NOEXEC)) ==
		(MS_NOSUID | MS_NODEV | MS_NOEXEC) &&
	    !(flags & ~volume_flags)) {
		ret = 0;
		goto out;
	}
	ret = -EACCES;
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_sb_umount(struct vfsmount *mnt, int flags)
{
	struct path path;
	char *buffer, *target;
	int ret;

	if (!t1os_runtime_root_active())
		return 0;
	if (!mnt || (flags && flags != MNT_DETACH))
		return -EACCES;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	path.mnt = mnt;
	path.dentry = mnt->mnt_root;
	ret = t1os_mount_path(&path, buffer, &target);
	if (ret)
		goto out;
	if (t1os_is_driverserver_process() &&
	    t1os_external_volume_target(target))
		ret = 0;
	else if (t1os_domain_is(T1OS_DOMAIN_VIRTUALBOX) &&
		 t1os_external_volume_target(target))
		ret = 0;
	else if (t1os_is_goddess_process() &&
		 (!strcmp(target, "/.ephemeral/terminfo") ||
		  !strcmp(target, "/.ephemeral/angel-boot") ||
		  !strcmp(target, "/.ephemeral")))
		ret = 0;
	else
		ret = -EACCES;
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_sb_pivotroot(const struct path *old_path,
			     const struct path *new_path)
{
	(void)old_path; (void)new_path;
	return t1os_mount_topology_allowed();
}

static int t1os_move_mount(const struct path *from_path,
			   const struct path *to_path)
{
	(void)from_path; (void)to_path;
	return t1os_mount_topology_allowed();
}

static int t1os_path_chroot(const struct path *path)
{
	(void)path;
	/* Chromium's fixed setuid sandbox requires one chroot after it has entered
	 * the chromium domain.  No other process receives this compatibility path. */
	if (t1os_runtime_root_active() &&
	    t1os_domain_is(T1OS_DOMAIN_CHROMIUM) &&
	    t1os_is_executable_process(T1OS_CHROMIUM_SANDBOX))
		return 0;
	return t1os_mount_topology_allowed();
}

/*
 * file_open hook
 *
 * This runs at open(2) time, before truncation happens for O_TRUNC.
 * We apply the same special write ACL here so a forbidden writer
 * cannot even open /the one/master/master.txt in "w" mode and zero it.
 */
static int t1os_file_open(struct file *file)
{
	char *tmp, *name;
	int ret = 0;
	bool wants_write;

	/* treat create/truncate as write intent as well */
	wants_write = (file->f_mode & FMODE_WRITE) ||
		      (file->f_flags & (O_CREAT | O_TRUNC));

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return -ENOMEM;

	name = d_path(&file->f_path, tmp, PAGE_SIZE);
	if (IS_ERR(name)) {
		free_page((unsigned long)tmp);
		return PTR_ERR(name);
	}
	if (t1os_unreachable_path(name)) {
		t1os_log_denial("unreachable open", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (t1os_is_forbidden_runtime_path(name) &&
	    !t1os_is_efi_bootnext(name)) {
		t1os_log_denial("open", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (t1os_is_ephemeral_path(name)) {
		free_page((unsigned long)tmp);
		return 0;
	}

	if ((file->f_mode & FMODE_READ) && !t1os_special_read_allowed(name)) {
		t1os_log_denial("confidential read", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (!wants_write) {
		free_page((unsigned long)tmp);
		return 0;
	}

	/* 1) Special paths: enforce per-process ACL immediately. */
	if (t1os_is_special_path(name)) {
		if (!t1os_special_write_allowed(name))
			ret = -EACCES;
		if (ret)
			t1os_log_denial("write open", name);
		free_page((unsigned long)tmp);
		return ret;
	}

	/* 2) Non-special paths: use generic role/path policy. */
	/* Script and interpreter exceptions apply only to execution. Existing
	 * protected code must not become writable merely because of its suffix or
	 * because it is the trusted Python binary. */
	if (!t1os_check_path(name))
		ret = -EACCES;

	if (ret)
		t1os_log_denial("write open", name);
	free_page((unsigned long)tmp);
	return ret;
}

/*
 * VFS write/delete/move hook
 *
 * This is a second layer; open-time is already checked, but this
 * protects against any writes that somehow bypassed file_open.
 */
static int t1os_file_perm(struct file *file, int mask)
{
	char *tmp, *name;
	int ret = 0;

	tmp = (char *)__get_free_page(GFP_KERNEL);
	if (!tmp)
		return -ENOMEM;

	name = d_path(&file->f_path, tmp, PAGE_SIZE);
	if (IS_ERR(name)) {
		free_page((unsigned long)tmp);
		return PTR_ERR(name);
	}
	if (t1os_unreachable_path(name)) {
		t1os_log_denial("unreachable permission", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (t1os_is_forbidden_runtime_path(name) &&
	    !t1os_is_efi_bootnext(name)) {
		t1os_log_denial("inherited runtime-root permission", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (t1os_is_ephemeral_path(name)) {
		free_page((unsigned long)tmp);
		return 0;
	}
	if ((mask & MAY_READ) && !t1os_special_read_allowed(name)) {
		t1os_log_denial("confidential permission", name);
		free_page((unsigned long)tmp);
		return -EACCES;
	}
	if (!(mask & MAY_WRITE)) {
		free_page((unsigned long)tmp);
		return 0;
	}

	/* 1) Special paths: per-process ACL. */
	if (t1os_is_special_path(name)) {
		if (!t1os_special_write_allowed(name))
			ret = -EACCES;
		if (ret)
			t1os_log_denial("write permission", name);
		free_page((unsigned long)tmp);
		return ret;
	}

	/* 2) Otherwise original policy. */
	if (!t1os_check_path(name))
		ret = -EACCES;

	if (ret)
		t1os_log_denial("write permission", name);
	free_page((unsigned long)tmp);
	return ret;
}

/* ------------------------------------------------------------------ */
/* Immutable domain transitions and execution                         */
/* ------------------------------------------------------------------ */

static int t1os_file_path(struct file *file, char *buffer, char **resolved)
{
	char *name;

	if (!file || !buffer || !resolved)
		return -EINVAL;
	name = d_path(&file->f_path, buffer, PAGE_SIZE);
	if (IS_ERR(name))
		return PTR_ERR(name);
	if (t1os_unreachable_path(name))
		return -EACCES;
	*resolved = name;
	return 0;
}

static int t1os_file_truncate(struct file *file)
{
	if (!file)
		return -EACCES;
	return t1os_file_perm(file, MAY_WRITE);
}

static int t1os_check_dentry_metadata(struct dentry *dentry)
{
	char *buffer, *name;
	int ret = 0;

	/* The verified initramfs establishes NTFS3's persistent $LX ownership and
	 * mode metadata before the GODDESS handoff activates the runtime policy.
	 * Enforcing the post-handoff dentry policy here would prevent PID 1 from
	 * assigning those exact, subsequently verified permissions. */
	if (!t1os_runtime_root_active())
		return 0;
	if (!dentry)
		return -EACCES;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	name = dentry_path_raw(dentry, buffer, PAGE_SIZE);
	if (IS_ERR(name)) {
		ret = PTR_ERR(name);
		goto out;
	}
	if (t1os_is_ephemeral_path(name))
		goto out;
	if (t1os_unreachable_path(name) ||
	    t1os_is_forbidden_runtime_path(name) ||
	    (t1os_is_special_path(name) &&
	     !t1os_special_write_allowed(name)) ||
	    (!t1os_is_special_path(name) && !t1os_check_path(name)))
		ret = -EACCES;
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_inode_setattr(struct mnt_idmap *idmap,
			      struct dentry *dentry, struct iattr *attr)
{
	(void)idmap;
	(void)attr;
	/* handle_create() follows vfs_mknod() with notify_change() so the node
	 * receives the mode and ownership selected by the registering device. */
	if (t1os_kernel_devtmpfs_dentry(dentry))
		return 0;
	return t1os_check_dentry_metadata(dentry);
}

static int t1os_inode_setxattr(struct mnt_idmap *idmap,
			       struct dentry *dentry, const char *name,
			       const void *value, size_t size, int flags)
{
	(void)idmap;
	(void)name;
	(void)value;
	(void)size;
	(void)flags;
	return t1os_check_dentry_metadata(dentry);
}

static int t1os_inode_removexattr(struct mnt_idmap *idmap,
				  struct dentry *dentry, const char *name)
{
	(void)idmap;
	(void)name;
	return t1os_check_dentry_metadata(dentry);
}

static int t1os_file_ioctl(struct file *file, unsigned int command,
			   unsigned long argument)
{
	char *buffer, *path;
	int ret = 0;

	(void)argument;
	if (!file)
		return -EACCES;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	ret = t1os_file_path(file, buffer, &path);
	if (ret)
		goto out;
	/* RTC descriptors are terminal here: opening an exact RTC alias never
	 * implies authority for an unrelated RTC ioctl, including through an
	 * SCM_RIGHTS transfer. */
	if (!strcmp(path, "/the one/drivers/nodes/rtc0") ||
	    !strcmp(path, "/the one/drivers/nodes/rtc")) {
		if (command == T1OS_RTC_RD_TIME)
			ret = t1os_is_operationsserver_process() ||
			      t1os_is_goddess_process() ||
			      t1os_is_driverserver_process() ? 0 : -EACCES;
		else if (command == T1OS_RTC_SET_TIME)
			ret = t1os_is_operationsserver_process() ? 0 : -EACCES;
		else
			ret = -EACCES;
		goto out;
	}
	if (!strncmp(path, "/the one/drivers/nodes/", 23)) {
		/* Ioctl authority follows the exact device/domain open matrix.  This is
		 * re-evaluated on every call so an SCM_RIGHTS transfer cannot widen it. */
		if (!t1os_special_read_allowed(path) ||
		    ((file->f_mode & FMODE_WRITE) &&
		     !t1os_special_write_allowed(path)))
			ret = -EACCES;
		else
			ret = 0;
	}
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_file_receive(struct file *file)
{
	/* Re-run open-time path/domain checks for descriptors received over Unix
	 * sockets; otherwise an authorized device broker could accidentally confer
	 * its authority to another uid1000 domain. */
	return t1os_file_open(file);
}

static int t1os_mmap_file(struct file *file, unsigned long reqprot,
			  unsigned long prot, unsigned long flags)
{
	int mask = 0;

	(void)reqprot;
	if (!file)
		return 0;
	if (prot & (PROT_READ | PROT_EXEC))
		mask |= MAY_READ;
	if ((prot & PROT_WRITE) && (flags & MAP_SHARED))
		mask |= MAY_WRITE;
	return mask ? t1os_file_perm(file, mask) : 0;
}

static int t1os_file_mprotect(struct vm_area_struct *vma,
			      unsigned long reqprot, unsigned long prot)
{
	int mask = 0;

	(void)reqprot;
	if (!vma || !vma->vm_file)
		return 0;
	if (prot & (PROT_READ | PROT_EXEC))
		mask |= MAY_READ;
	if ((prot & PROT_WRITE) && (vma->vm_flags & VM_SHARED))
		mask |= MAY_WRITE;
	return mask ? t1os_file_perm(vma->vm_file, mask) : 0;
}

static bool t1os_service_launch(enum t1os_domain target, const char *path)
{
	switch (target) {
	case T1OS_DOMAIN_STARTUP:
		return !strcmp(path, T1OS_STARTUP_SCRIPT);
	case T1OS_DOMAIN_OPERATIONS:
		return !strcmp(path, T1OS_OPERATIONSSERVER_SCRIPT);
	case T1OS_DOMAIN_PROCEDURES:
		return !strcmp(path, T1OS_PROCEDURES_SCRIPT);
	case T1OS_DOMAIN_WINDOW:
		return !strcmp(path, T1OS_WINDOWSERVER_SCRIPT);
	case T1OS_DOMAIN_AUDIO:
		return !strcmp(path, T1OS_AUDIOSERVER_SCRIPT);
	case T1OS_DOMAIN_DRIVER:
		return !strcmp(path, T1OS_DRIVERSERVER_SCRIPT);
	case T1OS_DOMAIN_INPUT:
		return !strcmp(path, T1OS_INPUT_SCRIPT);
	case T1OS_DOMAIN_NETWORK:
		return !strcmp(path, T1OS_NETWORK_SCRIPT);
	case T1OS_DOMAIN_REIGN:
		return !strcmp(path, T1OS_REIGN_SCRIPT);
	case T1OS_DOMAIN_PYTHON_SERVICE:
		return !strcmp(path, T1OS_PYTHON_SERVICE_SCRIPT);
	case T1OS_DOMAIN_EXCHANGE:
		return !strcmp(path, T1OS_EXCHANGE_SCRIPT);
	case T1OS_DOMAIN_EXPANSE:
		return !strcmp(path, T1OS_EXPANSE_SCRIPT);
	case T1OS_DOMAIN_VIRTUALBOX:
		return !strcmp(path, T1OS_VIRTUALBOX_SCRIPT);
	case T1OS_DOMAIN_BOOT_ANIMATION:
		return !strcmp(path, T1OS_BOOTANIM_SCRIPT);
	case T1OS_DOMAIN_VIDEO:
		return !strcmp(path, T1OS_MEDIA_DECODER_DAEMON);
	default:
		return false;
	}
}

static bool t1os_catalogue_launch(enum t1os_domain target, const char *path)
{
	switch (target) {
	case T1OS_DOMAIN_DESKTOP:
		return !strcmp(path, T1OS_ARRAY_SCRIPT) ||
		       !strcmp(path, T1OS_CALCULATOR_SCRIPT) ||
		       !strcmp(path, T1OS_OPERATIONSCENTRE_SCRIPT) ||
		       !strcmp(path, T1OS_VIEWER_SCRIPT) ||
		       !strcmp(path, T1OS_WRITE_SCRIPT);
	case T1OS_DOMAIN_BRICK:
		return !strcmp(path, T1OS_BRICK_SCRIPT);
	case T1OS_DOMAIN_VIDEO:
		return !strcmp(path, T1OS_PLAYER_SCRIPT);
	case T1OS_DOMAIN_SETTINGS:
		return !strcmp(path, T1OS_SETTINGS_SCRIPT);
	case T1OS_DOMAIN_SNAP:
		return !strcmp(path, T1OS_SNAP_SCRIPT);
	case T1OS_DOMAIN_CHROMIUM:
		return !strcmp(path, T1OS_CHROMIUM_SCRIPT);
	default:
		return false;
	}
}

static bool t1os_window_launch(enum t1os_domain target, const char *path)
{
	if (target == T1OS_DOMAIN_DESKTOP)
		return !strcmp(path, T1OS_ARRAY_SCRIPT) ||
		       !strcmp(path, T1OS_OPERATIONSCENTRE_SCRIPT);
	if (target == T1OS_DOMAIN_BRICK)
		return !strcmp(path, T1OS_BRICK_SCRIPT);
	if (target == T1OS_DOMAIN_PICKER)
		return !strcmp(path, T1OS_PICKER_SCRIPT);
	return false;
}

static bool t1os_transition_allowed(enum t1os_domain launcher,
				    enum t1os_domain target,
				    const char *path)
{
	if (launcher == T1OS_DOMAIN_GODDESS &&
	    target == T1OS_DOMAIN_GODDESS)
		return !strcmp(path, T1OS_GODDESS_SCRIPT);
	if (launcher == T1OS_DOMAIN_GODDESS)
		return t1os_service_launch(target, path);
	if (launcher == T1OS_DOMAIN_OPERATIONS)
		return t1os_catalogue_launch(target, path) ||
		       (target == T1OS_DOMAIN_STARTUP &&
			!strcmp(path, T1OS_STARTUP_SCRIPT)) ||
		       (target == T1OS_DOMAIN_LOCKSCREEN &&
			!strcmp(path, T1OS_STARTUP_SCRIPT));
	if (launcher == T1OS_DOMAIN_WINDOW)
		return t1os_window_launch(target, path);
	if (launcher == T1OS_DOMAIN_STARTUP) {
		if (target == T1OS_DOMAIN_LOCKSCREEN)
			return !strcmp(path, T1OS_LOCKSCREEN_SCRIPT);
		if (target == T1OS_DOMAIN_BOOT_ANIMATION)
			return !strcmp(path, T1OS_BOOTANIM_SCRIPT);
	}
	if (launcher == T1OS_DOMAIN_LOCKSCREEN &&
	    target == T1OS_DOMAIN_LOCKSCREEN)
		return !strcmp(path, T1OS_LOCKSCREEN_SCRIPT);
	return false;
}

static bool t1os_unprivileged_launch(enum t1os_domain target,
				     const char *path)
{
	if (target == T1OS_DOMAIN_LOCKSCREEN)
		return true;
	if (target == T1OS_DOMAIN_PICKER)
		return !strcmp(path, T1OS_PICKER_SCRIPT);
	if (target == T1OS_DOMAIN_EXPANSE)
		return !strcmp(path, T1OS_EXPANSE_SCRIPT);
	return t1os_catalogue_launch(target, path);
}

static bool t1os_unprivileged_domain(enum t1os_domain domain)
{
	return domain == T1OS_DOMAIN_EXPANSE ||
	       domain == T1OS_DOMAIN_DESKTOP ||
	       domain == T1OS_DOMAIN_BRICK ||
	       domain == T1OS_DOMAIN_VIDEO ||
	       domain == T1OS_DOMAIN_SETTINGS ||
	       domain == T1OS_DOMAIN_SNAP ||
	       domain == T1OS_DOMAIN_CHROMIUM ||
	       domain == T1OS_DOMAIN_PICKER ||
	       domain == T1OS_DOMAIN_LOCKSCREEN;
}

static bool t1os_unprivileged_creds(const struct cred *cred,
				    bool chromium_exception)
{
	kuid_t uid = make_kuid(&init_user_ns, 1000);
	kgid_t gid = make_kgid(&init_user_ns, 1000);

	if (!cred || !uid_valid(uid) || !gid_valid(gid) ||
	    cred->user_ns != &init_user_ns)
		return false;
	if (!uid_eq(cred->uid, uid) || !uid_eq(cred->euid, uid) ||
	    !uid_eq(cred->suid, uid) || !uid_eq(cred->fsuid, uid) ||
	    !gid_eq(cred->gid, gid) || !gid_eq(cred->egid, gid) ||
	    !gid_eq(cred->sgid, gid) || !gid_eq(cred->fsgid, gid))
		return false;
	if (!cred->group_info || cred->group_info->ngroups != 0)
		return false;
	if (!cap_isclear(cred->cap_inheritable) ||
	    !cap_isclear(cred->cap_permitted) ||
	    !cap_isclear(cred->cap_effective) ||
	    !cap_isclear(cred->cap_ambient))
		return false;

	/* Chromium alone must invoke the exact setuid sandbox once.  It starts
	 * without NNP and retains a bounding set; every other desktop domain is
	 * NNP and has an empty bounding set before it receives a label. */
	if (chromium_exception)
		return !task_no_new_privs(current);
	return task_no_new_privs(current) && cap_isclear(cred->cap_bset);
}

static bool t1os_root_service_creds(const struct cred *cred)
{
	if (!cred || cred->user_ns != &init_user_ns)
		return false;
	return uid_eq(cred->uid, GLOBAL_ROOT_UID) &&
	       uid_eq(cred->euid, GLOBAL_ROOT_UID) &&
	       uid_eq(cred->suid, GLOBAL_ROOT_UID) &&
	       uid_eq(cred->fsuid, GLOBAL_ROOT_UID) &&
	       gid_eq(cred->gid, GLOBAL_ROOT_GID) &&
	       gid_eq(cred->egid, GLOBAL_ROOT_GID) &&
	       gid_eq(cred->sgid, GLOBAL_ROOT_GID) &&
	       gid_eq(cred->fsgid, GLOBAL_ROOT_GID);
}

static bool t1os_chromium_sandbox_creds(const struct cred *cred)
{
	kuid_t user = make_kuid(&init_user_ns, 1000);
	kgid_t group = make_kgid(&init_user_ns, 1000);

	if (!cred || !uid_valid(user) || !gid_valid(group) ||
	    cred->user_ns != &init_user_ns ||
	    !uid_eq(cred->uid, user) || !gid_eq(cred->gid, group) ||
	    !gid_eq(cred->egid, group) || !gid_eq(cred->sgid, group) ||
	    !gid_eq(cred->fsgid, group) ||
	    !uid_eq(cred->euid, GLOBAL_ROOT_UID) ||
	    !uid_eq(cred->suid, GLOBAL_ROOT_UID) ||
	    !uid_eq(cred->fsuid, GLOBAL_ROOT_UID) ||
	    !cred->group_info || cred->group_info->ngroups != 0 ||
	    !cap_isclear(cred->cap_inheritable) ||
	    !cap_isclear(cred->cap_ambient) || task_no_new_privs(current))
		return false;

	/* A legacy setuid-root executable receives capabilities from the kernel's
	 * secureexec calculation.  The exception is attached only to the exact,
	 * root-owned, nonwritable chrome-sandbox image and lasts for that image. */
	return true;
}

static bool t1os_exec_cred_class_allowed(const struct linux_binprm *bprm,
					 enum t1os_cred_class class)
{
	if (!bprm || !bprm->cred)
		return false;
	switch (class) {
	case T1OS_CRED_UNPRIVILEGED:
		return t1os_unprivileged_creds(bprm->cred, false);
	case T1OS_CRED_CHROMIUM:
		return t1os_unprivileged_creds(bprm->cred, true);
	case T1OS_CRED_CHROMIUM_SANDBOX:
		return t1os_chromium_sandbox_creds(bprm->cred);
	case T1OS_CRED_ROOT:
	default:
		return t1os_root_service_creds(bprm->cred);
	}
}

static void t1os_clear_pending(struct t1os_task_security *security);

static bool t1os_python_script_path(const char *path)
{
	size_t length;

	if (!path)
		return false;
	length = strlen(path);
	return length > 3 && !strcmp(path + length - 3, ".py");
}

/* Custom prctl used only in a just-forked child immediately before exec.  The
 * descriptor names the already-open launch object; no argv or cmdline content
 * participates in the decision. */
static int t1os_task_prctl(int option, unsigned long arg2,
			   unsigned long arg3, unsigned long arg4,
			   unsigned long arg5)
{
	struct t1os_task_security *security;
	struct fd descriptor = { 0 };
	struct fd interpreter = { 0 };
	struct file *launch_file, *interpreter_file = NULL;
	struct inode *inode, *interpreter_inode;
	enum t1os_domain launcher, target;
	char *buffer = NULL, *path = NULL;
	bool python_script;
	int ret = -EACCES;

	if (option != T1OS_PR_SET_DOMAIN)
		return -ENOSYS;
	if (arg5 || !t1os_domain_valid(arg2))
		return -EINVAL;
	security = t1os_task(current);
	if (!security)
		return -ENOMEM;
	/* Every custom transition request consumes any older authorization, even
	 * when this request later fails validation. */
	t1os_clear_pending(security);
	launcher = t1os_task_domain(current);
	target = (enum t1os_domain)arg2;
	if (target == T1OS_DOMAIN_ARCHITECT_HELPER ||
	    target == T1OS_DOMAIN_MAINTENANCE ||
	    target == T1OS_DOMAIN_MODULE_LOADER)
		return -EACCES;

	descriptor = fdget((unsigned int)arg3);
	if (fd_empty(descriptor))
		return -EBADF;
	launch_file = fd_file(descriptor);
	inode = file_inode(launch_file);
	if (!S_ISREG(inode->i_mode)) {
		ret = -EINVAL;
		goto out;
	}
	if (!uid_eq(inode->i_uid, GLOBAL_ROOT_UID) ||
	    inode->i_nlink != 1 ||
	    (inode->i_mode & (S_IWGRP | S_IWOTH))) {
		ret = -EACCES;
		goto out;
	}
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer) {
		ret = -ENOMEM;
		goto out;
	}
	ret = t1os_file_path(launch_file, buffer, &path);
	if (ret)
		goto out;
	if (!t1os_transition_allowed(launcher, target, path)) {
		ret = -EACCES;
		goto out;
	}
	python_script = t1os_python_script_path(path);
	if (python_script) {
		if (!arg4) {
			ret = -EINVAL;
			goto out;
		}
		interpreter = fdget((unsigned int)arg4);
		if (fd_empty(interpreter)) {
			ret = -EBADF;
			goto out;
		}
		interpreter_file = fd_file(interpreter);
		interpreter_inode = file_inode(interpreter_file);
		if (!S_ISREG(interpreter_inode->i_mode) ||
		    !uid_eq(interpreter_inode->i_uid, GLOBAL_ROOT_UID) ||
		    interpreter_inode->i_nlink != 1 ||
		    (interpreter_inode->i_mode & (S_IWGRP | S_IWOTH))) {
			ret = -EACCES;
			goto out;
		}
		ret = t1os_file_path(interpreter_file, buffer, &path);
		if (ret || strcmp(path, T1OS_PYTHON_BINARY)) {
			ret = ret ?: -EACCES;
			goto out;
		}
		security->pending_interpreter_device =
			interpreter_inode->i_sb->s_dev;
		security->pending_interpreter_inode = interpreter_inode->i_ino;
	} else if (arg4) {
		ret = -EINVAL;
		goto out;
	}
	security->pending_domain = target;
	security->pending_device = inode->i_sb->s_dev;
	security->pending_inode = inode->i_ino;
	security->pending = true;
	/* The target has no authority before a successful exec commit. */
	security->domain = T1OS_DOMAIN_UNTRUSTED;
	ret = 0;
out:
	if (buffer)
		free_page((unsigned long)buffer);
	if (!fd_empty(interpreter))
		fdput(interpreter);
	fdput(descriptor);
	return ret;
}

static bool t1os_native_exec_allowed(enum t1os_domain domain, const char *path)
{
	/* Brick's terminal deliberately runs user-selected Python source, while
	 * the package service runs its hash-verified private resolver and isolated
	 * import checks.  Permit only the immutable system interpreter and retain
	 * the caller's existing domain; no new authority is granted by this exec. */
	if (domain == T1OS_DOMAIN_BRICK ||
	    domain == T1OS_DOMAIN_PYTHON_SERVICE)
		return !strcmp(path, T1OS_PYTHON_BINARY);
	if (domain == T1OS_DOMAIN_CHROMIUM)
		return !strcmp(path, T1OS_CHROMIUM_BINARY) ||
		       !strcmp(path, T1OS_CHROMIUM_SANDBOX) ||
		       !strcmp(path, T1OS_CHROMIUM_XSERVER) ||
		       !strcmp(path, T1OS_CHROMIUM_WINDOWMANAGER) ||
		       !strcmp(path, T1OS_CHROMIUM_T1_WINDOWMANAGER) ||
		       !strcmp(path, T1OS_CHROMIUM_INPUT_BRIDGE) ||
		       !strcmp(path, T1OS_CHROMIUM_SUBPROCESS) ||
		       !strcmp(path, T1OS_CHROMIUM_DASH) ||
		       !strcmp(path, T1OS_CHROMIUM_XCLIP) ||
		       !strcmp(path, T1OS_CHROMIUM_XDOTOOL) ||
		       !strcmp(path, T1OS_CHROMIUM_XKBCOMP) ||
		       !strcmp(path, T1OS_CHROMIUM_XRANDR);
	if (domain == T1OS_DOMAIN_VIDEO)
		return !strcmp(path, T1OS_FFMPEG_BINARY) ||
		       !strcmp(path, T1OS_FFPROBE_BINARY) ||
		       !strcmp(path, T1OS_MEDIA_DECODER_DAEMON) ||
		       !strcmp(path, T1OS_VIDEO_DECODER_BINARY);
	if (domain == T1OS_DOMAIN_NETWORK)
		return !strcmp(path, T1OS_WIRELESS_ENGINE);
	if (domain == T1OS_DOMAIN_VIRTUALBOX)
		return !strcmp(path, T1OS_VIRTUALBOX_CLIENT) ||
		       !strcmp(path, T1OS_VIRTUALBOX_CLIPBOARD) ||
		       !strcmp(path, T1OS_VIRTUALBOX_SERVICE);
	return false;
}

static bool t1os_profiled_python_script(const struct linux_binprm *bprm)
{
	static const char interpreter[] =
		"#!\"/the one/software/python/bin/python\" -B";
	size_t length = sizeof(interpreter) - 1;

	if (!bprm || memcmp(bprm->buf, interpreter, length))
		return false;
	return bprm->buf[length] == '\n' ||
	       (bprm->buf[length] == '\r' && bprm->buf[length + 1] == '\n');
}

static void t1os_clear_pending(struct t1os_task_security *security)
{
	if (!security)
		return;
	security->pending_domain = T1OS_DOMAIN_UNTRUSTED;
	security->pending_device = 0;
	security->pending_inode = 0;
	security->pending_interpreter_device = 0;
	security->pending_interpreter_inode = 0;
	security->pending = false;
}

static int t1os_bprm_check(struct linux_binprm *bprm)
{
	struct t1os_task_security *security = t1os_task(current);
	struct t1os_cred_security *execsecurity;
	enum t1os_domain domain = t1os_task_domain(current);
	struct inode *inode;
	enum t1os_domain pending_domain = T1OS_DOMAIN_UNTRUSTED;
	dev_t pending_device = 0;
	unsigned long pending_inode = 0;
	dev_t pending_interpreter_device = 0;
	unsigned long pending_interpreter_inode = 0;
	bool pending = false;
	char *buffer, *path;
	int ret;

	if (!bprm || !bprm->file || !bprm->cred)
		return -EACCES;
	execsecurity = t1os_cred(bprm->cred);
	if (!execsecurity)
		return -ENOMEM;

	/* The same bprm is checked again after binfmt_script opens its fixed
	 * interpreter.  State lives in the transient exec cred, so a failed exec
	 * cannot leave a reusable authorization in the task. */
	if (execsecurity->state == T1OS_EXEC_SCRIPT) {
		buffer = (char *)__get_free_page(GFP_KERNEL);
		if (!buffer)
			return -ENOMEM;
		inode = file_inode(bprm->file);
		ret = t1os_file_path(bprm->file, buffer, &path);
		if (!ret && !strcmp(path, T1OS_PYTHON_BINARY) &&
		    inode->i_sb->s_dev == execsecurity->interpreter_device &&
		    inode->i_ino == execsecurity->interpreter_inode &&
		    S_ISREG(inode->i_mode) &&
		    uid_eq(inode->i_uid, GLOBAL_ROOT_UID) &&
		    inode->i_nlink == 1 &&
		    !(inode->i_mode & (S_IWGRP | S_IWOTH)))
			execsecurity->state = T1OS_EXEC_READY;
		else
			ret = ret ?: -EACCES;
		free_page((unsigned long)buffer);
		return ret;
	}
	if (execsecurity->state != T1OS_EXEC_NONE)
		return -EACCES;

	if (security && security->pending) {
		pending = true;
		pending_domain = security->pending_domain;
		pending_device = security->pending_device;
		pending_inode = security->pending_inode;
		pending_interpreter_device = security->pending_interpreter_device;
		pending_interpreter_inode = security->pending_interpreter_inode;
		t1os_clear_pending(security);
	}
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	ret = t1os_file_path(bprm->file, buffer, &path);
	if (ret)
		goto out;

	/* PID 1 is the sole root of trust. */
	if (current->pid == 1 && !strcmp(path, T1OS_PYTHON_BINARY)) {
		execsecurity->domain = T1OS_DOMAIN_GODDESS;
		execsecurity->cred_class = T1OS_CRED_ROOT;
		execsecurity->state = T1OS_EXEC_READY;
		ret = 0;
		goto out;
	}
	/* The initramfs bootstrap runs shell helpers such as mount and BusyBox before
	 * the T1OS root-of-trust handoff.  Keep the complete pre-runtime bootstrap
	 * out of the domain policy; the exact PID 1 Python branch above is the
	 * one-way boundary that activates enforcement. */
	if (!t1os_runtime_root_active()) {
		ret = 0;
		goto out;
	}
	/* Protected runtime paths are a write-integrity boundary.  Executable
	 * authority is independently restricted by the object and domain checks
	 * below; protected placement alone never grants execution. */
	if (t1os_is_forbidden_runtime_path(path)) {
		ret = -EACCES;
		goto out;
	}

	/* modprobe can only be reached by Driver Server or a kernel usermode
	 * helper.  Its resulting immutable domain is the only module reader. */
	if (!strcmp(path, T1OS_MODPROBE_BINARY)) {
		if (domain != T1OS_DOMAIN_DRIVER && current->mm) {
			ret = -EACCES;
			goto out;
		}
		execsecurity->domain = T1OS_DOMAIN_MODULE_LOADER;
		execsecurity->cred_class = T1OS_CRED_ROOT;
		execsecurity->state = T1OS_EXEC_READY;
		ret = 0;
		goto out;
	}

	if (pending) {
		inode = file_inode(bprm->file);
		if (inode->i_sb->s_dev != pending_device ||
		    inode->i_ino != pending_inode ||
		    !uid_eq(inode->i_uid, GLOBAL_ROOT_UID) ||
		    inode->i_nlink != 1 ||
		    (inode->i_mode & (S_IWGRP | S_IWOTH))) {
			ret = -EACCES;
			goto out;
		}
		if (t1os_unprivileged_launch(pending_domain, path))
			execsecurity->cred_class =
				pending_domain == T1OS_DOMAIN_CHROMIUM ?
				T1OS_CRED_CHROMIUM : T1OS_CRED_UNPRIVILEGED;
		else
			execsecurity->cred_class = T1OS_CRED_ROOT;
		/* bprm_creds_from_file performs the final class check after Linux has
		 * calculated setuid/file-capability credentials. */
		execsecurity->domain = pending_domain;
		if (t1os_profiled_python_script(bprm)) {
			if (!pending_interpreter_device || !pending_interpreter_inode) {
				ret = -EACCES;
				goto out;
			}
			execsecurity->interpreter_device =
				pending_interpreter_device;
			execsecurity->interpreter_inode = pending_interpreter_inode;
			execsecurity->state = T1OS_EXEC_SCRIPT;
		} else if (t1os_native_exec_allowed(pending_domain, path))
			execsecurity->state = T1OS_EXEC_READY;
		else {
			ret = -ENOEXEC;
			goto out;
		}
		ret = 0;
		goto out;
	}

	/* Fixed native children may retain a service domain.  All other execs
	 * are an irreversible demotion, even when exec later fails. */
	if (domain != T1OS_DOMAIN_UNTRUSTED &&
	    t1os_native_exec_allowed(domain, path)) {
		execsecurity->domain = domain;
		if (domain == T1OS_DOMAIN_CHROMIUM &&
		    !strcmp(path, T1OS_CHROMIUM_SANDBOX))
			execsecurity->cred_class = T1OS_CRED_CHROMIUM_SANDBOX;
		else if (domain == T1OS_DOMAIN_CHROMIUM)
			execsecurity->cred_class = T1OS_CRED_CHROMIUM;
		else if (t1os_unprivileged_creds(bprm->cred, false))
			execsecurity->cred_class = T1OS_CRED_UNPRIVILEGED;
		else
			execsecurity->cred_class = T1OS_CRED_ROOT;
		execsecurity->state = T1OS_EXEC_READY;
		ret = 0;
		goto out;
	}
	/* Domain demotion alone is not a sandbox: retaining uid 0/capabilities in
	 * an untrusted domain would leave many kernel attack surfaces available.
	 * Only an already capless, NNP uid1000 process may make an unprofiled exec. */
	if (domain == T1OS_DOMAIN_UNTRUSTED &&
	    t1os_unprivileged_creds(bprm->cred, false)) {
		execsecurity->domain = T1OS_DOMAIN_UNTRUSTED;
		execsecurity->cred_class = T1OS_CRED_UNPRIVILEGED;
		execsecurity->state = T1OS_EXEC_READY;
		ret = 0;
	} else {
		ret = -EACCES;
	}
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_bprm_creds_from_file(struct linux_binprm *bprm,
				     const struct file *file)
{
	struct t1os_cred_security *execsecurity;

	(void)file;
	if (!bprm || !bprm->cred)
		return -EACCES;
	if (!t1os_runtime_root_active())
		return 0;
	execsecurity = t1os_cred(bprm->cred);
	if (!execsecurity || execsecurity->state != T1OS_EXEC_READY)
		return -EACCES;
	return t1os_exec_cred_class_allowed(
		bprm, (enum t1os_cred_class)execsecurity->cred_class) ? 0 : -EACCES;
}

static void t1os_bprm_committing_creds(const struct linux_binprm *bprm)
{
	struct t1os_task_security *security = t1os_task(current);
	struct t1os_cred_security *execsecurity;

	if (!security || !bprm || !bprm->cred)
		return;
	execsecurity = t1os_cred(bprm->cred);
	if (!execsecurity || execsecurity->state != T1OS_EXEC_READY)
		return;
	if (!t1os_exec_cred_class_allowed(
		    bprm, (enum t1os_cred_class)execsecurity->cred_class)) {
		security->domain = T1OS_DOMAIN_UNTRUSTED;
		t1os_clear_pending(security);
		return;
	}
	security->domain = execsecurity->domain;
	t1os_clear_pending(security);
	if (execsecurity->domain == T1OS_DOMAIN_GODDESS)
		WRITE_ONCE(t1os_runtime_active, true);
}

static void t1os_bprm_committed_creds(const struct linux_binprm *bprm)
{
	(void)bprm;
	if (t1os_runtime_root_active() && current->mm)
		set_dumpable(current->mm, SUID_DUMP_DISABLE);
}

/* Guard the actual module and firmware read paths as well as their loaders. */
static int t1os_kernel_read_file(struct file *file,
				 enum kernel_read_file_id id,
				 bool contents)
{
	char *buffer = NULL, *path = NULL;
	struct inode *inode;
	int ret;

	(void)contents;
	if (!t1os_runtime_root_active())
		return 0;
	/* Signed modules are staged as .ko.zst.  Linux reports the compressed
	 * file read separately, but it has the same measured-loader authority as
	 * an uncompressed module.  All other kernel-read purposes remain denied. */
	if (id == READING_MODULE || id == READING_MODULE_COMPRESSED)
		return t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER) ? 0 : -EACCES;
	/* Driver Server executes the measured modprobe binary in the immutable
	 * module-loader domain before driver init calls request_firmware(). Some
	 * drivers defer that request to a kernel workqueue, so keep all three
	 * trusted stages eligible. The file checks below still constrain the read
	 * to a root-owned, single-linked firmware file in the packaged tree. */
	if (id != READING_FIRMWARE ||
	    (!t1os_is_driverserver_process() &&
	     !t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER) &&
	     !t1os_kernel_firmware_worker()) ||
	    !file)
		return -EACCES;
	buffer = (char *)__get_free_page(GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	ret = t1os_file_path(file, buffer, &path);
	if (ret)
		goto out;
	inode = file_inode(file);
	if (strncmp(path, "/the one/drivers/firmware/", 26) ||
	    !S_ISREG(inode->i_mode) ||
	    !uid_eq(inode->i_uid, GLOBAL_ROOT_UID) || inode->i_nlink != 1 ||
	    (inode->i_mode & (S_IWGRP | S_IWOTH)))
		ret = -EACCES;
out:
	free_page((unsigned long)buffer);
	return ret;
}

static int t1os_kernel_load_data(enum kernel_load_data_id id, bool contents)
{
	(void)contents;
	if (!t1os_runtime_root_active())
		return 0;
	if (id == LOADING_MODULE)
		return t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER) ? 0 : -EACCES;
	/* kexec images/initramfs, policy blobs and anonymous firmware buffers have
	 * no production runtime consumer.  File-backed firmware is handled above. */
	return -EACCES;
}

static bool t1os_application_domain(enum t1os_domain domain)
{
	return domain == T1OS_DOMAIN_UNTRUSTED ||
	       domain == T1OS_DOMAIN_EXPANSE ||
	       domain == T1OS_DOMAIN_DESKTOP || domain == T1OS_DOMAIN_BRICK ||
	       domain == T1OS_DOMAIN_VIDEO || domain == T1OS_DOMAIN_SETTINGS ||
	       domain == T1OS_DOMAIN_SNAP || domain == T1OS_DOMAIN_CHROMIUM ||
	       domain == T1OS_DOMAIN_PICKER ||
	       domain == T1OS_DOMAIN_LOCKSCREEN;
}

static int t1os_capable(const struct cred *cred, struct user_namespace *ns,
			int cap, unsigned int opts)
{
	enum t1os_domain domain = t1os_task_domain(current);

	(void)cred;
	(void)ns;
	(void)opts;
	if (!t1os_runtime_root_active())
		return 0;
	switch (cap) {
	case CAP_SYS_MODULE:
		return domain == T1OS_DOMAIN_MODULE_LOADER ? 0 : -EACCES;
	case CAP_SYS_TIME:
		return domain == T1OS_DOMAIN_OPERATIONS ? 0 : -EACCES;
	case CAP_SYS_BOOT:
		return domain == T1OS_DOMAIN_GODDESS ? 0 : -EACCES;
	case CAP_SYS_ADMIN:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_DRIVER ||
		       domain == T1OS_DOMAIN_VIRTUALBOX ||
		       (domain == T1OS_DOMAIN_CHROMIUM &&
			t1os_is_executable_process(T1OS_CHROMIUM_SANDBOX)) ? 0 : -EACCES;
	case CAP_NET_ADMIN:
	case CAP_NET_RAW:
		return domain == T1OS_DOMAIN_NETWORK ||
		       domain == T1OS_DOMAIN_DRIVER ||
		       (domain == T1OS_DOMAIN_CHROMIUM &&
			t1os_is_executable_process(T1OS_CHROMIUM_SANDBOX)) ? 0 : -EACCES;
	case CAP_SYS_RAWIO:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_SYS_PTRACE:
	case CAP_BPF:
	case CAP_PERFMON:
	case CAP_AUDIT_CONTROL:
		return -EACCES;
	case CAP_SYS_CHROOT:
		return domain == T1OS_DOMAIN_CHROMIUM &&
		       t1os_is_executable_process(T1OS_CHROMIUM_SANDBOX) ? 0 : -EACCES;
	case CAP_SETUID:
	case CAP_SETGID:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_STARTUP ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_CHROMIUM ? 0 : -EACCES;
	case CAP_SETPCAP:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_STARTUP ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_CHROMIUM ? 0 : -EACCES;
	case CAP_KILL:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_WINDOW ? 0 : -EACCES;
	case CAP_MKNOD:
		if (t1os_kernel_devtmpfs_worker())
			return 0;
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_SYSLOG:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_CHOWN:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_STARTUP ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_INPUT ||
		       domain == T1OS_DOMAIN_PYTHON_SERVICE ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_DAC_OVERRIDE:
	case CAP_FOWNER:
	case CAP_FSETID:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_STARTUP ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_DAC_READ_SEARCH:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_STARTUP ||
		       domain == T1OS_DOMAIN_OPERATIONS ? 0 : -EACCES;
	case CAP_NET_BIND_SERVICE:
	case CAP_NET_BROADCAST:
		return domain == T1OS_DOMAIN_NETWORK ? 0 : -EACCES;
	case CAP_IPC_OWNER:
	case CAP_IPC_LOCK:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_SYS_TTY_CONFIG:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	case CAP_SYS_RESOURCE:
	case CAP_SYS_NICE:
		return domain == T1OS_DOMAIN_GODDESS ||
		       domain == T1OS_DOMAIN_OPERATIONS ||
		       domain == T1OS_DOMAIN_WINDOW ||
		       domain == T1OS_DOMAIN_AUDIO ||
		       domain == T1OS_DOMAIN_DRIVER ? 0 : -EACCES;
	default:
		/* No ambient MAC, audit, keyring, lease, wake-alarm, immutable-file,
		 * checkpoint/restore, ownership or namespace capability.  New runtime
		 * consumers must be added here as an exact domain/capability decision. */
		return -EACCES;
	}
}

static int t1os_settime(const struct timespec64 *ts,
			const struct timezone *tz)
{
	(void)ts;
	(void)tz;
	if (!t1os_runtime_root_active())
		return 0;
	return t1os_domain_is(T1OS_DOMAIN_OPERATIONS) ? 0 : -EACCES;
}

static int t1os_task_kill(struct task_struct *p,
			  struct kernel_siginfo *info,
			  int sig, const struct cred *cred)
{
	enum t1os_domain source = t1os_task_domain(current);
	enum t1os_domain target;

	(void)info;
	(void)sig;
	(void)cred;
	if (!p)
		return -ESRCH;
	if (p == current)
		return 0;
	target = t1os_task_domain(p);
	if (source == T1OS_DOMAIN_GODDESS)
		return 0;
	if (source == T1OS_DOMAIN_OPERATIONS && t1os_application_domain(target))
		return 0;
	if (source == T1OS_DOMAIN_WINDOW && t1os_application_domain(target))
		return 0;
	if ((source == T1OS_DOMAIN_DRIVER || source == T1OS_DOMAIN_STARTUP) &&
	    target == T1OS_DOMAIN_BOOT_ANIMATION)
		return 0;
	if (source == T1OS_DOMAIN_DRIVER &&
	    target == T1OS_DOMAIN_MODULE_LOADER)
		return 0;
	if (source != T1OS_DOMAIN_UNTRUSTED && source == target)
		return 0;
	return -EACCES;
}

static int t1os_ptrace_access_check(struct task_struct *child,
				    unsigned int mode)
{
	enum t1os_domain source, target;
	unsigned int access;

	if (!t1os_runtime_root_active())
		return 0;
	if (!child)
		return -ESRCH;
	access = mode & (PTRACE_MODE_READ | PTRACE_MODE_ATTACH |
			 PTRACE_MODE_FSCREDS | PTRACE_MODE_REALCREDS);
	if (access != PTRACE_MODE_READ_FSCREDS &&
	    access != PTRACE_MODE_READ_REALCREDS)
		return -EACCES;
	source = t1os_task_domain(current);
	target = t1os_task_domain(child);
	switch (source) {
	case T1OS_DOMAIN_GODDESS:
	case T1OS_DOMAIN_OPERATIONS:
	case T1OS_DOMAIN_WINDOW:
	case T1OS_DOMAIN_DRIVER:
	case T1OS_DOMAIN_INPUT:
	case T1OS_DOMAIN_PYTHON_SERVICE:
		return 0;
	case T1OS_DOMAIN_CHROMIUM:
		return target == T1OS_DOMAIN_CHROMIUM ? 0 : -EACCES;
	default:
		return -EACCES;
	}
}

static int t1os_ptrace_traceme(struct task_struct *parent)
{
	(void)parent;
	return t1os_runtime_root_active() ? -EACCES : 0;
}

static int t1os_getprocattr(struct task_struct *task, const char *name,
			    char **value)
{
	const char *domain;

	if (!task || !name || !value || strcmp(name, "current"))
		return -EINVAL;
	domain = t1os_domain_name(t1os_task_domain(task));
	*value = kasprintf(GFP_KERNEL, "t1os:%s\n", domain);
	if (!*value)
		return -ENOMEM;
	return strlen(*value);
}

static struct security_hook_list t1os_hooks[] = {
	/* Path-based structural operations */
	LSM_HOOK_INIT(path_unlink,        t1os_path_unlink),
	LSM_HOOK_INIT(path_rmdir,         t1os_path_rmdir),
	LSM_HOOK_INIT(path_mkdir,         t1os_path_mkdir),
	LSM_HOOK_INIT(path_mknod,         t1os_path_mknod),
	LSM_HOOK_INIT(path_truncate,      t1os_path_truncate),
	LSM_HOOK_INIT(path_symlink,       t1os_path_symlink),
	LSM_HOOK_INIT(path_link,          t1os_path_link),
	LSM_HOOK_INIT(path_rename,        t1os_path_rename),
	LSM_HOOK_INIT(path_chmod,         t1os_path_chmod),
	LSM_HOOK_INIT(path_chown,         t1os_path_chown),
	LSM_HOOK_INIT(path_chroot,        t1os_path_chroot),
	LSM_HOOK_INIT(sb_mount,           t1os_sb_mount),
	LSM_HOOK_INIT(sb_umount,          t1os_sb_umount),
	LSM_HOOK_INIT(sb_pivotroot,       t1os_sb_pivotroot),
	LSM_HOOK_INIT(move_mount,         t1os_move_mount),

	/* Existing hooks */
	LSM_HOOK_INIT(file_open,          t1os_file_open),
	LSM_HOOK_INIT(file_permission,    t1os_file_perm),
	LSM_HOOK_INIT(file_truncate,      t1os_file_truncate),
	LSM_HOOK_INIT(file_receive,       t1os_file_receive),
	LSM_HOOK_INIT(mmap_file,          t1os_mmap_file),
	LSM_HOOK_INIT(file_mprotect,      t1os_file_mprotect),
	LSM_HOOK_INIT(inode_setattr,      t1os_inode_setattr),
	LSM_HOOK_INIT(inode_setxattr,     t1os_inode_setxattr),
	LSM_HOOK_INIT(inode_removexattr,  t1os_inode_removexattr),
	LSM_HOOK_INIT(file_ioctl,         t1os_file_ioctl),
	LSM_HOOK_INIT(file_ioctl_compat,  t1os_file_ioctl),
	LSM_HOOK_INIT(task_alloc,         t1os_task_alloc),
	LSM_HOOK_INIT(task_prctl,         t1os_task_prctl),
	LSM_HOOK_INIT(getprocattr,        t1os_getprocattr),
	LSM_HOOK_INIT(bprm_check_security,t1os_bprm_check),
	LSM_HOOK_INIT(bprm_creds_from_file,t1os_bprm_creds_from_file),
	LSM_HOOK_INIT(bprm_committing_creds,t1os_bprm_committing_creds),
	LSM_HOOK_INIT(bprm_committed_creds,t1os_bprm_committed_creds),
	LSM_HOOK_INIT(kernel_load_data, t1os_kernel_load_data),
	LSM_HOOK_INIT(kernel_read_file,t1os_kernel_read_file),
	LSM_HOOK_INIT(capable,            t1os_capable),
	LSM_HOOK_INIT(settime,            t1os_settime),
	LSM_HOOK_INIT(task_kill,          t1os_task_kill),
	LSM_HOOK_INIT(ptrace_access_check,t1os_ptrace_access_check),
	LSM_HOOK_INIT(ptrace_traceme,     t1os_ptrace_traceme),
};

static struct lsm_id t1os_lsm_id = {
	.name = "t1os",
	.id = LSM_ID_T1OS_LOCAL,
};

static int __init t1os_lsm_init(void)
{
	security_add_hooks(t1os_hooks,
			   ARRAY_SIZE(t1os_hooks),
			   &t1os_lsm_id);
	pr_info("T1OS LSM loaded: immutable process domains active\n");
	return 0;
}

DEFINE_LSM(t1os) = {
	.id = &t1os_lsm_id,
	.blobs = &t1os_blob_sizes,
	.init = t1os_lsm_init,
};

