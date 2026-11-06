/* ********************************************************
 * DEPRECATED - DO NOT RUN (2026-11-06, before any device execution).
 *
 * Source-level review disproved the premise and found a real hazard:
 *   - kernel fastrpc_init_create_process() never calls fastrpc_req_mem_map(),
 *     so suppressing nr=10 in cdsprpcd has no causal link to INIT_CREATE;
 *   - faking a successful nr=10 makes fastrpc_mmap_helper() insert a bogus
 *     vaddrout=0 static mapping, which the DSP will dereference (same class of
 *     failure that wedged glink in PR#319 v2).
 * Replacement: tmp/boot_probe/fastrpc_pdscan.c + deploy_pdscan.py.
 * ********************************************************
 *
 * fastrpc_nomemmap.c - LD_PRELOAD shim for the ZERO-FLASH root-PD experiment.
 *
 * Goal: make cdsprpcd (and any process that loads libcdsprpc) NOT send
 * FASTRPC_IOCTL_MEM_MAP (nr=10) to the kernel / 2020-12 cDSP firmware at all,
 * then re-run host_main and observe whether INIT_CREATE (nr=5) changes.
 *
 * This is deliberately a SHORT CIRCUIT, not a rewrite of the error code:
 * nr=10 never reaches the driver, so no new RMID is emitted to the DSP.
 * (PR#319 v2 proved that emitting legacy RMID_INIT_MMAP wedges the glink
 * channel; this shim cannot do that.)
 *
 * Environment (all optional except FR_SKIP_MEMMAP):
 *   FR_SKIP_MEMMAP=1       short-circuit nr=10 instead of calling ioctl()
 *   FR_SKIP_MEMMAP_RC=N    value to return from the fake nr=10  (default 0)
 *   FR_FAKE_VA=0x...       value written to map->vaddrout      (default 0)
 *   FR_SKIP_UNMAP=1        also short-circuit nr=11 (MEM_UNMAP) (default on
 *                          when FR_SKIP_MEMMAP=1)
 *   FR_TRACE_FILE=/path    append-only trace (default /tmp/rootpd-exp.trace)
 *   FR_TRACE_ALL=1         log every 'R' ioctl, not only the intercepted ones
 *
 * Build on device:
 *   gcc -shared -fPIC -O0 -o /opt/rootpd-exp/fastrpc_nomemmap.so \
 *       /opt/rootpd-exp/fastrpc_nomemmap.c -ldl
 *
 * Use:
 *   LD_PRELOAD=/opt/rootpd-exp/fastrpc_nomemmap.so FR_SKIP_MEMMAP=1 ./host_main
 *   (or as a systemd drop-in Environment= on cdsprpcd.service)
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

typedef int (*ioctl_fn)(int, unsigned long, ...);
static ioctl_fn real_ioctl;

/* Mirrors upstream include/uapi/misc/fastrpc.h (no header needed on device). */
struct fastrpc_ioctl_mem_map {
    int32_t  version;
    int32_t  fd;
    int32_t  offset;
    uint32_t flags;
    uint64_t vaddrin;
    uint64_t length;
    uint64_t vaddrout;      /* [out] remote DSP virtual address */
    int32_t  attrs;
    int32_t  reserved[4];
};
struct fastrpc_ioctl_mem_unmap {
    int32_t  version;
    int32_t  fd;
    uint64_t vaddrout;
    uint64_t length;
    int32_t  reserved[4];
};
struct fastrpc_ioctl_init_create {
    uint32_t filelen;
    int32_t  filefd;
    uint32_t attrs;
    uint32_t siglen;
    uint64_t file;
};

static int do_skip, do_skip_unmap, do_trace_all, fake_rc;
static uint64_t fake_va;
static const char *trace_file;

static void init(void)
{
    static int done;
    const char *s;
    if (done)
        return;
    done = 1;
    real_ioctl = (ioctl_fn)dlsym(RTLD_NEXT, "ioctl");
    do_skip = getenv("FR_SKIP_MEMMAP") != NULL;
    do_skip_unmap = do_skip && getenv("FR_NO_SKIP_UNMAP") == NULL;
    do_trace_all = getenv("FR_TRACE_ALL") != NULL;
    trace_file = getenv("FR_TRACE_FILE");
    if (!trace_file)
        trace_file = "/tmp/rootpd-exp.trace";
    fake_rc = 0;
    if ((s = getenv("FR_SKIP_MEMMAP_RC")))
        fake_rc = (int)strtol(s, NULL, 0);
    fake_va = 0;
    if ((s = getenv("FR_FAKE_VA")))
        fake_va = (uint64_t)strtoull(s, NULL, 0);
}

static void logline(const char *fmt, ...)
{
    char buf[1024];
    va_list ap;
    int n, fd;
    struct timeval tv;

    if (!trace_file)
        return;
    gettimeofday(&tv, NULL);
    va_start(ap, fmt);
    n = snprintf(buf, sizeof(buf), "[%ld.%06ld pid=%d] ",
                 (long)tv.tv_sec, (long)tv.tv_usec, (int)getpid());
    n += vsnprintf(buf + n, sizeof(buf) - (size_t)n, fmt, ap);
    va_end(ap);
    if (n >= (int)sizeof(buf))
        n = (int)sizeof(buf) - 1;
    if (n > 0 && buf[n - 1] != '\n' && n < (int)sizeof(buf) - 1)
        buf[n++] = '\n';
    fd = open(trace_file, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) {
        (void)!write(fd, buf, (size_t)n);
        close(fd);
    }
}

int ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    int rc, saved, nr;
    int is_fastrpc;
    struct fastrpc_ioctl_mem_map *mm;

    init();
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);

    is_fastrpc = (((req >> 8) & 0xff) == 'R');
    nr = (int)(req & 0xff);

    if (is_fastrpc && do_skip && nr == 10) {
        mm = (struct fastrpc_ioctl_mem_map *)arg;
        if (mm)
            mm->vaddrout = fake_va;
        logline("SKIP nr=10 MEM_MAP fd=%d arg=%p "
                "(version=%d length=%llu flags=0x%x) -> fake rc=%d va=0x%llx",
                fd, arg, mm ? mm->version : -1,
                mm ? (unsigned long long)mm->length : 0ULL,
                mm ? mm->flags : 0U, fake_rc, (unsigned long long)fake_va);
        errno = 0;
        return fake_rc;
    }
    if (is_fastrpc && do_skip_unmap && nr == 11) {
        struct fastrpc_ioctl_mem_unmap *mu =
            (struct fastrpc_ioctl_mem_unmap *)arg;
        logline("SKIP nr=11 MEM_UNMAP fd=%d va=0x%llx -> fake rc=%d", fd,
                mu ? (unsigned long long)mu->vaddrout : 0ULL, fake_rc);
        errno = 0;
        return fake_rc;
    }

    errno = 0;
    rc = real_ioctl(fd, req, arg);
    saved = errno;

    if (is_fastrpc && (do_trace_all || nr == 5 || nr == 4 || nr == 13)) {
        logline("IOCTL nr=%-3d fd=%d arg=%p -> rc=%d (0x%08x) errno=%d",
                nr, fd, arg, rc, (unsigned int)rc, saved);
        if (nr == 5 && arg) {
            struct fastrpc_ioctl_init_create *ic =
                (struct fastrpc_ioctl_init_create *)arg;
            logline("       create{filelen=%u filefd=%d attrs=0x%08x siglen=%u "
                    "file=0x%llx}", ic->filelen, ic->filefd, ic->attrs,
                    ic->siglen, (unsigned long long)ic->file);
        }
    }
    errno = saved;
    return rc;
}
