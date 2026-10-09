import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor


class TestCloud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [
            patch.object(monitor, 'PRIVATE', Path(self.tmp.name)),
            patch.object(monitor, 'PAUSE_FILE', Path(self.tmp.name) / 'paused.json'),
            patch.object(monitor, 'HEALTH_FILE', Path(self.tmp.name) / 'health.json'),
            patch.object(monitor, 'STATE_FILE', Path(self.tmp.name) / 'state.json'),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.config = monitor.Config('chat', 'token', 'scope', 'ready', 'slot', 'category', 600)

    def test_action_required_pauses_without_repeating_site_checks(self):
        notices = []
        calls = []
        def blocked(*args, **kwargs):
            calls.append(1)
            raise monitor.ActionRequired('CAPTCHA: manual login needed')
        with patch.object(monitor, 'cmd_preflight'), patch.object(monitor, 'check_once', blocked), \
             patch.object(monitor, 'notify', lambda cfg, msg: notices.append(msg)):
            monitor.cmd_cloud_once(self.config)
            monitor.cmd_cloud_once(self.config)
        self.assertTrue(monitor.PAUSE_FILE.exists())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(notices), 1)
        monitor.cmd_resume()
        self.assertFalse(monitor.PAUSE_FILE.exists())

    def test_network_failure_alert_dedup_and_eventual_recovery(self):
        notices = []
        def failure(*args, **kwargs):
            raise ConnectionError('Network unavailable')
        with patch.object(monitor, 'cmd_preflight'), patch.object(monitor, 'check_once', failure), \
             patch.object(monitor, 'notify', lambda cfg, msg: notices.append(msg)):
            monitor.cmd_cloud_once(self.config)
            monitor.cmd_cloud_once(self.config)
        self.assertEqual(len(notices), 1)
        self.assertEqual(monitor.read_json(monitor.HEALTH_FILE)['status'], 'error')
        with patch.object(monitor, 'cmd_preflight'), patch.object(monitor, 'check_once'), \
             patch.object(monitor, 'notify', lambda cfg, msg: notices.append(msg)):
            monitor.cmd_cloud_once(self.config)
        self.assertEqual(len(notices), 2)
        self.assertEqual(monitor.read_json(monitor.HEALTH_FILE)['status'], 'ok')

    def test_preflight_requires_auth_state(self):
        with patch.object(monitor, 'AUTH_STATE_FILE', Path(self.tmp.name) / 'doesnotexist'):
            with self.assertRaises(monitor.ActionRequired):
                monitor.cmd_preflight(self.config)


if __name__ == '__main__':
    unittest.main()
