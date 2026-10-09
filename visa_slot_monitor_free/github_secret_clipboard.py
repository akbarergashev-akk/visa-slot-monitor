"""Windows-only helper to copy base64 browser session into clipboard, not terminal."""
from __future__ import annotations
import base64
import os
import subprocess
from pathlib import Path

p = Path(__file__).resolve().parent / '.private' / 'auth_state.json'
if not p.is_file():
    raise SystemExit('First run: python monitor.py export-session')
if os.name != 'nt':
    raise SystemExit('Windows helper only: use a protected clipboard tool on your OS.')
encoded = base64.b64encode(p.read_bytes())
if len(encoded) > 45_000:
    raise SystemExit('Session too large for a GitHub Secret. Do not use this method.')
subprocess.run(['clip'], input=encoded, check=True)
print('Session copied to Windows clipboard (NOT printed). Paste into GitHub Secret AUTH_STATE_B64, then clear clipboard.')
