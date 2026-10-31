# Retired unregistered CTP I9 adapters

`ctp_i9_managed_dispatch` and `ctp_i9_parent_request_builder` were unregistered
Backtrader-side glue: no production module called them, and their execution
spine already lives in `bt_api_execution` (`ctp_single_worker_candidate`,
`store`, `contracts`). They are archived here as migration source, not as a
fallback entry point.
