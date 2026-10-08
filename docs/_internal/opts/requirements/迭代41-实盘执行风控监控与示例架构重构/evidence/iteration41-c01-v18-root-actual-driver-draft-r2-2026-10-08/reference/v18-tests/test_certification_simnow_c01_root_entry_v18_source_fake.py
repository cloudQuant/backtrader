"""Fake-only same-process orchestration checks for the C01 V18 Root entry."""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import FunctionType, MappingProxyType, ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = ROOT / "examples" / "000_live_certification" / "simnow_penetration"
ENTRY_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_entry_v18.py"
FRONT_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_front_transport_v12.py"
ROOT_BRIDGE_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_v16.py"
CUSTODY_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_custody_v16.py"
ISSUER_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v18.py"
MANIFEST_PATH = (
    ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v18.sources.json"
)
BRIDGE_FIXTURE_PATH = (
    ROOT
    / "tests"
    / "unit"
    / "runtime"
    / "test_certification_simnow_c01_root_v16_source_fake.py"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _public_source_pins() -> dict[str, str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="ascii"))
    pins: dict[str, str] = {}
    for relative, expected in manifest["source_files"].items():
        assert _sha256(ROOT / Path(relative)) == expected
        pins[relative] = expected
    manifest_relative = MANIFEST_PATH.relative_to(ROOT).as_posix()
    pins[manifest_relative] = _sha256(MANIFEST_PATH)
    for relative in manifest["admission_bound_files"]:
        pins[relative] = _sha256(ROOT / Path(relative))
    for path in (
        FRONT_PATH,
        ROOT_BRIDGE_PATH,
        SUITE_ROOT / "common" / "c01_root_admission_bridge.py",
        SUITE_ROOT / "common" / "certification.py",
        CUSTODY_PATH,
        ISSUER_PATH,
    ):
        pins[path.relative_to(ROOT).as_posix()] = _sha256(path)
    return pins


def _bind_v18_fake_candidate(issuer, state, candidate) -> None:
    protocol = candidate["protocol"]
    contract = candidate["contract"]
    supervisor = candidate["supervisor"]
    owner = candidate["owner"]
    original = candidate["process"]
    payload = original.worker_receipt.to_dict()
    payload["worker_source_sha256"] = issuer._WORKER_SHA256
    worker = protocol.parse_worker_frame(protocol.encode_worker_frame(payload))
    lifecycle = dataclasses.replace(
        original.process_lifecycle,
        worker_source_sha256=issuer._WORKER_SHA256,
    )
    candidate["process"] = dataclasses.replace(
        original,
        worker_receipt=worker,
        process_lifecycle=lifecycle,
    )
    fixture_values = sys.modules["_c01_v2_contract_test_fixtures_for_v3"]
    candidate["validation"] = contract.validate_c01_candidate(
        worker,
        lifecycle,
        expected_pair_binding=candidate["pair"],
        expected_worker_source_sha256=issuer._WORKER_SHA256,
        expected_account_scope_sha256=candidate["admission"].bindings[
            "account_scope_sha256"
        ],
        expected_credential_binding_sha256=candidate["admission"].bindings[
            "credential_binding_sha256"
        ],
        private_snapshot_artifacts=candidate["artifacts"],
        expected_broker_id=fixture_values._BROKER_ID,
        expected_user_id=fixture_values._USER_ID,
    )

    @contextmanager
    def profile_lease(_root, _issuer_module):
        state["events"].append("issuer_enter")
        try:
            yield candidate["admission"]
        finally:
            state["events"].append("issuer_return")

    @contextmanager
    def pair_config_lease(_root, _helpers):
        state["issuer_stack_active"] = True
        try:
            yield (
                ({"md_front": "tcp://192.0.2.1:10001", "td_front": "tcp://192.0.2.2:10002"},),
                candidate["admission"].bindings["config_source_sha256"],
                lambda: None,
            )
        finally:
            state["issuer_stack_active"] = False
            state["events"].append("issuer_exitstack_closed")

    @contextmanager
    def credential_lease(*_args, **_kwargs):
        yield SimpleNamespace(broker_id=fixture_values._BROKER_ID, user_id=fixture_values._USER_ID)

    @contextmanager
    def private_run(_helpers):
        yield SimpleNamespace(root=SimpleNamespace(path=ROOT / "fake-private-root"))

    def select_pair(_helpers, _front_pairs, *, audit_sink, **_kwargs):
        pair = candidate["pair"]
        audit_sink["fresh_pair_selection"] = issuer._fresh_pair_selection_value(
            False, pair.selection_sha256
        )
        return pair

    issuer._profile_admission_lease = profile_lease
    issuer._private_pair_config_lease = pair_config_lease
    issuer._credential_lease = credential_lease
    issuer._private_run = private_run
    issuer._pair_projection = lambda _helpers, _pairs: b"source-fake-pair-projection"
    issuer._select_current_pair = select_pair
    issuer._selected_pair_from_binding = lambda _helpers, pairs, binding, **_kwargs: pairs[
        binding.selected_index
    ]
    issuer._require_clean_ambient_secrets = lambda: None
    issuer._consumer_matches = lambda: True
    issuer._verify_public_profile_sources = lambda _root: None
    issuer._verify_source_manifest = lambda _root, _owner: None
    issuer._read_worker_progress = lambda *_args, **_kwargs: {
        "status": "verified",
        "last_stage": "worker_receipt",
        "last_event": "end",
    }
    issuer._read_worker_failure_diagnostic = lambda *_args, **_kwargs: None
    issuer._project_worker_observation = lambda *_args, **_kwargs: None
    issuer._validation_issues_pass = lambda _contract, _protocol, decision: (
        type(decision) is protocol.C01CandidateValidation
    )
    issuer._audit_document = lambda *_args, **_kwargs: {}
    issuer._persist_private_audit = lambda *_args, **_kwargs: None
    owner._repo_root = lambda: ROOT
    owner._private_input_packet = lambda *_args, **_kwargs: (
        b"source-fake-credential-packet",
        candidate["admission"].bindings["account_scope_sha256"],
        candidate["admission"].bindings["credential_binding_sha256"],
    )
    owner._worker_process_complete = lambda *_args, **_kwargs: True
    owner._worker_receipt_matches = lambda *_args, **_kwargs: True
    owner._verify_tree = lambda *_args, **_kwargs: None
    owner._read_snapshot_artifacts = lambda *_args, **_kwargs: candidate["artifacts"]

    def fake_worker(*_args, **_kwargs):
        state["worker_called"] = True
        if state["mode"] == "missing":
            return SimpleNamespace(reason="source_fake_missing_worker_receipt")
        return candidate["process"]

    supervisor.run_fixed_c01_worker = fake_worker


@contextmanager
def _integrated_entry(mode: str = "success"):
    fixture_module_name = "_c01_v18_root_entry_bridge_fixtures"
    fixture = _load_module(fixture_module_name, BRIDGE_FIXTURE_PATH)
    saved_names = (
        "backtrader_runtime.certification_simnow_c01_root_v16",
        "backtrader_runtime.certification_simnow_c01_root_entry_v18",
        "common.c01_root_admission_bridge",
        "backtrader_runtime._c01_native_td_read_v7_owner",
    )
    missing = object()
    saved = {name: sys.modules.get(name, missing) for name in saved_names}
    entry = root_bridge = projection = None
    front_loader = None
    old_front_namespace: dict[str, object] = {}
    old_bridge_pin = None
    try:
        with fixture._candidate_scope() as (
            _fixture_bridge,
            front,
            candidate,
            bundle,
            projection,
            certification,
            _fixture_custody,
        ):
            root_bridge = _load_module(
                "backtrader_runtime.certification_simnow_c01_root_v16", ROOT_BRIDGE_PATH
            )
            root_bridge.__c01_source_sha256__ = _sha256(ROOT_BRIDGE_PATH)
            projection.__name__ = "common.c01_root_admission_bridge"
            sys.modules[projection.__name__] = projection
            projection.__dict__["project_c01_root_candidate"].__module__ = projection.__name__

            pins = _public_source_pins()
            front.__c01_source_sha256__ = pins[FRONT_PATH.relative_to(ROOT).as_posix()]
            certification.__c01_source_sha256__ = pins[
                "examples/000_live_certification/simnow_penetration/common/certification.py"
            ]
            projection.__c01_source_sha256__ = pins[
                "examples/000_live_certification/simnow_penetration/common/c01_root_admission_bridge.py"
            ]

            custody = _load_module(
                "backtrader_runtime.certification_simnow_c01_root_custody_v16",
                CUSTODY_PATH,
            )
            custody.__c01_source_sha256__ = pins[CUSTODY_PATH.relative_to(ROOT).as_posix()]
            real_prepare = custody.prepare_candidate_custody
            old_bridge_pin = root_bridge._ROOT_CUSTODY_MODULE_SHA256
            root_bridge._ROOT_CUSTODY_MODULE_SHA256 = custody.__c01_source_sha256__

            entry = _load_module(
                "backtrader_runtime.certification_simnow_c01_root_entry_v18", ENTRY_PATH
            )
            entry.__c01_source_sha256__ = _sha256(ENTRY_PATH)
            assert entry._EXACT_PUBLIC_SOURCE_PINS == pins
            assert (
                ENTRY_PATH.relative_to(ROOT).as_posix()
                not in entry._EXACT_PUBLIC_SOURCE_PINS
            )
            state: dict[str, object] = {
                "mode": mode,
                "events": [],
                "lease_active": False,
                "issuer_stack_active": False,
                "prepared": False,
                "postverified": False,
                "worker_called": False,
                "stage_calls": 0,
                "custody_hook_calls": 0,
                "scope": None,
                "entry": entry,
                "bridge": root_bridge,
                "bundle": bundle,
                "candidate": candidate,
                "real_prepare_candidate_custody": real_prepare,
            }
            custody._C01_TEST_STATE = state
            custody._C01_ROOT_POSTVERIFY_FACTORY = object()
            for receipt_name in (
                "C01RootSourcePostverifyReceipt",
                "C01RootRuntimePostverifyReceipt",
                "C01RootArtifactPostverifyReceipt",
                "C01RootAccountBindingReceipt",
                "C01RootNativeLedgerReceipt",
            ):
                receipt_type = type(receipt_name, (), {"__module__": custody.__name__})
                setattr(custody, receipt_name, receipt_type)

            exec(
                """
from contextlib import contextmanager
import sys

@contextmanager
def open_source_runtime_leases(private_module, cli_module, exact_public_pins,
                               exact_software_pins, *, root_entry_module):
    state = _C01_TEST_STATE
    if state['lease_active'] or root_entry_module is not state['entry']:
        raise RuntimeError('lease_binding_invalid')
    if exact_public_pins != state['entry']._EXACT_PUBLIC_SOURCE_PINS | {
            'backtrader_runtime/certification_simnow_c01_root_entry_v18.py':
                root_entry_module.__c01_source_sha256__}:
        raise RuntimeError('source_map_mismatch')
    state['events'].append('lease_open')
    state['lease_active'] = True
    try:
        yield state
    finally:
        state['events'].append('lease_close')
        state['scope_inactive_at_lease_close'] = (
            state['scope'] is None or state['scope'].active is False)
        state['lease_active'] = False

def prepare_candidate_custody(scope, admission, pair_binding, process,
                              validation, artifacts, credentials, private_paths):
    state = _C01_TEST_STATE
    state['custody_hook_calls'] += 1
    bridge = state['bridge']
    if state['scope'] is None:
        state['scope'] = scope
    mode = state['mode']
    if mode == 'late':
        state['issuer_stack_active'] = False
    if (not state['lease_active'] or not state['issuer_stack_active']
            or scope is not state['scope']
            or bridge.current_c01_root_invocation_nonce() is not scope.nonce):
        raise RuntimeError('candidate_scope_invalid')
    if mode == 'foreign':
        raise RuntimeError('candidate_scope_invalid')
    if state['prepared']:
        raise RuntimeError('candidate_custody_reused')
    state['events'].append('candidate_stage')
    state['stage_calls'] += 1
    bridge.stage_current_c01_candidate(
        admission=admission, pair_binding=pair_binding, process=process,
        validation=validation, artifacts=artifacts)
    state['prepared'] = True
    if mode == 'reused':
        state['prepared'] = False
        state['stage_calls'] += 1
        bridge.stage_current_c01_candidate(
            admission=admission, pair_binding=pair_binding, process=process,
            validation=validation, artifacts=artifacts)

def verify_and_mint_postverify(root_bridge_module, scope, pending):
    state = _C01_TEST_STATE
    if (not state['lease_active'] or state['issuer_stack_active']
            or not state['prepared'] or state['postverified']
            or root_bridge_module is not state['bridge']
            or scope is not state['scope']):
        raise RuntimeError('postverify_binding_invalid')
    state['events'].append('postverify')
    root_bridge_module.verify_current_c01_request_ledger(scope, pending)
    common = {'_factory': _C01_ROOT_POSTVERIFY_FACTORY,
              '_scope': scope, '_pending': pending, '_nonce': scope.nonce}
    def receipt(name, extra=None):
        value = getattr(sys.modules[__name__], name)()
        for key, item in common.items():
            setattr(value, key, item)
        for key, item in (extra or {}).items():
            setattr(value, key, item)
        return value
    native = receipt('C01RootNativeLedgerReceipt', {
        '_projection': scope.projection,
        '_source_bundle': scope.bundle,
        '_issuer': scope.issuer,
        '_owner': scope.owner,
        '_helpers': scope.helpers,
        '_candidate_refs': tuple(scope.candidate_refs),
        'request_count': 8,
        'auth_login_callback_count': 2,
        'query_callback_count': scope.stage.query_callback_count,
        'snapshot_count': 2,
        'write_invocation_count': 0,
    })
    root_bridge_module.record_root_native_ledger_receipt(
        scope, pending, root_custody_module=sys.modules[__name__], receipt=native)
    proof = root_bridge_module._mint_root_postverify_proof(
        scope=scope, pending=pending,
        source_postverify_receipt=receipt('C01RootSourcePostverifyReceipt'),
        runtime_postverify_receipt=receipt('C01RootRuntimePostverifyReceipt'),
        artifact_postverify_receipt=receipt('C01RootArtifactPostverifyReceipt'),
        account_binding_receipt=receipt('C01RootAccountBindingReceipt'),
        native_ledger_receipt=native)
    state['postverified'] = True
    return proof
""",
                custody.__dict__,
            )
            sys.modules[custody.__name__] = custody
            hook = custody.prepare_candidate_custody
            assert hook.__module__ == custody.__name__
            assert hook.__qualname__ == "prepare_candidate_custody"
            assert hook.__globals__ is custody.__dict__
            assert type(real_prepare) is FunctionType
            assert real_prepare.__module__ == custody.__name__
            assert real_prepare.__qualname__ == "prepare_candidate_custody"
            assert real_prepare.__globals__ is custody.__dict__
            assert real_prepare.__code__.co_filename == str(CUSTODY_PATH)
            assert custody.__c01_source_sha256__ == pins[
                CUSTODY_PATH.relative_to(ROOT).as_posix()
            ]

            issuer = _load_module(front._V18_MODULE_NAME, ISSUER_PATH)
            issuer.__file__ = str(ISSUER_PATH)
            issuer.__c01_source_sha256__ = front._V18_SHA256
            sys.modules[bundle.owner.__name__] = bundle.owner
            bundle.issuer = issuer
            issuer._C01_TEST_STATE = state
            issuer._C01_TEST_CUSTODY = custody
            now = datetime.now(timezone.utc)
            bindings = dict(candidate["admission"].bindings)
            bindings["config_source_sha256"] = "d" * 64
            candidate["admission"] = issuer._C01V18Admission(
                admission_id="source-fake-admission",
                not_before_utc=now - timedelta(minutes=1),
                expires_at_utc=now + timedelta(minutes=5),
                bindings=MappingProxyType(bindings),
                configured_front_pair_count=1,
            )
            _bind_v18_fake_candidate(issuer, state, candidate)
            helpers = dict(bundle.helpers)
            helpers["owner_now_utc"] = bundle.owner._now_utc
            bundle.helpers = MappingProxyType(helpers)
            bundle._active = True

            old_front_namespace = {
                key: front.__dict__.get(key, missing)
                for key in (
                    "verified_c01_v18_sources",
                    "_C01_TEST_BUNDLE",
                )
            }
            exec(
                """
from contextlib import contextmanager

@contextmanager
def verified_c01_v18_sources(root):
    if root != _C01_TEST_BUNDLE.root:
        raise RuntimeError('wrong_root')
    try:
        yield _C01_TEST_BUNDLE
    finally:
        _C01_TEST_BUNDLE._active = False
""",
                front.__dict__,
            )
            front._C01_TEST_BUNDLE = bundle
            front_loader = front.verified_c01_v18_sources

            yield {
                "entry": entry,
                "front": front,
                "root_bridge": root_bridge,
                "projection": projection,
                "certification": certification,
                "custody": custody,
                "bundle": bundle,
                "candidate": candidate,
                "pins": pins,
                "state": state,
                "software_pins": dict(entry._EXACT_SOFTWARE_PINS),
            }
    finally:
        if front_loader is not None:
            front.verified_c01_v18_sources = old_front_namespace[
                "verified_c01_v18_sources"
            ]
            if old_front_namespace["_C01_TEST_BUNDLE"] is missing:
                front.__dict__.pop("_C01_TEST_BUNDLE", None)
            else:
                front._C01_TEST_BUNDLE = old_front_namespace["_C01_TEST_BUNDLE"]
        if root_bridge is not None and old_bridge_pin is not None:
            root_bridge._ROOT_CUSTODY_MODULE_SHA256 = old_bridge_pin
        for name, previous in saved.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        sys.modules.pop(fixture_module_name, None)


def test_entry_runs_stage_after_validation_and_postverify_after_issuer_cleanup():
    with _integrated_entry() as harness:
        real_prepare = harness["state"]["real_prepare_candidate_custody"]
        assert real_prepare.__module__ == harness["custody"].__name__
        assert real_prepare.__globals__ is harness["custody"].__dict__
        assert harness["custody"].__c01_source_sha256__ == harness["pins"][
            CUSTODY_PATH.relative_to(ROOT).as_posix()
        ]
        assert harness["root_bridge"]._ROOT_CUSTODY_MODULE_SHA256 == (
            harness["custody"].__c01_source_sha256__
        )
        result = harness["entry"].run_c01_root_entry_v18(
            root=ROOT,
            front_module=harness["front"],
            root_bridge_module=harness["root_bridge"],
            projection_module=harness["projection"],
            certification_module=harness["certification"],
            root_custody_module=harness["custody"],
            exact_public_pins=harness["pins"]
            | {
                "backtrader_runtime/certification_simnow_c01_root_entry_v18.py":
                    harness["entry"].__c01_source_sha256__
            },
            exact_software_pins=harness["software_pins"],
        )
        payload = result.to_dict()
        state = harness["state"]

    assert result.exit_code() == 0
    assert payload["status"] == "PASS"
    assert state["events"] == [
        "lease_open",
        "issuer_enter",
        "candidate_stage",
        "issuer_exitstack_closed",
        "issuer_return",
        "postverify",
        "lease_close",
    ]
    assert state["scope_inactive_at_lease_close"] is True
    assert state["prepared"] is True
    assert state["postverified"] is True
    assert state["worker_called"] is True
    assert state["stage_calls"] == 1
    assert state["custody_hook_calls"] == 1


@pytest.mark.parametrize("mode", ["missing", "foreign", "reused", "late"])
def test_entry_denies_missing_foreign_reused_or_late_candidate_evidence(mode):
    with _integrated_entry(mode) as harness:
        with pytest.raises(harness["entry"].C01RootEntryV18Error):
            harness["entry"].run_c01_root_entry_v18(
                root=ROOT,
                front_module=harness["front"],
                root_bridge_module=harness["root_bridge"],
                projection_module=harness["projection"],
                certification_module=harness["certification"],
                root_custody_module=harness["custody"],
                exact_public_pins=harness["pins"]
                | {
                    "backtrader_runtime/certification_simnow_c01_root_entry_v18.py":
                        harness["entry"].__c01_source_sha256__
                },
                exact_software_pins=harness["software_pins"],
            )
        state = harness["state"]
    assert state["events"][0] == "lease_open"
    assert state["events"][-1] == "lease_close"
    assert state["postverified"] is False
    assert state["worker_called"] is True
    assert state["stage_calls"] == (2 if mode == "reused" else 0)
    assert state["custody_hook_calls"] == (0 if mode == "missing" else 1)


def test_rewind_helper_resets_only_a_successful_fake_handle():
    import ctypes
    from ctypes import wintypes

    issuer = _load_module(
        "_c01_v18_issuer_rewind_test", ISSUER_PATH
    )
    class FakeHandle:
        position = 57

    class FakeSetFilePointer:
        argtypes = None
        restype = None

        def __init__(self, succeeds=True, offset=0):
            self.succeeds = succeeds
            self.offset = offset

        def __call__(self, handle, _distance, new_position, move_method):
            assert move_method == 0
            if not self.succeeds:
                return False
            handle.position = self.offset
            new_position._obj.value = self.offset
            return True

    handle = FakeHandle()
    seek = FakeSetFilePointer()
    api = SimpleNamespace(kernel=SimpleNamespace(SetFilePointerEx=seek))
    private = SimpleNamespace(C=ctypes, W=wintypes)
    assert issuer._rewind_locked_read_handle(private, api, handle) is True
    assert handle.position == 0
    assert seek.restype is wintypes.BOOL

    handle.position = 57
    api.kernel.SetFilePointerEx = FakeSetFilePointer(succeeds=False)
    assert issuer._rewind_locked_read_handle(private, api, handle) is False
    assert handle.position == 57

    api.kernel.SetFilePointerEx = FakeSetFilePointer(offset=1)
    assert issuer._rewind_locked_read_handle(private, api, handle) is False
    assert handle.position == 1


def test_actual_v18_scope_validator_resolves_canonical_root_bridge_module():
    with _integrated_entry() as harness:
        front = harness["front"]
        root_bridge = harness["root_bridge"]
        owner = harness["bundle"].owner
        helper_values = harness["bundle"].helpers
        issuer_name = front._V18_MODULE_NAME
        old_issuer = sys.modules.get(issuer_name)
        owner_name = owner.__name__
        old_owner = sys.modules.get(owner_name)
        issuer = _load_module(issuer_name, ISSUER_PATH)
        issuer.__c01_source_sha256__ = front._V18_SHA256
        owner.__name__ = "backtrader_runtime._c01_native_td_read_v7_owner"
        sys.modules[owner.__name__] = owner
        bundle = front.VerifiedC01V18SourceBundle(
            ROOT,
            issuer,
            owner,
            helper_values,
            _factory=front._BUNDLE_FACTORY,
        )
        try:
            with root_bridge.c01_root_invocation_scope(
                front,
                bundle,
                harness["projection"],
                harness["certification"],
                harness["custody"],
            ) as scope:
                assert scope.bridge is harness["projection"]
                assert getattr(scope.bridge, "_C01RootInvocationScope", None) is None
                root, validated_owner, validated_helpers = issuer._validate_root_scope(
                    scope, issuer
                )
                assert root == ROOT
                assert validated_owner is owner
                assert validated_helpers is bundle.helpers
                foreign_scope = root_bridge._C01RootInvocationScope(
                    front,
                    bundle,
                    harness["projection"],
                    harness["certification"],
                    harness["custody"],
                    _factory=root_bridge._SCOPE_FACTORY,
                )
                with pytest.raises(issuer._IssuerError):
                    issuer._validate_root_scope(foreign_scope, issuer)
                foreign_scope.active = False
        finally:
            bundle._active = False
            if old_issuer is None:
                sys.modules.pop(issuer_name, None)
            else:
                sys.modules[issuer_name] = old_issuer
            if old_owner is None:
                sys.modules.pop(owner.__name__, None)
            else:
                sys.modules[owner_name] = old_owner
            owner.__name__ = owner_name


def test_real_custody_hook_identity_matches_entry_and_bridge_pins():
    custody_name = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
    bridge_name = "backtrader_runtime.certification_simnow_c01_root_v16"
    entry_name = "backtrader_runtime.certification_simnow_c01_root_entry_v18"
    missing = object()
    saved = {
        name: sys.modules.get(name, missing)
        for name in (custody_name, bridge_name, entry_name)
    }
    try:
        custody = _load_module(custody_name, CUSTODY_PATH)
        custody.__c01_source_sha256__ = _sha256(CUSTODY_PATH)
        bridge = _load_module(bridge_name, ROOT_BRIDGE_PATH)
        bridge.__c01_source_sha256__ = _sha256(ROOT_BRIDGE_PATH)
        entry = _load_module(entry_name, ENTRY_PATH)
        entry.__c01_source_sha256__ = _sha256(ENTRY_PATH)

        custody_relative = CUSTODY_PATH.relative_to(ROOT).as_posix()
        bridge_relative = ROOT_BRIDGE_PATH.relative_to(ROOT).as_posix()
        hook = custody.prepare_candidate_custody
        assert custody.__name__ == custody_name
        assert Path(custody.__file__).resolve() == CUSTODY_PATH.resolve()
        assert custody.__c01_source_sha256__ == _sha256(CUSTODY_PATH)
        assert (
            entry._EXACT_PUBLIC_SOURCE_PINS[custody_relative]
            == custody.__c01_source_sha256__
        )
        assert bridge._ROOT_CUSTODY_MODULE_SHA256 == custody.__c01_source_sha256__
        assert (
            entry._EXACT_PUBLIC_SOURCE_PINS[bridge_relative]
            == _sha256(ROOT_BRIDGE_PATH)
        )
        assert hook.__module__ == custody_name
        assert hook.__qualname__ == "prepare_candidate_custody"
        assert hook.__globals__ is custody.__dict__
        assert hook.__code__.co_filename == str(CUSTODY_PATH)

        issuer_text = ISSUER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(issuer_text)
        candidate = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_run_candidate"
        )
        candidate_text = ast.get_source_segment(issuer_text, candidate)
        assert 'root_custody.__name__' in candidate_text
        assert 'getattr(prepare, "__globals__", None)' in candidate_text
        assert 'prepare(' in candidate_text
    finally:
        for name, previous in saved.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_v18_candidate_hook_is_inside_the_original_exitstack_after_validation():
    tree = ast.parse(ISSUER_PATH.read_text(encoding="utf-8"))
    candidate = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_candidate"
    )
    stack = next(
        node
        for node in ast.walk(candidate)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "ExitStack"
            for item in node.items
        )
    )
    contract_validation = next(
        node
        for node in ast.walk(candidate)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "validate_c01_candidate"
    )
    custody_prepare = next(
        node
        for node in ast.walk(candidate)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "prepare"
    )
    assert stack.lineno < contract_validation.lineno < custody_prepare.lineno
    assert custody_prepare.end_lineno <= stack.end_lineno
    scope_checks = ast.get_source_segment(
        ISSUER_PATH.read_text(encoding="utf-8"),
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_validate_root_scope"
        ),
    )
    assert "scope_module_name" in scope_checks
    assert "current_nonce() is not root_scope.nonce" in scope_checks
