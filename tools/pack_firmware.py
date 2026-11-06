#!/usr/bin/env python3
"""Build the deployment bundle using the DEVICE-VERIFIED split PIL layout.

Key correction vs the old plan: the device loads
  qcom/sm8150/Xiaomi/raphael/cdsp.mdt + cdsp.b00..b10
(NOT cdsp.mbn).  The device's DT property firmware-name confirms this.
So the bundle contains lowercase split segments only; cdsp.mbn is excluded.
"""
import os
import io
import json
import hashlib
import tarfile

ROOT = os.path.join('tmp', 'firmware', 'raphael-20210730')
PIL_SRC = os.path.join(ROOT, 'pil')
DSP_SRC = os.path.join(ROOT, 'dsp', 'cdsp')
OUT = os.path.join(ROOT, 'deploy-bundle.tar.gz')
MANIFEST_OUT = os.path.join(ROOT, 'deploy-manifest.txt')

# source -> name on device (lowercase split, as qcom_mdt_load expects)
PIL_MAP = {
    'CDSP.MDT': 'cdsp.mdt',
    'CDSP.B00': 'cdsp.b00',
    'CDSP.B01': 'cdsp.b01',
    'CDSP.B02': 'cdsp.b02',
    'CDSP.B03': 'cdsp.b03',
    'CDSP.B04': 'cdsp.b04',
    'CDSP.B05': 'cdsp.b05',
    'CDSP.B06': 'cdsp.b06',
    'CDSP.B08': 'cdsp.b08',
    'CDSP.B10': 'cdsp.b10',
    'CDSPR.JSN': 'cdspr.jsn',
}

EXCLUDE = {'_extract_log.txt'}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    entries = []  # (arcname, bytes)
    for src, dst in sorted(PIL_MAP.items()):
        p = os.path.join(PIL_SRC, src)
        if not os.path.isfile(p):
            raise SystemExit('MISSING PIL FILE: ' + p)
        entries.append(('pil/' + dst, open(p, 'rb').read()))
    for name in sorted(os.listdir(DSP_SRC)):
        if name in EXCLUDE or not os.path.isfile(os.path.join(DSP_SRC, name)):
            continue
        entries.append(('dsp/' + name, open(os.path.join(DSP_SRC, name), 'rb').read()))

    # sanity: every phdr.filesz in the new MDT must equal the corresponding bXX size
    import struct
    mdt = dict((a, b) for a, b in entries)['pil/cdsp.mdt']
    assert mdt[:4] == b'\x7fELF', 'MDT is not ELF32'
    e_phoff, = struct.unpack_from('<I', mdt, 28)
    e_phentsize, e_phnum = struct.unpack_from('<HH', mdt, 42)
    print('MDT phdr check (new split layout):')
    ok = True
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
            struct.unpack_from('<IIIIIIII', mdt, off)
        if not p_filesz:
            continue
        key = 'pil/cdsp.b%02d' % i
        actual = len(dict((a, b) for a, b in entries).get(key, b''))
        match = (actual == p_filesz)
        ok &= match
        print('  phdr[%2d] filesz=%-9d %-18s %-9d %s' %
              (i, p_filesz, key, actual, 'OK' if match else 'MISMATCH'))
    assert ok, 'MDT phdr/filesz mismatch - aborting bundle build'

    lines = ['# deploy-manifest.txt - sha256 of every file in deploy-bundle.tar.gz',
             '# layout: pil/ -> /lib/firmware/qcom/sm8150/Xiaomi/raphael/',
             '#         dsp/ -> /usr/share/qcom/dsp/cdsp/',
             '# cdsp.mbn intentionally EXCLUDED (device boots cdsp.mdt split)',
             '']
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode='w:gz', compresslevel=9) as tf:
        for arcname, data in entries:
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
            lines.append('%s  %d  %s' % (sha(data), len(data), arcname))
        mf = '\n'.join(lines) + '\n'
        mi = tarfile.TarInfo('deploy-manifest.txt')
        mi.size = len(mf.encode())
        mi.mode = 0o644
        tf.addfile(mi, io.BytesIO(mf.encode()))

    blob = tar_bytes.getvalue()
    with open(OUT, 'wb') as f:
        f.write(blob)
    with open(MANIFEST_OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(mf)
    print('\nfiles: %d  raw bytes: %d  tar.gz: %d B  sha256=%s' %
          (len(entries), sum(len(b) for _, b in entries), len(blob), sha(blob)))
    print('bundle ->', OUT)
    print('manifest ->', MANIFEST_OUT)


if __name__ == '__main__':
    main()
