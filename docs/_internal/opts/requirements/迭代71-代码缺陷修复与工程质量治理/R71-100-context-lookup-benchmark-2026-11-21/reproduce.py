"""Rebuild the two public Git inputs and run the archived R71-100 benchmark."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


CURRENT = "62d08b47d70d863ddc6853c13cebeb5c3f686a58"
LEGACY = "8db4b49b0d2a9424a518e9deef5a56d611121253"
PINS = {
    "legacy_linebuffer.py": "830e1e54fb7cab1e02cd6234aedb2075cda7aa368372528f12ca5f4463a6d0b2",
    "backtrader/linebuffer.py": "09ea9d0a467b0ffcdf26d30547e1f826c8327e886af3e1757f2e6a01d3132618",
    "benchmark_r71_100_r2.py": "011860081c1990fc1f5db75cb4bb096fa962d21ba31d50bf2bca00ede3ee4973",
    "check_r71_100_oracle.py": "fd99fc3e489172f318d733dc2aa267b63d3b53b58025b22f3e581b7e2586bacb",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="construct and check inputs without timing")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    repo = subprocess.check_output(
        ["git", "-C", str(here), "rev-parse", "--show-toplevel"], text=True, encoding="utf-8"
    ).strip()
    target = Path(tempfile.mkdtemp(prefix="r71_100_public_snapshot_"))
    with tempfile.TemporaryFile() as archive:
        subprocess.run(
            ["git", "-c", "core.autocrlf=true", "-C", repo, "archive", "--format=tar", CURRENT, "backtrader"],
            stdout=archive, check=True,
        )
        archive.seek(0)
        with tarfile.open(fileobj=archive) as contents:
            contents.extractall(target, filter="data")
    legacy = subprocess.check_output(
        ["git", "-C", repo, "show", LEGACY + ":backtrader/linebuffer.py"]
    )
    (target / "legacy_linebuffer.py").write_bytes(legacy)
    for name in ("benchmark_r71_100_r2.py", "check_r71_100_oracle.py"):
        shutil.copyfile(here / name, target / name)
    for name, expected in PINS.items():
        actual = sha(target / name)
        if actual != expected:
            raise RuntimeError("input SHA-256 mismatch for %s: %s" % (name, actual))
    print(json.dumps({"snapshot": str(target), "current": CURRENT, "legacy": LEGACY,
                      "pins_checked": len(PINS)}, ensure_ascii=False), flush=True)
    if not args.prepare_only:
        subprocess.run([sys.executable, "benchmark_r71_100_r2.py"], cwd=target, check=True)
        subprocess.run([sys.executable, "check_r71_100_oracle.py"], cwd=target, check=True)
        print("New timings: " + str(target / "result_r2.json"), flush=True)


if __name__ == "__main__":
    main()
