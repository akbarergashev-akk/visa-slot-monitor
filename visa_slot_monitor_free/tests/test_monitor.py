import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor


class TestSafety(unittest.TestCase):
    def test_domain_lock(self):
        self.assertEqual(monitor.safe_site_url(monitor.DEFAULT_URL), monitor.DEFAULT_URL)
        for url in ['https://evil.example/reservations/calendar',
                    'http://uzembassyryouji.rsvsys.jp/reservations/calendar',
                    'https://uzembassyryouji.rsvsys.jp.evil.example/reservations/calendar',
                    'https://uzembassyryouji.rsvsys.jp/auth/login']:
            with self.assertRaises(ValueError):
                monitor.safe_site_url(url)

    def test_identity_stable(self):
        x = {'date': '2026-10-20', 'label': '受付中 10:00', 'context': 'Short Stay'}
        self.assertEqual(monitor.identity(x), monitor.identity(dict(x)))
        self.assertNotEqual(monitor.identity(x), monitor.identity({**x, 'date': '2026-10-21'}))

    def test_requires_calibration(self):
        cfg = monitor.Config('', '', '', '', '', '', 600)
        with self.assertRaises(monitor.ActionRequired):
            monitor.require_calibration(cfg)

    def test_alert_deduplication_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = monitor.STATE_FILE
            original_notify = monitor.notify
            monitor.STATE_FILE = Path(tmp) / 'state.json'
            messages = []
            monitor.notify = lambda cfg, msg: messages.append(msg)
            cfg = monitor.Config('chat', 'token', 'x', 'r', 's', 'c', 600)
            slot = {'date': '2026-10-20', 'label': '受付中', 'context': ''}
            try:
                self.assertEqual(monitor.record_and_alert(cfg, [slot]), 1)
                self.assertEqual(monitor.record_and_alert(cfg, [slot]), 0)
                self.assertEqual(monitor.record_and_alert(cfg, []), 0)
                self.assertEqual(monitor.record_and_alert(cfg, [slot]), 1)
                self.assertEqual(len(messages), 2)
            finally:
                monitor.STATE_FILE = original
                monitor.notify = original_notify


if __name__ == '__main__':
    unittest.main()
