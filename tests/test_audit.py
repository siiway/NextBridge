from __future__ import annotations

import json

import services.audit as audit


class FakeBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def emit(self, event: str, **kwargs) -> None:
        self.calls.append((event, kwargs))


def teardown_function() -> None:
    audit.configure(None)


def test_configure_writes_structured_entry(tmp_path):
    bus = FakeBus()
    assert audit.configure(str(tmp_path), event_bus=bus) is True

    entry = audit.record(
        "rule.create",
        actor="admin",
        source_ip="127.0.0.1",
        target="rule-1",
        after={"type": "forward"},
    )

    log_file = tmp_path / "audit.log"
    lines = [ln for ln in log_file.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event"] == "rule.create"
    assert parsed["actor"] == "admin"
    assert parsed["target"] == "rule-1"
    assert parsed["result"] == "ok"
    assert entry["event"] == "rule.create"


def test_record_emits_event_bus():
    bus = FakeBus()
    audit.configure(None, event_bus=bus)
    audit.record("plugin.disable", target="stats")

    assert bus.calls
    event, payload = bus.calls[0]
    assert event == "audit.plugin.disable"
    assert payload["target"] == "stats"


def test_truncates_long_fields(tmp_path):
    audit.configure(str(tmp_path))
    entry = audit.record("config.update", after="x" * 600)

    assert entry["after"] is not None
    assert len(entry["after"]) == 503
    assert entry["after"].endswith("...")


def test_configure_without_dir_returns_false():
    assert audit.configure(None) is False
