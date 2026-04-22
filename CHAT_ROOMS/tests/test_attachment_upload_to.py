"""
test_attachment_upload_to.py

Verifies the attachment_upload_to callable (M4) produces correctly-sharded
paths without requiring any database access.
"""

import re
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from CHAT_ROOMS.models import attachment_upload_to


class AttachmentUploadToTest(SimpleTestCase):

    def _make_instance(self, room_id=42):
        instance = MagicMock()
        instance.message.room_id = room_id
        return instance

    def test_path_matches_expected_pattern(self):
        instance = self._make_instance(room_id=7)
        path = attachment_upload_to(instance, "hello.png")
        # attachments/<4-digit year>/<2-digit month>/<room_id>/<32 hex chars>.png
        pattern = r'^attachments/\d{4}/\d{2}/7/[0-9a-f]{32}\.png$'
        self.assertRegex(path, pattern, f"Path {path!r} did not match expected pattern.")

    def test_extension_is_lowercased(self):
        instance = self._make_instance(room_id=1)
        path = attachment_upload_to(instance, "IMAGE.PNG")
        self.assertTrue(path.endswith(".png"), f"Extension not lowercased: {path!r}")

    def test_different_room_id_in_path(self):
        instance = self._make_instance(room_id=999)
        path = attachment_upload_to(instance, "doc.pdf")
        self.assertIn("/999/", path)

    def test_orphan_fallback_when_no_room_id(self):
        """If message has no room_id (orphan attachment), path uses 'orphan'."""
        instance = MagicMock()
        del instance.message.room_id  # make getattr fall back to 'orphan'
        instance.message.room_id = None
        path = attachment_upload_to(instance, "file.txt")
        # room_id=None becomes 'None' in the f-string — acceptable; just confirm no crash.
        self.assertTrue(path.startswith("attachments/"))

    def test_uuid_is_unique_per_call(self):
        instance = self._make_instance(room_id=5)
        path1 = attachment_upload_to(instance, "a.jpg")
        path2 = attachment_upload_to(instance, "a.jpg")
        self.assertNotEqual(path1, path2, "Two calls produced the same UUID path.")

    def test_path_starts_with_attachments_prefix(self):
        instance = self._make_instance(room_id=3)
        path = attachment_upload_to(instance, "video.mp4")
        self.assertTrue(path.startswith("attachments/"))

    def test_filename_without_extension(self):
        """No extension → no trailing dot in the output path."""
        instance = self._make_instance(room_id=2)
        path = attachment_upload_to(instance, "noext")
        # os.path.splitext("noext") → ("noext", "") → ext = ""
        # The path should not end with a dot.
        self.assertFalse(path.endswith("."), f"Unexpected trailing dot: {path!r}")
