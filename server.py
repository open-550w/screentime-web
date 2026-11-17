#!/usr/bin/env python3
"""Local Screen Time explorer. Stdlib only; source archive is always read-only."""
import argparse
import collections
from contextlib import contextmanager
import datetime as dt
import hashlib
import html
import sys
from contextlib import closing
from config_store import atomic_json
import hmac
import http.cookies
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('Asia/Shanghai')
DEFAULT_ARCHIVE = Path.home() / 'Library/Application Support/ScreenTimeArchive/archive.sqlite'
DEFAULT_STATE = Path.home() / ('Library/Application Support/ScreenTimeWeb' if sys.platform=='darwin' else '.local/share/screentime-web')
DEFAULT_CATEGORIES = [
    ('work', '工作与学习', '#5473e8'), ('social', '沟通社交', '#18a795'),
    ('video', '视频娱乐', '#e8a348'), ('read', '阅读资讯', '#a279cb'),
    ('tools', '工具与系统', '#8b99aa'), ('other', '未分类', '#bcc4cf')]
KNOWN = {
 'com.tencent.xin': ('微信', 'social'), 'com.tencent.xinWeChat': ('微信', 'social'),
 'tv.danmaku.bilianime': ('哔哩哔哩', 'video'), 'tv.danmaku.bili': ('哔哩哔哩', 'video'),
 'com.google.Chrome': ('Google Chrome', 'other'), 'com.google.chrome.ios': ('Chrome', 'other'),
 'com.openai.codex': ('Codex', 'work'), 'com.openai.chat': ('ChatGPT', 'work'),
 'com.microsoft.VSCode': ('Visual Studio Code', 'work'),
 'com.seagroup.seatalkmac.enterprise': ('SeaTalk', 'social'),
 'com.googlecode.iterm2': ('iTerm', 'work'), 'com.apple.loginwindow': ('登录 / 锁屏界面', 'tools'),
 'com.apple.finder': ('访达', 'tools'), 'com.apple.springboard': ('主屏幕', 'tools'),
 'com.apple.Preferences': ('设置', 'tools'), 'com.apple.mobilesafari': ('Safari', 'other'),
 'com.apple.Safari': ('Safari', 'other'), 'com.apple.MobileSMS': ('信息', 'social'),
 'com.apple.mobilephone': ('电话', 'social'), 'com.apple.InCallService': ('通话', 'social'),
 'com.apple.mobileslideshow': ('照片', 'tools'), 'com.apple.camera': ('相机', 'tools'),
 'com.apple.AppStore': ('App Store', 'tools'), 'com.apple.MobileStore': ('iTunes Store', 'tools'),
 'com.baidu.netdisk': ('百度网盘', 'tools'), 'com.max.xiaoheihe': ('小黑盒', 'video'),
 'com.netease.uuremote': ('UU 远程', 'tools'), 'com.apple.systempreferences': ('系统设置', 'tools'),
 'com.google.ios.youtube': ('YouTube', 'video'), 'com.apple.mobilemail': ('邮件', 'social'),
 'com.apple.mobilenotes': ('备忘录', 'tools'), 'com.apple.Music': ('音乐', 'video'),
 'com.apple.mobiletimer': ('时钟', 'tools'), 'com.apple.mobilesafari.SafariViewService': ('App 内浏览器', 'other')}


def stamp(value):
    value = str(value)
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.timestamp()


def local(ts):
    return dt.datetime.fromtimestamp(ts, TZ)


def life_day(ts, boundary):
    return (local(ts) - dt.timedelta(hours=boundary)).date()


def midnight(day, boundary=0):
    return dt.datetime.combine(day, dt.time(boundary), TZ).timestamp()


def union_seconds(intervals):
    total, start, end = 0.0, None, None
    for a, b in sorted(intervals):
        if start is None:
            start, end = a, b
        elif a <= end:
            end = max(end, b)
        else:
            total += end - start
            start, end = a, b
    return total + (end - start if start is not None else 0)


def special_seconds(a, b, start_hour, end_hour):
    total = 0
    day = local(a).date()
    while midnight(day) < b:
        total += max(0, min(b, midnight(day, end_hour)) - max(a, midnight(day, start_hour)))
        day += dt.timedelta(days=1)
    return total


class Store:
    def __init__(self, archive, state):
        self.archive, self.state = Path(archive), Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name=='posix':self.state.chmod(0o700)
        self.dbfile = self.state / 'preferences.sqlite'
        with self.prefs() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY,name TEXT NOT NULL,color TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS apps(bundle TEXT PRIMARY KEY,name TEXT,category TEXT);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
            db.executemany('INSERT OR IGNORE INTO categories VALUES (?,?,?)', DEFAULT_CATEGORIES)
            for key, value in {'boundary': 4, 'special_start': 3, 'special_end': 5}.items():
                db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, json.dumps(value)))
        self.sync_lock = threading.Lock()
        self.last_sync_request = 0
        self.sync_error = None
        from android_sync import SCHEMA
        self.empty_archive=self.state/'empty-archive.sqlite'
        with closing(sqlite3.connect(self.empty_archive)) as db:
            db.executescript(SCHEMA)
        from sync_manager import SyncManager
        self.manager=SyncManager(self)

    @contextmanager
    def prefs(self):
        db = sqlite3.connect(self.dbfile, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def source(self):
        path=self.archive if self.archive.exists() else self.empty_archive
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            android = self.state / 'android.sqlite'
            if android.exists():
                db.execute('ATTACH DATABASE ? AS android', (android.resolve().as_uri() + '?mode=ro',))
                for table in ('devices', 'sessions', 'runs'):
                    db.execute(f'CREATE TEMP VIEW {table} AS SELECT * FROM main.{table} UNION ALL SELECT * FROM android.{table}')
            yield db
        finally:
            db.close()

    def settings(self):
        with self.prefs() as db:
            return {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}

    def names(self):
        with self.prefs() as db:
            overrides = {r['bundle']: dict(r) for r in db.execute('SELECT * FROM apps')}
            cats = [dict(r) for r in db.execute('SELECT * FROM categories ORDER BY rowid')]
        return overrides, cats

    def app(self, bundle, overrides):
        name, category = KNOWN.get(bundle, (bundle.split('.')[-1], 'other'))
        if bundle.startswith('com.google.Chrome.app.'):
            name = 'Chrome 网页应用 · ' + bundle.rsplit('.', 1)[-1][:8]
        row = overrides.get(bundle, {})
        return {'bundle': bundle, 'name': row.get('name') or name, 'category': row.get('category') or category}

    def meta(self):
        overrides, cats = self.names()
        with self.manager.lock:
            sync_states=list(self.manager.status.values())
        with self.source() as db:
            devices = [dict(r) for r in db.execute('''SELECT d.*,count(s.start_ts) sessions,min(s.start_ts) earliest,max(s.end_ts) latest
                FROM devices d LEFT JOIN sessions s USING(device_id) GROUP BY d.device_id ORDER BY sessions DESC''')]
            bundles = [r[0] for r in db.execute('SELECT DISTINCT bundle_id FROM sessions ORDER BY bundle_id')]
            runs = [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY run_at DESC LIMIT 32')]
        counts = collections.Counter(d['name'] for d in devices)
        for d in devices:
            d['label'] = d['name'] + (' · ' + d['device_id'][:6] if counts[d['name']] > 1 else '')
            d['source_label'] = ('ActivityWatch 同步' if d['source'].startswith('activitywatch:') else
                                 '本机归档' if d['source'] == 'knowledgeC:/app/usage' else 'Apple 同步')
        phone = next((d['device_id'] for d in devices if d['platform'] == 'ios' and d['sessions']), None)
        last_time = max((r['run_at'] for r in runs), default=0)
        last_run = [r for r in runs if r['run_at'] >= last_time - 2]
        return {'devices': devices, 'apps': [self.app(b, overrides) for b in bundles],
                'categories': cats, 'settings': self.settings(), 'default_device': phone or (devices[0]['device_id'] if devices else None),
                'last_run': last_time, 'errors': [r['message'] for r in last_run if r['status'] != 'ok'],
                'sync_running': any(s.get('running') for s in sync_states), 'sync_error': next((s.get('error') for s in sync_states if s.get('error')),None),
                'android_sync': self.android_status(), 'source_count':len(self.manager.config.load()['sources']), 'timezone': 'Asia/Shanghai'}

    def android_status(self):
        try:
            return json.loads((self.state / 'android-sync-status.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def period(self, query):
        settings = self.settings()
        boundary = settings['boundary']
        start = stamp(query['start'])
        end = stamp(query['end'])
        if not math.isfinite(start + end) or end <= start or end - start > 366 * 86400:
            raise ValueError('请选择有效的起止时间，单次最多查询 366 天')
        devices = [s for s in query.get('devices', '').split(',') if s]
        if len(devices) > 64:
            raise ValueError('设备过多')
        where = ' AND device_id IN (' + ','.join('?' for _ in devices) + ')' if devices else ''
        with self.source() as db:
            rows = db.execute('SELECT device_id,bundle_id,start_ts,end_ts FROM sessions WHERE start_ts < ? AND end_ts > ?' + where + ' ORDER BY start_ts', [end, start] + devices).fetchall()
        return start, end, boundary, settings, rows

    def stats(self, query):
        start, end, boundary, settings, rows = self.period(query)
        overrides, cats = self.names()
        app_totals, cat_totals, device_intervals = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(list)
        days = {}
        day = life_day(start, boundary)
        while midnight(day, boundary) < end:
            key = day.isoformat()
            days[key] = {'date': key, 'seconds': 0, 'apps': {}, 'categories': {}, 'first': None, 'last': None, 'special_seconds': 0, 'sessions': 0}
            day += dt.timedelta(days=1)
        daily_intervals = collections.defaultdict(lambda: collections.defaultdict(list))
        for row in rows:
            a, b = max(start, row['start_ts']), min(end, row['end_ts'])
            bundle, device = row['bundle_id'], row['device_id']
            info = self.app(bundle, overrides)
            app_totals[bundle] += b - a
            cat_totals[info['category']] += b - a
            device_intervals[device].append((a,b))
            cursor = a
            while cursor < b:
                day = life_day(cursor, boundary)
                stop = min(b, midnight(day + dt.timedelta(days=1), boundary))
                if stop <= cursor:
                    raise ValueError('日期边界无效')
                d = days[day.isoformat()]
                secs = stop - cursor
                d['seconds'] += secs
                d['apps'][bundle] = d['apps'].get(bundle, 0) + secs
                d['categories'][info['category']] = d['categories'].get(info['category'], 0) + secs
                d['first'] = cursor if d['first'] is None else min(d['first'], cursor)
                d['last'] = stop if d['last'] is None else max(d['last'], stop)
                d['special_seconds'] += special_seconds(cursor, stop, settings['special_start'], settings['special_end'])
                d['sessions'] += 1
                daily_intervals[d['date']][device].append((cursor,stop))
                cursor = stop
        for d in days.values():
            d['active_seconds'] = sum(union_seconds(v) for v in daily_intervals[d['date']].values())
        group = query.get('group', 'day')
        if group not in ('day','week','month'):
            raise ValueError('无效的汇总粒度')
        buckets = {}
        for d in days.values():
            day = dt.date.fromisoformat(d['date'])
            key = d['date'] if group == 'day' else ((day - dt.timedelta(days=day.weekday())).isoformat() if group == 'week' else day.strftime('%Y-%m'))
            bucket = buckets.setdefault(key, {'date': key, 'seconds': 0, 'apps': {}, 'categories': {}})
            bucket['seconds'] += d['seconds']
            for field in ('apps','categories'):
                for key2, secs in d[field].items():
                    bucket[field][key2] = bucket[field].get(key2, 0) + secs
        total = sum(app_totals.values())
        apps = [dict(self.app(b,overrides), seconds=s, share=s/total if total else 0) for b,s in sorted(app_totals.items(),key=lambda x:-x[1])]
        catmap = {c['id']:c for c in cats}
        categories = [dict(catmap.get(c, {'id':c,'name':'未分类','color':'#bcc4cf'}),seconds=s,share=s/total if total else 0) for c,s in sorted(cat_totals.items(), key=lambda x:-x[1])]
        return {'total':total, 'active':sum(union_seconds(v) for v in device_intervals.values()),
                'sessions':len(rows), 'apps':apps, 'categories':categories, 'days':list(days.values()),
                'buckets':list(buckets.values()),'start':start,'end':end,'boundary':boundary,
                'first': min((max(start,r['start_ts']) for r in rows), default=None),
                'last': max((min(end,r['end_ts']) for r in rows), default=None)}

    def timeline(self, query, max_days=3):
        start, end, boundary, settings, rows = self.period(query)
        if end-start > max_days*86400:
            raise ValueError(f'时间线单次最多查看 {max_days} 天')
        overrides, _ = self.names()
        items = []
        for row in rows:
            a,b = max(start,row['start_ts']),min(end,row['end_ts'])
            items.append(dict(self.app(row['bundle_id'],overrides), device=row['device_id'],start=a,end=b,
                original_start=row['start_ts'], original_end=row['end_ts'], seconds=b-a,
                special=special_seconds(a,b,settings['special_start'],settings['special_end'])>0))
        return {'items':items,'start':start,'end':end}

    def save(self, kind, data):
        with self.prefs() as db:
            if kind == 'app':
                bundle = str(data.get('bundle','')).strip()
                name = str(data.get('name','')).strip()
                cat = str(data.get('category','other'))
                if not bundle or len(bundle)>300 or not name or len(name)>100:
                    raise ValueError('应用名称需为 1–100 个字符')
                if not db.execute('SELECT 1 FROM categories WHERE id=?',(cat,)).fetchone():
                    raise ValueError('分类不存在')
                db.execute('INSERT INTO apps VALUES (?,?,?) ON CONFLICT(bundle) DO UPDATE SET name=excluded.name,category=excluded.category', (bundle,name,cat))
            elif kind == 'category':
                name = str(data.get('name','')).strip()
                color = str(data.get('color','#5473e8'))
                ident = str(data.get('id') or secrets.token_hex(6))
                import re
                if not name or len(name)>40 or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
                    raise ValueError('分类名称或颜色无效')
                db.execute('INSERT INTO categories VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,color=excluded.color',(ident,name,color))
            elif kind == 'settings':
                values = {k:int(data[k]) for k in ('boundary','special_start','special_end')}
                if not 0<=values['boundary']<=12 or not 0<=values['special_start']<values['special_end']<=12:
                    raise ValueError('分界支持 0–12 点；特殊时段须在 0–12 点内且结束晚于开始')
                db.executemany('UPDATE settings SET value=? WHERE key=?',[(json.dumps(v),k) for k,v in values.items()])
            else:
                raise ValueError('未知设置')

    def sync(self,ids=None,full=False):
        return self.manager.run(ids,full=full)


class Server(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'ScreenTimeWeb'

    def log_message(self, format, *args):
        # Never log token-bearing URLs, cookies, request bodies or browsing records.
        print(f'{self.log_date_time_string()} {self.command} {urllib.parse.urlsplit(self.path).path} {args[1] if len(args)>1 else ""}', flush=True)

    def headers_common(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        # Cross-origin clients use an explicit Bearer token, never ambient cookies.
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
        self.send_header('Access-Control-Max-Age','600')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def response(self, status, data, content_type='application/json; charset=utf-8', cookie=None, location=None):
        body = json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
        self.send_response(status)
        self.headers_common()
        if cookie:
            self.send_header('Set-Cookie',cookie)
        if location:
            self.send_header('Location',location)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.bearer_authorized():
            return True
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
            return hmac.compare_digest(cookie.get(self.server.cookie_name).value, self.server.session) if cookie.get(self.server.cookie_name) else False
        except (http.cookies.CookieError,TypeError):
            return False

    def bearer_authorized(self):
        auth=self.headers.get('Authorization','')
        return auth.startswith('Bearer ') and hmac.compare_digest(auth[7:].encode(),self.server.token.encode())

    def valid_host(self):
        host=self.headers.get('Host','').lower()
        if not self.server.network_access:
            return host in self.server.allowed_hosts
        try:
            parsed=urllib.parse.urlsplit('http://'+host)
            return bool(parsed.hostname) and parsed.port in (None,self.server.server_address[1]) and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
        except ValueError:
            return False

    def same_origin(self):
        origin=self.headers.get('Origin')
        return not origin or origin == 'http://'+self.headers.get('Host','')

    def route_location(self):
        pairs=urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query,keep_blank_values=True)
        query=urllib.parse.urlencode([(k,v) for k,v in pairs if k!='token'])
        return '/'+('?' + query if query else '')

    def do_OPTIONS(self):
        if not self.valid_host():
            return self.response(403,{'error':'Host 不允许'})
        return self.response(204,b'')

    def do_GET(self):
        if not self.valid_host():
            return self.response(403,{'error':'Host 不允许'})
        url=urllib.parse.urlsplit(self.path)
        query={k:v[-1] for k,v in urllib.parse.parse_qs(url.query).items()}
        if url.path=='/' and 'token' in query:
            if hmac.compare_digest(query['token'].encode(),self.server.token.encode()):
                return self.response(303,b'',cookie=self.cookie(),location=self.route_location())
            return self.response(401,{'error':'Token 无效'})
        if url.path=='/login' or (url.path=='/' and not self.authorized()):
            route=self.route_location()
            action='/login'+(route[1:] if '?' in route else '')
            page=(ROOT/'static/login.html').read_text(encoding='utf-8').replace('action="/login"','action="'+html.escape(action,quote=True)+'"')
            return self.response(200,page.encode(),'text/html; charset=utf-8')
        if not self.authorized():
            return self.response(401,{'error':'请先输入访问 Token'})
        try:
            if url.path=='/api/meta':
                return self.response(200,self.server.store.meta())
            if url.path=='/api/sync-config':
                return self.response(200,self.server.store.manager.public())
            if url.path=='/api/export':
                return self.response(200,self.server.exporter.export(query))
            if url.path=='/api/stats':
                return self.response(200,self.server.store.stats(query))
            if url.path=='/api/timeline':
                return self.response(200,self.server.store.timeline(query))
            if url.path=='/api/device-timeline':
                return self.response(200,self.server.store.timeline(query,max_days=366))
            docs={'/docs/android-lan.md','/docs/android-frpc.md','/docs/api.md','/docs/scheduling.md','/docs/apple.md'}
            if url.path in docs:
                return self.response(200,(ROOT/url.path.lstrip('/')).read_bytes(),'text/plain; charset=utf-8')
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.ico':None}
            if url.path in files:
                name=files[url.path]
                if name is None:
                    return self.response(204,b'')
                typ='text/html; charset=utf-8' if name.endswith('.html') else ('text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8')
                return self.response(200,(ROOT/'static'/name).read_bytes(),typ)
            return self.response(404,{'error':'不存在'})
        except (ValueError,KeyError,OverflowError) as e:
            return self.response(400,{'error':str(e)})
        except (sqlite3.Error,OSError):
            return self.response(503,{'error':'归档暂不可读，请确认已安装 Screen Time Archive 并完成首次归档'})

    def cookie(self):
        return self.server.cookie_name+'='+self.server.session+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'

    def do_POST(self):
        if not self.valid_host():
            return self.response(403,{'error':'Host 不允许'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536:
                return self.response(413,{'error':'请求大小无效'})
            raw=self.rfile.read(length)
            path=urllib.parse.urlsplit(self.path).path
            if path=='/login':
                values=urllib.parse.parse_qs(raw.decode())
                token=values.get('token',[''])[0]
                if hmac.compare_digest(token.encode(),self.server.token.encode()):
                    return self.response(303,b'',cookie=self.cookie(),location=self.route_location())
                time.sleep(0.25)
                return self.response(401,b'Token invalid. Go back and try again.','text/plain; charset=utf-8')
            if not self.authorized():
                return self.response(401,{'error':'请先输入访问 Token'})
            if not self.same_origin() and not self.bearer_authorized():
                return self.response(403,{'error':'跨站调用请使用 Authorization: Bearer <全局Token>，不能仅使用 Cookie'})
            if path=='/api/logout':
                return self.response(200,{'ok':True},cookie=self.server.cookie_name+'=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            data=json.loads(raw)
            if not isinstance(data,dict):
                raise ValueError('JSON 须为对象')
            if path=='/api/sync':
                ids=data.get('sources')
                if ids is not None and (not isinstance(ids,list) or any(not isinstance(i,str) for i in ids)):raise ValueError('sources 须为 ID 数组')
                return self.response(202,self.server.store.sync(ids,full=data.get('full') is True))
            if path=='/api/sync-config':
                manager=self.server.store.manager
                if data.get('action')=='shared':
                    manager.config.save_shared(data['policy'])
                    manager.tick()
                elif data.get('action')=='source':
                    ident=manager.config.save_source(data['source'])
                    manager.tick()
                    return self.response(200,{'ok':True,'id':ident})
                else:raise ValueError('未知配置操作')
                return self.response(200,{'ok':True})
            if path=='/api/source-test':
                from android_sync import discover
                source=self.server.store.manager.config.source(data['id'])
                if source['type']!='activitywatch':raise ValueError('仅 AW 数据源支持连接测试')
                try:
                    info,buckets=discover(source)
                except Exception:
                    return self.response(502,{'error':'AW 连接失败，请检查地址、Token、服务监听与 frpc 状态'})
                return self.response(200,{'ok':True,'buckets':buckets,'version':info.get('version')})
            kind={'/api/app':'app','/api/category':'category','/api/settings':'settings'}.get(path)
            if not kind:
                return self.response(404,{'error':'不存在'})
            self.server.store.save(kind,data)
            return self.response(200,{'ok':True})
        except (ValueError,KeyError,TypeError) as e:
            return self.response(400,{'error':str(e)})
        except sqlite3.Error:
            return self.response(503,{'error':'设置保存失败，请稍后重试'})


def ensure_token(state):
    state=Path(state)
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    token_path=state/'access-token'
    if not token_path.exists():
        fd=os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(32)+'\n')
    token=token_path.read_text(encoding='utf-8').strip()
    if len(token)<32:
        raise ValueError('访问 Token 长度不足')
    return token


def create_server(host='127.0.0.1',port=7076,archive=DEFAULT_ARCHIVE,state=DEFAULT_STATE):
    token=ensure_token(state)
    server=Server((host,port),Handler)
    actual=server.server_address[1]
    server.token=token
    server.cookie_name=f'st_session_{actual}'
    server.session=hmac.new(token.encode(),b'screentime-web/session/v1',hashlib.sha256).hexdigest()
    server.allowed_hosts={f'127.0.0.1:{actual}',f'localhost:{actual}'}
    server.network_access=host not in ('127.0.0.1','localhost','::1')
    server.store=Store(archive,state)
    from export_api import Exporter
    server.exporter=Exporter(server.store,token)
    return server


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=7076)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--archive',type=Path,default=DEFAULT_ARCHIVE)
    parser.add_argument('--state',type=Path,default=DEFAULT_STATE)
    args=parser.parse_args()
    server=create_server(host=args.host,port=args.port,archive=args.archive,state=args.state)
    print(f'Screen Time Web: listening on {args.host}:{args.port} (token protected)',flush=True)
    server.store.manager.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.store.manager.close()
        server.server_close()
