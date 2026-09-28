# R1 superseded

R1 test migration patch SHA-256: 93BD64374B156CBDE9A2D2F62793A736EBBDF015C5BA01F6D0C55032F1DC31B1.

Independent R1 review found that the supplied-SDK configuration test replaced store.start() with _ensure_api_ready(), dropping Store lifecycle coverage. R2 supersedes R1 by restoring store.start()/stop() around a synchronous injected fake and asserting _started while preserving the configuration identity assertions. The R2 fake disables its async command methods, so the async worker/provider lifecycle remains outside this local test migration.
