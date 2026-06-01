from examples import ctp_example_support as support


class _FakeStore:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.started = False
        self.stopped = False
        self.start_calls = 0
        self.stop_calls = 0
        _FakeStore.instances.append(self)

    def start(self):
        self.start_calls += 1
        self.started = True

    def stop(self):
        self.stop_calls += 1
        self.stopped = True


def _patch_store_construction(monkeypatch):
    def _build_store(**kwargs):
        return _FakeStore(**kwargs)

    monkeypatch.setattr(support, "BtApiStore", _build_store)


def _patch_connection(monkeypatch):
    def _connection(env_key):
        return {
            "td_address": f"td://{env_key}",
            "md_address": f"md://{env_key}",
            "broker_id": "9999",
            "investor_id": "investor",
            "password": "password",
            "app_id": "app",
            "auth_code": "auth",
            "simnow_env": env_key,
            "simnow_name": env_key,
        }

    monkeypatch.setattr(support, "create_simnow_connection", _connection)


def test_create_live_store_returns_unstarted_store_for_first_candidate(monkeypatch):
    _FakeStore.instances = []
    _patch_store_construction(monkeypatch)
    _patch_connection(monkeypatch)
    monkeypatch.setattr(support, "iter_simnow_env_candidates", lambda *args, **kwargs: ("env_a",))

    store, connection = support.create_live_store({"simnow_env": "auto"})

    assert len(_FakeStore.instances) == 1
    assert store is _FakeStore.instances[0]
    assert store.started is False
    assert store.stop_calls == 0
    assert store.start_calls == 0
    assert connection["simnow_env"] == "env_a"
    assert connection["attempted_simnow_envs"] == ("env_a",)


def test_create_live_store_prefers_first_candidate_without_eager_probe(monkeypatch):
    _FakeStore.instances = []
    _patch_store_construction(monkeypatch)
    _patch_connection(monkeypatch)
    monkeypatch.setattr(
        support,
        "iter_simnow_env_candidates",
        lambda *args, **kwargs: ("env_a", "env_b"),
    )

    store, connection = support.create_live_store({"simnow_env": "auto"})

    assert len(_FakeStore.instances) == 1
    assert store is _FakeStore.instances[0]
    assert store.start_calls == 0
    assert store.stop_calls == 0
    assert connection["simnow_env"] == "env_a"
    assert connection["attempted_simnow_envs"] == ("env_a", "env_b")
