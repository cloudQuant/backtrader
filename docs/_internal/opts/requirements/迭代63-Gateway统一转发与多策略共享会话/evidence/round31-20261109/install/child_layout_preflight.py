"""Used by a normal subprocess with PYTHONPATH pointed at isolated target."""
from pathlib import Path
import os,socket,sys
import origin_guard
assert any(isinstance(f,origin_guard.TargetFinder) for f in sys.meta_path),'origin guard missing'
import backtrader as bt
import tests.unit.brokers.test_iter63_gateway_notification_delivery as helper
import iter60_gateway_execution_support as support
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');assert Path(bt.__file__).resolve().is_relative_to((T/'install/src').resolve());assert Path(helper.__file__).resolve().is_relative_to((T/'bt-tests').resolve());assert Path(support.__file__).resolve().is_relative_to((T/'bt-tests').resolve())
try:socket.socket().connect(('203.0.113.1',1))
except PermissionError as e:assert str(e)=='R31_OFFLINE_NON_LOOPBACK_BLOCKED'
else:raise AssertionError('outbound socket not blocked')
assert origin_guard.audit();print('CHILD_TARGET_TEST_IMPORT_AND_GUARD_OK',os.getpid(),flush=True)
