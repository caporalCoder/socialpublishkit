"""Portable credentials and restart behavior; no network or live secrets."""

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from socialpublishkit.config import load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "gateway.json"
        self.state = self.root / "state"
        self.data = {
            "app_env": {"TIKTOK_CLIENT_SECRET": "TEST_APP_SECRET"},
            "accounts": [{"id": "test-tiktok", "platform": "tiktok",
                          "access_token_env": "TEST_ACCESS_TOKEN",
                          "refresh_token_env": "TEST_REFRESH_TOKEN",
                          "expires_at": 2000000000,
                          "scopes": ["video.upload"]}],
        }
        self.config.write_text(json.dumps(self.data))
        env = patch.dict(os.environ, {"TEST_ACCESS_TOKEN": "fake-source-access",
                                     "TEST_REFRESH_TOKEN": "fake-source-refresh",
                                     "TEST_APP_SECRET": "fake-app-secret"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_environment_references_and_private_rotation_survive_restart(self):
        publisher, accounts = load_config(self.config, self.state)
        account = accounts["test-tiktok"]
        self.assertEqual(account.access_token, "fake-source-access")
        self.assertEqual(publisher._config["TIKTOK_CLIENT_SECRET"], "fake-app-secret")
        publisher._persist_refresh(account, {"jeton": "fake-rotated-access",
            "renouvellement": "fake-rotated-refresh", "expire": 2100000000,
            "scope": "video.upload"})
        cache = self.state / "rotated-accounts.local.json"
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        _, restarted = load_config(self.config, self.state)
        self.assertEqual(restarted["test-tiktok"].access_token, "fake-rotated-access")
        self.assertEqual(restarted["test-tiktok"].refresh_token, "fake-rotated-refresh")
        self.assertEqual(restarted["test-tiktok"].expires_at, 2100000000)

    def test_new_source_token_invalidates_old_cache(self):
        publisher, accounts = load_config(self.config, self.state)
        publisher._persist_refresh(accounts["test-tiktok"], {
            "jeton": "fake-rotated", "renouvellement": "fake-rotated-refresh", "expire": 2100000000})
        os.environ["TEST_ACCESS_TOKEN"] = "fake-reconnected-token"
        _, restarted = load_config(self.config, self.state)
        self.assertEqual(restarted["test-tiktok"].access_token, "fake-reconnected-token")

    def test_missing_environment_is_rejected_without_value_leak(self):
        del os.environ["TEST_ACCESS_TOKEN"]
        with self.assertRaises(ValueError) as caught:
            load_config(self.config, self.state)
        self.assertNotIn("fake-app-secret", str(caught.exception))

    def test_plaintext_token_field_and_duplicate_ids_are_rejected(self):
        self.data["accounts"][0]["access_token"] = "fake-forbidden-token"
        self.config.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            load_config(self.config, self.state)
        del self.data["accounts"][0]["access_token"]
        self.data["accounts"].append(dict(self.data["accounts"][0]))
        self.config.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            load_config(self.config, self.state)


if __name__ == "__main__":
    unittest.main()
