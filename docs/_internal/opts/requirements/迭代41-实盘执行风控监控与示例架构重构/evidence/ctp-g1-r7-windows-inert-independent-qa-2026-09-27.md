# Independent G1 R7 QA

Date: 2026-09-27
Disposition: REJECTED / G1 CLOSED; inert Windows prototype only.

## Freeze and provenance

The archived original is ctp-g1-r7-windows-inert-custodian-rejection-2026-09-27.raw.zip, SHA-256 7a642ce3af9bf92bca4af21d75f1d8a423d339b626e2867eafba7a76e21555ee. Its extracted r7_manifest.json SHA-256 is afdc99be96a1ad4961235e358f9069070a5bafe2d051db9f59e2ff94fc8f9d7d; all 14 manifest payloads match their frozen size and SHA-256 (0 mismatches). See independent-freeze-audit.json.

The author live directory had been changed after freeze. Against the frozen manifest, g1_win_lazy_probe.cpp changed from 31,043 bytes / b97d5997d5b563eea6ad24ec3df89db12c7095d1a05226271f020cfa1415f66b to 32,886 bytes / a3720c9d33b0520de7fa471183ac32b39557022aaabb8ce692829e72a14d013e; run_r7_scenarios.py changed from 6,516 bytes / 2c896d635ad2713ce4150662f67da86042aec2625c9106dda4913fa5fbff5317 to 6,679 bytes / d0ffe7a448e6adedafd4257fc691ff64828309746e05a3b728ad9b3335e7d2e1. The re-run used only the original ZIP-extracted copy.

## Independent replay

Ran the frozen run_r7_scenarios.py in this fresh extraction on Windows, using the frozen executable and original nine-mode runner (not rebuilding). All 9 scenarios returned without the six-second outer watchdog firing. scenario-summary.json and independent-run.stdout.log preserve the replay. Normal request succeeded with worker exit 0, observed Job empty, and controls released after proof. Each request-time worker stall (create_process, pipe, token, receipt, join, descendant_join) reached DEADLINE_EXCEEDED; descendant_join observed 3 Job members before termination and 0 after, with exit+empty observed before release.

### Blocking admission negatives

- admission-sync: actual synchronous WriteFile to the full connected/no-reader pipe remained blocked at the 1,800 ms request deadline. The harness killed the separate caller Job; result was UNKNOWN, caller exit 3774873602, observed elapsed 1,813 ms, worker still active (1), and worker controls remained retained. This does not show a bounded synchronous admission call or normal caller return. Source: g1_win_lazy_probe.cpp:301-306, 487-497.
- admission-overlapped: the caller returned UNKNOWN/exit 54 with overlapped_pending=1 cancel_completed=0; no persistent reaper/context owned the incomplete I/O. Worker remained active, no exact exit+Job-empty proof existed, and worker controls remained retained. Source: g1_win_lazy_probe.cpp:309-324, 487-504.
- Warm-up and pipe connection are before the request timer; there is no request-before-ready scenario. The custodian and deadline observer are the same process. The outer Python watchdog owns no duplicated Job handles. Several synchronous Win32 setup/cleanup calls are not forced to hang inside the call. Source/limitations: run_r7_scenarios.py:51-57.
- The JSON snapshot is emitted before test teardown (g1_win_lazy_probe.cpp:597-624). The later test-only teardown sends shutdown, may terminate, then closes handles (626-647) without recording an after-cleanup exit+empty proof. It cannot upgrade the UNKNOWN result.

## Conclusion

R7 is useful real-Windows inert diagnostic evidence for Job assignment/termination and for two admission failure modes. The sync pipe case misses the 1,800 ms caller bound and requires forced caller termination. The overlapped case leaves cancellation incomplete with no retained I/O owner/reaper. These are fail-closed rejection reasons; they do not demonstrate a production custodian. No CTP, credentials, provider, private configuration, SCM installation, or default preflight was used. This is not G1 acceptance.
