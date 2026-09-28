# Historical isolated r3 replay boundary

No write authorization or writer-closure claim.

- Exact historical source preimage: A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D.
- Candidate source target: 00D31700B8554E954C52A748E2DBA09CB781DAED403EEC82AA750D1844513F55.
- Patch: [patch.diff](patch.diff); candidate fake contract: [test file](tests/test_ctp_generic_sdk_queue_failclose.py); identity and static scope: [candidate manifest](candidate-manifest.json).
- The original exact replay used frozen baseline and candidate trees under D:\temp\ac41-63-store-generic-ctp-queue-failclose-r3-trust-boundary-20260927. Those full Store source trees are not duplicated in this evidence archive. Replaying requires that historical A028 input; do not substitute the current main checkout, which changed after r3 with the later r4 integration.
- The recorded rejection run is available locally as the [broad pytest log](qa/main-broad/pytest.log), [JUnit](qa/main-broad/junit.xml), and [exit sidecar](qa/main-broad/exit.txt). The narrow independent fake-only review is [here](qa/independent-qa-report.md).

The isolated candidate covered direct CTP, gateway CTP (including CTP___suffix), forwarding CTP, and configured btapi CTP; unknown btapi route was fail-closed. The classifier itself does not dereference _api during dispatch, but constructor snapshots may originate from injected api.exchange_kwargs and are not trusted authority. Its sink guard covers only the generic _invoke_sdk_command fallback, not managed typed _execute_sdk_command branches. See the independent report for its conditional stale-snapshot residual. No SDK/native/provider/network/credential path was invoked by this archival task.
