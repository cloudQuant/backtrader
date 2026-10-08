# Optional16 R4 source reconciliation delivery packet

**Classification:** `SOURCE_FAKE_SOURCE_RECONCILIATION_COMPONENT_ONLY`.

The frozen sourcefake QA ran at `dev` HEAD `9617fb3280d92edd1eae0198877d9438fd8cce5c` and passed 47/47 tests with no skips or failures. The current delivery inventory is at `dev` HEAD `16d49d3ee40f9628ae461a38117201e90ee1483d`. The QA was not rerun at this later HEAD. Root's separate current-state precheck confirmed the same 51 accepted input pins at the delivery HEAD.

## Current closure

- 51 frozen sourcefake inputs: 42 outer-map rows and 9 direct non-outer inputs.
- At current HEAD: 23 inputs are clean and tracked; 28 remain untracked; none of the 51 is dirty or missing; all 51 raw worktree bytes match their frozen SHA-256 and size.
- All 14 clean rows from the older inventory remain clean. Nine additional inputs are now tracked and clean, including `cuv2-source.py`.
- The proposed closure payload is 28 untracked inputs plus tracked `tests/__init__.py` as a byte-preservation member. The separate `.gitattributes` proposal is exactly `tests/__init__.py -text` and was not applied.
- On this Windows checkout, `core.autocrlf=true`: `tests/__init__.py` is 30-byte CRLF raw content matching its QA pin, while the current Git HEAD blob is 29-byte LF content. Its status is clean. The staged blob must be the 30-byte pinned raw content after the proposed `-text` rule is separately reviewed and applied.

## Frozen sourcefake evidence

Harness: `a037a10753262527985e887d8354d2a5bc55b75b41dc87724bf386fccb3fada4` (64,868 bytes). Receipt: `cb366f766fdcf0bed400bd892acf82a5395e143c22e63d425d5068cb45814ff7` (68,351 bytes). The receipt records 47 passed, 0 skipped, 0 failures, six repository source origins matched, all 51 pre/post inputs and Git snapshot stable on the QA HEAD, and zero observed forbidden-operation counts.

The sourcefake used synthetic Root scopes, credential/storage/provider leaves, and executable/DLL placeholders. It did not make an actual Root call, read private inputs or external software payloads, or call a provider, network, native API, or WinAPI. There is no child-process transcript: the receipt reports zero process and multiprocessing attempts. The saved stdout and finite runner diagnostic are included.

The Root runner is a public sourcefake fixture. The tests filter its `PREP_RESULT` assignment and exit branch before constructing synthetic scopes. This does not prove the historical assignment identity. Formal Optional16 remains 0/16; no actual R4 call is claimed.

## Frozen harness command

The receipt did not save the original shell command string. This reconstructs the frozen harness CLI from its pinned parser and interpreter origin; it is shown for provenance and was **not rerun** during delivery preparation. Its saved QA result is for HEAD `9617fb3280d92edd1eae0198877d9438fd8cce5c`.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe' -I -S -B -X utf8 `
  'D:/source_code/backtrader/.codex-tmp/optional16_r4_sourcefake_guarded_r2.py' `
  --run-sourcefake --self-sha256 a037a10753262527985e887d8354d2a5bc55b75b41dc87724bf386fccb3fada4
```

Running it would create a new receipt under `.codex-tmp`; this packet preserves the existing result and makes no new QA claim.

## Proposed exact add scope

`proposed-closure-whitelist.txt` lists the 29 closure input paths. `proposed-attribute-rule.txt` records the single line-ending rule proposal. `proposed-delivery-whitelist.txt` lists the full 43-path candidate set: closure inputs, `.gitattributes`, and these packet artifacts. No path was staged or committed. Verify each raw source hash immediately before any future staging, stage only this list, verify the cached path set and blobs, and keep unrelated edits unstaged.

Packet member hashes are in `packet-index.json`; the index itself is pinned in the delivery receipt reported by the packet builder. The original untracked inventory draft remains historical and is not edited.
