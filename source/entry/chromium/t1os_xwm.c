#define _GNU_SOURCE

#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <unistd.h>

typedef struct _XDisplay Display;
typedef unsigned long XID;
typedef XID Window;
typedef XID Atom;
typedef XID Drawable;
typedef XID Damage;
typedef XID XserverRegion;
typedef XID Time;
typedef int Bool;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Window window;
} XAnyEvent;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Window parent;
	Window window;
} XMapRequestEvent;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Window parent;
	Window window;
	int x;
	int y;
	int width;
	int height;
	int border_width;
	Window above;
	int detail;
	unsigned long value_mask;
} XConfigureRequestEvent;

typedef union {
	char b[20];
	short s[10];
	long l[5];
} XClientMessageData;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Window window;
	Atom message_type;
	int format;
	XClientMessageData data;
} XClientMessageEvent;

typedef struct {
	short x;
	short y;
	unsigned short width;
	unsigned short height;
} XRectangle;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Drawable drawable;
	Damage damage;
	int level;
	Bool more;
	Time timestamp;
	XRectangle area;
	XRectangle geometry;
} XDamageNotifyEvent;

typedef struct {
	int type;
	unsigned long serial;
	Bool send_event;
	Display *display;
	Window window;
	int subtype;
	unsigned long cursor_serial;
	Time timestamp;
	Atom cursor_name;
} XFixesCursorNotifyEvent;

typedef struct {
	short x;
	short y;
	unsigned short width;
	unsigned short height;
	unsigned short xhot;
	unsigned short yhot;
	unsigned long cursor_serial;
	unsigned long *pixels;
	Atom atom;
	const char *name;
} XFixesCursorImage;

typedef union {
	int type;
	XAnyEvent xany;
	XMapRequestEvent xmaprequest;
	XConfigureRequestEvent xconfigurerequest;
	XClientMessageEvent xclient;
	XDamageNotifyEvent xdamage;
	XFixesCursorNotifyEvent xcursor;
	long pad[24];
} XEvent;

typedef struct {
	int x;
	int y;
	int width;
	int height;
	int border_width;
	Window sibling;
	int stack_mode;
} XWindowChanges;

typedef struct {
	int type;
	Display *display;
	XID resourceid;
	unsigned long serial;
	unsigned char error_code;
	unsigned char request_code;
	unsigned char minor_code;
} XErrorEvent;

extern Display *XOpenDisplay(const char *);
extern int XCloseDisplay(Display *);
extern Window XDefaultRootWindow(Display *);
extern int XDefaultScreen(Display *);
extern int XDisplayWidth(Display *, int);
extern int XDisplayHeight(Display *, int);
extern int XConnectionNumber(Display *);
extern int XPending(Display *);
extern int XSelectInput(Display *, Window, long);
extern int XSync(Display *, Bool);
extern int XNextEvent(Display *, XEvent *);
extern int XMapWindow(Display *, Window);
extern int XRaiseWindow(Display *, Window);
extern int XSetInputFocus(Display *, Window, int, Time);
extern int XConfigureWindow(Display *, Window, unsigned int, XWindowChanges *);
extern int XMoveResizeWindow(Display *, Window, int, int, unsigned int, unsigned int);
extern int XGetGeometry(
	Display *, Window, Window *, int *, int *, unsigned int *, unsigned int *,
	unsigned int *, unsigned int *);
extern Atom XInternAtom(Display *, const char *, Bool);
extern int XChangeProperty(
	Display *, Window, Atom, Atom, int, int, const unsigned char *, int);
extern Window XCreateSimpleWindow(
	Display *, Window, int, int, unsigned int, unsigned int, unsigned int,
	unsigned long, unsigned long);
extern int XStoreName(Display *, Window, const char *);
extern int XFlush(Display *);
extern char *XGetAtomName(Display *, Atom);
extern int XFree(void *);
extern int (*XSetErrorHandler(int (*)(Display *, XErrorEvent *)))(
	Display *, XErrorEvent *);
extern Bool XDamageQueryExtension(Display *, int *, int *);
extern Damage XDamageCreate(Display *, Drawable, int);
extern void XDamageSubtract(Display *, Damage, XserverRegion, XserverRegion);
extern Bool XFixesQueryExtension(Display *, int *, int *);
extern int XFixesQueryVersion(Display *, int *, int *);
extern void XFixesSelectCursorInput(Display *, Window, unsigned long);
extern XFixesCursorImage *XFixesGetCursorImage(Display *);

enum {
	MAP_REQUEST = 20,
	CONFIGURE_REQUEST = 23,
	CLIENT_MESSAGE = 33,
};

enum {
	CWX = 1U << 0,
	CWY = 1U << 1,
	CW_WIDTH = 1U << 2,
	CW_HEIGHT = 1U << 3,
	CW_BORDER_WIDTH = 1U << 4,
	CW_SIBLING = 1U << 5,
	CW_STACK_MODE = 1U << 6,
};

enum {
	SUBSTRUCTURE_NOTIFY_MASK = 1L << 19,
	SUBSTRUCTURE_REDIRECT_MASK = 1L << 20,
	PROPERTY_CHANGE_MASK = 1L << 22,
	PROP_MODE_REPLACE = 0,
	REVERT_TO_POINTER_ROOT = 1,
	/*
	 * Report every rectangle which expands the accumulated damage region.
	 * NON_EMPTY reports only the empty-to-nonempty transition, so a disjoint
	 * repaint which arrives before our batched subtract can otherwise be
	 * cleared without ever being announced to the compositor.
	 */
	XDAMAGE_REPORT_DELTA_RECTANGLES = 1,
};

enum {
	XFIXES_CURSOR_NOTIFY = 1,
	XFIXES_DISPLAY_CURSOR_NOTIFY_MASK = 1L << 0,
};

enum {
	NET_WM_STATE_REMOVE = 0,
	NET_WM_STATE_ADD = 1,
	NET_WM_STATE_TOGGLE = 2,
};

static volatile sig_atomic_t running = 1;
static int xerror = 0;
static Display *display;
static Window root;
static Atom net_wm_state;
static Atom net_wm_state_fullscreen;
static Atom net_active_window;
static Window fullscreen_window;
static int damage_event_base = -1;
static int cursor_event_base = -1;
static int restore_x;
static int restore_y;
static unsigned int restore_width;
static unsigned int restore_height;

enum {
	DAMAGE_BATCH_LIMIT = 32,
};

typedef struct {
	int left;
	int top;
	int right;
	int bottom;
} DamageRect;

static DamageRect damage_batch[DAMAGE_BATCH_LIMIT];
static int damage_batch_count;

static void stop(int signal_number)
{
	(void)signal_number;
	running = 0;
}

static int xerrorhandler(Display *connection, XErrorEvent *event)
{
	(void)connection;
	xerror = event ? event->error_code : 1;
	return 0;
}

static int announce_ready(void)
{
	const char *path = getenv("T1OS_XWM_READY");
	static const char ready[] = "ready\n";
	int descriptor;
	ssize_t written;

	if (!path || path[0] != '/')
		return -1;
	descriptor = open(
		path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
		0600);
	if (descriptor < 0)
		return -1;
	written = write(descriptor, ready, sizeof(ready) - 1U);
	if (close(descriptor) != 0 || written != (ssize_t)(sizeof(ready) - 1U))
		return -1;
	return 0;
}

static void set_atoms(Window window, Atom property, const Atom *atoms, int count)
{
	Atom atom_type = XInternAtom(display, "ATOM", 0);

	XChangeProperty(
		display, window, property, atom_type, 32, PROP_MODE_REPLACE,
		(const unsigned char *)atoms, count);
}

static void set_window(Window window, Atom property, Window value)
{
	Atom window_type = XInternAtom(display, "WINDOW", 0);

	XChangeProperty(
		display, window, property, window_type, 32, PROP_MODE_REPLACE,
		(const unsigned char *)&value, 1);
}

static int message_has_fullscreen(const XClientMessageEvent *event)
{
	return (Atom)event->data.l[1] == net_wm_state_fullscreen ||
	       (Atom)event->data.l[2] == net_wm_state_fullscreen;
}

static void announce_fullscreen(int enabled)
{
	/*
	 * Complete the X11 state transition before its notification becomes
	 * visible to the parent. The parent may immediately resize the private
	 * Chromium window through a second X connection.
	 */
	XSync(display, 0);
	printf("FULLSCREEN %d\n", enabled ? 1 : 0);
	fflush(stdout);
}

static void announce_cursor(const XFixesCursorNotifyEvent *event)
{
	XFixesCursorImage *image = NULL;
	char *atom_name = NULL;
	const char *source = NULL;
	char name[128];
	size_t index;

	if (event->cursor_name) {
		atom_name = XGetAtomName(display, event->cursor_name);
		source = atom_name;
	}
	if (source && source[0]) {
		for (index = 0; source[index] && index + 1U < sizeof(name); index++) {
			unsigned char value = (unsigned char)source[index];

			if (!((value >= 'a' && value <= 'z') ||
			      (value >= 'A' && value <= 'Z') ||
			      (value >= '0' && value <= '9') ||
			      value == '_' || value == '-'))
				value = '_';
			name[index] = (char)value;
		}
		name[index] = '\0';
		printf("CURSOR %s\n", name);
	} else {
		uint64_t hash = UINT64_C(1469598103934665603);
		uint32_t values[4];
		size_t pixel_count;

		image = XFixesGetCursorImage(display);
		if (!image || !image->pixels || image->width == 0 || image->height == 0) {
			printf("CURSOR default\n");
		} else {
			values[0] = image->width;
			values[1] = image->height;
			values[2] = image->xhot;
			values[3] = image->yhot;
			for (index = 0; index < 4; index++) {
				hash ^= values[index];
				hash *= UINT64_C(1099511628211);
			}
			pixel_count = (size_t)image->width * (size_t)image->height;
			for (index = 0; index < pixel_count; index++) {
				hash ^= (uint32_t)image->pixels[index];
				hash *= UINT64_C(1099511628211);
			}
			printf(
				"CURSOR_IMAGE %u %u %u %u %016llx\n",
				image->width, image->height, image->xhot, image->yhot,
				(unsigned long long)hash);
		}
	}
	fflush(stdout);
	if (atom_name)
		XFree(atom_name);
	if (image)
		XFree(image);
}

static void leave_fullscreen(Window window)
{
	if (fullscreen_window != window)
		return;
	set_atoms(window, net_wm_state, NULL, 0);
	XMoveResizeWindow(
		display, window, restore_x, restore_y,
		restore_width > 0 ? restore_width : 1,
		restore_height > 0 ? restore_height : 1);
	fullscreen_window = 0;
	announce_fullscreen(0);
}

static void enter_fullscreen(Window window)
{
	Window unused_root;
	unsigned int border;
	unsigned int depth;
	Atom states[1];
	if (fullscreen_window == window)
		return;
	if (fullscreen_window)
		leave_fullscreen(fullscreen_window);
	if (!XGetGeometry(
		    display, window, &unused_root, &restore_x, &restore_y,
		    &restore_width, &restore_height, &border, &depth)) {
		restore_x = 0;
		restore_y = 0;
		restore_width = 1280;
		restore_height = 900;
	}
	fullscreen_window = window;
	states[0] = net_wm_state_fullscreen;
	set_atoms(window, net_wm_state, states, 1);
	/*
	 * The Xvfb root is the maximum allocation, not the current logical output.
	 * Preserve the current backing size until the T1OS parent sends its exact
	 * aspect-preserving ENGINEW/H resize.
	 */
	XMoveResizeWindow(
		display, window, 0, 0,
		restore_width > 0 ? restore_width : 1,
		restore_height > 0 ? restore_height : 1);
	XRaiseWindow(display, window);
	XSetInputFocus(display, window, REVERT_TO_POINTER_ROOT, 0);
	announce_fullscreen(1);
}

static void handle_state(const XClientMessageEvent *event)
{
	long action;
	int enabled;

	if (!message_has_fullscreen(event))
		return;
	action = event->data.l[0];
	enabled = fullscreen_window == event->window;
	if (action == NET_WM_STATE_TOGGLE)
		action = enabled ? NET_WM_STATE_REMOVE : NET_WM_STATE_ADD;
	if (action == NET_WM_STATE_ADD)
		enter_fullscreen(event->window);
	else if (action == NET_WM_STATE_REMOVE)
		leave_fullscreen(event->window);
}

static void handle_configure(const XConfigureRequestEvent *event)
{
	XWindowChanges changes;
	unsigned int mask;

	if (fullscreen_window == event->window) {
		/*
		 * This private display has one trusted Chromium client. While EWMH
		 * fullscreen is active, accept only its requested backing dimensions;
		 * keep the origin pinned and retain the pre-fullscreen restore geometry.
		 */
		memset(&changes, 0, sizeof(changes));
		changes.x = 0;
		changes.y = 0;
		changes.width = event->width;
		changes.height = event->height;
		mask = (unsigned int)event->value_mask & (CW_WIDTH | CW_HEIGHT);
		if (mask)
			XConfigureWindow(display, event->window, mask, &changes);
		return;
	}
	memset(&changes, 0, sizeof(changes));
	changes.x = event->x;
	changes.y = event->y;
	changes.width = event->width;
	changes.height = event->height;
	changes.border_width = event->border_width;
	changes.sibling = event->above;
	changes.stack_mode = event->detail;
	mask = (unsigned int)event->value_mask &
	       (CWX | CWY | CW_WIDTH | CW_HEIGHT | CW_BORDER_WIDTH |
		CW_SIBLING | CW_STACK_MODE);
	XConfigureWindow(display, event->window, mask, &changes);
}

static int damage_rects_touch(const DamageRect *left, const DamageRect *right)
{
	return left->left <= right->right && right->left <= left->right &&
	       left->top <= right->bottom && right->top <= left->bottom;
}

static void queue_damage(const XDamageNotifyEvent *event)
{
	DamageRect incoming;
	int index;

	if (event->area.width == 0 || event->area.height == 0) {
		XDamageSubtract(display, event->damage, 0, 0);
		return;
	}
	/*
	 * XDamage already includes the drawable geometry in the notification.
	 * Using it avoids an XGetGeometry round trip for every repaint rectangle.
	 */
	incoming.left = (int)event->geometry.x + (int)event->area.x;
	incoming.top = (int)event->geometry.y + (int)event->area.y;
	incoming.right = incoming.left + (int)event->area.width;
	incoming.bottom = incoming.top + (int)event->area.height;

	index = 0;
	while (index < damage_batch_count) {
		DamageRect *existing = &damage_batch[index];

		if (!damage_rects_touch(&incoming, existing)) {
			index++;
			continue;
		}
		if (existing->left < incoming.left)
			incoming.left = existing->left;
		if (existing->top < incoming.top)
			incoming.top = existing->top;
		if (existing->right > incoming.right)
			incoming.right = existing->right;
		if (existing->bottom > incoming.bottom)
			incoming.bottom = existing->bottom;
		damage_batch[index] = damage_batch[--damage_batch_count];
		index = 0;
	}
	if (damage_batch_count == DAMAGE_BATCH_LIMIT) {
		for (index = 0; index < damage_batch_count; index++) {
			DamageRect *existing = &damage_batch[index];

			if (existing->left < incoming.left)
				incoming.left = existing->left;
			if (existing->top < incoming.top)
				incoming.top = existing->top;
			if (existing->right > incoming.right)
				incoming.right = existing->right;
			if (existing->bottom > incoming.bottom)
				incoming.bottom = existing->bottom;
		}
		damage_batch_count = 0;
	}
	damage_batch[damage_batch_count++] = incoming;
	XDamageSubtract(display, event->damage, 0, 0);
}

static void flush_damage(void)
{
	int index;

	if (damage_batch_count == 0)
		return;
	/*
	 * Fence Xvfb once for the complete event batch. The parent can then read
	 * every announced rectangle from one completed shared-screen state.
	 */
	XSync(display, 0);
	for (index = 0; index < damage_batch_count; index++) {
		const DamageRect *rect = &damage_batch[index];

		if (rect->right <= rect->left || rect->bottom <= rect->top)
			continue;
		printf(
			"DAMAGE %d %d %u %u\n",
			rect->left,
			rect->top,
			(unsigned int)(rect->right - rect->left),
			(unsigned int)(rect->bottom - rect->top));
	}
	fflush(stdout);
	damage_batch_count = 0;
}

static void initialise_ewmh(void)
{
	Window support;
	Atom supporting;
	Atom supported;
	Atom utf8;
	Atom name;
	Atom capabilities[3];
	static const char wm_name[] = "T1OS Chromium bridge";

	supporting = XInternAtom(display, "_NET_SUPPORTING_WM_CHECK", 0);
	supported = XInternAtom(display, "_NET_SUPPORTED", 0);
	utf8 = XInternAtom(display, "UTF8_STRING", 0);
	name = XInternAtom(display, "_NET_WM_NAME", 0);
	net_wm_state = XInternAtom(display, "_NET_WM_STATE", 0);
	net_wm_state_fullscreen =
		XInternAtom(display, "_NET_WM_STATE_FULLSCREEN", 0);
	net_active_window = XInternAtom(display, "_NET_ACTIVE_WINDOW", 0);
	support = XCreateSimpleWindow(display, root, -1, -1, 1, 1, 0, 0, 0);
	set_window(root, supporting, support);
	set_window(support, supporting, support);
	capabilities[0] = net_wm_state;
	capabilities[1] = net_wm_state_fullscreen;
	capabilities[2] = net_active_window;
	set_atoms(root, supported, capabilities, 3);
	XChangeProperty(
		display, support, name, utf8, 8, PROP_MODE_REPLACE,
		(const unsigned char *)wm_name, (int)strlen(wm_name));
	XStoreName(display, support, wm_name);
}

int main(void)
{
	XEvent event;
	int damage_error_base;
	int cursor_error_base;
	int cursor_major = 2;
	int cursor_minor = 0;

	signal(SIGINT, stop);
	signal(SIGTERM, stop);
	display = XOpenDisplay(NULL);
	if (!display) {
		fputs("T1OS Chromium XWM: cannot open the private X display\n", stderr);
		return 1;
	}
	root = XDefaultRootWindow(display);
	XSetErrorHandler(xerrorhandler);
	XSelectInput(
		display, root,
		SUBSTRUCTURE_REDIRECT_MASK | SUBSTRUCTURE_NOTIFY_MASK |
			PROPERTY_CHANGE_MASK);
	XSync(display, 0);
	if (xerror) {
		fprintf(stderr, "T1OS Chromium XWM: another window manager owns the display (%d)\n",
			xerror);
		XCloseDisplay(display);
		return 1;
	}
	initialise_ewmh();
	if (!XDamageQueryExtension(
		    display, &damage_event_base, &damage_error_base)) {
		fputs("T1OS Chromium XWM: XDamage is unavailable\n", stderr);
		XCloseDisplay(display);
		return 1;
	}
	if (!XFixesQueryExtension(
		    display, &cursor_event_base, &cursor_error_base)) {
		fputs("T1OS Chromium XWM: XFixes is unavailable\n", stderr);
		XCloseDisplay(display);
		return 1;
	}
	if (!XFixesQueryVersion(display, &cursor_major, &cursor_minor) ||
	    cursor_major < 2) {
		fputs("T1OS Chromium XWM: XFixes cursor names are unavailable\n", stderr);
		XCloseDisplay(display);
		return 1;
	}
	XFixesSelectCursorInput(
		display, root, XFIXES_DISPLAY_CURSOR_NOTIFY_MASK);
	XFlush(display);
	if (announce_ready() != 0) {
		fputs("T1OS Chromium XWM: cannot publish readiness\n", stderr);
		XCloseDisplay(display);
		return 1;
	}
	fputs("T1OS Chromium XWM ready\n", stderr);

	while (running) {
		int connection = XConnectionNumber(display);
		int batch_events = 0;

		/*
		 * XNextEvent may remain blocked after SIGTERM on some libX11 builds.
		 * Poll the connection with a short bound so closing a T1OS browser
		 * window cannot inherit the helper's shutdown timeout.
		 */
		while (running && XPending(display) == 0) {
			fd_set readers;
			struct timeval timeout;
			int selected;

			FD_ZERO(&readers);
			FD_SET(connection, &readers);
			timeout.tv_sec = 0;
			timeout.tv_usec = 100000;
			selected = select(
				connection + 1, &readers, NULL, NULL, &timeout);
			if (selected < 0 && errno != EINTR) {
				running = 0;
				break;
			}
		}
		if (!running)
			break;
		do {
			if (XNextEvent(display, &event) != 0) {
				running = 0;
				break;
			}
			batch_events++;
			if (event.type == MAP_REQUEST) {
				XMapWindow(display, event.xmaprequest.window);
				XDamageCreate(
					display, event.xmaprequest.window,
					XDAMAGE_REPORT_DELTA_RECTANGLES);
				XRaiseWindow(display, event.xmaprequest.window);
				XSetInputFocus(
					display, event.xmaprequest.window,
					REVERT_TO_POINTER_ROOT, 0);
				printf("WINDOW %lu\n", event.xmaprequest.window);
				fflush(stdout);
			} else if (event.type == CONFIGURE_REQUEST) {
				handle_configure(&event.xconfigurerequest);
			} else if (
				event.type == CLIENT_MESSAGE &&
				event.xclient.message_type == net_wm_state) {
				handle_state(&event.xclient);
			} else if (
				event.type == CLIENT_MESSAGE &&
				event.xclient.message_type == net_active_window) {
				XRaiseWindow(display, event.xclient.window);
				XSetInputFocus(
					display, event.xclient.window,
					REVERT_TO_POINTER_ROOT, 0);
			} else if (event.type == damage_event_base) {
				queue_damage(&event.xdamage);
			} else if (event.type == cursor_event_base + XFIXES_CURSOR_NOTIFY) {
				announce_cursor(&event.xcursor);
			}
		} while (
			running && batch_events < 256 && XPending(display) > 0);
		flush_damage();
		XFlush(display);
	}

	XCloseDisplay(display);
	return 0;
}
