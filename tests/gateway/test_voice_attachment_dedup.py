import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class TestDurableVoiceDeduplicator(unittest.TestCase):
    def _make(self, db_path):
        from gateway.platforms.helpers import DurableVoiceDeduplicator

        return DurableVoiceDeduplicator(db_path=db_path)

    def test_first_call_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = self._make(Path(tmpdir) / "state.db")
            self.assertFalse(d.is_duplicate("msg1", "att1"))

    def test_second_call_is_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = self._make(Path(tmpdir) / "state.db")
            d.is_duplicate("msg1", "att1")
            self.assertTrue(d.is_duplicate("msg1", "att1"))

    def test_different_attachment_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = self._make(Path(tmpdir) / "state.db")
            d.is_duplicate("msg1", "att1")
            self.assertFalse(d.is_duplicate("msg1", "att2"))

    def test_different_message_id_same_att_id_both_admitted(self):
        """Same attachment_id under different message_ids are independent keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            d = self._make(Path(tmpdir) / "state.db")
            # First (msg1, att1) — not a duplicate
            self.assertFalse(d.is_duplicate("msg1", "att1"))
            # Second (msg2, att1) — different message_id, same attachment_id → NOT a duplicate
            self.assertFalse(d.is_duplicate("msg2", "att1"))

    def test_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            d1 = self._make(db_path)
            d1.is_duplicate("msg1", "att1")
            d2 = self._make(db_path)
            self.assertTrue(d2.is_duplicate("msg1", "att1"))

    def test_expired_entry_not_flagged_as_duplicate(self):
        """Entries older than TTL are pruned and treated as new."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "state.db"
            d = self._make(db_path)
            # Insert an entry with seen_at well before the TTL cutoff
            past_ts = time.time() - (d._TTL + 3600)  # 1 hour past TTL
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO discord_voice_dedup (key, seen_at) VALUES (?, ?)",
                    ("msg_old:att_old", past_ts),
                )
            # Now check — expired entry should NOT be a duplicate
            self.assertFalse(d.is_duplicate("msg_old", "att_old"))

    def test_db_unavailable_falls_back(self):
        with patch(
            "gateway.platforms.helpers.sqlite3.connect",
            side_effect=sqlite3.OperationalError("db unavailable"),
        ):
            d = self._make(Path("/tmp/ignored-state.db"))
            self.assertFalse(d.is_duplicate("msg1", "att1"))
            self.assertTrue(d.is_duplicate("msg1", "att1"))
