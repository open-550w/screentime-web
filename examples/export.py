#!/usr/bin/env python3
"""Fetch all pages with a fixed snapshot; token comes from the environment."""
import argparse
import json
import os
import urllib.parse
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:7076')
parser.add_argument('--start',required=True)
parser.add_argument('--end',required=True)
parser.add_argument('--devices',default='')
parser.add_argument('--format',choices=['raw','enriched'],default='enriched')
args=parser.parse_args()
token=os.environ['SCREEN_TIME_TOKEN']
query={'start':args.start,'end':args.end,'devices':args.devices,'format':args.format,'limit':1000}
records=[];metadata=None
while True:
    request=urllib.request.Request(args.url.rstrip('/')+'/api/export?'+urllib.parse.urlencode(query),headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=60) as response:page=json.load(response)
    if metadata is None:metadata={k:v for k,v in page.items() if k not in ('records','next_cursor','offset','returned_count','complete')}
    records.extend(page['records'])
    if not page['next_cursor']:break
    query={'cursor':page['next_cursor'],'limit':1000}
print(json.dumps(dict(metadata,returned_count=len(records),complete=True,records=records),ensure_ascii=False,indent=2))
