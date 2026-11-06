/* ioctl_trace.c - LD_PRELOAD shim that logs every FastRPC ('R') ioctl.
 *
 * Use when strace is unavailable on the target:
 *   gcc -shared -fPIC -O0 -o /tmp/ioctl_trace.so /tmp/ioctl_trace.c -ldl
 *   LD_PRELOAD=/tmp/ioctl_trace.so LD_LIBRARY_PATH=/usr/local/lib ./host_main
 *
 * Only ioctls whose magic byte is 'R' (the FastRPC UAPI family) are logged,
 * so unrelated terminal/socket ioctls do not flood the output.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

typedef int (*ioctl_fn)(int, unsigned long, ...);
typedef int (*openat_fn)(int, const char *, int, ...);

static ioctl_fn real_ioctl;
static openat_fn real_openat;

static void init(void)
{
    if (!real_ioctl)
        real_ioctl = (ioctl_fn)dlsym(RTLD_NEXT, "ioctl");
    if (!real_openat)
        real_openat = (openat_fn)dlsym(RTLD_NEXT, "openat");
}

int ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    int rc, saved;

    init();
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);

    errno = 0;
    rc = real_ioctl(fd, req, arg);
    saved = errno;

    if (((req >> 8) & 0xff) == 'R') {
        unsigned long nr = req & 0xff;
        fprintf(stderr,
                "[IOCTL] fd=%-3d req=0x%04lx nr=%-3lu arg=%p -> rc=%-12d "
                "(0x%08x) errno=%d %s\n",
                fd, req, nr, arg, rc, (unsigned int)rc,
                saved, saved ? strerror(saved) : "");
        if (nr == 5 && arg) {           /* FASTRPC_IOCTL_INIT_CREATE */
            const unsigned int *w = (const unsigned int *)arg;
            fprintf(stderr,
                    "        create{filelen=%u, filefd=%d, attrs=0x%08x, "
                    "siglen=%u, file=0x%llx}\n",
                    w[0], (int)w[1], w[2], w[3],
                    (unsigned long long)(((unsigned long long)w[5] << 32) | w[4]));
        }
        if (nr == 13 && arg) {          /* FASTRPC_IOCTL_GET_DSP_INFO */
            const unsigned int *w = (const unsigned int *)arg;
            fprintf(stderr, "        cap{unused=%u, attr_id=%u, capability=0x%08x}\n",
                    w[0], w[1], w[2]);
        }
        if (nr == 10 && arg) {          /* FASTRPC_IOCTL_MEM_MAP */
            const unsigned int *w = (const unsigned int *)arg;
            fprintf(stderr,
                    "        memmap{version=%d, fd=%d, offset=%d, flags=0x%x, "
                    "length=%llu}\n",
                    (int)w[0], (int)w[1], (int)w[2], w[3],
                    (unsigned long long)(((unsigned long long)w[5] << 32) | w[4]));
        }
        fflush(stderr);
    }
    errno = saved;
    return rc;
}

int open(const char *path, int flags, ...)
{
    va_list ap;
    mode_t mode = 0;
    int rc;

    init();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        rc = (int)real_openat(AT_FDCWD, path, flags, mode);
    } else {
        rc = (int)real_openat(AT_FDCWD, path, flags);
    }
    if (path && strstr(path, "fastrpc"))
        fprintf(stderr, "[OPEN ] %-55s flags=0x%x -> fd=%d\n",
                path, (unsigned)flags, rc);
    return rc;
}

int openat(int dirfd, const char *path, int flags, ...)
{
    va_list ap;
    mode_t mode = 0;
    int rc;

    init();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        rc = real_openat(dirfd, path, flags, mode);
    } else {
        rc = real_openat(dirfd, path, flags);
    }
    if (path && (strstr(path, "fastrpc") || strstr(path, "cdsp") ||
                 strstr(path, "/dev/") ))
        fprintf(stderr, "[OPEN ] %-55s flags=0x%x -> fd=%d\n",
                path, (unsigned)flags, rc);
    return rc;
}
