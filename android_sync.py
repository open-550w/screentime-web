"""Read ActivityWatch foreground events into a separate local archive."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
from contextlib import closing
from config_store import atomic_json

STATE = Path.home() / ('Library/Application Support/ScreenTimeWeb' if sys.platform=='darwin' else '.local/share/screentime-web')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY,name TEXT,platform TEXT,os_build TEXT,source TEXT,first_seen REAL,last_seen REAL);
CREATE TABLE IF NOT EXISTS events(device_id TEXT,event_id INTEGER,bundle TEXT,start REAL,end REAL,PRIMARY KEY(device_id,event_id));
CREATE TABLE IF NOT EXISTS sessions(device_id TEXT,bundle_id TEXT,start_ts REAL,end_ts REAL,PRIMARY KEY(device_id,bundle_id,start_ts));
CREATE TABLE IF NOT EXISTS runs(run_at REAL,device_id TEXT,source TEXT,sessions_seen INTEGER,sessions_new INTEGER,status TEXT,message TEXT);
'''
CATEGORIES = {
    'browser': ('浏览器', '#5794c8'), 'network': ('网络与安全', '#658c80'),
    'shopping': ('购物消费', '#e7807b'), 'travel': ('出行导航', '#409fb3'),
    'life': ('生活服务', '#88a952'), 'system': ('系统组件', '#929ba5'),
    'media': ('摄影与媒体工具', '#b681af'),
    'tools': ('工具与系统', '#8b99aa'), 'social': ('沟通社交', '#18a795'),
    'video': ('视频娱乐', '#e8a348'), 'work': ('工作与学习', '#5473e8'),
}
APP_CATEGORIES = {
    'browser': ['com.android.chrome', 'com.microsoft.emmx'],
    'network': ['com.github.metacubex.clash.meta', 'io.github.acedroidx.frp', 'com.netease.uu', 'com.netease.uurouter'],
    'shopping': ['com.jingdong.app.mall', 'com.taobao.taobao'],
    'travel': ['com.autonavi.minimap'], 'life': ['com.xiaomi.smarthome'],
    'media': ['com.coloros.gallery3d', 'com.oplus.screenrecorder', 'com.oplus.screenshot'],
    'social': ['com.tencent.mobileqq', 'org.telegram.messenger'],
    'video': ['com.phoenix.read', 'com.ss.android.ugc.aweme', 'com.xingin.xhs', 'tv.danmaku.bili'],
    'work': ['com.ss.android.lark'],
    'system': ['android', 'com.android.launcher', 'com.android.permissioncontroller', 'com.android.settings',
               'com.heytap.quicksearchbox', 'com.oplus.appdetail', 'com.oplus.battery', 'com.oplus.wirelesssettings'],
}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(config, path):
    req = urllib.request.Request(config['url'].rstrip('/') + path,
                                 headers={'Authorization': 'Bearer ' + config['token']} if config.get('token') else {})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
        raw=response.read(32*1024*1024+1)
        if len(raw)>32*1024*1024:raise ValueError('AW response too large')
        return json.loads(raw)

def import_events(state, identity, events, device_name='Android', hostname='', source_id='', bucket_id='aw-watcher-android'):
    """Validate the entire batch before writing; IDs make repeat sync idempotent."""
    rows, names, raw_rows = [], {}, []
    for event in events:
        data = event['data']
        package = data.get('package')
        if not package:
            continue
        start = dt.datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).timestamp()
        duration = float(event['duration'])
        if not math.isfinite(start) or not math.isfinite(duration) or duration < 0:
            raise ValueError('Invalid foreground event')
        raw_rows.append((identity,source_id,bucket_id,int(event['id']),start,json.dumps(event,ensure_ascii=False)))
        if not duration:
            continue
        bundle = 'android:' + package
        rows.append((identity, int(event['id']), bundle, start, start + duration))
        names[bundle] = str(data.get('app') or package)
    now = time.time()
    state=Path(state);state.mkdir(mode=0o700,parents=True,exist_ok=True)
    with closing(sqlite3.connect(state / 'android.sqlite', timeout=30)) as db, db:
        db.executescript(SCHEMA)
        db.execute('CREATE TABLE IF NOT EXISTS raw_events(device_id TEXT,source_id TEXT,bucket_id TEXT,event_id INTEGER,timestamp REAL,payload TEXT,PRIMARY KEY(device_id,bucket_id,event_id))')
        db.executemany('INSERT INTO raw_events VALUES (?,?,?,?,?,?) ON CONFLICT(device_id,bucket_id,event_id) DO UPDATE SET source_id=excluded.source_id,timestamp=excluded.timestamp,payload=excluded.payload',raw_rows)
        before = db.execute('SELECT count(*) FROM events WHERE device_id=?', (identity,)).fetchone()[0]
        db.execute('INSERT INTO devices VALUES (?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen',
                   (identity, device_name, 'android', '', 'activitywatch:'+hostname, now, now))
        db.executemany('INSERT INTO events VALUES (?,?,?,?,?) ON CONFLICT(device_id,event_id) DO UPDATE SET bundle=excluded.bundle,start=excluded.start,end=excluded.end', rows)
        db.execute('DELETE FROM sessions WHERE device_id=?', (identity,))
        db.execute('INSERT INTO sessions SELECT device_id,bundle,start,max(end) FROM events WHERE device_id=? GROUP BY device_id,bundle,start', (identity,))
        after = db.execute('SELECT count(*) FROM events WHERE device_id=?', (identity,)).fetchone()[0]
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)', (now, identity, 'activitywatch:'+hostname, len(rows), after-before, 'ok', ''))
    # Never overwrite a user-supplied name or category, including later edits.
    with closing(sqlite3.connect(state / 'preferences.sqlite', timeout=30)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,name TEXT NOT NULL,color TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS apps(bundle TEXT PRIMARY KEY,name TEXT,category TEXT)')
        db.executemany('INSERT OR IGNORE INTO categories VALUES (?,?,?)', [(k, *v) for k, v in CATEGORIES.items()])
        for bundle, name in names.items():
            package = bundle.removeprefix('android:')
            category = next((c for c, packages in APP_CATEGORIES.items() if package in packages), 'other')
            db.execute('INSERT OR IGNORE INTO apps VALUES (?,?,?)', (bundle, 'Android-' + name, category))
    return {'device': identity, 'events': after, 'new': after-before, 'apps': len(names)}

def discover(config):
    info=request(config,'/api/0/info')
    buckets=request(config,'/api/0/buckets/')
    choices=[{'id':key,'hostname':value.get('hostname',''),'type':value.get('type','')} for key,value in buckets.items()
             if value.get('type')=='currentwindow' and key.startswith('aw-watcher-android')]
    return info, choices


def sync_source(state,config,full=False):
    state=Path(state)
    info,choices=discover(config)
    selected=[b for b in choices if not config.get('bucket') or b['id']==config['bucket']]
    if config.get('hostname'):selected=[b for b in selected if b['hostname']==config['hostname']]
    if len(selected)!=1:raise ValueError('Choose exactly one Android foreground bucket')
    bucket=selected[0]
    if not info.get('device_id'):raise ValueError('AW device_id missing')
    seed=info['device_id']+':'+bucket['hostname']
    if bucket['id']!='aw-watcher-android':seed+=':'+bucket['id']
    identity='android-'+hashlib.sha256(seed.encode()).hexdigest()[:24]
    params={'limit':'-1'}
    dbfile=state/'android.sqlite'
    if not full and dbfile.exists():
        with closing(sqlite3.connect(dbfile)) as db:
            latest=db.execute('SELECT MAX(end) FROM events WHERE device_id=?',(identity,)).fetchone()[0]
        if latest:
            params['start']=dt.datetime.fromtimestamp(max(0,latest-48*3600),dt.timezone.utc).isoformat()
    path='/api/0/buckets/'+urllib.parse.quote(bucket['id'],safe='')+'/events?'+urllib.parse.urlencode(params)
    events=request(config,path)
    if not isinstance(events,list):raise ValueError('Invalid AW events response')
    result=import_events(state,identity,events,config.get('name') or bucket['hostname'] or 'Android',
                         bucket['hostname'],config.get('id',''),bucket['id'])
    atomic_json(state/'android-sync-status.json',{'ok':True,'time':time.time(),**result})
    return result


def sync(state=STATE):
    # Backward compatible command; new installations use the shared scheduler.
    from config_store import ConfigStore
    config=ConfigStore(state,Path.home()/'Library/Application Support/ScreenTimeArchive/archive.sqlite').load()
    results=[sync_source(state,s) for s in config['sources'] if s['type']=='activitywatch']
    return results


def install_job():
    raise RuntimeError('Use install.py; scheduling is managed by the Web service')

if __name__ == '__main__':
    try:
        print(json.dumps(sync(), ensure_ascii=False))
    except Exception as exc:
        # Exception text may contain URLs; never print credentials or request details.
        atomic_json(STATE / 'android-sync-status.json',{'ok': False, 'time': time.time(), 'error': type(exc).__name__})
        print('Android sync failed: ' + type(exc).__name__)
        raise SystemExit(1)
