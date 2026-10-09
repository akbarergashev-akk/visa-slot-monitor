"""One GitHub Actions run; GitHub repository holds only non-secret checkpoint data.

Never commit .env, .private/*, browser cookies, Telegram tokens or a session backup.
This is not a booking bot. A single run does not solve login/CAPTCHA challenges.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import monitor

CHECKPOINT_FILE = Path(__file__).resolve().parent / 'monitor_checkpoint.json'


def read_checkpoint() -> dict:
    if not CHECKPOINT_FILE.exists():
        return {}
    data = json.loads(CHECKPOINT_FILE.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid repository checkpoint structure')
    return data


def restore_checkpoint(data: dict, *, reset_pause: bool = False) -> None:
    """Restore public non-sensitive state between ephemeral GitHub runners."""
    slot_ids = data.get('slot_ids') or []
    if not isinstance(slot_ids, list) or any(not isinstance(s, str) for s in slot_ids):
        raise ValueError('Invalid checkpoint slot fingerprints')
    monitor.write_json(monitor.STATE_FILE, {'slot_ids': slot_ids})
    if data.get('paused') and not reset_pause:
        monitor.write_json(monitor.PAUSE_FILE, {'reason': 'previous CAPTCHA, login or selector issue'})
    elif monitor.PAUSE_FILE.exists():
        monitor.PAUSE_FILE.unlink()
    if data.get('health_status') == 'error':
        monitor.write_json(monitor.HEALTH_FILE, {
            'status': 'error',
            'last_alert_epoch': float(data.get('last_alert_epoch', 0) or 0),
        })


def restore_auth_from_secret() -> None:
    """Decode the encrypted GitHub Secret into a temporary local file (never print)."""
    encoded = os.getenv('AUTH_STATE_B64', '').strip()
    if not encoded:
        raise monitor.ActionRequired('AUTH_STATE_B64 GitHub Secret мавжуд эмас.')
    try:
        raw = base64.b64decode(encoded, validate=True)
        obj = json.loads(raw)
        if not isinstance(obj, dict) or not isinstance(obj.get('cookies'), list) or not isinstance(obj.get('origins'), list):
            raise ValueError()
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise monitor.ActionRequired('AUTH_STATE_B64 яроқсиз. Сессияни қайта экспорт қилинг.') from None
    monitor.secure_private()
    monitor.AUTH_STATE_FILE.write_bytes(raw)
    if os.name != 'nt':
        monitor.AUTH_STATE_FILE.chmod(0o600)


def make_checkpoint() -> dict:
    """Only hashes and generic status: absolutely no auth state or personal content."""
    state = monitor.read_json(monitor.STATE_FILE)
    health = monitor.read_json(monitor.HEALTH_FILE)
    slot_ids = state.get('slot_ids', [])
    if not isinstance(slot_ids, list) or any(not isinstance(s, str) for s in slot_ids):
        slot_ids = []
    # Weekly heartbeat makes scheduled workflows less likely to be disabled for 60d inactivity.
    heartbeat = datetime.now(timezone.utc).strftime('%G-W%V')
    return {
        'slot_ids': sorted(set(slot_ids)),
        'paused': monitor.PAUSE_FILE.exists(),
        'health_status': 'error' if health.get('status') == 'error' else 'ok',
        'last_alert_epoch': (float(health.get('last_alert_epoch', 0) or 0)
                             if health.get('status') == 'error' else 0),
        'heartbeat_week': heartbeat,
    }


def main() -> None:
    reset_pause = os.getenv('RESET_PAUSE', '').strip().lower() in {'true', '1', 'yes'}
    old = read_checkpoint()
    restore_checkpoint(old, reset_pause=reset_pause)
    # Fresh session on each run, with secret accessible ONLY to this workflow.
    # No authorization bypass: manual login on local machine must have succeeded first.
    if not (old.get('paused') and not reset_pause):
        try:
            restore_auth_from_secret()
            monitor.cmd_cloud_once(monitor.load_config())
        except monitor.ActionRequired as exc:
            monitor.write_json(monitor.PAUSE_FILE, {'reason': str(exc)})
            config = monitor.load_config()
            if config.bot_token and config.chat_id:
                try:
                    monitor.notify(config, '⛔️ Visa monitor: ' + str(exc) + ' ' + monitor.local_times())
                except Exception:
                    print('Telegram notification failed; inspect Secrets settings.')
            print('PAUSED: manual configuration required.')
    else:
        print('PAUSED: manual reset needed; no site request was sent.')
    checkpoint = make_checkpoint()
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Saved public-safe checkpoint (no cookies, passwords or tokens).')


if __name__ == '__main__':
    main()
