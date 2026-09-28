"""Reviewed Iteration 41 runtime registrations.

This is deliberately a short, code-owned inventory.  It does not scan the
current directory, environment, templates, or user configuration.  Adding a
runtime here is a reviewable change that binds one canonical directory,
strategy identity, preset allow-list, and parameter allow-list.
"""

from __future__ import annotations

from pathlib import Path

from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from .policy import MANAGED_WRITE_CAPABILITIES
from .registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    RuntimeSet,
    UnavailableModeProfile,
)


SOURCE_ROOT = Path(__file__).resolve().parent.parent
# The two packaged L2 fixtures are deliberately distinct from the source
# example registrations below. They include only secret-free, replay-only
# fake-provider artifacts needed by an isolated consumer test; they are never
# an installation route for the wider examples tree.
PACKAGE_L2_FIXTURE_ROOT = Path(__file__).resolve().parent / "_iteration41_l2_fixture"
PACKAGE_BACKTEST_FIXTURE_ROOT = Path(__file__).resolve().parent / "_iteration41_backtest_fixture"

# These are import-source allow-lists, not capability grants.  They bind the
# top-level SDK packages that a reviewed runner may load after its config and
# policy seals have passed.  ``config.yaml`` cannot add a module here.
_REPLAY_CAPABILITY_MODULES = (
    "bt_api_py",
    "bt_api_base",
    "bt_api_binance",
    "bt_api_okx",
    "bt_api_ctp",
)
_MANAGED_REPLAY_CAPABILITY_MODULES = (
    "bt_api_py",
    "bt_api_base",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
)
ITERATION41_012_1_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "012_1_midfreq_cross_exchange" / "runtime"
)
ITERATION41_012_1_STRATEGY_ID = "example.012_1.midfreq_cross_exchange"
ITERATION41_012_2_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "012_2_event_driven_cross_exchange" / "runtime"
)
ITERATION41_012_2_STRATEGY_ID = "example.012_2.event_driven_cross_exchange"
ITERATION41_013_1_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "013_1_midfreq_cross_arbitrage" / "runtime"
)
ITERATION41_013_1_STRATEGY_ID = "example.013_1.midfreq_cross_arbitrage"
ITERATION41_013_2_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "013_2_highfreq_calendar_arbitrage" / "runtime"
)
ITERATION41_013_2_STRATEGY_ID = "example.013_2.highfreq_calendar_arbitrage"
ITERATION41_013_3_RUNTIME_DIR = SOURCE_ROOT / "examples" / "013_3_sa_midfreq_simnow" / "runtime"
ITERATION41_013_3_STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "013_3_sa_midfreq_simnow" / "runtime-ctp-private"
)
ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID = "example.013_3.sa_midfreq_simnow.ctp_private"
ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "013_3_sa_midfreq_simnow" / "runtime-managed-replay"
)
ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID = "example.013_3.sa_midfreq_simnow.managed_replay_l2"
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "ctp_options_simnow_managed_replay_runtime"
)
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID = (
    "example.ctp_options_simnow.mechanical_managed_replay_l2"
)
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID = (
    "example.ctp_options_simnow.mechanical_managed_replay_l2"
)
ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_RUNTIME_DIR = (
    PACKAGE_L2_FIXTURE_ROOT / "runtimes" / "managed_013_3"
)
ITERATION41_PACKAGE_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR = (
    PACKAGE_L2_FIXTURE_ROOT / "runtimes" / "mechanical_p1b"
)
ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_DIR = (
    PACKAGE_BACKTEST_FIXTURE_ROOT / "runtimes" / "local_backtest"
)
ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID = "backtrader.iteration41.local_backtest_fixture"
ITERATION41_014_1_RUNTIME_DIR = SOURCE_ROOT / "examples" / "014_1_ctp_options_lowfreq" / "runtime"
ITERATION41_014_1_STRATEGY_ID = "example.014_1.ctp_options_lowfreq"
ITERATION41_014_2_RUNTIME_DIR = SOURCE_ROOT / "examples" / "014_2_ctp_options_midfreq" / "runtime"
ITERATION41_014_2_STRATEGY_ID = "example.014_2.ctp_options_midfreq"
ITERATION41_015_RUNTIME_DIR = SOURCE_ROOT / "examples" / "015_ctp_options_highfreq" / "runtime"
ITERATION41_015_STRATEGY_ID = "example.015.ctp_options_highfreq"
ITERATION41_SAMPLE_RUNTIME_DIR = SOURCE_ROOT / "examples" / "sample" / "runtime"
ITERATION41_SAMPLE_STRATEGY_ID = "example.sample.ctp_legacy"
ITERATION41_007_CTP_RUNTIME_DIR = SOURCE_ROOT / "examples" / "007_ctp" / "runtime"
ITERATION41_007_CTP_STRATEGY_ID = "example.007_ctp.legacy_direct"
ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR = (
    SOURCE_ROOT
    / "examples"
    / "007_ctp"
    / "live_certification"
    / "simnow_penetration"
)
ITERATION41_007_CTP_PRIVATE_RUNTIME_ID = "example.007_ctp.simnow_penetration.ctp_private"
ITERATION41_007_CTP_PRIVATE_STRATEGY_ID = "example.007_ctp.simnow_penetration"
ITERATION41_010_LIVE_EXAMPLES_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "010_live_examples" / "runtime"
)
ITERATION41_010_LIVE_EXAMPLES_STRATEGY_ID = "example.010_live_examples.simnow_legacy"
ITERATION41_010_OKX_SHADOW_RUNTIME_DIR = (
    SOURCE_ROOT / "examples" / "010_live_examples" / "runtime-okx-shadow"
)
ITERATION41_010_OKX_SHADOW_STRATEGY_ID = "example.010_live_examples.okx_public_shadow"


ITERATION41_012_1_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_012_1_RUNTIME_DIR,
    strategy_id=ITERATION41_012_1_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.012_1_midfreq_cross_exchange.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_012_2_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_012_2_RUNTIME_DIR,
    strategy_id=ITERATION41_012_2_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.012_2_event_driven_cross_exchange.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_013_1_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_013_1_RUNTIME_DIR,
    strategy_id=ITERATION41_013_1_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.013_1_midfreq_cross_arbitrage.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_013_2_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_013_2_RUNTIME_DIR,
    strategy_id=ITERATION41_013_2_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.013_2_highfreq_calendar_arbitrage.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_013_3_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_013_3_RUNTIME_DIR,
    strategy_id=ITERATION41_013_3_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.013_3_sa_midfreq_simnow.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    strategy_id=ITERATION41_013_3_STRATEGY_ID,
    runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    allowed_presets=(),
    sandbox_write_policy="deny",
    unavailable_mode_profiles=(
        UnavailableModeProfile(
            mode="live",
            preset="managed_live_direct",
            reason="managed_live_direct_profile_unavailable",
        ),
    ),
    profiles=(
        RuntimeProfile(
            mode="simulation",
            preset="sandbox",
            allowed_parameter_keys=(),
            allowed_secrets_refs=("config_yaml",),
            available_capabilities=(),
            approval_receipt_digest=None,
            runner_module=None,
            runner_entrypoint="run_runtime",
            capability_modules=(),
            offline_managed_execution=False,
            sandbox_write_policy="deny",
        ),
    ),
)
ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING = CtpSimNowConfigReadOnlyBinding(
    runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
)
ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR,
    strategy_id=ITERATION41_007_CTP_PRIVATE_STRATEGY_ID,
    runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
    allowed_presets=(),
    allowed_parameter_keys=(),
    allowed_secrets_refs=("none",),
    available_capabilities=(),
    capability_modules=(),
    offline_managed_execution=False,
    runner_module=None,
    runner_entrypoint="run_runtime",
    sandbox_write_policy="deny",
    unavailable_mode_profiles=(
        UnavailableModeProfile(
            mode="live",
            preset="managed_live_direct",
            reason="managed_live_direct_profile_unavailable",
        ),
    ),
    profiles=(
        RuntimeProfile(
            mode="simulation",
            preset="sandbox",
            allowed_parameter_keys=(),
            allowed_secrets_refs=("config_yaml",),
            available_capabilities=(),
            approval_receipt_digest=None,
            runner_module=None,
            runner_entrypoint="run_runtime",
            capability_modules=(),
            offline_managed_execution=False,
            sandbox_write_policy="deny",
        ),
    ),
)
ITERATION41_007_CTP_PRIVATE_READONLY_BINDING = CtpSimNowConfigReadOnlyBinding(
    runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
)
ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_DIR,
    strategy_id=ITERATION41_013_3_STRATEGY_ID,
    runtime_id=ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
    allowed_presets=("replay",),
    available_capabilities=MANAGED_WRITE_CAPABILITIES,
    offline_managed_execution=True,
    runner_module="examples.013_3_sa_midfreq_simnow.run_managed_replay_runtime",
    capability_modules=_MANAGED_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR,
    strategy_id=ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID,
    runtime_id=ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    allowed_presets=("replay",),
    available_capabilities=MANAGED_WRITE_CAPABILITIES,
    offline_managed_execution=True,
    runner_module="examples.ctp_options_simnow_managed_replay_runtime",
    capability_modules=_MANAGED_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_RUNTIME_DIR,
    strategy_id=ITERATION41_013_3_STRATEGY_ID,
    runtime_id=ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
    allowed_presets=("replay",),
    available_capabilities=MANAGED_WRITE_CAPABILITIES,
    offline_managed_execution=True,
    runner_module="backtrader_runtime._iteration41_l2_fixture.managed_013_3",
    capability_modules=_MANAGED_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_PACKAGE_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_PACKAGE_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_DIR,
    strategy_id=ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID,
    runtime_id=ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    allowed_presets=("replay",),
    available_capabilities=MANAGED_WRITE_CAPABILITIES,
    offline_managed_execution=True,
    runner_module="backtrader_runtime._iteration41_l2_fixture.mechanical_p1b",
    capability_modules=_MANAGED_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_PACKAGE_LOCAL_BACKTEST_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_DIR,
    strategy_id=ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID,
    allowed_presets=("local_backtest",),
    runner_module="backtrader_runtime._iteration41_backtest_fixture.run",
)
ITERATION41_014_1_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_014_1_RUNTIME_DIR,
    strategy_id=ITERATION41_014_1_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.014_1_ctp_options_lowfreq.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_014_2_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_014_2_RUNTIME_DIR,
    strategy_id=ITERATION41_014_2_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.014_2_ctp_options_midfreq.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_015_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_015_RUNTIME_DIR,
    strategy_id=ITERATION41_015_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.015_ctp_options_highfreq.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_SAMPLE_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_SAMPLE_RUNTIME_DIR,
    strategy_id=ITERATION41_SAMPLE_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.sample",
)
ITERATION41_007_CTP_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_007_CTP_RUNTIME_DIR,
    strategy_id=ITERATION41_007_CTP_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.007_ctp.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_010_LIVE_EXAMPLES_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_010_LIVE_EXAMPLES_RUNTIME_DIR,
    strategy_id=ITERATION41_010_LIVE_EXAMPLES_STRATEGY_ID,
    allowed_presets=("replay",),
    allowed_parameter_keys=("scenario",),
    runner_module="examples.010_live_examples.run_runtime",
    capability_modules=_REPLAY_CAPABILITY_MODULES,
)
ITERATION41_010_OKX_SHADOW_REGISTRATION = RegisteredRuntime(
    runtime_dir=ITERATION41_010_OKX_SHADOW_RUNTIME_DIR,
    strategy_id=ITERATION41_010_OKX_SHADOW_STRATEGY_ID,
    allowed_presets=("shadow",),
    allowed_parameter_keys=("symbols", "duration_seconds", "orderbook_limit"),
    runner_module="examples.010_live_examples.run_okx_shadow_runtime",
    bootstrap_parameters=(
        ("symbols", ("BTC/USDT:USDT", "ETH/USDT:USDT")),
        ("duration_seconds", 10),
        ("orderbook_limit", 5),
    ),
)


ITERATION41_REPLAY_RUNTIME_SET = RuntimeSet(
    name="iteration41-replay",
    runtime_ids=(
        ITERATION41_012_1_STRATEGY_ID,
        ITERATION41_012_2_STRATEGY_ID,
        ITERATION41_013_1_STRATEGY_ID,
        ITERATION41_013_2_STRATEGY_ID,
        ITERATION41_013_3_STRATEGY_ID,
        ITERATION41_014_1_STRATEGY_ID,
        ITERATION41_014_2_STRATEGY_ID,
        ITERATION41_015_STRATEGY_ID,
        ITERATION41_SAMPLE_STRATEGY_ID,
        ITERATION41_007_CTP_STRATEGY_ID,
        ITERATION41_010_LIVE_EXAMPLES_STRATEGY_ID,
    ),
)
ITERATION41_MANAGED_REPLAY_RUNTIME_SET = RuntimeSet(
    name="iteration41-managed-replay-l2",
    runtime_ids=(
        ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
        ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    ),
)
ITERATION41_PACKAGE_L2_FIXTURE_RUNTIME_SET = RuntimeSet(
    name="iteration41-l2-wheel-fixture",
    runtime_ids=(
        ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
        ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
    ),
)
ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_SET = RuntimeSet(
    name="iteration41-local-backtest",
    runtime_ids=(ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID,),
)


def iteration41_runtime_registry() -> RuntimeRegistry:
    """Return the only reviewed runtime registry shipped in this phase."""

    return RuntimeRegistry(
        (
            ITERATION41_012_1_REGISTRATION,
            ITERATION41_012_2_REGISTRATION,
            ITERATION41_013_1_REGISTRATION,
            ITERATION41_013_2_REGISTRATION,
            ITERATION41_013_3_REGISTRATION,
            ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
            ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
            ITERATION41_013_3_MANAGED_REPLAY_REGISTRATION,
            ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
            ITERATION41_014_1_REGISTRATION,
            ITERATION41_014_2_REGISTRATION,
            ITERATION41_015_REGISTRATION,
            ITERATION41_SAMPLE_REGISTRATION,
            ITERATION41_007_CTP_REGISTRATION,
            ITERATION41_010_LIVE_EXAMPLES_REGISTRATION,
            ITERATION41_010_OKX_SHADOW_REGISTRATION,
            ITERATION41_PACKAGE_LOCAL_BACKTEST_REGISTRATION,
        ),
        runtime_sets=(
            ITERATION41_REPLAY_RUNTIME_SET,
            ITERATION41_MANAGED_REPLAY_RUNTIME_SET,
            ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_SET,
        ),
        ctp_simnow_readonly_bindings=(
            ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
            ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
        ),
        registry_id="backtrader.iteration41",
    )


def iteration41_l2_fixture_registry() -> RuntimeRegistry:
    """Return only the two package-owned offline L2 fixture registrations.

    This registry is intentionally not a filtered view of the normal source
    inventory.  It makes the wheel-consumer surface explicit and cannot imply
    that the remaining eleven source examples are packaged or runnable after
    installation.
    """

    return RuntimeRegistry(
        (
            ITERATION41_PACKAGE_013_3_MANAGED_REPLAY_REGISTRATION,
            ITERATION41_PACKAGE_CTP_MECHANICAL_MANAGED_REPLAY_REGISTRATION,
        ),
        runtime_sets=(ITERATION41_PACKAGE_L2_FIXTURE_RUNTIME_SET,),
        registry_id="backtrader.iteration41.l2-wheel-fixture",
    )


def iteration41_backtest_fixture_registry() -> RuntimeRegistry:
    """Return the one package-owned, zero-I/O local-backtest fixture."""

    return RuntimeRegistry(
        (ITERATION41_PACKAGE_LOCAL_BACKTEST_REGISTRATION,),
        runtime_sets=(ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_SET,),
        registry_id="backtrader.iteration41.local-backtest-fixture",
    )
