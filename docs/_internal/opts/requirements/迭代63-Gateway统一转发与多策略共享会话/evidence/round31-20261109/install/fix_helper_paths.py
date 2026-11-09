from pathlib import Path
import shutil
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
for n in ('sdk-tests','bt-tests'):
 p=T/n
 if p.exists():p.rename(T/(n+'-initial'))
p=T/'prepare.py';shutil.copyfile(p,T/'prepare-v1.py');s=p.read_text().replace("prefixes = ('tests/unit','tests','tests/integration') if repo == SDK else ('tests',)","prefixes = ('tests/unit','tests','tests/integration') if repo in (SDK, BT) else ('tests',)");p.write_text(s)
p=T/'run.py';shutil.copyfile(p,T/'run-v1.py');s=p.read_text().replace("STAGES = {", "STAGES = {'tests-copy-v2',")
s=s.replace("    if stage == 'build':", "    if stage == 'tests-copy-v2':\n        return run(stage, PY+[str(T/'prepare.py'),'tests'])\n    if stage == 'build':")
p.write_text(s)
