# I13/I15 Offline Source Snapshot Candidate

The isolated worktree `D:\work\backtrader-g1-source-manifest` at local commit
`64c271bf14e917450c23b21c263a9c7e5db6c4f1` contains a reproducible,
non-authorizing source snapshot candidate for the I13 and I15 manifest paths.
This commit is local and has not been published to a shared remote. The source
came from the dirty `D:/source_code/backtrader` working tree based on `HEAD`
`ad2c142b9a8b42cede85886528c681abdfcb8096`. That parent commit alone does not
identify the source bytes; the manifests and candidate worktree commit do.

The post-G5 snapshot contains 91 `backtrader_runtime/**/*.py` source files.
Only those `.py` files were copied from the source tree. No `.env`, private
configuration, credential file, cache, SDK, or provider material was copied.
The final file-by-file comparison found the same 91 paths and zero byte
differences against the parent working tree at capture. The one source changed
since the earlier snapshot was
`backtrader_runtime/ctp_simulation_query_evidence.py`, whose captured SHA-256
is `e85f2bbb855f378eaf4ea618a0c6305bc4623c2af93f07ebb60d49d89056578d`.

The I13 artifact uses schema `1` with a `source_files` path-to-SHA-256 mapping.
The post-G5 manifest-byte SHA-256 is
`ed2f19ba8ac0214c65ac0131c76235c50226d336419d3d41c635631207768cde`.
The I15 artifact uses schema `ctp_i15_source_manifest.v2` with a sorted `files`
array of `{path, sha256}` rows. Its post-G5 manifest-byte SHA-256 is
`367e54f69ed23f9e2ddf77fdcc39ac750f429c116fb5ecf6de819f5cfb0e6d0d`.
The schemas are intentionally distinct while covering the same 91 source
bytes. Both exclude the two pin modules to avoid a self-hash cycle.

The first-cut artifacts are retained under the `current_dirty_tree` and
`source_snapshot` names for audit context. Their I13/I15 manifest hashes are
`6b1639dc9b11b8ff3409a418e4baea5d583cafad4d8ea139b449f0c3ddee8649` and
`49f147d63546ff1c67e810a0be22d4b83eadc63c85d0d037b53cdc0fdec6e8bd`.
They predate the G5 edit to the one file above, so they do not verify the
current 91-file tree and must not be used as this cut's deployment manifest.
The post-G5 artifacts use separate names; the builder refuses to overwrite an
existing candidate with different bytes.

The pin stubs remain closed:

- `ctp_i13_source_identity_pin.py` contains an all-zero SHA-256 placeholder.
- `ctp_i15_source_identity_pin.py` contains `None`.

The candidate manifests live only under `artifacts/`; the runtime manifest
paths are absent. A direct offline check confirmed that the I13 verifier
rejects the post-G5 candidate digest as `source_identity_pin_mismatch`, and
I15 rejects the stub value as `source_pin_unset`. Neither stub is a reviewed
trust root, approval, release pin, or production configuration. The generator
never updates runtime manifest paths, pins, or registry entries.

## Reproduction and offline checks

From this worktree, run:

```powershell
python scripts/build_ctp_i13_i15_source_candidates.py --write-candidates --candidate-label post_g5_current_tree
```

The command should report 91 source files and the post-G5 hashes above. It
writes only the two explicitly named candidate artifacts and is idempotent for
this exact source tree.

An offline temporary-root harness copied only the `.py` source inventory and
placed the post-G5 candidate artifacts at their expected temporary runtime
paths. With the I13 pin monkeypatched in process solely for the algorithm
check, both manifest verifiers accepted all 91 files. Mutating one temporary
copy of `config.py` caused I13 and I15 to reject with source-digest errors.
These fake checks do not activate a runtime route or approve either manifest.

A redacted static scan of the post-G5 tree found no AWS, GitHub, Slack,
PEM-private-key, credential-in-URI, or inline password/token assignment
patterns. The strict high-entropy scan flagged 63 long literals
(length at least 32, no whitespace, Shannon entropy at least 4.2); context
review classified them as code-owned patterns, paths, artifact/strategy
identifiers, hash alphabets, representation strings, and test literals. The
keyword scan found two direct literals under sensitive dictionary keys; both
were in exception-sanitization functions mapping failures to generic reason
codes. It did not find a credential value. This is a local source scan, not a
substitute for a dedicated secret-scanning service.

No wheel was built. No SDK, native library, provider, network, or real preflight
was accessed.

An independent source review replayed the generator, matched all 91 candidate
paths and hashes to the then-current main tree, and passed 27 focused offline
tests. The live I13 zero pin rejected the candidate digest; an in-process
test-only pin substitution showed that the verifier algorithm accepts the
same 91 files. I15's outer run path rejects its unset pin before worker
dispatch. A conditional future integration concern remains: the lower-level
I15 child/artifact helpers can build a bootstrap from a caller-supplied
`source_digest`. Any future route must make those helpers require the exact
code-owned pin too; current unset pin/default route still reject.
