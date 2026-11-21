"""Reproduce the R71-102 mechanism probe in new public Git archive directories."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

COMMITS = {
    "before": "d02e3d75452c34ff915aebd1d631332ff7a44679",
    "after": "1ac60dfe82c62bba83b699f3f153a57ddfe1feb6",
}
PINS = {
    "before": {
        "lineiterator.py": "3ccdaa08e03096de69fb15b16f32e54c4ec5393e865002b5334c8d9555ca3460",
        "linebuffer.py": "f01a9170aada1d18c46b5f014e067db7b8f39bc32696b13508835082cda6c670",
    },
    "after": {
        "lineiterator.py": "5fb31f333fb7e01e0f1910bb17bb4095b431524f7bd54495bf4f2595b91f0271",
        "linebuffer.py": "09ea9d0a467b0ffcdf26d30547e1f826c8327e886af3e1757f2e6a01d3132618",
    },
}
parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True)
parser.add_argument("--work", required=True, help="new, nonexistent output directory")
parser.add_argument("--python", required=True)
args = parser.parse_args()
root = Path(args.work).resolve()
root.mkdir(parents=False, exist_ok=False)
probe = Path(__file__).resolve().with_name("probe.py")
if (
    hashlib.sha256(probe.read_bytes()).hexdigest()
    != "ac24ce21f41454efd7c6d6acf5f9efeceda733dbd556d720a2ed806f9e62294a"
):
    raise RuntimeError("probe pin mismatch")
outputs = {}
for label, commit in COMMITS.items():
    snapshot = root / label
    snapshot.mkdir()
    result = subprocess.run(
        ["git", "-C", args.repo, "-c", "core.autocrlf=true", "archive", commit, "backtrader"],
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(snapshot, filter="data")
    for name, expected in PINS[label].items():
        raw = (snapshot / "backtrader" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError(f"source pin mismatch: {label}/{name}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(snapshot)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [args.python, "-B", str(probe)],
        cwd=snapshot,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (root / (label + ".stdout")).write_text(result.stdout, encoding="utf-8", newline="\n")
    (root / (label + ".stderr")).write_text(result.stderr, encoding="utf-8", newline="\n")
    outputs[label] = {"returncode": result.returncode, "output": json.loads(result.stdout)}
assert outputs["before"]["returncode"] == 1 and outputs["after"]["returncode"] == 0
old, new = outputs["before"]["output"], outputs["after"]["output"]
assert old["stats"] == {"calls": 1200, "self_id": 2400, "owner_id": 4320}
assert new["stats"] == {"calls": 1200, "self_id": 1200, "owner_id": 4320}
assert old["rows"] == new["rows"] == 233 and old["digest"] == new["digest"]
print(json.dumps(outputs, indent=2))
