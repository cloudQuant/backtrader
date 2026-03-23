from pathlib import Path

import backtrader as bt
import pytest

from backtrader.brokers.bbroker import BackBroker
from backtrader.feeds.btcsv import BacktraderCSVData
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.profiles import LiveProfile, build_cerebro
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_tick, make_store


class _NoopStrategy(bt.Strategy):
    pass


def test_build_cerebro_backtest_profile_wires_backtest_components():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.broker, BackBroker)
    assert isinstance(cerebro.datas[0], BacktraderCSVData)
    assert cerebro.live_profile is profile
    assert cerebro.profile_store is None


def test_build_cerebro_backtest_profile_passes_data_kwargs_through():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        data_kwargs={"timeframe": bt.TimeFrame.Minutes, "compression": 5},
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0]._timeframe == bt.TimeFrame.Minutes
    assert cerebro.datas[0]._compression == 5


def test_build_cerebro_passes_cerebro_kwargs_through():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        cerebro_kwargs={"quicknotify": True, "stdstats": False},
    )

    cerebro = build_cerebro(profile)

    assert cerebro.p.quicknotify is True
    assert cerebro.p.stdstats is False


def test_build_cerebro_backtest_profile_honors_custom_broker_cls_and_data_cls():
    class CustomBackBroker(BackBroker):
        pass

    class CustomBackData(BacktraderCSVData):
        pass

    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        broker_cls=CustomBackBroker,
        data_cls=CustomBackData,
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.broker, CustomBackBroker)
    assert isinstance(cerebro.datas[0], CustomBackData)
    assert cerebro.profile_store is None


def test_build_cerebro_backtest_profile_uses_broker_factory_with_profile_only():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    captured = {}

    class CustomBackBroker(BackBroker):
        pass

    def broker_factory(store, profile):
        captured["store"] = store
        captured["profile"] = profile
        return CustomBackBroker(cash=4321.0)

    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        broker_factory=broker_factory,
    )

    cerebro = build_cerebro(profile)

    assert captured["store"] is None
    assert captured["profile"] is profile
    assert isinstance(cerebro.broker, CustomBackBroker)
    assert float(cerebro.broker.getcash()) == 4321.0


def test_build_cerebro_rejects_broker_factory_returning_none():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        broker_factory=lambda store, profile: None,
    )

    with pytest.raises(ValueError, match="LiveProfile.broker_factory"):
        build_cerebro(profile)


def test_build_cerebro_passes_broker_kwargs_through_in_backtest_and_live():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    backtest_profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        broker_kwargs={"cash": 4321.0},
    )

    backtest_cerebro = build_cerebro(backtest_profile)

    assert float(backtest_cerebro.broker.getcash()) == 4321.0

    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    live_profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        broker_kwargs={"cancel_wait_remote": True},
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    live_cerebro = build_cerebro(live_profile)

    assert live_cerebro.broker.p.cancel_wait_remote is True


def test_build_cerebro_applies_explicit_data_name_to_single_feed_in_backtest_and_live():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    backtest_profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        data_name="primary-data",
    )

    backtest_cerebro = build_cerebro(backtest_profile)

    assert backtest_cerebro.datas[0]._name == "primary-data"
    assert backtest_cerebro.datasbyname["primary-data"] is backtest_cerebro.datas[0]

    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    live_profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        data_name="primary-data",
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    live_cerebro = build_cerebro(live_profile)

    assert live_cerebro.datas[0]._name == "primary-data"
    assert live_cerebro.datasbyname["primary-data"] is live_cerebro.datas[0]


def test_build_cerebro_treats_empty_data_name_as_unset():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        dataname=str(datapath),
        data_name="",
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0]._name == str(datapath)
    assert cerebro.datasbyname[str(datapath)] is cerebro.datas[0]


def test_build_cerebro_uses_data_factory_output_directly():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    data = BacktraderCSVData(dataname=str(datapath))
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: data,
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0] is data
    assert cerebro.live_profile is profile
    assert cerebro.profile_store is None


def test_build_cerebro_falls_back_to_data_dataname_when_name_is_empty():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    data = BacktraderCSVData(dataname=str(datapath))
    data._name = ""
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: data,
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0] is data
    assert cerebro.datas[0]._name == str(datapath)
    assert cerebro.datasbyname[str(datapath)] is data


@pytest.mark.parametrize("factory_result", [None, [], [None]])
def test_build_cerebro_rejects_invalid_data_factory_output(factory_result):
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: factory_result,
    )

    with pytest.raises(ValueError, match="LiveProfile.data_factory"):
        build_cerebro(profile)


def test_build_cerebro_applies_data_name_to_single_data_factory_output():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    data = BacktraderCSVData(dataname=str(datapath))
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: data,
        data_name="factory-data",
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0] is data
    assert cerebro.datas[0]._name == "factory-data"
    assert cerebro.datasbyname["factory-data"] is data


def test_build_cerebro_uses_multiple_data_factory_outputs_directly():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    data_a = BacktraderCSVData(dataname=str(datapath))
    data_b = BacktraderCSVData(dataname=str(datapath))
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: [data_a, data_b],
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0] is data_a
    assert cerebro.datas[1] is data_b
    assert cerebro.live_profile is profile
    assert cerebro.profile_store is None


def test_build_cerebro_live_profile_wires_store_broker_and_feed():
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.profile_store, BtApiStore)
    assert isinstance(cerebro.broker, bt.brokers.BtApiBroker)
    assert isinstance(cerebro.datas[0], BtApiFeed)
    assert cerebro.datas[0]._store is cerebro.profile_store
    assert cerebro.live_profile is profile


def test_build_cerebro_live_profile_reuses_store_factory_instance():
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    store = make_store(api=client)
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: store,
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert cerebro.profile_store is store
    assert cerebro.broker.store is store
    assert cerebro.datas[0]._store is store


def test_build_cerebro_live_profile_passes_data_kwargs_through():
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert cerebro.datas[0]._timeframe == bt.TimeFrame.Seconds
    assert cerebro.datas[0]._compression == 5
    assert cerebro.datas[0].p.backfill_start is False


def test_build_cerebro_live_profile_builds_store_from_provider_and_kwargs():
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_provider="okx",
        store_kwargs={"api": client},
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.profile_store, BtApiStore)
    assert cerebro.profile_store.provider == "okx"
    assert cerebro.profile_store._api is client
    assert isinstance(cerebro.broker, bt.brokers.BtApiBroker)
    assert cerebro.broker.provider == "okx"
    assert isinstance(cerebro.datas[0], BtApiFeed)
    assert cerebro.datas[0]._store is cerebro.profile_store


def test_build_cerebro_live_profile_rejects_missing_store_instance():
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: None,
    )

    with pytest.raises(ValueError, match="Live profiles require a store instance"):
        build_cerebro(profile)


def test_build_cerebro_live_profile_uses_broker_factory_with_store_and_profile():
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    captured = {}

    def broker_factory(store, profile):
        captured["store"] = store
        captured["profile"] = profile
        return store.getbroker(cancel_wait_remote=True)

    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=client),
        broker_factory=broker_factory,
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert captured["store"] is cerebro.profile_store
    assert captured["profile"] is profile
    assert isinstance(cerebro.broker, bt.brokers.BtApiBroker)
    assert cerebro.broker.p.cancel_wait_remote is True
    assert cerebro.datas[0]._store is cerebro.profile_store


def test_build_cerebro_live_profile_honors_custom_broker_cls():
    class CustomLiveBroker(bt.brokers.BtApiBroker):
        pass

    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        broker_cls=CustomLiveBroker,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.broker, CustomLiveBroker)
    assert cerebro.broker.store is cerebro.profile_store


def test_build_cerebro_live_profile_honors_custom_data_cls():
    class CustomLiveFeed(BtApiFeed):
        pass

    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: [make_tick(0, 100.0)]})
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        dataname=DEFAULT_SYMBOL,
        data_cls=CustomLiveFeed,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.datas[0], CustomLiveFeed)
    assert cerebro.datas[0]._store is cerebro.profile_store


def test_build_cerebro_live_profile_supports_multiple_symbols():
    symbols = ("BTC/USDT", "ETH/USDT")
    client = FakeBtApiClient(
        live_ticks={
            symbols[0]: [make_tick(0, 100.0, symbol=symbols[0])],
            symbols[1]: [make_tick(0, 200.0, symbol=symbols[1])],
        }
    )
    profile = LiveProfile(
        mode="live",
        strategy=_NoopStrategy,
        symbols=symbols,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )

    cerebro = build_cerebro(profile)

    assert isinstance(cerebro.profile_store, BtApiStore)
    assert isinstance(cerebro.broker, bt.brokers.BtApiBroker)
    assert len(cerebro.datas) == 2
    assert all(isinstance(data, BtApiFeed) for data in cerebro.datas)
    assert [getattr(data, "_dataname", None) for data in cerebro.datas] == list(symbols)
    assert all(getattr(data, "_store", None) is cerebro.profile_store for data in cerebro.datas)
    assert cerebro.live_profile is profile


def test_live_profile_normalizes_string_symbols_and_validates_frequency():
    profile = LiveProfile(
        mode="live",
        frequency="HFT",
        strategy=_NoopStrategy,
        symbols=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=FakeBtApiClient()),
    )

    assert profile.frequency == "hft"
    assert profile.symbols == (DEFAULT_SYMBOL,)

    with pytest.raises(ValueError, match="LiveProfile.frequency"):
        LiveProfile(
            mode="live",
            frequency="scalping",
            strategy=_NoopStrategy,
            symbols=DEFAULT_SYMBOL,
            store_factory=lambda: make_store(api=FakeBtApiClient()),
        )


def test_live_profile_normalizes_and_validates_mode():
    profile = LiveProfile(
        mode="LIVE",
        strategy=_NoopStrategy,
        symbols=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=FakeBtApiClient()),
    )

    assert profile.mode == "live"
    assert profile.is_live is True

    with pytest.raises(ValueError, match="LiveProfile.mode"):
        LiveProfile(
            mode="paper",
            strategy=_NoopStrategy,
            symbols=DEFAULT_SYMBOL,
            store_factory=lambda: make_store(api=FakeBtApiClient()),
        )


def test_live_profile_requires_dataname_symbols_or_data_factory():
    with pytest.raises(ValueError, match="LiveProfile requires dataname, symbols, or data_factory"):
        LiveProfile(
            mode="backtest",
            strategy=_NoopStrategy,
        )


def test_live_profile_rejects_live_store_configuration_in_backtest_mode():
    with pytest.raises(ValueError, match="Backtest profiles cannot use live store configuration"):
        LiveProfile(
            mode="backtest",
            strategy=_NoopStrategy,
            dataname="fake.csv",
            store_provider="okx",
            store_kwargs={"api": FakeBtApiClient()},
        )


def test_live_profile_rejects_data_factory_with_dataname_or_symbols():
    with pytest.raises(ValueError, match="LiveProfile.data_factory"):
        LiveProfile(
            mode="backtest",
            strategy=_NoopStrategy,
            dataname="fake.csv",
            data_factory=lambda: BacktraderCSVData(dataname="fake.csv"),
        )

    with pytest.raises(ValueError, match="LiveProfile.data_factory"):
        LiveProfile(
            mode="live",
            strategy=_NoopStrategy,
            symbols=(DEFAULT_SYMBOL,),
            data_factory=lambda: BtApiFeed(dataname=DEFAULT_SYMBOL),
            store_factory=lambda: make_store(api=FakeBtApiClient()),
        )


def test_live_profile_rejects_shared_data_name_for_multiple_symbols():
    with pytest.raises(ValueError, match="LiveProfile.data_name"):
        LiveProfile(
            mode="live",
            strategy=_NoopStrategy,
            symbols=("BTC/USDT", "ETH/USDT"),
            data_name="shared",
            store_factory=lambda: make_store(api=FakeBtApiClient()),
        )


def test_live_profile_rejects_dataname_and_symbols_together():
    with pytest.raises(ValueError, match="LiveProfile cannot use both dataname and symbols"):
        LiveProfile(
            mode="live",
            strategy=_NoopStrategy,
            dataname=DEFAULT_SYMBOL,
            symbols=(DEFAULT_SYMBOL, "ETH/USDT"),
            store_factory=lambda: make_store(api=FakeBtApiClient()),
        )


def test_build_cerebro_rejects_data_name_when_data_factory_returns_multiple_datas():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"
    profile = LiveProfile(
        mode="backtest",
        strategy=_NoopStrategy,
        data_factory=lambda: [
            BacktraderCSVData(dataname=str(datapath)),
            BacktraderCSVData(dataname=str(datapath)),
        ],
        data_name="shared",
    )

    with pytest.raises(ValueError, match="LiveProfile.data_name"):
        build_cerebro(profile)
