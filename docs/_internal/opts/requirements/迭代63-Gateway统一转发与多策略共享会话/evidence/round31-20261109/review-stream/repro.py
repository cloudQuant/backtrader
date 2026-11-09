import pathlib, tempfile
from dataclasses import replace
import pytest
from backtrader.live_state import StrategyStateDir
from bt_api_py.gateway_execution_stream_client import GatewayExecutionStreamClientResult
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.live_state.test_gateway_execution_checkpoint import ready
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated
from tests.unit.brokers.test_iter63_gateway_stream_consumer import attach, event_for, deliver

def setup_fixture():
    tmp = tempfile.TemporaryDirectory()
    path = pathlib.Path(tmp.name) / 'strategy'
    path.mkdir()
    state = StrategyStateDir.initialize(path)
    inp = inputs.__wrapped__(state)
    current = ready.__wrapped__(state, inp)
    mp = pytest.MonkeyPatch()
    return tmp, inp, current, mp

def offline():
    tmp, inp, current, mp = setup_fixture()
    first = event_for(current[0])
    second = event_for(current[0], 8, quantity='0.6', fact='9'*64, trade='c'*64)
    host, broker, strategy, order, calls, api = attach(current, inp, mp, [first,second])
    broker.next()
    deliver(broker,strategy)
    stream=api.gateway_execution_stream('CTP___FUTURE')
    mp.setattr(stream,'read_after',lambda *a, **kw: GatewayExecutionStreamClientResult('UNKNOWN', code='RPC_OUTCOME_UNKNOWN'))
    broker.next()
    c=host.load_execution_checkpoint()
    print('offline stored',c.stored_sequence,'applied',c.applied_sequence,'ack',c.acknowledged_sequence,'size',order.executed.size,'state',broker.gateway_execution_stream_status())
    mp.undo(); tmp.cleanup()

def metadata():
    tmp, inp, current, mp = setup_fixture()
    orig = event_for(current[0])
    orig = replace(orig, observation=replace(orig.observation, schema_version=1, trade_date=None))
    meta = dated(orig, 6, date='20261107', trade_time='10:00:00')
    host, broker, strategy, order, calls, api = attach(current,inp,mp,[orig,meta])
    broker.next()
    c=host.load_execution_checkpoint()
    print('metadata stored',c.stored_sequence,'original_time',orig.observation.trade_time,'metadata_time',meta.observation.trade_time,'position',order.executed.size,'saved_date',order.info['gateway_execution_time_facts'][orig.observation.trade_key_digest]['trade_date'])
    mp.undo(); tmp.cleanup()

offline()
metadata()
