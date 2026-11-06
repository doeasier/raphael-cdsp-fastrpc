# Key evidence excerpts

Auto-extracted from the raw logs in this directory. Line numbers refer to the
archived copies (identical to the originals except for redacted credentials and stripped NUL padding).

Full logs are kept alongside this file; this is only a navigation index.

> **Result in one line:** `fastrpc_test -d 3 -U 1` → 3/3 PASS;
> `host_main` → `host: PASS - all 1000 elements verified correct.`

> **Firmware in place:** `419065.1_20210730_070147`,
> `CDSP.HT.2.0.1-00171-SM8150-1.357350.2.419065.1_20210730_070147`,
> PAS accepted the split `cdsp.mdt` and cDSP reached `running`.

## `postboot-verify.txt`  (38 matching lines, showing first 25)

```text
  22 | CMD: echo '== PIL mdt / b02 / b05 =='; sha256sum /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.mdt /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b02 /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b05; echo '== unsigned sh
  31 | 419065.1_20210730_070147
  32 | CDSP.HT.2.0.1-00171-SM8150-1.357350.2.419065.1IMAGE_VARIANT_STRING=855.cdsp.prodQOEM_I
  33 | CDSP.HT.2.0.1-00171-SM8150qurt pid is %d
  34 | CDSP.HT.2.0.1-00171-SM8150-1_20200916_040146/b/cdsp_proc/platform/fastrpc_thread_queue/src/fa
  36 | >>> VERDICT: NEW 2021-07-30 FIRMWARE IN PLACE
  54 | 11月 06 22:31:19 xiaomi-raphael kernel: remoteproc remoteproc0: cdsp is available
  56 | 11月 06 22:31:19 xiaomi-raphael kernel: remoteproc remoteproc0: Booting fw image qcom/sm8150/Xiaomi/raphael/cdsp.mdt, size 7580
  57 | 11月 06 22:31:20 xiaomi-raphael kernel: remoteproc remoteproc0: remote processor cdsp is now up
  64 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  65 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  67 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  68 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  69 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  75 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  76 | 11月 06 22:31:20 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  78 | 11月 06 22:31:22 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  79 | 11月 06 22:31:32 xiaomi-raphael kernel: snd-sm8150-raphael sound: qcom_snd_parse_of failed: -517
  85 | [    0.000000] Unknown kernel command line parameters "dtb=\dtbs\qcom\sm8150-xiaomi-raphael.dtb", will be passed to user space.
  86 | [    5.283018] systemd[1]: Started systemd-ask-password-wall.path - Forward Password Requests to Wall Directory Watch.
  87 | [    6.325077] remoteproc remoteproc0: cdsp is available
  89 | [    6.326356] remoteproc remoteproc0: Booting fw image qcom/sm8150/Xiaomi/raphael/cdsp.mdt, size 7580
  90 | [    6.392507] remoteproc remoteproc0: remote processor cdsp is now up
  94 | CMD: echo '== remoteproc =='; cat /sys/class/remoteproc/remoteproc0/state 2>&1; echo '== devnodes =='; ls -l /dev/fastrpc-cdsp* 2>&1; echo '== daemon =='; systemctl is-active cdsprpcd 2>&1; echo '== failed units =='; sys
  99 | crw-r----- 1 root    fastrpc 10, 267 11月  6 22:31 /dev/fastrpc-cdsp
... 13 more matching lines in the full log
```

## `hostmain-uri-fix.txt`  (11 matching lines, showing first 25)

```text
  45 | host: PASS - all 1000 elements verified correct.
  49 | CMD: journalctl -b --no-pager --since '3 min ago' 2>/dev/null | grep -iE 'hvx|skel|dlerror|remote_handle64_open|Successfully opened file' | tail -40
  52 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  54 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: fastrpc_apps_user.c:1740: Error 0x80000406: remote_handle_open_domain: dynamic loading failed for file:///data/local/tmp/hvx/libhvx_add_skel.so?hvx_add_skel_handle_invoke&_
  55 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: fastrpc_apps_user.c:1840: Error 0x80000406: remote_handle64_open failed for file:///data/local/tmp/hvx/libhvx_add_skel.so?hvx_add_skel_handle_invoke&_modver=1.0&_dom=cdsp (
  56 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  61 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  66 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  71 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  76 | 11月 06 22:31:40 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  83 | 11月 06 22:34:05 xiaomi-raphael host_main[9869]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
```

## `hostmain-diag.txt`  (22 matching lines, showing first 25)

```text
   3 | CMD: echo '== AEE error code definitions =='; grep -rniE '80000406|AEE_E[A-Z]+[[:space:]]+0x8000040' /data/local/tmp/hvx/incs /usr/local/include /usr/include /opt 2>/dev/null | head -40; echo '== all AEE defines near 0x8
   6 | /data/local/tmp/hvx/incs/stddef/AEEStdErr.h:38:	#define AEE_EOFFSET               0x80000400
   7 | /usr/local/include/fastrpc/AEEStdErr.h:10:#define DSP_AEE_EOFFSET	0x80000400
   8 | /opt/fastrpc-backup-20261106/fastrpc-include/AEEStdErr.h:10:#define DSP_AEE_EOFFSET	0x80000400
   9 | /opt/fastrpc-pr319/inc/AEEStdErr.h:10:#define DSP_AEE_EOFFSET	0x80000400
  10 | == all AEE defines near 0x800004xx ==
  11 | /data/local/tmp/hvx/incs/stddef/AEEStdErr.h:38:	#define AEE_EOFFSET               0x80000400
  28 | 11月 06 22:31:20 xiaomi-raphael cdsprpcd[571]: fastrpc_mem.c:556: Error 0x14: fastrpc_mmap_helper failed for fd 11, addr 0xffffadca0000, length 0x40000, domain 3, flags 0x0, ioctl ret 0x80000414, errno Success
  31 | 11月 06 22:31:20 xiaomi-raphael cdsprpcd[571]: apps_mem_imp.c:175::error: 20: AEE_SUCCESS == (nErr = remote_mmap64_internal(fd, rflags, (uint64_t)(uintptr_t)buf, len, (uint64_t *)vadsp))
  35 | 11月 06 22:31:20 xiaomi-raphael cdsprpcd[571]: adspmsgd.c:119::error: 20: AEE_SUCCESS == (nErr = adspmsgd_adsp1_init3(handle, 0, RPCMEM_HEAP_DEFAULT, filter, DEFAULT_MEMORY_SIZE, &vapps))
  37 | 11月 06 22:31:20 xiaomi-raphael cdsprpcd[571]: fastrpc_apps_user.c:1607: Error 0x8000041d: remote_handle64_invoke failed for module (null), handle 0xaaaaf802f910, method 3 on domain 3 (sc 0x3000000) (errno Success)
  50 | 11月 06 22:31:20 xiaomi-raphael cdsprpcd[571]: fastrpc_apps_user.c:1607: Error 0x8000041d: remote_handle64_invoke failed for module (null), handle 0xaaaaf802f910, method 3 on domain 3 (sc 0x3000000) (errno Success)
  57 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  63 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: fastrpc_apps_user.c:1740: Error 0x80000406: remote_handle_open_domain: dynamic loading failed for file:///data/local/tmp/hvx/libhvx_add_skel.so?hvx_add_skel_handle_invoke&_
  64 | 11月 06 22:31:38 xiaomi-raphael host_main[2741]: fastrpc_apps_user.c:1840: Error 0x80000406: remote_handle64_open failed for file:///data/local/tmp/hvx/libhvx_add_skel.so?hvx_add_skel_handle_invoke&_modver=1.0&_dom=cdsp (
  66 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  75 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  85 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
  97 | 11月 06 22:31:38 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
 109 | 11月 06 22:31:40 xiaomi-raphael fastrpc_test[2747]: apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3
 122 | CMD: journalctl -b -k --no-pager 2>/dev/null | grep -iE 'fastrpc|glink|compute-cb|invoke|init_create|mem_map' | tail -60
 278 |         printf("host: PASS - all %d elements verified correct.\n", N);
```

## `matrix-p0-daemon-on.txt`  (15 matching lines, showing first 25)

```text
   1 | CMD: echo "### fastrpc-cdsp-noattach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp noattach 0x8 2>&1; echo "RC=$?"
   2 | echo "### fastrpc-cdsp-noattach-0x0"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp noattach 0x0 2>&1; echo "RC=$?"
   3 | echo "### fastrpc-cdsp-attach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp attach 0x8 2>&1; echo "RC=$?"
   4 | echo "### fastrpc-cdsp-secure-noattach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp-secure noattach 0x8 2>&1; echo "RC=$?"
   5 | echo "### fastrpc-cdsp-secure-attach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp-secure attach 0x8 2>&1; echo "RC=$?"
   9 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4594 ATTACH=noattach ATTRS=0x8 STATIC=0
  11 | INIT_CREATE              RC=-2147482541 RC_HEX=0x80000453 ERRNO=0 Success
  15 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4596 ATTACH=noattach ATTRS=0x0 STATIC=0
  17 | INIT_CREATE              RC=-2147482541 RC_HEX=0x80000453 ERRNO=0 Success
  21 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4598 ATTACH=attach ATTRS=0x8 STATIC=0
  24 | INIT_CREATE              RC=-2147482598 RC_HEX=0x8000041a ERRNO=0 Success
  28 | DEVICE=/dev/fastrpc-cdsp-secure FD=3 PID=4600 ATTACH=noattach ATTRS=0x8 STATIC=0
  30 | INIT_CREATE              RC=-2147482541 RC_HEX=0x80000453 ERRNO=0 Success
  34 | DEVICE=/dev/fastrpc-cdsp-secure FD=3 PID=4602 ATTACH=attach ATTRS=0x8 STATIC=0
  37 | INIT_CREATE              RC=-2147482598 RC_HEX=0x8000041a ERRNO=0 Success
```

## `matrix-p1-daemon-off.txt`  (15 matching lines, showing first 25)

```text
   1 | CMD: echo "### fastrpc-cdsp-noattach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp noattach 0x8 2>&1; echo "RC=$?"
   2 | echo "### fastrpc-cdsp-noattach-0x0"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp noattach 0x0 2>&1; echo "RC=$?"
   3 | echo "### fastrpc-cdsp-attach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp attach 0x8 2>&1; echo "RC=$?"
   4 | echo "### fastrpc-cdsp-secure-noattach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp-secure noattach 0x8 2>&1; echo "RC=$?"
   5 | echo "### fastrpc-cdsp-secure-attach-0x8"; timeout 25 /opt/rootpd-exp/fastrpc_pdscan /dev/fastrpc-cdsp-secure attach 0x8 2>&1; echo "RC=$?"
   9 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4859 ATTACH=noattach ATTRS=0x8 STATIC=0
  11 | INIT_CREATE              RC=-2147482240 RC_HEX=0x80000580 ERRNO=0 Success
  15 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4861 ATTACH=noattach ATTRS=0x0 STATIC=0
  17 | INIT_CREATE              RC=-2147482240 RC_HEX=0x80000580 ERRNO=0 Success
  21 | DEVICE=/dev/fastrpc-cdsp FD=3 PID=4863 ATTACH=attach ATTRS=0x8 STATIC=0
  24 | INIT_CREATE              RC=-2147482598 RC_HEX=0x8000041a ERRNO=0 Success
  28 | DEVICE=/dev/fastrpc-cdsp-secure FD=3 PID=4865 ATTACH=noattach ATTRS=0x8 STATIC=0
  30 | INIT_CREATE              RC=-2147482240 RC_HEX=0x80000580 ERRNO=0 Success
  34 | DEVICE=/dev/fastrpc-cdsp-secure FD=3 PID=4867 ATTACH=attach ATTRS=0x8 STATIC=0
  37 | INIT_CREATE              RC=-2147482598 RC_HEX=0x8000041a ERRNO=0 Success
```

## `readonly-audit.txt`  (5 matching lines, showing first 25)

```text
 382 | crw-r----- 1 root    fastrpc 10, 267 11月  6 18:48 /dev/fastrpc-cdsp
 383 | crw------- 1 fastrpc fastrpc 10, 266 11月  6 18:48 /dev/fastrpc-cdsp-secure
 478 | 11月 06 18:48:31 xiaomi-raphael kernel: remoteproc remoteproc0: cdsp is available
 480 | 11月 06 18:48:31 xiaomi-raphael kernel: remoteproc remoteproc0: Booting fw image qcom/sm8150/Xiaomi/raphael/cdsp.mdt, size 7580
 481 | 11月 06 18:48:31 xiaomi-raphael kernel: remoteproc remoteproc0: remote processor cdsp is now up
```

## `readonly-audit2.txt`  (1 matching lines, showing first 25)

```text
   5 | /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b00: /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b01: /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b02: /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.b03: /lib/firmware/qc
```

## `readonly-boot.txt`  (0 matching lines, showing first 25)

(no keyword matches in this log)

## `readonly-esp.txt`  (4 matching lines, showing first 25)

```text
  17 | 29:# Normally, when the timeout period has passed, rEFInd boots the
 102 | 635:#  options   - sets options to be passed to the boot loader; use
 105 | 650:# except when you must pass a forward slash to the loader, as when
 163 | # Normally, when the timeout period has passed, rEFInd boots the
```

