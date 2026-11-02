"""One Root-owned read-only discovery; private configuration stays in this host."""
import ctypes
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import warnings
from contextlib import ExitStack
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

EXAMPLE = Path('D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute')
CONSUMER = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1/consumer/Lib/site-packages')
OUTPUT = Path('D:/temp/i51-root-discovery-20261027-r3.json')
PRIVATE_TEMP = Path('D:/temp/i51-root-discovery-private-20261027-r3')
PINS = {
    'run.py': '3373140b1e68f3f4871ce821220117883edb0af85640bb723de19c75a1012e62',
    'protected_simnow.py': 'c4269bb9b78e40fd60843e32af5616dece5052d621258add12ba82f9696c1982',
    'discovery_lifecycle.py': '305ecf7cb89ccf8aee15179312fbf4b311f41ead7e65a97b01e19c0e3ccb3f3d',
}
ROOT_STATE = {}


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


def verify_sources():
    for name, expected in PINS.items():
        if hashlib.sha256((EXAMPLE / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('PUBLIC_SOURCE_CHANGED')


def persist(result):
    # Only this explicitly constructed finite/public-market projection is written.
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def login_projection(raw):
    day = raw['trading_day']
    generation = raw['connection_generation']
    if type(day) is not str or re.fullmatch(r'[0-9]{8}', day) is None:
        raise RuntimeError('LOGIN_DAY_INVALID')
    datetime.strptime(day, '%Y%m%d')
    if type(generation) is not int or generation <= 0:
        raise RuntimeError('LOGIN_GENERATION_INVALID')
    if raw['read_only_ready'] is not True:
        raise RuntimeError('READONLY_LOGIN_NOT_READY')
    return {'trading_day': day, 'connection_generation': generation, 'read_only_ready': True}


def public_close_projection(result):
    projection = {}
    for field in fields(result):
        value = getattr(result, field.name)
        if field.name in ('md_client', 'trader_client'):
            projection[field.name] = {item.name: getattr(value, item.name) for item in fields(value)}
        elif value is None or type(value) in (str, bool, int):
            projection[field.name] = value
        else:
            raise RuntimeError('CLOSE_PROJECTION_INVALID')
    return projection


def public_plan_projection(plan):
    manifest = plan['manifest']
    snapshot = manifest.query_snapshot
    routes = []
    for product, instrument in sorted(plan['routes'].items(), key=lambda row: (row[0].exchange_id, row[0].product_id)):
        for value in (product.exchange_id, product.product_id, instrument):
            if type(value) is not str or re.fullmatch(r'[A-Za-z0-9]{1,32}', value) is None:
                raise RuntimeError('PUBLIC_MARKET_IDENTIFIER_INVALID')
        routes.append({'exchange': product.exchange_id, 'product': product.product_id, 'instrument': instrument})
    return {
        'status': manifest.status, 'product_count': len(plan['products']),
        'selected_count': len(routes), 'catalog_rows': len(snapshot.catalog_records),
        'quote_rows': len(snapshot.quote_records), 'query_coverage_products': len(manifest.query_coverage),
        'blocker_count': len(manifest.blockers), 'routes': routes,
        'decision_at': manifest.decision_at.isoformat(),
        'grid_status': plan['grid'].status, 'grid_minutes': len(plan['grid'].minutes),
        'first_close': plan['grid'].minutes[0].close_time.isoformat(),
        'last_close': plan['grid'].minutes[-1].close_time.isoformat(),
        'calendar_rules_sha256': plan['calendar_rules_sha256'],
        'ranking_mode': manifest.policy.ranking_mode,
        'minimum_trading_days_to_expiry': manifest.policy.minimum_trading_days_to_expiry,
    }


def main():
    if OUTPUT.exists() or not PRIVATE_TEMP.is_dir():
        raise RuntimeError('FRESH_NAMESPACE_REQUIRED')
    if sys.flags.isolated != 1 or sys.flags.interactive != 1:
        raise RuntimeError('ISOLATED_INTERACTIVE_HOST_REQUIRED')
    verify_sources()
    tempfile.tempdir = str(PRIVATE_TEMP)
    os.environ['TEMP'] = str(PRIVATE_TEMP)
    os.environ['TMP'] = str(PRIVATE_TEMP)
    sys.path.insert(0, str(EXAMPLE))
    import backtrader
    import backtrader_runtime
    import protected_simnow
    import discovery_lifecycle
    import run as runner
    from backtrader.stores.registered_sim import RegisteredSimStore
    for module in (backtrader, backtrader_runtime):
        if not Path(module.__file__).resolve().is_relative_to(CONSUMER):
            raise RuntimeError('INSTALLED_ORIGIN_REQUIRED')

    result = {'schema': 1, 'status': 'RUNNING', 'phase': 'protected_handoff',
              'started_at': datetime.now(timezone.utc).isoformat(), 'selected_config_index': 3,
              'store_created': False, 'provider_attempted': False, 'allow_writes': False,
              'source_pins': PINS, 'private_values_exported': False}
    persist(result)
    stack = ExitStack()
    mute = NativeOutputMute()
    store = None
    closed = True
    ROOT_STATE.update(stack=stack, mute=mute, store=None, closed=False, result=result)
    mute.enter()
    try:
        handoff = stack.enter_context(protected_simnow.protected_simnow_store_config(selected_config_index=3))
        private_mapping = handoff.for_runner()
        runner.validate_official_simnow_store_profile(private_mapping['config'], private_mapping['api_kwargs'])
        result['phase'] = 'store_creation'
        persist(result)
        wrapper_api_kwargs = dict(private_mapping['api_kwargs'])
        wrapper_api_kwargs['ctp_join_observer'] = False
        wrapper_api_kwargs['allow_zero_login_response'] = True
        store = RegisteredSimStore(provider='ctp', backend='direct', allow_writes=False,
                                   preserve_raw_bars=True, config=private_mapping['config'],
                                   api_kwargs=wrapper_api_kwargs)
        ROOT_STATE['store'] = store
        result.update(store_created=True, phase='wait_readonly_ready', provider_attempted=True)
        closed = False
        persist(result)
        if store.registered_sim_wait_ready(timeout=30.0) is not True:
            raise RuntimeError('READONLY_LOGIN_NOT_READY')
        before = login_projection(store.registered_sim_login_facts())
        import bt_api_ctp.md_diagnostics as md_diagnostics
        md_client = store._api.md_client
        md_diagnostic = md_client.login_callback_diagnostic
        if type(md_diagnostic) is not md_diagnostics.MdLoginCallbackDiagnostic:
            raise RuntimeError('MD_READONLY_DIAGNOSTIC_INVALID')
        disposition = md_diagnostic.disposition
        if disposition not in (md_diagnostics.MdLoginCallbackDisposition.READ_ONLY_ACCEPTED,
                               md_diagnostics.MdLoginCallbackDisposition.ACCEPTED):
            raise RuntimeError('MD_READONLY_DIAGNOSTIC_INVALID')
        identity_present = md_client.active_md_identity is not None
        if disposition is md_diagnostics.MdLoginCallbackDisposition.READ_ONLY_ACCEPTED and identity_present:
            raise RuntimeError('MD_READONLY_IDENTITY_INVALID')
        result['md_login_mode'] = disposition.value
        result['authenticated_md_identity_present'] = identity_present
        result['md_zero_response_readonly_compatibility'] = True
        result.update(login=before, phase='query_full_market')
        persist(result)
        plan = runner.build_ctp_query_market_plan(store, {'selection': {'authorized_products': None}}, clock=runner.RunnerWallClock())
        after = login_projection(store.registered_sim_login_facts())
        if before != after:
            raise RuntimeError('LOGIN_SESSION_CHANGED')
        result['market_plan'] = public_plan_projection(plan)
        result['status'] = 'PASS_ROOT_READONLY_MARKET_DISCOVERY'
    except BaseException as error:
        ROOT_STATE['original_error'] = error
        result['status'] = 'BLOCKED_ROOT_READONLY_MARKET_DISCOVERY'
        # Own fixed codes only; no arbitrary exception strings, types or tracebacks.
        own_codes = {'READONLY_LOGIN_NOT_READY', 'LOGIN_DAY_INVALID', 'LOGIN_GENERATION_INVALID',
                     'LOGIN_SESSION_CHANGED', 'PUBLIC_MARKET_IDENTIFIER_INVALID',
                     'MD_READONLY_DIAGNOSTIC_INVALID', 'MD_READONLY_IDENTITY_INVALID'}
        runner_codes = {'CTP_FUTURES_SNAPSHOT_BRIDGE_UNAVAILABLE', 'CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED',
                        'CTP_FUTURES_SNAPSHOT_TYPE_INVALID', 'CTP_FUTURES_PRODUCT_POOL_UNAVAILABLE',
                        'CTP_FUTURES_TRADING_DAY_UNAVAILABLE', 'POINT_IN_TIME_SELECTION_BLOCKED',
                        'CTP_QUERY_PLAN_BUILD_FAILED', 'PLANNED_MINUTE_GRID_BLOCKED',
                        'POINT_IN_TIME_ROUTE_SET_MISMATCH', 'CTP_FUTURES_SNAPSHOT_ID_UNAVAILABLE'}
        if type(error) is runner.RunnerError and error.code in runner_codes:
            result['reason'] = error.code
        elif type(error) is RuntimeError and len(error.args) == 1 and error.args[0] in own_codes:
            result['reason'] = error.args[0]
        else:
            result['reason'] = 'OWNED_OPERATION_FAILED'
    finally:
        result['operation_phase'] = result['phase']
        result['phase'] = 'normal_close'
        try:
            persist(result)
        except BaseException as error:
            # Diagnostic I/O must never bypass native/client cleanup.
            ROOT_STATE['persistence_error'] = error
            result['result_write_failed'] = True
        if store is not None:
            try:
                close_result = discovery_lifecycle.close_discovery_store(store, timeout=10.0)
                result['close'] = public_close_projection(close_result)
                closed = close_result.complete is True
            except discovery_lifecycle.DiscoveryStoreCloseError as error:
                ROOT_STATE['close_error'] = error
                result['close'] = public_close_projection(error.result)
                closed = False
            except BaseException as error:
                ROOT_STATE['close_error'] = error
                result['close'] = {'status': 'INCOMPLETE', 'reason_code': 'close_observation_failed'}
                closed = False
        result['native_close_confirmed'] = closed if store is not None else None
        if closed:
            stack.close()
            mute.close()
            ROOT_STATE['closed'] = True
        else:
            result['status'] = 'BLOCKED_RETAINED_NATIVE_CUSTODY'
        result['private_context_closed'] = ROOT_STATE['closed']
        result['phase'] = 'complete' if closed else 'retained'
        try:
            verify_sources()
            result['source_pins_unchanged'] = True
        except BaseException as error:
            ROOT_STATE['source_error'] = error
            result['source_pins_unchanged'] = False
            result['status'] = 'BLOCKED_PUBLIC_SOURCE_CHANGED'
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        if result.get('result_write_failed'):
            result['status'] = 'BLOCKED_RESULT_PERSISTENCE_FAILED'
        persist(result)
    # Interactive host remains alive for Root's final finite check and normal exit.
    ROOT_STATE['result'] = result
    if closed:
        print(json.dumps({'status': result['status'], 'native_close_confirmed': result['native_close_confirmed']}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        ROOT_STATE['launcher_error'] = error
        # Keep the interactive host and any original references; no raw traceback.
        failed = ROOT_STATE.get('result', {'schema': 1})
        failed.update(status='BLOCKED_LAUNCHER', reason='ROOT_CALLER_FAILED')
        try:
            persist(failed)
        except BaseException:
            pass
