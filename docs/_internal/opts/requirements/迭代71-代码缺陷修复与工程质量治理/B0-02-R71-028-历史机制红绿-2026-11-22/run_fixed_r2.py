"""Run fixed R71-028 historical archive, preserving the earlier old log."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path('D:/temp/i71-r71-028-redgreen-6e0cba79')
folder = root / 'fixed'
test = root / 'test_r71_028_common_entry.py'
source = folder / 'backtrader/bokeh/live/datahandler.py'
expected = '373e42fb68c752b3ca911809a025b6f2c09cdb625c8cb7962994eae691dbf5ae'
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
env = dict(os.environ)
env.update(PYTHONPATH=str(folder), PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
cmd = [sys.executable, '-B', '-m', 'pytest', '-c', str(root/'empty.ini'), '--noconftest', '-p', 'no:cacheprovider', '--rootdir', str(folder), '-v', '--tb=short', str(test)]
proc = subprocess.run(cmd, cwd=folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
with (root/'fixed.log').open('xb') as out: out.write(proc.stdout)
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
record = {'old_commit':'276776852a09f639db49f489c1345590ac085c14','fixed_commit':'6e0cba79190290f3708d0db01865b811a7c1c0e8','old_source_sha256':'bf819b5ec2d28c740c0173a87f8840a515b6c37c8fecf0bad4697472bf329358','fixed_source_sha256':expected,'test_sha256':hashlib.sha256(test.read_bytes()).hexdigest(),'old_log_sha256':hashlib.sha256((root/'old.log').read_bytes()).hexdigest(),'fixed_log_sha256':hashlib.sha256(proc.stdout).hexdigest(),'fixed_exit':proc.returncode,'old_exit_from_prior_console':1,'python':sys.version}
with (root/'result_r2.json').open('x',encoding='utf-8') as out: json.dump(record,out,indent=2);out.write('\n')
print('fixed exit',proc.returncode)
