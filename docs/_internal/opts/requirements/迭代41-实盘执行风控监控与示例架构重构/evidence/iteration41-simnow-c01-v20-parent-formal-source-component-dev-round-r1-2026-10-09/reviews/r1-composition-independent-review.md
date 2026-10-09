# SimNow C01 V20 parent formal-composition independent review R1

**Verdict: GO_SOURCE_FAKE_PARENT_FORMAL_COMPOSITION_ONLY**

Review date: 2026-10-09. This review covers the frozen additive 26-parent-module / 23-child-frame V20 composition source and its eight focused test files. It does not approve Root activation, any actual Windows lifecycle, provider/account operation, or formal SimNow C01 acceptance.

## Frozen binding

Packet: `iteration41-simnow-c01-v20-parent-formal-composition-r1-2026-10-09`

- `candidate-pins.json`: 11,291 bytes, SHA-256 `68d2626ce4a14c4b95a15c59608bcc4103b00ab6ffec04ffee2c26b5b58215f9`
- `artifact-pins.json`: 1,049 bytes, SHA-256 `73ce21de624ec921d3716f7c241a44dc6f78617a85e84ce03c06c5012b6c0c3c`
- Root V17: SHA-256 `5fc2f7acd7ca0c2e107f846d637a6716c000b61d0b211ec9a2f21651025b7481`
- Parent driver: SHA-256 `e955b7887df5a6a975c8bf7ae264c4696d0dc09e25c2d98ddce0195f5fa210e8`
- Child wrapper: SHA-256 `752e59c2bb8bbbe4f26930182cb22d638a2747e5122fed3215bf7e0f9f3a8be6`
- Formal adjudicator: SHA-256 `743e9507157092d7f3c9b284e5775d895cbe42c1caf1da6fb9e1cbb8e1eb2db7`
- Completion adapter: SHA-256 `1d5e1183368b5bb1c4363056673a483d21e6e02b1bf342b6ac69b12a9b891f90`
- V20 composition source-fake test: SHA-256 `522a42ae435f624c2d5519144670ce73faa663b0c32e5ef206f20968da292843`

All 26 source rows and eight focused test rows matched their recorded sizes and SHA-256 values before and after independent QA. All six packet artifacts listed in `artifact-pins.json` matched as well.

## Independent verification

Using `D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and `-p no:asyncio`:

- The exact eight-file combined source-fake suite passed **118 tests**, exit 0, in 104.45 seconds.
- The singled-out production-loaded composition case passed **1 test**, with six deselected, exit 0, in 69.34 seconds.
- Both runs emitted the known `PytestConfigWarning` for the unrecognized `asyncio_default_fixture_loop_scope` option.

## Review results

The parent closure has exactly 26 module paths: the 23 paths used by the child frame plus the parent driver, formal adjudicator, and completion adapter. Root V17 checks exact parent source/object/pin/held-byte map membership, module origin and name, byte digests, source object snapshots, function code/globals, and parent receipt bindings. The frame decoder still requires exactly the 23 child source pins and checks those pins against the 26-member parent map.

The completion path obtains `create_c01_root_invocation_receipt`, `mint_c01_root_formal_pass_proof`, and `consume_c01_root_formal_pass` from the captured source-object maps. Root V17 links the same frame to the process, wrapper, and outer-close receipts, revalidates the frame and child projection, and provides source-derived invocation/account bindings. The adjudicator revalidates those bindings and content before minting its one-use proof. The completion adapter pins the adjudicator source and consumes that proof before constructing its finite result. The focused composition test production-loads these source modules, closes a synthetic CUv2 context, traverses the exact V17 receipt factory, adjudicator, and completion adapter, and labels the local PASS/count as source-fake-only.

The fixed parent launcher source retains the reviewed lifecycle protections: three distinct pipes and NUL stdin; exact four-handle inheritance; atomic Job/handle-list setup at suspended creation; pre-resume Job count check; readers started before resume; checked process-handle close before bounded Job-zero polling; no termination when Job state is unobserved; forced cleanup produces only a BLOCKED result; and uncertain handles, attribute storage, fd ownership, reader joins, or BaseException paths preserve custody. The prior eight lifecycle findings recorded in the historical parent review remain repaired in these frozen bytes.

## Limits

The review and tests made no WinAPI call, OS process launch, real Pipe operation, SDK import/use, credential/private-input read, provider/account access, or network request. The test uses synthetic process and CUv2 leaves. This is source-fake composition evidence only; formal SimNow C01 remains **0 passes**. No candidate file was edited, staged, or committed.