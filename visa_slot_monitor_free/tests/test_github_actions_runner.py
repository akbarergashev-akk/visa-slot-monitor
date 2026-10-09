import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import github_actions_runner as runner
import monitor


class TestGitHubActionsRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.patches = [
            patch.object(monitor, 'PRIVATE', d),
            patch.object(monitor, 'STATE_FILE', d / 'state.json'),
            patch.object(monitor, 'PAUSE_FILE', d / 'pause.json'),
            patch.object(monitor, 'HEALTH_FILE', d / 'health.json'),
            patch.object(monitor, 'AUTH_STATE_FILE', d / 'auth_state.json'),
            patch.object(runner, 'CHECKPOINT_FILE', d / 'monitor_checkpoint.json'),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_secret_is_never_in_checkpoint(self):
        secret = {'cookies': [{'name': 'x', 'value': 'TOP_SECRET_COOKIE'}], 'origins': []}
        encoded = base64.b64encode(json.dumps(secret).encode()).decode()
        with patch.dict(os.environ, {'AUTH_STATE_B64': encoded}):
            runner.restore_auth_from_secret()
        self.assertEqual(monitor.AUTH_STATE_FILE.read_text(), json.dumps(secret))
        monitor.write_json(monitor.STATE_FILE, {'slot_ids': ['fingerprint'], 'checked_at': 'private'})
        monitor.write_json(monitor.HEALTH_FILE, {'status': 'ok', 'last_success': 'private'})
        obj = runner.make_checkpoint()
        output = json.dumps(obj)
        self.assertEqual(obj['slot_ids'], ['fingerprint'])
        self.assertNotIn('TOP_SECRET_COOKIE', output)
        self.assertNotIn('checked_at', output)
        self.assertNotIn('last_success', output)

    def test_paused_state_skips_network_and_reset_clears(self):
        runner.restore_checkpoint({'slot_ids': ['abc'], 'paused': True})
        self.assertTrue(monitor.PAUSE_FILE.exists())
        with patch.object(runner, 'read_checkpoint', return_value={'slot_ids': ['abc'], 'paused': True}), \
             patch.object(runner, 'restore_auth_from_secret') as auth, \
             patch.object(monitor, 'cmd_cloud_once') as cloud, \
             patch.dict(os.environ, {'RESET_PAUSE': 'false'}):
            runner.main()
        cloud.assert_not_called()
        auth.assert_not_called()
        with patch.object(runner, 'read_checkpoint', return_value={'slot_ids': ['abc'], 'paused': True}), \
             patch.object(runner, 'restore_auth_from_secret'), \
             patch.object(monitor, 'cmd_cloud_once') as cloud, \
             patch.dict(os.environ, {'RESET_PAUSE': 'true'}):
            runner.main()
        self.assertFalse(monitor.PAUSE_FILE.exists())
        self.assertEqual(cloud.call_count, 1)

    def test_bad_auth_never_in_logs(self):
        with patch.dict(os.environ, {'AUTH_STATE_B64': 'not!base64'}):
            with self.assertRaises(monitor.ActionRequired) as cm:
                runner.restore_auth_from_secret()
        self.assertNotIn('not!base64', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
