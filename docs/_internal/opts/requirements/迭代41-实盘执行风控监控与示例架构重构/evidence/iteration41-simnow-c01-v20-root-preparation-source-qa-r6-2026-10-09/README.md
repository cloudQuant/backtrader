# Root focused QA draft: V20 preparation source-fake R6

Status: `DRAFT_FOR_ROOT_REVIEW / NOT_EXECUTED_BY_AUTHOR`.

R6 is additive. It preserves R1 through R5, including consumed R4 and R5 QA
results and the independent R5 failure-path review. The runner selects the same
12 pinned source-fake cases, checks the same 42 input rows and uses the same
fixed QA interpreter. It does not invoke the credential-free gate or C01
activation. Official C01 PASS remains 0.

## R5 outcome and R6 change

Root consumed the frozen R5 command once. Its sanitized result is
`.codex-tmp/i41q/af4e183d48ec4da38b8fa79d3cdb89c1/result.json`, 20,250 bytes,
SHA-256
`50e240b0bf0b75899baa0d312f3d65068e037c86f6d5b337dba97981144496c8`. It
reported 12 collected, 11 passed, one error, pytest exit 1, and one
`file_outside_public_qa_roots` attempt. All 42 source-input rows, ten packet
artifacts, and repository metadata matched before and after. The result did
not retain a denied path, failed node, phase, or traceback, so the exact denial
is unavailable.

Public pytest source shows that when an explicit `--basetemp` already exists,
pytest removes it through `rm_rf`; on Windows this path helper can add an
extended local-drive prefix. Root's metadata-only path probe showed that the
extended spelling does not compare as a descendant of the normal run directory
after `Path.resolve()`. This is the likely cause of the R5 error, inferred from
the source path and the probe; it was not recorded in the R5 result. The
independent review records the same limitation and cause as an inference:
`iteration41-simnow-c01-v20-root-preparation-source-qa-r5-independent-static-review-2026-10-09/README.md`,
SHA-256 `aa2f10aa5960d27d28772b6a642c3b88649ee3a940568167228ffdd9050da7be`.

R6 creates only the fresh run directory. It leaves the `pytest-tmp` basetemp
child absent so pytest can create it without first removing it. It does not
broaden path authorization. On a failing selected test, the runner records
only a finite test name and phase, a whitelisted exception class, safe guard
event/category labels, two path-classification booleans, and up to 16 public
source-frame labels/function names/line numbers. It stores no raw path,
exception text, locals, or credential-bearing values. A passing result
requires an empty failure-diagnostics list.

## Frozen inputs

- R1 packet pins: `6e512153dfecc182a2fe772f4b4be445b7dc7702a329e321825167e88346fe2b`.
- R1 independent review: `a0969324876b9bf3cbe9f005a70300dc568719517b5165e743d88d3f2d5b39aa`.
- R5 preparation packet pins: `62ddd86cc141a4b94dbe5eee6736c7b13099133f890e77a0f931f90d31bfef16`.
- R5 runtime source map: `e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387`.
- R5 independent static review: `4dd6725c42dfc2b8f8ef6a2d8cb7952f4bde27a7995fb867fd6e916eab6fbfba`.

The runner verifies the eight artifacts in each historical R1 and R5 packet,
the 26 public source rows, and the ten R6 QA packet artifacts before and after
pytest. Software metadata is compared by value; the runner does not open
CPython software pins or CUv2 payload.

## Root command and preconditions

Run the exact PowerShell command in `qa/command.txt` from the repository root.
It uses the fixed QA interpreter with `-I -B -X utf8` and intentionally omits
`-S`; the runner verifies the interpreter, pytest origin, and startup flags.
Pytest uses `--noconftest`, `--capture=sys`, and a fresh log path. An inert
colorama facade is installed after native guards and before pytest import.
The runner checks public Git metadata before and after, without launching Git.

The exact Root-attested checkpoint bound by this draft is branch
`refs/heads/dev`, HEAD `902d55daa397d601a947141b6a87eb1ca1df4d0a`, HEAD-file SHA-256
`bda77d7d12a90332080071375095fb080d8cd2a6702e6ee44552863a0ca4317e`, and raw
index size/SHA-256/entry-count `2,863,553 / b555903584c1b95e5f0da20fcef2fe87095bf608cd12a97e8b5e45b2af5a189b / 13,505`.
Root independently confirmed the cached diff was empty and the raw index was
unchanged when preparing this baseline. Root must recheck that baseline before
running the command; index entry count alone does not establish cleanliness.

This is a task-specific guarded source-fake run, not a general filesystem
sandbox. It blocks the fixed private/config/capture and software payload paths,
provider/SDK imports, native loading, network access, process creation, and
writes outside the fresh run directory. It does not read software payloads or
private inputs and does not establish gate, provider, account, or trading
behavior. The author did not run R6 QA or any actual gate. The next acceptance
decision remains Root's after independent review and Root-run QA.
