# R19 public test dependency inventory (draft)

No runtime source or tests have been snapshotted. The final primary selectors and explicit allowlists govern the frozen snapshot.

R18 SDK non-selected test helpers/config examples (path-based CTP helper must retain sdk-tests/bt_api/bt_api_ctp/tests layout):
- conftest.py
- examples/services/account-service.yaml
- examples/services/portfolio-analysis-client.yaml
- examples/services/portfolio-analysis-service.yaml
- examples/services/strategy-readonly.yaml
- examples/services/unconfigured-client.yaml
- tests/__init__.py
- tests/conftest.py
- tests/conftest_test_data.py
- tests/integration/__init__.py
- tests/integration/test_gateway_operator_ctp_market.py
- tests/integration/test_gateway_operator_deployment.py
- tests/integration/test_iter62_gateway_ctp_market_profile.py
- tests/integration/test_iter62_gateway_market_runtime_lease.py
- tests/integration/test_iter63_gateway_client_processes.py
- tests/integration/test_service_account_instrument_metadata.py
- tests/test_iter62_settlement_readback_on_write.py
- tests/test_iter63_prepared_cancel.py
- tests/unit/test_service_runtime_renewal_retry.py

Base full tests: all git-tracked Python files under tests/ including tests/r2a_reference plus selected approved R19 tests; copy pyproject.toml separately; isolated tests/src links installed target.
Gateway full tests: copy all selected test modules, including test_service_component.py used by path via test_typed_account_snapshot.py.
CTP: selected tests and transitive public helpers, relocated byte-identically to install/tests for source-layout assertions.
SDK: root conftest.py and tests/conftest.py, tests/conftest_test_data.py and package initializers when tracked; recursively scan public helper imports and explicitly check dynamic __file__ paths.
Retain the five explicitly tracked examples/services YAML files in test-manifest; no globbed credentials or private configuration.
Record original logs/commands and source/test manifests; disclose --no-deps, editable ZMQ, child processes lacking exit audits, and Base -S subprocess with no sitecustomize audit.
