import json
import sys

import bt_api_ctp
from bt_api_ctp.containers.ctp import ctp_native_query_certificate as evidence

blocked = [name for name in ("_ctp", "bt_api_ctp.ctp._ctp") if name in sys.modules]
print(json.dumps({
    "python": sys.version.split()[0],
    "package": bt_api_ctp.__file__,
    "evidence_module": evidence.__file__,
    "native_python_modules_in_sys_modules": blocked,
}, sort_keys=True))
if blocked:
    raise SystemExit("native module unexpectedly imported")
