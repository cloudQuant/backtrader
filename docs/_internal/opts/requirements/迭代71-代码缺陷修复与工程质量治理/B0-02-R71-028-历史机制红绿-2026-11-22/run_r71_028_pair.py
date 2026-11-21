"""Run the same public synthetic R71-028 test against pinned Git archives."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path('D:/temp/i71-r71-028-redgreen-6e0cba79')
SOURCES = {
    'old': ('276776852a09f639db49f489c1345590ac085c14', 'bf819b5ec2d28c740c0173a87f8840a515b6c37c8fecf0bad4697472bf329358'),
    'fixed': ('6e0cba79190290f3708d0db01865b811a7c1c0e8', '373e42fb68c752b3ca911809a025b6f2c09cdb625c8cb7962994ae691dbf5ae'),
}
TEST = ROOT/'test_r71_028_common_entry.py'
CONFIG = ROOT/'empty.ini'
if not CONFIG.exists():
    CONFIG.write_text('[pytest]\n', encoding='utf-8')
results={}
for label,(commit,expected) in SOURCES.items():
    folder=ROOT/label
    source=folder/'backtrader/bokeh/live/datahandler.py'
    raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected
    env=dict(os.environ)
    env['PYTHONPATH']=str(folder)
    env['PYTHONDONTWRITEBYTECODE']='1'
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    command=[sys.executable,'-B','-m','pytest','-c',str(CONFIG),'--noconftest','-p','no:cacheprovider','--rootdir',str(folder),'-v','--tb=short',str(TEST)]
    proc=subprocess.run(command,cwd=folder,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)
    log=ROOT/(label+'.log')
    with log.open('xb') as stream:stream.write(proc.stdout)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
    results[label]={'commit':commit,'source_sha256':expected,'returncode':proc.returncode,'log':str(log),'log_sha256':hashlib.sha256(proc.stdout).hexdigest()}
    print(label,'exit',proc.returncode,'log',log,flush=True)
results['test_sha256']=hashlib.sha256(TEST.read_bytes()).hexdigest()
results['python']=sys.version
with (ROOT/'result.json').open('x',encoding='utf-8') as out:json.dump(results,out,indent=2);out.write('\n')
