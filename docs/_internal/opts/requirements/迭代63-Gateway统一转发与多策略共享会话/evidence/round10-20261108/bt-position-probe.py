from types import SimpleNamespace
from bt_api_base.account_protocol import AccountKey, AccountResourceKey, AccountPosition, AccountObservation
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_py.broker_event_envelope import neutral_instrument_identity, resolve_neutral_position_route
from backtrader.service.service_read_proxy import ServiceReadProxy

stamp = '2026-11-08T00:00:00Z'
resource = AccountResourceKey('future', 'futures')
instrument = MarketInstrumentKey('ctp', 'SHFE', 'simnow', 'future', 'rb2701', 'rb2701')
position = AccountPosition(resource, instrument, 'long', '2', 'contract', '3500', 'CNY', stamp)
observation = AccountObservation(AccountKey('ctp', 'simnow', 'simnow', 'synthetic-account', 'synthetic-broker'), 'observation', (resource,), (), (position,), None, stamp, stamp, 'multi_query', True, True, (), True)
proxy = ServiceReadProxy.__new__(ServiceReadProxy)
proxy._position_mode = 'dual_side'
proxy._current_observation = lambda: observation
proxy._position_binding = lambda resource, instrument: ('rb-feed', SimpleNamespace(qty_unit='contract', quantity_multiplier='1'))
row, = proxy.get_positions()
identity = neutral_instrument_identity(instrument)
aliases = {'aliases': {'rb-feed': frozenset({'rb-feed'})}, 'identities': {identity: frozenset({'rb-feed'})}, 'route_identities': {'rb-feed': frozenset({identity})}}
route = resolve_neutral_position_route(row, aliases)
control_route = resolve_neutral_position_route({**row, 'instrument': instrument.to_dict()}, aliases)
print('position_average_price:', position.average_price)
print('returned_keys:', ', '.join(sorted(row)))
print('missing_broker_fields:', ', '.join(name for name in ('instrument', 'quantity', 'average_price') if name not in row))
print('actual_route:', repr(route))
print('control_route_with_instrument_only:', repr(control_route))
assert route is None and control_route == 'rb-feed'
assert all(field not in row for field in ('instrument', 'quantity', 'average_price'))
