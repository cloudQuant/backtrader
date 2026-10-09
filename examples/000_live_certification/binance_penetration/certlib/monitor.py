"""Minimal local certification monitor: event recording + threshold alerts.

This is the suite's own monitoring layer (the certification runner is the
operator).  It records session events with monotonic timestamps, snapshots
its effective configuration, and emits exactly-once alert records when
configured thresholds are crossed:

- ``submit_threshold``: one alert when submit count reaches the value
- ``combined_threshold``: one alert when submit + cancel count reaches it
- ``repeated_threshold`` with ``window_seconds``: one alert when that many
  submits happen inside the window
"""

from __future__ import annotations

import hashlib
import json
import time

_SCALARS = (str, int, float, bool, type(None))


class Monitor:
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.events = []
        self.alerts = []
        self._fired = set()
        self.started = time.monotonic()
        self.config_snapshot_id = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    # ------------------------------------------------------------- recording
    def record(self, kind, **fields):
        entry = {"t": round(time.monotonic() - self.started, 4), "kind": str(kind)}
        entry.update({k: v for k, v in fields.items() if isinstance(v, _SCALARS)})
        self.events.append(entry)
        self._evaluate(entry)
        return entry

    def submits(self):
        return [e for e in self.events if e["kind"] == "order_insert"]

    def cancels(self):
        return [e for e in self.events if e["kind"] == "order_action"]

    def _emit(self, alert_kind, **fields):
        if alert_kind in self._fired:
            return
        self._fired.add(alert_kind)
        alert = {"t": round(time.monotonic() - self.started, 4), "alert": alert_kind}
        alert.update(fields)
        self.alerts.append(alert)

    def _evaluate(self, entry):
        submit_threshold = self.config.get("submit_threshold")
        if submit_threshold and len(self.submits()) >= int(submit_threshold):
            self._emit("submit_threshold", count=len(self.submits()))
        combined_threshold = self.config.get("combined_threshold")
        if combined_threshold and len(self.submits()) + len(self.cancels()) >= int(combined_threshold):
            self._emit("combined_threshold", count=len(self.submits()) + len(self.cancels()))
        repeated_threshold = self.config.get("repeated_threshold")
        window_seconds = float(self.config.get("window_seconds", 60))
        if repeated_threshold:
            recent = [e for e in self.submits() if entry["t"] - e["t"] <= window_seconds]
            if len(recent) >= int(repeated_threshold):
                self._emit("repeated_threshold", count=len(recent), window_seconds=window_seconds)

    # -------------------------------------------------------------- evidence
    def snapshot_config(self):
        return {"config": dict(self.config), "config_snapshot_id": self.config_snapshot_id}

    def dump(self):
        return {
            "config": dict(self.config),
            "config_snapshot_id": self.config_snapshot_id,
            "events": list(self.events),
            "alerts": list(self.alerts),
        }
