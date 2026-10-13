# Optional16 acceptance path — retired

The Optional16 component-acceptance path is retired. The historical
`run_matrix.py` and `gateway_capability_check.py` command names now print
`{"status":"BLOCKED","reason":"optional16_acceptance_retired"}` and exit
with code 2 for every invocation. They do not read configuration or
credentials, start child processes or a gateway, or write result files.

The acceptance matrix, gateway-capability record, journal, and source files
remain in the repository as historical material. `gateway_server.py`,
`components.py`, and `spec.py` remain unchanged as retained source support;
their presence is not a recommendation for future production deployment. No
new Optional16 acceptance result is produced by this retired path.

The retirement does not change the existing 33-case entry defaults. See the
Binance and OKX suite READMEs for their per-case entry instructions.
