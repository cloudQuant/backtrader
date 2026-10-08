from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import types

import pytest


PACKET = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[8]
CAPSULE_PATH = PACKET / "root-prelaunch-cleanup-capsule.py"
WRAPPER_PATH = (
    PACKET
    / "reference"
    / "r4b-driver-source"
    / "reference"
    / "v18-activation-r5"
    / "public-source"
    / "root_activation_wrapper_r2.py"
)
R4B_DRIVER_PATH = (
    PACKET
    / "reference"
    / "r4b-driver-source"
    / "root-actual-driver.py"
)


def _load_capsule():
    spec = importlib.util.spec_from_file_location("_cleanup_capsule_test", CAPSULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


capsule = _load_capsule()


def _fake_runtime_binding(*, close_success=True):
    module_name = "_cleanup_capsule_fake_driver"
    module = types.ModuleType(module_name)
    source = b'''\
def run_root_activation():
    return None
def activate_with_held_sources():
    return None
def invoke_fixed_wrapper_main():
    return None
def verify_held_source_map():
    return None
def _expected_absolute_pins():
    return None
def _expected_full_held_map():
    return None
def _load_module():
    return None
class HeldSourceLease:
    def verify_held(self):
        return True
    def postverify_and_close(self, *, cuv2_path, cuv2_sha256):
        self.calls += 1
        self.exit_started = True
        self.closed = True
        self.postverify_complete = self.close_success
        return self.close_success
    def keepalive(self, activation_module=None):
        return (self, activation_module)
'''
    codes = capsule._compiled_codes(source, "fake-r4b-driver.py")
    for name in capsule._DRIVER_FUNCTIONS:
        module.__dict__[name] = types.FunctionType(codes[name], module.__dict__, name)
    methods = {
        name: types.FunctionType(codes[f"HeldSourceLease.{name}"], module.__dict__, name)
        for name in capsule._LEASE_METHODS
    }
    lease_class = type("HeldSourceLease", (), {"__module__": module_name, **methods})
    module.HeldSourceLease = lease_class
    lease = lease_class()
    lease.entered = True
    lease.closed = False
    lease.exit_started = False
    lease.postverify_complete = False
    lease.close_success = close_success
    lease.calls = 0
    binding = capsule._capture_runtime_driver_binding(module, lease, codes)
    return module, lease, codes, binding


def _enable_full_fake_recheck(monkeypatch, cap):
    monkeypatch.setattr(
        capsule,
        "_driver_binding",
        lambda _driver: (cap._driver_path, cap._driver_raw, cap._driver_codes),
    )
    monkeypatch.setattr(capsule, "_check_wrapper_module", lambda *_args: None)
    monkeypatch.setattr(capsule, "CUV2_SHA256", capsule._sha(cap._lease.cuv2_raw))
    cap._use_full_precheck = True


def _valid_result():
    profile = {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": "C01_NATIVE_TD_READ_V18",
        "profile": "C01_NATIVE_TD_READ_V18",
        "reason": "admission_namespace_not_fresh",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": None,
        "receipt_verified": False,
        "source_closure_verified": False,
        "root_postverify_verified": False,
        "request_count": 0,
        "query_callback_count": 0,
        "snapshot_count": 0,
        "write_invocation_count": 0,
        "outer_job_empty": False,
        "stdout_eof": False,
        "stderr_eof": False,
        "stderr_empty": False,
        "job_handles_closed": False,
        "reader_threads_joined": False,
        "cleanup_verified": False,
    }
    return {
        "schema": "iteration41.simnow.v18.root_actual_driver.public_result.r4b",
        "classification": "ROOT_PROFILE_RESULT_NOT_OFFICIAL_C01_ACCEPTANCE",
        "profile_result": profile,
        "independent_review_verified": True,
        "root_readback_verified": True,
        "intended_public_source_count": 31,
        "intended_software_pin_count": 2,
        "intended_held_file_count": 33,
        "cuv2_scope_entered": True,
        "held_source_map_verified": True,
        "observed_public_source_count": 31,
        "observed_software_pin_count": 2,
        "observed_held_file_count": 33,
        "wrapper_call_count": 1,
        "wrapper_projection_verified": True,
        "outer_cuv2_postverify_verified": False,
        "outer_cuv2_scope_closed": False,
        "writes": 0,
        "official_c01_pass_count": 0,
        "formal_c01_pass": False,
        "private_capture_read_by_driver": False,
        "opaque_receipt_seen_by_driver": False,
        "late_private_capture_read": False,
    }


def test_frozen_public_sources_bind_r4b_driver_and_r5_wrapper():
    assert capsule._sha(R4B_DRIVER_PATH.read_bytes()) == capsule.DRIVER_SHA256
    assert capsule._sha(WRAPPER_PATH.read_bytes()) == capsule.WRAPPER_SHA256
    codes, _tree = capsule._wrapper_static_gate(WRAPPER_PATH.read_bytes(), str(WRAPPER_PATH))
    assert "main" in codes
    assert "_run_core" in codes
    assert "_ProductionPorts.activation_namespace_lease" in codes
    assert "_ProductionPorts.run_fixed_cli" in codes


@pytest.mark.parametrize("method_name", ("verify_held", "postverify_and_close", "keepalive"))
def test_preexisting_lease_method_shadows_are_rejected(method_name):
    module, lease, codes, _binding = _fake_runtime_binding()
    setattr(lease, method_name, lambda *args, **kwargs: True)
    with pytest.raises(capsule.CleanupBlocked, match="lease_method_shadow_invalid"):
        capsule._capture_runtime_driver_binding(module, lease, codes)


def test_r5_pins_are_exactly_31_public_plus_2_software_rows():
    driver = types.ModuleType("fake_driver")
    driver.ROOT = ROOT
    driver.PACKET_DIR = PACKET / "reference" / "r4b-driver-source"
    driver.V18_PINS_SHA256 = capsule.V18_PINS_SHA256
    driver.WRAPPER_SHA256 = capsule.WRAPPER_SHA256
    driver.WRAPPER_RELATIVE = capsule.WRAPPER_RELATIVE
    expected, raw = capsule._expected_map(driver)
    assert capsule._sha(raw) == capsule.V18_PINS_SHA256
    assert len(expected) == 33
    assert sum(path.startswith(capsule._path_key(str(ROOT))) for path in expected) == 31
    assert sum(path.startswith(capsule._path_key("C:/")) for path in expected) == 2


def test_held_map_checks_exact_key_set_and_every_source_hash():
    raw_a = b"public source a"
    raw_b = b"software source b"
    expected = {
        capsule._path_key("D:/source/a.py"): ("D:/source/a.py", capsule._sha(raw_a)),
        capsule._path_key("C:/runtime/b.dll"): ("C:/runtime/b.dll", capsule._sha(raw_b)),
    }
    lease = types.SimpleNamespace(held={"D:/source/a.py": raw_a, "C:/runtime/b.dll": raw_b})
    assert capsule._held_map(lease, expected) == {
        capsule._path_key("D:/source/a.py"): raw_a,
        capsule._path_key("C:/runtime/b.dll"): raw_b,
    }
    lease.held["D:/source/a.py"] = b"changed source"
    with pytest.raises(capsule.CleanupBlocked, match="held_map_hash_invalid"):
        capsule._held_map(lease, expected)
    lease.held = {"D:/source/a.py": raw_a}
    with pytest.raises(capsule.CleanupBlocked, match="held_map_keys_invalid"):
        capsule._held_map(lease, expected)


def test_namespace_freshness_reason_is_a_unique_pre_yield_gate_before_fixed_cli():
    raw = WRAPPER_PATH.read_bytes()
    capsule._wrapper_static_gate(raw, str(WRAPPER_PATH))
    changed = raw.replace(
        b'raise RootActivationError("admission_namespace_not_fresh")',
        b'raise RootActivationError("different_reason")',
        1,
    )
    with pytest.raises(capsule.CleanupBlocked, match="wrapper_source_pin_mismatch"):
        capsule._wrapper_static_gate(changed, str(WRAPPER_PATH))


def test_exact_result_contract_does_not_treat_zero_fields_as_prelaunch_proof():
    result = _valid_result()
    assert capsule._exact_projection(result)
    altered_reason = _valid_result()
    altered_reason["profile_result"]["reason"] = "root_entry_blocked"
    assert not capsule._exact_projection(altered_reason)
    boolean_count = _valid_result()
    boolean_count["profile_result"]["request_count"] = False
    assert not capsule._exact_projection(boolean_count)
    extra_field = _valid_result()
    extra_field["provider_identity"] = "must-not-exist"
    assert not capsule._exact_projection(extra_field)


def test_only_a_builtin_empty_retained_list_is_accepted_and_same_identity_is_required():
    activation = types.ModuleType("fake_activation")
    activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS = []
    observed = capsule._require_empty_retained_list(activation)
    assert observed is activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS
    assert capsule._require_empty_retained_list(activation, observed) is observed

    class EqualEmpty:
        def __eq__(self, other):
            return other == []

    impostor = EqualEmpty()
    assert impostor == []
    activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS = impostor
    with pytest.raises(capsule.CleanupBlocked, match="wrapper_job_refs_not_empty_list"):
        capsule._require_empty_retained_list(activation, observed)


def test_retained_lease_tuple_is_bound_by_identity_and_exclusive_membership():
    activation = types.ModuleType("fake_activation")
    activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS = []

    class Lease:
        pass

    driver = types.ModuleType("fake_driver")
    driver.HeldSourceLease = Lease
    driver.ACTIVATION = activation
    manager = object()
    private = object()
    cli = object()
    held = object()
    expected = object()
    cuv2_raw = b"public source"
    lease = Lease()
    lease.manager = manager
    lease.private_module = private
    lease.cli_module = cli
    lease.held = held
    lease.expected = expected
    lease.cuv2_raw = cuv2_raw
    lease.references = [activation]
    holder = (lease, manager, private, cli, held, expected, cuv2_raw, activation, activation)
    driver.KEEPALIVE = [holder]
    found_lease, found_holder, found_list = capsule._find_retained(driver, activation)
    assert found_lease is lease and found_holder is holder and found_list is activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS
    driver.KEEPALIVE.append(tuple(holder))
    with pytest.raises(capsule.CleanupBlocked, match="retained_lease_membership_invalid"):
        capsule._find_retained(driver, activation)


def test_close_receipt_removal_requires_normal_close_and_exact_holder_identity():
    holder = (object(),)
    keepalive = [holder]
    assert not capsule._remove_exact_closed_holder(
        keepalive,
        holder,
        normal_exit_verified=False,
        postverify_verified=True,
    )
    assert keepalive == [holder]
    equal_but_distinct = tuple([holder[0]])
    assert equal_but_distinct == holder and equal_but_distinct is not holder
    assert not capsule._remove_exact_closed_holder(
        keepalive,
        equal_but_distinct,
        normal_exit_verified=True,
        postverify_verified=True,
    )
    assert keepalive == [holder]
    assert capsule._remove_exact_closed_holder(
        keepalive,
        holder,
        normal_exit_verified=True,
        postverify_verified=True,
    )
    assert keepalive == []
    class EmptyList(list):
        pass

    assert not capsule._remove_exact_closed_holder(
        EmptyList([holder]),
        holder,
        normal_exit_verified=True,
        postverify_verified=True,
    )


def _state_machine_capsule(*, close_success: bool):
    activation = types.ModuleType("fake_activation")
    activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS = []
    raw_a = b"public source a"
    raw_b = b"software source b"
    raw_c = b"fake wrapper source"
    expected = {
        capsule._path_key("D:/source/a.py"): ("D:/source/a.py", capsule._sha(raw_a)),
        capsule._path_key("C:/runtime/b.dll"): ("C:/runtime/b.dll", capsule._sha(raw_b)),
        capsule._path_key("D:/source/wrapper.py"): ("D:/source/wrapper.py", capsule._sha(raw_c)),
    }

    driver, lease, codes, runtime_binding = _fake_runtime_binding(close_success=close_success)
    lease.cuv2_raw = b"fake pinned custody source"
    lease.held = {
        "D:/source/a.py": raw_a,
        "C:/runtime/b.dll": raw_b,
        "D:/source/wrapper.py": raw_c,
    }
    lease.expected = expected
    lease.references = [activation]
    lease.manager = object()
    lease.private_module = object()
    lease.cli_module = object()
    holder = (
        lease,
        lease.manager,
        lease.private_module,
        lease.cli_module,
        lease.held,
        expected,
        lease.cuv2_raw,
        activation,
        activation,
    )
    driver.KEEPALIVE = [holder]
    driver.ACTIVATION = activation
    driver.CUV2_PATH = "fake-public-cuv2-source"
    driver.CUV2_SHA256 = "fake-public-cuv2-sha"
    result = _valid_result()

    class PreverifiedCapsule(capsule.RootPrelaunchCleanupCapsule):
        def _recheck_before_close(self):
            if getattr(self, "_use_full_precheck", False):
                return capsule.RootPrelaunchCleanupCapsule._recheck_before_close(self)
            # Isolate the postverify/remove one-use state machine.  Production
            # construction performs full source/origin checks.  Keep the
            # mutable callable/class identity checks live in this fake path.
            return capsule._recheck_runtime_driver_binding(
                self._driver,
                self._lease,
                self._driver_codes,
                self._runtime_binding,
            )

    cap = object.__new__(PreverifiedCapsule)
    cap._driver = driver
    cap._activation = activation
    cap._lease = lease
    cap._holder = holder
    cap._unresolved_list = activation._ROOT_RETAINED_UNRESOLVED_JOB_REFS
    cap._result = result
    cap._result_bytes = capsule._canonical_result(result)
    cap._expected_map = dict(expected)
    cap._wrapper_raw = raw_c
    cap._wrapper_path = Path("D:/source/wrapper.py")
    cap._driver_path = Path("D:/source/driver.py")
    cap._driver_raw = b"fake driver source"
    cap._driver_codes = codes
    cap._runtime_binding = runtime_binding
    cap._keepalive_list = driver.KEEPALIVE
    cap._owner_pid = os.getpid()
    cap._owner_thread = __import__("threading").get_ident()
    cap._used = False
    cap._issued_id = id(lease)
    capsule._ISSUED_LEASE_IDS.add(id(lease))
    return cap, lease, holder, result


def test_one_use_capsule_removes_only_after_normal_fake_postverify_close():
    cap, lease, holder, result = _state_machine_capsule(close_success=True)
    receipt = cap.cleanup_once()
    assert receipt.classification == "PRELAUNCH_NAMESPACE_BLOCK_CLEANED"
    assert receipt.prelaunch_namespace_proven is True
    assert receipt.full_held_map_verified is True
    assert receipt.normal_cuv2_close_verified is True
    assert receipt.exact_retained_tuple_removed is True
    assert receipt.schema == "iteration41.simnow.v18.root_prelaunch_cleanup_receipt.r3"
    assert receipt.official_c01_pass_count == 0
    assert result["formal_c01_pass"] is False
    assert result["official_c01_pass_count"] == 0
    assert lease.calls == 1
    assert cap._driver is None
    assert cap.cleanup_once().reason == "cleanup_capsule_already_used"


def test_failed_fake_postverify_close_keeps_exact_holder_and_cannot_retry():
    cap, lease, holder, _result = _state_machine_capsule(close_success=False)
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert cap._driver.KEEPALIVE == [holder]
    assert lease.calls == 1
    assert cap.cleanup_once().reason == "cleanup_capsule_already_used"
    assert lease.calls == 1


def test_instance_shadow_after_prepare_blocks_without_close_or_holder_removal():
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    lease.postverify_and_close = lambda **_kwargs: True
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "lease_method_shadow_invalid"
    assert lease.calls == 0
    assert cap._driver.KEEPALIVE == [holder]


def test_class_method_replacement_after_prepare_blocks_without_close_or_holder_removal():
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    lease_class = type(lease)
    original = lease_class.__dict__["postverify_and_close"]
    replacement = types.FunctionType(original.__code__, original.__globals__, original.__name__)
    try:
        lease_class.postverify_and_close = replacement
        receipt = cap.cleanup_once()
    finally:
        lease_class.postverify_and_close = original
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "lease_callable_identity_changed"
    assert lease.calls == 0
    assert cap._driver.KEEPALIVE == [holder]


def test_keepalive_container_replacement_after_prepare_blocks_before_close(monkeypatch):
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    _enable_full_fake_recheck(monkeypatch, cap)
    original_list = cap._keepalive_list
    replacement_list = [holder]
    cap._driver.KEEPALIVE = replacement_list
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "driver_keepalive_identity_changed"
    assert lease.calls == 0
    assert original_list == [holder]
    assert replacement_list == [holder]
    assert cap._holder is holder


def test_keepalive_member_removal_after_prepare_blocks_before_close(monkeypatch):
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    _enable_full_fake_recheck(monkeypatch, cap)
    cap._keepalive_list.clear()
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "retained_tuple_membership_changed"
    assert lease.calls == 0
    assert cap._holder is holder
    assert cap._lease is lease


def test_lease_expected_map_mutation_after_prepare_blocks_before_close(monkeypatch):
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    _enable_full_fake_recheck(monkeypatch, cap)
    lease.expected.clear()
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "lease_expected_map_changed"
    assert lease.calls == 0
    assert cap._holder is holder
    assert cap._expected_map


@pytest.mark.parametrize(
    ("attribute", "value"),
    (
        ("entered", False),
        ("closed", True),
        ("exit_started", True),
        ("postverify_complete", True),
    ),
)
def test_mutable_lease_lifecycle_state_after_prepare_blocks_before_close(monkeypatch, attribute, value):
    cap, lease, holder, _result = _state_machine_capsule(close_success=True)
    _enable_full_fake_recheck(monkeypatch, cap)
    setattr(lease, attribute, value)
    receipt = cap.cleanup_once()
    assert receipt.classification == "CLEANUP_BLOCKED_REFERENCES_RETAINED"
    assert receipt.reason == "lease_not_open_uncertain"
    assert lease.calls == 0
    assert cap._holder is holder


def test_wrapper_runtime_functions_are_bound_to_frozen_code_without_calling_them():
    raw = WRAPPER_PATH.read_bytes()
    codes, _tree = capsule._wrapper_static_gate(raw, str(WRAPPER_PATH))
    name = capsule.WRAPPER_MODULE_NAME
    module = types.ModuleType(name)
    module.__file__ = str(WRAPPER_PATH)
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(WRAPPER_PATH))
    module.CASE_ID = "C01"
    module.PROFILE_ID = "C01_NATIVE_TD_READ_V18"
    module.main = types.FunctionType(codes["main"], module.__dict__, "main")
    module._run_core = types.FunctionType(codes["_run_core"], module.__dict__, "_run_core")
    module._run_production = types.FunctionType(codes["_run_production"], module.__dict__, "_run_production")
    module._public_blocked = types.FunctionType(codes["_public_blocked"], module.__dict__, "_public_blocked")
    error_type = type("RootActivationError", (RuntimeError,), {"__module__": name})

    def _cell_for(value):
        def capture():
            return value

        return capture.__closure__[0]

    error_cell = _cell_for(error_type)
    error_type.__init__ = types.FunctionType(
        codes["RootActivationError.__init__"],
        module.__dict__,
        "__init__",
        closure=(error_cell,),
    )
    module.RootActivationError = error_type
    ports_init = types.FunctionType(
        codes["_ProductionPorts.__init__"], module.__dict__, "__init__"
    )
    namespace_generator = types.FunctionType(
        codes["_ProductionPorts.activation_namespace_lease"],
        module.__dict__,
        "activation_namespace_lease",
    )
    run_fixed_cli = types.FunctionType(
        codes["_ProductionPorts.run_fixed_cli"],
        module.__dict__,
        "run_fixed_cli",
    )
    from contextlib import contextmanager

    ports = type(
        "_ProductionPorts",
        (),
        {
            "__module__": name,
            "__init__": ports_init,
            "activation_namespace_lease": contextmanager(namespace_generator),
            "run_fixed_cli": run_fixed_cli,
        },
    )
    module._ProductionPorts = ports
    sys.modules[name] = module
    try:
        assert capsule._function_matches(module.main, module, codes, "main"), (
            module.main.__module__,
            module.main.__globals__ is module.__dict__,
            module.main.__code__.co_filename,
            codes["main"].co_filename,
            module.main.__code__.co_qualname,
        )
        capsule._check_wrapper_module(module, WRAPPER_PATH, raw)
        wrong = compile("def wrong():\n    return None\n", str(WRAPPER_PATH), "exec", dont_inherit=True)
        wrong_code = next(item for item in wrong.co_consts if isinstance(item, types.CodeType))
        module.main = types.FunctionType(wrong_code, module.__dict__, "main")
        with pytest.raises(capsule.CleanupBlocked, match="wrapper_main_code_identity_invalid"):
            capsule._check_wrapper_module(module, WRAPPER_PATH, raw)
    finally:
        sys.modules.pop(name, None)

