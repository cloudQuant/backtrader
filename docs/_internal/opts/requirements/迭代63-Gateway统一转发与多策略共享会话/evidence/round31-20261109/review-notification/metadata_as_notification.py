import pytest

class Inject:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            mod = item.module
            def repro(state, ready):
                host, binding, data, broker, strategy, order, original, event = mod.prepare(ready)
                before = len(strategy.events)
                broker.arm_gateway_notification_state(strategy, 6)
                strategy._addnotification(order.clone())
                strategy._notify()
                checkpoint = broker.assert_gateway_notifications_ackable(strategy, 6)
                batch = host.load_execution_notification_batch()
                assert len(strategy.events) > before
                assert checkpoint.projection['state']['_gateway_strategy']['version'] == 1
                assert batch['status'] == 'confirmed'
                assert 'gateway_trade_dates' not in order.info
                print('REPRODUCED: metadata-only event emitted order callback, confirmed v1 batch, and authorized ACK without date projection')
            item.obj = repro

raise SystemExit(pytest.main(['-q', '-s', '-p', 'no:cacheprovider', 'tests/unit/brokers/test_iter63_gateway_metadata_checkpoint.py::test_date_only_projection_durable_without_second_trade_or_notification'], plugins=[Inject()]))
