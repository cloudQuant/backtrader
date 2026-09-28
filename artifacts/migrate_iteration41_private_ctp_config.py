"""One-time protected local migration from ctp_simnow to canonical ctp."""

from pathlib import Path
import hashlib
import os
import re
import uuid


base = Path(r"D:\source_code\backtrader\examples\013_3_sa_midfreq_simnow\runtime-ctp-private").resolve(strict=True)
source = base / "config.yaml"
state = (base / "state").resolve(strict=True)
if state.parent != base or source.parent != base or not source.is_file():
    raise RuntimeError("private config path verification failed")

raw = source.read_bytes()
if len(re.findall(br"(?m)^ctp_simnow:\r?$", raw)) != 1 or re.search(br"(?m)^ctp:\r?$", raw):
    raise RuntimeError("unexpected existing CTP block shape")
updated = re.sub(br"(?m)^ctp_simnow:(\r?)$", br"ctp:\1", raw, count=1)

nonce = uuid.uuid4().hex
backup = state / ("config-before-canonical-" + nonce + ".bak")
staging = state / ("config-next-" + nonce + ".yaml")
for path, payload in ((backup, raw), (staging, updated)):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())

if staging.resolve(strict=True).parent != state or source.resolve(strict=True).parent != base:
    raise RuntimeError("private config identity changed")
os.replace(staging, source)
print(
    {
        "canonical_ctp_block": True,
        "byte_count": len(updated),
        "sha256": hashlib.sha256(updated).hexdigest(),
        "protected_backup_created": True,
    }
)
