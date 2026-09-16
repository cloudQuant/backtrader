#!/usr/bin/env python
"""Create one sealed, zero-network Iteration 27 T7 MF-T1 acceptance attempt.

The versioned oracle, case manifest, and pytest-node manifest are pinned by
SHA256.  A current worktree result is deliberately lower evidence than a
clean-commit result; neither proves CTP, SimNow, fills, PnL, or profitability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

ROOT = Path(__file__).parent.parent
LOG_ROOT = ROOT / "logs"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "iter27_mf_t1"
ORACLE = FIXTURE_ROOT / "frozen_oracle.py"
CASES = FIXTURE_ROOT / "case_manifest.json"
NODES = FIXTURE_ROOT / "pytest_node_manifest.json"
PRODUCT_NEGATIVE = FIXTURE_ROOT / "product_negative_contracts.json"
BASE_PYTHON = Path("/Users/yunjinqi/opt/anaconda3/bin/python")
ORACLE_SHA256 = "28a6b7272632f277a768b2b7a5e6edea0567406cc1c6671551ae9c02ceb13a3a"
CASES_SHA256 = "3c309fb6ba15d2f820052dcb85a8679b72b4a240bcad4a57d5571ec933cfdc90"
NODES_SHA256 = "e7bbc368821960f6f933e85ec9f1036c976076a1183b71f1832f143057aaa0e3"
PRODUCT_NEGATIVE_SHA256 = "3b68efa917ffa7e886f4450887ca203ad04604c1284fe07a5e0b13b9fa3ca054"
FIXTURES = (
    ("oracle_template", ORACLE, ORACLE_SHA256),
    ("case_manifest", CASES, CASES_SHA256),
    ("pytest_node_manifest", NODES, NODES_SHA256),
    ("product_negative_contracts", PRODUCT_NEGATIVE, PRODUCT_NEGATIVE_SHA256),
)
RUNNER_RELATIVE = Path("scripts/run_iter27_mf_t1_independent_acceptance.py")
FROZEN_MATERIAL_ARTIFACTS = (
    Path("tests/fixtures/iter27_mf_t1/frozen_oracle.py"),
    Path("tests/fixtures/iter27_mf_t1/case_manifest.json"),
    Path("tests/fixtures/iter27_mf_t1/pytest_node_manifest.json"),
    Path("tests/fixtures/iter27_mf_t1/product_negative_contracts.json"),
)
CONTROLLED_ARTIFACTS = (
    RUNNER_RELATIVE,
    *FROZEN_MATERIAL_ARTIFACTS,
)
PYTEST_CONFIGS = (Path("pytest.ini"), Path("conftest.py"), Path("pyproject.toml"))
PYTEST_ARGS = ("-q", "-p", "no:cacheprovider", "-p", "no:rerunfailures")
SOURCE_ROOTS = (Path("backtrader"), Path("examples/014_2_ctp_options_midfreq"))
SOURCE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}
SCENARIO_COUNT = 73
ROOT_IDS = tuple(f"ROOT-MFT1-{item:02d}" for item in range(1, 17))
PRODUCT_NEGATIVE_CONTRACT_COUNT = 32
PRODUCT_NEGATIVE_USE_COUNT = 35

# Every deterministic setup refusal has a stable type/code/message contract.
ERRORS = {
    "BASE_CONDA_INTERPRETER_REQUIRED": "The runner must execute with the exact base Conda Python interpreter.",
    "CLEAN_COMMIT_ARTIFACTS_REQUIRED": (
        "Strict acceptance requires every source-binding input and product source to be "
        "tracked in HEAD, index-clean, worktree-clean, and free of relevant untracked or "
        "ignored paths."
    ),
    "COPIED_MF_ORACLE_TEMPLATE_SHA256_MISMATCH": (
        "The copied frozen MF-T1 oracle does not match its pinned SHA256."
    ),
    "COPIED_MF_T1_CASE_MANIFEST_SHA256_MISMATCH": (
        "The copied MF-T1 case manifest does not match its pinned SHA256."
    ),
    "COPIED_MF_T1_PYTEST_NODE_MANIFEST_SHA256_MISMATCH": (
        "The copied MF-T1 pytest-node manifest does not match its pinned SHA256."
    ),
    "COPIED_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_SHA256_MISMATCH": (
        "The copied MF-T1 product-negative contract manifest does not match its pinned SHA256."
    ),
    "FROZEN_MF_T1_CASE_MANIFEST_INVALID": "The frozen MF-T1 case manifest has an invalid schema.",
    "FROZEN_MF_T1_FIXTURE_MISSING": "A required frozen MF-T1 fixture is missing.",
    "FROZEN_MF_T1_FIXTURE_PATH_IGNORED": (
        "The runner and frozen MF-T1 fixtures must not be ignored by Git."
    ),
    "FROZEN_MF_T1_FIXTURE_SHA256_MISMATCH": (
        "The frozen MF-T1 fixture material does not match the pinned SHA256 values."
    ),
    "FROZEN_MF_T1_PYTEST_NODE_MANIFEST_INVALID": (
        "The frozen MF-T1 pytest-node manifest has an invalid schema."
    ),
    "FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID": (
        "The frozen MF-T1 product-negative contract manifest has an invalid schema."
    ),
    "FROZEN_MF_T1_ROOT_ORACLES_INVALID": (
        "The frozen MF-T1 root oracle commitments are missing or out of order."
    ),
    "FROZEN_MF_T1_SCENARIO_COUNT_INVALID": (
        "The frozen MF-T1 case manifest does not declare exactly 73 unique scenarios."
    ),
    "SOURCE_BINDING_INPUT_MISSING": (
        "A required source-binding, runner, fixture, or pytest configuration input is missing."
    ),
}


class AttemptSetupError(RuntimeError):
    """A fail-closed setup refusal with an explicit stable contract."""

    def __init__(self, code: str) -> None:
        if code not in ERRORS:
            raise ValueError(f"unknown Iter27 MF-T1 setup code: {code}")
        self.code = code
        self.message = ERRORS[code]
        super().__init__(f"{code}: {self.message}")


class ParentGuard:
    """Install before setup reads and allow only declared local subprocesses."""

    REQUIRED = frozenset(
        {
            "child-oracle",
            "git-cat-file",
            "git-check-ignore",
            "git-diff-cached",
            "git-diff-worktree",
            "git-ls-files",
            "git-untracked",
        }
    )
    CTP_NAMES = frozenset(
        {
            "Init",
            "RegisterFront",
            "ReqAuthenticate",
            "ReqUserLogin",
            "ReqOrderInsert",
            "ReqOrderAction",
            "ReqSettlementInfoConfirm",
            "CreateFtdcTraderApi",
            "CreateFtdcMdApi",
        }
    )

    def __init__(self) -> None:
        self.original_popen = subprocess.Popen
        self.original_profile = sys.getprofile()
        self.pending: tuple[str, tuple[str, ...]] | None = None
        self.records: list[dict[str, Any]] = []
        self.dotenv: list[dict[str, str]] = []
        self.network: list[dict[str, str]] = []
        self.native: list[dict[str, str]] = []
        self.undeclared: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.installed_before_setup = False

    @staticmethod
    def _command(command: Any) -> tuple[str, ...]:
        return (
            tuple(str(part) for part in command)
            if isinstance(command, (list, tuple))
            else (str(command),)
        )

    def install(self) -> None:
        self.installed_before_setup = True
        sys.addaudithook(self.audit)
        sys.setprofile(self.profile)
        subprocess.Popen = self.popen  # type: ignore[assignment]

    def close(self) -> None:
        subprocess.Popen = self.original_popen  # type: ignore[assignment]
        sys.setprofile(self.original_profile)

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args and Path(str(args[0])).name == ".env":
            self.dotenv.append({"event": event, "path": str(args[0])})
            self.errors.append("ITER27_MF_T1_DOTENV_FORBIDDEN")
            raise RuntimeError("ITER27_MF_T1_DOTENV_FORBIDDEN")
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}:
            self.network.append({"event": event, "arguments": repr(args)})
            self.errors.append("ITER27_MF_T1_NETWORK_FORBIDDEN")
            raise RuntimeError("ITER27_MF_T1_NETWORK_FORBIDDEN")

    def profile(self, frame: Any, event: str, arg: Any) -> None:
        if event != "c_call":
            return
        module = getattr(arg, "__module__", "") or ""
        name = getattr(arg, "__name__", "")
        if "_ctp" in module and name in self.CTP_NAMES:
            self.native.append({"module": module, "name": name})
            self.errors.append("ITER27_MF_T1_NATIVE_FORBIDDEN")
            raise RuntimeError("ITER27_MF_T1_NATIVE_FORBIDDEN")

    def popen(self, command: Any, *args: Any, **kwargs: Any) -> Any:
        actual = self._command(command)
        if self.pending is None:
            self.undeclared.append({"command": list(actual), "reason": "no-label"})
            self.errors.append("ITER27_MF_T1_UNDECLARED_PARENT_SUBPROCESS")
            raise RuntimeError("ITER27_MF_T1_UNDECLARED_PARENT_SUBPROCESS")
        label, expected = self.pending
        if actual != expected:
            self.undeclared.append(
                {
                    "command": list(actual),
                    "expected": list(expected),
                    "label": label,
                    "reason": "mismatch",
                }
            )
            self.errors.append("ITER27_MF_T1_PARENT_SUBPROCESS_MISMATCH")
            raise RuntimeError("ITER27_MF_T1_PARENT_SUBPROCESS_MISMATCH")
        self.records.append({"command": list(actual), "label": label})
        return self.original_popen(command, *args, **kwargs)

    def run(
        self, label: str, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if label not in self.REQUIRED or self.pending is not None:
            self.undeclared.append(
                {"command": command, "label": label, "reason": "invalid-label-or-reentry"}
            )
            self.errors.append("ITER27_MF_T1_PARENT_GUARD_PROTOCOL")
            raise RuntimeError("ITER27_MF_T1_PARENT_GUARD_PROTOCOL")
        self.pending = (label, tuple(command))
        try:
            return subprocess.run(command, **kwargs)
        finally:
            self.pending = None

    def receipt(self) -> dict[str, Any]:
        labels = [record["label"] for record in self.records]
        counts = Counter(labels)
        required = sorted(self.REQUIRED)
        return {
            "coverage_complete": all(counts[label] > 0 for label in required),
            "coverage_counts": {label: counts[label] for label in required},
            "coverage_labels": labels,
            "declared_subprocesses": self.records,
            "dotenv_attempts": self.dotenv,
            "error": None if not self.errors else self.errors[0],
            "guard_errors": self.errors,
            "installed_before_setup": self.installed_before_setup,
            "native_forbidden_calls": self.native,
            "network_attempts": self.network,
            "required_coverage_labels": required,
            "undeclared_subprocesses": self.undeclared,
        }


def configure_paths_after_guard() -> None:
    """Resolve filesystem paths only after the parent audit is active."""

    global \
        BASE_PYTHON, \
        CASES, \
        FIXTURE_ROOT, \
        FIXTURES, \
        LOG_ROOT, \
        NODES, \
        ORACLE, \
        PRODUCT_NEGATIVE, \
        ROOT
    ROOT = ROOT.resolve()
    LOG_ROOT = ROOT / "logs"
    FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "iter27_mf_t1"
    ORACLE = FIXTURE_ROOT / "frozen_oracle.py"
    CASES = FIXTURE_ROOT / "case_manifest.json"
    NODES = FIXTURE_ROOT / "pytest_node_manifest.json"
    PRODUCT_NEGATIVE = FIXTURE_ROOT / "product_negative_contracts.json"
    BASE_PYTHON = BASE_PYTHON.resolve()
    FIXTURES = (
        ("oracle_template", ORACLE, ORACLE_SHA256),
        ("case_manifest", CASES, CASES_SHA256),
        ("pytest_node_manifest", NODES, NODES_SHA256),
        ("product_negative_contracts", PRODUCT_NEGATIVE, PRODUCT_NEGATIVE_SHA256),
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="A new directory below logs/.")
    parser.add_argument(
        "--attestation-mode",
        choices=("auto", "clean-commit", "worktree"),
        default="auto",
        help="auto selects clean-commit only when every source-binding input is clean in HEAD.",
    )
    return parser.parse_args()


def output_path(raw: str) -> Path:
    output = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        output.relative_to(LOG_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("--output-dir must be inside logs/") from exc
    if output.exists():
        raise FileExistsError(f"refusing to reuse acceptance output directory: {output}")
    output.mkdir(parents=True, mode=0o700)
    return output


def source_binding_paths() -> tuple[Path, ...]:
    """Return every existing file whose bytes can affect this local oracle run."""

    files: set[Path] = set()
    for item in (*CONTROLLED_ARTIFACTS, *PYTEST_CONFIGS):
        path = ROOT / item
        if not path.is_file():
            raise AttemptSetupError("SOURCE_BINDING_INPUT_MISSING")
        files.add(path)
    for root in SOURCE_ROOTS:
        full_root = ROOT / root
        if not full_root.is_dir():
            raise AttemptSetupError("SOURCE_BINDING_INPUT_MISSING")
        files.update(
            item
            for item in full_root.rglob("*")
            if item.is_file() and item.suffix in SOURCE_SUFFIXES
        )
    return tuple(sorted(files, key=rel))


def source_binding_scopes() -> tuple[str, ...]:
    """Return Git path scopes that also surface deleted or new relevant inputs."""

    return tuple(
        sorted({str(item) for item in (*CONTROLLED_ARTIFACTS, *PYTEST_CONFIGS, *SOURCE_ROOTS)})
    )


def source_hashes() -> dict[str, str]:
    return {rel(path): sha256(path) for path in source_binding_paths()}


def frozen_material_source_kind(tracking: dict[str, Any]) -> str:
    """Describe fixture provenance from its actual Git state, never a label alone."""

    frozen_tracking = tracking.get("frozen_material_tracking", {})
    if isinstance(frozen_tracking, dict) and frozen_tracking.get("clean_commit_ready") is True:
        return "clean-commit-pinned-fixture"
    return "worktree-pinned-fixture"


def frozen_material(tracking: dict[str, Any]) -> tuple[dict[str, bytes | None], dict[str, Any]]:
    payloads: dict[str, bytes | None] = {}
    expected: dict[str, str] = {}
    actual: dict[str, str | None] = {}
    paths: dict[str, str] = {}
    for name, path, pinned in FIXTURES:
        key = f"{name}_sha256"
        paths[name] = rel(path)
        expected[key] = pinned
        try:
            payload = path.read_bytes()
        except OSError:
            payload = None
        payloads[name] = payload
        actual[key] = hashlib.sha256(payload).hexdigest() if payload is not None else None
    return payloads, {
        "actual": actual,
        "expected": expected,
        "fixture_paths": paths,
        "matches_canonical_sha256": actual == expected,
        "reference_fields_used": [
            "frozen oracle program",
            "case ids",
            "root contracts",
            "product negative contracts",
            "pytest testcase names",
        ],
        "source_kind": frozen_material_source_kind(tracking),
        "source_tracking": tracking.get("frozen_material_tracking", {}),
    }


def decode(payload: bytes, code: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttemptSetupError(code) from exc


def product_negative_contracts(payload: bytes) -> dict[str, Any]:
    """Validate the frozen exact product error/projection contract table."""

    document = decode(payload, "FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
    contracts = document.get("contracts") if isinstance(document, dict) else None
    expected_fields = {
        "code",
        "exception_class",
        "kind",
        "message",
        "normal_exit_allowed",
        "risk_action",
        "token_is_none",
    }
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != "backtrader.iter27.mf-t1-product-negative-contracts.v1"
        or not isinstance(contracts, dict)
        or len(contracts) != PRODUCT_NEGATIVE_CONTRACT_COUNT
    ):
        raise AttemptSetupError("FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
    use_count = 0
    for identifier, definition in contracts.items():
        if not isinstance(identifier, str) or not identifier or not isinstance(definition, dict):
            raise AttemptSetupError("FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
        expected = definition.get("expected")
        count = definition.get("expected_use_count")
        if (
            not isinstance(expected, dict)
            or set(expected) != expected_fields
            or type(count) is not int
            or count <= 0
        ):
            raise AttemptSetupError("FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
        use_count += count
        if expected["kind"] == "exception":
            if expected["exception_class"] == "TimingContractError":
                code_valid = expected["code"] is None
            elif expected["exception_class"] == "ConfigurationError":
                code_valid = isinstance(expected["code"], str) and bool(expected["code"])
            else:
                code_valid = False
            valid = (
                code_valid
                and isinstance(expected["message"], str)
                and expected["message"]
                and expected["normal_exit_allowed"] is None
                and expected["risk_action"] is None
                and expected["token_is_none"] is None
            )
        elif expected["kind"] == "projection":
            valid = (
                isinstance(expected["code"], str)
                and expected["code"]
                and expected["exception_class"] is None
                and expected["message"] is None
                and type(expected["normal_exit_allowed"]) is bool
                and isinstance(expected["risk_action"], str)
                and expected["risk_action"]
                and type(expected["token_is_none"]) is bool
            )
        else:
            valid = False
        if not valid:
            raise AttemptSetupError("FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
    if use_count != PRODUCT_NEGATIVE_USE_COUNT:
        raise AttemptSetupError("FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID")
    return document


def reference(
    payloads: dict[str, bytes | None], integrity: dict[str, Any]
) -> tuple[list[str], dict[str, list[str]], list[str], dict[str, Any]]:
    if any(value is None for value in payloads.values()):
        raise AttemptSetupError("FROZEN_MF_T1_FIXTURE_MISSING")
    if integrity.get("matches_canonical_sha256") is not True:
        raise AttemptSetupError("FROZEN_MF_T1_FIXTURE_SHA256_MISMATCH")
    case_doc = decode(payloads["case_manifest"], "FROZEN_MF_T1_CASE_MANIFEST_INVALID")  # type: ignore[arg-type]
    if (
        not isinstance(case_doc, dict)
        or case_doc.get("schema_version") != "backtrader.iter27.mf-t1-case-manifest.v1"
        or not isinstance(case_doc.get("cases"), list)
    ):
        raise AttemptSetupError("FROZEN_MF_T1_CASE_MANIFEST_INVALID")
    rows = case_doc["cases"]
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if (
        len(rows) != SCENARIO_COUNT
        or len(ids) != SCENARIO_COUNT
        or any(not isinstance(item, str) for item in ids)
        or len(set(ids)) != SCENARIO_COUNT
    ):
        raise AttemptSetupError("FROZEN_MF_T1_SCENARIO_COUNT_INVALID")
    roots: dict[str, list[str]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("id") in ROOT_IDS:
            contracts = row.get("contracts")
            if not isinstance(contracts, list) or any(
                not isinstance(item, str) for item in contracts
            ):
                raise AttemptSetupError("FROZEN_MF_T1_ROOT_ORACLES_INVALID")
            roots[row["id"]] = contracts
    if tuple(roots) != ROOT_IDS or len(roots) != len(ROOT_IDS):
        raise AttemptSetupError("FROZEN_MF_T1_ROOT_ORACLES_INVALID")

    node_doc = decode(payloads["pytest_node_manifest"], "FROZEN_MF_T1_PYTEST_NODE_MANIFEST_INVALID")  # type: ignore[arg-type]
    names = node_doc.get("testcase_names") if isinstance(node_doc, dict) else None
    if (
        not isinstance(node_doc, dict)
        or node_doc.get("schema_version") != "backtrader.iter27.mf-t1-pytest-node-manifest.v1"
        or not isinstance(names, list)
        or len(names) != SCENARIO_COUNT
        or any(not isinstance(item, str) or not item for item in names)
        or len(set(names)) != SCENARIO_COUNT
    ):
        raise AttemptSetupError("FROZEN_MF_T1_PYTEST_NODE_MANIFEST_INVALID")
    product_contracts = product_negative_contracts(payloads["product_negative_contracts"])  # type: ignore[arg-type]
    return ids, roots, names, product_contracts


def require_base(attestation: dict[str, Any]) -> None:
    if attestation.get("matches_base_conda") is not True:
        raise AttemptSetupError("BASE_CONDA_INTERPRETER_REQUIRED")


def require_nonignored(tracking: dict[str, Any]) -> None:
    if tracking.get("paths_not_ignored") is not True:
        raise AttemptSetupError("FROZEN_MF_T1_FIXTURE_PATH_IGNORED")


def require_clean_commit(tracking: dict[str, Any]) -> None:
    if tracking.get("clean_commit_ready") is not True:
        raise AttemptSetupError("CLEAN_COMMIT_ARTIFACTS_REQUIRED")


def receipt_exit_code(*, accepted: bool) -> int:
    """Return success only for an accepted clean-commit receipt.

    A passing current-worktree execution is useful diagnostic evidence, but it
    is deliberately not acceptance: its runner, fixture, and source binding
    can still be changed locally. Keeping the rule here makes the process
    result directly regression-testable.
    """

    return 0 if accepted else 1


def effective_attestation_mode(requested: str, tracking: dict[str, Any]) -> str:
    """Resolve ``auto`` from the same full source-binding audit used for acceptance."""

    if requested == "auto":
        return "clean-commit" if tracking.get("clean_commit_ready") is True else "worktree"
    if requested in {"clean-commit", "worktree"}:
        return requested
    raise ValueError(f"unsupported attestation mode: {requested}")


def assert_contract(name: str, code: str, action: Callable[[], Any]) -> dict[str, Any]:
    message = ERRORS[code]
    expected = {
        "code": code,
        "message": message,
        "rendered": f"{code}: {message}",
        "type": "AttemptSetupError",
    }
    observed: dict[str, Any] = {"code": None, "message": None, "rendered": None, "type": None}
    try:
        action()
    except BaseException as exc:
        observed = {
            "code": getattr(exc, "code", None),
            "message": getattr(exc, "message", None),
            "rendered": str(exc),
            "type": type(exc).__name__,
        }
    return {
        "expected": expected,
        "name": name,
        "observed": observed,
        "passed": observed == expected,
    }


def negative_oracles(
    payloads: dict[str, bytes | None], integrity: dict[str, Any]
) -> list[dict[str, Any]]:
    missing = dict(payloads)
    missing["case_manifest"] = None
    mismatch = dict(integrity)
    mismatch["matches_canonical_sha256"] = False
    invalid_node = dict(payloads)
    invalid_node["pytest_node_manifest"] = b"{}"
    invalid_product_negative = dict(payloads)
    invalid_product_negative["product_negative_contracts"] = b"{}"
    valid = dict(integrity)
    valid["matches_canonical_sha256"] = True
    return [
        assert_contract(
            "missing_fixture", "FROZEN_MF_T1_FIXTURE_MISSING", lambda: reference(missing, valid)
        ),
        assert_contract(
            "pinned_hash_mismatch",
            "FROZEN_MF_T1_FIXTURE_SHA256_MISMATCH",
            lambda: reference(payloads, mismatch),
        ),
        assert_contract(
            "invalid_pytest_node_manifest",
            "FROZEN_MF_T1_PYTEST_NODE_MANIFEST_INVALID",
            lambda: reference(invalid_node, valid),
        ),
        assert_contract(
            "invalid_product_negative_contracts",
            "FROZEN_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_INVALID",
            lambda: reference(invalid_product_negative, valid),
        ),
        assert_contract(
            "wrong_interpreter",
            "BASE_CONDA_INTERPRETER_REQUIRED",
            lambda: require_base({"matches_base_conda": False}),
        ),
        assert_contract(
            "ignored_controlled_artifact",
            "FROZEN_MF_T1_FIXTURE_PATH_IGNORED",
            lambda: require_nonignored({"paths_not_ignored": False}),
        ),
        assert_contract(
            "not_clean_commit",
            "CLEAN_COMMIT_ARTIFACTS_REQUIRED",
            lambda: require_clean_commit({"clean_commit_ready": False}),
        ),
    ]


def git_all_tracked(guard: ParentGuard, paths: list[str]) -> bool:
    """Return whether every existing binding path is tracked by the index."""

    return (
        guard.run(
            "git-ls-files",
            ["git", "ls-files", "--error-unmatch", "--", *paths],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def git_lines(
    guard: ParentGuard,
    label: str,
    command: list[str],
    *,
    input_text: str | None = None,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> list[str]:
    """Run one declared local Git read and fail closed on an unexpected result."""

    result = guard.run(
        label,
        command,
        cwd=ROOT,
        check=False,
        text=True,
        input=input_text,
        capture_output=True,
    )
    if result.returncode not in accepted_returncodes:
        raise RuntimeError(f"ITER27_MF_T1_GIT_TRACKING_FAILED:{label}:{result.returncode}")
    return [line for line in result.stdout.splitlines() if line]


def git_head_missing_paths(guard: ParentGuard, paths: list[str]) -> list[str]:
    """Use one batch read to prove every current binding path exists in HEAD."""

    lines = git_lines(
        guard,
        "git-cat-file",
        ["git", "cat-file", "--batch-check"],
        input_text="".join(f"HEAD:{path}\n" for path in paths),
    )
    missing = [
        path
        for index, path in enumerate(paths)
        if index >= len(lines) or lines[index].endswith(" missing")
    ]
    return missing


def git_ignored_paths(guard: ParentGuard, paths: list[str]) -> list[str]:
    return git_lines(
        guard,
        "git-check-ignore",
        ["git", "check-ignore", "--stdin"],
        input_text="".join(f"{path}\n" for path in paths),
        accepted_returncodes=(0, 1),
    )


def git_untracked_paths(guard: ParentGuard, scopes: list[str]) -> list[str]:
    return git_lines(
        guard,
        "git-untracked",
        ["git", "ls-files", "--others", "--exclude-standard", "--", *scopes],
    )


def git_dirty_paths(guard: ParentGuard, label: str, command: list[str]) -> list[str]:
    return git_lines(guard, label, command)


def clean_commit_eligible(record: dict[str, Any]) -> bool:
    """Require tracked, HEAD-bound, clean source bytes and no relevant extras."""

    return (
        record.get("head_contains_all") is True
        and record.get("index_matches_head") is True
        and record.get("index_tracked") is True
        and record.get("paths_not_ignored") is True
        and record.get("worktree_matches_index") is True
        and not record.get("index_dirty_paths")
        and not record.get("untracked_paths")
        and not record.get("worktree_dirty_paths")
    )


def tracking_record(guard: ParentGuard, paths: list[str], scopes: list[str]) -> dict[str, Any]:
    """Audit the paths that can bind an acceptance outcome to source bytes."""

    head_missing_paths = git_head_missing_paths(guard, paths)
    ignored_paths = git_ignored_paths(guard, paths)
    untracked_paths = git_untracked_paths(guard, scopes)
    index_dirty_paths = git_dirty_paths(
        guard, "git-diff-cached", ["git", "diff", "--cached", "--name-only", "--", *scopes]
    )
    worktree_dirty_paths = git_dirty_paths(
        guard, "git-diff-worktree", ["git", "diff", "--name-only", "--", *scopes]
    )
    record = {
        "head_contains_all": not head_missing_paths,
        "head_missing_paths": head_missing_paths,
        "index_dirty_paths": index_dirty_paths,
        "index_matches_head": not index_dirty_paths,
        "index_tracked": git_all_tracked(guard, paths),
        "paths": paths,
        "paths_not_ignored": not ignored_paths,
        "scopes": scopes,
        "untracked_paths": untracked_paths,
        "worktree_dirty_paths": worktree_dirty_paths,
        "worktree_matches_index": not worktree_dirty_paths,
    }
    record["clean_commit_ready"] = clean_commit_eligible(record)
    record["state"] = (
        "HEAD_INDEX_WORKTREE_CLEAN"
        if record["clean_commit_ready"]
        else "UNTRACKED_SOURCE_BINDING"
        if untracked_paths or not record["index_tracked"]
        else "DIRTY_SOURCE_BINDING"
        if index_dirty_paths or worktree_dirty_paths
        else "IGNORED_SOURCE_BINDING"
        if ignored_paths
        else "SOURCE_BINDING_NOT_IN_HEAD"
    )
    return record


def artifact_tracking(guard: ParentGuard) -> dict[str, Any]:
    """Track every runtime source binding, plus the frozen fixture subset."""

    source_paths = [rel(path) for path in source_binding_paths()]
    source_scopes = list(source_binding_scopes())
    source_record = tracking_record(guard, source_paths, source_scopes)
    frozen_paths = [str(path) for path in FROZEN_MATERIAL_ARTIFACTS]
    frozen_record = tracking_record(guard, frozen_paths, frozen_paths)
    clean = source_record["clean_commit_ready"]
    return {
        "clean_commit_ready": clean,
        "clean_ref_reproducibility": "READY" if clean else "PENDING_OWNER_ALLOWLIST_COMMIT",
        "frozen_material_tracking": frozen_record,
        "git_head_contains_all": source_record["head_contains_all"],
        "git_index_matches_head": source_record["index_matches_head"],
        "git_index_matches_worktree": source_record["worktree_matches_index"],
        "git_index_tracked": source_record["index_tracked"],
        "path_checks": source_record,
        "paths": source_paths,
        "paths_not_ignored": source_record["paths_not_ignored"],
        "relevant_index_dirty_paths": source_record["index_dirty_paths"],
        "relevant_untracked_paths": source_record["untracked_paths"],
        "relevant_worktree_dirty_paths": source_record["worktree_dirty_paths"],
        "source_binding_path_count": len(source_paths),
        "source_binding_scopes": source_scopes,
        "state": source_record["state"],
    }


def child_runner(path: Path) -> None:
    path.write_text(
        r'''#!/usr/bin/env python
"""Guarded child pytest process for the Iter27 MF-T1 frozen oracle."""
from __future__ import annotations
import json, os, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
HARNESS = Path(sys.argv[2]).resolve()
JUNIT = Path(sys.argv[3]).resolve()
AUDIT = Path(sys.argv[4]).resolve()
BASE = Path("/Users/yunjinqi/opt/anaconda3/bin/python").resolve()
ARGS = ("-q", "-p", "no:cacheprovider", "-p", "no:rerunfailures")
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"
network_attempts=[]; dotenv_attempts=[]; native_forbidden_calls=[]; undeclared_subprocesses=[]
allowed_local_probes=[]; pytest_call_reports=[]; pytest_skipped_reports=[]; pytest_xfail_reports=[]; pytest_xpass_reports=[]
pytest_args=[]; audit_hook_installed_before_pytest=False

def dump(value):
    AUDIT.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n")
def audit(event,args):
    if event=="open" and args and Path(str(args[0])).name==".env":
        dotenv_attempts.append({"event":event,"path":str(args[0])}); raise RuntimeError("ITER27_MF_T1_DOTENV_FORBIDDEN")
    if event in {"socket.connect","socket.getaddrinfo","socket.sendto","socket.bind"}:
        network_attempts.append({"event":event,"arguments":repr(args)}); raise RuntimeError("ITER27_MF_T1_NETWORK_FORBIDDEN")
def profile(frame,event,arg):
    if event!="c_call": return
    module=getattr(arg,"__module__","") or ""; name=getattr(arg,"__name__","")
    if "_ctp" in module and name in {"Init","RegisterFront","ReqAuthenticate","ReqUserLogin","ReqOrderInsert","ReqOrderAction","ReqSettlementInfoConfirm","CreateFtdcTraderApi","CreateFtdcMdApi"}:
        native_forbidden_calls.append({"module":module,"name":name}); raise RuntimeError("ITER27_MF_T1_NATIVE_FORBIDDEN")
original_popen=subprocess.Popen
def popen(command,*args,**kwargs):
    if command=="lscpu" and not kwargs.get("shell",False):
        allowed_local_probes.append("lscpu"); return original_popen(command,*args,**kwargs)
    undeclared_subprocesses.append({"command":repr(command)}); raise RuntimeError("ITER27_MF_T1_UNDECLARED_CHILD_SUBPROCESS")
class Outcomes:
    def pytest_runtest_logreport(self,report):
        wasxfail=getattr(report,"wasxfail",None)
        row={"nodeid":report.nodeid,"outcome":report.outcome,"when":report.when,"wasxfail":wasxfail}
        if report.when=="call": pytest_call_reports.append(row)
        if report.outcome=="skipped": pytest_skipped_reports.append(row)
        if wasxfail:
            (pytest_xpass_reports if report.outcome=="passed" else pytest_xfail_reports).append(row)
code=99; error=None; cwd=Path.cwd()
try:
    # Install before pytest, source imports, and pytest configuration reads.
    sys.addaudithook(audit); sys.setprofile(profile); audit_hook_installed_before_pytest=True
    sys.dont_write_bytecode=True; os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"; os.environ["PYTHONDONTWRITEBYTECODE"]="1"; os.environ.pop("PYTEST_ADDOPTS",None)
    sys.path[:0]=[str(ROOT),str(EXAMPLE)]; os.chdir(ROOT); subprocess.Popen=popen
    import pytest
    pytest_args=[*ARGS,f"--junitxml={JUNIT}",str(HARNESS)]
    code=int(pytest.main(pytest_args,plugins=[Outcomes()]))
except BaseException as exc:
    error=repr(exc); traceback.print_exc()
finally:
    subprocess.Popen=original_popen; sys.setprofile(None); os.chdir(cwd)
    dump({"allowed_local_probes":allowed_local_probes,"audit_hook_installed_before_pytest":audit_hook_installed_before_pytest,"base_interpreter":str(Path(sys.executable).resolve()),"dotenv_attempts":dotenv_attempts,"error":error,"matches_base_conda":Path(sys.executable).resolve()==BASE,"native_forbidden_calls":native_forbidden_calls,"network_attempts":network_attempts,"pytest_args":pytest_args,"pytest_call_reports":pytest_call_reports,"pytest_skipped_reports":pytest_skipped_reports,"pytest_xfail_reports":pytest_xfail_reports,"pytest_xpass_reports":pytest_xpass_reports,"undeclared_subprocesses":undeclared_subprocesses})
raise SystemExit(code)
''',
        encoding="utf-8",
    )


def junit_summary(path: Path) -> dict[str, Any]:
    empty = {
        "error_count": None,
        "failure_count": None,
        "nodes": [],
        "skipped_count": None,
        "testcase_count": None,
    }
    if not path.is_file():
        return empty
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError:
        return empty
    cases = root.findall(".//testcase")
    return {
        "error_count": len(root.findall(".//error")),
        "failure_count": len(root.findall(".//failure")),
        "nodes": [
            {"classname": case.attrib.get("classname"), "name": case.attrib.get("name")}
            for case in cases
        ],
        "skipped_count": len(root.findall(".//skipped")),
        "testcase_count": len(cases),
    }


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def valid_parent(receipt: Any) -> bool:
    return (
        isinstance(receipt, dict)
        and receipt.get("error") is None
        and receipt.get("installed_before_setup") is True
        and receipt.get("required_coverage_labels") == sorted(ParentGuard.REQUIRED)
        and receipt.get("coverage_complete") is True
        and isinstance(receipt.get("declared_subprocesses"), list)
        and bool(receipt["declared_subprocesses"])
        and isinstance(receipt.get("undeclared_subprocesses"), list)
        and not receipt["undeclared_subprocesses"]
        and all(
            isinstance(receipt.get(key), list)
            for key in (
                "network_attempts",
                "dotenv_attempts",
                "native_forbidden_calls",
                "guard_errors",
            )
        )
    )


def valid_child(receipt: Any, harness: Path, junit: Path) -> bool:
    args = [*PYTEST_ARGS, f"--junitxml={junit}", str(harness)]
    return (
        isinstance(receipt, dict)
        and receipt.get("error") is None
        and receipt.get("audit_hook_installed_before_pytest") is True
        and receipt.get("matches_base_conda") is True
        and receipt.get("pytest_args") == args
        and all(
            isinstance(receipt.get(key), list)
            for key in (
                "allowed_local_probes",
                "dotenv_attempts",
                "native_forbidden_calls",
                "network_attempts",
                "pytest_call_reports",
                "pytest_skipped_reports",
                "pytest_xfail_reports",
                "pytest_xpass_reports",
                "undeclared_subprocesses",
            )
        )
        and all(item == "lscpu" for item in receipt["allowed_local_probes"])
        and not receipt["undeclared_subprocesses"]
    )


def valid_outcomes(receipt: dict[str, Any]) -> bool:
    reports = receipt.get("pytest_call_reports", [])
    return (
        isinstance(reports, list)
        and len(reports) == SCENARIO_COUNT
        and all(
            isinstance(row, dict)
            and row.get("outcome") == "passed"
            and row.get("wasxfail") in (None, False)
            for row in reports
        )
        and not receipt.get("pytest_skipped_reports")
        and not receipt.get("pytest_xfail_reports")
        and not receipt.get("pytest_xpass_reports")
    )


def valid_product_negative_observations(document: dict[str, Any], observations: Any) -> bool:
    """Require every exact product error/rejection contract, with no extras."""

    contracts = document.get("contracts")
    if not isinstance(contracts, dict) or not isinstance(observations, list):
        return False
    expected_counts = {
        identifier: item["expected_use_count"] for identifier, item in contracts.items()
    }
    if len(observations) != sum(expected_counts.values()):
        return False
    counts: Counter[str] = Counter()
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {
            "expected",
            "id",
            "observed",
            "pass_",
        }:
            return False
        identifier = observation["id"]
        contract = contracts.get(identifier)
        if (
            not isinstance(identifier, str)
            or not isinstance(contract, dict)
            or observation["expected"] != contract.get("expected")
            or observation["observed"] != contract.get("expected")
            or observation["pass_"] is not True
        ):
            return False
        counts[identifier] += 1
    return dict(counts) == expected_counts


def sanitized_environment() -> tuple[dict[str, str], list[str]]:
    fragments = (
        "API_KEY",
        "API_SECRET",
        "BROKER_PASSWORD",
        "CTP",
        "PASSWORD",
        "PASSPHRASE",
        "SECRET",
        "SIMNOW",
        "TOKEN",
    )
    removed = [
        key
        for key in os.environ
        if key == "PYTEST_ADDOPTS" or any(word in key.upper() for word in fragments)
    ]
    env = {key: value for key, value in os.environ.items() if key not in removed}
    env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return env, sorted(removed)


def expected_nodes(harness: Path, names: list[str]) -> list[dict[str, str]]:
    classname = ".".join(harness.relative_to(ROOT).with_suffix("").parts)
    return [{"classname": classname, "name": name} for name in names]


def seal(output: Path, paths: list[Path]) -> None:
    files = {
        str(path.relative_to(output)): sha256(path)
        for path in paths
        if path.is_file() and path.name != "seal.json"
    }
    dump_json(
        output / "seal.json",
        {
            "excludes": ["seal.json", str(RUNNER_RELATIVE)],
            "files": files,
            "schema_version": "backtrader.iter27.acceptance-seal.v3",
            "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def main() -> int:
    guard = ParentGuard()
    guard.install()  # Before arguments, paths, reads, and every subprocess.
    try:
        configure_paths_after_guard()
        args = parse_args()
        output = output_path(args.output_dir)
        manifest_path = output / "manifest.json"
        consolidated_path = output / "consolidated.json"
        stdout_path = output / "stdout.log"
        stderr_path = output / "stderr.log"
        junit_path = output / "junit.xml"
        child_audit_path = output / "child-audit.json"
        parent_audit_path = output / "parent-audit.json"
        harness_dir = output / "harness"
        harness = harness_dir / "mf_t1_oracle.py"
        case_copy = harness_dir / "case_manifest.json"
        node_copy = harness_dir / "pytest_node_manifest.json"
        product_negative_copy = harness_dir / "product_negative_contracts.json"
        scenarios = harness_dir / "mf-cases.json"
        traces = harness_dir / "mf-engine-traces.json"
        product_negative_observations_path = harness_dir / "mf-product-negative-contracts.json"
        child = output / "child_runner.py"

        error: str | None = None
        returncode = 99
        before: dict[str, str] = {}
        after: dict[str, str] = {}
        ids: list[str] = []
        root_contracts: dict[str, list[str]] = {}
        product_negative_contract_document: dict[str, Any] = {}
        node_names: list[str] = []
        nodes: list[dict[str, str]] = []
        negative: list[dict[str, Any]] = []
        tracking: dict[str, Any] = {
            "clean_commit_ready": False,
            "paths_not_ignored": False,
            "state": "UNAVAILABLE",
        }
        integrity: dict[str, Any] = {
            "actual": {},
            "expected": {},
            "matches_canonical_sha256": False,
        }
        interpreter = {
            "actual": str(Path(sys.executable).resolve()),
            "expected_base_conda": str(BASE_PYTHON),
            "matches_base_conda": Path(sys.executable).resolve() == BASE_PYTHON,
        }
        effective = "worktree"
        manifest: dict[str, Any] = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(ROOT),
            "schema_version": "backtrader.iter27.mf-t1-independent-attempt.v7",
            "scope": "current-source local MF-T1 timing subset only; no CTP/SimNow/native-session/fill/PnL/profitability claim",
            "setup_error_contracts": ERRORS,
            "source_binding": {
                "controlled_artifacts": [str(path) for path in CONTROLLED_ARTIFACTS],
                "pytest_arguments": list(PYTEST_ARGS),
                "pytest_config_inputs": [str(path) for path in PYTEST_CONFIGS],
                "source_roots": [str(path) for path in SOURCE_ROOTS],
            },
        }
        try:
            tracking = artifact_tracking(guard)
            payloads, integrity = frozen_material(tracking)
            effective = effective_attestation_mode(args.attestation_mode, tracking)
            require_base(interpreter)
            require_nonignored(tracking)
            if effective == "clean-commit":
                require_clean_commit(tracking)
            before = source_hashes()
            ids, root_contracts, node_names, product_negative_contract_document = reference(
                payloads, integrity
            )
            negative = negative_oracles(payloads, integrity)
            if not all(item["passed"] is True for item in negative):
                raise RuntimeError("ITER27_MF_T1_NEGATIVE_ORACLE_CONTRACT_MISMATCH")

            harness_dir.mkdir()
            assert payloads["oracle_template"] is not None
            assert payloads["case_manifest"] is not None
            assert payloads["pytest_node_manifest"] is not None
            assert payloads["product_negative_contracts"] is not None
            harness.write_bytes(payloads["oracle_template"])
            case_copy.write_bytes(payloads["case_manifest"])
            node_copy.write_bytes(payloads["pytest_node_manifest"])
            product_negative_copy.write_bytes(payloads["product_negative_contracts"])
            integrity["copied"] = {
                "oracle_template_sha256": sha256(harness),
                "case_manifest_sha256": sha256(case_copy),
                "pytest_node_manifest_sha256": sha256(node_copy),
                "product_negative_contracts_sha256": sha256(product_negative_copy),
            }
            if integrity["copied"]["oracle_template_sha256"] != ORACLE_SHA256:
                raise AttemptSetupError("COPIED_MF_ORACLE_TEMPLATE_SHA256_MISMATCH")
            if integrity["copied"]["case_manifest_sha256"] != CASES_SHA256:
                raise AttemptSetupError("COPIED_MF_T1_CASE_MANIFEST_SHA256_MISMATCH")
            if integrity["copied"]["pytest_node_manifest_sha256"] != NODES_SHA256:
                raise AttemptSetupError("COPIED_MF_T1_PYTEST_NODE_MANIFEST_SHA256_MISMATCH")
            if integrity["copied"]["product_negative_contracts_sha256"] != PRODUCT_NEGATIVE_SHA256:
                raise AttemptSetupError("COPIED_MF_T1_PRODUCT_NEGATIVE_CONTRACTS_SHA256_MISMATCH")

            os.symlink(ROOT, output / "source", target_is_directory=True)
            child_runner(child)
            nodes = expected_nodes(harness, node_names)
            env, stripped = sanitized_environment()
            manifest.update(
                {
                    "attestation_mode": {
                        "effective": effective,
                        "requested": args.attestation_mode,
                        "strict_clean_commit_ready": tracking["clean_commit_ready"],
                    },
                    "expected_junit": {
                        "error_count": 0,
                        "failure_count": 0,
                        "nodes": nodes,
                        "skipped_count": 0,
                        "testcase_count": SCENARIO_COUNT,
                        "xfail_count": 0,
                        "xpass_count": 0,
                    },
                    "expected_root_contracts": root_contracts,
                    "expected_root_ids": list(ROOT_IDS),
                    "expected_scenario_count": SCENARIO_COUNT,
                    "expected_scenario_ids": ids,
                    "fixture_tracking": tracking,
                    "frozen_fixture": integrity,
                    "interpreter": interpreter,
                    "negative_oracles": negative,
                    "product_negative_contracts": product_negative_contract_document,
                    "parent_guard_policy": {
                        "installed_before_setup": True,
                        "required_coverage_labels": sorted(ParentGuard.REQUIRED),
                    },
                    "source_before": before,
                    "stripped_environment_key_names": stripped,
                    "test_execution": "fresh copied frozen oracle under output/harness against current source",
                }
            )
            dump_json(manifest_path, manifest)
            result = guard.run(
                "child-oracle",
                [
                    str(BASE_PYTHON),
                    str(child),
                    str(ROOT),
                    str(harness),
                    str(junit_path),
                    str(child_audit_path),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            returncode = result.returncode
            stdout_path.write_text(result.stdout, encoding="utf-8")
            stderr_path.write_text(result.stderr, encoding="utf-8")
        except BaseException as exc:
            error = repr(exc)
            stderr_path.write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            try:
                after = source_hashes()
            except BaseException as exc:
                after = {"source_hash_error": repr(exc)}

        observed_cases = read_json(scenarios, [])
        product_negative_observations = read_json(product_negative_observations_path, [])
        child_audit = read_json(child_audit_path, {})
        junit = junit_summary(junit_path)
        observed_ids = (
            [row.get("id") for row in observed_cases if isinstance(row, dict)]
            if isinstance(observed_cases, list)
            else []
        )
        case_map = (
            {
                row["id"]: row
                for row in observed_cases
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            if isinstance(observed_cases, list)
            else {}
        )
        root_observations = [
            {
                "contracts": case_map.get(root_id, {}).get("contracts"),
                "expected_contracts": root_contracts.get(root_id),
                "id": root_id,
                "passed": case_map.get(root_id, {}).get("pass_"),
            }
            for root_id in ROOT_IDS
        ]

        # This snapshot occurs after every source/result read and after all seven
        # declared subprocess labels have been exercised; it is non-vacuous.
        parent_audit = guard.receipt()
        dump_json(parent_audit_path, parent_audit)
        parent_ok = valid_parent(parent_audit)
        child_ok = valid_child(child_audit, harness, junit_path)
        outcomes_ok = valid_outcomes(child_audit) if child_ok else False
        mapping_ok = observed_ids == ids
        cases_ok = (
            isinstance(observed_cases, list)
            and len(observed_cases) == SCENARIO_COUNT
            and all(isinstance(row, dict) and row.get("pass_") is True for row in observed_cases)
        )
        roots_ok = all(
            row["passed"] is True and row["contracts"] == row["expected_contracts"]
            for row in root_observations
        )
        source_stable = bool(before) and before == after
        nodes_ok = junit["nodes"] == nodes
        negative_ok = bool(negative) and all(item.get("passed") is True for item in negative)
        product_negative_ok = valid_product_negative_observations(
            product_negative_contract_document, product_negative_observations
        )
        no_forbidden = (
            parent_ok
            and child_ok
            and not parent_audit.get("network_attempts")
            and not parent_audit.get("dotenv_attempts")
            and not parent_audit.get("native_forbidden_calls")
            and not child_audit.get("network_attempts")
            and not child_audit.get("dotenv_attempts")
            and not child_audit.get("native_forbidden_calls")
        )
        worktree_pass = (
            error is None
            and returncode == 0
            and interpreter["matches_base_conda"] is True
            and tracking.get("paths_not_ignored") is True
            and integrity.get("matches_canonical_sha256") is True
            and junit["testcase_count"] == SCENARIO_COUNT
            and junit["failure_count"] == 0
            and junit["error_count"] == 0
            and junit["skipped_count"] == 0
            and nodes_ok
            and outcomes_ok
            and mapping_ok
            and cases_ok
            and roots_ok
            and source_stable
            and negative_ok
            and product_negative_ok
            and no_forbidden
        )
        accepted = (
            worktree_pass
            and effective == "clean-commit"
            and tracking.get("clean_commit_ready") is True
        )
        exit_contract = {
            "accepted_receipt_exit_code": receipt_exit_code(accepted=True),
            "passed": receipt_exit_code(accepted=True) == 0
            and receipt_exit_code(accepted=False) != 0,
            "unaccepted_receipt_exit_code": receipt_exit_code(accepted=False),
        }
        process_exit_code = receipt_exit_code(accepted=accepted)
        interface_incompatibility = (
            not worktree_pass
            and returncode != 0
            and len(observed_ids) != SCENARIO_COUNT
            and no_forbidden
            and error is None
        )
        status = (
            "LOCAL_MIDFREQ_TIMING_SUBSET_PASS_CLEAN_COMMIT"
            if accepted
            else "LOCAL_MIDFREQ_TIMING_SUBSET_WORKTREE_EVIDENCE_PASS_NOT_CLEAN_COMMIT"
            if worktree_pass
            else "LOCAL_MIDFREQ_TIMING_SUBSET_FAIL"
        )

        manifest.update(
            {
                "parent_guard": parent_audit,
                "receipt_exit_contract": exit_contract,
                "source_after": after,
                "source_stable": source_stable,
            }
        )
        dump_json(manifest_path, manifest)
        consolidated = {
            "accepted": accepted,
            "all_cases_pass": cases_ok,
            "attestation_mode": {
                "effective": effective,
                "requested": args.attestation_mode,
                "strict_clean_commit_ready": tracking.get("clean_commit_ready"),
            },
            "child_audit": child_audit,
            "child_audit_valid": child_ok,
            "child_outcomes_valid": outcomes_ok,
            "error": error,
            "expected_junit_nodes": nodes,
            "expected_root_count": len(ROOT_IDS),
            "expected_scenario_count": SCENARIO_COUNT,
            "fixture_tracking": tracking,
            "frozen_fixture": integrity,
            "interface_incompatibility": interface_incompatibility,
            "interpreter": interpreter,
            "junit": junit,
            "junit_node_identities_exact": nodes_ok,
            "negative_oracles": negative,
            "negative_oracles_pass": negative_ok,
            "product_negative_contracts": product_negative_contract_document,
            "product_negative_observations": product_negative_observations,
            "product_negative_observations_pass": product_negative_ok,
            "no_forbidden_activity": no_forbidden,
            "observed_scenario_count": len(observed_ids),
            "parent_audit": parent_audit,
            "parent_audit_valid": parent_ok,
            "process_exit_code": process_exit_code,
            "receipt_exit_contract": exit_contract,
            "returncode": returncode,
            "root_oracle_commitments": root_observations,
            "root_oracle_commitments_pass": roots_ok,
            "scenario_mapping_exact": mapping_ok,
            "source_after": after,
            "source_stable": source_stable,
            "status": status,
            "strict_clean_commit_ready": tracking.get("clean_commit_ready"),
            "worktree_evidence_pass": worktree_pass,
        }
        dump_json(consolidated_path, consolidated)
        seal(
            output,
            [
                manifest_path,
                junit_path,
                stdout_path,
                stderr_path,
                child_audit_path,
                parent_audit_path,
                scenarios,
                traces,
                product_negative_observations_path,
                harness,
                case_copy,
                node_copy,
                product_negative_copy,
                child,
                consolidated_path,
            ],
        )
        return process_exit_code
    finally:
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main())
