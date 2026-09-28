# Independent QA Receipt — G1 overlapped-I/O channel custody

**Verdict: `GO_LOCAL_SUBGATE` only. Strict whole-command G1 remains `NO_GO`.**

Date: 2026-09-28 (Asia/Singapore)
QA copy: `D:\temp\ac41-g1-overlapped-channel-custody-qa-20260928-a`
Frozen candidate: `D:\temp\ac41-g1-overlapped-channel-custody-20260927`
Baseline checkout: `D:\source_code\backtrader`

## Frozen identity and replay

The current checkout's two baseline preimages matched the frozen manifest exactly. The final frozen candidate identity also matched the manifest:

| Artifact | SHA-256 |
| --- | --- |
| Baseline `scripts/ctp_i13_i15_worker_output_channel.py` | `c32dbe7c850e07fde6a3e57f5b29ca45803cfa5b8f3bea103d5e0582b4656222` |
| Baseline `tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py` | `10f814f004843dbd404640fb2041763bdb087fa18ec7478c48c4b21ec43a287c` |
| Frozen candidate channel source | `4f9ff31428cdfd9d62acc8118ae4bb00bc09cc0e5883fb07c6b1daea85f41178` |
| Frozen candidate test source | `25332e48979f7827fa97e5dc4c8fa4fb7acd8eb17262c505bde4f4afec182861` |
| Frozen `PATCH.diff` | `c27ddf0d605a9705956dff9ba00b05f3b6640492162c8e58f4e07d4791a44bdd` |
| Frozen `FROZEN-MANIFEST.json` | `074235d2ff29afb6256ef385f29f5c6b7a9e84be8eacbb3bc3fb4fbaa472668c` |

Support preimages also match their manifest hashes: `scripts/__init__.py` `fc4fa253c49a6d8148d2f24aae77d0e3b8cf3596380cd4a81fae9233c9643fdb`; `scripts/ctp_i13_i15_outer_watchdog.py` `f738f5deac1e7e5a7db101b72343677bb299f49451a8325cf1defe1305799a79`; `scripts/ctp_i13_i15_windows_job_backend.py` `c1e83f7075f48fa16f5db862d0ef95aec1eed2e8551464c9e990dbb3ecd324fd`.

I copied the baseline preimages and support files into a newly created QA temp directory, ran `git apply --check`, then applied the frozen patch. Both replayed files were line-for-line identical to the frozen candidates. Windows `git apply` preserved the baseline CRLF style; converting only the two replayed QA files to the candidate's LF style produced exact candidate SHA-256 values above. Final clean replay channel-source hash: `4f9ff31428cdfd9d62acc8118ae4bb00bc09cc0e5883fb07c6b1daea85f41178`.

The QA-only test file, after adding three adversarial cases, has SHA-256 `d5316f7a3b4d0a163684c777e0bbb59b70bce94d9725134e26c01d35c17f158b`. The frozen candidate files and manifest in the original candidate directory were not changed.

## Checks

Frozen candidate replay, before QA-only additions:

```text
python -m pytest -q tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py
.................................                                        [100%]
33 passed in 0.60s
```

QA additions cover CancelIoEx `ERROR_NOT_FOUND` and access-denied followed by a naturally completed operation (both terminal results are consumed before release), plus `CloseHandle` failure retaining the handle and successful retry. Final replay plus these three cases:

```text
python -m pytest -q tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py
....................................                                     [100%]
36 passed in 0.72s

python -m ruff check --config pyproject.toml scripts/ctp_i13_i15_worker_output_channel.py tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py
All checks passed!

python -m py_compile scripts/ctp_i13_i15_worker_output_channel.py tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py
exit 0 (no output)
```

The original 33-test run includes two real local Windows named-pipe/child-process smoke tests; the other cases use fakes. Those smoke tests use a local Python child and a local named pipe only.

## Review findings

- `close()` cancels pipe I/O, then queries and waits for each pending connect/read operation against the already-bound absolute deadline. It removes an OVERLAPPED object only after a successful result or an allowlisted terminal pipe status.
- Incomplete/unknown completion, wait/query failure, failed handle release, or deadline expiry keeps the channel, OVERLAPPED storage/events, descriptor when applicable, and remaining handles in `_RETAINED_UNRESOLVED_CHANNELS`. Unknown status does not release custody. A missed bound deadline is sticky, preventing a retry with a later deadline.
- Native handle close returning at/after D fails the frame read after close; the post-close deadline check prevents late frame publication.
- The pipe is first-instance and rejects remote clients. Security attributes set `bInheritHandle=False`; the server-side DACL is scoped to the service and requested client identities. The descriptor remains attached to the channel if freeing it fails.
- Microsoft documents that `CancelIoEx` does not wait, `ERROR_NOT_FOUND` is not completion proof, and an operation may complete normally, be canceled, or fail. It also requires retaining OVERLAPPED storage until completion. The implementation's post-cancel `GetOverlappedResult`/bounded event-wait path matches those requirements: [CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex), [GetOverlappedResult](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresult), [Canceling Pending I/O Operations](https://learn.microsoft.com/en-us/windows/desktop/FileIO/canceling-pending-i-o-operations).
- The exact current service cleanup call sites invoke `close()` without supplying an unbound future deadline. When the read path has bound D, `close()` uses the same value; otherwise constructor cleanup uses the 250 ms fallback.
- Nonblocking observation: constructor cleanup failure can append the channel twice to the retention list because `close()` already retains it and `_FAILED_CONSTRUCTOR_CHANNELS` aliases that same list. This adds a duplicate list reference but does not release custody or change the subgate verdict.

The candidate/channel path imports no CTP SDK or provider and does not read trading credentials or use external networking. The smoke tests use only the local OS named-pipe/process path. This QA made no edits to the shared repository; all replay and added tests are in the QA temp directory.

## Limits

This is local channel-custody evidence only. It does not prove a hard return bound for synchronous Win32 calls such as `CancelIoEx`, `CloseHandle`, or `LocalFree`, nor for Windows scheduling, SCM startup, outer command launch, or a whole G1 command. A host blocked inside a native call remains outside this subgate's proof. No CTP native/provider, credentials, network route, or live order path was exercised. Keep strict G1 and live/write decisions closed.
