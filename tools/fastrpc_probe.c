/* fastrpc_probe.c - minimal raw ioctl probe for /dev/fastrpc-cdsp.
 *
 * Goal: separate kernel/DSP-level failures from libcdsprpc userspace logic.
 * It intentionally does NOT link libcdsprpc; it only uses the kernel UAPI.
 *
 * Build on the phone:
 *   gcc -O0 -g -Wall -I/usr/src/linux-headers-$(uname -r)/include/uapi \
 *       -o /tmp/fastrpc_probe /tmp/fastrpc_probe.c
 *
 * Usage:
 *   /tmp/fastrpc_probe /dev/fastrpc-cdsp            # full: caps, attach, create
 *   /tmp/fastrpc_probe /dev/fastrpc-cdsp noattach   # skip INIT_ATTACH
 *   /tmp/fastrpc_probe /dev/fastrpc-cdsp createonly # only GET_DSP_INFO + create
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <misc/fastrpc.h>

static void show(const char *name, int rc)
{
    printf("%-32s rc=%-12d (0x%08x) errno=%-4d %s\n",
           name, rc, (unsigned int)rc, errno,
           rc ? strerror(errno) : "");
    fflush(stdout);
}

static void dump_create(const char *tag, const struct fastrpc_init_create *cr)
{
    printf("  %s: filelen=%u filefd=%d attrs=0x%x siglen=%u file=0x%llx\n",
           tag, cr->filelen, cr->filefd, cr->attrs, cr->siglen,
           (unsigned long long)cr->file);
}

int main(int argc, char **argv)
{
    const char *dev = (argc > 1) ? argv[1] : "/dev/fastrpc-cdsp";
    const char *mode = (argc > 2) ? argv[2] : "full";
    int noattach = !strcmp(mode, "noattach") || !strcmp(mode, "createonly");
    int fd, rc, i;
    struct fastrpc_ioctl_capability cap;
    struct fastrpc_init_create cr;

    fd = open(dev, O_RDWR | O_CLOEXEC);
    printf("DEVICE %s -> fd=%d errno=%d (%s) mode=%s\n",
           dev, fd, errno, strerror(errno), mode);
    fflush(stdout);
    if (fd < 0)
        return 1;

    if (strcmp(mode, "createonly")) {
        printf("\n--- capability sweep (FASTRPC_IOCTL_GET_DSP_INFO) ---\n");
        for (i = 0; i <= 8; i++) {
            memset(&cap, 0, sizeof(cap));
            cap.attribute_id = (unsigned int)i;
            errno = 0;
            rc = ioctl(fd, FASTRPC_IOCTL_GET_DSP_INFO, &cap);
            printf("  attr=%-2d rc=%-11d (0x%08x) capability=0x%08x errno=%d %s\n",
                   i, rc, (unsigned int)rc, cap.capability, errno,
                   rc ? strerror(errno) : "");
            fflush(stdout);
        }
    } else {
        memset(&cap, 0, sizeof(cap));
        cap.attribute_id = 0;
        errno = 0;
        rc = ioctl(fd, FASTRPC_IOCTL_GET_DSP_INFO, &cap);
        show("GET_DSP_INFO(attr=0)", rc);
    }

    if (!noattach) {
        printf("\n--- root PD attach ---\n");
        errno = 0;
        rc = ioctl(fd, FASTRPC_IOCTL_INIT_ATTACH, 0);
        show("INIT_ATTACH", rc);
    }

    printf("\n--- user PD create ---\n");
    memset(&cr, 0, sizeof(cr));
    cr.attrs = FASTRPC_MODE_UNSIGNED_MODULE;
    cr.filefd = -1;
    dump_create("INIT_CREATE(unsigned)", &cr);
    errno = 0;
    rc = ioctl(fd, FASTRPC_IOCTL_INIT_CREATE, &cr);
    show("  -> INIT_CREATE(unsigned)", rc);
    dump_create("  after", &cr);

    memset(&cr, 0, sizeof(cr));
    cr.filefd = -1;
    errno = 0;
    rc = ioctl(fd, FASTRPC_IOCTL_INIT_CREATE, &cr);
    show("  -> INIT_CREATE(signed)", rc);

    close(fd);
    printf("\nDONE\n");
    return 0;
}
