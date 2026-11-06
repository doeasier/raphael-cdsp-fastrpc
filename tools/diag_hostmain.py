#!/usr/bin/env python3
"""Diagnose why the self-built host_main still fails while fastrpc_test passes
on the 2021-07-30 cDSP firmware. Read-only device inspection."""
import os
import sys
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'
LOG = os.path.join('logs', 'firmware', 'hostmain-diag.txt')

CMDS = [
    ('aee-codes', "echo '== AEE error code definitions =='; "
                  "grep -rniE '80000406|AEE_E[A-Z]+[[:space:]]+0x8000040' "
                  "/data/local/tmp/hvx/incs /usr/local/include /usr/include /opt 2>/dev/null | head -40; "
                  "echo '== all AEE defines near 0x800004xx =='; "
                  "grep -rniE '#define[[:space:]]+AEE_[A-Z]+[[:space:]]+0x800004' "
                  "/data/local/tmp/hvx/incs /usr/local/include /opt 2>/dev/null | head -60"),
    ('daemon-log', "echo '== cdsprpcd journal (this boot) =='; "
                   "journalctl -u cdsprpcd -b --no-pager 2>/dev/null | tail -100; "
                   "echo '== any hvx / skel / open errors =='; "
                   "journalctl -b --no-pager 2>/dev/null | grep -iE "
                   "'hvx|skel|apps_std|remote_handle|mod_table|unsigned|fastrpc_shell' | tail -80"),
    ('kernel-fastrpc', "journalctl -b -k --no-pager 2>/dev/null | grep -iE "
                       "'fastrpc|glink|compute-cb|invoke|init_create|mem_map' | tail -60"),
    ('our-files', "echo '== host_main.c =='; cat /data/local/tmp/hvx/host_main.c; "
                  "echo '== hvx_add.h URI lines =='; grep -nE 'URI|_modver|handle_invoke' "
                  "/data/local/tmp/hvx/hvx_add.h; "
                  "echo '== skel copies =='; ls -l /data/local/tmp/hvx/libhvx_add_skel.so "
                  "/usr/share/qcom/dsp/cdsp/libhvx_add_skel.so "
                  "/usr/lib/rfsa/adsp/libhvx_add_skel.so 2>&1; "
                  "echo '== sha =='; sha256sum /data/local/tmp/hvx/libhvx_add_skel.so "
                  "/usr/share/qcom/dsp/cdsp/libhvx_add_skel.so 2>&1; "
                  "echo '== ELF =='; file /data/local/tmp/hvx/libhvx_add_skel.so 2>&1; "
                  "readelf -h /data/local/tmp/hvx/libhvx_add_skel.so 2>&1 | head -20"),
    ('test-assets', "echo '== fastrpc_test skels =='; "
                    "find /usr /data/local/tmp /opt -iname 'lib*calculator*' -o -iname 'lib*hap_example*' "
                    "2>/dev/null | head -30; "
                    "echo '== fastrpc_test binary =='; which fastrpc_test; "
                    "file $(which fastrpc_test) 2>&1; "
                    "echo '== how calculator is opened (strings) =='; "
                    "strings -a $(which fastrpc_test) 2>/dev/null | grep -iE "
                    "'calculator|_modver|file:///|_skel|URI' | head -30"),
    ('dsp-libs', "echo '== /usr/share/qcom/dsp/cdsp contents =='; "
                 "ls -la /usr/share/qcom/dsp/cdsp/ | head -40; "
                 "echo '== rfsa adsp links =='; ls -la /usr/lib/rfsa/adsp/ | head -30; "
                 "echo '== env =='; systemctl show cdsprpcd -p Environment --no-pager"),
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
            _in, out, err = c.exec_command(cmd, timeout=120)
            o = out.read().decode(errors='replace')
            e = err.read().decode(errors='replace')
            rc = out.channel.recv_exit_status()
        except Exception as ex:
            o, e, rc = '', repr(ex), -1
        text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
        sys.stdout.write(text[:14000])
        print('\n[rc=%d]' % rc)
        buf.append('===== %s =====\nCMD: %s\nRC: %d\n%s\n' % (label, cmd, rc, text))
    c.close()
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write('host_main failure diagnosis (read-only)\n' + ''.join(buf))
    print('\nSaved -> ' + LOG)


if __name__ == '__main__':
    main()
