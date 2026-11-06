#!/usr/bin/env python3
"""Fix the skel URI (absolute path -> bare filename) and rebuild host_main.

Root cause (device journal, 2026-11-06 22:31:38):
  Error 0x80000406: dynamic loading failed for
  file:///data/local/tmp/hvx/libhvx_add_skel.so?...
  (dlerror: Absolute path or ./obj_name required for shared object data/local/t...)
The 2021-07 CDSP firmware's DSP loader strips the leading '/' after file:///,
so the path becomes relative and dlopen rejects it.  fastrpc_test succeeds with
a bare filename resolved via ADSP_LIBRARY_PATH; libhvx_add_skel.so is present
in /usr/lib/rfsa/adsp, /usr/share/qcom/dsp/cdsp and /data/local/tmp/hvx.
"""
import os
import sys
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'
LOG = os.path.join('logs', 'firmware', 'hostmain-uri-fix.txt')
W = '/data/local/tmp/hvx'
ENV = ("LD_LIBRARY_PATH=/usr/local/lib "
       "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
       "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx'")

CMDS = [
    ('backup-and-check', "cd %s && cp -a hvx_add.h hvx_add.h.pre-uri-fix-20261106 && "
                         "cp -a host_main host_main.pre-uri-fix-20261106 && "
                         "echo '== URI before =='; grep -n 'define hvx_add_URI' hvx_add.h; "
                         "echo '== URI hardcoded in stub? =='; grep -n 'libhvx_add_skel.so' "
                         "hvx_add_stub.c host_main.c hvx_add.h 2>/dev/null" % W),
    ('patch-uri', "cd %s && sed -i "
                  "'s|file:///data/local/tmp/hvx/libhvx_add_skel.so|file:///libhvx_add_skel.so|' "
                  "hvx_add.h && echo '== URI after =='; grep -n 'define hvx_add_URI' hvx_add.h" % W),
    ('rebuild', "cd %s && gcc host_main.c hvx_add_stub.c -I. -Iincs -Iincs/stddef "
                "-o host_main -L/usr/local/lib -lcdsprpc -lpthread -ldl 2>&1; "
                "echo GCC_RC=$?; ls -l host_main" % W),
    ('run', "cd %s && timeout 120 env %s ./host_main 2>&1; echo HOST_MAIN_RC=$?" % (W, ENV)),
    ('journal', "journalctl -b --no-pager --since '3 min ago' 2>/dev/null | grep -iE "
                "'hvx|skel|dlerror|remote_handle64_open|Successfully opened file' | tail -40"),
]


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    buf = []
    for label, cmd in CMDS:
        print('\n===== %s =====' % label)
        try:
            _in, out, err = c.exec_command(cmd, timeout=200)
            o = out.read().decode(errors='replace')
            e = err.read().decode(errors='replace')
            rc = out.channel.recv_exit_status()
        except Exception as ex:
            o, e, rc = '', repr(ex), -1
        text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
        sys.stdout.write(text[:16000])
        print('\n[rc=%d]' % rc)
        buf.append('===== %s =====\nCMD: %s\nRC: %d\n%s\n' % (label, cmd, rc, text))
    c.close()
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write('host_main URI fix (bare filename)\n' + ''.join(buf))
    print('\nSaved -> ' + LOG)


if __name__ == '__main__':
    main()
