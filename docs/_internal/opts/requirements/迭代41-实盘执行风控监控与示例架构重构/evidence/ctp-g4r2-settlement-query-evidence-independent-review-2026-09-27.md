# G4-r2 settlement query evidence: independent fake-source review

**Disposition: source/fake evidence only. G2, G4, G6-S and the default CTP route remain closed.**

## Verified candidate

Independently reviewed the frozen SDK candidate at D:\temp\iteration41-g4r2-settlement-query-candidate-20260927. Its source manifest is DA9D20D35D0B5680267F1A95C5B7FFF54F25E9F57F0DFDA270B55EB7F251EBE9. The manifest and freeze receipt bind exactly three changes:

| Changed file | SHA-256 |
| --- | --- |
| src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py | 53333798198177dd675f96478d8d7d2d0445e2e41459e54d4f021bdd32fa3282 |
| src/bt_api_ctp/__init__.py | 246f5963130219d87c7773637c840b2b6ff5b99ce97dd2c0c1cef670197de505 |
| tests/test_ctp_settlement_query_evidence.py | d8ce90248acbf87ee8e05525e4102eb9d917ac7e13e42d2feb2d0c3bc11b4e65 |

Clean G4-r2 source-a is based on D:\q\e at 29f8ff171f61a71038328a7067e0909bf44774b2. Its source-manifest SHA-256 is 10aa5dae8464dcccff6ac831ff7e6e63106efef6adcae81c00eac38618d45b9a and evidence-manifest SHA-256 is d579ef460d9fd1b9e03364f7e96f9c58cf1afc78b72eaa326bcb7225829c9dc7. The clean source-a client.py hash C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF is unchanged in this candidate. The review compared 238 source/test files from source-a with 239 candidate files: only the two manifest-declared modules changed and the settlement fake test was added. The isolated QA copy matched the frozen candidate source/test tree exactly.

## Independent checks

- In the isolated QA copy, CPython 3.11.5 ran python -m pytest --noconftest tests/test_ctp_settlement_query_evidence.py tests/test_ctp_native_query_certificate.py -q --tb=short: **48 passed, 2 warnings**.
- The fake suite covers actual request-field getter readback, exact BrokerID/InvestorID filters, terminal and request identity, row count/account/day scope, optional mismatching TradingDay, payload mutation and session-generation changes. Getter normalization and getter failure reject before the fake query API is called.
- Two supplemental fake negatives also passed: a result from another client issuer rejects as query_client_mismatch; a mismatched current query-history readback rejects as settlement_query_current_result_mismatch.
- The native import guard intercepted both _ctp import attempts during pytest. The source-origin smoke loaded bt_api_ctp and the evidence module from the isolated candidate copy, with no _ctp module in sys.modules. No native extension or API was loaded or called.
- The available settlement response type exposes BrokerID, InvestorID and ConfirmDate, with no TradingDay. QuerySource/session supplies TradingDay. No native callback was exercised.

## Lineage correction

The clean G4-r2 source-a client at lines 8021-8051 passes request_filter_field=field and request_intent_filters=intent_filters at 8049-8050. _execute_query lines 7491-7547 reads native getters before submit; OnRspQrySettlementInfoConfirm is at line 4019. This corrects the lineage scope: the missing-filter finding applies only to dirty d3674e19 / CTP submodule ce1edd607 source, client hash B61B32F9A2A2E61035BF88BCB7ACF669C8C7EE8E5BF5D7E1F6E375E69F053EAB (query lines 6171-6184 omit filter arguments; _execute_query begins at 5753). Its certificate hash A76E4E1245E84C782FFB9A92B4A804C377FC58C7F3672FD33265E3260E059FBE still has only the seven query types and excludes settlement.

## Limits

- terminal_callback_history_sha256 is a digest over in-process sealed source and final QueryResult facts. It is not a durable ordered callback inbox, signed provider receipt, independent callback audit log, or account-wide writer fence.
- This is an additive SDK evidence helper only. It does not replace the SDK settlement-readiness promotion method, is not consumed by backtrader_runtime/ctp_simnow_td_trading_readiness.py, and does not change the existing seven-query certificate builder. No wheel, SDK pin, registration, main readiness gate or write route changed.
- No provider, network, credential, account, protected config or live/native access occurred. All account strings and query callbacks were synthetic.

## Related G6-S matrix provenance correction

Root and guardian_qa verified the frozen G6-S r1 manifest bytes: its acceptance-matrix path is valid canonical Unicode, contains no U+FFFD, and resolves. The earlier mojibake-path diagnosis was incorrect. The r1 matrix digest is historical because matrix content changed later; this review does not alter frozen G6-S r1.

## Frozen review archive

- Raw ZIP: [ctp-g4r2-settlement-query-evidence-independent-review-2026-09-27.raw.zip](ctp-g4r2-settlement-query-evidence-independent-review-2026-09-27.raw.zip)
- ZIP SHA-256: 0a3722ffdb772ee4ec5e19e227a7e25f9fc497d7d285f23de4db150f54f51daf
- Independent receipt: [independent-review-receipt.json](ctp-g4r2-settlement-query-evidence-independent-review-2026-09-27/independent-review/independent-review-receipt.json) (SHA-256 d57ca79a31246b2243c800035e3bd95b63844409d59113e29cac2e1c78b0a6ac)
- The archive contains the candidate Python source and test inputs, clean/dirty lineage references, author evidence, independent stdout/guard logs and SHA256SUMS.txt. Native binary payloads are omitted.
