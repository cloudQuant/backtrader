import examples.ctp_options_simnow_mechanical_operator as m

class AfterApiReady(Exception):
    pass

m.MECHANICAL_EXECUTION_ENABLED = True
m._require_external_receipt_path = lambda path, reason: __import__('pathlib').Path('synthetic-receipt.json')
m._require_pinned_trust_root = lambda *args: None
m._load_external_entry_approval = lambda *args, **kwargs: {'payload': {'issuer_key_id': 'fake-issuer'}}
m._calendar_receipt_sha256 = lambda *args: 'a' * 64
m._read_json_mapping = lambda *args: {}
m._contains_private_key_material = lambda value: False
m.resolve_credentials = lambda env: {'synthetic': 'only'}
m.resolve_fronts = lambda env, environment: {'synthetic': 'only'}

class FakeStore:
    sdk_api = object()
    def _ensure_api_ready(self):
        raise AssertionError('existing SDK API must not invoke private lazy fallback')
    def get_ctp_preflight_snapshot(self, *args, **kwargs):
        raise AfterApiReady('advanced beyond sdk_api readiness guard')

config = m.MechanicalConfiguration(environment='second_7x24', product_id='SA', exchange_id='CZCE', future_instrument_id='SA701', call_instrument_id='SA701C1500', put_instrument_id='SA701P1500')
try:
    m.run_mechanical_cycle(config, {}, state_directory='.', store=FakeStore())
except AfterApiReady as exc:
    assert str(exc) == 'advanced beyond sdk_api readiness guard'
    print('PASS: non-None sdk_api proceeds to preflight snapshot; _ensure_api_ready unused')
else:
    raise AssertionError('expected sentinel after readiness guard')
