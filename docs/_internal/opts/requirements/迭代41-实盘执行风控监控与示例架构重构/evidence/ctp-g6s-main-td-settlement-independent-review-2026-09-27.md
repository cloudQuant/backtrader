# G6-S TD settlement consumer — independent review

**Status: isolated fake-only review; not G6-S acceptance.** The reviewed frozen
candidate manifest is `1FD47CFF2514FA25E4298EFE7051989AD97427C8056693374004791D6B983661` at
`D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927`. Its 117 manifest payload files were verified against the
manifest and copied byte-for-byte into `candidate/` here. The original freeze
receipt is preserved unchanged.

The candidate's focused suite was rerun from a separate source copy: **22
passed**. Seven additional QA-only negative tests also passed. The tests cover
missing request-filter, history, generation and SDK evidence digests; missing
SDK source-manifest identity before the query; a fake public seal check that
raises; and a wrong-day native `ConfirmDate`-only row. Every failure asserted
zero settlement-confirm, order-insert and order-action writes. A separate
fresh-process import guard verified that the readiness module came from the QA
copy and blocked all `bt_api_ctp` imports.

The frozen candidate changes two runtime files plus its candidate-specific
README relative to the recorded main base. The main production readiness file
and test still hash to their frozen base values after review. The candidate
keeps the exact selected TD pair and session day; it contains no time/set
fallback. If exact current settlement provenance is absent, it fails closed.

## Trust boundary and blockers

The required verifier is an injected Python seam. The consumer compares its
`source_manifest_sha256` string to the expected G4-r2 digest and checks the
returned evidence shape/digests, but that string does not attest the verifier
implementation or installed SDK bytes. The nominal class module/name can also
be imitated. The candidate has no code-owned production adapter wired to the
SDK builder, no OS-backed trust anchor, and no durable callback inbox or
cross-process signature. The fake success result therefore verifies consumer
shape handling only; it does not prove settlement or trading authorization.

Native CTP settlement confirmation rows contain `ConfirmDate`, not
`TradingDay`. The candidate binds that date to the independently sealed
current session TradingDay. No native, provider, network, credentials, or
private config were used. G2, G4, G6-S and the default route remain closed; no
write authority is granted.

See `independent-review-receipt.json`, `SHA256SUMS.txt`, `candidate/` and
`independent/` for hashes, frozen source, original candidate logs, isolated
reruns, negative tests and import guard.


Raw archive: `ctp-g6s-main-td-settlement-independent-review-2026-09-27.raw.zip`

Raw ZIP SHA-256: `9696C1195C2C5186CD46AB685D111B542F572A5612EB281B66E1D5A4677F1172`

SHA256SUMS entries: 130; candidate payload entries: 117.
