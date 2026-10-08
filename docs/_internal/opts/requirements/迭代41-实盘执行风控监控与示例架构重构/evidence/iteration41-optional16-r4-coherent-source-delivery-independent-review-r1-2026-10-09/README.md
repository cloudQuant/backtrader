# Optional16 R4 coherent source delivery — independent review

**Verdict: GO_SOURCE_DELIVERY_ONLY**

**Review scope:** exact frozen public source/fixture/evidence closure and byte-preservation proposal for the R4 sourcefake round. This is not an R4 actual-call or Optional16 acceptance.

## Frozen packet pins

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Delivery manifest | 78,291 | d2cedaa8040e217e0ffce6416151dc09f39b1d39e2602e57a3205b6be6332f9f |
| Packet index | 4,188 | e9587a12204860f4ba3ed1bb19b857b2ba21b34ff616071ac98ce7c3683abf6a |
| Packet README | 4,101 | 492464ae988e6197f5e90178d7eb1e0889c3962931a9e4de2cf9e87f29ce85ce |
| Proposed 42-path -text rules | 6,586 | 2246c09b2bda43093ec7e2ea20a8f1e1a8364d015b1167f4daafa65489f0da72 |
| Frozen sourcefake QA receipt | 68,351 | cb366f766fdcf0bed400bd892acf82a5395e143c22e63d425d5068cb45814ff7 |
| Root delivery precheck receipt | 27,443 | b1ce5871216685e0c237abd73211f0e13713944f7514fccb1311abdbdbefa16d |

The packet index pins its 12 listed artifacts. Its own 4,188-byte pin is recorded by the separate delivery-packet receipt; it does not recursively pin itself.

## Closure checks

I independently rehashed all 51 unique input rows in the frozen manifest against the current worktree. All paths exist, sizes and SHA-256 values match, and there are no duplicate paths or pin mismatches. The manifest's membership split also matches current Git state at 16d49d3ee40f9628ae461a38117201e90ee1483d: 23 clean tracked inputs and 28 untracked inputs, with zero dirty or staged members. The old inventory's 14/37 membership labels are superseded by the corrected 23/28 split; the nine corrected paths are already tracked and clean.

The source closure is coherent for the recorded sourcefake checks:

- The outer source map has 42 rows: 35 frozen source-index rows, six support rows, and the pinned Root runner fixture.
- Nine additional direct inputs support the R4 sourcefake chain: the tracked CUv2 public source snapshot, the R4 independent source review, the R1–R4 reconciliation helper sources, Call R1, tests/__init__.py, and the R4 test.
- The proposed closure carries 29 payload paths: the 28 untracked inputs plus the byte-preservation member tests/__init__.py. The other 22 tracked inputs already have exact raw HEAD/worktree bytes.
- I found no safe omission that preserves the frozen 51-pin check and complete sourcefake closure. The two source-packet ZIPs are pinned as opaque archive bytes; this review did not extract them or read .blob/.pyc payloads.

The 43-path delivery whitelist is unique and contains the 29 closure paths, 13 packet files, and .gitattributes. The proposed cross-platform rules have 42 unique entries and match the delivery list exactly after excluding .gitattributes. I checked all 42 effective text attributes: each is currently unspecified. The unchanged .gitattributes file is 53,683 bytes, SHA-256 3c31648a8b4263428e36cd3184f37c6ad3323f2ba0217819dfdcb93d1e27e713.

The path-specific rules cover every new pinned source, fixture, QA and delivery file, including tests/__init__.py. That file is semantically unchanged but its current 30-byte CRLF worktree form differs from its 29-byte LF HEAD blob; with core.autocrlf=true, its exact 30-byte reviewed blob needs the proposed tests/__init__.py -text rule. Preserve existing .gitattributes entries and append only the reviewed missing rules. Root's final round/scope records are outside this packet's 43 paths; if included in the same delivery, pin them explicitly and give each new pinned file its own path-specific -text rule.

## QA and limits

No QA was rerun for this delivery review. The frozen guarded receipt records 47 passed, zero skipped, exit 0, six checked repository origins with zero mismatches, and matching pre/post 51-input pins on QA HEAD 9617fb3280d92edd1eae0198877d9438fd8cce5c. The receipt records no provider, network, native, WinAPI, private-input or external software-payload reads. Its zero process counters describe guarded candidate operations; pytest itself ran in the guarded harness process.

The evidence level remains sourcefake and source-delivery only. The Root caller fixture filters the run-assignment/exits path, so historical PREP_RESULT assignment identity is not proven. This review does not authorize another Root call, software/cache payload access, installer/preparation execution, or activation. Formal Optional16 remains **0/16**.

**Repository:** D:/source_code/backtrader, branch dev; reviewed HEAD 16d49d3ee40f9628ae461a38117201e90ee1483d. No source/test changes, staging, commit, QA rerun, or actual-host action was performed.