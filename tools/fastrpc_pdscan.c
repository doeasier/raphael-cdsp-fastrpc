/* fastrpc_pdscan.c - raw UAPI PD-creation scanner (NO libcdsprpc, NO shim).
 *
 * Why this replaces the "suppress nr=10" idea:
 *   - kernel fastrpc_init_create_process() never calls fastrpc_req_mem_map();
 *   - cdsprpcd never issues INIT_CREATE (it only does INIT_ATTACH + MEM_MAP for
 *     reverse RPC on the ROOT_PD session);
 *   - therefore suppressing MEM_MAP in the daemon has no direct causal link to
 *     INIT_CREATE in the client process, and faking a successful MEM_MAP would
 *     insert a bogus vaddrout=0 mapping (same class of failure as PR#319 v2).
 *
 * This probe sends ONE PD-creation ioctl per process, so each measurement is
 * independent and cannot be polluted by an earlier create on the same fd.
 *
 * Build on device:
 *   gcc -O0 -g -Wall \
 *     -I/usr/src/linux-headers-$(uname -r)/include/uapi \
 *     -o /opt/rootpd-exp/fastrpc_pdscan /opt/rootpd-exp/fastrpc_pdscan.c
 *
 * Usage:
 *   fastrpc_pdscan <dev> attach|noattach <attrs-hex> [static]
 *     attrs-hex  0x8 = unsigned (RMID7), 0 = signed (RMID6)
 *     static     use FASTRPC_IOCTL_INIT_CREATE_STATIC (nr=9 / RMID8) instead
 *
 * Output is one line per step with KEY=VALUE, easy to diff across runs.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <misc/fastrpc.h>

static void report(const char *tag, int rc)
{
    printf("%-24s RC=%d RC_HEX=0x%08x ERRNO=%d %s\n", tag, rc,
           (unsigned int)rc, errno, rc ? strerror(errno) : "");
    fflush(stdout);
}

int main(int argc, char **argv)
{
    const char *dev = (argc > 1) ? argv[1] : "/dev/fastrpc-cdsp";
    const char *attach_mode = (argc > 2) ? argv[2] : "noattach";
    unsigned int attrs = (argc > 3) ? (unsigned int)strtoul(argv[3], NULL, 0) : 0x8;
    int do_static = (argc > 4) && !strcmp(argv[4], "static");
    int do_attach = !strcmp(attach_mode, "attach");
    struct fastrpc_ioctl_capability cap;
    struct fastrpc_init_create cr;
    struct fastrpc_init_create_static st;
    static const char pdname[] = "pdscan";
    int fd, rc;

    fd = open(dev, O_RDWR | O_CLOEXEC);
    printf("DEVICE=%s FD=%d PID=%d ATTACH=%s ATTRS=0x%x STATIC=%d\n",
           dev, fd, (int)getpid(), attach_mode, attrs, do_static);
    fflush(stdout);
    if (fd < 0) {
        report("OPEN", fd);
        return 1;
    }

    memset(&cap, 0, sizeof(cap));
    cap.attribute_id = 0;
    errno = 0;
    rc = ioctl(fd, FASTRPC_IOCTL_GET_DSP_INFO, &cap);
    printf("GET_DSP_INFO_CAP=0x%08x ", cap.capability);
    report("GET_DSP_INFO", rc);

    if (do_attach) {
        errno = 0;
        rc = ioctl(fd, FASTRPC_IOCTL_INIT_ATTACH, 0);
        report("INIT_ATTACH", rc);
    }

    if (do_static) {
        memset(&st, 0, sizeof(st));
        st.namelen = sizeof(pdname);       /* includes trailing NUL */
        st.memlen = 0x100000;              /* 1 MB remote heap */
        st.name = (uint64_t)(uintptr_t)pdname;
        errno = 0;
        rc = ioctl(fd, FASTRPC_IOCTL_INIT_CREATE_STATIC, &st);
        report("INIT_CREATE_STATIC", rc);
    } else {
        memset(&cr, 0, sizeof(cr));
        cr.attrs = attrs;
        cr.filefd = -1;
        errno = 0;
        rc = ioctl(fd, FASTRPC_IOCTL_INIT_CREATE, &cr);
        report("INIT_CREATE", rc);
    }

    close(fd);
    printf("DONE\n");
    return 0;
}
