import pytest

class Inject:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            mod = item.module
            def repro(state, ready):
                host, binding, data, broker, strategy, order, original, event = mod.prepare(ready)
                before_events = tuple(strategy.events)
                before_orders = tuple(strategy._orderspending)
                before = host.load_execution_checkpoint()
                broker.arm_gateway_notification_state(strategy, 6)
                with pytest.raises(ValueError, match='METADATA_ONLY'):
                    strategy._addnotification(order.clone())
                assert tuple(strategy.events) == before_events
                assert tuple(strategy._orderspending) == before_orders
                assert host.load_execution_checkpoint() == before
                with pytest.raises(ValueError, match='ACK_BLOCKED'):
                    broker.assert_gateway_notifications_ackable(strategy, 6)
                result = broker.commit_gateway_trade_metadata(strategy, 6)
                assert result.applied_sequence == 6
                assert host.load_execution_notification_batch() is None
                assert order.info['gateway_trade_dates'][original.observation.trade_key_digest] == '20261107'
                assert broker.assert_gateway_notifications_ackable(strategy, 6) == result
                print('FIXED: original E075 entry rejected before mutation; date-only checkpoint and ACK succeeded')
            item.obj = repro

raise SystemExit(pytest.main(['-q', '-s', '-p', 'no:cacheprovider', 'tests/unit/brokers/test_iter63_gateway_metadata_checkpoint.py::test_date_only_projection_durable_without_second_trade_or_notification'], plugins=[Inject()]))
