"""Iteration 60 release/install matrix: build wheels, install them, prove what runs.

Usage (offline; no package index is contacted)::

    python scripts/ci/iter60_release_matrix.py --out <evidence-dir> \
        --python /path/to/python3.11 --python /path/to/python3.13

For the Backtrader checkout and the bt_api_py SDK checkout (``--sdk``) this

1. records branch, HEAD and dirty state of every repository and submodule;
2. builds a wheel and an sdist of each package with ``--no-isolation`` (the
   build backend must already be installed in the building interpreter);
3. per interpreter, creates a venv that shares only third-party packages with
   that interpreter (``--system-site-packages``), installs the project wheels
   with ``--no-deps --no-index``, and verifies that every project module is
   imported from the venv (``__file__``), not from a source checkout or an
   editable ``.pth`` entry;
4. runs the curated iteration-60 test files against the installed packages
   from a scratch copy (so no source tree is on ``sys.path``);
5. writes ``matrix.json`` (machine readable) and ``matrix.md`` under ``--out``.

Limits stated in the output: third-party dependencies are the interpreter's
own (not re-resolved), this is one macOS host, and no real provider, account,
Gateway deployment or remote CI is involved.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BT_ROOT = Path(__file__).resolve().parents[2]

SDK_PACKAGES = (
    ("bt_api_py", "."),
    ("bt_api_base", "bt_api/bt_api_base"),
    ("bt_api_ctp", "bt_api/bt_api_ctp"),
    ("bt_api_okx", "bt_api/bt_api_okx"),
    ("bt_api_binance", "bt_api/bt_api_binance"),
    ("bt_api_gateway", "bt_api/bt_api_gateway"),
    ("bt_api_transport_zmq", "bt_api/bt_api_transport_zmq"),
    ("bt_api_execution", "bt_api/bt_api_execution"),
    ("bt_api_risk", "bt_api/bt_api_risk"),
)

# (repository key, test file relative to that repository, helper files copied to the
# same relative path)
TESTS = (
    ("sdk", "tests/unit/test_iter60_writer_authority.py", ()),
    ("sdk", "tests/unit/test_iter60_venue_safe_correlation_ids.py", ()),
    ("sdk", "tests/unit/test_iter60_account_owner_handoff.py", ()),
    ("sdk", "tests/unit/test_iter60_handoff_local_only.py", ()),
    ("sdk", "tests/integration/test_iter60_cross_host_writer_authority.py", ()),
    # Sibling helper modules only; Base's conftest would put its src tree on sys.path.
    ("sdk", "bt_api/bt_api_base/tests/test_iter60_execution_trade_fee_events.py", ("bt_api/bt_api_base/tests/test_wire_account_codec.py", "bt_api/bt_api_base/tests/test_wire_codec_v1.py", "bt_api/bt_api_base/tests/test_wire_execution_observations.py", "bt_api/bt_api_base/tests/test_wire_strategy_account_book.py", "bt_api/bt_api_base/tests/test_wire_strategy_commands.py")),
    ("sdk", "bt_api/bt_api_base/tests/test_wire_exit_gates.py", ("bt_api/bt_api_base/tests/test_wire_account_codec.py", "bt_api/bt_api_base/tests/test_wire_codec_v1.py", "bt_api/bt_api_base/tests/test_wire_execution_observations.py", "bt_api/bt_api_base/tests/test_wire_strategy_account_book.py", "bt_api/bt_api_base/tests/test_wire_strategy_commands.py")),
    ("sdk", "bt_api/bt_api_okx/tests/test_iter60_private_push_rows.py", ()),
    ("sdk", "bt_api/bt_api_ctp/tests/test_iter60_real_client_scope_issuer.py", ()),
    ("bt", "tests/unit/brokers/test_iter60_owner_fence_writer_authority.py", ()),
    ("bt", "tests/unit/brokers/test_iter60_durable_fee_index.py",
     ("tests/integration/iter60_gateway_execution_support.py",)),
    ("bt", "tests/unit/test_iter60_target_orders_scope.py", ()),
)

MODULES = ("backtrader",) + tuple(name for name, _ in SDK_PACKAGES)


def run(cmd, *, cwd=None, env=None, check=True, timeout=3600):
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(map(str, cmd))}\n"
            f"{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    return proc, time.monotonic() - started


def git_state(path: Path) -> dict:
    def git(*args):
        proc, _ = run(["git", "-C", str(path), *args], check=False)
        return proc.stdout.strip()

    return {
        "path": str(path),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "dirty_files": len([line for line in git("status", "--porcelain").splitlines() if line]),
    }


def build(python: str, source: Path, wheelhouse: Path) -> dict:
    """Build one package; a failure is recorded, not raised (reported per package)."""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    before = set(wheelhouse.iterdir())
    proc, seconds = run(
        [python, "-m", "build", "--no-isolation", "--wheel", "--sdist",
         "--outdir", str(wheelhouse), str(source)],
        check=False,
    )
    built = sorted(p.name for p in set(wheelhouse.iterdir()) - before)
    return {
        "ok": proc.returncode == 0 and any(name.endswith(".whl") for name in built),
        "artifacts": built,
        "seconds": round(seconds, 1),
        "error_tail": "" if proc.returncode == 0 else proc.stderr.strip()[-600:],
    }


def probe_code(modules=MODULES) -> str:
    return (
        "import importlib, importlib.metadata as md, json, sys, numpy\n"
        f"mods = {tuple(modules)!r}\n"
        "import msgpack, zmq\n"
        "out = {'python': sys.version.split()[0], 'numpy': numpy.__version__, "
        "'msgpack': md.version('msgpack'), 'pyzmq': zmq.__version__, 'modules': {}}\n"
        "for name in mods:\n"
        "    mod = importlib.import_module(name)\n"
        "    dist = {'backtrader': 'back-trader-python'}.get(name, name.replace('_', '-'))\n"
        "    try:\n"
        "        version = md.version(dist)\n"
        "    except md.PackageNotFoundError:\n"
        "        version = md.version(name)\n"
        "    out['modules'][name] = {'file': mod.__file__, 'version': version}\n"
        "print(json.dumps(out))\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sdk", type=Path, default=BT_ROOT.parent / "bt_api_py")
    parser.add_argument("--python", action="append", required=True)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--pip-extra", action="append", default=[],
        help="third-party requirement installed into every venv from the package index "
             "(only when the interpreter lacks it; recorded in matrix.json)",
    )
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sdk = args.sdk.resolve()

    repos = {"backtrader": git_state(BT_ROOT), "bt_api_py": git_state(sdk)}
    for name, rel in SDK_PACKAGES[1:]:
        repos[name] = git_state(sdk / rel)

    results = []
    artifacts = {}
    for python in args.python:
        proc, _ = run([python, "-c", "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')"])
        tag = proc.stdout.strip()
        # Built per interpreter: bt_api_ctp carries a compiled extension.
        wheelhouse = out / f"wheelhouse-py{tag}"
        if wheelhouse.exists():
            shutil.rmtree(wheelhouse)
        built = {"backtrader": build(python, BT_ROOT, wheelhouse)}
        for name, rel in SDK_PACKAGES:
            built[name] = build(python, sdk / rel, wheelhouse)
        # A pure-Python wheel (py3-none-any) that this interpreter cannot build
        # (for example no Cython for the build backend) is reused from an
        # interpreter that built it; the reuse is recorded.
        for name, item in built.items():
            if item["ok"]:
                continue
            for other in artifacts.values():
                donor = other.get(name)
                pure = [a for a in (donor or {}).get("artifacts", []) if a.endswith("-py3-none-any.whl")]
                if donor and donor["ok"] and pure:
                    source_dir = next(out.glob(f"wheelhouse-py*/{pure[0]}")).parent
                    shutil.copy2(source_dir / pure[0], wheelhouse / pure[0])
                    item.update(ok=True, reused_from=str(source_dir / pure[0]))
                    break
        artifacts[f"py{tag}"] = built
        wheels = sorted(str(p) for p in wheelhouse.glob("*.whl"))
        venv = out / f"venv-py{tag}"
        if venv.exists():
            shutil.rmtree(venv)
        run([python, "-m", "venv", "--system-site-packages", str(venv)])
        vpy = str(venv / "bin" / "python")
        run([vpy, "-m", "pip", "install", "--no-deps", "--no-index", "--force-reinstall", *wheels])
        extras_installed = []
        for requirement in args.pip_extra:
            # pip decides against the version constraint; an inherited older
            # copy is shadowed by the venv's own install.
            proc, _ = run([vpy, "-m", "pip", "install", requirement])
            if "Successfully installed" in proc.stdout:
                extras_installed.append(requirement)
        clean_env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
        scratch = out / f"run-py{tag}"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir()
        missing = [name for name, item in built.items() if not item["ok"]]
        proc, _ = run([vpy, "-I", "-c", probe_code(tuple(m for m in MODULES if m not in missing))],
                      cwd=scratch, env=clean_env, check=False)
        if proc.returncode != 0:
            results.append({"python": tag, "probe_failed": proc.stderr.strip()[-800:],
                            "build_failures": missing, "extras_installed": extras_installed})
            continue
        probe = json.loads(proc.stdout.strip().splitlines()[-1])
        venv_prefix = str(venv.resolve())
        outside = {
            name: info["file"]
            for name, info in probe["modules"].items()
            if not str(Path(info["file"]).resolve()).startswith(venv_prefix)
        }
        entry = {"python": probe["python"], "numpy": probe["numpy"], "venv": str(venv),
                 "msgpack": probe["msgpack"], "pyzmq": probe["pyzmq"],
                 "build_failures": sorted(name for name, item in built.items() if not item["ok"]),
                 "extras_installed": extras_installed,
                 "modules": probe["modules"], "imported_outside_venv": outside, "tests": []}
        if not args.skip_tests:
            for repo, rel, helpers in TESTS:
                base = sdk if repo == "sdk" else BT_ROOT
                source = base / rel
                target_dir = scratch / repo / Path(rel).parent
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_dir / source.name)
                for helper in helpers:
                    destination = scratch / repo / helper
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(base / helper, destination)
                proc, seconds = run(
                    [vpy, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
                     "--rootdir", str(scratch), str(target_dir / source.name)],
                    cwd=target_dir, env=clean_env, check=False, timeout=1800,
                )
                tail = (proc.stdout.strip().splitlines() or [""])[-1]
                entry["tests"].append({"file": f"{repo}:{rel}", "returncode": proc.returncode,
                                       "summary": tail, "seconds": round(seconds, 1)})
        results.append(entry)

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": os.uname().sysname,
              "repos": repos, "artifacts": artifacts, "results": results,
              "limits": ["third-party dependencies come from each interpreter (not re-resolved)",
                         "single macOS host; no Windows/Linux; no remote CI",
                         "no real provider, account or Gateway deployment"]}
    (out / "matrix.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Iteration 60 release/install matrix", "",
             f"Generated {report['generated_at']} on {report['host']}.", ""]
    for entry in results:
        if "probe_failed" in entry:
            lines.append(f"## Python tag {entry['python']}: import probe FAILED")
            lines.append(f"```\n{entry['probe_failed']}\n```")
            continue
        lines.append(f"## Python {entry['python']} / numpy {entry['numpy']} / msgpack {entry['msgpack']} / pyzmq {entry['pyzmq']}")
        lines.append(f"- third-party requirements installed into the venv: {entry['extras_installed'] or 'none'}")
        lines.append(f"- packages whose wheel did not build: {entry['build_failures'] or 'none'}")
        lines.append(f"- modules imported outside the venv: {entry['imported_outside_venv'] or 'none'}")
        for name, info in sorted(entry["modules"].items()):
            lines.append(f"  - `{name}` {info['version']} from `{info['file']}`")
        for item in entry["tests"]:
            lines.append(f"- `{item['file']}` rc={item['returncode']}: {item['summary']}")
        lines.append("")
    (out / "matrix.md").write_text("\n".join(lines), encoding="utf-8")
    failed = any("probe_failed" in entry or entry["imported_outside_venv"] or entry["build_failures"]
                 for entry in results) or any(
        item["returncode"] != 0 for entry in results for item in entry.get("tests", [])
    )
    print(out / "matrix.md")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
