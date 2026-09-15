"""Every split execution file remains bound to a signed local test receipt."""

import copy

import pytest

from examples.strategy_candidate_approval import (
    DemoApprovalVerificationError,
    canonical_sha256,
)

from tests.integration.test_cross_exchange_demo_contract import (
    RUNNERS,
    _approval_artifact,
    _verify,
)

SPLIT_LABELS = [
    "backtrader.cerebro",
    "backtrader._cerebro",
    "backtrader._cerebro.registry",
    "backtrader._cerebro.notifications",
    "backtrader._cerebro.lifecycle",
    "backtrader._cerebro.channel",
    "backtrader._cerebro.execution",
    "backtrader._cerebro.runnext",
    "backtrader._cerebro.runonce",
    "backtrader._cerebro.presentation",
]


@pytest.mark.parametrize("label", SPLIT_LABELS)
@pytest.mark.parametrize("mutation", ["changed", "missing"])
def test_split_file_change_or_omission_rejects_previous_signed_receipt(tmp_path, label, mutation):
    runner = RUNNERS[0]
    artifact = _approval_artifact(runner, tmp_path)
    _verify(runner, artifact)
    changed = copy.deepcopy(artifact["runtime_source"])
    for field in ("runtime_files", "source_files"):
        assert label in changed[field]
        if mutation == "missing":
            del changed[field][label]
        else:
            changed[field][label] = "8" * 64
    changed["fingerprint_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "fingerprint_sha256"}
    )
    artifact["runtime_source"] = changed
    with pytest.raises(DemoApprovalVerificationError):
        _verify(runner, artifact)
