from __future__ import annotations

import pytest

from services.metrics import MetricsCollector


class TestMetricsCollector:
    def test_inc_and_get(self):
        m = MetricsCollector()
        m.inc_message("discord", "inst1", "recv")
        m.inc_message("discord", "inst1", "recv")
        m.inc_message("discord", "inst1", "send")
        assert (
            m.get(
                "nextbridge_messages_total",
                platform="discord",
                instance_id="inst1",
                direction="recv",
            )
            == 2
        )
        assert (
            m.get(
                "nextbridge_messages_total",
                platform="discord",
                instance_id="inst1",
                direction="send",
            )
            == 1
        )

    def test_unknown_metric_raises(self):
        m = MetricsCollector()
        with pytest.raises(KeyError):
            m.inc("nope_total", a="b")

    def test_render_exposes_metrics(self):
        m = MetricsCollector()
        m.inc_rule_match("rule-1")
        m.inc_send_timeout("telegram")
        m.inc_driver_restart("qq", "qq1")
        text = m.render().decode()
        assert "nextbridge_rule_matches_total" in text
        assert 'rule_id="rule-1"' in text
        assert "nextbridge_send_timeouts_total" in text
        assert 'platform="telegram"' in text
        assert "nextbridge_driver_restarts_total" in text

    def test_snapshot_and_restore(self):
        m = MetricsCollector()
        m.inc_config_reload("config", "", "ok")
        m.inc_config_reload("config", "", "ok")
        m.inc_send_failure("discord", "TimeoutError")

        restored = MetricsCollector()
        restored.restore(m.snapshot())

        assert (
            restored.get(
                "nextbridge_config_reloads_total", kind="config", target="", result="ok"
            )
            == 2
        )
        assert (
            restored.get(
                "nextbridge_send_failures_total",
                platform="discord",
                reason="TimeoutError",
            )
            == 1
        )

    def test_restore_then_increment_accumulates(self):
        m = MetricsCollector()
        m.inc_message("a", "b", "recv")
        restored = MetricsCollector()
        restored.restore(m.snapshot())
        restored.inc_message("a", "b", "recv")
        assert (
            restored.get(
                "nextbridge_messages_total",
                platform="a",
                instance_id="b",
                direction="recv",
            )
            == 2
        )


class TestMetricsPersistence:
    def test_db_roundtrip(self, db):
        m = MetricsCollector()
        m.inc_message("discord", "i1", "recv")
        m.inc_rule_match("r1")
        db.save_metrics_counters(m.snapshot())

        restored = MetricsCollector()
        restored.restore(db.load_metrics_counters())

        assert (
            restored.get(
                "nextbridge_messages_total",
                platform="discord",
                instance_id="i1",
                direction="recv",
            )
            == 1
        )
        assert restored.get("nextbridge_rule_matches_total", rule_id="r1") == 1

    def test_db_upsert_overwrites(self, db):
        m = MetricsCollector()
        m.inc_message("discord", "i1", "recv")
        db.save_metrics_counters(m.snapshot())
        m.inc_message("discord", "i1", "recv")
        db.save_metrics_counters(m.snapshot())
        rows = db.load_metrics_counters()
        assert len(rows) == 1
        assert rows[0]["value"] == 2
