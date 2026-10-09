"""Iteration-41 optional16 acceptance-matrix runner (2 transports x 3 components).

Iterates the sixteen combinations of ``transport`` in ``{direct, gateway_zmq}``
and the three optional components ``execution`` / ``risk`` / ``monitor`` in
``{0, 1}``, runs the designated certification cases through the *existing*
``certlib.runner`` CLI in a subprocess, captures each case's summary JSON and
exit code, and writes one record per combination to ``acceptance-matrix.json``.

Modes
-----

* ``--dry`` (default): each case is invoked as its own dry self-check
  (``run.py --transport <t> [--execution] [--risk] [--monitor]``).  The dry
  path of the case runner reads the config, resolves credential *names* and
  prints its plan; it never constructs a client, so nothing touches the
  network.  Non-zero exits and BLOCKED/DRY-with-missing-env results are
  recorded honestly instead of being treated as harness failures.
* ``--live``: adds ``--live`` (plus the grants you pass) to every command.
  A human operator runs this; the runner itself performs no account work and
  imports no provider/SDK code.

The runner is read-only with respect to the suite: it never edits case files,
never imports an SDK package itself, resolves every path from the repository
root (so any CWD works), and records the exact command line of every case.

Examples::

    C:/anaconda3/python.exe <repo>/examples/000_live_certification/optional16/run_matrix.py --dry
    C:/anaconda3/python.exe .../run_matrix.py --live --allow-write --cases C01,T03
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CERT_ROOT = HERE.parent
BINANCE_ROOT = CERT_ROOT / "binance_penetration"
DEFAULT_CASES = ("C01", "T03")
DEFAULT_OUT = HERE / "acceptance-matrix.json"
DEFAULT_TIMEOUT = 180.0
SCHEMA = "optional16-acceptance-matrix/1"
TRANSPORTS = ("direct", "gateway_zmq")
COMPONENT_FLAGS = ("execution", "risk", "monitor")
EXIT_CODES = {0: "PASS", 1: "FAIL", 2: "BLOCKED", 3: "UNKNOWN"}


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _specs():
    """The sixteen combos; prefer the sibling ``optional16.spec`` module."""
    try:
        if str(CERT_ROOT) not in sys.path:
            sys.path.insert(0, str(CERT_ROOT))
        from optional16 import spec as spec_module

        return [(spec_module.combo_id(item), item.as_dict()) for item in spec_module.matrix_specs()], \
            "optional16.spec"
    except Exception:
        combos = []
        for transport in TRANSPORTS:
            for execution in (False, True):
                for risk in (False, True):
                    for monitor in (False, True):
                        flags = {"transport": transport, "execution": execution, "risk": risk,
                                 "monitor": monitor}
                        combos.append(("%s-e%d-r%d-m%d" % (transport, int(execution), int(risk),
                                                           int(monitor)), flags))
        return combos, "inline-fallback"


def _case_command(python, case_dir, flags, mode_args):
    command = [python, str(case_dir / "run.py"), "--transport", str(flags["transport"])]
    for flag in COMPONENT_FLAGS:
        if flags.get(flag):
            command.append("--" + flag)
    command.extend(mode_args)
    return command


def _extract_summary(stdout):
    """Return the case summary object: the dry plan or the live one-line summary."""
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    marker = text.rfind("\n{")
    if marker != -1:
        try:
            return json.loads(text[marker:])
        except ValueError:
            return None
    return None


def _run_case(python, case_dir, case_id, flags, mode_args, timeout):
    command = _case_command(python, case_dir, flags, mode_args)
    started = _utc_now()
    record = {"case": case_id, "command": " ".join(command), "started_utc": started}
    try:
        proc = subprocess.run(command, cwd=str(case_dir), capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        record.update({"status": "TIMEOUT", "exit_code": None, "reason": "case_timeout",
                       "stdout_tail": _tail(exc.stdout), "stderr_tail": _tail(exc.stderr)})
    except Exception as exc:
        record.update({"status": "ERROR", "exit_code": None,
                       "reason": "harness_error:%s" % type(exc).__name__, "stderr_tail": ""})
    else:
        summary = _extract_summary(proc.stdout)
        status = None
        reason = ""
        evidence = None
        if isinstance(summary, dict):
            status = str(summary.get("status") or "") or None
            reason = str(summary.get("reason") or "")
            evidence = summary.get("evidence")
        record["exit_code"] = proc.returncode
        record["status"] = status or EXIT_CODES.get(proc.returncode, "UNPARSED")
        record["reason"] = reason
        record["evidence"] = evidence
        record["summary"] = summary
        record["stdout_tail"] = _tail(proc.stdout)
        record["stderr_tail"] = _tail(proc.stderr)
    record["finished_utc"] = _utc_now()
    return record


def _tail(value, limit=400):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return value[-limit:]


def _parse_list(value, default):
    if value is None:
        return list(default)
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _print_table(rows, cases):
    width = max([len("combo")] + [len(row["combo_id"]) for row in rows])
    header = "%-*s  %s" % (width, "combo", "  ".join("%-22s" % case for case in cases))
    print(header)
    print("-" * len(header))
    for row in rows:
        cells = []
        for case in cases:
            item = row["cases"].get(case, {})
            cells.append("%-22s" % ("%s(exit %s)" % (item.get("status", "-"),
                                                     item.get("exit_code", "-"))))
        print("%-*s  %s" % (width, row["combo_id"], "  ".join(cells)))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_matrix.py", description="Run the optional16 acceptance matrix (16 combos).",
        epilog="live example: run_matrix.py --live --allow-write --cases C01,T03")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", help="dry self-checks only (default)")
    mode.add_argument("--live", action="store_true", help="add --live to every case command")
    parser.add_argument("--allow-write", action="store_true", help="pass --allow-write (live)")
    parser.add_argument("--allow-dangerous", action="store_true", help="pass --allow-dangerous (live)")
    parser.add_argument("--cases", default=None, help="comma list (default C01,T03)")
    parser.add_argument("--combos", default=None, help="comma list of combo ids to run")
    parser.add_argument("--python", default=sys.executable or "C:/anaconda3/python.exe")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    live = bool(args.live)
    if live and (args.allow_write and args.allow_dangerous):
        print("grants: --allow-write and --allow-dangerous both requested", file=sys.stderr)
    mode_args = ["--live"] if live else []
    if live and args.allow_write:
        mode_args.append("--allow-write")
    if live and args.allow_dangerous:
        mode_args.append("--allow-dangerous")

    cases = _parse_list(args.cases, DEFAULT_CASES)
    combos, spec_source = _specs()
    wanted = set(_parse_list(args.combos, ())) if args.combos else None
    if wanted is not None:
        combos = [(cid, flags) for cid, flags in combos if cid in wanted]
        missing = wanted - {cid for cid, _ in combos}
        if missing:
            print("unknown combo ids: %s" % ",".join(sorted(missing)), file=sys.stderr)
            return 2

    run_id = uuid.uuid4().hex
    started = _utc_now()
    print("optional16 matrix: mode=%s cases=%s combos=%d python=%s"
          % ("live" if live else "dry", ",".join(cases), len(combos), args.python))
    rows = []
    for combo_id, flags in combos:
        row = {"combo_id": combo_id, "transport": flags["transport"],
               "flags": {flag: bool(flags.get(flag)) for flag in COMPONENT_FLAGS},
               "started_utc": _utc_now(), "cases": {}}
        for case_id in cases:
            case_dir = BINANCE_ROOT / "cases" / case_id
            if not case_dir.is_dir():
                row["cases"][case_id] = {"case": case_id, "status": "ERROR", "exit_code": None,
                                         "reason": "case_dir_missing:%s" % case_dir}
                continue
            row["cases"][case_id] = _run_case(args.python, case_dir, case_id, flags, mode_args,
                                              args.timeout)
        row["finished_utc"] = _utc_now()
        rows.append(row)
    finished = _utc_now()

    totals = {}
    for row in rows:
        for case_id, item in row["cases"].items():
            key = "%s:%s" % (item.get("status", "UNPARSED"), case_id)
            totals[key] = totals.get(key, 0) + 1

    payload = {
        "schema": SCHEMA,
        "run_id": run_id,
        "mode": "live" if live else "dry",
        "dry": not live,
        "python": args.python,
        "repo_root": str(Path(__file__).resolve().parents[3]),
        "cert_root": str(CERT_ROOT),
        "case_root": str(BINANCE_ROOT),
        "cases": list(cases),
        "spec_source": spec_source,
        "grants": {"allow_write": bool(args.allow_write), "allow_dangerous": bool(args.allow_dangerous)},
        "started_utc": started,
        "finished_utc": finished,
        "commands": sorted({item["command"] for row in rows for item in row["cases"].values()
                            if item.get("command")}),
        "combos": rows,
        "totals": totals,
    }
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    _print_table(rows, cases)
    print("totals: %s" % ", ".join("%s=%d" % (key, value) for key, value in sorted(totals.items())))
    print("matrix written: %s" % out_path)
    if not live:
        print("live invocation: %s --live [--allow-write] [--allow-dangerous] --cases %s"
              % (Path(__file__).name, ",".join(cases)))
        return 0
    return 0 if all(item.get("status") == "PASS" for row in rows
                    for item in row["cases"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
