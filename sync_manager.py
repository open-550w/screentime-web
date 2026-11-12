"""One scheduler for configurable source policies; manual runs bypass auto-disable."""
from copy import deepcopy
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from config_store import ConfigStore, atomic_json, next_due


class SyncManager:
    def __init__(self,store):
        self.store=store
        self.config=ConfigStore(store.state,store.archive)
        self.path=store.state/'sync-status.json'
        try:self.status=json.loads(self.path.read_text())
        except (OSError,ValueError):self.status={}
        for row in self.status.values():row['running']=False
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.fingerprints={}

    def start(self):
        if self.thread:return
        self.thread=threading.Thread(target=self.loop,name='source-scheduler',daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)

    def loop(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception:
                # Do not log endpoints, tokens, or exception strings from remote services.
                print('Scheduler tick failed; retrying',flush=True)
            self.stop_event.wait(5)

    def tick(self,now=None):
        now=time.time() if now is None else now
        config=self.config.load()
        for source in config['sources']:
            policy=self.config.effective(config,source)
            fingerprint=hashlib.sha256(json.dumps(source,sort_keys=True).encode()+json.dumps(policy,sort_keys=True).encode()).hexdigest()
            with self.lock:
                row=self.status.setdefault(source['id'],{})
                fresh=source['id'] not in self.fingerprints
                changed=self.fingerprints.get(source['id'])!=fingerprint
                previous=row.get('policy_fingerprint')
                if changed:
                    self.fingerprints[source['id']]=fingerprint
                    if previous!=fingerprint or 'next_at' not in row or (fresh and policy['enabled'] and policy['run_on_start']):
                        row['next_at']=now if policy['enabled'] and policy['run_on_start'] else next_due(policy,now)
                    row['policy_fingerprint']=fingerprint
                if not policy['enabled']:row['next_at']=None
                due=row.get('next_at')
                running=row.get('running',False)
            if due is not None and due<=now and not running:
                self.run([source['id']],automatic=True)
        with self.lock:atomic_json(self.path,self.status)

    def public(self):
        config=self.config.public()
        with self.lock:
            statuses=deepcopy(self.status)
        for source in config['sources']:
            row=statuses.get(source['id'],{})
            if not source['effective_schedule']['enabled']:row['next_at']=None
            source['status']={k:v for k,v in row.items() if k!='policy_fingerprint'}
        return config

    def run(self,ids=None,automatic=False,full=False):
        config=self.config.load()
        wanted=set(ids) if ids is not None else None
        if wanted and not wanted.issubset({s['id'] for s in config['sources']}):raise ValueError('数据源不存在')
        started=[];busy=[]
        for source in config['sources']:
            if wanted is not None and source['id'] not in wanted:continue
            ident=source['id']
            with self.lock:
                row=self.status.setdefault(ident,{})
                if row.get('running') or time.time()-row.get('last_started',0)<10:
                    busy.append(ident);continue
                row.update(running=True,last_started=time.time(),error=None)
                started.append(ident)
            threading.Thread(target=self._work,args=(source,full),daemon=True).start()
        return {'started':started,'busy':busy}

    def _work(self,source,full):
        error=None;result=None
        try:
            if source['type']=='activitywatch':
                from android_sync import sync_source
                result=sync_source(self.store.state,source,full=full)
            else:
                self._apple()
                result={'archived':True}
        except Exception as exc:
            labels={'HTTPError':'远程接口拒绝访问，请检查地址、AW Token 或桶名',
                    'URLError':'无法连接数据源，请检查局域网 / frpc 连接',
                    'TimeoutExpired':'执行超时，请稍后重试','TimeoutError':'连接超时，请检查网络'}
            error=labels.get(type(exc).__name__,'同步失败，请检查数据源与归档权限（'+type(exc).__name__+'）')
        now=time.time()
        try:config=self.config.load();current=next((s for s in config['sources'] if s['id']==source['id']),source);policy=self.config.effective(config,current)
        except Exception:policy={'enabled':False}
        with self.lock:
            row=self.status.setdefault(source['id'],{})
            row.update(running=False,last_finished=now,error=error,result=result)
            if not error:row['last_success']=now
            row['next_at']=next_due(policy,now,last_interval=now)
            atomic_json(self.path,self.status)

    def _apple(self):
        target=f'gui/{os.getuid()}/io.github.tobias-x.screentime-archiver'
        process=subprocess.run(['/bin/launchctl','kickstart',target],capture_output=True,timeout=15)
        if process.returncode:raise RuntimeError('Archiver job unavailable')
        # The archiver must run as its own launchd job to retain its Full Disk Access.
        for _ in range(120):
            time.sleep(.5)
            result=subprocess.run(['/bin/launchctl','print',target],capture_output=True,timeout=5)
            text=result.stdout.decode(errors='replace')
            if 'state = running' in text or re.search(r'\bpid = \d+',text):continue
            code=re.search(r'last exit code = (\d+)',text)
            if code and code[1]=='0':return
            raise RuntimeError('Archiver failed; check Full Disk Access')
        raise TimeoutError('Archiver timeout')
