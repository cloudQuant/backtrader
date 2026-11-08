"""Run SDK again after the single approved test fixture refresh."""
import sys
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
sys.path.insert(0,str(T))
import run
raise SystemExit(run.run('sdk-installed-after-fixture',run.PY+['-I',str(T/'run_installed.py')],kind='sdk'))
