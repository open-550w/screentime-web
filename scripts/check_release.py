#!/usr/bin/env python3
"""Scan tracked release files for runtime artifacts and optional real credentials."""
import argparse
import json
import re
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('--private-state',type=Path);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
secrets=[]
if args.private_state:
    directory=args.private_state.expanduser()
    token=directory/'access-token'
    if token.exists():secrets.append(token.read_text(encoding='utf-8').strip())
    for name in ('android-source.json','sync-config.json'):
        path=directory/name
        if path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            sources=data.get('sources',[data])
            for source in sources:
                if source.get('token'):secrets.append(source['token'])
                if source.get('url'):secrets.append(source['url'])
fail=[]
for name in filter(None,files):
    path=root/name
    if path.suffix in ('.sqlite','.db','.log','.png','.jpg') or path.name in ('access-token','sync-config.json','android-source.json'):
        fail.append(name+' (runtime artifact)');continue
    if not path.is_file():continue
    text=path.read_text(encoding='utf-8',errors='replace')
    if any(value and len(value)>8 and value in text for value in secrets):fail.append(name+' (private credential/endpoint)')
    if re.search(r'/Users/[A-Za-z0-9_-]+/',text):fail.append(name+' (absolute personal path)')
if fail:
    print('\n'.join(fail));raise SystemExit(1)
print('Release scan passed: no runtime artifacts or supplied private credentials in tracked files.')
