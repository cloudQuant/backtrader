"""Offline checks of the public 007 Gateway templates, without service evidence."""

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from bt_api_py.gateway_strategy_config import (
    GatewayStrategyConfigError,
    parse_gateway_strategy_config,
)


EXAMPLES = Path(__file__).resolve().parents[2] / "examples/live/007_ctp"
TEMPLATES = sorted(EXAMPLES.glob("*_gateway/config.yaml"))


def test_all_eleven_templates_are_present():
    assert len(TEMPLATES) == 11


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda path: path.parent.name)
def test_selected_risk_config_and_offline_runner(path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tree = raw["gateway_strategy"]
    parsed = parse_gateway_strategy_config(tree)
    risk = parsed.risk_selection
    assert risk is not None
    assert risk.route.scope == parsed.route.scope
    assert risk.route.identity.actor_ref == parsed.route.identity.actor_ref
    assert risk.peer.actor_ref == risk.route.service_id
    assert risk.security_profile_ref != "security"
    assert set(raw["gateway_resource_files"]) == {"security", risk.security_profile_ref}
    operations = set(tree["requested_operations"])
    assert not operations & {"direct.reserve", "direct.dispatch"}
    assert {"direct.delegated_command_status", "direct.delegated_cancel",
            "direct.delegated_cancel_status"} <= operations

    for forbidden in ("direct.reserve", "direct.dispatch"):
        invalid = copy.deepcopy(tree)
        invalid["requested_operations"].append(forbidden)
        with pytest.raises(GatewayStrategyConfigError):
            parse_gateway_strategy_config(invalid)

    result = subprocess.run(
        [sys.executable, str(path.parent / "run.py"), "--config", str(path), "--dry-run"],
        cwd=EXAMPLES.parents[2], capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["status"] == "PASS"
    assert report["mode"] == "offline_config_validation"
