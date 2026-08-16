#define _GNU_SOURCE

#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

#define T1OS_LIBXDO "/the one/software/chromium/libraries/libxdo.so.3"
#define T1OS_LIBX11 "/the one/software/chromium/libraries/libX11.so.6"
#define CURRENTWINDOW 0UL
#define MAX_INPUT_BYTES (1024U * 1024U)
#define MAX_COMMAND_BYTES (MAX_INPUT_BYTES * 2U + 2U)
#define COMMAND_BUFFER_BYTES (MAX_COMMAND_BYTES + 2U)
#define X11_SUCCESS 0
#define X11_ANY_PROPERTY_TYPE 0UL

typedef void xdo_t;
typedef void xdisplay_t;
typedef unsigned long xdo_window_t;
typedef unsigned long xatom_t;

struct xdo_api {
	void *library;
	xdo_t *(*new_context)(const char *);
	void (*free_context)(xdo_t *);
	int (*move_mouse)(const xdo_t *, int, int, int);
	int (*mouse_down)(const xdo_t *, xdo_window_t, int);
	int (*mouse_up)(const xdo_t *, xdo_window_t, int);
	int (*click_window)(const xdo_t *, xdo_window_t, int);
	int (*enter_text)(const xdo_t *, xdo_window_t, const char *, useconds_t);
	int (*send_key)(const xdo_t *, xdo_window_t, const char *, useconds_t);
	int (*set_window_size)(const xdo_t *, xdo_window_t, int, int, int);
	int (*move_window)(const xdo_t *, xdo_window_t, int, int);
	int (*activate_window)(const xdo_t *, xdo_window_t);
	int (*focus_window)(const xdo_t *, xdo_window_t);
	int (*raise_window)(const xdo_t *, xdo_window_t);
	int (*close_window)(const xdo_t *, xdo_window_t);
};

struct x11_api {
	void *library;
	xdisplay_t *(*open_display)(const char *);
	int (*close_display)(xdisplay_t *);
	xatom_t (*intern_atom)(xdisplay_t *, const char *, int);
	int (*get_window_property)(
		xdisplay_t *, xdo_window_t, xatom_t, long, long, int, xatom_t,
		xatom_t *, int *, unsigned long *, unsigned long *, unsigned char **);
	int (*free_data)(void *);
};

static int load_symbol(void *library, const char *name, void **target)
{
	const char *error;

	dlerror();
	*target = dlsym(library, name);
	error = dlerror();
	if (error || !*target) {
		fprintf(stderr, "T1OS chromium input: missing %s: %s\n",
			name, error ? error : "unknown error");
		return -1;
	}
	return 0;
}

#define LOAD(api, member, symbol) \
	load_symbol((api)->library, (symbol), (void **)&(api)->member)

static int load_api(struct xdo_api *api)
{
	memset(api, 0, sizeof(*api));
	api->library = dlopen(T1OS_LIBXDO, RTLD_NOW | RTLD_LOCAL);
	if (!api->library) {
		fprintf(stderr, "T1OS chromium input: could not load libxdo: %s\n",
			dlerror());
		return -1;
	}
	if (LOAD(api, new_context, "xdo_new") ||
	    LOAD(api, free_context, "xdo_free") ||
	    LOAD(api, move_mouse, "xdo_move_mouse") ||
	    LOAD(api, mouse_down, "xdo_mouse_down") ||
	    LOAD(api, mouse_up, "xdo_mouse_up") ||
	    LOAD(api, click_window, "xdo_click_window") ||
	    LOAD(api, enter_text, "xdo_enter_text_window") ||
	    LOAD(api, send_key, "xdo_send_keysequence_window") ||
	    LOAD(api, set_window_size, "xdo_set_window_size") ||
	    LOAD(api, move_window, "xdo_move_window") ||
	    LOAD(api, activate_window, "xdo_activate_window") ||
	    LOAD(api, focus_window, "xdo_focus_window") ||
	    LOAD(api, raise_window, "xdo_raise_window") ||
	    LOAD(api, close_window, "xdo_close_window"))
		return -1;
	return 0;
}

static int load_x11_api(struct x11_api *api)
{
	memset(api, 0, sizeof(*api));
	api->library = dlopen(T1OS_LIBX11, RTLD_NOW | RTLD_LOCAL);
	if (!api->library) {
		fprintf(stderr, "T1OS chromium input: could not load libX11: %s\n",
			dlerror());
		return -1;
	}
	if (LOAD(api, open_display, "XOpenDisplay") ||
	    LOAD(api, close_display, "XCloseDisplay") ||
	    LOAD(api, intern_atom, "XInternAtom") ||
	    LOAD(api, get_window_property, "XGetWindowProperty") ||
	    LOAD(api, free_data, "XFree"))
		return -1;
	return 0;
}

static int window_is_fullscreen(
	struct x11_api *api, xdisplay_t *display, xdo_window_t window)
{
	xatom_t state_atom;
	xatom_t fullscreen_atom;
	xatom_t actual_type = 0;
	int actual_format = 0;
	unsigned long count = 0;
	unsigned long remaining = 0;
	unsigned char *data = NULL;
	unsigned long index;
	int fullscreen = 0;

	state_atom = api->intern_atom(display, "_NET_WM_STATE", 0);
	fullscreen_atom = api->intern_atom(
		display, "_NET_WM_STATE_FULLSCREEN", 0);
	if (!state_atom || !fullscreen_atom)
		return 0;
	if (api->get_window_property(
		    display, window, state_atom, 0, 64, 0,
		    X11_ANY_PROPERTY_TYPE, &actual_type, &actual_format,
		    &count, &remaining, &data) != X11_SUCCESS)
		return 0;
	if (data && actual_format == 32) {
		unsigned long *atoms = (unsigned long *)data;

		for (index = 0; index < count; index++) {
			if (atoms[index] == fullscreen_atom) {
				fullscreen = 1;
				break;
			}
		}
	}
	if (data)
		api->free_data(data);
	return fullscreen;
}

static int hex_value(char character)
{
	if (character >= '0' && character <= '9')
		return character - '0';
	character = (char)tolower((unsigned char)character);
	if (character >= 'a' && character <= 'f')
		return character - 'a' + 10;
	return -1;
}

static char *decode_hex(const char *encoded)
{
	size_t encoded_length = strlen(encoded);
	size_t index;
	char *decoded;

	if ((encoded_length & 1U) != 0 ||
	    encoded_length > MAX_INPUT_BYTES * 2U)
		return NULL;
	decoded = calloc(encoded_length / 2U + 1U, 1U);
	if (!decoded)
		return NULL;
	for (index = 0; index < encoded_length; index += 2U) {
		int high = hex_value(encoded[index]);
		int low = hex_value(encoded[index + 1U]);

		if (high < 0 || low < 0) {
			free(decoded);
			return NULL;
		}
		decoded[index / 2U] = (char)((high << 4) | low);
	}
	return decoded;
}

static int parse_window(const char *text, xdo_window_t *window)
{
	char *end = NULL;
	unsigned long value;

	errno = 0;
	value = strtoul(text, &end, 10);
	if (errno || !end || *end != '\0')
		return -1;
	*window = value;
	return 0;
}

static int handle_command(
	struct xdo_api *api, xdo_t *context, struct x11_api *x11,
	xdisplay_t *display, char *line)
{
	int x, y, button, width, height;
	xdo_window_t window;
	char *cursor;

	if (sscanf(line, "M %d %d", &x, &y) == 2)
		return api->move_mouse(context, x, y, 0);
	if (sscanf(line, "D %d", &button) == 1)
		return api->mouse_down(context, CURRENTWINDOW, button);
	if (sscanf(line, "U %d", &button) == 1)
		return api->mouse_up(context, CURRENTWINDOW, button);
	if (sscanf(line, "C %d", &button) == 1)
		return api->click_window(context, CURRENTWINDOW, button);
	if (line[0] == 'K' && line[1] == ' ') {
		cursor = line + 2;
		if (!*cursor || strlen(cursor) > 256U)
			return -1;
		return api->send_key(context, CURRENTWINDOW, cursor, 0);
	}
	if (line[0] == 'T' && line[1] == ' ') {
		char *decoded = decode_hex(line + 2);
		int result;

		if (!decoded)
			return -1;
		result = api->enter_text(context, CURRENTWINDOW, decoded, 0);
		free(decoded);
		return result;
	}
	if (sscanf(line, "W %lu %d %d", &window, &width, &height) == 3) {
		int result = api->set_window_size(context, window, width, height, 0);

		if (result == 0)
			result = api->move_window(context, window, 0, 0);
		return result;
	}
	if (sscanf(line, "S %lu", &window) == 1) {
		printf("FULLSCREEN %d\n",
		       window_is_fullscreen(x11, display, window));
		fflush(stdout);
		return 0;
	}
	if ((line[0] == 'F' || line[0] == 'Q') && line[1] == ' ') {
		cursor = line + 2;
		if (parse_window(cursor, &window) != 0)
			return -1;
		if (line[0] == 'Q')
			return api->close_window(context, window);
		if (api->activate_window(context, window) != 0 &&
		    api->focus_window(context, window) != 0)
			return -1;
		return api->raise_window(context, window);
	}
	return -1;
}

int main(void)
{
	struct xdo_api api;
	struct x11_api x11;
	xdo_t *context;
	xdisplay_t *xdisplay;
	const char *display = getenv("DISPLAY");
	char *line;
	size_t length;

	if (load_api(&api) != 0)
		return 1;
	if (load_x11_api(&x11) != 0) {
		dlclose(api.library);
		return 1;
	}
	context = api.new_context(display);
	if (!context) {
		fprintf(stderr, "T1OS chromium input: could not connect to display %s\n",
			display ? display : "(default)");
		dlclose(x11.library);
		dlclose(api.library);
		return 1;
	}
	xdisplay = x11.open_display(display);
	if (!xdisplay) {
		fprintf(stderr, "T1OS chromium input: libX11 could not connect to display %s\n",
			display ? display : "(default)");
		api.free_context(context);
		dlclose(x11.library);
		dlclose(api.library);
		return 1;
	}
	line = malloc(COMMAND_BUFFER_BYTES);
	if (!line) {
		fputs("T1OS chromium input: could not allocate command buffer\n",
		      stderr);
		x11.close_display(xdisplay);
		api.free_context(context);
		dlclose(x11.library);
		dlclose(api.library);
		return 1;
	}
	fputs("READY\n", stdout);
	fflush(stdout);
	fprintf(stderr, "T1OS chromium input bridge ready\n");
	while (fgets(line, (int)COMMAND_BUFFER_BYTES, stdin)) {
		length = strlen(line);
		/*
		 * Python accepts one MiB of UTF-8 paste data and transmits it as
		 * "T " plus two hexadecimal characters per byte. Keep one fixed
		 * buffer large enough for that exact command and its newline. If
		 * fgets fills the spare byte without seeing a newline, the record is
		 * larger than the protocol permits; exit without ever allocating in
		 * proportion to an untrusted line.
		 */
		if (length == MAX_COMMAND_BYTES + 1U &&
		    line[length - 1U] != '\n') {
			fprintf(stderr, "T1OS chromium input: command exceeds limit\n");
			break;
		}
		while (length > 0 &&
		       (line[length - 1] == '\n' || line[length - 1] == '\r'))
			line[--length] = '\0';
		if (length == 0)
			continue;
		if (strcmp(line, "P") == 0) {
			fputs("PONG\n", stdout);
			fflush(stdout);
			continue;
		}
		if (handle_command(&api, context, &x11, xdisplay, line) != 0)
			fprintf(stderr, "T1OS chromium input: command failed: %.120s\n",
				line);
	}
	free(line);
	x11.close_display(xdisplay);
	api.free_context(context);
	dlclose(x11.library);
	dlclose(api.library);
	return 0;
}
