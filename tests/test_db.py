from __future__ import annotations

import time


class TestMessageDB:
    """Integration tests with in-memory SQLite."""

    def test_save_and_get_mapping(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        db.save_mapping("bridge1", "inst2", {"id": "ch2"}, "msg002")

        assert db.get_bridge_id("inst1", "msg001") == "bridge1"
        assert db.get_bridge_id("inst2", "msg002") == "bridge1"
        assert db.get_bridge_id("inst1", "nonexistent") is None

    def test_get_platform_msg_id(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        db.save_mapping("bridge1", "inst2", {"id": "ch2"}, "msg002")

        assert db.get_platform_msg_id("bridge1", "inst1", {"id": "ch1"}) == "msg001"
        assert db.get_platform_msg_id("bridge1", "inst2", {"id": "ch2"}) == "msg002"
        assert db.get_platform_msg_id("bridge1", "inst3", {"id": "ch3"}) is None

    def test_get_platform_msg_ids(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg002")

        ids = db.get_platform_msg_ids("bridge1", "inst1", {"id": "ch1"})
        # May return 1 or 2 depending on merge behavior with same primary key
        assert len(ids) >= 1

    def test_save_user_and_get_name(self, db):
        db.save_user("inst1", "user1", "Alice")
        assert db.get_user_name("inst1", "user1") == "Alice"
        assert db.get_user_name("inst1", "unknown") is None

    def test_get_user_id_by_name(self, db):
        db.save_user("inst1", "user1", "Alice")
        assert db.get_user_id_by_name("inst1", "Alice") == "user1"
        assert db.get_user_id_by_name("inst1", "Unknown") is None

    def test_get_user_id_by_name_case_insensitive(self, db):
        db.save_user("inst1", "user1", "Alice")
        assert db.get_user_id_by_name("inst1", "alice") == "user1"

    def test_get_mapped_user_id(self, db):
        db.save_user("inst1", "user1", "Alice")
        db.save_user("inst2", "user2", "Alice")
        assert db.get_mapped_user_id("inst1", "user1", "inst2") == "user2"
        assert db.get_mapped_user_id("inst1", "unknown", "inst2") is None

    def test_binding_code_lifecycle(self, db):
        db.create_binding_code("123456", "inst1", "user1", ttl=300)
        assert db.consume_binding_code("123456", "inst2", "user2") is True
        assert db.get_bound_user_id("inst1", "user1", "inst2") == "user2"
        # Consumed code should not work again
        assert db.consume_binding_code("123456", "inst3", "user3") is False

    def test_binding_code_expired(self, db):
        db.create_binding_code("999999", "inst1", "user1", ttl=-1)
        assert db.consume_binding_code("999999", "inst2", "user2") is False

    def test_remove_user_binding(self, db):
        db.create_binding_code("654321", "inst1", "user1", ttl=300)
        db.consume_binding_code("654321", "inst2", "user2")
        assert db.get_bound_user_id("inst1", "user1", "inst2") == "user2"
        db.remove_user_binding("inst1", "user1", "inst2")
        assert db.get_bound_user_id("inst1", "user1", "inst2") is None

    def test_get_all_bindings(self, db):
        db.create_binding_code("111111", "inst1", "user1", ttl=300)
        db.consume_binding_code("111111", "inst2", "user2")
        bindings = db.get_all_bindings("inst1", "user1")
        assert ("inst1", "user1") in bindings
        assert ("inst2", "user2") in bindings

    def test_list_binding_groups(self, db):
        db.create_binding_code("222222", "inst1", "user1", ttl=300)
        db.consume_binding_code("222222", "inst2", "user2")
        groups = db.list_binding_groups()
        assert len(groups) >= 1

    def test_delete_mapping_by_bridge_id(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        db.save_mapping("bridge1", "inst2", {"id": "ch2"}, "msg002")
        count = db.delete_mapping_by_bridge_id("bridge1")
        assert count == 2
        assert db.get_bridge_id("inst1", "msg001") is None

    def test_stats(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        db.save_user("inst1", "user1", "Alice")
        stats = db.stats()
        assert stats["message_mappings"] == 1
        assert stats["user_mappings"] == 1

    def test_recent_mappings(self, db):
        db.save_mapping("bridge1", "inst1", {"id": "ch1"}, "msg001")
        recent = db.recent_mappings(limit=10)
        assert len(recent) == 1
        assert recent[0]["bridge_id"] == "bridge1"

    def test_forward_page_lifecycle(self, db):
        now = int(time.time())
        db.save_forward_page("page1", "inst1", "<html/>", now, now + 3600)
        page = db.get_forward_page("page1")
        assert page is not None
        assert page["page_id"] == "page1"
        assert db.mark_forward_page_destroyed("page1") is True
        assert db.get_forward_page("page1")["destroyed_at"] is not None

    def test_mark_forward_page_destroyed_nonexistent(self, db):
        assert db.mark_forward_page_destroyed("nonexistent") is False

    def test_forward_asset_lifecycle(self, db):
        now = int(time.time())
        db.save_forward_asset(
            "asset1", "page1", "inst1", "image/png", b"data", now, now + 3600
        )
        asset = db.get_forward_asset("asset1")
        assert asset is not None
        assert asset["mime"] == "image/png"
        assert asset["data"] == b"data"

    def test_purge_expired_forward_assets(self, db):
        now = int(time.time())
        db.save_forward_asset(
            "asset1", "page1", "inst1", "text/plain", b"data", now, now - 10
        )
        db.save_forward_asset(
            "asset2", "page1", "inst1", "text/plain", b"data2", now, now + 3600
        )
        count = db.purge_expired_forward_assets(now)
        assert count == 1
        assert db.get_forward_asset("asset1") is None
        assert db.get_forward_asset("asset2") is not None

    def test_normalize_channel_id_handles_types(self, db):
        assert db._normalize_channel_id(None) == ""
        assert db._normalize_channel_id(123) == "123"
        assert db._normalize_channel_id("abc") == "abc"
        assert (
            db._normalize_channel_id({"id": 123, "type": "group"})
            == '{"id":"123","type":"group"}'
        )

    def test_normalize_channel_id_strips_transport_keys(self, db):
        result = db._normalize_channel_id(
            {"id": "ch1", "webhook_url": "https://hook", "msg": {"format": "text"}}
        )
        assert "webhook_url" not in result
        assert "msg" not in result
        assert "id" in result
