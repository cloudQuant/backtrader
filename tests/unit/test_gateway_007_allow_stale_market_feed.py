"""007 Gateway runner accepts the allow_stale_market_feed opt-in (bool only).

The flag defaults to False at feed level and per contract; a contract entry
overrides the feed default (the same precedence as event_time_max_age), and a
non-boolean value fails the whole configuration as FEED_CONFIG_INVALID.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples/live/007_ctp'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runner = _module('gateway_007_allow_stale_runner', EXAMPLE / 'gateway_client_runner.py')


def sample():
    templates = [
        path for path in sorted(EXAMPLE.glob('*_gateway/config.yaml'))
    ]
    assert templates, 'no gateway template config found'
    return runner.load_config(templates[0])


def test_default_config_has_no_stale_flag_and_still_validates():
    config = sample()
    runner.validate_config(config)
    assert 'allow_stale_market_feed' not in config.get('feed', {})
    for row in config['contracts'].values():
        assert 'allow_stale_market_feed' not in row


def test_feed_level_bool_is_accepted():
    config = sample()
    config['feed']['allow_stale_market_feed'] = True
    runner.validate_config(config)
    config['feed']['allow_stale_market_feed'] = False
    runner.validate_config(config)


def test_contract_level_bool_overrides_feed_default():
    config = sample()
    symbol = config['symbols'][0]
    config['contracts'][symbol]['allow_stale_market_feed'] = True
    runner.validate_config(config)


@pytest.mark.parametrize('value', ['yes', 1, None, [], {}])
def test_non_bool_values_are_rejected(value):
    config = sample()
    config['feed']['allow_stale_market_feed'] = value
    with pytest.raises(ValueError, match='FEED_CONFIG_INVALID'):
        runner.validate_config(config)
    contract_config = sample()
    symbol = config['symbols'][0]
    contract_config['contracts'][symbol]['allow_stale_market_feed'] = value
    with pytest.raises(ValueError, match='FEED_CONFIG_INVALID'):
        runner.validate_config(contract_config)


def test_options_merge_prefers_contract_over_feed():
    """The runner's feed options keep the flag from the feed default and let
    a contract entry override it, mirroring event_time_max_age."""
    config = sample()
    symbol = config['symbols'][0]
    config['feed']['allow_stale_market_feed'] = False
    config['contracts'][symbol]['allow_stale_market_feed'] = True
    feed_defaults = dict(config['feed'])
    options = dict(feed_defaults)
    for key in ('event_time_max_age', 'receive_time_max_age', 'incomplete_volume_bars',
                'allow_stale_market_feed'):
        if key in config['contracts'][symbol]:
            options[key] = config['contracts'][symbol][key]
    assert options['allow_stale_market_feed'] is True
