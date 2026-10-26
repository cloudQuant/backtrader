# I51 protected SimNow handoff — static review, 2026-10-27

**Decision: GO for source-only handoff review (`SOURCE_HANDOFF_ONLY`).** I
read the uncommitted public helper, its directly used public `backtrader_runtime`
sources, and the named public SDK pin record. I did not read protected config,
`.env`, or `runtime-ctp-private`, and did not run or import the helper.

The helper relocates only the existing 013_3 runtime directory to the
code-relative `examples/unified/013_3_sa_midfreq_simnow/runtime-ctp-private`
location. `dataclasses.replace` reconstructs the registration, so its
directory identity is captured for the relocated path; the existing runtime
ID, strategy ID, profile, secrets route, binding, and `sandbox_write_policy`
remain code-owned. The profile retains `simulation/sandbox`, the
`config_yaml` route, no capabilities, and denied writes. The registered loader
reads a bounded config (1 MiB cap) through the registry-verified directory and
file identity/security path, then seals the parsed config before resolution.

The selected index rejects non-exact integers and values outside 0–7; the
sealed reader separately requires a nonempty configured candidate set of at
most eight pairs. The binding derives admission and credential scope from that
sealed config. The read-only runtime contract and matching-scope checks run
before local credential resolution. Within the strict installed-package import
context, the helper validates exact TCP front syntax and checks both
`bt_api_base` and `bt_api_ctp` against its fixed distribution version, installed
RECORD, package inventory/import root, and local-wheel provenance before
credential resolution. Its six wheel/RECORD values match the named public
`ctp-sdk-artifact-pins.json`. The official SDK profile selector and TD/MD pair
verifier are then called before credentials are resolved. No Store, SDK
client, provider session, or network probe is created by this helper.

The credential source revalidates its resolver seal on every credential read.
`_Handoff.__repr__` is redacted, `for_runner()` rechecks all five credential
bindings, and context exit marks the handoff inactive, clears its backing
options dictionary, and drops its source reference. Previously returned
mapping proxies share that dictionary and therefore observe the clear.

**Handling caveat:** `for_runner()` returns ordinary `MappingProxyType`
objects; their standard representation exposes the credential values. Only
the `_Handoff` representation is redacted. The helper docstring explicitly
prohibits logging, serialization, or subprocess transfer, but this is a
caller obligation rather than an enforced property of the returned mapping.
The minimal integration safeguard is to keep the mapping local, pass it
directly to the intended in-process Store setup, and never format/log it. If
automatic repr redaction is required, wrap the returned mapping with a small
repr-redacted in-process view before integration. As with any Python handoff,
references or copied strings retained by trusted in-process code cannot be
revoked by clearing the shared dictionary.

This is a static review of the standalone context/helper only. It does not
establish that a caller keeps the context open through Store shutdown, that
normal native cleanup succeeds, or any Store/provider/account behavior or
acceptance.
