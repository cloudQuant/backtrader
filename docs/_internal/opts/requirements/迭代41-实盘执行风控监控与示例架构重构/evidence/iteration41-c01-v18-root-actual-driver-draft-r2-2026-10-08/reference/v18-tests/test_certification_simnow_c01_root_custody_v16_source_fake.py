"""Synthetic source-fake checks for the C01 Root custody producer.

This exercises only fake file handles, synthetic source bytes, fake account
fields, and a fake Root bridge. It does not read private configuration or
invoke Windows, provider, SDK, or native APIs.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from importlib.machinery import ModuleSpec
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
PRODUCER_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_custody_v16.py"
PRODUCER_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
BRIDGE_NAME = "backtrader_runtime.certification_simnow_c01_root_v16"
ENTRY_NAME = "backtrader_runtime.certification_simnow_c01_root_entry_v18"
SNAPSHOT_BASELINE = "snapshots/baseline.json"
SNAPSHOT_FINAL = "snapshots/final.json"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _key(path: Path) -> str:
    import os

    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


class _FakeHandle:
    def __init__(self, path: Path, directory: bool, identity: tuple[int, int]):
        self.path = path
        self.directory = directory
        self.identity = identity
        self.position = 0


class _FakeApi:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.identities: dict[str, tuple[int, int]] = {}
        self._next = 1
        self.acl_tampered = False
        self.seek_mode = None

    def _identity(self, path: Path) -> tuple[int, int]:
        key = _key(path)
        if key not in self.identities:
            self.identities[key] = (7, self._next)
            self._next += 1
        return self.identities[key]

    @contextlib.contextmanager
    def opened(self, path, *, directory, access=None):
        path = Path(path)
        if not directory and _key(path) not in self.files:
            raise OSError("fake_file_unavailable")
        handle = _FakeHandle(path, directory, self._identity(path))
        yield handle

    def info(self, handle, *, directory):
        if type(handle) is not _FakeHandle or handle.directory is not directory:
            raise OSError("fake_identity_invalid")
        return handle.identity

    def verify_acl(self, handle, sid, *, directory=False, inherited=False):
        if self.acl_tampered or type(handle) is not _FakeHandle or sid != "S-1-5-fake":
            raise OSError("fake_acl_invalid")

    def current_sid(self):
        return "S-1-5-fake"

    def rewind_handle(self, handle):
        if self.seek_mode == "fail":
            return False
        if self.seek_mode == "eof":
            handle.position = len(self.files[_key(handle.path)])
            return False
        handle.position = 0
        return True


@contextlib.contextmanager
def _loaded_producer():
    saved = sys.modules.get(PRODUCER_NAME)
    spec = importlib.util.spec_from_file_location(PRODUCER_NAME, PRODUCER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PRODUCER_NAME] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        if saved is None:
            sys.modules.pop(PRODUCER_NAME, None)
        else:
            sys.modules[PRODUCER_NAME] = saved


@contextlib.contextmanager
def _synthetic_candidate(tmp_path: Path, custody):
    saved_names: dict[str, object] = {}
    missing = object()
    names = {
        PRODUCER_NAME,
        BRIDGE_NAME,
        ENTRY_NAME,
        "backtrader_runtime",
        "scripts",
        "backtrader_runtime.certification_simnow_c01_front_transport_v12",
        "backtrader_runtime._c01_front_transport_v12_v18_source",
        "backtrader_runtime._c01_native_td_read_v7_owner",
        "common.c01_root_admission_bridge",
        "common.certification",
        "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
        "backtrader_runtime.certification_simnow_c01_v3_protocol",
        "backtrader_runtime.certification_simnow_c01_v3_contract",
        "backtrader_runtime.certification_simnow_c01_v4_supervisor",
        "backtrader_runtime.certification_roundtrip_private",
        "backtrader_runtime.certification_binance_roundtrip_r3_cli",
        "backtrader_runtime.ctp_front_pair_probe",
        "scripts.ctp_000_render_config",
        "scripts.ctp_000_paired_front_selector",
        "scripts.ctp_000_front_handoff",
        "scripts.ctp_i13_i15_outer_watchdog",
        "scripts.ctp_i13_i15_windows_job_backend",
    }
    saved_names.update({name: sys.modules.get(name, missing) for name in names})
    try:
        fake_root = tmp_path / "source-root"
        (fake_root / "backtrader_runtime").mkdir(parents=True)
        (fake_root / "examples" / "000_live_certification" / "simnow_penetration" / "common").mkdir(parents=True)
        (fake_root / "examples" / "000_live_certification" / "simnow_penetration" / "case_contracts").mkdir(parents=True)
        (fake_root / "examples" / "000_live_certification" / "simnow_penetration" / "cases" / "C01").mkdir(parents=True)
        (fake_root / "scripts").mkdir(parents=True)

        files: dict[str, bytes] = {}

        def source(relative: str, raw: bytes | None = None) -> tuple[str, str]:
            if raw is None:
                raw = ("synthetic source row: " + relative).encode("ascii")
            files[_key(fake_root / relative)] = raw
            return relative, _sha(raw)

        owner_rows = {
            "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": None,
            "backtrader_runtime/certification_simnow_c01_native_v4.py": None,
            "backtrader_runtime/certification_simnow_c01_dependencies_v1.json": None,
            "backtrader_runtime/certification_simnow_c01_v3_protocol.py": None,
            "backtrader_runtime/certification_simnow_c01_v3_contract.py": None,
            "backtrader_runtime/certification_simnow_c01_v4_supervisor.py": None,
            "backtrader_runtime/certification_roundtrip_private.py": None,
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": None,
            "backtrader_runtime/ctp_front_pair_probe.py": None,
            "scripts/ctp_000_render_config.py": None,
            "scripts/ctp_000_paired_front_selector.py": None,
            "scripts/ctp_000_front_handoff.py": None,
            "scripts/ctp_i13_i15_outer_watchdog.py": None,
            "scripts/ctp_i13_i15_windows_job_backend.py": None,
        }
        for relative in tuple(owner_rows):
            _, owner_rows[relative] = source(relative)

        source_paths = {
            "front": "backtrader_runtime/certification_simnow_c01_front_transport_v12.py",
            "issuer": "backtrader_runtime/certification_simnow_c01_native_td_read_v18.py",
            "owner": "backtrader_runtime/certification_simnow_c01_v7_owner.py",
            "projection": "examples/000_live_certification/simnow_penetration/common/c01_root_admission_bridge.py",
            "certification": "examples/000_live_certification/simnow_penetration/common/certification.py",
            "root_bridge": "backtrader_runtime/certification_simnow_c01_root_v16.py",
            "root_entry": "backtrader_runtime/certification_simnow_c01_root_entry_v18.py",
        }
        module_bytes: dict[str, bytes] = {}
        for key, relative in source_paths.items():
            module_bytes[key] = PRODUCER_PATH.read_bytes() if key == "custody" else (
                "synthetic module source: " + relative
            ).encode("ascii")
            if key != "root_entry":
                source(relative, module_bytes[key])
        custody_relative = "backtrader_runtime/certification_simnow_c01_root_custody_v16.py"
        module_bytes["custody"] = PRODUCER_PATH.read_bytes()
        source(custody_relative, module_bytes["custody"])

        contract_relative = "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml"
        strategy_relative = "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py"
        template_relative = "examples/000_live_certification/simnow_penetration/config.private.yaml.template"
        schema_relative = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.admission.schema.json"
        manifest_relative = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.sources.json"
        runner_relative = "examples/000_live_certification/simnow_penetration/cases/C01/run_v18.py"
        known_rows = {}
        for relative in (contract_relative, strategy_relative, template_relative, schema_relative, runner_relative):
            _, known_rows[relative] = source(relative)
        owner_relative = source_paths["owner"]
        owner_pin = _sha(module_bytes["owner"])
        manifest_rows = dict(owner_rows)
        manifest_rows.update(
            {
                owner_relative: owner_pin,
                contract_relative: known_rows[contract_relative],
                strategy_relative: known_rows[strategy_relative],
                template_relative: known_rows[template_relative],
                schema_relative: known_rows[schema_relative],
            }
        )
        manifest = json.dumps(
            {
                "schema": "simnow.c01.native_td_read_v18.source_manifest.v1",
                "profile_id": "C01_NATIVE_TD_READ_V18",
                "source_files": manifest_rows,
                "admission_bound_files": [source_paths["issuer"], runner_relative],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        _, manifest_pin = source(manifest_relative, manifest)

        # The root entry is source loaded by the caller; the fixture supplies
        # the corresponding synthetic module bytes and its exact marker.
        entry_raw = b"synthetic fixed Root entry source"
        source(source_paths["root_entry"], entry_raw)
        root_entry = ModuleType(ENTRY_NAME)
        root_entry.__file__ = str(fake_root / source_paths["root_entry"])
        root_entry.__c01_source_sha256__ = _sha(entry_raw)
        exec("def _entry(): return None\n_C01_ROOT_ENTRY_CALLABLE = _entry", root_entry.__dict__)
        sys.modules[ENTRY_NAME] = root_entry

        exact_public = dict(owner_rows)
        for key, relative in source_paths.items():
            if key != "root_entry":
                exact_public[relative] = _sha(module_bytes[key])
        exact_public.update(
            {
                custody_relative: _sha(module_bytes["custody"]),
                **known_rows,
                manifest_relative: manifest_pin,
            }
        )
        # `source_paths` has no custody entry; its owner/source bytes are all
        # synthetic except for the producer bytes pinned by this test.
        exact_public[custody_relative] = _sha(module_bytes["custody"])
        root_entry._EXACT_PUBLIC_SOURCE_PINS = dict(exact_public)

        software_root = tmp_path / "approved-runtime"
        exe_path = software_root / "python.exe"
        dll_path = software_root / "python311.dll"
        exe_raw, dll_raw = b"synthetic approved executable", b"synthetic approved DLL"
        files[_key(exe_path)] = exe_raw
        files[_key(dll_path)] = dll_raw
        software_pins = {str(exe_path): _sha(exe_raw), str(dll_path): _sha(dll_raw)}
        root_entry._EXACT_SOFTWARE_PINS = dict(software_pins)

        api = _FakeApi(files)

        def package_module(name: str) -> ModuleType:
            module = ModuleType(name)
            module.__package__ = name
            module.__path__ = [str(fake_root.joinpath(*name.split(".")))]
            module.__loader__ = None
            module.__spec__ = ModuleSpec(name, loader=None, is_package=True)
            sys.modules[name] = module
            return module

        package_module("backtrader_runtime")
        package_module("scripts")

        def helper_module(name: str, relative: str) -> ModuleType:
            module = ModuleType(name)
            module.__file__ = str(fake_root / relative)
            parent_name, _, child_name = name.rpartition(".")
            module.__package__ = parent_name
            module.__loader__ = None
            module.__spec__ = ModuleSpec(name, loader=None)
            parent = sys.modules[parent_name]
            sys.modules[name] = module
            setattr(parent, child_name, module)
            return module

        private_module = helper_module(
            "backtrader_runtime.certification_roundtrip_private",
            "backtrader_runtime/certification_roundtrip_private.py",
        )
        private_module._api = lambda: api
        private_module.PrivateArtifactDirectory = type("PrivateArtifactDirectory", (), {})
        private_module.PrivateArtifactDirectory.verify = lambda self: None

        cli_module = helper_module(
            "backtrader_runtime.certification_binance_roundtrip_r3_cli",
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        )

        @contextlib.contextmanager
        def locked_file(path, _private, file_api, *, allow_hardlinks):
            with file_api.opened(path, directory=False) as handle:
                yield handle, file_api.info(handle, directory=False)

        cli_module._locked_readonly_file = locked_file
        cli_module._locked_file_identity = lambda file_api, handle, _private, *, allow_hardlinks: file_api.info(handle, directory=False)
        def read_bounded_handle(file_api, handle, limit):
            raw = file_api.files[_key(handle.path)]
            start = handle.position
            result = raw[start : start + limit + 1]
            handle.position += len(result)
            return result

        cli_module._read_bounded_handle = read_bounded_handle

        owner = ModuleType("backtrader_runtime._c01_native_td_read_v7_owner")
        owner.__file__ = str(fake_root / owner_relative)
        owner.__package__ = "backtrader_runtime"
        owner.__loader__ = None
        owner.__spec__ = ModuleSpec(owner.__name__, loader=None)
        owner.__c01_source_sha256__ = owner_pin
        owner._SOURCE_PINS = MappingProxyType(dict(owner_rows))
        owner._MODULE_PATHS = MappingProxyType({
            "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1": "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
            "backtrader_runtime.certification_simnow_c01_v3_protocol": "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
            "backtrader_runtime.certification_simnow_c01_v3_contract": "backtrader_runtime/certification_simnow_c01_v3_contract.py",
            "backtrader_runtime.certification_simnow_c01_v4_supervisor": "backtrader_runtime/certification_simnow_c01_v4_supervisor.py",
            "backtrader_runtime.certification_roundtrip_private": "backtrader_runtime/certification_roundtrip_private.py",
            "backtrader_runtime.certification_binance_roundtrip_r3_cli": "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
            "backtrader_runtime.ctp_front_pair_probe": "backtrader_runtime/ctp_front_pair_probe.py",
            "scripts.ctp_000_render_config": "scripts/ctp_000_render_config.py",
            "scripts.ctp_000_paired_front_selector": "scripts/ctp_000_paired_front_selector.py",
            "scripts.ctp_000_front_handoff": "scripts/ctp_000_front_handoff.py",
            "scripts.ctp_i13_i15_outer_watchdog": "scripts/ctp_i13_i15_outer_watchdog.py",
            "scripts.ctp_i13_i15_windows_job_backend": "scripts/ctp_i13_i15_windows_job_backend.py",
        })
        owner._Credentials = type("Credentials", (), {})
        owner._PrivateRun = type("PrivateRun", (), {})
        owner.Path = Path
        owner.SimpleNamespace = SimpleNamespace
        exec(
            compile(
                "def _now_utc(): return 'synthetic-time'\n"
                "def _directory_entries(path):\n"
                "    return (SimpleNamespace(name='baseline.json'), SimpleNamespace(name='final.json')) if Path(path).name == 'snapshots' else ()\n",
                owner.__file__,
                "exec",
            ),
            owner.__dict__,
        )
        sys.modules[owner.__name__] = owner

        interpreter = helper_module(
            "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
            "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
        )
        interpreter.CPYTHON_EXECUTABLE = str(exe_path)
        interpreter.CPYTHON_EXECUTABLE_SHA256 = _sha(exe_raw)
        interpreter.CPYTHON_DLL = str(dll_path)
        interpreter.CPYTHON_DLL_SHA256 = _sha(dll_raw)
        protocol = helper_module(
            "backtrader_runtime.certification_simnow_c01_v3_protocol",
            "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
        )
        contract = helper_module(
            "backtrader_runtime.certification_simnow_c01_v3_contract",
            "backtrader_runtime/certification_simnow_c01_v3_contract.py",
        )
        supervisor = helper_module(
            "backtrader_runtime.certification_simnow_c01_v4_supervisor",
            "backtrader_runtime/certification_simnow_c01_v4_supervisor.py",
        )
        helper_names = [
            ("backtrader_runtime.ctp_front_pair_probe", "backtrader_runtime/ctp_front_pair_probe.py"),
            ("scripts.ctp_000_render_config", "scripts/ctp_000_render_config.py"),
            ("scripts.ctp_000_paired_front_selector", "scripts/ctp_000_paired_front_selector.py"),
            ("scripts.ctp_000_front_handoff", "scripts/ctp_000_front_handoff.py"),
            ("scripts.ctp_i13_i15_outer_watchdog", "scripts/ctp_i13_i15_outer_watchdog.py"),
            ("scripts.ctp_i13_i15_windows_job_backend", "scripts/ctp_i13_i15_windows_job_backend.py"),
        ]
        other_helpers = [helper_module(name, relative) for name, relative in helper_names]
        credentials_type = owner._Credentials
        credentials = credentials_type()
        for name, value in {
            "broker_id": "fake-broker",
            "user_id": "fake-user",
            "password": "synthetic-password",
            "app_id": "fake-app",
            "auth_code": "fake-auth",
            "product_info": "fake-product",
            "md_front": "tcp://fake-md",
            "td_front": "tcp://fake-td",
        }.items():
            setattr(credentials, name, value)

        def account_digest(broker, user):
            return _sha((broker + "\0" + user).encode("utf-8"))

        def credential_digest(broker, user, password, app, auth, product):
            return _sha("\0".join((broker, user, password, app, auth, product)).encode("utf-8"))

        protocol.compute_account_scope_sha256 = account_digest
        protocol.compute_credential_binding_sha256 = credential_digest

        class FakePairBinding:
            def to_receipt_ref(self):
                return SimpleNamespace(to_dict=lambda: {"pair": "synthetic"})

        class FakeValidation:
            pass

        protocol.C01PairBinding = FakePairBinding
        protocol.C01CandidateValidation = FakeValidation
        pair_binding = FakePairBinding()
        validation = FakeValidation()
        account_hash = account_digest(credentials.broker_id, credentials.user_id)
        credential_hash = credential_digest(
            credentials.broker_id,
            credentials.user_id,
            credentials.password,
            credentials.app_id,
            credentials.auth_code,
            credentials.product_info,
        )
        worker_rows = [
            {"account_scope_sha256": account_hash, "credential_binding_sha256": credential_hash}
            for _ in range(8)
        ]
        worker_payload = {
            "account_scope_sha256": account_hash,
            "credential_binding_sha256": credential_hash,
            "pair_binding": {"pair": "synthetic"},
            "requests": worker_rows,
            "callbacks": worker_rows[:8],
        }
        class FakeWorkerReceipt:
            def to_dict(self):
                return dict(worker_payload)

        protocol.C01WorkerReceipt = FakeWorkerReceipt
        worker_receipt = FakeWorkerReceipt()

        class FakeProcess:
            def __init__(self):
                self.worker_receipt = worker_receipt

        supervisor.C01SupervisorResult = FakeProcess
        process = FakeProcess()

        issuer = ModuleType("backtrader_runtime._c01_front_transport_v12_v18_source")
        issuer.__file__ = str(fake_root / source_paths["issuer"])
        issuer.__c01_source_sha256__ = _sha(module_bytes["issuer"])
        issuer.PROFILE_ID = "C01_NATIVE_TD_READ_V18"
        issuer._OWNER_SHA256 = owner_pin
        issuer._SOURCE_MANIFEST_PATH = manifest_relative
        issuer._SOURCE_MANIFEST_SHA256 = manifest_pin
        issuer._ADMISSION_SCHEMA_PATH = schema_relative
        issuer._ADMISSION_SCHEMA_SHA256 = known_rows[schema_relative]
        issuer._CASE_CONTRACT_PATH = contract_relative
        issuer._CASE_CONTRACT_SHA256 = known_rows[contract_relative]
        issuer._CASE_STRATEGY_PATH = strategy_relative
        issuer._CASE_STRATEGY_SHA256 = known_rows[strategy_relative]
        issuer._ENVREF_TEMPLATE_PATH = template_relative
        issuer._ENVREF_TEMPLATE_SHA256 = known_rows[template_relative]
        issuer._INTERPRETER_BINDING_PATH = "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
        issuer._INTERPRETER_BINDING_SHA256 = owner_rows[issuer._INTERPRETER_BINDING_PATH]
        issuer._WORKER_SHA256 = owner_rows["backtrader_runtime/certification_simnow_c01_native_v4.py"]
        issuer._PROTOCOL_SHA256 = owner_rows["backtrader_runtime/certification_simnow_c01_v3_protocol.py"]
        issuer._CONTRACT_SHA256 = owner_rows["backtrader_runtime/certification_simnow_c01_v3_contract.py"]
        issuer._SUPERVISOR_SHA256 = owner_rows["backtrader_runtime/certification_simnow_c01_v4_supervisor.py"]
        issuer._DEPENDENCY_MANIFEST_SHA256 = owner_rows[
            "backtrader_runtime/certification_simnow_c01_dependencies_v1.json"
        ]
        issuer._PRIVATE_HELPER_SHA256 = owner_rows[
            "backtrader_runtime/certification_roundtrip_private.py"
        ]
        issuer._R3_CLI_HELPER_SHA256 = owner_rows[
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
        ]
        issuer._ADMISSION_BOUND_SOURCE_PATHS = (source_paths["issuer"], runner_relative)
        exec(
            "def _rewind_locked_read_handle(private, api, handle):\n"
            "    return api.rewind_handle(handle)\n",
            issuer.__dict__,
        )
        issuer._C01V18Admission = type("Admission", (), {})
        admission = issuer._C01V18Admission()
        admission.bindings = {
            "account_scope_sha256": account_hash,
            "credential_binding_sha256": credential_hash,
        }
        sys.modules[issuer.__name__] = issuer

        front = ModuleType("backtrader_runtime.certification_simnow_c01_front_transport_v12")
        front.__file__ = str(fake_root / source_paths["front"])
        front.__c01_source_sha256__ = _sha(module_bytes["front"])
        front._V18_RELATIVE = source_paths["issuer"]
        front._V18_SHA256 = issuer.__c01_source_sha256__
        front._V18_MODULE_NAME = issuer.__name__
        sys.modules[front.__name__] = front
        projection = ModuleType("common.c01_root_admission_bridge")
        projection.__file__ = str(fake_root / source_paths["projection"])
        projection.__c01_source_sha256__ = _sha(module_bytes["projection"])
        sys.modules[projection.__name__] = projection
        certification = ModuleType("common.certification")
        certification.__file__ = str(fake_root / source_paths["certification"])
        certification.__c01_source_sha256__ = _sha(module_bytes["certification"])
        sys.modules[certification.__name__] = certification

        expected_custody_sha = _sha(module_bytes["custody"])
        custody.__file__ = str(fake_root / custody_relative)
        custody.__c01_source_sha256__ = expected_custody_sha
        issuer._OWNER_MODULE_NAME = owner.__name__

        bridge = ModuleType(BRIDGE_NAME)
        bridge.__file__ = str(fake_root / source_paths["root_bridge"])
        bridge.__c01_source_sha256__ = _sha(module_bytes["root_bridge"])
        bridge._CURRENT_SCOPE = ContextVar("synthetic_root_scope", default=None)
        bridge._C01RootInvocationScope = type(
            "Scope", (), {"__module__": BRIDGE_NAME}
        )
        bridge.C01NativeTdReadV16CandidatePendingRootAdmission = type(
            "Pending", (), {}
        )
        bridge._FRONT_MODULE_SHA256 = front.__c01_source_sha256__
        bridge._BRIDGE_SHA256 = projection.__c01_source_sha256__
        bridge._CERTIFICATION_MODULE_SHA256 = certification.__c01_source_sha256__
        bridge._ROOT_CUSTODY_MODULE_SHA256 = expected_custody_sha
        bridge.stage_calls = 0
        bridge.ledger_events = []

        def stage_current_c01_candidate(*, admission, pair_binding, process, validation, artifacts):
            scope = bridge._CURRENT_SCOPE.get()
            bridge.stage_calls += 1
            scope.stage_count = 1
            scope.stage = SimpleNamespace(
                request_count=8,
                auth_login_callback_count=2,
                query_callback_count=6,
                snapshot_count=2,
                write_invocation_count=0,
            )
            scope.candidate_refs = (admission, pair_binding, process, validation, artifacts)

        def verify_ledger(scope, pending):
            assert scope.pending is pending and scope.candidate_refs is not None
            assert scope.stage.request_count == 8
            assert scope.stage.auth_login_callback_count == 2
            assert scope.stage.query_callback_count >= 6
            assert scope.stage.snapshot_count == 2 and scope.stage.write_invocation_count == 0
            bridge.ledger_events.append("verify")
            return None

        def record_ledger(scope, pending, *, root_custody_module, receipt):
            assert root_custody_module is custody
            assert type(receipt) is custody.C01RootNativeLedgerReceipt
            assert receipt._factory is custody._C01_ROOT_POSTVERIFY_FACTORY
            assert receipt._scope is scope and receipt._pending is pending
            assert receipt._nonce is scope.nonce
            assert receipt._candidate_refs is scope.candidate_refs
            assert (
                receipt._projection is scope.projection
                and receipt._source_bundle is scope.bundle
                and receipt._issuer is scope.issuer
                and receipt._owner is scope.owner
                and receipt._helpers is scope.helpers
            )
            bridge.ledger_events.append("record")
            scope.verification = receipt

        def mint(**kwargs):
            assert bridge.ledger_events == ["verify", "record"]
            assert kwargs["native_ledger_receipt"] is kwargs["scope"].verification
            bridge.ledger_events.append("mint")
            bridge.receipts = tuple(
                kwargs[key]
                for key in (
                    "source_postverify_receipt",
                    "runtime_postverify_receipt",
                    "artifact_postverify_receipt",
                    "account_binding_receipt",
                    "native_ledger_receipt",
                )
            )
            return SimpleNamespace(status="synthetic-proof")

        bridge.stage_current_c01_candidate = stage_current_c01_candidate
        bridge.verify_current_c01_request_ledger = verify_ledger
        bridge.record_root_native_ledger_receipt = record_ledger
        bridge._mint_root_postverify_proof = mint
        bridge._root_custody_module_is_pinned = lambda module: (
            module is custody and module.__c01_source_sha256__ == expected_custody_sha
        )
        sys.modules[BRIDGE_NAME] = bridge

        helpers = {
            "private": private_module,
            "r3_cli": cli_module,
            "interpreter_binding": interpreter,
            "protocol": protocol,
            "contract": contract,
            "supervisor": supervisor,
            "probe": other_helpers[0],
            "renderer": other_helpers[1],
            "selector": other_helpers[2],
            "handoff": other_helpers[3],
            "watchdog": other_helpers[4],
            "job_backend": other_helpers[5],
            "owner_now_utc": owner._now_utc,
        }

        class FakePrivateDirectory(private_module.PrivateArtifactDirectory):
            def __init__(self, path: Path):
                self.path = path
                self.device, self.inode = api._identity(path)

        private_module.PrivateArtifactDirectory = FakePrivateDirectory
        run_root = fake_root / "private-run"
        root_dir = FakePrivateDirectory(run_root)
        native_dir = FakePrivateDirectory(run_root / "native-flow")
        evidence_dir = FakePrivateDirectory(run_root / "evidence")
        snapshot_dir = evidence_dir.path / "snapshots"
        baseline_path = snapshot_dir / "baseline.json"
        final_path = snapshot_dir / "final.json"
        baseline_raw = b'{"synthetic":"baseline"}'
        final_raw = b'{"synthetic":"final"}'
        files[_key(baseline_path)] = baseline_raw
        files[_key(final_path)] = final_raw
        artifacts = {SNAPSHOT_BASELINE: baseline_raw, SNAPSHOT_FINAL: final_raw}
        private_paths = owner._PrivateRun()
        private_paths.root = root_dir
        private_paths.native_flow = native_dir
        private_paths.evidence = evidence_dir

        # The file map is shared by the fake API; update it after adding the
        # private snapshots, then build the typed scope and pending result.
        api.files = files
        protocol.MAX_PRIVATE_SNAPSHOT_BYTES = 1024
        bundle_factory = object()
        bundle_type = type("VerifiedC01V18SourceBundle", (), {})
        front._BUNDLE_FACTORY = bundle_factory
        front.VerifiedC01V18SourceBundle = bundle_type
        bundle = bundle_type()
        bundle.root = fake_root
        bundle.issuer = issuer
        bundle.owner = owner
        bundle.helpers = helpers
        bundle._active = True
        bundle._factory = bundle_factory
        scope = bridge._C01RootInvocationScope()
        scope.bundle = bundle
        scope.front = front
        scope.root_custody_module = custody
        scope.issuer = issuer
        scope.owner = owner
        scope.helpers = helpers
        scope.protocol = protocol
        scope.contract = contract
        scope.supervisor = supervisor
        scope.bridge = projection
        scope.certification_module = certification
        scope.nonce = object()
        scope.active = True
        scope.stage_count = 0
        scope.stage = None
        scope.projection = object()
        scope.candidate_refs = None
        scope.verification = None
        scope.issuer_returned = False
        scope.pending = None
        scope.consumed = False

        pending_type = bridge.C01NativeTdReadV16CandidatePendingRootAdmission
        pending = pending_type()
        pending._scope = scope
        pending._nonce = scope.nonce
        scope.pending = pending
        scope.issuer_returned = True

        # Fake source APIs below address this synthetic source tree only.
        private_module._api = lambda: api
        cli_module._read_bounded_handle = read_bounded_handle
        yield SimpleNamespace(
            custody=custody,
            root=fake_root,
            private_module=private_module,
            cli_module=cli_module,
            root_entry=root_entry,
            exact_public=exact_public,
            software_pins=software_pins,
            scope=scope,
            bridge=bridge,
            admission=admission,
            pair_binding=pair_binding,
            process=process,
            validation=validation,
            artifacts=artifacts,
            credentials=credentials,
            private_paths=private_paths,
            api=api,
            pending=pending,
        )
    finally:
        for name, old in saved_names.items():
            if old is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "snapshot",
        "artifact_mapping",
        "seek_fail",
        "seek_eof",
        "held_change",
        "path_replace",
        "acl_change",
        "account_binding",
        "stage_bool",
        "foreign_nonce",
    ],
)
def test_same_call_receipts_and_artifact_tamper_rejection(tmp_path, tamper):
    with _loaded_producer() as custody:
        with _synthetic_candidate(tmp_path, custody) as candidate:
            bridge = candidate.bridge
            scope = candidate.scope
            public_pins_with_entry = dict(candidate.exact_public)
            entry_relative = Path(candidate.root_entry.__file__).relative_to(
                candidate.root
            ).as_posix()
            public_pins_with_entry[entry_relative] = candidate.root_entry.__c01_source_sha256__
            with pytest.raises(custody.C01RootCustodyV16Error) if tamper else contextlib.nullcontext():
                with candidate.custody.open_source_runtime_leases(
                    candidate.private_module,
                    candidate.cli_module,
                    public_pins_with_entry,
                    candidate.software_pins,
                    root_entry_module=candidate.root_entry,
                ):
                    scope_token = bridge._CURRENT_SCOPE.set(scope)
                    try:
                        custody.prepare_candidate_custody(
                            scope,
                            candidate.admission,
                            candidate.pair_binding,
                            candidate.process,
                            candidate.validation,
                            candidate.artifacts,
                            candidate.credentials,
                            candidate.private_paths,
                        )
                        if tamper == "snapshot":
                            candidate.api.files[_key(candidate.private_paths.evidence.path / SNAPSHOT_FINAL)] = b'{"synthetic":"changed"}'
                        elif tamper == "artifact_mapping":
                            candidate.artifacts[SNAPSHOT_FINAL] = b'{"synthetic":"changed"}'
                        elif tamper in {"seek_fail", "seek_eof"}:
                            candidate.api.seek_mode = "fail" if tamper == "seek_fail" else "eof"
                        elif tamper == "held_change":
                            relative = next(
                                path
                                for path in candidate.exact_public
                                if path.endswith("certification_simnow_c01_root_v16.py")
                            )
                            candidate.api.files[_key(candidate.root / relative)] = b"changed held source"
                        elif tamper == "path_replace":
                            final_path = candidate.private_paths.evidence.path / SNAPSHOT_FINAL
                            candidate.api.files[_key(final_path)] = b'{"synthetic":"replacement"}'
                            candidate.api.identities[_key(final_path)] = (7, 999999)
                        elif tamper == "foreign_nonce":
                            candidate.pending._nonce = object()
                        elif tamper == "acl_change":
                            candidate.api.acl_tampered = True
                        elif tamper == "account_binding":
                            candidate.admission.bindings[
                                "credential_binding_sha256"
                            ] = "0" * 64
                        elif tamper == "stage_bool":
                            scope.stage.write_invocation_count = False
                        proof = custody.verify_and_mint_postverify(
                            bridge, scope, candidate.pending
                        )
                    finally:
                        bridge._CURRENT_SCOPE.reset(scope_token)
            if tamper is None:
                assert proof.status == "synthetic-proof"
                assert bridge.stage_calls == 1
                assert bridge.ledger_events == ["verify", "record", "mint"]
                assert len(bridge.receipts) == 5
                native = bridge.receipts[-1]
                assert native.request_count == 8
                assert native.auth_login_callback_count == 2
                assert native.query_callback_count == scope.stage.query_callback_count == 6
                assert native.snapshot_count == 2
                assert native.write_invocation_count == 0
                assert "synthetic-password" not in repr(native)
                assert candidate.credentials.user_id not in repr(native)
                assert candidate.admission.bindings["account_scope_sha256"] not in repr(native)
                assert candidate.admission.bindings["credential_binding_sha256"] not in repr(native)
            else:
                assert bridge.ledger_events == (["verify"] if tamper == "stage_bool" else [])
                assert bridge.stage_calls == 1


@pytest.mark.parametrize("tamper", ["missing_source_row", "software_hash"])
def test_source_and_runtime_pin_maps_are_exact(tmp_path, tamper):
    with _loaded_producer() as custody:
        with _synthetic_candidate(tmp_path, custody) as candidate:
            public_pins = dict(candidate.exact_public)
            entry_relative = Path(candidate.root_entry.__file__).relative_to(
                candidate.root
            ).as_posix()
            public_pins[entry_relative] = candidate.root_entry.__c01_source_sha256__
            software_pins = dict(candidate.software_pins)
            if tamper == "missing_source_row":
                del public_pins["backtrader_runtime/certification_simnow_c01_v3_protocol.py"]
            else:
                path, _pin = next(iter(software_pins.items()))
                software_pins[path] = "0" * 64
            with pytest.raises(custody.C01RootCustodyV16Error):
                with candidate.custody.open_source_runtime_leases(
                    candidate.private_module,
                    candidate.cli_module,
                    public_pins,
                    software_pins,
                    root_entry_module=candidate.root_entry,
                ):
                    pytest.fail("tampered fixed pin map unexpectedly opened")


def test_real_v7_helper_bundle_without_module_hash_markers_is_bound(tmp_path):
    """Exercise the public owner loader, which compiles pinned helpers without hash markers."""
    with _loaded_producer() as custody:
        source_root = tmp_path / "public-source-root"
        runtime_dir = source_root / "backtrader_runtime"
        scripts_dir = source_root / "scripts"
        runtime_dir.mkdir(parents=True)
        scripts_dir.mkdir(parents=True)

        owner_source = ROOT / "backtrader_runtime" / "certification_simnow_c01_v7_owner.py"
        owner_relative = "backtrader_runtime/certification_simnow_c01_v7_owner.py"
        owner_target = source_root / owner_relative
        owner_target.write_bytes(owner_source.read_bytes())

        owner_name = "backtrader_runtime._c01_native_td_read_v7_owner"
        module_names = (
            "backtrader_runtime",
            "scripts",
            owner_name,
            "backtrader_runtime._c01_native_td_read_v18_source",
            "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
            "backtrader_runtime.certification_simnow_c01_v3_protocol",
            "backtrader_runtime.certification_simnow_c01_v3_contract",
            "backtrader_runtime.certification_simnow_c01_v4_supervisor",
            "backtrader_runtime.certification_roundtrip_private",
            "backtrader_runtime.certification_binance_roundtrip_r3_cli",
            "backtrader_runtime.ctp_front_pair_probe",
            "scripts.ctp_000_render_config",
            "scripts.ctp_000_paired_front_selector",
            "scripts.ctp_000_front_handoff",
            "scripts.ctp_i13_i15_outer_watchdog",
            "scripts.ctp_i13_i15_windows_job_backend",
        )
        missing = object()
        saved = {name: sys.modules.get(name, missing) for name in module_names}
        try:
            for name, package_path in (
                ("backtrader_runtime", runtime_dir),
                ("scripts", scripts_dir),
            ):
                package = ModuleType(name)
                package.__package__ = name
                package.__path__ = [str(package_path.resolve())]
                package.__loader__ = None
                package.__spec__ = ModuleSpec(name, loader=None, is_package=True)
                sys.modules[name] = package

            owner = ModuleType(owner_name)
            owner.__file__ = str(owner_target.resolve())
            owner.__package__ = "backtrader_runtime"
            owner.__loader__ = None
            owner.__spec__ = ModuleSpec(owner_name, loader=None)
            sys.modules[owner_name] = owner
            owner_code = compile(
                owner_target.read_bytes(), owner.__file__, "exec", dont_inherit=True
            )
            exec(owner_code, owner.__dict__, owner.__dict__)

            for relative, expected_pin in owner._SOURCE_PINS.items():
                source_path = ROOT / Path(relative)
                raw = source_path.read_bytes()
                assert _sha(raw) == expected_pin, f"public owner pin is stale: {relative}"
                target = source_root / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)

            issuer = ModuleType("backtrader_runtime._c01_native_td_read_v18_source")
            issuer._OWNER_MODULE_NAME = owner_name
            sys.modules[issuer.__name__] = issuer
            owner_pin = _sha(owner_target.read_bytes())
            custody._validate_owner_module_source(owner, issuer, source_root, owner_pin)

            lease = object.__new__(custody.C01RootSourceRuntimeLease)
            lease._helper_bindings = None
            scope = SimpleNamespace(owner=owner, helpers=None)
            with owner._verified_helper_bundle() as aliases:
                helpers = dict(aliases)
                helpers["owner_now_utc"] = owner._now_utc
                scope.helpers = helpers
                helpers["private"]._api = lambda: SimpleNamespace(
                    opened=None, info=None, verify_acl=None, current_sid=None
                )
                assert all(
                    getattr(module, "__c01_source_sha256__", None) is None
                    for module in helpers.values()
                    if type(module) is ModuleType
                )
                custody._verify_owner_helper_modules(
                    scope,
                    source_root,
                    dict(owner._SOURCE_PINS),
                    owner._MODULE_PATHS,
                    lease,
                    require_active=True,
                )
                custody._validate_helper_modules(helpers["private"], helpers["r3_cli"])

            assert lease._helper_bindings is not None
            custody._verify_owner_helper_modules(
                scope,
                source_root,
                dict(owner._SOURCE_PINS),
                owner._MODULE_PATHS,
                lease,
                require_active=False,
            )
        finally:
            for name, previous in saved.items():
                if previous is missing:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous
