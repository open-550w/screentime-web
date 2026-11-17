"""Versioned private sync settings. Never expose stored credentials in API responses."""
from copy import deepcopy
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_POLICY = {'enabled': True, 'mode': 'interval', 'interval_minutes': 30,
                  'times': ['12:30'], 'timezone': 'Asia/Shanghai', 'run_on_start': False}


def atomic_json(path, data):
    path=Path(path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(5)+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def validate_policy(value):
    if not isinstance(value,dict):
        raise ValueError('调度配置须为对象')
    p={k:value.get(k,v) for k,v in DEFAULT_POLICY.items()}
    for key in ('enabled','run_on_start'):
        if not isinstance(p[key],bool):
            raise ValueError('自动拉取和启动执行必须是布尔值')
    if p['mode'] not in ('interval','daily','combined'):
        raise ValueError('调度模式无效')
    if type(p['interval_minutes']) is not int or not 1<=p['interval_minutes']<=10080:
        raise ValueError('间隔须为 1–10080 分钟')
    if not isinstance(p['times'],list) or len(p['times'])>24:
        raise ValueError('每天最多 24 个固定时刻')
    if any(not isinstance(t,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',t) for t in p['times']):
        raise ValueError('固定时刻格式为 HH:MM')
    p['times']=sorted(set(p['times']))
    if p['mode']!='interval' and not p['times']:
        raise ValueError('请至少设置一个固定时刻')
    try:
        ZoneInfo(p['timezone'])
    except (ZoneInfoNotFoundError,TypeError,ValueError):
        raise ValueError('无效的 IANA 时区') from None
    return p


def next_due(policy, now, last_interval=None):
    """Coalesce missed runs; daily times are in the selected wall-clock timezone."""
    if not policy['enabled']:
        return None
    candidates=[]
    if policy['mode'] in ('interval','combined'):
        candidates.append((now if last_interval is None else last_interval)+policy['interval_minutes']*60)
    if policy['mode'] in ('daily','combined'):
        zone=ZoneInfo(policy['timezone'])
        day=dt.datetime.fromtimestamp(now,zone).date()
        for offset in (0,1,2):
            for wall in policy['times']:
                value=dt.datetime.combine(day+dt.timedelta(days=offset),dt.time.fromisoformat(wall),zone).timestamp()
                if value>now:
                    candidates.append(value)
    return min(candidates)


class ConfigStore:
    def __init__(self,state,archive):
        self.state=Path(state);self.path=self.state/'sync-config.json';self.lock=threading.RLock()
        if not self.path.exists():
            sources=[]
            binary=Path.home()/'Library/Application Support/ScreenTimeArchive/bin/screentime-archiver'
            if Path(archive).exists() and binary.exists():
                sources.append({'id':'apple','name':'Apple 归档（本机与 iCloud 设备）','type':'apple',
                                'schedule_mode':'independent','schedule':dict(DEFAULT_POLICY,mode='daily',times=['12:30'],run_on_start=True)})
            legacy=self.state/'android-source.json'
            if legacy.exists():
                old=json.loads(legacy.read_text(encoding='utf-8'))
                hostname='';name='Android'
                dbfile=self.state/'android.sqlite'
                if dbfile.exists():
                    db=sqlite3.connect(dbfile.resolve().as_uri()+'?mode=ro',uri=True)
                    try:
                        row=db.execute("SELECT name,source FROM devices WHERE platform='android' LIMIT 1").fetchone()
                        if row:name,hostname=row[0],row[1].removeprefix('activitywatch:')
                    finally:db.close()
                sources.append({'id':'android-legacy','name':name,'type':'activitywatch','transport':'frpc',
                    'url':old['url'],'token':old.get('token',''),'bucket':'aw-watcher-android','hostname':hostname,
                    'schedule_mode':'independent','schedule':dict(DEFAULT_POLICY,interval_minutes=5,run_on_start=True)})
            atomic_json(self.path,{'version':1,'shared':deepcopy(DEFAULT_POLICY),'sources':sources})

    def load(self):
        with self.lock:
            return json.loads(self.path.read_text(encoding='utf-8'))

    def public(self):
        config=self.load()
        for source in config['sources']:
            source['has_token']=bool(source.pop('token',''))
            source['effective_schedule']=self.effective(config,source)
        return config

    @staticmethod
    def effective(config,source):
        return deepcopy(config['shared'] if source.get('schedule_mode','inherit')=='inherit' else source['schedule'])

    def save_shared(self,policy):
        policy=validate_policy(policy)
        with self.lock:
            config=self.load();config['shared']=policy;atomic_json(self.path,config)

    def save_source(self,data):
        if not isinstance(data,dict):raise ValueError('数据源须为对象')
        ident=data.get('id') or 'aw-'+secrets.token_hex(5)
        if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',ident):raise ValueError('数据源 ID 无效')
        name=str(data.get('name','')).strip()
        kind=data.get('type','activitywatch')
        if not name or len(name)>100 or kind not in ('apple','activitywatch'):raise ValueError('名称或数据源类型无效')
        with self.lock:
            config=self.load()
            old=next((s for s in config['sources'] if s['id']==ident),{})
            if old and old['type']!=kind:raise ValueError('不能更改已存在数据源的类型')
            if kind=='apple' and any(s['type']=='apple' and s['id']!=ident for s in config['sources']):raise ValueError('Apple 数据源只需配置一项，覆盖本机与同步设备')
            mode=data.get('schedule_mode','inherit')
            if mode not in ('inherit','independent'):raise ValueError('请选择继承公共配置或独立配置')
            source={'id':ident,'name':name,'type':kind,'schedule_mode':mode,
                    'schedule':validate_policy(data.get('schedule',old.get('schedule',DEFAULT_POLICY)))}
            if kind=='activitywatch':
                transport=data.get('transport','lan')
                if transport not in ('lan','frpc'):raise ValueError('连接方式无效')
                url=str(data.get('url','')).strip().rstrip('/')
                try:
                    parsed=urllib.parse.urlsplit(url)
                    valid=parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                    _=parsed.port
                except ValueError:valid=False
                if not valid or len(url)>2000:raise ValueError('AW 地址须为 http(s) URL，不要把 Token 写在 URL 中')
                token=data.get('token')
                if token in (None,''):token=old.get('token','')
                if data.get('clear_token'):token=''
                if not isinstance(token,str) or len(token)>4096 or '\n' in token or '\r' in token:raise ValueError('Token 无效')
                source.update(transport=transport,url=url,token=token,
                    bucket=str(data.get('bucket','')).strip(),hostname=str(data.get('hostname','')).strip())
                if len(source['bucket'])>300 or len(source['hostname'])>300:raise ValueError('桶名或主机名过长')
            config['sources']=[source if s['id']==ident else s for s in config['sources']]
            if not old:config['sources'].append(source)
            atomic_json(self.path,config)
            return ident

    def source(self,ident):
        source=next((s for s in self.load()['sources'] if s['id']==ident),None)
        if not source:raise ValueError('数据源不存在')
        return source
