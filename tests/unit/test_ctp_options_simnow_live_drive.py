from types import SimpleNamespace


from examples.ctp_options_simnow_live_drive import drive_simnow_mechanical_session


class FakeBroker:
    def __init__(self, notifications=()):
        self.notifications = list(notifications)

    def next(self):
        return None

    def get_notification(self):
        return self.notifications.pop(0) if self.notifications else None


class FakeSession:
    def __init__(self, broker, *, native=True, final_pass=True):
        self.broker = broker
        self.native = native
        self.final_pass = final_pass
        self.phase = "OPEN"
        self.pending = True
        self.journal = []
        self.cancel_calls = 0
        self.timeout_calls = 0
        self.exit_plans = 0
        self.exit_submissions = 0

    def _status(self):
        return {
            "status": self.phase,
            "phase": self.phase,
            "pending": self.pending,
            "journal": list(self.journal),
        }

    def on_order_update(self, order):
        if not self.native or getattr(order, "partial", False):
            raise RuntimeError("native fill not proven")
        self.journal.append({"status": "NATIVE_FILL_CONFIRMED", "bt_ref_hash": "a" * 64})
        fills = len([row for row in self.journal if row["status"] == "NATIVE_FILL_CONFIRMED"])
        if self.phase == "OPEN":
            self.pending = fills < 3
        else:
            self.pending = fills < 6
        return self._status()

    def plan_exit(self, prices, *, intent_id, reference_snapshot):
        assert prices == {"F": 1, "C": 2, "P": 3}
        assert reference_snapshot == {"quote": "fresh"}
        self.exit_plans += 1
        self.phase = "CLOSE"
        self.pending = False

    def submit_next_exit(self):
        self.exit_submissions += 1
        self.pending = True
        start = len(self.journal)
        self.broker.notifications.extend(
            [SimpleNamespace(ref=100 + start + index) for index in range(3)]
        )

    def cancel_pending(self):
        self.cancel_calls += 1
        self.pending = False

    def timeout(self):
        self.timeout_calls += 1
        raise RuntimeError("timeout")

    def finalize_flat(self, first, second):
        assert first == second
        if self.final_pass:
            return {"status": "MECHANICAL_PASS", "phase": "CLOSE", "journal": self.journal}
        return {"status": "RECOVERY_REQUIRED", "phase": "CLOSE", "journal": self.journal}


def _drive(session, broker, **kwargs):
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleep(seconds):
        clock[0] += seconds

    return drive_simnow_mechanical_session(
        broker=broker,
        session=session,
        fresh_exit_prices=lambda: ({"F": 1, "C": 2, "P": 3}, {"quote": "fresh"}),
        reconciliation_snapshot=lambda: {"flat": True},
        monotonic=monotonic,
        sleep=sleep,
        leg_timeout=kwargs.pop("leg_timeout", 0.1),
        **kwargs,
    )


def _entry_notifications(*, duplicate=False, partial=False):
    values = [SimpleNamespace(ref=index, partial=partial) for index in range(1, 4)]
    return values + ([values[-1]] if duplicate else [])


def test_complete_three_leg_drive_requires_native_fills_and_final_two_rounds():
    broker = FakeBroker(_entry_notifications(duplicate=True))
    session = FakeSession(broker)

    result = _drive(session, broker)

    assert result["status"] == "MECHANICAL_PASS"
    assert result["native_fill_count"] == 6
    assert result["duplicate_notification_count"] == 1
    assert session.exit_plans == 1
    assert session.exit_submissions == 1
    assert result["cancel_request_count"] == 0
    assert "ORDER-1" not in repr(result)
    assert "1.0" not in repr(result)


def test_partial_or_non_native_entry_never_plans_exit():
    broker = FakeBroker(_entry_notifications(partial=True))
    session = FakeSession(broker)

    result = _drive(session, broker)

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["reason"] == "RuntimeError"
    assert session.exit_plans == 0


def test_deadline_cancels_once_and_never_reopens():
    broker = FakeBroker()
    session = FakeSession(broker)

    result = _drive(session, broker, leg_timeout=0.1)

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["reason"] == "LEG_TIMEOUT_RECOVERY_REQUIRED"
    assert session.cancel_calls == 1
    assert session.timeout_calls == 1
    assert session.exit_plans == 0


def test_failed_final_reconciliation_is_not_pass():
    broker = FakeBroker(_entry_notifications())
    session = FakeSession(broker, final_pass=False)

    result = _drive(session, broker)

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["reason"] == "FINAL_RECONCILIATION_NOT_PASS"


def test_invalid_public_surface_fails_closed_without_side_effects():
    result = drive_simnow_mechanical_session(
        broker=object(),
        session=object(),
        fresh_exit_prices=dict,
        reconciliation_snapshot=dict,
    )

    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["cancel_request_count"] == 0
