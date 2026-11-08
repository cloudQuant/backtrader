"""Build the CTP wheel with verified R19 native payload, without compiling."""
from __future__ import annotations
import base64
import csv
import hashlib
import io
import json
import os
import runpy
import sys
import zipfile
from pathlib import Path
import setuptools
from setuptools.command.build_ext import build_ext

T=Path('/tmp/iter63-r26-ctp-final-v2-20261109-UFGxjkbS')
if not (T/'SOURCE_FROZEN').is_file(): raise SystemExit('SOURCE_FREEZE required')
root=(T/'source/ctp').resolve()
if not root.is_dir() or (root/'build').exists(): raise RuntimeError('CTP source missing or stale build tree')
old=Path('/tmp/iter63-r19-install-20261109-uQ78MEA5/wheels/bt_api_ctp-2.1.0.dev63-cp311-cp311-macosx_11_0_arm64.whl')
expected='56e9618be0202ea2c935d784179201f5ea9f79b9656398ad83727ad015485134'
if hashlib.sha256(old.read_bytes()).hexdigest()!=expected: raise RuntimeError('prior CTP wheel SHA mismatch')
manifest=T/'ctp-native-reuse-manifest.json'
if manifest.exists(): raise RuntimeError('native reuse already staged')
if os.environ.get('CC')!='/usr/bin/false' or os.environ.get('CXX')!='/usr/bin/false':
    raise RuntimeError('compiler fail-closed variables missing')

class ReuseVerifiedNative(build_ext):
    def run(self):
        output=Path(self.get_ext_fullpath('bt_api_ctp.ctp._ctp')).resolve()
        if not output.is_relative_to(root/'build'): raise RuntimeError('extension build outside snapshot')
        with zipfile.ZipFile(old) as wheel:
            record_names=[n for n in wheel.namelist() if n.endswith('.dist-info/RECORD')]
            if len(record_names)!=1: raise RuntimeError('prior wheel RECORD missing/ambiguous')
            record={row[0]:row[1:] for row in csv.reader(io.StringIO(wheel.read(record_names[0]).decode('utf-8')))}
            prefix='bt_api_ctp/ctp/'
            native=[i for i in wheel.infolist() if i.filename.startswith(prefix) and not i.filename.endswith(('.py','/'))]
            extension=[i for i in native if Path(i.filename).name.startswith('_ctp.') and i.filename.endswith('.so')]
            if len(extension)!=1 or Path(extension[0].filename).name!=output.name: raise RuntimeError('native ABI mismatch')
            rows=[]
            for item in native:
                rel=Path(item.filename[len(prefix):])
                if rel.is_absolute() or '..' in rel.parts: raise RuntimeError('invalid native path')
                data=wheel.read(item);digest=hashlib.sha256(data).digest()
                encoded=base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
                if record.get(item.filename)!=['sha256='+encoded,str(len(data))]: raise RuntimeError(('native RECORD mismatch',item.filename))
                destination=output.parent/rel;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
                rows.append({'member':item.filename,'sha256':digest.hex(),'size':len(data)})
            manifest.write_text(json.dumps({'source_wheel':str(old),'source_wheel_sha256':expected,
                'native_extension_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'members':rows,
                'build_policy':'standard setuptools metadata/build with verified native payload; no native compilation'},indent=2)+'\n')
        print('CTP_NATIVE_REUSED_NO_COMPILATION',len(rows),manifest,flush=True)

original_setup=setuptools.setup

def setup_without_native_compilation(*args,**kwargs):
    classes=dict(kwargs.get('cmdclass',{}));classes['build_ext']=ReuseVerifiedNative;kwargs['cmdclass']=classes
    return original_setup(*args,**kwargs)

setuptools.setup=setup_without_native_compilation
os.chdir(root)
sys.argv=[str(root/'setup.py'),'bdist_wheel','--dist-dir',str(T/'wheels')]
runpy.run_path(str(root/'setup.py'),run_name='__main__')
