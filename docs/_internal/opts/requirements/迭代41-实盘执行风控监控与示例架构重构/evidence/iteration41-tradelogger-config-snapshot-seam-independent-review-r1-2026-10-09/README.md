# TradeLogger configuration snapshot seam review

The frozen source and focused tests passed the source-fake review. The one-bar test uses ordinary `Cerebro.addobserver` and `Cerebro.run`; the observer's start receipt is read from the strategy's normal `start()` hook after the framework has started observers. The receipt is immutable, generated for the current run/generation, bound to the allowlisted risk thresholds, and linked to the emitted configuration event when thresholds are enabled.

The seam rejects direct `TradeLogger.start()` and direct `TradeLogger._start()` calls without the Strategy-owned observer-start context. It also rejects changed thresholds/start time and stopped state. Source readback checks current attachment and generation; the focused file does not add a standalone detached/restart negative test.

A `TradeLoggerConfigSnapshotV1` receipt is configuration evidence from one observer instance. Root acceptance must separately bind the exact `Cerebro`, `Strategy`, and observer sources and record that the actual `Cerebro.run` composition reached `Strategy.start` and read the receipt before account calls. The receipt is not an account authentication proof or a formal case pass.

The focused configuration tests passed 4/4. The related seven-file TradeLogger compatibility batch passed 76/76. Both runs used Python 3.11.5 with isolated flags, disabled plugin autoload, no ambient `PYTHONPATH`, and repo-local basetemps. Each had one existing pytest configuration warning for `asyncio_default_fixture_loop_scope`.

No private input, provider, network, SDK, native, or OS API operation was performed. Official case PASS remains 0.
