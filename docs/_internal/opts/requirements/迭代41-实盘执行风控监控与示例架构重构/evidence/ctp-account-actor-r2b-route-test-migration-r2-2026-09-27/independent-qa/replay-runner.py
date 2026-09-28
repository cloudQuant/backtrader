import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(r'D:\temp\iteration41-r2b-route-test-migration-qa-20260927-r2-independent')
guards = root / 'guards'
command = [
    sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short',
    '-p', 'no:cacheprovider', '--junitxml', str(root / 'focused-route-migration-r2.junit.xml'),
    'tests/unit/stores/test_btapistore.py::test_store_getdata_binds_store_provider_and_store_alias_for_custom_data_cls',
    'tests/unit/stores/test_btapistore.py::test_store_getdata_preserves_explicit_store_and_provider_arguments',
    'tests/unit/stores/test_btapistore.py::test_store_getbroker_binds_store_and_provider_for_custom_broker_cls',
    'tests/unit/stores/test_btapistore.py::test_placeholder_provider_raises',
    'tests/unit/stores/test_btapistore_normalized.py::test_venue_account_cache_uses_completion_time_and_force_reads',
    'tests/unit/stores/test_btapistore_normalized.py::test_public_source_stop_callback_hook_does_not_expose_the_private_client',
    'tests/unit/stores/test_btapistore_normalized.py::test_supplied_sdk_configuration_is_preserved_when_store_does_not_override_it',
    'tests/unit/stores/test_btapistore_normalized.py::test_explicit_ctp_route_hidden_in_sdk_configuration_is_rejected_before_store_use',
    'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py',
    'tests/unit/stores/test_ctp_non_authorizing_contracts.py',
]
env = {}
for key in ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC'):
    if key in os.environ:
        env[key] = os.environ[key]
env.update({
    'PYTHONPATH': str(guards) + os.pathsep + str(root),
    'PYTHONDONTWRITEBYTECODE': '1',
    'PYTHONNOUSERSITE': '1',
    'PYTHONUTF8': '1',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
    'BACKTRADER_LIGHT_IMPORT': '1',
    'R2B_ROUTE_QA_GUARD_LOG': str(root / 'guard-summary-r2.json'),
})
result = subprocess.run(command, cwd=str(root), env=env, capture_output=True, text=True)
(root / 'test-command-r2.json').write_text(json.dumps(command, indent=2) + '\n', encoding='utf-8')
(root / 'pytest-r2.stdout.log').write_text(result.stdout, encoding='utf-8')
(root / 'pytest-r2.stderr.log').write_text(result.stderr, encoding='utf-8')
(root / 'pytest-r2.exit-code.txt').write_text(str(result.returncode) + '\n', encoding='ascii')
print(result.stdout, end='')
if result.stderr:
    print(result.stderr, file=sys.stderr, end='')
raise SystemExit(result.returncode)

