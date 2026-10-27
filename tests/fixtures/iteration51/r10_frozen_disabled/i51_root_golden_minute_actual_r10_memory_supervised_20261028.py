import ctypes
import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
import uuid
import warnings
import subprocess
import stat
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXAMPLE = Path('D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute')
STRATEGY_MODULE_KEY = 'alpha003_strategy'
STRATEGY_MODULE_PATH = EXAMPLE / 'alpha003_strategy.py'
CONSUMER = Path('D:\\temp\\i51-final-source-consumer-20261027-r3\\consumer\\Lib\\site-packages')
PROFILE = Path('D:\\source_code\\backtrader\\.codex-tmp\\i51_golden_fullpool_profile_r9_20261028.json')
WRITE_OBSERVER = Path('D:\\source_code\\backtrader\\.codex-tmp\\i51_root_readonly_write_observation_20261027.py')
SPAN_HELPER = Path('D:\\source_code\\backtrader\\.codex-tmp\\i51_root_golden_minute_span_r4_20261027.py')
POSTFLIGHT_HELPER = Path('D:\\source_code\\backtrader\\.codex-tmp\\i51_fullpool_golden_postflight_r9_20261027.py')
SAVED_TAPE_VALIDATOR = Path('D:\\source_code\\backtrader\\scripts\\validate_iteration51_saved_factor_tape.py')
RUN_ROOT = Path('D:/temp/i51-golden-minute-readonly-20261028-r9-fullpool')
PRIVATE_TEMP = Path('D:/temp/i51-root-golden-private-20261028-r9-fullpool')
OUTPUT = Path('D:/temp/i51-root-golden-minute-readonly-20261028-r9-fullpool.json')
BT_RECORD = CONSUMER / 'back_trader_python-1.4.0.dist-info/RECORD'
BT_RECORD_SHA = '5975a32820cbfab85145ffd865f805199dac082f3d7f9c66976e234607c4e14f'
SDK_RECORD = CONSUMER / 'bt_api_ctp-2.0.4+iteration41.i9.dist-info/RECORD'
SDK_RECORD_SHA = 'cb2c2f3501a447ab34c403f35e2a000e53d9c6ba04b88b822a23682d54b9006a'
ROOT_STATE = {}

DRAFT_UNEXECUTABLE = True
R10_SUPERVISOR_ENABLED = False
R9_SOURCE = Path('D:\\source_code\\backtrader\\.codex-tmp\\i51_root_golden_minute_actual_r9_qualified_650947ea_20261028.py')
R9_SOURCE_SHA = '18d3e29beac450abaefa0ddb1c750ae6bf120ba9a6b9fa87d6bd89d3351cbb36'
MEMORY_OBSERVER = Path('D:\\source_code\\backtrader\\scripts\\observe_iteration51_process_memory.py')
MEMORY_OBSERVER_SHA = 'a3943f00862fb34b0557578102c24b69908f4d5a2d7acb8f0ebee8932090b080'
MEMORY_CONTROL = None
MEMORY_TARGET_IDENTITY = None
MEMORY_RUN_ID = None
MEMORY_LIVE_READY_RECORD = None
MEMORY_LIVE_NEXT_RECORD = None
EXPECTED_DEV_HEAD = 'ROOT_MUST_BIND_AFTER_FINAL_DEV_HEAD'
# Root must externally attest actual HEAD, index/dirty state, public inputs and
# installed RECORDs before binding this draft. This field is a required label,
# not a self-check of Git state.
PUBLIC_RUNNER_ERROR_CODES = frozenset(('ALLOW_WRITE_REQUIRES_LIVE_MODE', 'ALPHA003_STRATEGY_API_PENDING', 'AUTHORIZED_PRODUCTS_INVALID', 'AUTHORIZED_PRODUCTS_OUTSIDE_POOL', 'COHORT_CTP_TRADING_DAY_OPTION_INVALID', 'COHORT_EPOCH_INVALID', 'COHORT_HAS_NO_PLANNED_SLOTS', 'COHORT_MEMBER_SESSION_API_REQUIRED', 'COHORT_TRADING_DAY_INVALID', 'CONFIG_FIELDS_INVALID', 'CONFIG_FILE_UNAVAILABLE', 'CONFIG_MODE_INVALID', 'CONFIG_SCHEMA_UNSUPPORTED', 'CONFIG_SECTION_FIELDS_INVALID', 'CONFIG_YAML_INVALID', 'CTP_FUTURES_PRODUCT_POOL_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_BRIDGE_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED', 'CTP_FUTURES_SNAPSHOT_ID_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_TYPE_INVALID', 'CTP_FUTURES_TRADING_DAY_UNAVAILABLE', 'CTP_QUERY_PLAN_BUILD_FAILED', 'CTP_QUERY_SELECTION_NOT_CONFIGURED', 'DAILY_EPOCH_RETIREMENT_UNPROVEN', 'DAILY_ROLLOVER_CLOSE_ALL_POLICY_REQUIRED', 'DAILY_ROLLOVER_LIVE_MODE_REQUIRED', 'DAILY_ROLLOVER_LIVE_TIER_REQUIRED', 'DAILY_SELECTION_AUTHORIZED_POOL_CHANGED', 'DAILY_SELECTION_BUNDLES_INVALID', 'DAILY_SELECTION_BUNDLE_DUPLICATE', 'DAILY_SELECTION_DECISION_TIME_NOT_ADVANCED', 'DAILY_SELECTION_EXCHANGE_SET_CHANGED', 'DAILY_SELECTION_POLICY_CHANGED', 'DAILY_SELECTION_PRODUCT_POOL_CHANGED', 'DAILY_SELECTION_TRADING_DAY_NOT_ADVANCED', 'DAILY_SELECTION_TRADING_DAY_SET_CHANGED', 'DECISION_TAPE_BATCH_SNAPSHOT_MISMATCH', 'DECISION_TAPE_BYTE_BUDGET_EXCEEDED', 'DECISION_TAPE_BYTE_BUDGET_INVALID', 'DECISION_TAPE_CLOSE_FAILED', 'DECISION_TAPE_CREATE_FAILED', 'DECISION_TAPE_FACTOR_SNAPSHOT_INVALID', 'DECISION_TAPE_FACTOR_TARGET_SET_INVALID', 'DECISION_TAPE_GRID_COVERAGE_MISMATCH', 'DECISION_TAPE_HEADER_BINDING_MISMATCH', 'DECISION_TAPE_HEADER_BINDING_REQUIRED', 'DECISION_TAPE_HEADER_INVALID', 'DECISION_TAPE_HEADER_MISSING', 'DECISION_TAPE_MEMBER_SET_INVALID', 'DECISION_TAPE_MODE_INVALID', 'DECISION_TAPE_PROFILE_REQUIRED', 'DECISION_TAPE_RAW_FIELDS_INVALID', 'DECISION_TAPE_READBACK_MISMATCH', 'DECISION_TAPE_READ_FAILED', 'DECISION_TAPE_RECEIPT_INVALID', 'DECISION_TAPE_RECORD_HASH_INVALID', 'DECISION_TAPE_RECORD_INVALID', 'DECISION_TAPE_SELECTION_EVIDENCE_MISMATCH', 'DECISION_TAPE_TARGETS_INVALID', 'DECISION_TAPE_UNAVAILABLE', 'DECISION_TAPE_VALUE_INVALID', 'DECISION_TAPE_WRITE_FAILED', 'ENTRY_TIER_ESCALATION_DENIED', 'ENTRY_TIER_INVALID', 'FACTOR_DIRECTION_INVALID', 'FACTOR_MODE_INVALID', 'FACTOR_WINDOW_INVALID', 'FINCORE_FLAG_INVALID', 'GOLDEN_AUTHORIZED_TARGETS_EMPTY', 'GOLDEN_TARGETS_COUNT_INVALID', 'GOLDEN_TARGETS_DUPLICATE', 'GOLDEN_TARGETS_EMPTY', 'GOLDEN_TARGETS_FULL_SELECTION_INVALID', 'GOLDEN_TARGETS_FULL_SELECTION_NOT_READY', 'GOLDEN_TARGETS_GRID_BUILD_FAILED', 'GOLDEN_TARGETS_GRID_UNAVAILABLE', 'GOLDEN_TARGETS_INVALID', 'GOLDEN_TARGETS_LIVE_CTP_QUERY_REQUIRED', 'GOLDEN_TARGETS_OUTSIDE_SELECTED_POOL', 'GOLDEN_TARGETS_QUERY_PLAN_REQUIRED', 'GOLDEN_TARGETS_READ_ONLY_REQUIRED', 'GOLDEN_TARGETS_WRITE_CONFIGURATION_UNSUPPORTED', 'INPUT_DATE_INVALID', 'INPUT_DECIMAL_INVALID', 'INPUT_FIELDS_INVALID', 'INPUT_FILE_UNAVAILABLE', 'INPUT_JSON_INVALID', 'INPUT_NUMBER_INVALID', 'INPUT_OBJECT_REQUIRED', 'INPUT_PATH_REQUIRED', 'INPUT_TEXT_INVALID', 'INPUT_TIMESTAMP_INVALID', 'INPUT_TIMESTAMP_NAIVE', 'LIVE_ARM_TEMPLATES_INVALID', 'LIVE_ARM_TEMPLATE_DUPLICATE', 'LIVE_ARM_TEMPLATE_FIELDS_INVALID', 'LIVE_ARM_TEMPLATE_ROUTE_SET_MISMATCH', 'LIVE_ARM_TEMPLATE_TARGET_NOT_AUTHORIZED', 'LIVE_BAR_AGE_PROFILE_REQUIRED', 'LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING', 'LIVE_COHORT_WAKE_API_UNAVAILABLE', 'LIVE_CORE_WINDDOWN_NOT_CONFIRMED', 'LIVE_CTP_READ_ONLY_STATE_UNAVAILABLE', 'LIVE_CTP_SESSION_NOT_READY', 'LIVE_CTP_STORE_UNAVAILABLE_FOR_FACTOR_SOURCE', 'LIVE_CTP_TRADING_DAY_UNAVAILABLE_FOR_FACTOR_SOURCE', 'LIVE_CTP_TRADING_STATE_UNAVAILABLE', 'LIVE_DATED_TRADE_RECONCILIATION_BLOCKED', 'LIVE_DATED_TRADE_RECONCILIATION_PAGE_INVALID', 'LIVE_EXECUTION_TARGETS_INVALID', 'LIVE_FEE_BUDGET_REQUIRED', 'LIVE_GRID_HAS_NO_REMAINING_COMMON_MINUTES', 'LIVE_HISTORY_AVAILABILITY_INVALID', 'LIVE_HISTORY_BATCH_ID_INVALID', 'LIVE_HISTORY_EPOCH_INVALID', 'LIVE_HISTORY_FRESH_SELECTION_REQUIRED', 'LIVE_HISTORY_GENERATION_CHANGED', 'LIVE_HISTORY_GRID_WINDOW_UNAVAILABLE', 'LIVE_HISTORY_HEADER_MISMATCH', 'LIVE_HISTORY_IDENTITY_INVALID', 'LIVE_HISTORY_IDENTITY_MISMATCH', 'LIVE_HISTORY_IDENTITY_REQUIRED', 'LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH', 'LIVE_HISTORY_JOURNAL_HIGHWATER_MISMATCH', 'LIVE_HISTORY_LIVE_MODE_REQUIRED', 'LIVE_HISTORY_MEMBER_INVALID', 'LIVE_HISTORY_MEMBER_SET_INVALID', 'LIVE_HISTORY_MODE_MISMATCH', 'LIVE_HISTORY_OHLCV_INVALID', 'LIVE_HISTORY_ORDER_INVALID', 'LIVE_HISTORY_OUTSIDE_CURRENT_GRID', 'LIVE_HISTORY_PATH_CONFLICT', 'LIVE_HISTORY_RECORDS_MISSING', 'LIVE_HISTORY_RECORD_IDENTITY_INVALID', 'LIVE_HISTORY_SELECTION_EVIDENCE_INVALID', 'LIVE_HISTORY_SELECTION_MISMATCH', 'LIVE_HISTORY_SELECTION_UNSUPPORTED', 'LIVE_HISTORY_SEQUENCE_INVALID', 'LIVE_HISTORY_SESSION_CHANGED', 'LIVE_HISTORY_SLOT_IDENTITY_INVALID', 'LIVE_HISTORY_SLOT_SEQUENCE_INVALID', 'LIVE_HISTORY_SOURCE_ROLE_INVALID', 'LIVE_HISTORY_SOURCE_ROLE_ORDER_INVALID', 'LIVE_HISTORY_TAIL_NOT_LIVE', 'LIVE_HISTORY_WARMUP_INVALID', 'LIVE_HISTORY_WARMUP_NOT_CONTIGUOUS', 'LIVE_HISTORY_WARMUP_NOT_READY', 'LIVE_INITIAL_QUERY_REFRESH_FAILED', 'LIVE_INITIAL_QUERY_REFRESH_INCOMPLETE', 'LIVE_QUERY_REFRESH_DID_NOT_JOIN', 'LIVE_RECONCILIATION_BLOCKED', 'LIVE_RECONCILIATION_LIMIT_EXCEEDED', 'LIVE_RECONCILIATION_PAGE_INVALID', 'LIVE_RECOVERY_INTENT_SNAPSHOT_INVALID', 'LIVE_RECOVERY_INTENT_SNAPSHOT_UNAVAILABLE', 'LIVE_REFRESH_TARGETS_INVALID', 'LIVE_REFRESH_TARGETS_REQUIRED', 'LIVE_RESOURCE_CLEANUP_INCOMPLETE', 'LIVE_RISK_BUDGETS_REQUIRED', 'LIVE_SECTION_INVALID', 'LIVE_SELECTION_PLAN_REQUIRED', 'LIVE_SESSION_CHANGED_DURING_FACTOR_SOURCE_BINDING', 'LIVE_SESSION_CHANGED_DURING_SELECTION', 'LIVE_SHUTDOWN_NOT_CONFIRMED', 'LIVE_SHUTDOWN_SIGNAL_HANDLER_UNAVAILABLE', 'LIVE_STORE_CONFIG_ENV_INVALID', 'LIVE_STORE_CONFIG_ENV_MISSING', 'LIVE_STORE_CONFIG_FIELDS_INVALID', 'LIVE_STORE_CONFIG_INJECTION_DENIED', 'LIVE_STORE_CONFIG_OVERRIDE_REQUIRES_LIVE_MODE', 'LIVE_STRATEGY_BINDING_CONFLICT', 'LIVE_STRATEGY_POST_JOIN_RETIREMENT_NOT_CONFIRMED', 'LIVE_STRATEGY_SHUTDOWN_NOT_CONFIRMED', 'LIVE_TARGET_CAPACITY_EXCEEDED', 'LIVE_TIER_REQUIRED', 'LIVE_TRADE_RECONCILIATION_BLOCKED', 'LIVE_WRITE_FLAG_INVALID', 'LIVE_WRITE_GRANT_MISSING_IN_CONFIG', 'LIVE_ZERO_LOGIN_RESPONSE_READ_ONLY', 'LIVE_WRITE_TIER_REQUIRED', 'MINUTE_BAR_AVAILABILITY_INVALID', 'MINUTE_BAR_CLOCK_PROFILE_MISMATCH', 'MINUTE_BAR_FIELDS_INVALID', 'MINUTE_BAR_GENERATION_INVALID', 'MINUTE_BAR_ID_DUPLICATE', 'MINUTE_BAR_INCOMPLETE', 'MINUTE_BAR_NOT_PRESENT', 'MINUTE_BAR_OHLC_INVALID', 'MINUTE_BAR_OUTSIDE_PLANNED_GRID', 'MINUTE_BAR_PLANNED_MEMBER_MISSING', 'MINUTE_BAR_PRICE_INVALID', 'MINUTE_BAR_QUALITY_BLOCKED', 'MINUTE_BAR_ROUTE_MISMATCH', 'MINUTE_BAR_SEQUENCE_INVALID', 'MINUTE_BAR_SEQUENCE_NOT_INCREASING', 'MINUTE_BAR_SESSION_MISMATCH', 'MINUTE_BAR_TARGET_OUTSIDE_POOL', 'MINUTE_BAR_TIMESTAMP_MISMATCH', 'MINUTE_TAPE_BARS_REQUIRED', 'MINUTE_TAPE_FIELDS_INVALID', 'MINUTE_TAPE_PRICE_BASIS_MISMATCH', 'MINUTE_TAPE_PRICE_BASIS_UNSPECIFIED', 'MINUTE_TAPE_SCHEMA_UNSUPPORTED', 'MINUTE_TAPE_SOURCE_ORDER_INVALID', 'MINUTE_TAPE_TIMEZONE_MISMATCH', 'OFFLINE_MODE_REQUIRES_SAVED_SELECTION_BUNDLE', 'PLANNED_GRID_DUPLICATE_CLOSE', 'PLANNED_GRID_RECORD_INVALID', 'PLANNED_MINUTE_GRID_BLOCKED', 'POINT_IN_TIME_ROUTE_SET_MISMATCH', 'POINT_IN_TIME_SELECTION_BLOCKED', 'POINT_IN_TIME_TRADING_DAY_SET_MISMATCH', 'QUERY_SELECTION_DAILY_BUNDLES_UNSUPPORTED', 'QUERY_SELECTION_LIVE_TIER_REQUIRED', 'QUOTE_AVAILABILITY_INVALID', 'QUOTE_CROSSED', 'QUOTE_FIELDS_INVALID', 'QUOTE_ID_DUPLICATE', 'QUOTE_ROUTE_MISMATCH', 'QUOTE_TAPE_FIELDS_INVALID', 'QUOTE_TAPE_ROWS_REQUIRED', 'QUOTE_TAPE_SCHEMA_UNSUPPORTED', 'REGISTERED_SIM_STORE_CONTRACT_INVALID', 'REPLAY_INSTRUMENT_FIELDS_INVALID', 'REPLAY_METADATA_AVAILABILITY_MISMATCH', 'REPLAY_METADATA_FIELDS_INVALID', 'REPLAY_METADATA_ROUTE_MISMATCH', 'REPLAY_METADATA_ROWS_INVALID', 'REPLAY_METADATA_SCHEMA_UNSUPPORTED', 'REPLAY_METADATA_TARGET_SET_MISMATCH', 'REPLAY_PERMISSION_INVALID', 'REPLAY_PRICE_LIMITS_INVALID', 'REPLAY_RISK_BUDGETS_REQUIRED', 'REPLAY_TAPE_NOT_FULL_GRID', 'REPLAY_TIER_REQUIRED', 'RESEARCH_ENDPOINTS_OUTSIDE_PLANNED_GRID', 'RESEARCH_ENDPOINTS_REQUIRED', 'RISK_POLICY_INVALID', 'SAVED_SELECTION_BUNDLE_REQUIRED', 'SELECTION_EVIDENCE_AUTHORIZED_TARGETS_INVALID', 'SELECTION_EVIDENCE_BYTE_BUDGET_EXCEEDED', 'SELECTION_EVIDENCE_BYTE_BUDGET_INVALID', 'SELECTION_EVIDENCE_EPOCH_INVALID', 'SELECTION_EVIDENCE_GRID_INVALID', 'SELECTION_EVIDENCE_GRID_UNAVAILABLE', 'SELECTION_EVIDENCE_MANIFEST_UNAVAILABLE', 'SELECTION_EVIDENCE_SERIALIZATION_FAILED', 'SELECTION_MAX_EPOCHS_INVALID', 'SELECTION_SOURCE_INVALID', 'SESSION_CALENDAR_DUPLICATE_EXCHANGE', 'SESSION_CALENDAR_REQUIRED', 'SESSION_CALENDAR_SCHEMA_REQUIRED', 'SESSION_CALENDAR_SET_MISMATCH'))
PUBLIC_RUNNER_ERROR_CODES = PUBLIC_RUNNER_ERROR_CODES | frozenset(('CTP_FUTURES_QUERY_MODE_MISMATCH', 'CTP_FUTURES_QUERY_SET_UNAVAILABLE'))
PUBLIC_RUNNER_ERROR_CODES = PUBLIC_RUNNER_ERROR_CODES | frozenset(('ALLOW_WRITE_REQUIRES_LIVE_MODE', 'ALPHA003_STRATEGY_API_PENDING', 'AUTHORIZED_PRODUCTS_INVALID', 'AUTHORIZED_PRODUCTS_OUTSIDE_POOL', 'COHORT_CALENDAR_OVERRIDE_IDENTITY_INVALID', 'COHORT_CALENDAR_OVERRIDE_INVALID', 'COHORT_CTP_TRADING_DAY_OPTION_INVALID', 'COHORT_EPOCH_INVALID', 'COHORT_HAS_NO_PLANNED_SLOTS', 'COHORT_MEMBER_SESSION_API_REQUIRED', 'COHORT_TRADING_DAY_INVALID', 'CONFIG_FIELDS_INVALID', 'CONFIG_FILE_UNAVAILABLE', 'CONFIG_MODE_INVALID', 'CONFIG_SCHEMA_UNSUPPORTED', 'CONFIG_SECTION_FIELDS_INVALID', 'CONFIG_YAML_INVALID', 'CTP_FUTURES_PRODUCT_POOL_UNAVAILABLE', 'CTP_FUTURES_QUERY_MODE_MISMATCH', 'CTP_FUTURES_QUERY_SET_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_BRIDGE_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED', 'CTP_FUTURES_SNAPSHOT_ID_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_TYPE_INVALID', 'CTP_FUTURES_TRADING_DAY_UNAVAILABLE', 'CTP_QUERY_PLAN_BUILD_FAILED', 'CTP_QUERY_SELECTION_NOT_CONFIGURED', 'DAILY_EPOCH_RETIREMENT_UNPROVEN', 'DAILY_ROLLOVER_CLOSE_ALL_POLICY_REQUIRED', 'DAILY_ROLLOVER_LIVE_MODE_REQUIRED', 'DAILY_ROLLOVER_LIVE_TIER_REQUIRED', 'DAILY_SELECTION_AUTHORIZED_POOL_CHANGED', 'DAILY_SELECTION_BUNDLES_INVALID', 'DAILY_SELECTION_BUNDLE_DUPLICATE', 'DAILY_SELECTION_DECISION_TIME_NOT_ADVANCED', 'DAILY_SELECTION_EXCHANGE_SET_CHANGED', 'DAILY_SELECTION_POLICY_CHANGED', 'DAILY_SELECTION_PRODUCT_POOL_CHANGED', 'DAILY_SELECTION_TRADING_DAY_NOT_ADVANCED', 'DAILY_SELECTION_TRADING_DAY_SET_CHANGED', 'DECISION_TAPE_BATCH_SNAPSHOT_MISMATCH', 'DECISION_TAPE_BYTE_BUDGET_EXCEEDED', 'DECISION_TAPE_BYTE_BUDGET_INVALID', 'DECISION_TAPE_CALENDAR_FINGERPRINT_INVALID', 'DECISION_TAPE_CLOSE_FAILED', 'DECISION_TAPE_CREATE_FAILED', 'DECISION_TAPE_FACTOR_SNAPSHOT_INVALID', 'DECISION_TAPE_FACTOR_TARGET_SET_INVALID', 'DECISION_TAPE_GRID_COVERAGE_MISMATCH', 'DECISION_TAPE_HEADER_BINDING_MISMATCH', 'DECISION_TAPE_HEADER_BINDING_REQUIRED', 'DECISION_TAPE_HEADER_INVALID', 'DECISION_TAPE_HEADER_MISSING', 'DECISION_TAPE_MEMBER_SET_INVALID', 'DECISION_TAPE_MODE_INVALID', 'DECISION_TAPE_PROFILE_REQUIRED', 'DECISION_TAPE_RAW_FIELDS_INVALID', 'DECISION_TAPE_READBACK_MISMATCH', 'DECISION_TAPE_READ_FAILED', 'DECISION_TAPE_RECEIPT_INVALID', 'DECISION_TAPE_RECORD_HASH_INVALID', 'DECISION_TAPE_RECORD_INVALID', 'DECISION_TAPE_SELECTION_EVIDENCE_MISMATCH', 'DECISION_TAPE_TARGETS_INVALID', 'DECISION_TAPE_UNAVAILABLE', 'DECISION_TAPE_VALUE_INVALID', 'DECISION_TAPE_WRITE_FAILED', 'ENTRY_TIER_ESCALATION_DENIED', 'ENTRY_TIER_INVALID', 'FACTOR_DIRECTION_INVALID', 'FACTOR_MODE_INVALID', 'FACTOR_WINDOW_INVALID', 'FINCORE_FLAG_INVALID', 'GOLDEN_AUTHORIZED_TARGETS_EMPTY', 'GOLDEN_TARGETS_COUNT_INVALID', 'GOLDEN_TARGETS_DUPLICATE', 'GOLDEN_TARGETS_EMPTY', 'GOLDEN_TARGETS_FULL_SELECTION_INVALID', 'GOLDEN_TARGETS_FULL_SELECTION_NOT_READY', 'GOLDEN_TARGETS_GRID_BUILD_FAILED', 'GOLDEN_TARGETS_GRID_UNAVAILABLE', 'GOLDEN_TARGETS_INVALID', 'GOLDEN_TARGETS_LIVE_CTP_QUERY_REQUIRED', 'GOLDEN_TARGETS_OUTSIDE_SELECTED_POOL', 'GOLDEN_TARGETS_QUERY_PLAN_REQUIRED', 'GOLDEN_TARGETS_READ_ONLY_REQUIRED', 'GOLDEN_TARGETS_WRITE_CONFIGURATION_UNSUPPORTED', 'INPUT_DATE_INVALID', 'INPUT_DECIMAL_INVALID', 'INPUT_FIELDS_INVALID', 'INPUT_FILE_UNAVAILABLE', 'INPUT_JSON_INVALID', 'INPUT_NUMBER_INVALID', 'INPUT_OBJECT_REQUIRED', 'INPUT_PATH_REQUIRED', 'INPUT_TEXT_INVALID', 'INPUT_TIMESTAMP_INVALID', 'INPUT_TIMESTAMP_NAIVE', 'LIVE_ARM_TEMPLATES_INVALID', 'LIVE_ARM_TEMPLATE_DUPLICATE', 'LIVE_ARM_TEMPLATE_FIELDS_INVALID', 'LIVE_ARM_TEMPLATE_ROUTE_SET_MISMATCH', 'LIVE_ARM_TEMPLATE_TARGET_NOT_AUTHORIZED', 'LIVE_BAR_AGE_PROFILE_REQUIRED', 'LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING', 'LIVE_COHORT_WAKE_API_UNAVAILABLE', 'LIVE_CORE_WINDDOWN_NOT_CONFIRMED', 'LIVE_CTP_READ_ONLY_STATE_UNAVAILABLE', 'LIVE_CTP_SESSION_NOT_READY', 'LIVE_CTP_STORE_UNAVAILABLE_FOR_FACTOR_SOURCE', 'LIVE_CTP_TRADING_DAY_UNAVAILABLE_FOR_FACTOR_SOURCE', 'LIVE_CTP_TRADING_STATE_UNAVAILABLE', 'LIVE_DATED_TRADE_RECONCILIATION_BLOCKED', 'LIVE_DATED_TRADE_RECONCILIATION_PAGE_INVALID', 'LIVE_EXECUTION_TARGETS_INVALID', 'LIVE_FEE_BUDGET_REQUIRED', 'LIVE_GRID_HAS_NO_REMAINING_COMMON_MINUTES', 'LIVE_HISTORY_AVAILABILITY_INVALID', 'LIVE_HISTORY_BATCH_ID_INVALID', 'LIVE_HISTORY_EPOCH_INVALID', 'LIVE_HISTORY_FRESH_SELECTION_REQUIRED', 'LIVE_HISTORY_GENERATION_CHANGED', 'LIVE_HISTORY_GRID_WINDOW_UNAVAILABLE', 'LIVE_HISTORY_HEADER_CALENDAR_FINGERPRINT_INVALID', 'LIVE_HISTORY_HEADER_MISMATCH', 'LIVE_HISTORY_IDENTITY_INVALID', 'LIVE_HISTORY_IDENTITY_MISMATCH', 'LIVE_HISTORY_IDENTITY_REQUIRED', 'LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH', 'LIVE_HISTORY_JOURNAL_HIGHWATER_MISMATCH', 'LIVE_HISTORY_LIVE_MODE_REQUIRED', 'LIVE_HISTORY_MEMBER_INVALID', 'LIVE_HISTORY_MEMBER_SET_INVALID', 'LIVE_HISTORY_MODE_MISMATCH', 'LIVE_HISTORY_OHLCV_INVALID', 'LIVE_HISTORY_ORDER_INVALID', 'LIVE_HISTORY_OUTSIDE_CURRENT_GRID', 'LIVE_HISTORY_PATH_CONFLICT', 'LIVE_HISTORY_RECORDS_MISSING', 'LIVE_HISTORY_RECORD_IDENTITY_INVALID', 'LIVE_HISTORY_RESTART_CALENDAR_ORDER_INVALID', 'LIVE_HISTORY_RESTART_CALENDAR_UNAVAILABLE', 'LIVE_HISTORY_RESTART_GAP_INVALID', 'LIVE_HISTORY_SELECTION_EVIDENCE_INVALID', 'LIVE_HISTORY_SELECTION_MISMATCH', 'LIVE_HISTORY_SELECTION_UNSUPPORTED', 'LIVE_HISTORY_SEQUENCE_INVALID', 'LIVE_HISTORY_SESSION_CHANGED', 'LIVE_HISTORY_SLOT_IDENTITY_INVALID', 'LIVE_HISTORY_SLOT_SEQUENCE_INVALID', 'LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH', 'LIVE_HISTORY_SOURCE_HIGHWATER_MISSING', 'LIVE_HISTORY_SOURCE_JOURNAL_REQUIRED', 'LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH', 'LIVE_HISTORY_SOURCE_ROLE_INVALID', 'LIVE_HISTORY_SOURCE_ROLE_ORDER_INVALID', 'LIVE_HISTORY_TAIL_NOT_RESTORABLE', 'LIVE_HISTORY_TAPE_REQUIRED_FOR_SOURCE_HIGHWATER', 'LIVE_HISTORY_WARMUP_INVALID', 'LIVE_HISTORY_WARMUP_NOT_CONTIGUOUS', 'LIVE_INITIAL_QUERY_REFRESH_FAILED', 'LIVE_INITIAL_QUERY_REFRESH_INCOMPLETE', 'LIVE_LEGACY_SOURCE_HIGHWATER_UNSUPPORTED', 'LIVE_QUERY_REFRESH_DID_NOT_JOIN', 'LIVE_RECONCILIATION_BLOCKED', 'LIVE_RECONCILIATION_LIMIT_EXCEEDED', 'LIVE_RECONCILIATION_PAGE_INVALID', 'LIVE_RECOVERY_INTENT_SNAPSHOT_INVALID', 'LIVE_RECOVERY_INTENT_SNAPSHOT_UNAVAILABLE', 'LIVE_REFRESH_TARGETS_INVALID', 'LIVE_REFRESH_TARGETS_REQUIRED', 'LIVE_RESOURCE_CLEANUP_INCOMPLETE', 'LIVE_RISK_BUDGETS_REQUIRED', 'LIVE_RUN_LOSS_POLICY_INVALID', 'LIVE_RUN_LOSS_POLICY_REQUIRED', 'LIVE_SECTION_INVALID', 'LIVE_SELECTION_PLAN_REQUIRED', 'LIVE_SESSION_CHANGED_DURING_FACTOR_SOURCE_BINDING', 'LIVE_SESSION_CHANGED_DURING_SELECTION', 'LIVE_SHUTDOWN_NOT_CONFIRMED', 'LIVE_SHUTDOWN_SIGNAL_HANDLER_UNAVAILABLE', 'LIVE_SOURCE_CONTINUITY_UNAVAILABLE', 'LIVE_SOURCE_TRADING_DAYS_INVALID', 'LIVE_SOURCE_TRADING_DAYS_UNAVAILABLE', 'LIVE_STORE_CONFIG_ENV_INVALID', 'LIVE_STORE_CONFIG_ENV_MISSING', 'LIVE_STORE_CONFIG_FIELDS_INVALID', 'LIVE_STORE_CONFIG_INJECTION_DENIED', 'LIVE_STORE_CONFIG_OVERRIDE_REQUIRES_LIVE_MODE', 'LIVE_STRATEGY_BINDING_CONFLICT', 'LIVE_STRATEGY_POST_JOIN_RETIREMENT_NOT_CONFIRMED', 'LIVE_STRATEGY_SHUTDOWN_NOT_CONFIRMED', 'LIVE_TARGET_CAPACITY_EXCEEDED', 'LIVE_TIER_REQUIRED', 'LIVE_TRADE_RECONCILIATION_BLOCKED', 'LIVE_WRITE_FLAG_INVALID', 'LIVE_WRITE_GRANT_MISSING_IN_CONFIG', 'LIVE_WRITE_TIER_REQUIRED', 'LIVE_ZERO_LOGIN_RESPONSE_READ_ONLY', 'MINUTE_BAR_AVAILABILITY_INVALID', 'MINUTE_BAR_CLOCK_PROFILE_MISMATCH', 'MINUTE_BAR_FIELDS_INVALID', 'MINUTE_BAR_GENERATION_INVALID', 'MINUTE_BAR_ID_DUPLICATE', 'MINUTE_BAR_INCOMPLETE', 'MINUTE_BAR_NOT_PRESENT', 'MINUTE_BAR_OHLC_INVALID', 'MINUTE_BAR_OUTSIDE_PLANNED_GRID', 'MINUTE_BAR_PLANNED_MEMBER_MISSING', 'MINUTE_BAR_PRICE_INVALID', 'MINUTE_BAR_QUALITY_BLOCKED', 'MINUTE_BAR_ROUTE_MISMATCH', 'MINUTE_BAR_SEQUENCE_INVALID', 'MINUTE_BAR_SEQUENCE_NOT_INCREASING', 'MINUTE_BAR_SESSION_MISMATCH', 'MINUTE_BAR_TARGET_OUTSIDE_POOL', 'MINUTE_BAR_TIMESTAMP_MISMATCH', 'MINUTE_TAPE_BARS_REQUIRED', 'MINUTE_TAPE_FIELDS_INVALID', 'MINUTE_TAPE_PRICE_BASIS_MISMATCH', 'MINUTE_TAPE_PRICE_BASIS_UNSPECIFIED', 'MINUTE_TAPE_SCHEMA_UNSUPPORTED', 'MINUTE_TAPE_SOURCE_ORDER_INVALID', 'MINUTE_TAPE_TIMEZONE_MISMATCH', 'OFFLINE_MODE_REQUIRES_SAVED_SELECTION_BUNDLE', 'PLANNED_GRID_DUPLICATE_CLOSE', 'PLANNED_GRID_RECORD_INVALID', 'PLANNED_MINUTE_GRID_BLOCKED', 'POINT_IN_TIME_ROUTE_SET_MISMATCH', 'POINT_IN_TIME_SELECTION_BLOCKED', 'POINT_IN_TIME_TRADING_DAY_SET_MISMATCH', 'QUERY_SELECTION_DAILY_BUNDLES_UNSUPPORTED', 'QUERY_SELECTION_LIVE_TIER_REQUIRED', 'QUOTE_AVAILABILITY_INVALID', 'QUOTE_CROSSED', 'QUOTE_FIELDS_INVALID', 'QUOTE_ID_DUPLICATE', 'QUOTE_ROUTE_MISMATCH', 'QUOTE_TAPE_FIELDS_INVALID', 'QUOTE_TAPE_ROWS_REQUIRED', 'QUOTE_TAPE_SCHEMA_UNSUPPORTED', 'REGISTERED_SIM_STORE_CONTRACT_INVALID', 'REPLAY_INSTRUMENT_FIELDS_INVALID', 'REPLAY_METADATA_AVAILABILITY_MISMATCH', 'REPLAY_METADATA_FIELDS_INVALID', 'REPLAY_METADATA_ROUTE_MISMATCH', 'REPLAY_METADATA_ROWS_INVALID', 'REPLAY_METADATA_SCHEMA_UNSUPPORTED', 'REPLAY_METADATA_TARGET_SET_MISMATCH', 'REPLAY_PERMISSION_INVALID', 'REPLAY_PRICE_LIMITS_INVALID', 'REPLAY_RISK_BUDGETS_REQUIRED', 'REPLAY_TAPE_NOT_FULL_GRID', 'REPLAY_TIER_REQUIRED', 'RESEARCH_ENDPOINTS_OUTSIDE_PLANNED_GRID', 'RESEARCH_ENDPOINTS_REQUIRED', 'RISK_POLICY_INVALID', 'SAVED_SELECTION_BUNDLE_REQUIRED', 'SELECTION_EVIDENCE_AUTHORIZED_TARGETS_INVALID', 'SELECTION_EVIDENCE_BYTE_BUDGET_EXCEEDED', 'SELECTION_EVIDENCE_BYTE_BUDGET_INVALID', 'SELECTION_EVIDENCE_EPOCH_INVALID', 'SELECTION_EVIDENCE_GRID_INVALID', 'SELECTION_EVIDENCE_GRID_UNAVAILABLE', 'SELECTION_EVIDENCE_MANIFEST_UNAVAILABLE', 'SELECTION_EVIDENCE_SERIALIZATION_FAILED', 'SELECTION_MAX_EPOCHS_INVALID', 'SELECTION_QUERY_MODE_INVALID', 'SELECTION_QUERY_MODE_REQUIRES_CTP_QUERY', 'SELECTION_SOURCE_INVALID', 'SESSION_CALENDAR_DUPLICATE_EXCHANGE', 'SESSION_CALENDAR_REQUIRED', 'SESSION_CALENDAR_SCHEMA_REQUIRED', 'SESSION_CALENDAR_SET_MISMATCH'))
PUBLIC_PINS = {'D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute\\alpha003_strategy.py': '42228f543908b8c2bf61174797d9266ddb859880a7806b236782ef07c803e0e0', 'D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute\\discovery_lifecycle.py': '305ecf7cb89ccf8aee15179312fbf4b311f41ead7e65a97b01e19c0e3ccb3f3d', 'D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute\\entry_tier.py': '230ab3ab1bb94313a186fef2bf181f1e1d80e769cd029832bab1614ea659c15e', 'D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute\\protected_simnow.py': '88fef4e0ed6268dca4399e36e2ed42a7229ca73035c10726beea4856917eca60', 'D:\\source_code\\backtrader\\examples\\unified\\028_alpha003_simnow_minute\\run.py': 'e789ccce322b7ae9f5a050c26c7295e519d5eef286503ff1e800a1a700a4bbd2', 'D:\\source_code\\backtrader\\.codex-tmp\\i51_root_readonly_write_observation_20261027.py': 'cf0c540c68ce23959e4d63d007ab1aae6b526710523b2d4be4cc313d4385ec59', 'D:\\source_code\\backtrader\\.codex-tmp\\i51_golden_minute_profile_r7_20261028.json': '20651d0e1d9abcc7d1bd1762fd6f5d1841f5dc79ee79f56519a8b96298b9172d', 'D:\\source_code\\backtrader\\.codex-tmp\\i51_root_golden_minute_span_r4_20261027.py': '59b475eb6e3bf63c8710e990b0e6d85e7a6767fbe953fd42b25f92d3dd837bb9', 'D:\\source_code\\backtrader\\.codex-tmp\\i51_golden_postflight_r1_20261027.py': 'd11859309e21991e04271c8bb19ad211a420926b33e6972622767b1176b53459', 'D:\\temp\\i51-final-source-consumer-20261027-r3\\consumer\\Lib\\site-packages\\bt_api_ctp\\ctp\\client.py': 'cd020b4ea3496a4e8c357a1fd58a5bba33a94784e65401963c0d605cb77be92b', 'D:\\temp\\i51-final-source-consumer-20261027-r3\\consumer\\Lib\\site-packages\\bt_api_ctp\\md_identity.py': 'f884b734fc719d015a58d351c47f493ef368aab54d5437b83e8dfb000d7a9f35'}


PUBLIC_PINS.update({
    str(R9_SOURCE): R9_SOURCE_SHA,
    str(PROFILE): 'c1da03a96911d85a951f2ac00cd94f1cf1fbe1a8752dd2efa9f22e2b9e7396c9',
    str(MEMORY_OBSERVER): MEMORY_OBSERVER_SHA,
    str(POSTFLIGHT_HELPER): '320e7fd9fc009a73e248d7f2fbbe2e3eb451235ebd641ec10883eeb49712e747',
    str(SAVED_TAPE_VALIDATOR): '7800089b42c54c2902873d69b95a867cc6849599b290fb780fa4756dedf4592d',
})

R10_RUNTIME_DEPENDENCIES = (
    R9_SOURCE,
    PROFILE,
    MEMORY_OBSERVER,
    EXAMPLE / 'entry_tier.py',
    STRATEGY_MODULE_PATH,
    EXAMPLE / 'protected_simnow.py',
    EXAMPLE / 'run.py',
    WRITE_OBSERVER,
    SPAN_HELPER,
    POSTFLIGHT_HELPER,
    SAVED_TAPE_VALIDATOR,
)
MAX_PINNED_SOURCE_BYTES = 8 * 1024 * 1024

READY_NAME = 'target_ready.json'
RELEASE_NAME = 'target_release.json'
START_NAME = 'run_start.json'
LIVE_READY_NAME = 'first_live_ready.json'
LIVE_NEXT_NAME = 'first_live_next.json'
RECEIPT_NAME = 'completion_receipt.json'
SAMPLE_NAME = 'process_rss.jsonl'
TARGET_RESULT_NAME = 'synthetic_target_result.json'
MAX_CONTROL_RECORD_BYTES = 32768
MAX_TARGET_RESULT_BYTES = 8 * 1024 * 1024
READY_TIMEOUT_SECONDS = 60
CHILD_TIMEOUT_SECONDS = 7 * 60 * 60 + 60
TARGET_POSTFLIGHT_CHECKS = frozenset((
    'closed_complete_phase', 'read_only_profile', 'source_pins_unchanged',
    'process_tree_memory_scope_explicit', 'zero_writes_observed',
    'native_cleanup_confirmed', 'timer_joined', 'live_run_complete',
    'full_target_selection', 'full_planned_grid_recorded', 'read_only_mode',
    'normal_resource_cleanup', 'normal_epoch_retirement', 'controlled_stop',
    'strategy_shutdown_proof', 'qualified_fullpool_postflight',
    'three_target_qualified_streak', 'full_run_duration',
    'actual_live_call_window_for_external_sampling',
    'first_full_cohort_source_time_marker_matches_tape',
    'validated_tape_availability_for_external_sampling', 'bounded_tape_identity',
))


def capture_os_clock_pair(*, strictly_after_monotonic_ns=None):
    for _ in range(100):
        before = time.monotonic_ns()
        utc = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        after = time.monotonic_ns()
        midpoint = (before + after) // 2
        if strictly_after_monotonic_ns is None or midpoint > strictly_after_monotonic_ns:
            return utc, midpoint, after - before
        time.sleep(0.001)
    raise RuntimeError('OS_CLOCK_PAIR_MONOTONIC_NOT_ADVANCING')


def parse_os_utc(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError('INVALID_OS_UTC')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError('OS_UTC_REQUIRED')
    return parsed.astimezone(timezone.utc)


def publish_protocol_record(path, payload):
    """Publish a single-use JSON protocol record without replacement."""
    if not path.parent.is_dir() or path.exists() or path.is_symlink():
        raise FileExistsError('PROTOCOL_PATH_NOT_FRESH')
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent
    )
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_path, path)
        temp_path.unlink()
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def read_protocol_record(path):
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or path.is_symlink():
            return None
        if before.st_size < 0 or before.st_size > MAX_CONTROL_RECORD_BYTES:
            return None
        descriptor = os.open(
            str(path), os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        )
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(MAX_CONTROL_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or len(raw) > MAX_CONTROL_RECORD_BYTES
            or opened.st_size != before.st_size
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or (opened.st_ino and before.st_ino and opened.st_ino != before.st_ino)
        ):
            return None
        value = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if type(value) is dict else None


def validate_ready_record(record, *, run_id, root_pid, root_create_time, sampler_pid):
    fields = {
        'schema', 'run_id', 'root_pid', 'root_create_time', 'sampler_pid',
        'sample_utc', 'sample_monotonic_ns', 'sampling_valid',
    }
    if type(record) is not dict or set(record) != fields:
        return False
    try:
        parse_os_utc(record['sample_utc'])
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        type(record['schema']) is int and record['schema'] == 1
        and record['run_id'] == run_id
        and type(record['root_pid']) is int and record['root_pid'] == root_pid
        and type(record['root_create_time']) in (int, float)
        and record['root_create_time'] == root_create_time
        and type(record['sampler_pid']) is int and record['sampler_pid'] == sampler_pid
        and type(record['sample_monotonic_ns']) is int
        and record['sample_monotonic_ns'] > 0
        and record['sampling_valid'] is True
    )


def publish_run_start_record():
    if not isinstance(MEMORY_CONTROL, Path) or type(MEMORY_TARGET_IDENTITY) is not dict:
        raise RuntimeError('MEMORY_TARGET_CONTEXT_MISSING')
    utc, mono_ns, span_ns = capture_os_clock_pair()
    record = {
        'schema': 1,
        'run_id': MEMORY_RUN_ID,
        'root_pid': MEMORY_TARGET_IDENTITY['pid'],
        'root_create_time': MEMORY_TARGET_IDENTITY['create_time'],
        'start_utc': utc,
        'start_monotonic_ns': mono_ns,
        'clock_pair_span_ns': span_ns,
    }
    publish_protocol_record(MEMORY_CONTROL / START_NAME, record)
    return record


def validate_live_ready_record(record, *, run_id, root_pid, root_create_time):
    fields = {
        'schema', 'boundary_id', 'run_id', 'root_pid', 'root_create_time',
        'readiness', 'replay_mode', 'cohort_id', 'epoch_id', 'calendar_id',
        'batch_id', 'slot_index',
        'ready_utc', 'ready_monotonic_ns', 'clock_pair_span_ns',
    }
    if type(record) is not dict or set(record) != fields:
        return False
    try:
        parse_os_utc(record['ready_utc'])
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        type(record['schema']) is int and record['schema'] == 1
        and record['boundary_id'] == f'{run_id}:live-ready'
        and record['run_id'] == run_id
        and type(record['root_pid']) is int and record['root_pid'] == root_pid
        and type(record['root_create_time']) in (int, float)
        and record['root_create_time'] == root_create_time
        and record['readiness'] == 'LIVE_READY'
        and record['replay_mode'] is False
        and type(record['cohort_id']) is str and bool(record['cohort_id'])
        and type(record['epoch_id']) is int and record['epoch_id'] > 0
        and type(record['calendar_id']) is str and bool(record['calendar_id'])
        and type(record['batch_id']) is str and bool(record['batch_id'])
        and type(record['slot_index']) is int and record['slot_index'] >= 0
        and type(record['ready_monotonic_ns']) is int
        and record['ready_monotonic_ns'] > 0
        and type(record['clock_pair_span_ns']) is int
        and 0 <= record['clock_pair_span_ns'] <= 2_000_000_000
    )


def validate_live_next_record(
    record, *, run_id, root_pid, root_create_time, live_ready_record
):
    fields = {
        'schema', 'boundary_id', 'run_id', 'root_pid', 'root_create_time',
        'readiness', 'replay_mode', 'cohort_id', 'epoch_id', 'calendar_id',
        'batch_id', 'slot_index',
        'live_ready_boundary_id', 'next_utc', 'next_monotonic_ns',
        'clock_pair_span_ns',
    }
    if type(record) is not dict or set(record) != fields:
        return False
    if not validate_live_ready_record(
        live_ready_record,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=root_create_time,
    ):
        return False
    try:
        parse_os_utc(record['next_utc'])
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        type(record['schema']) is int and record['schema'] == 1
        and record['boundary_id'] == f'{run_id}:first-next'
        and record['run_id'] == run_id
        and type(record['root_pid']) is int and record['root_pid'] == root_pid
        and type(record['root_create_time']) in (int, float)
        and record['root_create_time'] == root_create_time
        and record['readiness'] == 'LIVE_READY'
        and record['replay_mode'] is False
        and record['cohort_id'] == live_ready_record['cohort_id']
        and record['epoch_id'] == live_ready_record['epoch_id']
        and record['calendar_id'] == live_ready_record['calendar_id']
        and type(record['batch_id']) is str and bool(record['batch_id'])
        and type(record['slot_index']) is int
        and record['slot_index'] >= live_ready_record['slot_index']
        and (
            record['slot_index'] > live_ready_record['slot_index']
            or record['batch_id'] == live_ready_record['batch_id']
        )
        and (
            record['slot_index'] == live_ready_record['slot_index']
            or record['batch_id'] != live_ready_record['batch_id']
        )
        and record['live_ready_boundary_id'] == live_ready_record['boundary_id']
        and type(record['next_monotonic_ns']) is int
        and record['next_monotonic_ns'] > live_ready_record['ready_monotonic_ns']
        and type(record['clock_pair_span_ns']) is int
        and 0 <= record['clock_pair_span_ns'] <= 2_000_000_000
    )


def _memory_binding_projection():
    identity = MEMORY_TARGET_IDENTITY if type(MEMORY_TARGET_IDENTITY) is dict else {}
    ready = MEMORY_LIVE_READY_RECORD if type(MEMORY_LIVE_READY_RECORD) is dict else {}
    next_boundary = MEMORY_LIVE_NEXT_RECORD if type(MEMORY_LIVE_NEXT_RECORD) is dict else {}
    close = ROOT_STATE.get('memory_close_receipt')
    close = close if type(close) is dict else {}
    return {
        'schema': 1,
        'run_id': MEMORY_RUN_ID,
        'root_pid': identity.get('pid'),
        'root_create_time': identity.get('create_time'),
        'live_ready_boundary_id': ready.get('boundary_id'),
        'live_ready_monotonic_ns': ready.get('ready_monotonic_ns'),
        'live_next_boundary_id': next_boundary.get('boundary_id'),
        'live_next_monotonic_ns': next_boundary.get('next_monotonic_ns'),
        'resource_close_receipt_id': close.get('receipt_id'),
        'resource_close_monotonic_ns': close.get('close_monotonic_ns'),
    }


def validate_target_postflight_result(
    payload, *, run_id, root_pid, root_create_time, close_record
):
    """Bind a separate public R9 postflight result to this memory run and close."""
    if type(payload) is not dict:
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_RESULT_INVALID'}
    binding = payload.get('memory_binding')
    binding_fields = {
        'schema', 'run_id', 'root_pid', 'root_create_time',
        'live_ready_boundary_id', 'live_ready_monotonic_ns',
        'live_next_boundary_id', 'live_next_monotonic_ns',
        'resource_close_receipt_id', 'resource_close_monotonic_ns',
    }
    if type(binding) is not dict or set(binding) != binding_fields:
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_MEMORY_BINDING_INVALID'}
    if (
        type(binding.get('schema')) is not int or binding.get('schema') != 1
        or binding.get('run_id') != run_id
        or type(binding.get('root_pid')) is not int or binding.get('root_pid') != root_pid
        or type(binding.get('root_create_time')) not in (int, float)
        or binding.get('root_create_time') != root_create_time
        or payload.get('root_pid') != root_pid
    ):
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_MEMORY_TARGET_BINDING_MISMATCH'}
    if (
        type(close_record) is not dict
        or close_record.get('run_id') != run_id
        or close_record.get('root_pid') != root_pid
        or close_record.get('root_create_time') != root_create_time
        or binding.get('live_ready_boundary_id') != close_record.get('live_ready_boundary_id')
        or binding.get('live_ready_monotonic_ns') != close_record.get('live_ready_monotonic_ns')
        or binding.get('live_next_boundary_id') != close_record.get('live_next_boundary_id')
        or binding.get('live_next_monotonic_ns') != close_record.get('live_next_monotonic_ns')
        or binding.get('resource_close_receipt_id') != close_record.get('receipt_id')
        or binding.get('resource_close_monotonic_ns') != close_record.get('close_monotonic_ns')
    ):
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_MEMORY_CLOSE_BINDING_MISMATCH'}
    ready_mono = binding.get('live_ready_monotonic_ns')
    next_mono = binding.get('live_next_monotonic_ns')
    close_mono = binding.get('resource_close_monotonic_ns')
    if (
        binding.get('live_ready_boundary_id') != f'{run_id}:live-ready'
        or type(ready_mono) is not int or ready_mono <= 0
        or binding.get('live_next_boundary_id') != f'{run_id}:first-next'
        or type(next_mono) is not int or next_mono <= ready_mono
        or type(close_mono) is not int or close_mono <= next_mono
    ):
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_MEMORY_BOUNDARY_ORDER_INVALID'}
    checks = payload.get('fullpool_acceptance_checks')
    if (
        payload.get('phase') != 'complete'
        or payload.get('status') != 'FULL_POOL_TAPE_WITNESS_PASS'
        or payload.get('private_context_closed') is not True
        or payload.get('fullpool_tape_witness_pass') is not True
        or type(checks) is not dict or set(checks) != TARGET_POSTFLIGHT_CHECKS
        or any(type(value) is not bool or value is not True for value in checks.values())
        or type(payload.get('postflight')) is not dict
        or payload['postflight'].get('status') != 'PASS'
    ):
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_POSTFLIGHT_NOT_PASS'}
    return {
        'status': 'PASS',
        'failure_code': None,
        'bound_run_id': run_id,
        'bound_root_pid': root_pid,
        'bound_root_create_time': root_create_time,
        'bound_live_ready_monotonic_ns': ready_mono,
        'bound_live_next_monotonic_ns': next_mono,
        'bound_resource_close_monotonic_ns': close_mono,
    }


def read_target_postflight_result(
    path, *, run_id, root_pid, root_create_time, close_record
):
    if not isinstance(path, Path) or path.is_symlink():
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_RESULT_PATH_INVALID'}
    try:
        info = path.lstat()
    except OSError:
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_RESULT_UNAVAILABLE'}
    if not stat.S_ISREG(info.st_mode) or info.st_size < 0 or info.st_size > MAX_TARGET_RESULT_BYTES:
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_RESULT_SIZE_OR_TYPE_INVALID'}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {'status': 'INCOMPLETE', 'failure_code': 'TARGET_RESULT_INVALID'}
    return validate_target_postflight_result(
        payload,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=root_create_time,
        close_record=close_record,
    )


def publish_live_ready_record(event):
    """Publish a single first-LIVE_READY engine-thread witness.

    The strategy calls this once when its first complete LIVE_READY snapshot
    is confirmed, including during prenext. This protocol records an OS clock
    pair; tape or cohort event times are never used as RSS window boundaries.
    """
    global MEMORY_LIVE_READY_RECORD
    if (
        not isinstance(MEMORY_CONTROL, Path)
        or type(MEMORY_TARGET_IDENTITY) is not dict
        or not isinstance(MEMORY_RUN_ID, str)
        or MEMORY_LIVE_READY_RECORD is not None
    ):
        raise RuntimeError('LIVE_READY_TARGET_CONTEXT_INVALID')
    fields = {
        'readiness', 'replay_mode', 'cohort_id', 'epoch_id', 'calendar_id',
        'batch_id', 'slot_index',
    }
    if type(event) is not dict or set(event) != fields:
        raise RuntimeError('LIVE_READY_EVENT_FIELDS_INVALID')
    if (
        event['readiness'] != 'LIVE_READY'
        or event['replay_mode'] is not False
        or type(event['cohort_id']) is not str or not event['cohort_id']
        or type(event['epoch_id']) is not int or event['epoch_id'] <= 0
        or type(event['calendar_id']) is not str or not event['calendar_id']
        or type(event['batch_id']) is not str or not event['batch_id']
        or type(event['slot_index']) is not int or event['slot_index'] < 0
    ):
        raise RuntimeError('LIVE_READY_EVENT_INVALID')
    start_record = read_protocol_record(MEMORY_CONTROL / START_NAME)
    if (
        type(start_record) is not dict
        or start_record.get('run_id') != MEMORY_RUN_ID
        or start_record.get('root_pid') != MEMORY_TARGET_IDENTITY['pid']
        or start_record.get('root_create_time') != MEMORY_TARGET_IDENTITY['create_time']
        or type(start_record.get('start_monotonic_ns')) is not int
    ):
        raise RuntimeError('LIVE_READY_RUN_START_BINDING_INVALID')
    utc, mono_ns, span_ns = capture_os_clock_pair(
        strictly_after_monotonic_ns=start_record['start_monotonic_ns']
    )
    record = {
        'schema': 1,
        'boundary_id': f'{MEMORY_RUN_ID}:live-ready',
        'run_id': MEMORY_RUN_ID,
        'root_pid': MEMORY_TARGET_IDENTITY['pid'],
        'root_create_time': MEMORY_TARGET_IDENTITY['create_time'],
        'readiness': event['readiness'],
        'replay_mode': event['replay_mode'],
        'cohort_id': event['cohort_id'],
        'epoch_id': event['epoch_id'],
        'calendar_id': event['calendar_id'],
        'batch_id': event['batch_id'],
        'slot_index': event['slot_index'],
        'ready_utc': utc,
        'ready_monotonic_ns': mono_ns,
        'clock_pair_span_ns': span_ns,
    }
    if span_ns > 2_000_000_000 or not validate_live_ready_record(
        record,
        run_id=MEMORY_RUN_ID,
        root_pid=MEMORY_TARGET_IDENTITY['pid'],
        root_create_time=MEMORY_TARGET_IDENTITY['create_time'],
    ):
        raise RuntimeError('LIVE_READY_RECORD_INVALID')
    publish_protocol_record(MEMORY_CONTROL / LIVE_READY_NAME, record)
    MEMORY_LIVE_READY_RECORD = record
    target_result = ROOT_STATE.get('result')
    if type(target_result) is dict:
        target_result['memory_binding'] = _memory_binding_projection()
    return record


def publish_live_next_record(event):
    """Publish the first regular ``next`` boundary at the ready or later slot."""
    global MEMORY_LIVE_NEXT_RECORD
    if (
        not isinstance(MEMORY_CONTROL, Path)
        or type(MEMORY_TARGET_IDENTITY) is not dict
        or not isinstance(MEMORY_RUN_ID, str)
        or MEMORY_LIVE_NEXT_RECORD is not None
    ):
        raise RuntimeError('LIVE_NEXT_TARGET_CONTEXT_INVALID')
    fields = {
        'readiness', 'replay_mode', 'cohort_id', 'epoch_id', 'calendar_id',
        'batch_id', 'slot_index',
    }
    if type(event) is not dict or set(event) != fields:
        raise RuntimeError('LIVE_NEXT_EVENT_FIELDS_INVALID')
    ready = MEMORY_LIVE_READY_RECORD
    if (
        event['readiness'] != 'LIVE_READY'
        or event['replay_mode'] is not False
        or type(event['cohort_id']) is not str or not event['cohort_id']
        or type(event['epoch_id']) is not int or event['epoch_id'] <= 0
        or type(event['calendar_id']) is not str or not event['calendar_id']
        or type(event['batch_id']) is not str or not event['batch_id']
        or type(event['slot_index']) is not int or event['slot_index'] < 0
        or not validate_live_ready_record(
            ready,
            run_id=MEMORY_RUN_ID,
            root_pid=MEMORY_TARGET_IDENTITY['pid'],
            root_create_time=MEMORY_TARGET_IDENTITY['create_time'],
        )
        or event['cohort_id'] != ready['cohort_id']
        or event['epoch_id'] != ready['epoch_id']
        or event['calendar_id'] != ready['calendar_id']
        or event['slot_index'] < ready['slot_index']
        or (
            event['slot_index'] == ready['slot_index']
            and event['batch_id'] != ready['batch_id']
        )
        or (
            event['slot_index'] > ready['slot_index']
            and event['batch_id'] == ready['batch_id']
        )
    ):
        raise RuntimeError('LIVE_NEXT_EVENT_INVALID')
    utc, mono_ns, span_ns = capture_os_clock_pair(
        strictly_after_monotonic_ns=ready['ready_monotonic_ns']
    )
    record = {
        'schema': 1,
        'boundary_id': f'{MEMORY_RUN_ID}:first-next',
        'run_id': MEMORY_RUN_ID,
        'root_pid': MEMORY_TARGET_IDENTITY['pid'],
        'root_create_time': MEMORY_TARGET_IDENTITY['create_time'],
        'readiness': event['readiness'],
        'replay_mode': event['replay_mode'],
        'cohort_id': event['cohort_id'],
        'epoch_id': event['epoch_id'],
        'calendar_id': event['calendar_id'],
        'batch_id': event['batch_id'],
        'slot_index': event['slot_index'],
        'live_ready_boundary_id': ready['boundary_id'],
        'next_utc': utc,
        'next_monotonic_ns': mono_ns,
        'clock_pair_span_ns': span_ns,
    }
    if span_ns > 2_000_000_000 or not validate_live_next_record(
        record,
        run_id=MEMORY_RUN_ID,
        root_pid=MEMORY_TARGET_IDENTITY['pid'],
        root_create_time=MEMORY_TARGET_IDENTITY['create_time'],
        live_ready_record=ready,
    ):
        raise RuntimeError('LIVE_NEXT_RECORD_INVALID')
    publish_protocol_record(MEMORY_CONTROL / LIVE_NEXT_NAME, record)
    MEMORY_LIVE_NEXT_RECORD = record
    target_result = ROOT_STATE.get('result')
    if type(target_result) is dict:
        target_result['memory_binding'] = _memory_binding_projection()
    return record


def publish_close_record(summary, *, closed):
    if not isinstance(MEMORY_CONTROL, Path) or type(MEMORY_TARGET_IDENTITY) is not dict:
        raise RuntimeError('MEMORY_TARGET_CONTEXT_MISSING')
    cleanup_complete = bool(
        closed is True
        and type(summary) is dict
        and summary.get('status') == 'LIVE_RUN_COMPLETE'
        and summary.get('cleanup_complete') is True
        and ROOT_STATE.get('closed') is True
        and ROOT_STATE.get('observer_sink', {}).get('cleanup_confirmed') is True
        and ROOT_STATE.get('observer_sink', {}).get('timer_joined') is True
    )
    live_ready_valid = (
        type(MEMORY_TARGET_IDENTITY) is dict
        and validate_live_ready_record(
            MEMORY_LIVE_READY_RECORD,
            run_id=MEMORY_RUN_ID,
            root_pid=MEMORY_TARGET_IDENTITY['pid'],
            root_create_time=MEMORY_TARGET_IDENTITY['create_time'],
        )
    )
    live_next_valid = (
        live_ready_valid
        and validate_live_next_record(
            MEMORY_LIVE_NEXT_RECORD,
            run_id=MEMORY_RUN_ID,
            root_pid=MEMORY_TARGET_IDENTITY['pid'],
            root_create_time=MEMORY_TARGET_IDENTITY['create_time'],
            live_ready_record=MEMORY_LIVE_READY_RECORD,
        )
    )
    if closed is True:
        previous_boundary = (
            MEMORY_LIVE_NEXT_RECORD['next_monotonic_ns']
            if live_next_valid
            else MEMORY_LIVE_READY_RECORD['ready_monotonic_ns'] if live_ready_valid else None
        )
        utc, mono_ns, span_ns = capture_os_clock_pair(
            strictly_after_monotonic_ns=previous_boundary
        )
    else:
        utc, mono_ns, span_ns = None, None, None
    record = {
        'schema': 1,
        'status': (
            'LIVE_RUN_COMPLETE'
            if cleanup_complete and live_ready_valid and live_next_valid
            else 'LIVE_RUN_INCOMPLETE'
        ),
        'closed': closed is True,
        'cleanup_complete': cleanup_complete,
        'receipt_id': f'{MEMORY_RUN_ID}:close',
        'run_id': MEMORY_RUN_ID,
        'root_pid': MEMORY_TARGET_IDENTITY['pid'],
        'root_create_time': MEMORY_TARGET_IDENTITY['create_time'],
        'live_ready_boundary_id': (
            MEMORY_LIVE_READY_RECORD['boundary_id'] if live_ready_valid else None
        ),
        'live_ready_monotonic_ns': (
            MEMORY_LIVE_READY_RECORD['ready_monotonic_ns'] if live_ready_valid else None
        ),
        'live_next_boundary_id': (
            MEMORY_LIVE_NEXT_RECORD['boundary_id'] if live_next_valid else None
        ),
        'live_next_monotonic_ns': (
            MEMORY_LIVE_NEXT_RECORD['next_monotonic_ns'] if live_next_valid else None
        ),
        'close_utc': utc if closed is True else None,
        'close_monotonic_ns': mono_ns if closed is True else None,
        'close_clock_pair_span_ns': span_ns,
    }
    publish_protocol_record(MEMORY_CONTROL / RECEIPT_NAME, record)
    ROOT_STATE['memory_close_receipt'] = record
    target_result = ROOT_STATE.get('result')
    if type(target_result) is dict:
        target_result['memory_binding'] = _memory_binding_projection()
    return record


def analyze_memory_capture(
    observer_module,
    *,
    output_path,
    run_id,
    root_pid,
    root_create_time,
    sampler_pid,
    start_record,
    live_ready_record,
    live_next_record,
    close_record,
):
    """Validate the sibling sampler stream; never turn diagnostics into PASS."""
    result = {
        'status': 'INCOMPLETE',
        'memory_acceptance': 'NOT_EVALUATED',
        'window_summary': None,
        'rss_growth_diagnostic': _rss_growth_diagnostic(None),
        'object_growth_evidence': 'NOT_COLLECTED',
        'pre_run_sample_count_filtered': 0,
        'pre_live_ready_sample_count_filtered': 0,
        'post_close_sample_count_filtered': 0,
        'failure_code': None,
    }
    close_fields = {
        'schema', 'status', 'closed', 'cleanup_complete', 'receipt_id', 'run_id',
        'root_pid', 'root_create_time', 'live_ready_boundary_id',
        'live_ready_monotonic_ns', 'live_next_boundary_id',
        'live_next_monotonic_ns', 'close_utc', 'close_monotonic_ns',
        'close_clock_pair_span_ns',
    }
    if type(close_record) is not dict or set(close_record) != close_fields:
        result['failure_code'] = 'CLOSE_RECEIPT_MISSING_OR_INVALID'
        return result
    if not output_path.is_file() or output_path.is_symlink():
        result['failure_code'] = 'SAMPLE_OUTPUT_UNAVAILABLE'
        return result
    if output_path.stat().st_size > observer_module.MAX_OUTPUT_BYTES:
        result['failure_code'] = 'SAMPLE_OUTPUT_LIMIT'
        return result
    try:
        with output_path.open('r', encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result['failure_code'] = 'SAMPLE_OUTPUT_INVALID'
        return result
    if len(rows) < 2 or type(rows[0]) is not dict or type(rows[-1]) is not dict:
        result['failure_code'] = 'SAMPLE_RECORDS_MISSING'
        return result
    header, summary = rows[0], rows[-1]
    samples = rows[1:-1]
    if (
        header.get('record_type') != 'header'
        or header.get('schema') != 1
        or header.get('run_id') != run_id
        or type(header.get('root_pid')) is not int or header['root_pid'] != root_pid
        or type(header.get('expected_create_time')) not in (int, float)
        or header['expected_create_time'] != root_create_time
        or type(header.get('sampler_pid')) is not int or header['sampler_pid'] != sampler_pid
        or summary.get('record_type') != 'summary'
        or summary.get('schema') != 1
        or summary.get('run_id') != run_id
        or summary.get('root_pid') != root_pid
        or summary.get('expected_create_time') != root_create_time
        or summary.get('sampler_pid') != sampler_pid
        or summary.get('stop_reason') != 'COMPLETION_RECEIPT'
        or summary.get('completion_status') != close_record.get('status')
        or summary.get('completion_closed') is not close_record.get('closed')
        or summary.get('completion_cleanup_complete') is not close_record.get('cleanup_complete')
        or summary.get('sampling_quality_valid') is not True
        or summary.get('completion_receipt_state') != 'terminal'
        or summary.get('completion_receipt_id') != f'{run_id}:close'
        or summary.get('completion_run_id') != run_id
        or summary.get('completion_root_pid') != root_pid
        or summary.get('completion_root_create_time') != root_create_time
        or summary.get('completion_live_ready_boundary_id')
        != close_record.get('live_ready_boundary_id')
        or summary.get('completion_live_ready_monotonic_ns')
        != close_record.get('live_ready_monotonic_ns')
        or summary.get('completion_live_next_boundary_id')
        != close_record.get('live_next_boundary_id')
        or summary.get('completion_live_next_monotonic_ns')
        != close_record.get('live_next_monotonic_ns')
        or summary.get('close_utc') != close_record.get('close_utc')
        or summary.get('close_monotonic_ns') != close_record.get('close_monotonic_ns')
        or summary.get('close_clock_pair_span_ns') != close_record.get('close_clock_pair_span_ns')
    ):
        result['failure_code'] = 'SAMPLER_TERMINAL_BINDING_MISMATCH'
        return result
    start_fields = {
        'schema', 'run_id', 'root_pid', 'root_create_time', 'start_utc',
        'start_monotonic_ns', 'clock_pair_span_ns',
    }
    live_ready_fields = {
        'schema', 'boundary_id', 'run_id', 'root_pid', 'root_create_time',
        'readiness', 'replay_mode', 'cohort_id', 'epoch_id', 'calendar_id',
        'batch_id', 'slot_index',
        'ready_utc', 'ready_monotonic_ns', 'clock_pair_span_ns',
    }
    if type(start_record) is not dict or set(start_record) != start_fields:
        result['failure_code'] = 'RUN_START_RECORD_INVALID'
        return result
    if type(live_ready_record) is not dict or set(live_ready_record) != live_ready_fields:
        result['failure_code'] = 'LIVE_READY_RECORD_MISSING_OR_INVALID'
        return result
    if not validate_live_ready_record(
        live_ready_record,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=root_create_time,
    ):
        result['failure_code'] = 'LIVE_READY_TARGET_BINDING_INVALID'
        return result
    if not validate_live_next_record(
        live_next_record,
        run_id=run_id,
        root_pid=root_pid,
        root_create_time=root_create_time,
        live_ready_record=live_ready_record,
    ):
        result['failure_code'] = 'LIVE_NEXT_RECORD_MISSING_OR_INVALID'
        return result
    if (
        type(close_record.get('schema')) is not int or close_record.get('schema') != 1
        or close_record.get('status') not in ('LIVE_RUN_COMPLETE', 'LIVE_EPOCH_SEQUENCE_COMPLETE')
        or close_record.get('closed') is not True
        or close_record.get('cleanup_complete') is not True
        or type(close_record.get('root_pid')) is not int
        or type(close_record.get('root_create_time')) not in (int, float)
        or type(start_record['schema']) is not int or start_record['schema'] != 1
        or start_record['run_id'] != run_id
        or type(start_record['root_pid']) is not int or start_record['root_pid'] != root_pid
        or start_record['root_create_time'] != root_create_time
        or type(start_record['start_monotonic_ns']) is not int
        or start_record['start_monotonic_ns'] <= 0
        or type(start_record['clock_pair_span_ns']) is not int
        or not 0 <= start_record['clock_pair_span_ns']
        <= observer_module.MAX_UTC_MONOTONIC_SKEW_SECONDS * 1_000_000_000
        or type(close_record.get('close_monotonic_ns')) is not int
        or close_record['close_monotonic_ns'] <= start_record['start_monotonic_ns']
        or type(close_record.get('close_clock_pair_span_ns')) is not int
        or not 0 <= close_record['close_clock_pair_span_ns']
        <= observer_module.MAX_UTC_MONOTONIC_SKEW_SECONDS * 1_000_000_000
        or close_record.get('run_id') != run_id
        or close_record.get('root_pid') != root_pid
        or close_record.get('root_create_time') != root_create_time
        or close_record.get('receipt_id') != f'{run_id}:close'
        or close_record.get('live_ready_boundary_id') != f'{run_id}:live-ready'
        or close_record.get('live_ready_monotonic_ns')
        != live_ready_record.get('ready_monotonic_ns')
        or close_record.get('live_next_boundary_id') != f'{run_id}:first-next'
        or close_record.get('live_next_monotonic_ns')
        != live_next_record.get('next_monotonic_ns')
        or close_record.get('status') not in ('LIVE_RUN_COMPLETE', 'LIVE_EPOCH_SEQUENCE_COMPLETE')
        or close_record.get('closed') is not True
        or close_record.get('cleanup_complete') is not True
    ):
        result['failure_code'] = 'RUN_BOUNDARY_BINDING_INVALID'
        return result
    try:
        start_utc = parse_os_utc(start_record['start_utc'])
        live_ready_utc = parse_os_utc(live_ready_record['ready_utc'])
        live_next_utc = parse_os_utc(live_next_record['next_utc'])
        close_utc = parse_os_utc(close_record['close_utc'])
    except (KeyError, ValueError):
        result['failure_code'] = 'RUN_BOUNDARY_UTC_INVALID'
        return result
    start_mono = start_record['start_monotonic_ns']
    live_ready_mono = live_ready_record['ready_monotonic_ns']
    live_next_mono = live_next_record['next_monotonic_ns']
    close_mono = close_record['close_monotonic_ns']
    if not start_mono < live_ready_mono < live_next_mono < close_mono:
        result['failure_code'] = 'LIVE_READY_BOUNDARY_ORDER_INVALID'
        return result
    monotonic_elapsed = (close_mono - start_mono) / 1_000_000_000
    utc_elapsed = (close_utc - start_utc).total_seconds()
    if abs(utc_elapsed - monotonic_elapsed) > observer_module.MAX_UTC_MONOTONIC_SKEW_SECONDS:
        result['failure_code'] = 'RUN_BOUNDARY_CLOCK_DOMAIN_MISMATCH'
        return result
    next_utc_elapsed = (live_next_utc - live_ready_utc).total_seconds()
    next_monotonic_elapsed = (live_next_mono - live_ready_mono) / 1_000_000_000
    if abs(next_utc_elapsed - next_monotonic_elapsed) > observer_module.MAX_UTC_MONOTONIC_SKEW_SECONDS:
        result['failure_code'] = 'LIVE_NEXT_CLOCK_DOMAIN_MISMATCH'
        return result
    in_run = []
    previous = None
    for row in samples:
        if type(row) is not dict or row.get('record_type') != 'sample':
            result['failure_code'] = 'SAMPLE_ROW_INVALID'
            return result
        mono = row.get('monotonic_ns')
        if type(mono) is not int or mono <= 0 or (previous is not None and mono <= previous):
            result['failure_code'] = 'SAMPLE_MONOTONIC_ORDER_INVALID'
            return result
        previous = mono
        if mono < start_mono:
            result['pre_run_sample_count_filtered'] += 1
            continue
        if mono >= close_mono:
            result['post_close_sample_count_filtered'] += 1
            continue
        if mono < live_ready_mono:
            result['pre_live_ready_sample_count_filtered'] += 1
            continue
        tree = row.get('process_tree')
        if type(tree) is not list or any(type(entry) is not dict for entry in tree):
            result['failure_code'] = 'SAMPLE_TREE_INVALID'
            return result
        roots = [entry for entry in tree if entry.get('pid') == root_pid]
        if (
            row.get('sampling_valid') is not True
            or type(row.get('rss_total_bytes')) is not int or row['rss_total_bytes'] <= 0
            or len(roots) != 1
            or roots[0].get('create_time') != root_create_time
            or roots[0].get('rss_bytes') is None
            or any(entry.get('pid') == sampler_pid for entry in tree)
        ):
            result['failure_code'] = 'SAMPLE_TREE_IDENTITY_OR_QUALITY_INVALID'
            return result
        try:
            sample_utc = parse_os_utc(row.get('utc'))
        except ValueError:
            result['failure_code'] = 'SAMPLE_UTC_INVALID'
            return result
        expected_utc = live_ready_utc + timedelta(
            seconds=(mono - live_ready_mono) / 1_000_000_000
        )
        if abs((sample_utc - expected_utc).total_seconds()) > observer_module.MAX_UTC_MONOTONIC_SKEW_SECONDS:
            result['failure_code'] = 'SAMPLE_OS_CLOCK_PAIR_MISMATCH'
            return result
        in_run.append(row)
    if not in_run:
        result['failure_code'] = 'NO_IN_RUN_SAMPLES'
        return result
    gaps = [
        (right['monotonic_ns'] - left['monotonic_ns']) / 1_000_000_000
        for left, right in zip(in_run, in_run[1:])
    ]
    max_gap = max(gaps, default=float('inf'))
    if max_gap > observer_module.MAX_SAMPLE_GAP_SECONDS:
        result['failure_code'] = 'IN_RUN_SAMPLE_GAP_EXCEEDED'
        result['maximum_in_run_sample_gap_seconds'] = max_gap
        return result
    windows = observer_module.summarize_equal_windows(
        in_run,
        warmup_end_utc=live_ready_record['ready_utc'],
        run_end_utc=close_record['close_utc'],
        start_monotonic_ns=live_ready_mono,
        end_monotonic_ns=close_mono,
    )
    result.update(
        status='WINDOWS_RECORDED' if windows.get('status') == 'WINDOWS_RECORDED' else 'INCOMPLETE',
        failure_code=None if windows.get('status') == 'WINDOWS_RECORDED' else windows.get('status'),
        maximum_in_run_sample_gap_seconds=max_gap,
        run_start_utc=start_record['start_utc'],
        run_start_monotonic_ns=start_mono,
        first_live_ready_utc=live_ready_record['ready_utc'],
        first_live_ready_monotonic_ns=live_ready_mono,
        first_live_next_utc=live_next_record['next_utc'],
        first_live_next_monotonic_ns=live_next_mono,
        live_ready_identity={
            'cohort_id': live_ready_record['cohort_id'],
            'epoch_id': live_ready_record['epoch_id'],
            'batch_id': live_ready_record['batch_id'],
        },
        window_start_source='FIRST_LIVE_READY_PAIRED_OS_UTC_MONOTONIC',
        resource_close_utc=close_record['close_utc'],
        resource_close_monotonic_ns=close_mono,
        window_summary=windows,
        rss_growth_diagnostic=_rss_growth_diagnostic(windows),
        object_growth_evidence='NOT_COLLECTED',
    )
    return result


def _rss_growth_diagnostic(window_summary):
    """Report RSS median movement without treating it as memory acceptance."""
    result = {
        'status': 'NOT_EVALUATED',
        'comparison_scope': 'DIAGNOSTIC_ONLY',
        'stable_rss_established': False,
        'baseline_source': 'FIRST_WINDOW_MEDIAN_PROXY',
        'first_window_median_rss_bytes': None,
        'last_window_median_rss_bytes': None,
        'growth_bytes': None,
        'diagnostic_limit_bytes': None,
        'object_growth_evidence': 'NOT_COLLECTED',
        'formal_memory_acceptance': 'NOT_EVALUATED',
    }
    if type(window_summary) is not dict or window_summary.get('status') != 'WINDOWS_RECORDED':
        return result
    windows = window_summary.get('windows')
    if type(windows) is not list or len(windows) != 2:
        return result
    first = windows[0].get('median_rss_bytes') if type(windows[0]) is dict else None
    last = windows[1].get('median_rss_bytes') if type(windows[1]) is dict else None
    if (
        type(first) not in (int, float) or type(first) is bool or first <= 0
        or type(last) not in (int, float) or type(last) is bool or last <= 0
    ):
        return result
    growth = last - first
    diagnostic_limit = max(32 * 1024 * 1024, int(first * 0.10))
    result.update(
        status='WITHIN_DIAGNOSTIC_LIMIT' if growth <= diagnostic_limit else 'OVER_DIAGNOSTIC_LIMIT',
        first_window_median_rss_bytes=first,
        last_window_median_rss_bytes=last,
        growth_bytes=growth,
        diagnostic_limit_bytes=diagnostic_limit,
    )
    return result


def _read_first_observer_rows(path):
    try:
        with path.open('r', encoding='utf-8') as stream:
            header = json.loads(stream.readline())
            first_sample = json.loads(stream.readline())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if type(header) is not dict or type(first_sample) is not dict:
        return None, None
    return header, first_sample


def _target_wait_for_release(run_id, control_dir):
    if DRAFT_UNEXECUTABLE or not R10_SUPERVISOR_ENABLED:
        raise RuntimeError('R10_TARGET_DRAFT_UNEXECUTABLE')
    if not isinstance(run_id, str) or not re.fullmatch(r'i51-[0-9a-f]{32}', run_id):
        raise RuntimeError('R10_RUN_ID_INVALID')
    if not control_dir.name.startswith('i51-r10-memory-') or not control_dir.is_dir():
        raise RuntimeError('R10_CONTROL_DIRECTORY_INVALID')
    import psutil

    target = psutil.Process(os.getpid())
    target_create_time = float(target.create_time())
    target_parent = target.parent()
    if target_parent is None:
        raise RuntimeError('R10_SUPERVISOR_IDENTITY_UNAVAILABLE')
    supervisor_pid = int(target_parent.pid)
    supervisor_create_time = float(target_parent.create_time())
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    release_path = control_dir / RELEASE_NAME
    while time.monotonic() < deadline:
        record = read_protocol_record(release_path)
        if record is None:
            time.sleep(0.05)
            continue
        fields = {
            'schema', 'run_id', 'target_pid', 'target_create_time', 'supervisor_pid',
            'supervisor_create_time', 'sampler_pid', 'sampler_create_time',
            'ready_sample_utc', 'ready_sample_monotonic_ns', 'release_utc',
            'release_monotonic_ns',
        }
        if type(record) is not dict or set(record) != fields:
            raise RuntimeError('R10_RELEASE_GATE_FIELDS_INVALID')
        sampler_pid = record.get('sampler_pid')
        sampler_create_time = record.get('sampler_create_time')
        if (
            type(record.get('schema')) is not int or record['schema'] != 1
            or record.get('run_id') != run_id
            or type(record.get('target_pid')) is not int or record['target_pid'] != os.getpid()
            or record.get('target_create_time') != target_create_time
            or record.get('supervisor_pid') != supervisor_pid
            or record.get('supervisor_create_time') != supervisor_create_time
            or type(sampler_pid) is not int or sampler_pid == os.getpid()
            or type(sampler_create_time) not in (int, float)
            or type(record.get('ready_sample_monotonic_ns')) is not int
            or record['ready_sample_monotonic_ns'] <= 0
            or type(record.get('release_monotonic_ns')) is not int
            or record['release_monotonic_ns'] <= record['ready_sample_monotonic_ns']
        ):
            raise RuntimeError('R10_RELEASE_GATE_BINDING_INVALID')
        try:
            parse_os_utc(record['ready_sample_utc'])
            parse_os_utc(record['release_utc'])
            sampler = psutil.Process(sampler_pid)
            sampler_parent = sampler.ppid()
            sampler_time = float(sampler.create_time())
        except (AttributeError, TypeError, ValueError, psutil.Error) as error:
            raise RuntimeError('R10_SAMPLER_IDENTITY_UNAVAILABLE') from error
        if sampler_parent != supervisor_pid or sampler_time != sampler_create_time:
            raise RuntimeError('R10_SAMPLER_IDENTITY_MISMATCH')
        if target.ppid() != supervisor_pid:
            raise RuntimeError('R10_TARGET_PARENT_CHANGED')
        return {
            'run_id': run_id,
            'target_pid': os.getpid(),
            'target_create_time': target_create_time,
            'sampler_pid': sampler_pid,
            'sampler_create_time': sampler_create_time,
        }
    raise RuntimeError('R10_RELEASE_GATE_TIMEOUT')


def _target_main(run_id, control_dir):
    global MEMORY_CONTROL, MEMORY_RUN_ID, MEMORY_TARGET_IDENTITY
    identity = _target_wait_for_release(run_id, control_dir)
    MEMORY_CONTROL = control_dir
    MEMORY_RUN_ID = run_id
    MEMORY_TARGET_IDENTITY = {
        'pid': identity['target_pid'],
        'create_time': identity['target_create_time'],
    }
    main()


def _verify_r10_dependencies():
    if DRAFT_UNEXECUTABLE or not R10_SUPERVISOR_ENABLED:
        raise RuntimeError('R10_DRAFT_UNEXECUTABLE')
    if (PUBLIC_PINS.get(str(R9_SOURCE)) != R9_SOURCE_SHA
            or PUBLIC_PINS.get(str(MEMORY_OBSERVER)) != MEMORY_OBSERVER_SHA):
        raise RuntimeError('R10_RUNTIME_PIN_BINDING_INVALID')
    verify_sources()


def supervisor_main(
    *, execute_bound_readonly_run, _target_command_factory=None, _target_result_path=None
):
    """Start the isolated R10 target and its RSS observer as sibling processes."""
    if execute_bound_readonly_run is not True:
        return {'status': 'DRAFT_UNEXECUTABLE', 'memory_acceptance': 'NOT_EVALUATED'}
    _verify_r10_dependencies()
    observer = load_public_module('i51_memory_observer_r10', MEMORY_OBSERVER)
    run_id = 'i51-' + uuid.uuid4().hex
    control_dir = Path(tempfile.mkdtemp(prefix='i51-r10-memory-'))
    ready_path = control_dir / READY_NAME
    receipt_path = control_dir / RECEIPT_NAME
    release_path = control_dir / RELEASE_NAME
    start_path = control_dir / START_NAME
    live_ready_path = control_dir / LIVE_READY_NAME
    output_path = control_dir / SAMPLE_NAME
    if _target_result_path is not None:
        target_result_path = Path(_target_result_path)
    elif _target_command_factory is not None:
        target_result_path = control_dir / TARGET_RESULT_NAME
    else:
        target_result_path = OUTPUT
    if any(path.exists() or path.is_symlink() for path in (
        ready_path, receipt_path, release_path, start_path, live_ready_path,
        output_path, target_result_path,
    )):
        raise RuntimeError('R10_CONTROL_NAMESPACE_NOT_FRESH')
    result = {
        'status': 'INCOMPLETE',
        'run_id': run_id,
        'memory_acceptance': 'NOT_EVALUATED',
        'supervisor_rss_report': {
            'status': 'NOT_RECORDED',
            'scope': 'R10_SIBLING_PROCESS_TREE_RSS',
            'run_id': run_id,
            'sample_file': SAMPLE_NAME,
            'formal_memory_acceptance': 'NOT_EVALUATED',
        },
        'rss_growth_diagnostic': _rss_growth_diagnostic(None),
        'object_growth_evidence': 'NOT_COLLECTED',
        'control_directory': str(control_dir),
        'target_release_gate_opened': False,
        'cleanup_state': 'UNCERTAIN',
    }
    target = sampler = None
    target_identity = sampler_identity = None
    try:
        if _target_command_factory is None:
            command = [
                sys.executable, '-I', '-i', str(Path(__file__).resolve()),
                '--mode', 'target', '--run-id', run_id, '--control-dir', str(control_dir),
            ]
        else:
            # In-process-only seam for a synthetic child; the CLI exposes no override.
            command = _target_command_factory(run_id, control_dir)
            if type(command) is not list or not command or any(
                type(part) is not str or not part for part in command
            ):
                raise RuntimeError('R10_SYNTHETIC_TARGET_COMMAND_INVALID')
        target = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        target_proc = observer.psutil.Process(target.pid)
        target_identity = {
            'pid': int(target.pid),
            'create_time': float(target_proc.create_time()),
        }
        supervisor_proc = observer.psutil.Process(os.getpid())
        if target_proc.ppid() != os.getpid():
            raise RuntimeError('R10_TARGET_NOT_SUPERVISOR_CHILD')
        sampler = subprocess.Popen(
            [
                sys.executable, '-I', str(MEMORY_OBSERVER),
                '--root-pid', str(target_identity['pid']),
                '--expected-create-time', repr(target_identity['create_time']),
                '--run-id', run_id,
                '--completion-receipt', str(receipt_path),
                '--ready-path', str(ready_path),
                '--output', str(output_path),
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        sampler_proc = observer.psutil.Process(sampler.pid)
        sampler_identity = {
            'pid': int(sampler.pid),
            'create_time': float(sampler_proc.create_time()),
        }
        if sampler_proc.ppid() != os.getpid() or sampler.pid == target.pid:
            raise RuntimeError('R10_SAMPLER_NOT_SIBLING')
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        ready = None
        while time.monotonic() < deadline:
            ready = read_protocol_record(ready_path)
            if ready is not None:
                break
            if target.poll() is not None or sampler.poll() is not None:
                break
            time.sleep(0.05)
        if not validate_ready_record(
            ready,
            run_id=run_id,
            root_pid=target_identity['pid'],
            root_create_time=target_identity['create_time'],
            sampler_pid=sampler_identity['pid'],
        ):
            result['failure_code'] = 'R10_VALID_FIRST_SAMPLE_NOT_PROVEN'
            return result
        header, first_sample = _read_first_observer_rows(output_path)
        if (
            header is None or first_sample is None
            or header.get('run_id') != run_id
            or header.get('root_pid') != target_identity['pid']
            or header.get('expected_create_time') != target_identity['create_time']
            or header.get('sampler_pid') != sampler_identity['pid']
            or first_sample.get('record_type') != 'sample'
            or first_sample.get('sampling_valid') is not True
            or first_sample.get('run_id') is not None
            or first_sample.get('monotonic_ns') != ready.get('sample_monotonic_ns')
            or first_sample.get('utc') != ready.get('sample_utc')
            or any(entry.get('pid') == sampler_identity['pid'] for entry in first_sample.get('process_tree', []))
        ):
            result['failure_code'] = 'R10_READY_SAMPLE_NOT_IN_STREAM'
            return result
        sample_roots = [
            item for item in first_sample.get('process_tree', [])
            if type(item) is dict and item.get('pid') == target_identity['pid']
        ]
        if len(sample_roots) != 1 or sample_roots[0].get('create_time') != target_identity['create_time']:
            result['failure_code'] = 'R10_FIRST_SAMPLE_TARGET_IDENTITY_MISMATCH'
            return result
        release_utc, release_mono_ns, _release_pair_span = capture_os_clock_pair()
        if release_mono_ns <= ready['sample_monotonic_ns']:
            result['failure_code'] = 'R10_RELEASE_PRECEDES_SAMPLE'
            return result
        gate = {
            'schema': 1,
            'run_id': run_id,
            'target_pid': target_identity['pid'],
            'target_create_time': target_identity['create_time'],
            'supervisor_pid': os.getpid(),
            'supervisor_create_time': float(supervisor_proc.create_time()),
            'sampler_pid': sampler_identity['pid'],
            'sampler_create_time': sampler_identity['create_time'],
            'ready_sample_utc': ready['sample_utc'],
            'ready_sample_monotonic_ns': ready['sample_monotonic_ns'],
            'release_utc': release_utc,
            'release_monotonic_ns': release_mono_ns,
        }
        publish_protocol_record(release_path, gate)
        result['target_release_gate_opened'] = True
        target_exit = target.wait(timeout=CHILD_TIMEOUT_SECONDS)
        try:
            sampler.wait(timeout=READY_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            result['failure_code'] = 'R10_SAMPLER_EXIT_UNCONFIRMED'
            return result
        start_record = read_protocol_record(start_path)
        live_ready_record = read_protocol_record(live_ready_path)
        live_next_record = read_protocol_record(control_dir / LIVE_NEXT_NAME)
        close_record = read_protocol_record(receipt_path)
        analysis = analyze_memory_capture(
            observer,
            output_path=output_path,
            run_id=run_id,
            root_pid=target_identity['pid'],
            root_create_time=target_identity['create_time'],
            sampler_pid=sampler_identity['pid'],
            start_record=start_record,
            live_ready_record=live_ready_record,
            live_next_record=live_next_record,
            close_record=close_record,
        )
        target_postflight = read_target_postflight_result(
            target_result_path,
            run_id=run_id,
            root_pid=target_identity['pid'],
            root_create_time=target_identity['create_time'],
            close_record=close_record,
        )
        result.update(
            status=analysis['status'],
            failure_code=analysis['failure_code'],
            target_exit_code=target_exit,
            sampler_exit_code=sampler.returncode,
            cleanup_state='CHILDREN_EXITED',
            pre_run_sample_count_filtered=analysis['pre_run_sample_count_filtered'],
            pre_live_ready_sample_count_filtered=analysis[
                'pre_live_ready_sample_count_filtered'
            ],
            post_close_sample_count_filtered=analysis['post_close_sample_count_filtered'],
            maximum_in_run_sample_gap_seconds=analysis.get('maximum_in_run_sample_gap_seconds'),
            run_start_utc=analysis.get('run_start_utc'),
            run_start_monotonic_ns=analysis.get('run_start_monotonic_ns'),
            first_live_ready_utc=analysis.get('first_live_ready_utc'),
            first_live_ready_monotonic_ns=analysis.get('first_live_ready_monotonic_ns'),
            first_live_next_utc=analysis.get('first_live_next_utc'),
            first_live_next_monotonic_ns=analysis.get('first_live_next_monotonic_ns'),
            window_start_source=analysis.get('window_start_source'),
            resource_close_utc=analysis.get('resource_close_utc'),
            resource_close_monotonic_ns=analysis.get('resource_close_monotonic_ns'),
            window_summary=analysis['window_summary'],
            rss_growth_diagnostic=analysis.get('rss_growth_diagnostic'),
            object_growth_evidence=analysis.get('object_growth_evidence', 'NOT_COLLECTED'),
            supervisor_rss_report={
                'status': 'ANALYSIS_RECORDED',
                'scope': 'R10_SIBLING_PROCESS_TREE_RSS',
                'run_id': run_id,
                'target_pid': target_identity['pid'],
                'target_create_time': target_identity['create_time'],
                'sampler_pid': sampler_identity['pid'],
                'sample_file': SAMPLE_NAME,
                'analysis_status': analysis['status'],
                'window_summary_status': (
                    analysis['window_summary'].get('status')
                    if type(analysis.get('window_summary')) is dict else None
                ),
                'diagnostic_only': True,
                'stable_rss_established': False,
                'object_growth_evidence': analysis.get('object_growth_evidence', 'NOT_COLLECTED'),
                'formal_memory_acceptance': 'NOT_EVALUATED',
            },
            target_postflight_status=target_postflight['status'],
            target_postflight_failure_code=target_postflight['failure_code'],
            target_postflight_binding={
                key: target_postflight.get(key)
                for key in (
                    'bound_run_id', 'bound_root_pid', 'bound_root_create_time',
                    'bound_live_ready_monotonic_ns', 'bound_live_next_monotonic_ns',
                    'bound_resource_close_monotonic_ns',
                )
            },
            fullpool_acceptance='NOT_EVALUATED',
        )
        if sampler.returncode != 0 or target_exit != 0:
            result['status'] = 'INCOMPLETE'
            result['failure_code'] = result['failure_code'] or 'R10_CHILD_EXIT_NONZERO'
        return result
    except subprocess.TimeoutExpired:
        result['failure_code'] = 'R10_CHILD_TIMEOUT'
        result['cleanup_state'] = 'UNCERTAIN_CHILD_MAY_REMAIN'
        return result
    except BaseException:
        result['failure_code'] = 'R10_SUPERVISOR_FAILURE'
        result['cleanup_state'] = 'VERIFY_CHILD_STATES_REQUIRED'
        return result
    finally:
        if not result.get('target_release_gate_opened'):
            for child in (target, sampler):
                if child is not None and child.poll() is None:
                    try:
                        child.wait(timeout=READY_TIMEOUT_SECONDS + 10)
                    except subprocess.TimeoutExpired:
                        result['cleanup_state'] = 'UNCERTAIN_CHILD_MAY_REMAIN'
            if result.get('cleanup_state') != 'UNCERTAIN_CHILD_MAY_REMAIN':
                result['cleanup_state'] = 'CHILDREN_EXITED_BEFORE_RELEASE'
        elif target is not None and sampler is not None:
            if target.poll() is not None and sampler.poll() is not None:
                result['cleanup_state'] = 'CHILDREN_EXITED'
            else:
                result['cleanup_state'] = 'UNCERTAIN_CHILD_MAY_REMAIN'
        # Never force-kill a target that may still own protected resources.
        try:
            publish_protocol_record(control_dir / 'supervisor_result.json', result)
        except (OSError, TypeError, ValueError):
            pass


class NativeOutputMute:
    """Discard provider output, retaining no raw private capture."""
    def __init__(self):
        self.saved_fds = []
        self.saved_handles = []
        self.null_fd = None
        self.warning_scope = None
        self.prior_logging = logging.root.manager.disable
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        self.kernel.GetStdHandle.restype = ctypes.c_void_p
        self.kernel.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        self.kernel.SetStdHandle.restype = ctypes.c_int

    def enter(self):
        import msvcrt
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            self.null_fd = os.open(os.devnull, os.O_WRONLY)
            for number, handle_id in ((1, -11), (2, -12)):
                self.saved_fds.append((number, os.dup(number)))
                self.saved_handles.append((handle_id, self.kernel.GetStdHandle(handle_id)))
                os.dup2(self.null_fd, number)
                if not self.kernel.SetStdHandle(handle_id, msvcrt.get_osfhandle(self.null_fd)):
                    raise RuntimeError('OUTPUT_SUPPRESSION_FAILED')
            logging.disable(logging.CRITICAL)
            self.warning_scope = warnings.catch_warnings()
            self.warning_scope.__enter__()
            warnings.simplefilter('ignore')
        except BaseException:
            # No provider or private context exists yet; undo partial setup.
            self.close()
            raise

    def close(self):
        sys.stdout.flush()
        sys.stderr.flush()
        for handle_id, value in self.saved_handles:
            if not self.kernel.SetStdHandle(handle_id, value):
                raise RuntimeError('OUTPUT_RESTORE_FAILED')
        for number, saved in self.saved_fds:
            os.dup2(saved, number)
            os.close(saved)
        if self.null_fd is not None:
            os.close(self.null_fd)
        if self.warning_scope is not None:
            self.warning_scope.__exit__(None, None, None)
        logging.disable(self.prior_logging)

def verify_public_source(path):
    path = Path(path)
    expected = PUBLIC_PINS.get(str(path))
    if (type(expected) is not str or len(expected) != 64
            or any(character not in '0123456789abcdef' for character in expected)):
        raise RuntimeError('PUBLIC_INPUT_PIN_MISSING')
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode)
                    or before.st_size < 0
                    or before.st_size > MAX_PINNED_SOURCE_BYTES):
                raise RuntimeError('PUBLIC_INPUT_SIZE_OR_TYPE_INVALID')
            raw = stream.read(MAX_PINNED_SOURCE_BYTES + 1)
            after = os.fstat(stream.fileno())
    except OSError:
        raise RuntimeError('PUBLIC_INPUT_UNAVAILABLE') from None
    before_identity = (
        before.st_dev, before.st_ino, before.st_size,
        getattr(before, 'st_mtime_ns', before.st_mtime),
        getattr(before, 'st_ctime_ns', before.st_ctime),
    )
    after_identity = (
        after.st_dev, after.st_ino, after.st_size,
        getattr(after, 'st_mtime_ns', after.st_mtime),
        getattr(after, 'st_ctime_ns', after.st_ctime),
    )
    if len(raw) > MAX_PINNED_SOURCE_BYTES or len(raw) != before.st_size:
        raise RuntimeError('PUBLIC_INPUT_SIZE_OR_TYPE_INVALID')
    if before_identity != after_identity:
        raise RuntimeError('PUBLIC_INPUT_CHANGED_DURING_READ')
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('PUBLIC_INPUT_CHANGED')
    return raw


def verify_sources():
    if DRAFT_UNEXECUTABLE or EXPECTED_DEV_HEAD.startswith('ROOT_MUST_BIND_'):
        raise RuntimeError('ROOT_FINALIZATION_REQUIRED')
    if BT_RECORD_SHA.startswith('ROOT_MUST_BIND_') or SDK_RECORD_SHA.startswith('ROOT_MUST_BIND_'):
        raise RuntimeError('FRESH_INSTALLED_RECORDS_REQUIRED')
    for path in PUBLIC_PINS:
        verify_public_source(path)
    if any(str(Path(path)) not in PUBLIC_PINS for path in R10_RUNTIME_DEPENDENCIES):
        raise RuntimeError('R10_RUNTIME_DEPENDENCY_PIN_MISSING')
    # These local installed-RECORD hashes are additional checks, not a Root
    # attestation of the checkout HEAD/index/dirty state or installed wheel.
    if hashlib.sha256(BT_RECORD.read_bytes()).hexdigest() != BT_RECORD_SHA:
        raise RuntimeError('INSTALLED_RECORD_CHANGED')
    # This is also verified by the source-pinned protected handoff before
    # credential resolution, using its existing approved SDK artifact pin.
    if hashlib.sha256(SDK_RECORD.read_bytes()).hexdigest() != SDK_RECORD_SHA:
        raise RuntimeError('INSTALLED_SDK_RECORD_CHANGED')


def verify_loaded_strategy_module(module):
    """Bind the imported strategy class to the pinned production module key and path."""
    if (
        type(getattr(module, '__name__', None)) is not str
        or module.__name__ != STRATEGY_MODULE_KEY
        or sys.modules.get(STRATEGY_MODULE_KEY) is not module
    ):
        raise RuntimeError('STRATEGY_MODULE_KEY_OR_IDENTITY_INVALID')
    try:
        origin = Path(module.__file__).resolve(strict=True)
        expected_origin = STRATEGY_MODULE_PATH.resolve(strict=True)
    except (AttributeError, OSError, TypeError, ValueError):
        raise RuntimeError('STRATEGY_MODULE_ORIGIN_INVALID') from None
    if origin != expected_origin:
        raise RuntimeError('STRATEGY_MODULE_ORIGIN_INVALID')
    expected_sha = PUBLIC_PINS.get(str(STRATEGY_MODULE_PATH))
    if (
        type(expected_sha) is not str
        or getattr(module, '__i51_source_sha256__', None) != expected_sha
        or getattr(module, '__i51_source_origin__', None) != str(expected_origin)
    ):
        raise RuntimeError('STRATEGY_MODULE_SOURCE_PIN_INVALID')
    strategy_class = getattr(module, 'Alpha003TargetStrategy', None)
    if (
        not isinstance(strategy_class, type)
        or strategy_class.__module__ != STRATEGY_MODULE_KEY
        or strategy_class.__name__ != 'Alpha003TargetStrategy'
    ):
        raise RuntimeError('STRATEGY_CLASS_MODULE_BINDING_INVALID')
    return strategy_class


def verify_loaded_live_runner(runner, strategy_module):
    """Verify run_live resolves the exact pinned strategy module by its import key."""
    if (
        type(getattr(runner, '__name__', None)) is not str
        or runner.__name__ != 'run'
        or sys.modules.get('run') is not runner
    ):
        raise RuntimeError('LIVE_RUNNER_MODULE_IDENTITY_INVALID')
    try:
        origin = Path(runner.__file__).resolve(strict=True)
        expected_origin = (EXAMPLE / 'run.py').resolve(strict=True)
    except (AttributeError, OSError, TypeError, ValueError):
        raise RuntimeError('LIVE_RUNNER_MODULE_ORIGIN_INVALID') from None
    if origin != expected_origin:
        raise RuntimeError('LIVE_RUNNER_MODULE_ORIGIN_INVALID')
    expected_sha = PUBLIC_PINS.get(str(EXAMPLE / 'run.py'))
    if (
        type(expected_sha) is not str
        or getattr(runner, '__i51_source_sha256__', None) != expected_sha
        or getattr(runner, '__i51_source_origin__', None) != str(origin)
    ):
        raise RuntimeError('LIVE_RUNNER_SOURCE_PIN_INVALID')
    for name in ('run_live', '_make_strategy_kwargs'):
        function = getattr(runner, name, None)
        if (
            not callable(function)
            or getattr(function, '__globals__', None) is not runner.__dict__
            or Path(function.__code__.co_filename).resolve() != expected_origin
        ):
            raise RuntimeError('LIVE_RUNNER_FUNCTION_BINDING_INVALID')
    strategy_class = verify_loaded_strategy_module(strategy_module)
    # _make_strategy_kwargs imports the class locally, so its module object is
    # resolved by Python's exact sys.modules key at invocation time.
    if sys.modules.get(STRATEGY_MODULE_KEY) is not strategy_module:
        raise RuntimeError('LIVE_RUNNER_STRATEGY_IMPORT_BINDING_INVALID')
    return strategy_class


def bounded_snapshot_failure_detail(detail, allowed_details):
    if type(detail) is str and type(allowed_details) is frozenset and detail in allowed_details:
        return detail
    if type(detail) is str and detail.startswith('INSTRUMENTS_') and detail.endswith('_QUERY_CALL_FAILED'):
        ordinal = detail[len('INSTRUMENTS_'):-len('_QUERY_CALL_FAILED')]
        if len(ordinal) == 3 and ordinal.isascii() and ordinal.isdigit() and 1 <= int(ordinal) <= 256:
            return detail
    return 'UNEXPECTED_COLLECTION_FAILURE'

def persist(result):
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def load_public_module(name, path, *, register=False):
    import importlib.util
    path = Path(path)
    source = verify_public_source(path)
    origin = path.resolve(strict=True)
    spec = importlib.util.spec_from_file_location(name, origin)
    if spec is None or spec.loader is None:
        raise RuntimeError('PUBLIC_MODULE_SPEC_UNAVAILABLE')
    module = importlib.util.module_from_spec(spec)
    # Execute the exact bytes just checked against PUBLIC_PINS; do not ask the
    # source loader to reopen a potentially replaced path or consume a stale pyc.
    code = compile(source, str(origin), 'exec')
    previous = sys.modules.get(name) if register else None
    if register:
        sys.modules[name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        if register and sys.modules.get(name) is module:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        raise
    module.__i51_source_sha256__ = hashlib.sha256(source).hexdigest()
    module.__i51_source_origin__ = str(origin)
    return module


def load_pinned_profile(runner):
    source = verify_public_source(PROFILE)
    # run.py's schema loader accepts a Path. Feed it a private temporary copy
    # made from the checked public bytes so its actual read is bound to the pin.
    with tempfile.TemporaryDirectory(prefix='i51-r10-profile-') as directory:
        pinned_copy = Path(directory) / PROFILE.name
        pinned_copy.write_bytes(source)
        return runner.load_config(pinned_copy)


def public_cleanup(cleanup):
    allowed_resources = {'query_refresh', 'broker', 'store', 'journal', 'decision_tape'}
    allowed_states = {'PASS', 'FAIL', 'INCOMPLETE', 'UNPROVEN', 'NOT_CREATED', 'NOT_RUN',
                      'NOT_STARTED', 'RETURNED', 'CLOSED', 'CLOSED_BY_BROKER',
                      'OBSERVATION_ONLY', 'OBSERVATION_ONLY_NONFLAT',
                      'SKIPPED_REFRESH_UNJOINED', 'SKIPPED_BROKER_SHUTDOWN_UNPROVEN'}
    rows = []
    if not isinstance(cleanup, (list, tuple)):
        return rows
    for item in cleanup:
        if not isinstance(item, dict) or item.get('resource') not in allowed_resources:
            continue
        row = {'resource': item['resource']}
        for key in ('status', 'shutdown_state', 'store_shutdown_state'):
            value = item.get(key)
            row[key] = value if type(value) is str and value in allowed_states else None
        for key in ('started', 'joined'):
            row[key] = item.get(key) if type(item.get(key)) is bool else None
        source = item.get('ctp_factor_source_shutdown')
        if isinstance(source, dict):
            row['ctp_source_required'] = source.get('required') is True
            row['ctp_source_pass'] = source.get('status') == 'PASS'
        rows.append(row)
    return rows


def _capacity_count(value):
    return value if type(value) is int and 0 <= value < (1 << 63) else None


def _capacity_utc_timestamp(value):
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return value


def _capacity_sample_projection(sample, *, logical_run_id, pid, create_time, epoch_id, calendar_id):
    if type(sample) is not dict:
        return None
    binding = sample.get('run_binding')
    boundary = sample.get('ready_boundary')
    cohort = sample.get('cohort_identity')
    ordinal = sample.get('ordinal')
    if (
        sample.get('schema') != 'backtrader.live_capacity_snapshot.v1'
        or type(sample.get('run_id')) is not str or sample['run_id'] != logical_run_id
        or type(ordinal) is not int or ordinal < 0
        or sample.get('status') not in ('OBSERVED', 'INCOMPLETE')
        or sample.get('acceptance_evaluated') is not False
        or type(binding) is not dict
        or binding.get('run_id') != logical_run_id
        or type(binding.get('epoch_id')) is not int or binding['epoch_id'] != epoch_id
        or type(binding.get('process_id')) is not int or binding['process_id'] != pid
        or type(binding.get('process_create_time')) not in (int, float)
        or not math.isfinite(binding['process_create_time'])
        or binding['process_create_time'] != create_time
        or type(boundary) is not dict
        or boundary.get('ordinal_source') != 'live_cohort_batch_slot_index_zero_based'
        or type(boundary.get('grid_ordinal')) is not int
        or boundary['grid_ordinal'] != ordinal
        or type(boundary.get('slot_index')) is not int
        or boundary['slot_index'] != ordinal
        or type(boundary.get('epoch_id')) is not int or boundary['epoch_id'] != epoch_id
        or boundary.get('calendar_id') != calendar_id
        or type(boundary.get('cohort_id')) is not str or not boundary['cohort_id']
        or type(boundary.get('batch_id')) is not str or not boundary['batch_id']
        or boundary.get('engine_phase') not in ('prenext_ready', 'grid_recorded')
        or type(cohort) is not dict
        or cohort.get('status') != 'OBSERVED'
        or cohort.get('cohort_id') != boundary['cohort_id']
        or type(cohort.get('epoch_id')) is not int or cohort['epoch_id'] != epoch_id
    ):
        return None

    lines = sample.get('lines')
    cohort_capacity = sample.get('cohort')
    diagnostics = sample.get('diagnostics')
    strategy_events = sample.get('strategy_events')
    orders = sample.get('orders')
    status_allowlist = ('OBSERVED', 'INCOMPLETE', 'UNAVAILABLE', 'UNSTABLE_OR_OVER_CAPACITY')

    def count(group, key):
        return _capacity_count(group.get(key)) if type(group) is dict else None

    def status(group, required_counts=(), required_booleans=()):
        if type(group) is not dict:
            return 'UNAVAILABLE'
        value = group.get('status')
        if value not in status_allowlist:
            return 'UNAVAILABLE'
        if value == 'OBSERVED':
            if any(count(group, key) is None for key in required_counts):
                return 'INCOMPLETE'
            if any(type(group.get(key)) is not bool for key in required_booleans):
                return 'INCOMPLETE'
        return value

    line_status = status(
        lines,
        (
            'graph_node_count', 'graph_reference_count', 'graph_node_limit',
            'graph_reference_limit', 'line_buffer_count', 'bounded_line_buffer_count',
            'unbounded_line_buffer_count', 'line_capacity_unavailable_count',
            'unobservable_line_reference_count', 'unobservable_line_collection_count',
            'line_capacity_sum', 'max_line_capacity', 'retained_line_value_count',
            'bounded_retained_line_value_count', 'unbounded_retained_line_value_count',
            'max_retained_values_per_line', 'value_line_count', 'reason_line_count',
        ),
        ('observation_complete',),
    )
    if line_status == 'OBSERVED' and (
        lines.get('observation_complete') is not True
        or lines.get('retained_line_value_count_status') != 'OBSERVED'
        or count(lines, 'line_buffer_count') <= 0
        or count(lines, 'line_capacity_unavailable_count') != 0
        or count(lines, 'unobservable_line_reference_count') != 0
        or count(lines, 'unobservable_line_collection_count') != 0
        or count(lines, 'line_buffer_count')
        != count(lines, 'bounded_line_buffer_count')
        + count(lines, 'unbounded_line_buffer_count')
        + count(lines, 'line_capacity_unavailable_count')
        or count(lines, 'retained_line_value_count')
        != count(lines, 'bounded_retained_line_value_count')
        + count(lines, 'unbounded_retained_line_value_count')
        or count(lines, 'graph_node_count') > count(lines, 'graph_node_limit')
        or count(lines, 'graph_reference_count') > count(lines, 'graph_reference_limit')
    ):
        line_status = 'INCOMPLETE'

    cohort_fields = (
        'member_count', 'pending_slot_count', 'pending_bar_count', 'max_pending_slots',
        'max_pending_bars', 'window_receipt_count', 'window_receipt_limit',
        'window_receipt_member_limit', 'recent_signature_count',
        'recent_signature_order_count', 'recent_signature_limit',
        'diagnostic_gap_count', 'diagnostic_gap_limit',
    )
    cohort_status = status(
        cohort_capacity, cohort_fields,
        ('window_receipt_member_limits_match', 'limits_respected'),
    )
    if cohort_status == 'OBSERVED' and (
        cohort_capacity.get('window_receipt_member_limits_match') is not True
        or cohort_capacity.get('limits_respected') is not True
    ):
        cohort_status = 'INCOMPLETE'

    diagnostic_status = status(
        diagnostics,
        ('factor_count', 'call_count', 'once_range_count', 'call_sample_count',
         'once_range_sample_count'),
        ('call_samples_bounded', 'once_range_samples_bounded'),
    )
    sample_limits = diagnostics.get('sample_limits') if type(diagnostics) is dict else None
    if (
        diagnostic_status == 'OBSERVED'
        and (
            diagnostics.get('call_samples_bounded') is not True
            or diagnostics.get('once_range_samples_bounded') is not True
            or type(sample_limits) not in (tuple, list)
            or not sample_limits
            or len(sample_limits) > 100_000
            or any(type(value) is not int or not 0 < value < (1 << 63) for value in sample_limits)
        )
    ):
        diagnostic_status = 'INCOMPLETE'
    projected_sample_limits = (
        sorted(set(sample_limits))
        if type(sample_limits) in (tuple, list)
        and len(sample_limits) <= 100_000
        and all(type(value) is int and 0 < value < (1 << 63) for value in sample_limits)
        else None
    )

    event_rows = strategy_events.get('events') if type(strategy_events) is dict else None
    projected_events = {}
    event_counts = []
    event_projection_complete = type(event_rows) is dict
    for name in ('order_events', 'trade_events'):
        event = event_rows.get(name) if type(event_rows) is dict else None
        event_count = count(event, 'count')
        event_limit = count(event, 'limit')
        event_bounded = event.get('bounded') if type(event) is dict else None
        explicit_unbounded = (
            type(event) is dict
            and 'limit' in event
            and event.get('limit') is None
            and event_bounded is False
        )
        event_status = 'OBSERVED'
        limit_status = 'OBSERVED'
        if type(event) is not dict:
            event_status = 'UNAVAILABLE'
            limit_status = 'UNKNOWN'
            event_projection_complete = False
        elif event_count is None or type(event_bounded) is not bool:
            event_status = 'INCOMPLETE'
            limit_status = 'UNKNOWN'
            event_projection_complete = False
        elif explicit_unbounded:
            event_status = 'INCOMPLETE'
            limit_status = 'UNBOUNDED'
            event_projection_complete = False
        elif event_limit is None or event_limit <= 0:
            event_status = 'INCOMPLETE'
            limit_status = 'UNKNOWN'
            event_projection_complete = False
        elif event_bounded != (event_count <= event_limit) or event_bounded is not True:
            event_status = 'INCOMPLETE'
            event_projection_complete = False
        if event_count is not None:
            event_counts.append(event_count)
        projected_events[name] = {
            'status': event_status,
            'count': event_count,
            'limit': event_limit,
            'limit_status': limit_status,
            'bounded': event_bounded if type(event_bounded) is bool else None,
        }
    event_status = status(strategy_events)
    if event_status == 'OBSERVED' and not event_projection_complete:
        event_status = 'INCOMPLETE'

    order_status = status(
        orders,
        ('active_order_count', 'unknown_order_count', 'terminal_order_count',
         'dispatching_order_count', 'terminal_order_limit'),
        ('active_unknown_bounded', 'terminal_limit_respected'),
    )
    if order_status == 'OBSERVED' and (
        orders.get('active_unknown_limit', 'missing') is not None
        or orders.get('active_unknown_bounded') is not False
        or count(orders, 'terminal_order_limit') <= 0
        or orders.get('terminal_limit_respected') is not True
        or count(orders, 'terminal_order_count') > count(orders, 'terminal_order_limit')
    ):
        order_status = 'INCOMPLETE'

    sample_utc = _capacity_utc_timestamp(sample.get('sampled_at_utc'))
    sample_mono_before = _capacity_count(sample.get('utc_monotonic_before_ns'))
    sample_mono_after = _capacity_count(sample.get('utc_monotonic_after_ns'))
    capture_mono = _capacity_count(sample.get('capture_monotonic_ns'))
    boundary_utc = _capacity_count(boundary.get('system_utc_epoch_ns'))
    boundary_mono_before = _capacity_count(boundary.get('monotonic_before_ns'))
    boundary_mono_after = _capacity_count(boundary.get('monotonic_after_ns'))
    time_status = 'OBSERVED'
    if (
        sample_utc is None
        or sample_mono_before is None
        or sample_mono_after is None
        or capture_mono is None
        or boundary_utc is None
        or boundary_mono_before is None
        or boundary_mono_after is None
        or boundary_mono_before > boundary_mono_after
        or boundary_mono_after > sample_mono_before
        or sample_mono_before > sample_mono_after
        or sample_mono_after > capture_mono
    ):
        time_status = 'INCOMPLETE'

    projected_status = sample['status']
    if projected_status == 'OBSERVED' and (
        time_status != 'OBSERVED'
        or any(value != 'OBSERVED' for value in
               (line_status, cohort_status, diagnostic_status, event_status, order_status))
    ):
        projected_status = 'INCOMPLETE'

    counts = {
        'graph_nodes': count(lines, 'graph_node_count'),
        'graph_references': count(lines, 'graph_reference_count'),
        'line_buffers': count(lines, 'line_buffer_count'),
        'bounded_line_buffers': count(lines, 'bounded_line_buffer_count'),
        'unbounded_line_buffers': count(lines, 'unbounded_line_buffer_count'),
        'line_capacity_unavailable': count(lines, 'line_capacity_unavailable_count'),
        'unobservable_line_references': count(lines, 'unobservable_line_reference_count'),
        'unobservable_line_collections': count(lines, 'unobservable_line_collection_count'),
        'line_capacity_sum': count(lines, 'line_capacity_sum'),
        'retained_line_values': count(lines, 'retained_line_value_count'),
        'bounded_retained_line_values': count(lines, 'bounded_retained_line_value_count'),
        'unbounded_retained_line_values': count(lines, 'unbounded_retained_line_value_count'),
        'value_lines': count(lines, 'value_line_count'),
        'reason_lines': count(lines, 'reason_line_count'),
        'factor_nodes': count(diagnostics, 'factor_count'),
        'cohort_members': count(cohort_capacity, 'member_count'),
        'pending_cohort_slots': count(cohort_capacity, 'pending_slot_count'),
        'pending_cohort_bars': count(cohort_capacity, 'pending_bar_count'),
        'window_receipts': count(cohort_capacity, 'window_receipt_count'),
        'recent_signatures': count(cohort_capacity, 'recent_signature_count'),
        'recent_signature_order': count(cohort_capacity, 'recent_signature_order_count'),
        'diagnostic_gaps': count(cohort_capacity, 'diagnostic_gap_count'),
        'strategy_events': sum(event_counts) if event_projection_complete else None,
        'active_orders': count(orders, 'active_order_count'),
        'unknown_orders': count(orders, 'unknown_order_count'),
        'terminal_orders': count(orders, 'terminal_order_count'),
        'dispatching_orders': count(orders, 'dispatching_order_count'),
    }
    return {
        'ordinal': ordinal,
        'status': projected_status,
        'batch_id': boundary['batch_id'],
        'cohort_id': boundary['cohort_id'],
        'epoch_id': epoch_id,
        'calendar_id': calendar_id,
        'engine_phase': boundary['engine_phase'],
        'capture_time': {
            'status': time_status,
            'utc_clock_domain': 'SYSTEM_UTC',
            'sampled_at_utc': sample_utc,
            'ready_boundary_system_utc_epoch_ns': boundary_utc,
            'monotonic_clock_domain': 'OS_MONOTONIC_NS',
            'ready_boundary_monotonic_before_ns': boundary_mono_before,
            'ready_boundary_monotonic_after_ns': boundary_mono_after,
            'sample_monotonic_before_ns': sample_mono_before,
            'sample_monotonic_after_ns': sample_mono_after,
            'capture_monotonic_ns': capture_mono,
        },
        'capacity_status': {
            'lines': line_status,
            'cohort': cohort_status,
            'factor_diagnostics': diagnostic_status,
            'strategy_events': event_status,
            'orders': order_status,
        },
        'counts': counts,
        'work_counters': {
            'factor_calls': count(diagnostics, 'call_count'),
            'factor_once_ranges': count(diagnostics, 'once_range_count'),
            'factor_call_samples': count(diagnostics, 'call_sample_count'),
            'factor_once_range_samples': count(diagnostics, 'once_range_sample_count'),
        },
        'capacity_limits': {
            'lines': {
                'graph_node_limit': count(lines, 'graph_node_limit'),
                'graph_reference_limit': count(lines, 'graph_reference_limit'),
                'observation_complete': (
                    lines.get('observation_complete')
                    if type(lines) is dict and type(lines.get('observation_complete')) is bool else None
                ),
                'bounded_line_capacity_sum': count(lines, 'line_capacity_sum'),
                'max_line_capacity': count(lines, 'max_line_capacity'),
                'unbounded_line_buffers': count(lines, 'unbounded_line_buffer_count'),
                'line_capacity_unavailable_count': count(lines, 'line_capacity_unavailable_count'),
                'max_retained_values_per_line': count(lines, 'max_retained_values_per_line'),
                'retained_value_classification_status': (
                    lines.get('retained_line_value_count_status')
                    if type(lines) is dict else None
                ),
            },
            'cohort': {
                key: count(cohort_capacity, key)
                for key in (
                    'max_pending_slots', 'max_pending_bars', 'window_receipt_limit',
                    'window_receipt_member_limit', 'recent_signature_limit',
                    'diagnostic_gap_limit',
                )
            },
            'factor_diagnostics': {
                'call_samples_bounded': (
                    diagnostics.get('call_samples_bounded')
                    if type(diagnostics) is dict else None
                ),
                'once_range_samples_bounded': (
                    diagnostics.get('once_range_samples_bounded')
                    if type(diagnostics) is dict else None
                ),
                'sample_limits': projected_sample_limits,
            },
            'strategy_events': projected_events,
            'orders': {
                'active_unknown_limit': (
                    orders.get('active_unknown_limit') if type(orders) is dict else None
                ),
                'active_unknown_limit_status': (
                    'UNBOUNDED'
                    if type(orders) is dict
                    and orders.get('active_unknown_limit', 'missing') is None
                    and orders.get('active_unknown_bounded') is False
                    else 'UNKNOWN'
                ),
                'active_unknown_bounded': (
                    orders.get('active_unknown_bounded')
                    if type(orders) is dict
                    and type(orders.get('active_unknown_bounded')) is bool else None
                ),
                'terminal_order_limit': count(orders, 'terminal_order_limit'),
                'terminal_limit_respected': (
                    orders.get('terminal_limit_respected')
                    if type(orders) is dict
                    and type(orders.get('terminal_limit_respected')) is bool else None
                ),
            },
        },
    }


def public_live_capacity(summary, config):
    """Project count-only run capture and bind it to this R10 target call."""
    base = {
        'status': 'INCOMPLETE',
        'reason_code': 'LIVE_CAPACITY_REPORT_UNAVAILABLE',
        'acceptance_evaluated': False,
        'window_evaluation': 'NOT_EVALUATED',
        'growth_evaluation': 'NOT_EVALUATED',
        'stability_peak_claimed': False,
        'samples': [],
    }
    report = summary.get('live_capacity') if type(summary) is dict else None
    if type(report) is not dict:
        return base
    live_cfg = config.get('live') if type(config) is dict else None
    cohort_cfg = config.get('cohort') if type(config) is dict else None
    identity = MEMORY_TARGET_IDENTITY if type(MEMORY_TARGET_IDENTITY) is dict else None
    run_uuid = MEMORY_RUN_ID
    if (
        type(live_cfg) is not dict or type(cohort_cfg) is not dict
        or type(identity) is not dict
        or type(run_uuid) is not str or not re.fullmatch(r'i51-[0-9a-f]{32}', run_uuid)
    ):
        base['reason_code'] = 'LIVE_CAPACITY_CALL_CONTEXT_UNAVAILABLE'
        return base
    logical_run_id = live_cfg.get('logical_run_id')
    epoch_id = cohort_cfg.get('epoch_id')
    calendar_id = cohort_cfg.get('calendar_id')
    pid = identity.get('pid')
    create_time = identity.get('create_time')
    if (
        type(logical_run_id) is not str or not logical_run_id
        or type(epoch_id) is not int or epoch_id <= 0
        or type(calendar_id) is not str or not calendar_id
        or type(pid) is not int or pid <= 0
        or type(create_time) not in (int, float) or not math.isfinite(create_time)
        or create_time <= 0
    ):
        base['reason_code'] = 'LIVE_CAPACITY_CALL_CONTEXT_INVALID'
        return base

    process_identity = report.get('process_identity')
    samples = report.get('samples')
    expected_ordinals = report.get('expected_ordinals')
    sample_count = report.get('sample_count')
    max_samples = report.get('max_samples')
    issues = report.get('issues')
    if (
        report.get('schema') != 'backtrader.live_capacity_run_report.v1'
        or type(report.get('run_id')) is not str or report['run_id'] != logical_run_id
        or type(report.get('epoch_id')) is not int or report['epoch_id'] != epoch_id
        or type(report.get('calendar_id')) is not str or report['calendar_id'] != calendar_id
        or report.get('status') not in ('RECORDED_NOT_EVALUATED', 'INCOMPLETE')
        or report.get('acceptance_evaluated') is not False
        or report.get('window_evaluation') != 'NOT_EVALUATED'
        or report.get('growth_evaluation') != 'NOT_EVALUATED'
        or report.get('stability_peak_claimed') is not False
        or type(process_identity) is not dict
        or process_identity.get('status') != 'OBSERVED'
        or type(process_identity.get('pid')) is not int
        or process_identity['pid'] != pid
        or type(process_identity.get('create_time')) not in (int, float)
        or not math.isfinite(process_identity['create_time'])
        or process_identity['create_time'] != create_time
        or type(samples) not in (tuple, list) or len(samples) > 16
        or type(expected_ordinals) not in (tuple, list) or len(expected_ordinals) > 16
        or not samples or not expected_ordinals
        or type(sample_count) is not int or sample_count != len(samples)
        or type(max_samples) is not int or not 1 <= max_samples <= 16
        or len(samples) > max_samples
        or any(type(value) is not int or value < 0 for value in expected_ordinals)
        or any(left >= right for left, right in zip(expected_ordinals, expected_ordinals[1:]))
        or len(samples) > len(expected_ordinals)
        or type(issues) not in (tuple, list) or len(issues) > 32
    ):
        base['reason_code'] = 'LIVE_CAPACITY_REPORT_BINDING_INVALID'
        return base

    projected_samples = []
    for index, sample in enumerate(samples):
        projection = _capacity_sample_projection(
            sample,
            logical_run_id=logical_run_id,
            pid=pid,
            create_time=create_time,
            epoch_id=epoch_id,
            calendar_id=calendar_id,
        )
        if projection is None or projection['ordinal'] != expected_ordinals[index]:
            base['reason_code'] = 'LIVE_CAPACITY_SAMPLE_BINDING_INVALID'
            return base
        projected_samples.append(projection)

    complete = (
        report['status'] == 'RECORDED_NOT_EVALUATED'
        and len(samples) == len(expected_ordinals)
        and all(sample['status'] == 'OBSERVED' for sample in projected_samples)
        and not issues
    )
    return {
        'status': 'BOUND_RECORDED_NOT_EVALUATED' if complete else 'BOUND_INCOMPLETE',
        'reason_code': None if complete else 'LIVE_CAPACITY_CAPTURE_INCOMPLETE',
        'acceptance_evaluated': False,
        'window_evaluation': 'NOT_EVALUATED',
        'growth_evaluation': 'NOT_EVALUATED',
        'stability_peak_claimed': False,
        'report_status': report['status'],
        'issue_count': len(issues),
        'sample_count': sample_count,
        'max_samples': max_samples,
        'expected_ordinals': list(expected_ordinals),
        'binding': {
            'association': 'SAME_TARGET_RUN_CALL_CONTEXT',
            'supervisor_run_uuid': run_uuid,
            'logical_run_id': logical_run_id,
            'root_pid': pid,
            'root_create_time': create_time,
            'epoch_id': epoch_id,
            'calendar_id': calendar_id,
        },
        'samples': projected_samples,
    }


def public_summary(summary, runner, config):
    routes = summary.get('routes')
    count = len(routes) if type(routes) is dict else None
    tape = summary.get('decision_tape')
    tape = tape if type(tape) is dict else {}
    plan = summary.get('_plan')
    grid = plan.get('grid') if type(plan) is dict else None
    grid_to_dict = getattr(grid, 'to_dict', None)
    try:
        grid_row = grid_to_dict() if callable(grid_to_dict) else None
        grid_minutes = (len(grid_row.get('minutes'))
                        if type(grid_row) is dict and type(grid_row.get('minutes')) is list else None)
    except Exception:
        grid_minutes = None
    def count_or_none(value):
        return value if type(value) is int and 0 <= value < (1 << 63) else None
    return {
        'run_returned_complete': summary.get('status') == 'LIVE_RUN_COMPLETE',
        'target_count': count,
        'expected_full_target_count_matches': count == 87,
        'same_run_plan_target_count': (len(plan.get('targets'))
                                       if type(plan) is dict and type(plan.get('targets')) in (tuple, list) else None),
        'same_run_plan_grid_minutes': grid_minutes,
        'factor_mode_native': summary.get('factor_mode') == 'native',
        'write_mode_disabled': summary.get('write_mode') is False,
        'cleanup_complete': summary.get('cleanup_complete') is True,
        'normal_epoch_retired': runner._live_epoch_retired(summary),
        'controlled_stop': runner._live_epoch_controlled_stopped(summary),
        'strategy_ready_to_close': summary.get('strategy_shutdown_ready') is True,
        'strategy_post_join_confirmed': summary.get('strategy_shutdown_post_join_confirmed') is True,
        'decision_tape_records': count_or_none(tape.get('record_count')),
        'full_grid_record_count_matches': type(tape.get('record_count')) is int and tape['record_count'] == 195,
        'decision_tape_bytes': count_or_none(tape.get('bytes')),
        'live_capacity': public_live_capacity(summary, config),
        'resources': public_cleanup(summary.get('resource_shutdown')),
    }


def main():
    if DRAFT_UNEXECUTABLE:
        raise RuntimeError('R9_DRAFT_UNEXECUTABLE')
    if sys.flags.isolated != 1 or sys.flags.interactive != 1:
        raise RuntimeError('ISOLATED_INTERACTIVE_HOST_REQUIRED')
    if OUTPUT.exists() or RUN_ROOT.exists() or not PRIVATE_TEMP.is_dir():
        raise RuntimeError('FRESH_NAMESPACE_REQUIRED')
    verify_sources()
    local = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    # This is only an attempt window; pre-open query/subscription availability is unproven.
    # The same-run 195-slot tape validator is decisive; subscribe return is not acknowledgement.
    if local.strftime('%Y%m%d') != '20261028' or not ('08:30' <= local.strftime('%H:%M') < '08:35'):
        raise RuntimeError('GOLDEN_MINUTE_START_WINDOW_REQUIRED')
    tempfile.tempdir = str(PRIVATE_TEMP)
    os.environ['TEMP'] = os.environ['TMP'] = str(PRIVATE_TEMP)
    sys.path.insert(0, str(EXAMPLE))
    import backtrader
    import backtrader_runtime
    protected_simnow = load_public_module(
        'protected_simnow', EXAMPLE / 'protected_simnow.py', register=True
    )
    generated_strategy = load_public_module(
        STRATEGY_MODULE_KEY, STRATEGY_MODULE_PATH, register=True
    )
    entry_tier = load_public_module('entry_tier', EXAMPLE / 'entry_tier.py', register=True)
    if sys.modules.get('entry_tier') is not entry_tier:
        raise RuntimeError('ENTRY_TIER_MODULE_BINDING_INVALID')
    runner = load_public_module('run', EXAMPLE / 'run.py', register=True)
    verify_loaded_live_runner(runner, generated_strategy)
    for module in (backtrader, backtrader_runtime):
        if not Path(module.__file__).resolve().is_relative_to(CONSUMER):
            raise RuntimeError('INSTALLED_ORIGIN_REQUIRED')
    from backtrader_runtime.capability_imports import trusted_installed_capability_import_context
    with trusted_installed_capability_import_context(('bt_api_base', 'bt_api_ctp')):
        import bt_api_ctp
        import bt_api_ctp.ctp.client as sdk_client
        import bt_api_ctp.md_identity as sdk_md_identity
    for module in (bt_api_ctp, sdk_client, sdk_md_identity):
        if not Path(module.__file__).resolve().is_relative_to(CONSUMER):
            raise RuntimeError('SDK_INSTALLED_ORIGIN_REQUIRED')
    config = load_pinned_profile(runner)
    mode, decision = runner.resolve_mode(config, None)
    factor_mode, direction, _, _ = runner._factor_parameters(config, None)
    if not (mode == decision.effective_tier == 'live' and factor_mode == 'native'
            and config['selection']['source'] == 'ctp_query'
            and config['selection']['query_mode'] == 'staged_product_set'
            and config['selection']['authorized_products'] is None
            and config['selection']['max_epochs'] == 1
            and config['live']['allow_writes'] is False
            and config['live']['golden_targets'] is None
            and config['live']['arm_templates'] == []
            and config['cohort']['clock_domain_id'] == 'i51-md-20261028-fullpool-r9'
            and config['cohort']['epoch_id'] == 1):
        raise RuntimeError('FULL_POOL_READONLY_PROFILE_REQUIRED')
    for key in ('journal_path',):
        if Path(config['live'][key]).parent != RUN_ROOT:
            raise RuntimeError('OUTPUT_ROOT_MISMATCH')
    if Path(config['output']['decision_tape_path']).parent != RUN_ROOT:
        raise RuntimeError('OUTPUT_ROOT_MISMATCH')
    if Path(config['output']['directory']) != RUN_ROOT / 'output':
        raise RuntimeError('OUTPUT_ROOT_MISMATCH')
    observer = load_public_module('i51_root_write_observer', WRITE_OBSERVER)
    span = load_public_module('i51_root_span_capture', SPAN_HELPER)
    postflight = load_public_module('i51_fullpool_golden_postflight', POSTFLIGHT_HELPER)
    saved_tape_validator = load_public_module('i51_saved_factor_tape_validator', SAVED_TAPE_VALIDATOR)
    # This legacy field describes the R9 target's own scope. R10's sibling
    # sampler reports same-run process-tree RSS separately in its result.
    result = {'schema': 'i51_root_golden_fullpool_readonly.r9.v1', 'status': 'PREPARING',
              'root_pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
              'phase': 'protected_configuration', 'allow_writes': False,
              'expected_targets': 87, 'required_witness_targets': ['DCE.I', 'SHFE.RB', 'CZCE.MA'],
              'expected_grid_minutes': 195, 'minimum_runtime_seconds': 7200,
              'expected_dev_head': EXPECTED_DEV_HEAD,
              'query_mode': config['selection']['query_mode'], 'source_pins': PUBLIC_PINS,
              'installed_record_pins': {'backtrader': BT_RECORD_SHA, 'bt_api_ctp': SDK_RECORD_SHA},
              'process_tree_memory_observation': 'NOT_RUN_IN_R9',
              'memory_binding': _memory_binding_projection(),
              'validated_tape_availability': {'status': 'NOT_VALIDATED'},
              'full_factor_acceptance': False, 'account_acceptance': False,
              'private_values_exported': False}
    ROOT_STATE['result'] = result
    persist(result)
    stack = ExitStack()
    mute = NativeOutputMute()
    ROOT_STATE.update(stack=stack, mute=mute, closed=False, observer_sink={})
    mute.enter()
    live_entered = False
    closed = False
    summary = None
    run_duration_seconds = None
    try:
        handoff = stack.enter_context(protected_simnow.protected_simnow_store_config(selected_config_index=0))
        ROOT_STATE['handoff'] = handoff
        if handoff.profile != 'set1_group1_vpn':
            raise RuntimeError('OFFICIAL_PROFILE_CATEGORY_MISMATCH')
        private_mapping = handoff.for_runner()
        # The accepted SDK compatibility mode is read-only and does not invent
        # an authenticated MD identity. The public runner still disables writes.
        override = {'config': private_mapping['config'],
                    'api_kwargs': {'ctp_join_observer': False, 'allow_zero_login_response': True}}
        RUN_ROOT.mkdir()
        (RUN_ROOT / 'output').mkdir()
        result.update(status='RUNNING', phase='run_live', profile_category=handoff.profile)
        run_started_at_utc = datetime.now(timezone.utc)
        result['live_call_window'] = {
            'started_at_utc': run_started_at_utc.isoformat(),
            'returned_at_utc': None,
            'runner_call_returned': False,
        }
        persist(result)
        live_entered = True
        run_started = time.monotonic()
        run_call_returned = False
        try:
            publish_run_start_record()
            summary = span.invoke_with_readonly_span_observation(
                runner.run_live, observer, ROOT_STATE['observer_sink'],
                config, PROFILE, None, factor_mode, direction,
                decision=decision, allow_write_flag=False,
                _live_store_config_override=override,
                _live_ready_callback=publish_live_ready_record,
                _live_next_callback=publish_live_next_record,
                _include_plan=True,
                _capture_live_capacity=True,
                # Conservative session cutoff after the public day session.
                # The accepted 195-slot count still comes from this run's plan.
                shutdown_deadline_utc=datetime(2026, 10, 28, 7, 10, 0, tzinfo=timezone.utc),
            )
            run_call_returned = True
        finally:
            run_duration_seconds = time.monotonic() - run_started
            result['live_call_window']['returned_at_utc'] = datetime.now(
                timezone.utc
            ).isoformat()
            result['live_call_window']['runner_call_returned'] = run_call_returned
        ROOT_STATE['summary'] = summary
        result['run'] = public_summary(summary, runner, config)
        cleanup = summary.get('resource_shutdown')
        closed = (summary.get('cleanup_complete') is True and runner._cleanup_complete(cleanup)
                  and ROOT_STATE['observer_sink'].get('timer_joined') is True)
        result['status'] = 'FULL_POOL_RUN_RETURNED_REQUIRES_TAPE_VALIDATION'
    except BaseException as error:
        ROOT_STATE['original_error'] = error
        # Never export arbitrary exception code/text, causes, frame locals, or
        # account snapshots. Keep original objects privately if cleanup is unsure.
        result['status'] = 'BLOCKED_ROOT_GOLDEN_MINUTE_READONLY'
        result['reason'] = 'RUN_LIVE_FAILED' if live_entered else 'PROTECTED_SETUP_FAILED'
        if (type(error) is runner.RunnerError and type(error.code) is str
                and error.code in PUBLIC_RUNNER_ERROR_CODES):
            result['reason'] = error.code
            if error.code == 'CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED':
                detail = getattr(error, 'detail', None)
                allowed_details = getattr(runner, '_CTP_FUTURES_SNAPSHOT_ERROR_CODES', None)
                result['snapshot_failure_detail'] = bounded_snapshot_failure_detail(detail, allowed_details)
                result['snapshot_query_diagnostics'] = runner._sanitize_ctp_query_diagnostics(
                    getattr(error, 'query_diagnostics', None)
                )
        capture_count = ROOT_STATE['observer_sink'].get('capture_count')
        result['engine_span_reached'] = (capture_count == 1) if type(capture_count) is int else None
        cleanup = getattr(error, 'cleanup_results', None)
        result['resources'] = public_cleanup(cleanup)
        closed = (not live_entered) or (
            ROOT_STATE['observer_sink'].get('cleanup_confirmed') is True
            and ROOT_STATE['observer_sink'].get('timer_joined') is True
        )
    finally:
        result['observation'] = ROOT_STATE['observer_sink']
        result['write_surfaces_observed_zero'] = bool(
            ROOT_STATE['observer_sink'].get('status') == 'FINISHED'
            and ROOT_STATE['observer_sink'].get('write_zero_confirmed') is True
        )
        result['native_cleanup_confirmed'] = (
            ROOT_STATE['observer_sink'].get('cleanup_confirmed') is True
        ) if live_entered else None
        result['timer_joined'] = ROOT_STATE['observer_sink'].get('timer_joined')
        if closed:
            stack.close()
            # Drop traceback/private-mapping ownership before restoring output.
            ROOT_STATE.pop('original_error', None)
            ROOT_STATE.pop('handoff', None)
            mute.close()
            ROOT_STATE['closed'] = True
        else:
            result['status'] = 'BLOCKED_RETAINED_GOLDEN_CUSTODY'
        result['private_context_closed'] = ROOT_STATE['closed']
        if ROOT_STATE['closed'] is True and MEMORY_CONTROL is not None:
            publish_close_record(summary, closed=True)
        if summary is not None and ROOT_STATE['closed'] is True:
            normal_cleanup_complete = bool(
                result.get('native_cleanup_confirmed') is True
                and result.get('private_context_closed') is True
                and result.get('timer_joined') is True
            )
            if normal_cleanup_complete:
                cohort_cfg = config['cohort']
                expected_cohort = {
                    'cohort_id': (
                        f"alpha003:{cohort_cfg['calendar_id']}:{cohort_cfg['epoch_id']}"
                    ),
                    'calendar_version': cohort_cfg['calendar_version'],
                    'epoch_id': cohort_cfg['epoch_id'],
                    'timezone_id': cohort_cfg['timezone_id'],
                }
                try:
                    postflight_facts = postflight.validate_fullpool_postflight(
                        runner,
                        saved_tape_validator,
                        summary,
                        clock_domain_id=cohort_cfg['clock_domain_id'],
                        calendar_id=cohort_cfg['calendar_id'],
                        expected_cohort=expected_cohort,
                        normal_cleanup_complete=True,
                        zero_writes_confirmed=(result.get('write_surfaces_observed_zero') is True
                                               and config['live']['allow_writes'] is False),
                        controlled_stop_confirmed=runner._live_epoch_controlled_stopped(summary) is True,
                        epoch_retired_confirmed=runner._live_epoch_retired(summary) is True,
                        run_duration_seconds=run_duration_seconds,
                        direction=direction,
                        preheat_bars=config['factor']['preheat_bars'],
                    )
                    if type(postflight_facts) is not dict or postflight_facts.get(
                        'status'
                    ) not in ('PASS', 'FAIL'):
                        postflight_facts = {
                            'status': 'FAIL',
                            'code': 'POSTFLIGHT_RESULT_INVALID',
                        }
                except BaseException:
                    postflight_facts = {
                        'status': 'FAIL',
                        'code': 'POSTFLIGHT_VALIDATION_FAILED',
                    }
                result['postflight'] = postflight_facts
                if postflight_facts['status'] == 'PASS':
                    result['live_call_window']['first_qualified_source_available_at_utc'] = postflight_facts.get(
                        'first_full_cohort_live_ready_available_at_utc'
                    )
                    result['live_call_window']['source_time_marker_kind'] = (
                        'TAPE_EVENT_WATERMARK_NOT_OS_WALL_CLOCK'
                    )
                    result['validated_tape_availability'] = {
                        'status': 'VERIFIED',
                        'validated_at_utc': datetime.now(timezone.utc).isoformat(),
                        'file_id': postflight_facts.get('tape_file_id'),
                        'sha256': postflight_facts.get('tape_sha256'),
                        'bytes': postflight_facts.get('tape_bytes'),
                        'record_count': postflight_facts.get('decision_record_count'),
                    }
                    result['status'] = 'FULL_POOL_POSTFLIGHT_PASS'
                else:
                    # Tape failure is a validation result; the already-closed
                    # host and private/native cleanup remain closed.
                    result['status'] = 'FULL_POOL_POSTFLIGHT_FAIL'
            else:
                result['postflight'] = {
                    'status': 'NOT_RUN',
                    'code': 'NORMAL_CLEANUP_NOT_CONFIRMED',
                }
        else:
            result['postflight'] = {
                'status': 'NOT_RUN',
                'code': 'RUN_SUMMARY_OR_NORMAL_CLOSE_UNAVAILABLE',
            }
        result['phase'] = 'complete' if closed else 'retained'
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        verify_sources()
        result['source_pins_unchanged'] = True
        if summary is not None and result.get('private_context_closed') is True:
            try:
                checks = postflight.fullpool_acceptance_checks(result)
                if type(checks) is not dict or not checks or any(
                    type(value) is not bool for value in checks.values()
                ):
                    checks = {'aggregate_facts_valid': False}
            except BaseException:
                checks = {'aggregate_facts_valid': False}
            passed = bool(checks) and all(value is True for value in checks.values())
            result['fullpool_acceptance_checks'] = checks
            result['fullpool_tape_witness_pass'] = passed
            result['status'] = (
                'FULL_POOL_TAPE_WITNESS_PASS'
                if passed else 'FULL_POOL_TAPE_WITNESS_ACCEPTANCE_FAIL'
            )
        persist(result)
    if closed:
        print(json.dumps({'status': result['status'], 'native_cleanup_confirmed': result['native_cleanup_confirmed']}))


def _dispatch_r10():
    parser = argparse.ArgumentParser(description='Draft R10 full-pool read-only caller/supervisor')
    parser.add_argument('--mode', choices=('supervisor', 'target'), required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--control-dir', type=Path)
    parser.add_argument('--execute-bound-readonly-run', action='store_true')
    args = parser.parse_args()
    if DRAFT_UNEXECUTABLE or not R10_SUPERVISOR_ENABLED:
        print(json.dumps({'status': 'DRAFT_UNEXECUTABLE', 'memory_acceptance': 'NOT_EVALUATED'}))
        return 2
    if args.mode == 'target':
        if args.run_id is None or args.control_dir is None:
            print(json.dumps({'status': 'R10_TARGET_ARGUMENTS_INVALID'}))
            return 2
        try:
            _target_main(args.run_id, args.control_dir)
            raise SystemExit(0)
        except SystemExit:
            raise
        except BaseException:
            failed = ROOT_STATE.get('result', {'schema': 'i51_root_golden_fullpool_readonly.r10.v1'})
            failed.update(status='BLOCKED_R10_TARGET', reason='R10_TARGET_FAILURE')
            try:
                persist(failed)
            except BaseException:
                pass
            return 2
    result = supervisor_main(execute_bound_readonly_run=args.execute_bound_readonly_run)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') == 'WINDOWS_RECORDED' else 2


if __name__ == '__main__':
    raise SystemExit(_dispatch_r10())
