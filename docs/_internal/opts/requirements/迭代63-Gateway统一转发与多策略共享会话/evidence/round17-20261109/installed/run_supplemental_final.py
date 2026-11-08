import sys
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
sys.path.insert(0,str(T))
import run
raise SystemExit(run.run('supplemental-verify-final',run.PY+['-I',str(T/'verify_supplemental_final.py')]))
