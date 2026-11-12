"""Authenticated, snapshot-based JSON session exports (raw archive or enriched)."""
import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
import threading
import time
from config_store import atomic_json


class Exporter:
    TTL=1800
    def __init__(self,store,secret):
        self.store,self.secret=store,secret.encode()
        self.directory=store.state/'exports'
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.lock=threading.Lock()

    def cursor(self,ident,offset):
        value=f'{ident}:{offset}'
        signature=hmac.new(self.secret,value.encode(),hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode((value+':'+signature).encode()).decode().rstrip('=')

    def read_cursor(self,value):
        try:
            raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode()
            ident,offset,signature=raw.split(':')
            if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError()
            expected=hmac.new(self.secret,(ident+':'+offset).encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,signature):raise ValueError()
            if not 0<=int(offset)<=10000000:raise ValueError()
            return ident,int(offset)
        except Exception:
            raise ValueError('无效的分页游标') from None

    def export(self,query):
        limit=query.get('limit','1000')
        if limit!='all':
            try:limit=int(limit)
            except (TypeError,ValueError):raise ValueError('limit 须为 1–5000 或 all') from None
            if not 1<=limit<=5000:raise ValueError('limit 须为 1–5000 或 all')
        with self.lock:
            if query.get('cursor'):
                ident,offset=self.read_cursor(query['cursor'])
                path=self.directory/(ident+'.json')
                try:snapshot=json.loads(path.read_text())
                except (OSError,ValueError):raise ValueError('快照不存在或已过期，请重新导出') from None
                if time.time()-snapshot['created_at']>self.TTL:
                    path.unlink(missing_ok=True)
                    raise ValueError('快照已过期，请重新导出')
            else:
                ident=secrets.token_hex(16);offset=0
                snapshot=self.build(query)
                atomic_json(self.directory/(ident+'.json'),snapshot)
                for path in self.directory.glob('*.json'):
                    if time.time()-path.stat().st_mtime>self.TTL:path.unlink(missing_ok=True)
            records=snapshot['records']
            stop=len(records) if limit=='all' else min(len(records),offset+limit)
            page=records[offset:stop]
            next_cursor=self.cursor(ident,stop) if stop<len(records) else None
            metadata={k:v for k,v in snapshot.items() if k!='records'}
            return dict(metadata,snapshot_id=ident,total_count=len(records),offset=offset,returned_count=len(page),
                        next_cursor=next_cursor,complete=next_cursor is None,records=page)

    def build(self,query):
        from server import stamp
        start,end=stamp(query['start']),stamp(query['end'])
        if end<=start or end-start>366*86400:raise ValueError('导出范围须为正数且不超过 366 天')
        mode=query.get('format','enriched')
        if mode not in ('raw','enriched'):raise ValueError('format 须为 raw 或 enriched')
        ids=[i for i in query.get('devices','').split(',') if i]
        if len(ids)>64:raise ValueError('设备过多')
        where=' AND device_id IN ('+','.join('?' for _ in ids)+')' if ids else ''
        overrides,categories=self.store.names();cats={c['id']:c for c in categories}
        with self.store.source() as db:
            db.execute('BEGIN')
            devices={d['device_id']:dict(d) for d in db.execute('SELECT * FROM devices')}
            unknown=set(ids)-devices.keys()
            if unknown:raise ValueError('设备 ID 不存在')
            rows=[dict(r) for r in db.execute('SELECT device_id,bundle_id,start_ts,end_ts FROM sessions WHERE start_ts < ? AND end_ts > ?'+where+' ORDER BY start_ts,device_id,bundle_id',[end,start]+ids)]
            # Preserve actual AW payloads when collected by the open-source version.
            raw_events={}
            try:
                for row in db.execute('SELECT r.device_id,r.timestamp,r.payload,r.bucket_id,r.event_id FROM android.raw_events r JOIN android.events e ON r.device_id=e.device_id AND r.event_id=e.event_id WHERE e.start < ? AND e.end > ?',(end,start)):
                    event=json.loads(row['payload']);package=event.get('data',{}).get('package','')
                    raw_events.setdefault((row['device_id'],'android:'+package,row['timestamp']),[]).append({'bucket_id':row['bucket_id'],'event':event})
            except Exception as exc:
                import sqlite3
                if not isinstance(exc,sqlite3.OperationalError):raise
            freshness={r['device_id']:r['latest'] for r in db.execute('SELECT device_id,MAX(end_ts) latest FROM sessions GROUP BY device_id')}
        records=[]
        for row in rows:
            device=devices[row['device_id']]
            original_start,original_end=row['start_ts'],row['end_ts']
            key=(row['device_id'],row['bundle_id'],row['start_ts'])
            record=dict(row,source=device['source'])
            record['source_events']=raw_events.get(key,[])
            record['source_payload_available']=bool(record['source_events'])
            if mode=='enriched':
                app=self.store.app(row['bundle_id'],overrides)
                a,b=max(start,original_start),min(end,original_end)
                record.update(name=app['name'],category=cats.get(app['category']),device_name=device['name'],
                              platform=device['platform'],original_start=original_start,original_end=original_end,
                              start=a,end=b,duration_seconds=b-a,
                              start_iso=dt.datetime.fromtimestamp(a,dt.timezone.utc).isoformat(),
                              end_iso=dt.datetime.fromtimestamp(b,dt.timezone.utc).isoformat())
            records.append(record)
        selected=[dict(d,latest_record=freshness.get(ident)) for ident,d in devices.items() if not ids or ident in ids]
        return {'schema_version':1,'created_at':time.time(),'format':mode,'timezone':'Asia/Shanghai',
                'range':{'start':start,'end':end,'semantics':'[start,end); intersecting sessions'},
                'devices':selected,'categories':categories if mode=='enriched' else [],
                'raw_definition':'Archived sessions, not Apple OS database dumps. source_events present only where retained.',
                'records':records}
