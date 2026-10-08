"""Source-fake checks for the V18 outer Root driver; no activation/native calls."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


DRIVER_PATH = Path(__file__).parents[1] / "root-actual-driver.py"
SPEC = importlib.util.spec_from_file_location("_simnow_v18_root_driver_source_fake", DRIVER_PATH)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)


def _pass_projection():
    return {
        "case_id": "C01",
        "certification": "PASS",
        "mode": "C01_NATIVE_TD_READ_V18",
        "profile": "C01_NATIVE_TD_READ_V18",
        "reason": "root_case_receipt_verified",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": "C01RootCaseResultReceipt",
        "receipt_verified": True,
        "source_closure_verified": True,
        "root_postverify_verified": True,
        "request_count": 8,
        "query_callback_count": 6,
        "snapshot_count": 2,
        "write_invocation_count": 0,
        "outer_job_empty": True,
        "stdout_eof": True,
        "stderr_eof": True,
        "stderr_empty": True,
        "job_handles_closed": True,
        "reader_threads_joined": True,
        "cleanup_verified": True,
    }


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _review_and_readback(driver_sha, packet_pins_sha):
    review = {
        "schema": "iteration41.simnow.v18.root_driver.independent_review.r2",
        "driver_revision": "R2",
        "status": "FINAL_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "candidate": {
            "driver_sha256": driver_sha,
            "driver_packet_pins_sha256": packet_pins_sha,
            "v18_activation_packet_pins_sha256": DRIVER.V18_PINS_SHA256,
            "wrapper_sha256": DRIVER.WRAPPER_SHA256,
            "entry_sha256": DRIVER.ENTRY_SHA256,
            "cuv2_sha256": DRIVER.CUV2_SHA256,
            "r1_parent_diagnostic_sha256": DRIVER.R1_DIAGNOSTIC_SHA256,
            "public_source_file_count": 29,
            "software_pin_count": 2,
            "held_file_count": 31,
        },
        "official_c01_pass_count": 0,
        "actual_root_provider_native_acceptance": "NOT_RUN",
        "driver_executed": False,
        "private_inputs_read": False,
    }
    review_raw = _canonical(review)
    readback = {
        "schema": "iteration41.simnow.v18.root_driver.pre_activation_readback.r2",
        "driver_revision": "R2",
        "status": "PUBLIC_SOURCE_AND_INDEPENDENT_REVIEW_MATCH",
        "driver_sha256": driver_sha,
        "driver_packet_pins_sha256": packet_pins_sha,
        "independent_review_sha256": DRIVER.sha(review_raw),
        "v18_activation_packet_pins_sha256": DRIVER.V18_PINS_SHA256,
        "wrapper_sha256": DRIVER.WRAPPER_SHA256,
        "entry_sha256": DRIVER.ENTRY_SHA256,
        "cuv2_sha256": DRIVER.CUV2_SHA256,
        "r1_parent_diagnostic_sha256": DRIVER.R1_DIAGNOSTIC_SHA256,
        "public_source_file_count": 29,
        "public_source_files_verified": 29,
        "software_pin_count": 2,
        "software_pins_verified": 2,
        "held_file_count": 31,
        "held_files_verified": 31,
        "driver_executed": False,
        "private_inputs_read": False,
        "actual_root_provider_native_acceptance": "NOT_RUN",
        "official_c01_pass_count": 0,
    }
    return _canonical(readback), review_raw


class _FakeManager:
    def __init__(self, held, *, enter_error=False):
        self.held = held
        self.closed = False
        self.enter_error = enter_error
        self.enter_count = 0
        self.exit_count = 0
        self.exit_args = []

    def __enter__(self):
        self.enter_count += 1
        if self.enter_error:
            raise RuntimeError("fake_enter_failure")
        return (SimpleNamespace(name="fake-private"), SimpleNamespace(name="fake-cli"), self.held)

    def __exit__(self, *exc):
        self.exit_count += 1
        self.exit_args.append(exc)
        self.closed = True
        return False


class _FakeCUv2:
    def __init__(self, manager):
        self.manager = manager
        self.calls = []

    def held_public_sources(self, source_pins, software_pins):
        self.calls.append((dict(source_pins), dict(software_pins)))
        return self.manager


def _source_and_software_case(tmp_path, *, projection=None, mutation=None, public_count=1):
    root = tmp_path / "repo"
    wrapper_path = root / DRIVER.WRAPPER_RELATIVE
    wrapper_path.parent.mkdir(parents=True)
    wrapper_raw = _wrapper_source(projection or _pass_projection())
    wrapper_path.write_bytes(wrapper_raw)
    source_map = {DRIVER.WRAPPER_RELATIVE: DRIVER.sha(wrapper_raw)}
    held = {str(wrapper_path).upper(): wrapper_raw}
    for index in range(public_count - 1):
        relative = f"public_payload/source_{index:02d}.py"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = f"# public source fixture {index}\n".encode("ascii")
        path.write_bytes(raw)
        source_map[relative] = DRIVER.sha(raw)
        held[str(path).replace("\\", "/").upper()] = raw

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    software_bytes = {
        runtime / "python.exe": b"fake python executable bytes",
        runtime / "python311.dll": b"fake python DLL bytes",
    }
    software_pins = {}
    for path, raw in software_bytes.items():
        path.write_bytes(raw)
        software_pins[str(path)] = DRIVER.sha(raw)

    for path, raw in software_bytes.items():
        if mutation == "software_missing" and path.name == "python311.dll":
            continue
        if mutation == "software_tamper" and path.name == "python311.dll":
            raw = b"tampered software bytes"
        held[str(path).replace("\\", "/").upper()] = raw
    if mutation == "software_extra":
        held[str(runtime / "unexpected.exe").upper()] = b"unexpected software"

    cuv2_path = tmp_path / "cuv2.py"
    cuv2_raw = b"fake CUV2 bytes for source-fake test"
    cuv2_path.write_bytes(cuv2_raw)
    manager = _FakeManager(held)
    cuv2 = _FakeCUv2(manager)
    return {
        "root": root,
        "wrapper_path": wrapper_path,
        "wrapper_raw": wrapper_raw,
        "source_map": source_map,
        "software_pins": software_pins,
        "cuv2_path": cuv2_path,
        "cuv2_raw": cuv2_raw,
        "manager": manager,
        "cuv2": cuv2,
    }


def _wrapper_source(projection, *, retain_unresolved=False):
    encoded = repr(projection)
    retained_append = (
        "    _ROOT_RETAINED_UNRESOLVED_JOB_REFS.append(('fake-job', 'fake-pipe'))\n"
        if retain_unresolved
        else ""
    )
    return (
        "import json\n"
        "SEEN_ARGV = None\n"
        "SEVEN_VALUE_CONSTRUCTOR = None\n"
        "_ROOT_RETAINED_UNRESOLVED_JOB_REFS = []\n"
        f"PROJECTION = {encoded}\n"
        "def _fake_seven_value_constructor():\n"
        "    global SEVEN_VALUE_CONSTRUCTOR\n"
        "    values = ('bundle', 'policy', b'runner', b'entry', {'source': 'pin'}, {'exe': 'pin'}, {'all': 'pins'})\n"
        "    bundle, policy, runner_source, entry_raw, public_pins, software_pins, complete_pins = values\n"
        "    SEVEN_VALUE_CONSTRUCTOR = (bundle, policy, runner_source, entry_raw, public_pins, software_pins, complete_pins)\n"
        "def main(argv=None):\n"
        "    global SEEN_ARGV\n"
        "    SEEN_ARGV = list(argv or [])\n"
        "    _fake_seven_value_constructor()\n"
        f"{retained_append}"
        "    print(json.dumps(PROJECTION, sort_keys=True, separators=(',', ':')))\n"
        "    return 0 if PROJECTION['certification'] == 'PASS' else 2\n"
    ).encode("utf-8")


def test_packet_self_pins_and_all_29_public_sources_match():
    pins_raw = DRIVER.PINS_PATH.read_bytes()
    pins = DRIVER.parse_ascii_json(pins_raw)
    loaded, _, driver_raw = DRIVER.verify_packet_and_sources(DRIVER.sha(pins_raw))
    assert len(loaded["source_payload_files"]) == 29
    assert DRIVER.sha(driver_raw) == next(
        row["sha256"] for row in loaded["packet_files"] if row["path"] == "root-actual-driver.py"
    )
    assert pins["v18_activation_packet_pins_sha256"] == DRIVER.V18_PINS_SHA256


def test_final_review_and_readback_bind_driver_packet_and_wrapper():
    driver_sha = "a" * 64
    packet_pins_sha = "b" * 64
    readback_raw, review_raw = _review_and_readback(driver_sha, packet_pins_sha)
    readback, review = DRIVER.verify_review_readback(
        readback_raw,
        review_raw,
        expected_readback_sha256=DRIVER.sha(readback_raw),
        expected_review_sha256=DRIVER.sha(review_raw),
        expected_packet_pins_sha256=packet_pins_sha,
        driver_sha256=driver_sha,
    )
    assert readback["public_source_files_verified"] == 29
    assert review["verdict"] == "GO_SOURCE_FAKE_ONLY"


def test_readback_rejects_review_change_and_unreviewed_candidate():
    driver_sha = "a" * 64
    packet_pins_sha = "b" * 64
    readback_raw, review_raw = _review_and_readback(driver_sha, packet_pins_sha)
    with __import__("pytest").raises(DRIVER.DriverBlocked):
        DRIVER.verify_review_readback(
            readback_raw,
            review_raw,
            expected_readback_sha256=DRIVER.sha(readback_raw),
            expected_review_sha256="c" * 64,
            expected_packet_pins_sha256=packet_pins_sha,
            driver_sha256=driver_sha,
        )
    bad_readback, review_raw = _review_and_readback(driver_sha, packet_pins_sha)
    bad = json.loads(bad_readback.decode("ascii"))
    bad["status"] = "PENDING"
    bad_raw = _canonical(bad)
    with __import__("pytest").raises(DRIVER.DriverBlocked):
        DRIVER.verify_review_readback(
            bad_raw,
            review_raw,
            expected_readback_sha256=DRIVER.sha(bad_raw),
            expected_review_sha256=DRIVER.sha(review_raw),
            expected_packet_pins_sha256=packet_pins_sha,
            driver_sha256=driver_sha,
        )


def test_outer_main_argv_and_seven_value_constructor_are_sourcefake_only(tmp_path, capsys):
    DRIVER.KEEPALIVE.clear()
    case = _source_and_software_case(tmp_path, public_count=29)
    result, lease, activation = DRIVER.activate_with_held_sources(
        case["cuv2"],
        case["cuv2_raw"],
        source_map=case["source_map"],
        software_pins=case["software_pins"],
        wrapper_relative=DRIVER.WRAPPER_RELATIVE,
        wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
        root=case["root"],
        cuv2_path=case["cuv2_path"],
        cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
    )
    assert capsys.readouterr().out == ""
    public_call, software_call = case["cuv2"].calls[0]
    assert public_call[str(case["wrapper_path"])] == DRIVER.sha(case["wrapper_raw"])
    assert software_call == case["software_pins"]
    assert len(public_call) == 29 and len(software_call) == 2
    assert activation.SEEN_ARGV == [
        "--activate-c01-v18-td-read",
        "--expected-wrapper-sha256",
        DRIVER.sha(case["wrapper_raw"]),
    ]
    assert len(activation.SEVEN_VALUE_CONSTRUCTOR) == 7
    assert case["manager"].closed and case["manager"].exit_count == 1
    assert case["manager"].exit_args == [(None, None, None)]
    assert lease.closed and lease.verify_held()
    assert lease.public_source_count == 29 and lease.software_pin_count == 2
    assert lease.postverify_and_close(
        cuv2_path=case["cuv2_path"], cuv2_sha256=DRIVER.sha(case["cuv2_raw"])
    ) is False
    assert case["manager"].exit_count == 1
    assert result["profile_result"] == _pass_projection()
    assert result["outer_cuv2_postverify_verified"] is True
    assert result["outer_cuv2_scope_closed"] is True
    assert result["public_source_file_count"] == 29
    assert result["software_pin_count"] == 2
    assert result["held_file_count"] == 31
    assert result["official_c01_pass_count"] == 0
    assert result["opaque_receipt_seen_by_driver"] is False
    sys.modules.pop(activation.__name__, None)


@__import__("pytest").mark.parametrize(
    "mutation", ["software_tamper", "software_missing", "software_extra"]
)
def test_bad_software_hold_map_blocks_before_wrapper_and_retains_uncertain_scope(
    tmp_path, mutation
):
    DRIVER.KEEPALIVE.clear()
    case = _source_and_software_case(tmp_path, mutation=mutation)
    with __import__("pytest").raises(DRIVER.DriverBlocked):
        DRIVER.activate_with_held_sources(
            case["cuv2"],
            case["cuv2_raw"],
            source_map=case["source_map"],
            software_pins=case["software_pins"],
            wrapper_relative=DRIVER.WRAPPER_RELATIVE,
            wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
            root=case["root"],
            cuv2_path=case["cuv2_path"],
            cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
        )
    assert len(case["cuv2"].calls) == 1
    assert len(case["cuv2"].calls[0][0]) == 1
    assert len(case["cuv2"].calls[0][1]) == 2
    assert case["manager"].enter_count == 1
    assert case["manager"].exit_count == 0
    assert DRIVER.KEEPALIVE
    assert "_iteration41_simnow_c01_v18_root_activation_wrapper" not in sys.modules
    DRIVER.KEEPALIVE.clear()


def test_pre_wrapper_failure_normally_exits_and_postverifies_valid_hold(tmp_path, monkeypatch):
    DRIVER.KEEPALIVE.clear()
    case = _source_and_software_case(tmp_path)

    def fail_wrapper_load(*_args, **_kwargs):
        raise DRIVER.DriverBlocked("synthetic_wrapper_load_failure")

    monkeypatch.setattr(DRIVER, "_load_module", fail_wrapper_load)
    with __import__("pytest").raises(DRIVER.DriverBlocked, match="synthetic_wrapper_load_failure"):
        DRIVER.activate_with_held_sources(
            case["cuv2"],
            case["cuv2_raw"],
            source_map=case["source_map"],
            software_pins=case["software_pins"],
            wrapper_relative=DRIVER.WRAPPER_RELATIVE,
            wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
            root=case["root"],
            cuv2_path=case["cuv2_path"],
            cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
        )
    assert case["manager"].closed is True
    assert case["manager"].exit_count == 1
    assert case["manager"].exit_args == [(None, None, None)]
    assert DRIVER.KEEPALIVE == []


def test_unentered_cuv2_context_is_never_exited(tmp_path):
    DRIVER.KEEPALIVE.clear()
    case = _source_and_software_case(tmp_path)
    case["manager"].enter_error = True
    with __import__("pytest").raises(RuntimeError, match="fake_enter_failure"):
        DRIVER.activate_with_held_sources(
            case["cuv2"],
            case["cuv2_raw"],
            source_map=case["source_map"],
            software_pins=case["software_pins"],
            wrapper_relative=DRIVER.WRAPPER_RELATIVE,
            wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
            root=case["root"],
            cuv2_path=case["cuv2_path"],
            cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
        )
    assert case["manager"].enter_count == 1
    assert case["manager"].exit_count == 0
    assert DRIVER.KEEPALIVE == []


def test_public_software_overlap_rejected_before_cuv2_entry(tmp_path):
    DRIVER.KEEPALIVE.clear()
    manager = _FakeManager({})
    cuv2 = _FakeCUv2(manager)
    with __import__("pytest").raises(DRIVER.DriverBlocked, match="public_software_pin_overlap"):
        DRIVER.activate_with_held_sources(
            cuv2,
            b"fake CUv2 source",
            source_map={"python.exe": "a" * 64},
            software_pins={
                "C:/ANACONDA3/python.exe": "a" * 64,
                "C:/anaconda3/python311.dll": "b" * 64,
            },
            wrapper_relative=DRIVER.WRAPPER_RELATIVE,
            wrapper_sha256="a" * 64,
            root=Path("C:/anaconda3"),
            cuv2_path=tmp_path / "unused-cuv2.py",
        )
    assert cuv2.calls == []
    assert manager.enter_count == 0
    assert manager.exit_count == 0
    assert DRIVER.KEEPALIVE == []


def test_uncertain_same_call_cleanup_retains_hold_and_never_publishes_pass(tmp_path, capsys):
    DRIVER.KEEPALIVE.clear()
    blocked = DRIVER._blocked_projection("synthetic_cleanup_uncertain")
    case = _source_and_software_case(tmp_path, projection=blocked)
    result, lease, activation = DRIVER.activate_with_held_sources(
        case["cuv2"],
        case["cuv2_raw"],
        source_map=case["source_map"],
        software_pins=case["software_pins"],
        wrapper_relative=DRIVER.WRAPPER_RELATIVE,
        wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
        root=case["root"],
        cuv2_path=case["cuv2_path"],
        cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
    )
    assert capsys.readouterr().out == ""
    assert result["profile_result"]["certification"] == "BLOCKED"
    assert result["outer_cuv2_postverify_verified"] is False
    assert result["outer_cuv2_scope_closed"] is False
    assert not case["manager"].closed and case["manager"].exit_count == 0
    assert lease.closed is False
    assert DRIVER.KEEPALIVE
    assert any(activation in refs for refs in DRIVER.KEEPALIVE if type(refs) is tuple)
    sys.modules.pop(activation.__name__, None)


def test_same_call_retention_list_overrides_nominal_pass_and_keeps_scope(tmp_path, capsys):
    DRIVER.KEEPALIVE.clear()
    case = _source_and_software_case(tmp_path)
    case["wrapper_raw"] = _wrapper_source(_pass_projection(), retain_unresolved=True)
    case["wrapper_path"].write_bytes(case["wrapper_raw"])
    case["source_map"] = {DRIVER.WRAPPER_RELATIVE: DRIVER.sha(case["wrapper_raw"])}
    case["manager"].held = {
        str(case["wrapper_path"]).upper(): case["wrapper_raw"],
        **{
            str(Path(path)).upper(): Path(path).read_bytes()
            for path in case["software_pins"]
        },
    }
    case["cuv2"].manager = case["manager"]
    with __import__("pytest").raises(DRIVER.DriverBlocked, match="wrapper_same_call_unresolved_job_refs"):
        DRIVER.activate_with_held_sources(
            case["cuv2"],
            case["cuv2_raw"],
            source_map=case["source_map"],
            software_pins=case["software_pins"],
            wrapper_relative=DRIVER.WRAPPER_RELATIVE,
            wrapper_sha256=DRIVER.sha(case["wrapper_raw"]),
            root=case["root"],
            cuv2_path=case["cuv2_path"],
            cuv2_sha256=DRIVER.sha(case["cuv2_raw"]),
        )
    assert capsys.readouterr().out == ""
    assert not case["manager"].closed and case["manager"].exit_count == 0
    module = sys.modules["_iteration41_simnow_c01_v18_root_activation_wrapper"]
    assert module._ROOT_RETAINED_UNRESOLVED_JOB_REFS == [("fake-job", "fake-pipe")]
    assert module in DRIVER.KEEPALIVE
    assert module._ROOT_RETAINED_UNRESOLVED_JOB_REFS in DRIVER.KEEPALIVE
    assert any(type(refs) is tuple and refs[0] is not None for refs in DRIVER.KEEPALIVE)
    sys.modules.pop(module.__name__, None)


def test_public_projection_rejects_opaque_receipt_and_pass_without_outer_close():
    projection = _pass_projection()
    with __import__("pytest").raises(DRIVER.DriverBlocked):
        DRIVER.validate_public_result({**projection, "opaque_receipt": {"front_id": "secret"}}, 0)
    candidate = DRIVER._driver_result(projection, outer_postverify=False, outer_closed=False)
    assert candidate["profile_result"]["certification"] == "BLOCKED"
    assert candidate["profile_result"]["reason"] == "outer_cuv2_postverify_failed"
    assert candidate["outer_cuv2_postverify_verified"] is False
    assert candidate["outer_cuv2_scope_closed"] is False
    assert candidate["formal_c01_pass"] is False
    assert candidate["official_c01_pass_count"] == 0


def test_optimized_mode_fails_before_cli_or_activation():
    result = subprocess.run(
        [sys.executable, "-O", "-I", "-S", "-B", str(DRIVER_PATH)],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"optimized_python_not_supported" in result.stderr
    assert b"usage:" not in result.stderr.lower()
    assert result.stdout == b""

