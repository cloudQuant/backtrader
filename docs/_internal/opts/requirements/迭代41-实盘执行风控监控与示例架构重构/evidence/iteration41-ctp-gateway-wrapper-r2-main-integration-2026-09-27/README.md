# CTP Gateway wrapper R2 main integration evidence

Disposition: `LOCAL_DEFAULT_DENY_WRAPPER_GUARD_ONLY / NO_WRITE / LIVE_NO_GO`.

Candidate R2 is rebased on Store R5: Store SHA-256 `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`; candidate report SHA-256 `A205F85DBFF119F32FFD8F01F477B9F26CE2708BEBEA0D67C6BC9582F1499183`; manifest SHA-256 `7DE39D43443B35C2A5346E1560AC681640FB9927C9A325052332F3BB2637F230`; patch SHA-256 `DCD748DBF2D1041F5B524278F32E2CE696BDC9080980BB3430415D6F1BFF1451`. Independent receipt SHA-256 `FC4607FEBE29094BCC402FC7ED101DBF20BE671227076BA88BC67CDC9C64DFAB` reports exact replay match and six focused tests passing; the four named non-CTP allowlist probes passed using fakes.

The guard denies CTP and uncertain/unknown gateway wrapper construction before fake SDK import/client creation, preserves the Store CTP-session marker over exchange labels, and permits only the reviewed exact non-CTP names through this wrapper. The guard is on public wrapper methods only.

Limits: raw `wrapper._client`, direct GatewayClient construction, custom Store API injection, mutable same-process state, and CTP read/connect paths are outside the guard. Tests use AST-extracted code and fakes only. It is not account-level authorization, writer closure, or SimNow/production acceptance; CTP writes and live remain closed.
