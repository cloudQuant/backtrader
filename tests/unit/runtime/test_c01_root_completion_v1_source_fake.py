"""Source-fake checks for the C01 Root formal completion seam."""

from __future__ import annotations

import hashlib
from pathlib import Path
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
COMPLETION_PATH = (
    ROOT / "examples/000_live_certification/simnow_penetration/common/c01_root_completion_v1.py"
)
ADJUDICATOR_PATH = (
    ROOT / "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py"
)


def _load_exact_module(name: str, path: Path) -> types.ModuleType:
    raw = path.read_bytes()
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    module.__c01_source_sha256__ = hashlib.sha256(raw).hexdigest()
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _captured_objects(module: types.ModuleType) -> dict[str, object]:
    from types import FunctionType

    rows: dict[str, object] = {}
    for name, value in module.__dict__.items():
        if name.startswith("__"):
            continue
        rows[name] = value
        if type(value) is FunctionType:
            rows[name + ".__code__"] = value.__code__
    return rows


def _load_completion() -> types.ModuleType:
    return _load_exact_module("common.c01_root_completion_v1", COMPLETION_PATH)


def test_result_constructor_requires_private_factory() -> None:
    module = _load_completion()
    values = {
        name: None for name in module.C01FormalCompletionResult.__slots__ if name != "_factory"
    }
    with pytest.raises(module.C01RootCompletionError, match="formal_result_factory_required"):
        module.C01FormalCompletionResult(values=values)


def test_source_fake_adjudicator_cannot_mint_formal_result() -> None:
    completion = _load_completion()
    adjudicator = _load_exact_module(
        "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1",
        ADJUDICATOR_PATH,
    )
    proof = object.__new__(adjudicator.C01RootFormalPassProof)
    object.__setattr__(proof, "_factory", adjudicator._FACTORY)
    object.__setattr__(proof, "_used", False)
    with pytest.raises(completion.C01RootCompletionError, match="formal_proof_consumption_failed"):
        completion.consume_c01_root_formal_pass(
            proof,
            adjudicator_module=adjudicator,
            adjudicator_source_objects=_captured_objects(adjudicator),
        )


def test_caller_shapes_and_counts_are_not_a_proof() -> None:
    completion = _load_completion()
    fake_adjudicator = types.ModuleType(
        "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"
    )
    fake_adjudicator.__file__ = str(ADJUDICATOR_PATH)
    fake_adjudicator.__c01_source_sha256__ = "a" * 64
    projection = {
        "case_id": "C01",
        "certification": "PASS",
        "request_count": 8,
        "query_callback_count": 6,
        "snapshot_count": 2,
    }
    with pytest.raises(completion.C01RootCompletionError, match="adjudicator_source_invalid"):
        completion.consume_c01_root_formal_pass(
            projection,
            adjudicator_module=fake_adjudicator,
            adjudicator_source_objects={},
        )


def test_adjudicator_replay_fails_closed() -> None:
    adjudicator = _load_exact_module(
        "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1",
        ADJUDICATOR_PATH,
    )
    proof = object.__new__(adjudicator.C01RootFormalPassProof)
    object.__setattr__(proof, "_factory", adjudicator._FACTORY)
    object.__setattr__(proof, "_used", True)
    with pytest.raises(
        adjudicator.C01RootFormalAdjudicationError,
        match="formal_proof_invalid_or_replayed",
    ):
        adjudicator.consume_c01_root_formal_pass_proof(proof)


def test_completion_resolves_full_root_source_object_snapshot() -> None:
    completion = _load_completion()
    adjudicator = _load_exact_module(
        "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1",
        ADJUDICATOR_PATH,
    )
    from types import FunctionType

    rows: dict[str, object] = {"__module_object__": adjudicator}
    for name, value in tuple(adjudicator.__dict__.items()):
        if name.startswith("__"):
            continue
        rows[name] = value
        if type(value) is FunctionType:
            rows[name + ".__code__"] = value.__code__
            rows[name + ".__globals__"] = value.__globals__
        elif type(value) is type and value.__module__ == adjudicator.__name__:
            for attribute, member in tuple(value.__dict__.items()):
                key = name + "." + attribute
                rows[key] = member
                if type(member) is FunctionType:
                    rows[key + ".__code__"] = member.__code__
                    rows[key + ".__globals__"] = member.__globals__
                elif isinstance(member, (classmethod, staticmethod)):
                    function = member.__func__
                    rows[key + ".__func__"] = function
                    rows[key + ".__code__"] = function.__code__
                    rows[key + ".__globals__"] = function.__globals__
                elif isinstance(member, property):
                    for accessor in ("fget", "fset", "fdel"):
                        function = getattr(member, accessor)
                        if type(function) is FunctionType:
                            accessor_key = key + "." + accessor
                            rows[accessor_key] = function
                            rows[accessor_key + ".__code__"] = function.__code__
                            rows[accessor_key + ".__globals__"] = function.__globals__

    for name, expected in rows.items():
        assert completion._resolve_adjudicator_object(adjudicator, name) is expected
