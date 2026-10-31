# Iteration 53: live broker factory structure

Scope: `backtrader/live_trading/interface.py` in the Backtrader `dev` checkout.
The factory now accepts explicitly registered concrete `LiveBroker` classes
instead of advertising CTP and CCXT implementations that are absent from the
repository. It does not discover or assemble SDK providers.

This is a breaking public API change: callers that registered dotted class
paths must register a concrete `LiveBroker` subclass instead. Unknown names
remain unavailable. Duplicate normalized names can currently overwrite an
earlier registration; review this behavior during acceptance.

Evidence: independent source-structure review and Python 3.8 syntax parsing.
No behavior tests, provider connection, account operation, or live-trading
acceptance were performed. The iteration remains in structural refactoring;
testing and defect repair follow after that phase.
