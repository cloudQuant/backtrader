# Independent QA — G6-S settlement consumer r2

**Disposition: `FAKE_LOCAL_CONTRACT_ONLY / G6-S CLOSED / G7-S CLOSED`.** The r2 freeze and its narrow strict-type repair were independently verified. Its 39-test focus passed. The consumer's own function returns a shape receipt with `provider_source_trusted=false` and `execution_authorized=false`; neither the injected attestor nor the receipt DTO is an authority token, and the candidate is not wired into the main runtime.

## Frozen artifact and r1 lineage

- r2 manifest SHA-256: `f989c834be030e7f7227cea408697c4b98fa7f750f55c1c4bbaa59d318976587` — matches.
- r2 archive SHA-256: `6302f9ebb04b1c33f7d25da228e5ee215beedced7a9061173201c005939bad03` — matches.
- Extracted r2 verifier: all checks passed, **92 payload entries / 94 ZIP members**, CRC okay; source-snapshot and reference checks passed.
- r1 lineage: nested manifest `d39dbfa40185bd8f12704cd158c59a35d6737ef6a8d58d0a0aa165a144128486`, ZIP `9f4e2f169384c56dd2b95e755074c4035684c0140946d7dba623114c1236e8bb`; nested candidate verifier passed. The preserved r1 independent QA receipt says **35 focused + 21 adversarial passed**. All 47 files listed in the earlier canonical r1 `SHA256SUMS.txt` match the r2-preserved lineage copy, and the report is byte-identical.
- The 24 r1/r2 shared paths show functional source changes only in `ctp_simnow_settlement_consumer.py` and its focused test. All shared input snapshots are unchanged. The source/test unified diffs are preserved in this packet.

## Independent execution

The r2 focused target passed **39/39** from a fresh extraction. A startup `sitecustomize` hook actively blocked `bt_api_ctp` and `_ctp`; direct import smoke confirmed the hook was active and no forbidden module loaded. Tests and probes use only synthetic `tmp_path` config under the existing test fixture's ACL monkeypatch. No protected/private config was read.

A separate **34-test** QA-only suite passed. It confirmed:

- r1 counterexamples are rejected before any fake write: query/current generation `True`; `error_code=False`; `submit_code=False`.
- Generation booleans, floats, zero, and negative values reject; native result codes accept only `None` or exact built-in integer zero; other status/count/request fields reject bool/int aliasing.
- Request filter readback, callback/source/history, selected pair/account/day/generation, row identity, and ConfirmDate checks remain fail-closed. A `ConfirmDate`-only synthetic row succeeds as shape evidence, not as a native TradingDay field.
- Each returned success checked by the function has `consumer_contract_satisfied=true`, `provider_source_trusted=false`, and `execution_authorized=false`.

## Remaining boundary concerns

1. **Attestor remains an unauthenticated injection.** A mutable property supplying `attest_current_settlement` is looked up twice: once for the callable check and again for invocation. A QA-only object returned a different callable on the second access and supplied correctly shaped synthetic evidence. The consumer accepted only the shape; its returned trust/authorization flags remained false. Capturing the bound callable once would avoid this same-call accessor inconsistency, but would not authenticate the attestor.
2. **The receipt dataclass is caller-constructible.** The `consume_current_settlement_readiness()` path emits false trust/authorization flags, but any caller can instantiate the public dataclass with those flags set to true. A downstream caller must not treat nominal DTO type or `consumer_contract_satisfied` as provider trust or execution authority.
3. **Provider provenance is unproved.** The consumer validates pin strings and digest formats but cannot authenticate the injected attestor, recompute callback/source/history digests, or establish durable provider origin. The clean SDK query evidence is not itself a durable external receipt.
4. **No main integration.** Static search of `backtrader_runtime` found no consumer import or call. The helper is not registered or exposed through CLI; this candidate does not alter runtime behavior.

No CTP SDK, `_ctp`, native library, provider, credential, private config, network, order, cancel, or settlement write was used. This review does not accept G6-S or G7-S.

## QA harness notes

Two preliminary lineage-helper attempts are retained as *-harness-error* logs. One expected the prior checksum list to be embedded in the r2 lineage directory; the other passed the extracted path instead of the candidate root to the delta script. Both were harness path/assumption mistakes. The corrected lineage comparison against the already-canonical r1 checksum list passed all 47 file checks, and the corrected delta script found the expected two functional source/test changes. These attempts are not candidate test failures.


The first QA-package verifier script itself called zipfile.testzip() after closing the archive and raised ValueError; that packaging-tool attempt and first ZIP are preserved as verify_qa_zip-attempt1.py, evidence-zip-verifier-attempt1.txt, and the adjacent *-archive-attempt1.zip. The corrected verifier completed CRC and file-hash checks successfully. This did not affect either candidate or pytest execution.

