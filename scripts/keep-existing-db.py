#!/usr/bin/env python3
"""Generate a persistent Compose override from the pre-upgrade resolved config."""
import json
import os
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 scripts/keep-existing-db.py /path/to/compose.before.json')
old = json.loads(Path(sys.argv[1]).read_text())
if not old.get('name') or 'db' not in old.get('services', {}):
    raise SystemExit('Snapshot must contain the original Compose project name and db service')
output = Path('compose.keep-db.json')
if output.exists():
    raise SystemExit('compose.keep-db.json already exists; keep using it, do not overwrite it')
config = {'name': old['name'], 'services': {'db': old['services']['db']}}
for key in ('volumes', 'networks', 'configs', 'secrets'):
    if old.get(key):
        config[key] = old[key]
with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
    json.dump(config, stream, indent=2)
    stream.write('\n')
print('Created compose.keep-db.json. Keep this file: it preserves the existing database configuration.')
