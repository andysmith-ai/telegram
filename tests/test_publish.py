"""Behavioral tests for the Telegram publisher's sibling-state design.

Tests run against a temporary root directory so they never touch the real repo
state. Telegram API calls and git push are mocked; state files are real.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "publish"))

from publish import main, state_path, load_state


class PublishTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "posts"))

    def tearDown(self):
        self.tmp.cleanup()

    def _write_post(self, slug: str, body: str = "Hello") -> str:
        path = os.path.join(self.root, "posts", f"{slug}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"---\ntitle: \"{slug}\"\n---\n\n# {slug}\n\n{body}\n")
        return path

    def _write_state(self, slug: str, record: dict) -> str:
        path = state_path(slug, self.root)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_migrated_success_is_skipped(self):
        """A post already recorded as published is not sent again."""
        self._write_post("2026-09-15-fx-sh")
        self._write_state("2026-09-15-fx-sh",
                          {"message_id": 144, "url": "https://t.me/testchannel/144"})
        fake_tg = MagicMock()
        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)
            fake_tg.send_rich_message.assert_not_called()

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_claim_before_send(self):
        """The sending state file exists before the Telegram API is called."""
        self._write_post("2026-09-20-claim")
        fake_tg = MagicMock()
        captured = []

        def send_and_capture(*args, **kwargs):
            captured.append(load_state("2026-09-20-claim", self.root))
            return {"message_id": 42}

        fake_tg.send_rich_message.side_effect = send_and_capture

        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)

        self.assertEqual(captured, [{"status": "sending"}])
        state = load_state("2026-09-20-claim", self.root)
        self.assertEqual(state["message_id"], 42)
        self.assertEqual(state["url"], "https://t.me/testchannel/42")

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_failed_state_is_skipped(self):
        """A post in the failed state is never auto-retried."""
        self._write_post("2026-09-20-fail")
        self._write_state("2026-09-20-fail", {"status": "failed", "error": "boom"})
        fake_tg = MagicMock()
        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)
            fake_tg.send_rich_message.assert_not_called()

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_manual_reset_allows_retry(self):
        """Removing a failed state file lets the publisher retry that post."""
        self._write_post("2026-09-20-retry")
        self._write_state("2026-09-20-retry", {"status": "failed", "error": "boom"})
        fake_tg = MagicMock()
        fake_tg.send_rich_message.return_value = {"message_id": 99}

        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)
            self.assertEqual(fake_tg.send_rich_message.call_count, 0)

            os.remove(state_path("2026-09-20-retry", self.root))
            main(argv=["--no-push"], root=self.root)
            self.assertEqual(fake_tg.send_rich_message.call_count, 1)

        state = load_state("2026-09-20-retry", self.root)
        self.assertEqual(state["message_id"], 99)

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_multiple_posts_published_in_order(self):
        """Oldest-first publishing creates independent state files per post."""
        self._write_post("2026-09-18-a")
        self._write_post("2026-09-19-b")
        fake_tg = MagicMock()
        fake_tg.send_rich_message.side_effect = [
            {"message_id": 1},
            {"message_id": 2},
        ]
        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)

        calls = [c.args[1]["blocks"][0]["text"] for c in fake_tg.send_rich_message.call_args_list]
        self.assertEqual(calls, ["2026-09-18-a", "2026-09-19-b"])
        self.assertEqual(load_state("2026-09-18-a", self.root)["message_id"], 1)
        self.assertEqual(load_state("2026-09-19-b", self.root)["message_id"], 2)

    @patch.dict(os.environ, {"TG_USERNAME": "testchannel", "TELEGRAM_BOT_TOKEN": "token"})
    def test_migration_from_root_state(self):
        """A legacy root state.json is migrated to sibling files and removed."""
        self._write_post("2026-09-15-fx-sh")
        legacy = os.path.join(self.root, "state.json")
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump({
                "2026-09-15-fx-sh": {
                    "message_id": 144,
                    "url": "https://t.me/old/144",
                },
            }, f)

        fake_tg = MagicMock()
        with patch("publish.Telegram", return_value=fake_tg):
            main(argv=["--no-push"], root=self.root)
            fake_tg.send_rich_message.assert_not_called()

        self.assertFalse(os.path.exists(legacy))
        state = load_state("2026-09-15-fx-sh", self.root)
        self.assertEqual(state["message_id"], 144)
        self.assertEqual(state["url"], "https://t.me/old/144")


if __name__ == "__main__":
    unittest.main()
