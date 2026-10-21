import importlib.metadata
import json
from pathlib import Path
import sys
import backtrader
import fincore
print(json.dumps({
  'python': sys.version.split()[0],
  'executable': str(Path(sys.executable).resolve()),
  'prefix': str(Path(sys.prefix).resolve()),
  'backtrader_origin': str(Path(backtrader.__file__).resolve()),
  'backtrader_version': importlib.metadata.version('backtrader'),
  'fincore_origin': str(Path(fincore.__file__).resolve()),
  'fincore_version': importlib.metadata.version('fincore'),
}, sort_keys=True))
