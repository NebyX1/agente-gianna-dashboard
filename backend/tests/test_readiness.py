import time
from threading import Event

from app.services.readiness import ReadinessProbe


def test_blocked_probe_has_one_worker_and_recovers():
    entered, release = Event(), Event()
    calls = []

    def blocked():
        calls.append(1)
        entered.set()
        release.wait()
        return True

    probe = ReadinessProbe(blocked, timeout=0.03)
    try:
        assert probe.ready() is False
        assert entered.wait(1)
        started = time.monotonic()
        assert probe.ready() is False
        assert calls == [1]
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        assert probe._pending.result(timeout=1) is True
    probe.timeout = 1
    assert probe.ready() is True
    assert calls == [1, 1]


def test_readiness_dependency_error_is_uniform_and_recovers(app, monkeypatch):
    probe = app.extensions["readiness_probe"]
    client = app.test_client()

    def unavailable():
        raise ConnectionError("dependency unavailable")

    monkeypatch.setattr(probe, "check", unavailable)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "not_ready"
    assert response.json["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert "dependency unavailable" not in response.text
    monkeypatch.setattr(probe, "check", lambda: True)
    assert client.get("/readyz").status_code == 200
