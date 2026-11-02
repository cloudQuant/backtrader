"""Public SDK receipt compatibility; no clients, credentials or provider calls."""
import hashlib
import json
import sys
from pathlib import Path

EXAMPLE = Path('D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute')
OUTPUT = Path('D:/temp/i51-discovery-installed-receipts-20261027.json')
CONSUMER = Path('D:/temp/i51cal-consumer-20261027-r1/consumer/Lib/site-packages')
PIN = '9cf046246e803eec81002b8152307ac78825cbef351facb26e2c4739e0e4607f'


def main():
    assert not OUTPUT.exists()
    assert hashlib.sha256((EXAMPLE / 'discovery_lifecycle.py').read_bytes()).hexdigest() == PIN
    sys.path.insert(0, str(EXAMPLE))
    import discovery_lifecycle as lifecycle
    import bt_api_ctp.ctp.client as client
    import backtrader.stores.registered_sim as registered
    for module in (client, registered):
        assert Path(module.__file__).resolve().is_relative_to(CONSUMER)
    normal = client.CtpNativeStopReceipt(1, True, True, True, False, False)
    preflight = client.CtpNativeStartupStopReceipt(None, 'preflight_no_owner', 0, None,
                                                 False, True, False, False, object())
    released = client.CtpNativeStartupStopReceipt('1' * 32, 'api_created_released', 0, True,
                                                True, True, False, False, object())
    uncertain = client.CtpNativeStartupStopReceipt('2' * 32, 'factory_uncertain', 0, None,
                                                 False, False, None, False, object())
    flags = []
    for receipt, expected in ((normal, True), (preflight, True), (released, True), (uncertain, False)):
        observed = lifecycle._receipt_observation(receipt, present=True,
            allowed_types=('CtpNativeStopReceipt', 'CtpNativeStartupStopReceipt'), minimum_generation=0)
        assert observed.complete is expected
        flags.append(observed.complete)
    impostor_type = type('CtpNativeStopReceipt', (), {'__module__': 'bt_api_ctp.ctp.client'})
    try:
        lifecycle._receipt_observation(impostor_type(), present=True,
            allowed_types=('CtpNativeStopReceipt',), minimum_generation=0)
    except ValueError:
        pass
    else:
        raise AssertionError('impostor accepted')
    store = registered.RegisteredSimStore(allow_writes=False)
    assert store._api is None
    health = lifecycle._store_health(store)
    assert health['quiescent'] is True and health['shutdown_state'] == 'NOT_STARTED'
    assert hashlib.sha256((EXAMPLE / 'discovery_lifecycle.py').read_bytes()).hexdigest() == PIN
    result = {'status': 'PASS_INSTALLED_RECEIPT_COMPATIBILITY_ONLY', 'schema': 1,
              'helper_sha256': PIN, 'receipt_cases': 4, 'completion_flags': flags,
              'same_named_impostor_rejected': True, 'real_unstarted_store_health_valid': True,
              'installed_origins_verified': True, 'client_created': False, 'provider_invoked': False,
              'private_input_read': False, 'actual_native_close_proven': False}
    OUTPUT.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
