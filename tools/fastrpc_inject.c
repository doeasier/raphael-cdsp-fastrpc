/* fastrpc_inject.c - LD_PRELOAD experiment shim (zero on-disk config change).
 *
 * Controlled entirely by environment variables, so one .so can run a matrix:
 *
 *   FASTRPC_INJECT_REDIRECT=1  redirect open("/dev/fastrpc-*-secure") to the
 *                              non-secure sibling device node
 *   FASTRPC_INJECT_ATTACH=1    before the first INIT_CREATE (nr=5) on a fd,
 *                              issue INIT_ATTACH (nr=4) on that same fd
 *   FASTRPC_INJECT_IGNORE_ERR=0x80000453  if INIT_CREATE returns exactly this
 *                              value, rewrite it to 0 (success) so the
 *                              userspace stack continues. Use 0xffffffff
 *                              to accept ANY negative/nonzero DSP error.
 *   FASTRPC_INJECT_TRACE=1     log FastRPC ioctls to stderr
 *
 * Build: gcc -shared -fPIC -O0 -o /tmp/fastrpc_inject.so /tmp/fastrpc_inject.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

typedef int (*ioctl_fn)(int, unsigned long, ...);
typedef int (*openat_fn)(int, const char *, int, ...);

static ioctl_fn real_ioctl;
static openat_fn real_openat;
static int do_redirect, do_attach, do_trace;
static unsigned int ignore_err;
static int ignore_any;
static int attached[256];

#define NR_ATTACH 4
#define NR_CREATE 5

static void init(void)
{
    static int done;
    if (done)
        return;
    done = 1;
    real_ioctl = (ioctl_fn)dlsym(RTLD_NEXT, "ioctl");
    real_openat = (openat_fn)dlsym(RTLD_NEXT, "openat");
    do_redirect = getenv("FASTRPC_INJECT_REDIRECT") != NULL;
    do_attach = getenv("FASTRPC_INJECT_ATTACH") != NULL;
    do_trace = getenv("FASTRPC_INJECT_TRACE") != NULL;
    {
        const char *s = getenv("FASTRPC_INJECT_IGNORE_ERR");
        if (s) {
            ignore_err = (unsigned int)strtoul(s, NULL, 0);
            ignore_any = (ignore_err == 0xffffffffu);
        }
    }
}

int open(const char *path, int flags, ...)
{
    va_list ap;
    mode_t mode = 0;
    int rc;
    const char *use = path;
    char alt[256];

    init();
    if (do_redirect && path && strstr(path, "/dev/fastrpc-") &&
        strstr(path, "-secure")) {
        size_t n = strlen(path) - strlen("-secure");
        if (n < sizeof(alt)) {
            memcpy(alt, path, n);
            alt[n] = '\0';
            use = alt;
            if (do_trace)
                fprintf(stderr, "[REDIRECT] %s -> %s\n", path, use);
        }
    }
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        rc = real_openat(AT_FDCWD, use, flags, mode);
    } else {
        rc = real_openat(AT_FDCWD, use, flags);
    }
    if (do_trace && path && strstr(path, "fastrpc"))
        fprintf(stderr, "[OPEN] %s -> fd=%d\n", use, rc);
    return rc;
}

int open64(const char *path, int flags, ...)
{
    va_list ap;
    mode_t mode = 0;
    init();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        return open(path, flags, mode);
    }
    return open(path, flags);
}

int ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    int rc, saved, nr;

    init();
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);
    nr = (int)(req & 0xff);

    if (((req >> 8) & 0xff) == 'R' && do_attach && nr == NR_CREATE &&
        fd >= 0 && fd < 256 && !attached[fd]) {
        attached[fd] = 1;
        errno = 0;
        rc = real_ioctl(fd, 0x5204 /* FASTRPC_IOCTL_INIT_ATTACH */, 0);
        if (do_trace)
            fprintf(stderr, "[INJECT] INIT_ATTACH on fd=%d -> %d (0x%08x)\n",
                    fd, rc, (unsigned int)rc);
    }

    errno = 0;
    rc = real_ioctl(fd, req, arg);
    saved = errno;

    if (((req >> 8) & 0xff) == 'R' && nr == NR_CREATE && rc != 0 &&
        (ignore_any || (ignore_err && (unsigned int)rc == ignore_err))) {
        if (do_trace)
            fprintf(stderr, "[REWRITE] INIT_CREATE %d (0x%08x) -> 0\n",
                    rc, (unsigned int)rc);
        rc = 0;
        saved = 0;
    }

    if (((req >> 8) & 0xff) == 'R' && do_trace)
        fprintf(stderr, "[IOCTL] nr=%-3d fd=%d -> %d (0x%08x) errno=%d\n",
                nr, fd, rc, (unsigned int)rc, saved);
    errno = saved;
    return rc;
}
