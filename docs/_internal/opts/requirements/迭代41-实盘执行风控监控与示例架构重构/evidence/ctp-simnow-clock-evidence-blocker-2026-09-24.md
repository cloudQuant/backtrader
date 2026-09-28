# CTP SimNow read-only clock-gate review

Status: `READONLY_CLOCK_GATE_REMOVED / WRITE_TIME_POLICY_SEPARATE / DEFAULT_UNREGISTERED`

Date: 2026-09-24

## Decision

The fixed-endpoint CTP SimNow `simulation/sandbox` read-only route no longer
requires an injected UTC reader or host-clock skew comparison. The sealed
private config supplies one explicit `td_front`/`md_front` pair. Runtime
policy accepts only an exact code-owned pair; no time, calendar, reachability,
or fallback logic selects another endpoint. The previous UTC comparison did
not affect the selected route and its returned timestamp was not consumed by
the read-only composition.

This change removes only that read-only prerequisite. Exact front and query
scope validation, sealed runtime and registry checks, credential-source
protections, installed SDK provenance checks, seven allowlisted TD reads,
configured MD login/subscription, bounded session duration, identity binding,
client closure, and zero-write policy remain required. Session duration
continues to be bounded by the local monotonic deadline as well as its wall
deadline. This does not enable a default route: the default registry still has
no CTP SimNow private-read binding, the code-owned SDK artifact pin catalog is
empty, and no real account/session has been verified.

## Write-specific time policy

This route and the credential-binding tags grant no execution or write
authority. The reviewed credential-binding payload moved to schema/domain v3
when clock fields were removed; it continues to bind the sealed runtime,
account, exact configured fronts, query scope, and session TTL. Its result is
non-authorizing.

Any future writer must have a separate reviewed execution admission. If its
approval, replay protection, or session policy relies on absolute timestamps,
that admission must consume independently reviewed trusted-time evidence and
enforce expiry at the relevant decision boundaries. The removed read-only
host-skew comparison is not a substitute for that policy.

## Evidence

- `ctp_simnow_operator.py` now validates the explicit front pair and builds
  the read-only admission without a clock source.
- `ctp_artifact_provenance.py::simnow_profile_for_fronts` accepts only exact
  code-owned pairs and derives SDK metadata; the configured strings remain the
  endpoint values.
- `ctp_sandbox_readonly_admission.py` bounds the session using wall and
  monotonic deadlines. The monotonic deadline is the local duration bound.
- Focused route tests verify preflight dispatch without a time source, exact
  configured front preservation, rejection of custom/mixed pairs before
  composition or credential resolution, and zero-write output. Credential
  binding tests retain exact account/front/config revalidation and verify that
  invalid or changed route state fails before key material is read.

Focused command run on 2026-09-24:

```text
python -m pytest -p no:asyncio tests/unit/runtime/test_ctp_simnow_config_operator_route.py tests/unit/runtime/test_ctp_credential_binding.py tests/unit/runtime/test_ctp_simnow_readonly_runtime.py tests/unit/runtime/test_ctp_sdk_readonly.py -q --tb=short
94 passed, 1 warning in 5.18s
```

The warning is the environment's unrecognized
`asyncio_default_fixture_loop_scope` pytest option.

These are source and fake-provider contract checks. They do not establish a
real SimNow account, a reviewed SDK release, a live provider session, or a
future write authorization.
