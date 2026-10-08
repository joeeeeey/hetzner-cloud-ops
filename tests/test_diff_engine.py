from __future__ import annotations

import unittest

from hetzner_cloud_ops.diff_engine import render_diff_markdown


class DiffEngineTests(unittest.TestCase):
    def test_first_sync(self) -> None:
        md = render_diff_markdown({}, {"resources": {"servers": []}})
        self.assertIn("First sync", md)

    def test_server_status_change(self) -> None:
        prev = {
            "resources": {
                "servers": [
                    {
                        "id": 1,
                        "name": "a",
                        "status": "running",
                        "public_net": {"ipv4": "1.1.1.1"},
                    }
                ]
            }
        }
        cur = {
            "resources": {
                "servers": [
                    {
                        "id": 1,
                        "name": "a",
                        "status": "off",
                        "public_net": {"ipv4": "1.1.1.1"},
                    }
                ]
            }
        }
        md = render_diff_markdown(prev, cur)
        self.assertIn("Servers", md)
        self.assertIn("status", md)


if __name__ == "__main__":
    unittest.main()
