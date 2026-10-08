# TradeLogger configuration snapshot seam development round

**Date:** 2026-10-09  
**Repository/branch:** `D:/source_code/backtrader`, existing `dev`  
**Parent:** `567a204660f10befccddc55663b96991ad04f6ab`  
**Scope:** `SOURCE_FAKE_COMPONENT_ONLY`  
**Round state:** accepted source-fake component; ready for Root's exact-scope staging and commit.

## Accepted scope

The three candidate files implement the TradeLogger configuration snapshot seam, add Strategy-owned observer-start context, and cover the lifecycle with focused tests. Inspection found no unrelated hunk in the two production files: `trade_logger.py` has 273 additions/8 deletions; `strategy.py` has 6 additions/1 deletion.

The six tracked-clean compatibility tests are the three existing TradeLogger observer unit tests and three TradeLogger integration tests. Ten more tracked-clean core and fixture files form the fixed Root source closure. All 16 clean inputs are pinned in the manifest and excluded from additions.

The proposed 13-file round is: 3 candidate source/test files; 3 independent review artifacts; 2 R1 historical QA files; 2 accepted R2 QA archive files; 2 delivery metadata files; and `.gitattributes` with 12 proposed exact quoted `-text` rules. The manifest pins every payload and clean input, records baseline `.gitattributes` hash, and reports its own SHA-256 below. It does not modify `.gitattributes` or the index.

## Root source QA

Independent review verdict: `GO_SOURCE_FAKE_ONLY; RECEIPT_ALONE_NOT_ROOT_ENGINE_PROOF`. Author and independent source-fake runs each passed 4 focused tests and 76 compatibility tests, with one existing pytest configuration warning per run.

Root R2 tool `4c6eb5` (process handle `21075`) passed 76 tests in 32.47 seconds, exit 0, with exactly 15 known warnings: one existing Quandl deprecation and fourteen unknown integration-mark warnings from the isolated config. Its archived result records four private-path guard self-checks, four framework module origins, and all 20 exact pre/post pins. Candidate imports occurred only after private/native/SDK/network/process/Pipe denials. No private open, provider/account action, or formal case pass occurred.

R1's 76-pass output is preserved as compatibility history only. Root audit found its path-normalization expression matched pairs of backslashes, so the R1 private-path guard did not fully check single Windows separators. R1 is excluded as acceptance evidence. Earlier harness setup failures and the complete R1/R2 source/results are preserved in the manifest.

## Delivery pins

Delivery manifest SHA-256: `4320bb8379474511aea8b39661d8b8d88e177bc3d29af6fc541234a7d51f5bf9`. The round-record SHA-256 is reported out of band. The exact whitelist, pins, unchanged dependencies, baseline attributes hash, and proposed attribute lines are in [`delivery-manifest.json`](delivery-manifest.json).

## Evidence limits

This round establishes `SOURCE_FAKE_COMPONENT_ONLY`. Tests use synthetic local data and do not establish real provider/account behavior, a native or network result, or a formal case pass. The receipt alone does not prove account-call ordering through an actual certification path.

Unrelated pre-existing working-tree changes remain untouched. No staging or commit was performed by this preparation agent. Root may stage only the 10 payload paths, 2 delivery metadata paths, and the proposed `.gitattributes` rules after the exact-scope/index check.
