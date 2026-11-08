"""Run Base again after separately manifested helper copy; preserve first log."""
import sys
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
sys.path.insert(0,str(T))
import run
raise SystemExit(run.run('base-installed-after-helpers',run.PY+['-I',str(T/'run_installed.py')],kind='base'))
