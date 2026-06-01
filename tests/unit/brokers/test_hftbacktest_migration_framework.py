from backtrader.brokers.hft import build_input_manifest, build_quote_builder, get_hftbacktest_demo_example_specs, get_hftbacktest_example_spec, get_hftbacktest_example_specs
from backtrader.events import OrderBookSnapshot


def test_hftbacktest_example_specs_capture_original_notebook_inputs_and_parameters():
    specs = {spec.name: spec for spec in get_hftbacktest_example_specs()}
    demo_specs = {spec.name: spec for spec in get_hftbacktest_demo_example_specs()}

    assert set(specs) == {
        "plain_grid",
        "queue_market_making",
        "obi_alpha_market_making",
        "basis_alpha_market_making",
        "apt_alpha_market_making",
        "glft_market_making",
    }
    assert set(demo_specs) == {"plain_grid", "queue_market_making", "obi_alpha_market_making"}
    assert specs["plain_grid"].asset_parameters["tick_size"] == 0.01
    assert specs["plain_grid"].asset_parameters["maker_commission"] == -0.00005
    assert specs["queue_market_making"].strategy.parameters["grid_num"] == 10
    assert specs["obi_alpha_market_making"].strategy.parameters["window"] == 3600
    assert specs["basis_alpha_market_making"].strategy.builder == "BasisAlphaQuoteBuilder"
    assert specs["apt_alpha_market_making"].strategy.builder == "APTQuoteBuilder"
    assert specs["glft_market_making"].strategy.builder == "GLFTQuoteBuilder"


def test_hftbacktest_input_manifest_reports_missing_files_when_original_data_is_absent(tmp_path):
    spec = get_hftbacktest_example_spec("plain_grid")

    manifest = build_input_manifest(spec, tmp_path)

    assert manifest["ready"] is False
    assert "market_data" in manifest["missing"]
    assert "latency_data" in manifest["missing"]
    assert manifest["resolved"]["market_data"] == ()


def test_plain_grid_and_queue_builders_emit_multilevel_quote_grids():
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(100.0, 5.0)],
        asks=[(101.0, 5.0)],
    )

    plain_builder = build_quote_builder(get_hftbacktest_example_spec("plain_grid"))
    queue_builder = build_quote_builder(get_hftbacktest_example_spec("queue_market_making"))

    plain_quotes = plain_builder(0.0, snapshot)
    queue_quotes = queue_builder(0.0, snapshot)

    assert len(plain_quotes["buy"]) == 20
    assert len(plain_quotes["sell"]) == 20
    assert plain_quotes["buy"][0] > plain_quotes["buy"][-1]
    assert plain_quotes["sell"][0] < plain_quotes["sell"][-1]
    assert len(queue_quotes["buy"]) == 10
    assert len(queue_quotes["sell"]) == 10


def test_obi_builder_from_framework_emits_single_level_quotes_for_original_variant():
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(30000.0, 8.0), (29999.9, 4.0)],
        asks=[(30000.1, 2.0), (30000.2, 1.0)],
    )

    builder = build_quote_builder(get_hftbacktest_example_spec("obi_alpha_market_making"))
    quotes = builder(0.0, snapshot)

    assert len(quotes["buy"]) == 1
    assert len(quotes["sell"]) == 1
    assert quotes["buy"][0] <= snapshot.bids[0][0]
    assert quotes["sell"][0] >= snapshot.asks[0][0]


def test_extended_framework_builders_accept_runtime_context_and_update_order_qty():
    snapshot = OrderBookSnapshot(
        timestamp=1.0,
        symbol="BTC/USDT",
        bids=[(60000.0, 8.0), (59999.9, 4.0)],
        asks=[(60000.1, 2.0), (60000.2, 1.0)],
    )

    basis_builder = build_quote_builder(get_hftbacktest_example_spec("basis_alpha_market_making"))
    basis_builder.precompute_data = [[50, 59000.0, 150.0], [150, 60000.0, 100.0]]
    basis_quotes = basis_builder(0.0, snapshot, {"timestamp_ns": 100})

    apt_builder = build_quote_builder(get_hftbacktest_example_spec("apt_alpha_market_making"))
    apt_builder.precompute_data = [[50, 0.001, 0.0, 0.0, 59000.0], [150, 0.002, 0.0, 0.0, 60000.0]]
    apt_quotes = apt_builder(0.0, snapshot, {"timestamp_ns": 100})

    glft_builder = build_quote_builder(get_hftbacktest_example_spec("glft_market_making"))
    glft_quotes = glft_builder(0.0, snapshot, {"last_trades": (), "timestamp_ns": 100})

    assert basis_builder.current_order_qty > 0.0
    assert apt_builder.current_order_qty > 0.0
    assert len(basis_quotes["buy"]) == 1
    assert len(basis_quotes["sell"]) == 1
    assert len(apt_quotes["buy"]) == 1
    assert len(apt_quotes["sell"]) == 1
    assert len(glft_quotes["buy"]) == 1
    assert len(glft_quotes["sell"]) == 1
