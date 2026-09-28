# Cloudflare Roughtime assessment for future trusted-time admission

Status: `CANDIDATE_NOT_APPROVED / NO_READER_DEPLOYED`

Assessment date: 2026-09-24

Contract update: the fixed-front **read-only** SimNow route no longer requires
an injected UTC reader because the old comparison did not select an endpoint
or bound the read-only observation. The below analysis records why Cloudflare
Roughtime was not suitable for that retired one-second gate and what a future
write/absolute-expiry gate would need. It is not a blocker for the read-only
route; that route remains unregistered for separate config/artifact/account
reasons. No trusted-time reader was added.

## Decision

Cloudflare Roughtime is a technically relevant candidate, but the available
evidence does not justify adding a production clock reader or registering a
SimNow route. The official service page currently publishes
`roughtime.cloudflare.com:2003` over UDP and the Ed25519 root key
`0GD7c3yP8xEc4Zl2zeuN2SlLvDVVocjsPSL8/Rl/7zg=`. Cloudflare marks the service
beta and says that this root key may change. The page does not state a response
radius bound or availability commitment. Published documentation establishes
the intended endpoint and key, not successful reachability from a particular
deployment. No live UDP transaction was performed for this assessment.

Roughtime has properties a future trusted-time gate may need in principle: a fresh
nonce binds the signed response to a request; a response authenticates a time
midpoint and uncertainty radius; and a monotonic send/receive interval can
bound how old that sample may be when received. The retired read-only operator
contract accepted only a source ID and timestamp. It could not represent
the signature/version, nonce binding, uncertainty, or monotonic anchors, and
its skew comparison did not add uncertainty to the observed host offset.
Passing a midpoint through that contract would therefore have overstated the
strength of the check.

## Current official facts

- Cloudflare's [Get the Roughtime page](https://developers.cloudflare.com/time-services/roughtime/usage/),
  last updated 2026-04-24, specifies UDP `roughtime.cloudflare.com:2003` and
  the base64 Ed25519 root key above. It says the service is in beta and that
  the root key can change. Its [server deprecation page](https://developers.cloudflare.com/time-services/roughtime/deprecation/)
  lists the old `:2002` endpoint/key as deprecated on 2024-06-30; it does not
  list the current `:2003` endpoint as deprecated.
- Cloudflare's [Roughtime recipes](https://developers.cloudflare.com/time-services/roughtime/recipes/)
  describe the root-key delegation to an online key, the online response
  signature, Ed25519, and UDP. The signed response includes a time and a
  server-supplied uncertainty radius. The client uses a prior response to
  construct a chained nonce, and Cloudflare recommends multiple sources for
  synchronization and auditing. Its example filters source radii at 10
  seconds; that example is not a guarantee that this service returns a radius
  small enough for this route.
- Cloudflare's [client repository](https://github.com/cloudflare/roughtime)
  says its current code supports `draft-ietf-ntp-roughtime-11` and `-08`, that
  protocol compatibility is not guaranteed and its API is unstable, and
  explicitly says “DO NOT USE IN PRODUCTION SOFTWARE.” Its generated
  [ecosystem data](https://github.com/cloudflare/roughtime/blob/master/ecosystem.json.go)
  labels Cloudflare's endpoint `IETF-Roughtime` but does not identify a draft
  revision.
- The IETF [Roughtime document status](https://datatracker.ietf.org/doc/draft-ietf-ntp-roughtime/)
  currently identifies revision 19 as an Experimental Internet-Draft in the
  RFC Editor process. That is newer than the revisions the Cloudflare client
  repository says it supports. The service documentation does not resolve
  which wire revision `:2003` currently serves.

## Why the retired 1-second check was not proven

Let `M` be the verified signed midpoint, `R` its signed radius, and `T` the
monotonic elapsed time between sending the query and receiving its response.
At receipt, a conservative interval around the source time is at least
`[M - R, M + R + T]`: the server's signed time can refer to any point after
request transmission and before response receipt. Its center is
`M + T/2`, with uncertainty `R + T/2`. The full `R + T` can be used as a
simpler one-sided budget. If the evidence is consumed `A` monotonic seconds
after receipt, the interval center must advance by `A`; a separately reviewed
bound `E(A)` on monotonic-rate and measurement error must be added to its
uncertainty.

For host time `H` sampled at that comparison, the route should accept only
when the maximum possible offset is within its approved limit, for example
`abs(H - (M + T/2 + A)) + R + T/2 + E(A) <= max_clock_skew_seconds`.
The retired read-only policy maximum was at most 5 seconds and defaulted to 1 second.
The Cloudflare example's 10-second radius threshold cannot meet that bound;
an individual response might be tighter, but no source-side bound or measured
response is available here to establish that. The host wall clock may be
compared to the authenticated interval, but it must not be used to authenticate
the response, validate freshness, or bootstrap its key.

## Implementation and acceptance blockers

1. Resolve the served protocol revision with Cloudflare and select a client
   implementation that supports that exact revision and is suitable for
   production review. The current official client repository warns against
   production use and does not claim support for the current IETF revision.
2. Review the endpoint operator, service time discipline, key lifecycle and
   revocation process, privacy/network requirements, and an independently
   defensible source error budget. The currently published beta key is a
   usable pin candidate, not deployment approval.
3. Extend the clock evidence contract to retain authenticated source identity,
   protocol revision, verified time interval, uncertainty, nonce/freshness
   result, monotonic send/receive anchors, and bounded age. Reject when the
   total uncertainty plus measured host offset exceeds the existing bound.
4. Measure signed radius, round-trip time, and end-to-end uncertainty in the
   intended Windows deployment from its actual service account and network.
   Include source outage, malformed/replayed response, invalid signature,
   wall-clock steps in both directions, suspend/resume, monotonic reset, and
   key rotation. Every failure must occur before credential resolution and
   provider SDK import.
5. Keep the source fixed in reviewed code. A DNS answer, UDP success, or
   failure must never select another time source or change the configured CTP
   front pair. Keep the default registry unbound until review and deployment
   evidence pass.

No clock reader, operator contract change, registry entry, credential access,
or provider connection was made as part of this assessment. The existing
blocker remains in force: `DEFAULT_UNREGISTERED / REAL_PREFLIGHT_NOT_RUN`.
