"""Rebuild and optionally rerun the R71-046 public benchmark in a fresh directory."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


BASELINE = "a2472f5b0baedf460de043847ab9f9189dc3a42f"
CANDIDATE = "0ef1994c6b06a741c091e10cc2e194fffb51beb2"
SOURCE = "backtrader/indicators/contrib/digital_macd.py"
SOURCE_PINS = {
    "baseline": "42b6595b25aa48c48570aa19ecb528eeeeb0d3c81dcd9404f5815184ae13e0b7",
    "candidate": "d3e862d8beb9a36ae966677534f06f3c50cca9c53eed7e0a51904c5dcf99a386",
}
BLOB_PINS = {
    "baseline": "af1bd8411c1811c393a5305260a76bed292f9624563f3329a7a98e783e381ffa",
    "candidate": "d3e862d8beb9a36ae966677534f06f3c50cca9c53eed7e0a51904c5dcf99a386",
}
WORKER_PIN = "a3bd2e365d57ddad869176cd71726a3934ac5549ec96848d4eeb62de9e0dc8f7"
DATA_PIN = "ba0c87d512cc0a8f699ee1b9e22a9a10b5def19e4e27f831e00138925b36e92c"
OUTPUT_PINS = {
    5: "3c264e1b654aaa1f583e15e29c473c490b8c246000df50af5b6381d684b28442",
    256: "fbdae4be3cc4807729ef5ffaa845332b68bac4ecb3985d5b214434bb40a376e5",
    1024: "9a1b969300acbdeb05c0661c4a477c04c7a6c2a2015d0beec5f9d69ae6fe8184",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python 3.14.2 executable")
    parser.add_argument("--check", action="store_true", help="check pins only; do not run benchmarks")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    repo = Path(git(here, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    worker = (here / "executed_worker.py").read_bytes()
    if digest(worker) != WORKER_PIN:
        raise ValueError("worker hash mismatch")
    sources = {}
    for name, revision in (("baseline", BASELINE), ("candidate", CANDIDATE)):
        actual = git(repo, "rev-parse", f"{revision}^{{commit}}").decode("ascii").strip()
        blob = git(repo, "show", f"{revision}:{SOURCE}")
        if actual != revision or digest(blob) != BLOB_PINS[name]:
            raise ValueError(f"{name} commit or blob mismatch")
        # The recorded baseline archive used CRLF; the candidate was LF.
        sources[name] = blob.replace(b"\n", b"\r\n") if name == "baseline" else blob
        if digest(sources[name]) != SOURCE_PINS[name]:
            raise ValueError(f"{name} runtime source mismatch")
    env_check = subprocess.check_output(
        [args.python, "-c", "import json,sys,numpy,pandas; print(json.dumps([list(sys.version_info[:3]),numpy.__version__,pandas.__version__]))"],
        text=True,
    )
    versions = json.loads(env_check)
    if versions != [[3, 14, 2], "2.4.1", "2.3.3"]:
        raise ValueError(f"expected Python 3.14.2, NumPy 2.4.1, pandas 2.3.3; got {versions}")
    if args.check:
        print("Pins and interpreter verified; no benchmark was run.")
        return

    # mkdtemp and exclusive creation avoid all existing directories and evidence.
    work = Path(tempfile.mkdtemp(prefix="iter71-digital-rebuild-"))
    print(f"Fresh output directory: {work}", flush=True)
    for name, revision in (("baseline", BASELINE), ("candidate", CANDIDATE)):
        dest = work / name
        dest.mkdir(exist_ok=False)
        archive = git(repo, "archive", revision, "backtrader")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(dest, filter="data")
        # Git archive newline projection varies with checkout configuration.
        # This write is confined to the newly created private temporary tree.
        (dest / SOURCE).write_bytes(sources[name])
        if digest((dest / SOURCE).read_bytes()) != SOURCE_PINS[name]:
            raise ValueError(f"{name} extracted source mismatch")
        with (dest / "bench_worker.py").open("xb") as out:
            out.write(worker)

    import os

    records = []
    for period in (5, 256, 1024):
        for pair in range(4):
            order = ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
            for name in order:
                folder = work / name
                env = os.environ.copy()
                env["PYTHONPATH"] = str(folder)
                raw = subprocess.check_output(
                    [args.python, "-B", "bench_worker.py", str(period), "1"],
                    cwd=folder,
                    env=env,
                    text=True,
                )
                row = json.loads(raw.strip().splitlines()[-1])
                if row["source_sha256"] != SOURCE_PINS[name] or row["data_sha256"] != DATA_PIN:
                    raise ValueError("source or generated data hash mismatch")
                if row["output_sha256"] != OUTPUT_PINS[period]:
                    raise ValueError("output hash differs from recorded benchmark")
                row.update(pair=pair, variant=name)
                records.append(row)
            if records[-2]["output_sha256"] != records[-1]["output_sha256"]:
                raise ValueError("paired output mismatch")
        print(f"period {period}: four pairs complete", flush=True)
    output = work / "reproduced_result.json"
    with output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(records, out, indent=2)
        out.write("\n")
    print(f"New result: {output}")


if __name__ == "__main__":
    main()
