import os
import datetime as dt
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from server import Store,create_server,stamp
from android_sync import import_events,sync_source,discover
from config_store import ConfigStore,DEFAULT_POLICY,atomic_json,next_due,validate_policy
from export_api import Exporter
from sync_manager import SyncManager


def event(ident,start,duration=3600,package='example.a'):
    return {'id':ident,'timestamp':start,'duration':duration,'data':{'package':package,'app':'Demo','classname':'MainActivity'}}


class OpenSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=self.root/'state';self.archive=self.root/'absent-apple.sqlite'
        self.store=Store(self.archive,self.state)
        import_events(self.state,'android-demo',[event(1,'2026-01-01T08:00:00+08:00'),event(2,'2026-01-01T09:00:00+08:00'),event(3,'2026-01-01T10:00:00+08:00')],device_name='Demo phone')
        self.query={'start':'2026-01-01T09:30:00+08:00','end':'2026-01-01T10:30:00+08:00'}

    def tearDown(self):self.temp.cleanup()

    def test_android_only_startup_and_payload_preserved(self):
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.store.meta()['devices'][0]['name'],'Demo phone')
        export=Exporter(self.store,'test-secret')
        raw=export.export(dict(self.query,format='raw',limit='all'))
        self.assertEqual(raw['returned_count'],2)
        self.assertEqual(raw['records'][0]['start_ts'],stamp('2026-01-01T09:00'))
        self.assertEqual(raw['records'][0]['source_events'][0]['event']['data']['classname'],'MainActivity')
        enriched=export.export(dict(self.query,format='enriched',limit='all'))
        self.assertEqual([r['duration_seconds'] for r in enriched['records']],[1800,1800])
        self.assertFalse(self.archive.exists())

    def test_export_snapshot_stable_across_new_sync(self):
        export=Exporter(self.store,'test-secret')
        first=export.export(dict(self.query,limit='1'))
        import_events(self.state,'android-demo',[event(99,'2026-01-01T09:45:00+08:00',60)])
        second=export.export({'cursor':first['next_cursor'],'limit':'1'})
        self.assertEqual(second['total_count'],2)
        self.assertEqual(second['snapshot_id'],first['snapshot_id'])
        self.assertTrue(second['complete'])
        self.assertNotEqual(first['records'][0]['start_ts'],second['records'][0]['start_ts'])
        with self.assertRaises(ValueError):export.export({'cursor':first['next_cursor']+'BAD'})
        with self.assertRaises(ValueError):export.export(dict(self.query,devices='unknown'))
        self.assertEqual(export.export(dict(self.query,limit='all'))['total_count'],3)

    def test_shared_and_independent_policies_and_secret_masking(self):
        config=self.store.manager.config
        ident=config.save_source({'name':'Phone','url':'http://192.168.1.20:5600','token':'private-test-secret','schedule_mode':'inherit'})
        config.save_shared(dict(DEFAULT_POLICY,enabled=False))
        source=config.public()['sources'][0]
        self.assertFalse(source['effective_schedule']['enabled'])
        self.assertTrue(source['has_token'])
        self.assertNotIn('private-test-secret',json.dumps(config.public()))
        config.save_source(dict(config.source(ident),schedule_mode='independent',schedule=dict(DEFAULT_POLICY,enabled=True,interval_minutes=17),token=''))
        self.assertTrue(config.public()['sources'][0]['effective_schedule']['enabled'])
        self.assertEqual(config.source(ident)['token'],'private-test-secret')
        if os.name=='posix':
            self.assertEqual(config.path.stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError):config.save_source({'name':'x','url':'file:///tmp/data'})
        with self.assertRaises(ValueError):validate_policy(dict(DEFAULT_POLICY,mode='daily',times=['25:00']))

    def test_unicode_config_status_and_snapshot_roundtrip(self):
        name='手机与电脑 📱'
        config=self.store.manager.config
        ident=config.save_source({'name':name,'url':'http://127.0.0.1:5600'})
        self.assertEqual(ConfigStore(self.state,self.archive).source(ident)['name'],name)
        atomic_json(self.store.manager.path,{ident:{'error':name}})
        self.assertEqual(SyncManager(self.store).status[ident]['error'],name)
        self.store.save('app',{'bundle':'android:example.a','name':name,'category':'work'})
        export=Exporter(self.store,'test-secret')
        first=export.export(dict(self.query,limit='1'))
        second=export.export({'cursor':first['next_cursor'],'limit':'1'})
        self.assertEqual(first['records'][0]['name'],name)
        self.assertEqual(second['records'][0]['name'],name)

    def test_scheduler_fixed_times_combination_and_disable(self):
        now=stamp('2026-01-01T11:00:00+08:00')
        daily=dict(DEFAULT_POLICY,mode='daily',times=['12:30'])
        self.assertEqual(next_due(daily,now),stamp('2026-01-01T12:30:00+08:00'))
        self.assertEqual(next_due(dict(daily,mode='combined',interval_minutes=30),now),now+1800)
        self.assertIsNone(next_due(dict(daily,enabled=False),now))
        ident=self.store.manager.config.save_source({'name':'Phone','url':'http://127.0.0.1:1','schedule_mode':'independent','schedule':dict(DEFAULT_POLICY,interval_minutes=5)})
        manager=self.store.manager
        with patch.object(manager,'run') as run:
            manager.tick(now);run.assert_not_called()
            manager.tick(now+301);run.assert_called_once_with([ident],automatic=True)
        cfg=manager.config.source(ident);cfg['schedule']['enabled']=False;manager.config.save_source(cfg)
        with patch.object(manager,'run') as run:
            manager.tick(now+10000);run.assert_not_called()
        with patch.object(manager,'_work') as work:
            manager.run([ident])
            for _ in range(20):
                if work.called:break
                time.sleep(.01)
            work.assert_called_once()  # Manual execution works while automatic is disabled.

    def test_run_on_start_and_missed_run_resume_once(self):
        ident=self.store.manager.config.save_source({'name':'Phone','url':'http://127.0.0.1:1','schedule_mode':'independent','schedule':dict(DEFAULT_POLICY,run_on_start=True)})
        now=stamp('2026-01-01T11:00:00+08:00')
        with patch.object(self.store.manager,'run') as run:
            self.store.manager.tick(now)
            run.assert_called_once_with([ident],automatic=True)
        # Persist a future run, then recreate the service: explicit startup policy still runs.
        self.store.manager.status[ident]['next_at']=now+99999
        atomic_json(self.store.manager.path,self.store.manager.status)
        restarted=SyncManager(self.store)
        with patch.object(restarted,'run') as run:
            restarted.tick(now+1)
            run.assert_called_once_with([ident],automatic=True)

    def test_legacy_migration_keeps_credentials_and_interval(self):
        state=self.root/'legacy';state.mkdir()
        atomic_json(state/'android-source.json',{'url':'http://192.168.1.2:7075','token':'old-secret'})
        config=ConfigStore(state,self.archive)
        source=config.source('android-legacy')
        self.assertEqual(source['token'],'old-secret')
        self.assertEqual(source['schedule']['interval_minutes'],5)
        self.assertEqual(source['schedule_mode'],'independent')
        self.assertTrue((state/'android-source.json').exists())

    def test_aw_discovery_sync_is_generic_idempotent_and_no_redirect(self):
        requests=[]
        class Mock(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith('/redirect'):
                    self.send_response(302);self.send_header('Location','/api/0/info');self.end_headers();return
                if self.path=='/api/0/info':data={'device_id':'any-phone','version':'test'}
                elif self.path=='/api/0/buckets/':data={'aw-watcher-android-demo':{'hostname':'demo_phone','type':'currentwindow'},'aw-watcher-web':{'hostname':'demo_phone','type':'web.tab.current'}}
                else:data=[event(10,'2026-01-02T09:00:00+08:00')]
                body=json.dumps(data).encode();self.send_response(200);self.end_headers();self.wfile.write(body)
        srv=ThreadingHTTPServer(('127.0.0.1',0),Mock);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        try:
            source={'id':'test-source','name':'Any phone','url':f'http://127.0.0.1:{srv.server_port}','token':'fake','bucket':'aw-watcher-android-demo'}
            self.assertEqual(len(discover(source)[1]),1)
            first=sync_source(self.state,source);second=sync_source(self.state,source)
            self.assertEqual(first['device'],second['device'])
            self.assertEqual(second['new'],0)
            self.assertTrue(any('start=' in p for p in requests))
            before=len(requests)
            with self.assertRaises(urllib.error.HTTPError):discover(dict(source,url=source['url']+'/redirect'))
            self.assertEqual(len(requests),before+1)
        finally:srv.shutdown();srv.server_close();t.join()

    def test_export_and_config_http_auth(self):
        srv=create_server(port=0,archive=self.archive,state=self.state)
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        def request(path,auth=False):
            c=http.client.HTTPConnection('127.0.0.1',srv.server_port)
            c.request('GET',path,headers={'Authorization':'Bearer '+srv.token} if auth else {})
            r=c.getresponse();out=r.status,r.read();c.close();return out
        try:
            query=urllib.parse.urlencode(dict(self.query,limit='all'))
            for path in ('/api/export?'+query,'/api/sync-config'):
                self.assertEqual(request(path)[0],401)
                self.assertEqual(request(path,True)[0],200)
            self.assertEqual(json.loads(request('/api/export?'+query,True)[1])['returned_count'],2)
        finally:srv.shutdown();srv.server_close();t.join()


if __name__=='__main__':unittest.main()
