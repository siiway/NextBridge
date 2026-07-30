from services.message import Attachment, NormalizedMessage


class TestNormalizedMessage:
    def test_default_values(self):
        msg = NormalizedMessage()
        assert msg.platform == ""
        assert msg.instance_id == ""
        assert msg.channel == {}
        assert msg.text == ""
        assert msg.attachments == []

    def test_user_property(self):
        msg = NormalizedMessage(nickname="TestUser")
        assert msg.user == "TestUser"

    def test_str_with_all_fields(self):
        msg = NormalizedMessage(
            platform="discord",
            instance_id="discord_main",
            channel={"id": "123"},
            nickname="Alice",
            user_id="user1",
            text="Hello",
            message_id="msg1",
            reply_parent="parent1",
            time="12:00",
            source_proxy="http://proxy",
        )
        s = str(msg)
        assert "platform: 'discord'" in s
        assert "instance_id: 'discord_main'" in s
        assert "text: 'Hello'" in s

    def test_str_with_attachments(self):
        msg = NormalizedMessage(
            attachments=[
                Attachment(
                    type="image", url="https://example.com/img.png", name="photo.png"
                )
            ]
        )
        s = str(msg)
        assert "photo.png" in s


class TestAttachment:
    def test_default_values(self):
        a = Attachment(type="image", url="https://example.com/img.png")
        assert a.name == ""
        assert a.size == -1
        assert a.data is None

    def test_full_attachment(self):
        a = Attachment(
            type="file",
            url="https://example.com/doc.pdf",
            name="doc.pdf",
            size=1024,
            data=b"content",
        )
        assert a.name == "doc.pdf"
        assert a.size == 1024
        assert a.data == b"content"
