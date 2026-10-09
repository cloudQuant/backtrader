# Root focused QA draft: V20 preparation source-fake R5

Status: `DRAFT_FOR_ROOT_RUN / NOT_EXECUTED_BY_AUTHOR`.

This packet supplies a guarded Root-run command for the frozen R5 preparation
composition. It is not a gate or account invocation. The command runs only the
12 pinned source-fake cases in the R5 test file.

## Fixed inputs

- R5 packet: `iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09/`.
- R5 `artifact-pins.json`: SHA-256
  `62ddd86cc141a4b94dbe5eee6736c7b13099133f890e77a0f931f90d31bfef16`;
  its eight artifacts are checked before and after pytest.
- R5 runtime source map: SHA-256
  `e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387`;
  exactly 26 public source rows are checked before and after pytest.
- R5 independent static review: SHA-256
  `4dd6725c42dfc2b8f8ef6a2d8cb7952f4bde27a7995fb867fd6e916eab6fbfba`;
  verdict `GO_STATIC_REVIEW_ONLY / R4_PREPARATION_PLUS_R5_TEST_CLEANUP / EXECUTION_NOT_RUN`.
- Runtime source metadata declares three software rows. The runner verifies
  only their public metadata and denies reads of the executable, runtime DLL,
  and CUv2 helper. It never loads those bodies.

## Guarded execution

Run the command in `qa/command.txt` from the repository root with Root's QA
interpreter, where pytest is installed. The runner binds its own eight packet
artifacts, the R5 eight-artifact packet, and all 26 public source rows. It
records finite pytest counts and warning categories, pytest origin category,
public source origins, and before/after source plus Git HEAD/index identities.
Each invocation writes one fresh result under this packet's `runs/` directory.

Before importing pytest, the runner installs guards that deny:

- `.env`, `config.yaml`, `secrets.yaml`, capture directories, and files outside
  the repository, selected Python environment, or fresh QA output directory;
- all three software payload paths, including CUv2, and all `D:/temp` reads;
- native library loads, provider/SDK imports, network calls, and process or
  child-process creation;
- writes outside the fresh QA result directory.

The test uses synthetic CUv2 bytes, synthetic software pin values, and a
synthetic in-memory lease boundary. It does not read real CUv2/software
payloads. A QA result can only be `PASS_SOURCE_FAKE_ONLY`; official C01 PASS
remains 0. The result schema is in `result-schema.json`.

The runner and this draft have not been executed. Root should bind the final
interpreter/pytest origin and run-result pins to the current source checkpoint
before considering the separate credential-free Job/channel gate.

## Packet verification

`artifact-pins.json` binds the eight fixed draft files and the runner checks
their byte counts and SHA-256 values before proceeding. Pinned paths are
resolved and required to remain inside their designated packet or repository
root, so a symlink cannot redirect a source read outside the public inputs.
The result records whether the three source-loader assertion cases were
collected; it does not infer source provenance from a test count alone.
