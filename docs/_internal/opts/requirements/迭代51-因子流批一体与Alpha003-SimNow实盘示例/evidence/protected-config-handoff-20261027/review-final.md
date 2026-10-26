# I51 protected SimNow handoff — final static delta review, 2026-10-27

**Decision: GO for `SOURCE_HANDOFF_ONLY` at the recorded synthetic-test level.**
The final helper SHA-256 is
`6d411641a2cf5cafd1ead5fa530c7cd145a138adb84d579e7dcffaaa805847ec`; the
focused test SHA-256 is
`86e9545bfa15b4e47fbab608c7e61596e772b5ab50e28bedfa3c3752a1ef6bcb`.
The public R2 `run.json` records the same two hashes before and after the
pytest process and exit code 0. Its JUnit report records 13 tests, zero
failures, zero errors, and zero skips. I read these results but did not rerun
tests or import the helper.

The final delta resolves the prior representation caveat: both outer and
inner `for_runner()` mappings use `_PrivateMapping` with a value-free `repr`,
and the mapping remains read-only through its mapping interface. Existing
lookup semantics remain intact. The shared options dict is cleared at context
exit, so an already returned inner view observes an empty mapping; the
handoff is also marked closed and drops its credential-source reference.
`ProtectedSimNowConfigError` is now re-raised directly, preserving the fixed
`CONFIG_INDEX_INVALID` reason instead of remapping it to a generic phase.

The 13 recorded cases cover sealed synthetic resolution and close-time clearing,
redacted representations, no credentials after the artifact/profile gates
reject, index rejection before config I/O, rechecking a mutated seal, preserving
a consumer exception, registration-policy preservation, and passing both
addresses to the official-pair verifier. The tests use temporary synthetic
config and fake file-ACL leaves; they monkeypatch the installed-artifact gate,
import fence, and SDK profile selector. Thus they do not verify the installed
SDK artifacts or exercise the real SDK pair check. Root's separate installed
artifact checker remains the appropriate evidence for that gate.

The representation and close behavior are now covered. `_PrivateMapping` is
still an in-process handoff, not a hostile-code boundary: its backing values
are accessible to trusted Python code, and serialization is prohibited by the
helper's documented caller contract rather than an explicit serialization
guard. Any references or strings copied before close also remain outside the
shared mapping's clearing behavior.

This review covers only the public helper/test delta and recorded synthetic
test result. It does not read private runtime data or establish that the
integration caller retains the context through Store shutdown, performs
normal native cleanup, or completes any Store, provider, account, or formal
acceptance path.
