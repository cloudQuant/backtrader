# Gateway suffix correction and isolated regression evidence

This packet is a local fail-close candidate only. It does not authorize a write
route or establish writer closure. The source preimage is the exact Store file
whose SHA-256 is bound in `manifest.json`.

## Reviewed candidates and call paths

- `i41-writer-a5104365b2d37af86d15` locates the indirect SDK writer dispatch in
  `backtrader/stores/btapistore.py::_invoke_sdk_command` (preimage line 6648).
  Generic public submit flows through `enqueue_order` (7164),
  `_enqueue_order_command`, `_enqueue_sdk_command` (6245),
  `_execute_sdk_command` (6472), and the fallback to `_invoke_sdk_command`.
  The managed typed branch in `_execute_sdk_command` precedes that fallback;
  this candidate's `_invoke_sdk_command` guard is not a global gate for all
  `_execute_sdk_command` branches.
  Generic cancel flows through `enqueue_cancel` (7322),
  `_enqueue_sdk_command`, `_execute_sdk_command`, and
  `_invoke_sdk_command`.
- `i41-writer-716fa6d57bd60cca1c95` locates the managed cancel alias in
  `_cancel_managed` (8052). The preimage resolves the injected
  `adapter.cancel_order` before the callback reaches
  `_enqueue_ctp_managed_cancel` (7358), whose durable outbox route is currently
  closed.
- The r1 candidate used exact gateway equality (`exchange == "CTP"`) in the
  write classifier. That missed supported suffixed gateway route labels such
  as `CTP___TEST`. The source defines gateway route parsing by the prefix
  before `___` in `CtpGatewayClientWrapper._is_supported_non_ctp_exchange`
  (3077), so the classifier now uses the same prefix rule. The new
  `gateway-suffixed-route` test exercises submit, cancel, queue, and API-sink
  rejection for that route form.
- A local inert classifier probe using `backend="gateway"` and
  `exchange_type="CTP___TEST"` returned `False` on r1 and `True` on r2. It
  instantiated only the Store object and did not access injected API properties.
- The classifier reads Store snapshots on dispatch and does not dereference
  `_api` there. However, the constructor initializes `_sdk_exchanges` from
  explicit `sdk_options["exchange_kwargs"]` or falls back to
  `getattr(api, "exchange_kwargs", {})` (preimage line 3550). That snapshot can
  originate from injected API metadata, so it is a route hint for local
  fail-close behavior, not trusted authorization. The earlier “code-owned
  snapshots” wording was inaccurate and is corrected in the candidate
  docstring and manifest.

## Frozen checks

- Candidate-only fake contracts: 12 passed, one existing Quandl deprecation
  warning.
- Baseline fake reachability probe: 2 passed, one existing Quandl deprecation
  warning.
- Existing Store regression tests, run with the candidate tree as the working
  directory: 190 passed, 1 skipped, one existing pytest config warning. This
  includes managed projection, CTP I9 managed dispatch, and the Store test
  module with non-CTP cases.
- The three regression test input SHA-256 values are recorded in
  `manifest.json`; they were only read/executed and were not used as patch
  preimages.
- Candidate `py_compile`: passed.
- Repository-configured Ruff for the candidate Store source and candidate test:
  passed.
- Black compatibility fallback with `--line-length 100 --target-version
  py311` on the candidate test: passed. The full Store source file has
  pre-existing whole-file formatting differences under the installed Black;
  no whole-file formatting was applied.
- Strict byte replay from the exact preimage with
  `git -c core.autocrlf=false apply --check` and `apply` passed; replayed Store
  SHA-256 matches the target in `manifest.json`.

All provider-like behavior uses local fake objects and monkeypatched hooks.
There was no private config/credential read, SDK/native import, network or
provider contact, account operation, order, or cancel.
