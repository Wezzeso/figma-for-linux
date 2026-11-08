/* Figma's dedicated Firefox profile: relay TouchEgg pinch motion to GTK.
 *
 * Build: gcc -std=c11 -O2 -Wall -Wextra -fPIC -shared -o figma-pinch.so \
 *              figma-pinch.c -ldl -lm
 * Opt in ONLY from the Figma launcher: FIGMA_NATIVE_PINCH=1 LD_PRELOAD=...
 * No input device grabs, keyboard synthesis, or page/script injection.
 *
 * GTK 3's public GdkEventTouchpadPinch ABI is declared below so the build does
 * not require development packages. Mozilla's nsWindow.cpp uses the same
 * structure in its GTK compatibility block and SynthesizeNativeTouchPadPinch.
 * https://raw.githubusercontent.com/mozilla-firefox/firefox/main/widget/gtk/nsWindow.cpp
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

typedef void GdkWindow;
typedef void GdkDisplay;
typedef void GdkDevice;
typedef void GdkScreen;
typedef void GVariant;
typedef void GDBusConnection;
typedef int gboolean;
typedef struct { unsigned domain; int code; char *message; } GError;
typedef struct {
    int type;
    GdkWindow *window;
    int8_t send_event, phase, n_fingers;
    uint32_t time;
    double x, y, dx, dy, angle_delta, scale, x_root, y_root;
    unsigned state;
} PinchEvent;

_Static_assert(offsetof(PinchEvent, scale) == 64, "GTK 3 pinch ABI requires 64-bit Linux");
_Static_assert(sizeof(PinchEvent) == 96, "Unexpected GTK 3 pinch ABI");

#define DECL(ret, name, args) static ret (*p_##name) args
DECL(unsigned, g_timeout_add, (unsigned, int (*)(void *), void *));
DECL(void *, g_object_ref, (void *));
DECL(void, g_object_unref, (void *));
DECL(void, g_error_free, (GError *));
DECL(int64_t, g_get_monotonic_time, (void));
DECL(const char *, g_variant_get_type_string, (GVariant *));
DECL(void, g_variant_get, (GVariant *, const char *, ...));
DECL(unsigned long, g_signal_connect_data, (void *, const char *, void (*)(void), void *, void (*)(void *, void *), unsigned));
DECL(void *, g_settings_new, (const char *));
DECL(int, g_settings_get_boolean, (void *, const char *));
DECL(void, g_dbus_connection_new_for_address, (const char *, unsigned, void *, void *, void (*)(void *, void *, void *), void *));
DECL(GDBusConnection *, g_dbus_connection_new_for_address_finish, (void *, GError **));
DECL(int, g_dbus_connection_is_closed, (GDBusConnection *));
DECL(void, g_dbus_connection_set_exit_on_close, (GDBusConnection *, int));
DECL(unsigned, g_dbus_connection_signal_subscribe, (GDBusConnection *, const char *, const char *, const char *, const char *, const char *, unsigned, void (*)(void *, const char *, const char *, const char *, const char *, GVariant *, void *), void *, void (*)(void *)));
DECL(GdkDisplay *, gdk_display_get_default, (void));
DECL(GdkScreen *, gdk_display_get_default_screen, (GdkDisplay *));
DECL(void *, gdk_display_get_device_manager, (GdkDisplay *));
DECL(GdkDevice *, gdk_device_manager_get_client_pointer, (void *));
DECL(GdkWindow *, gdk_device_get_window_at_position, (GdkDevice *, int *, int *));
DECL(void, gdk_device_get_position, (GdkDevice *, GdkScreen **, int *, int *));
DECL(GdkWindow *, gdk_window_get_toplevel, (GdkWindow *));
DECL(void, gdk_window_get_user_data, (GdkWindow *, void **));
DECL(GdkWindow *, gdk_screen_get_active_window, (GdkScreen *));
DECL(unsigned long, gdk_x11_window_get_xid, (GdkWindow *));
DECL(int, gdk_window_is_destroyed, (GdkWindow *));
DECL(GdkWindow *, gdk_window_get_device_position, (GdkWindow *, GdkDevice *, int *, int *, unsigned *));
DECL(void *, gdk_event_new, (int));
DECL(void, gdk_event_put, (const void *));
DECL(void, gdk_event_free, (void *));
DECL(void, gdk_event_set_device, (void *, GdkDevice *));
DECL(void, gdk_event_set_source_device, (void *, GdkDevice *));
DECL(unsigned, g_unix_fd_add, (int, unsigned, int (*)(int, unsigned, void *), void *));
DECL(void, g_main_context_invoke, (void *, int (*)(void *), void *));

static GDBusConnection *connection;
static GdkDisplay *display;
static GdkDevice *pointer;
static void *settings;
static GdkWindow *target, *target_top;
static double anchor_x, anchor_y, root_x, root_y, last_percentage, scale;
static int direction_sign, connecting, loaded, ready, eligible, diagnostics;
static int64_t last_motion_us;
static char marker_path[512], diagnostic_path[512];
static int diagnostic_fd = -1;
static const double gain = 0.007875;

static void log_message(const char *message) {
    fprintf(stderr, "Figma pinch: %s\n", message);
}

static int main_figma_process(void) {
    const char *opt_in = getenv("FIGMA_NATIVE_PINCH");
    const char *profile_path = getenv("FIGMA_NATIVE_PROFILE");
    if (!opt_in || strcmp(opt_in, "1") || !profile_path) return 0;
    char expected[512], command[16384];
    if (snprintf(expected, sizeof expected, "%s", profile_path) >= (int)sizeof expected) return 0;
    int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, command, sizeof command - 1);
    close(fd);
    if (n <= 0) return 0;
    command[n] = '\0';
    int profile = 0, figma_class = 0;
    for (char *arg = command; arg < command + n;) {
        char *next = arg + strlen(arg) + 1;
        if (!strcmp(arg, "-contentproc") || !strcmp(arg, "--contentproc") || strstr(arg, "crashhelper")) return 0;
        if (!strcmp(arg, "--profile") && next < command + n && !strcmp(next, expected)) profile = 1;
        if (!strcmp(arg, "--class") && next < command + n && !strcmp(next, "Figma")) figma_class = 1;
        arg = next;
    }
    return profile && figma_class;
}

static void remove_marker(void) {
    if (!marker_path[0]) return;
    char buffer[64];
    int fd = open(marker_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return;
    ssize_t n = read(fd, buffer, sizeof buffer - 1);
    close(fd);
    if (n > 0) {
        buffer[n] = '\0';
        if (strtol(buffer, NULL, 10) == (long)getpid()) unlink(marker_path);
    }
}

static int write_marker(void) {
    char temporary[560], text[64];
    snprintf(temporary, sizeof temporary, "%s.%ld.tmp", marker_path, (long)getpid());
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return 0;
    int length = snprintf(text, sizeof text, "%ld\n", (long)getpid());
    int ok = write(fd, text, (size_t)length) == length;
    close(fd);
    if (ok && rename(temporary, marker_path) == 0) return 1;
    unlink(temporary);
    return 0;
}

static void emit_phase(int phase) {
    if (!target || p_gdk_window_is_destroyed(target)) return;
    PinchEvent *event = p_gdk_event_new(42); /* GDK_TOUCHPAD_PINCH */
    if (!event) return;
    event->window = p_g_object_ref(target);
    event->send_event = 0;
    event->phase = (int8_t)phase;
    event->n_fingers = 2;
    event->time = 0; /* GDK_CURRENT_TIME, as in Firefox native synthesis */
    event->x = anchor_x;
    event->y = anchor_y;
    event->dx = event->dy = event->angle_delta = 0;
    event->scale = scale;
    event->x_root = root_x;
    event->y_root = root_y;
    event->state = 0;
    p_gdk_event_set_device(event, pointer);
    p_gdk_event_set_source_device(event, pointer);
    p_gdk_event_put(event);
    p_gdk_event_free(event);
}

static void finish_gesture(void) {
    if (!target) return;
    /* Firefox treats END as a zero-delta cleanup. CANCEL is ignored by its
     * handler, so use END on focus loss too; it cannot change the zoom. */
    emit_phase(2);
    p_g_object_unref(target);
    p_g_object_unref(target_top);
    target = target_top = NULL;
}

static GdkWindow *valid_pointer_window(int *x, int *y) {
    if (!display || !pointer) return NULL;
    GdkWindow *window = p_gdk_device_get_window_at_position(pointer, x, y);
    if (!window || p_gdk_window_is_destroyed(window)) return NULL;
    GdkWindow *top = p_gdk_window_get_toplevel(window);
    void *widget = NULL;
    p_gdk_window_get_user_data(top, &widget);
    /* Foreign X11 windows have no GTK widget in this process. */
    if (!widget) return NULL;
    GdkScreen *screen = p_gdk_display_get_default_screen(display);
    GdkWindow *active = p_gdk_screen_get_active_window(screen);
    if (!active) return NULL;
    int focused = p_gdk_x11_window_get_xid(active) == p_gdk_x11_window_get_xid(top);
    p_g_object_unref(active);
    unsigned state = 0;
    p_gdk_window_get_device_position(window, pointer, NULL, NULL, &state);
    /* Ignore Caps/Num Lock; avoid all held shortcut modifiers and buttons. */
    if (!focused || (state & 0x1fedu)) return NULL;
    return window;
}

static void feed_gesture(unsigned phase, unsigned direction, double percentage) {
    if (!ready || !isfinite(percentage) || (direction != 5 && direction != 6)) return;
    int x, y;
    GdkWindow *window = valid_pointer_window(&x, &y);
    if (phase == 0) {
        finish_gesture();
        if (!window) return;
        target = p_g_object_ref(window);
        target_top = p_g_object_ref(p_gdk_window_get_toplevel(window));
        anchor_x = x;
        anchor_y = y;
        int rx, ry;
        p_gdk_device_get_position(pointer, NULL, &rx, &ry);
        root_x = rx;
        root_y = ry;
        scale = 1;
        last_percentage = percentage;
        direction_sign = direction == 6 ? 1 : -1;
        last_motion_us = p_g_get_monotonic_time();
        emit_phase(0);
        if (diagnostics) log_message("pinch begin");
        return;
    }
    if (!target) return;
    if (!window || p_gdk_window_is_destroyed(target) || p_gdk_window_get_toplevel(window) != target_top) {
        finish_gesture();
        return;
    }
    if (phase != 1 && phase != 2) return;
    double delta = (percentage - last_percentage) * direction_sign;
    last_percentage = percentage;
    last_motion_us = p_g_get_monotonic_time();
    /* Treat invalid discontinuities as a cancelled gesture, never a burst. */
    if (fabs(delta) > 100) {
        finish_gesture();
        return;
    }
    if (delta != 0) {
        scale = fmax(0.05, fmin(20.0, scale * exp(delta * gain)));
        emit_phase(1);
    }
    if (phase == 2) {
        if (diagnostics) fprintf(stderr, "Figma pinch: pinch end scale=%.6f\n", scale);
        finish_gesture();
    }
}

static void gesture_signal(void *bus, const char *sender, const char *path,
                           const char *interface, const char *member,
                           GVariant *parameters, void *data) {
    (void)bus; (void)sender; (void)path; (void)interface; (void)data;
    if (strcmp(p_g_variant_get_type_string(parameters), "(uudiut)")) return;
    uint32_t kind, direction, device;
    int fingers;
    double percentage;
    uint64_t elapsed;
    p_g_variant_get(parameters, "(uudiut)", &kind, &direction, &percentage, &fingers, &device, &elapsed);
    if (kind != 2 || fingers != 2 || device != 1) return;
    if (!strcmp(member, "OnGestureBegin")) feed_gesture(0, direction, percentage);
    else if (!strcmp(member, "OnGestureUpdate")) feed_gesture(1, direction, percentage);
    else if (!strcmp(member, "OnGestureEnd")) feed_gesture(2, direction, percentage);
}

static void connection_closed(void *bus, int remote, void *error, void *data) {
    (void)bus; (void)remote; (void)error; (void)data;
    ready = 0;
    remove_marker();
    finish_gesture();
    log_message("TouchEgg disconnected; keyboard fallback restored");
}

static void connection_finished(void *source, void *result, void *data) {
    (void)source; (void)data;
    GError *error = NULL;
    connecting = 0;
    connection = p_g_dbus_connection_new_for_address_finish(result, &error);
    if (!connection) {
        if (error) p_g_error_free(error);
        return;
    }
    p_g_dbus_connection_set_exit_on_close(connection, 0);
    p_g_signal_connect_data(connection, "closed", (void (*)(void))connection_closed, NULL, NULL, 0);
    p_g_dbus_connection_signal_subscribe(connection, NULL, "io.github.joseexposito.Touchegg", NULL,
        "/io/github/joseexposito/Touchegg", NULL, 0, gesture_signal, NULL, NULL);
    log_message("connected to TouchEgg motion stream");
}

static int resolve_api(void) {
#define LOAD(name) do { *(void **)(&p_##name) = dlsym(RTLD_DEFAULT, #name); if (!p_##name) return 0; } while (0)
    LOAD(g_object_ref); LOAD(g_object_unref); LOAD(g_error_free);
    LOAD(g_get_monotonic_time); LOAD(g_variant_get_type_string); LOAD(g_variant_get);
    LOAD(g_signal_connect_data); LOAD(g_settings_new); LOAD(g_settings_get_boolean);
    LOAD(g_dbus_connection_new_for_address); LOAD(g_dbus_connection_new_for_address_finish);
    LOAD(g_dbus_connection_is_closed); LOAD(g_dbus_connection_set_exit_on_close);
    LOAD(g_dbus_connection_signal_subscribe); LOAD(gdk_display_get_default);
    LOAD(gdk_display_get_default_screen); LOAD(gdk_display_get_device_manager);
    LOAD(gdk_device_manager_get_client_pointer); LOAD(gdk_device_get_window_at_position);
    LOAD(gdk_device_get_position); LOAD(gdk_window_get_toplevel);
    LOAD(gdk_window_get_user_data);
    LOAD(gdk_screen_get_active_window); LOAD(gdk_x11_window_get_xid);
    LOAD(gdk_window_is_destroyed); LOAD(gdk_window_get_device_position);
    LOAD(gdk_event_new); LOAD(gdk_event_put); LOAD(gdk_event_free);
    LOAD(gdk_event_set_device); LOAD(gdk_event_set_source_device);
    LOAD(g_unix_fd_add); LOAD(g_main_context_invoke);
#undef LOAD
    return 1;
}

static int diagnostic_input(int fd, unsigned condition, void *data) {
    (void)condition; (void)data;
    char text[128], tail;
    unsigned phase, direction;
    double percentage;
    ssize_t n;
    while ((n = recv(fd, text, sizeof text - 1, MSG_DONTWAIT)) > 0) {
        text[n] = '\0';
        if (sscanf(text, "%u %u %lf %c", &phase, &direction, &percentage, &tail) == 3)
            feed_gesture(phase, direction, percentage);
    }
    return 1;
}

static void open_diagnostic_socket(void) {
    if (!diagnostics || diagnostic_fd >= 0) return;
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    if (strlen(diagnostic_path) >= sizeof address.sun_path) return;
    strcpy(address.sun_path, diagnostic_path);
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) return;
    /* A PID suffix prevents removing another process's diagnostic endpoint. */
    if (bind(fd, (struct sockaddr *)&address, sizeof address) < 0) { close(fd); return; }
    chmod(diagnostic_path, 0600);
    diagnostic_fd = fd;
    p_g_unix_fd_add(fd, 1, diagnostic_input, NULL); /* G_IO_IN */
    log_message("diagnostic socket enabled");
}

static int maintenance(void *data) {
    (void)data;
    if (!loaded) {
        if (!resolve_api()) return 1;
        display = p_gdk_display_get_default();
        if (!display) return 1;
        pointer = p_gdk_device_manager_get_client_pointer(p_gdk_display_get_device_manager(display));
        if (!pointer) return 1;
        settings = p_g_settings_new("org.cinnamon.gestures");
        loaded = 1;
        log_message("GTK native pinch relay initialized");
    }
    int enabled = settings && p_g_settings_get_boolean(settings, "enabled");
    if (connection && p_g_dbus_connection_is_closed(connection)) {
        ready = 0;
        remove_marker();
        finish_gesture();
        p_g_object_unref(connection);
        connection = NULL;
    }
    if (!connection && !connecting && enabled) {
        connecting = 1;
        p_g_dbus_connection_new_for_address("unix:abstract=touchegg", 1, NULL, NULL, connection_finished, NULL);
    }
    int new_ready = enabled && connection && !p_g_dbus_connection_is_closed(connection);
    if (new_ready && !ready) {
        ready = write_marker();
        if (ready) log_message("ready: continuous two-finger native pinch");
    } else if (!new_ready && ready) {
        ready = 0;
        remove_marker();
        finish_gesture();
    }
    if (target) {
        int x, y;
        GdkWindow *current = valid_pointer_window(&x, &y);
        if (!current || p_gdk_window_get_toplevel(current) != target_top ||
            p_g_get_monotonic_time() - last_motion_us > 3000000)
            finish_gesture();
    }
    if (ready) open_diagnostic_socket();
    return 1;
}

/* Optional in-process diagnostics. Safe to call from any thread: feeds the
 * exact same code on GTK's default main context. Disabled in normal launches. */
struct diagnostic_event { unsigned phase, direction; double percentage; };
static int diagnostic_on_main(void *data) {
    struct diagnostic_event *event = data;
    feed_gesture(event->phase, event->direction, event->percentage);
    free(event);
    return 0;
}
__attribute__((visibility("default")))
int figma_pinch_test(unsigned phase, unsigned direction, double percentage) {
    if (!eligible || !diagnostics || !loaded || !ready || phase > 2 ||
        (direction != 5 && direction != 6) || !isfinite(percentage)) return 0;
    struct diagnostic_event *event = malloc(sizeof *event);
    if (!event) return 0;
    *event = (struct diagnostic_event){phase, direction, percentage};
    p_g_main_context_invoke(NULL, diagnostic_on_main, event);
    return 1;
}

__attribute__((constructor)) static void initialize(void) {
    if (!(eligible = main_figma_process())) return;
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    char fallback[64];
    if (!runtime) {
        snprintf(fallback, sizeof fallback, "/run/user/%lu", (unsigned long)getuid());
        runtime = fallback;
    }
    struct stat info;
    if (stat(runtime, &info) || !S_ISDIR(info.st_mode) || info.st_uid != getuid()) return;
    if (snprintf(marker_path, sizeof marker_path, "%s/figma-native-pinch.ready", runtime) >= (int)sizeof marker_path) return;
    diagnostics = getenv("FIGMA_PINCH_DIAGNOSTICS") && !strcmp(getenv("FIGMA_PINCH_DIAGNOSTICS"), "1");
    snprintf(diagnostic_path, sizeof diagnostic_path, "%s/figma-pinch-test-%ld.sock", runtime, (long)getpid());
    /* Loading GLib is safe before GTK; callback only runs after Firefox enters
     * the main context. No worker thread, early GTK call, or blocking DBus IO. */
    void *glib = dlopen("libglib-2.0.so.0", RTLD_LAZY | RTLD_GLOBAL);
    if (!glib) return;
    *(void **)(&p_g_timeout_add) = dlsym(glib, "g_timeout_add");
    if (p_g_timeout_add) p_g_timeout_add(250, maintenance, NULL);
}

__attribute__((destructor)) static void cleanup(void) {
    if (!eligible) return;
    remove_marker();
    if (diagnostic_fd >= 0) {
        close(diagnostic_fd);
        unlink(diagnostic_path);
    }
    /* Firefox owns GTK teardown ordering; do not call GTK from a destructor. */
}
