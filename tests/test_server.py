from contextlib import closing
import os
import concurrent.futures
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.parse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store, create_server, stamp, union_seconds


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.archive=self.root/'archive.sqlite'
        with closing(sqlite3.connect(self.archive)) as db, db:
            db.executescript('''CREATE TABLE devices(device_id TEXT PRIMARY KEY,name TEXT,platform TEXT,os_build TEXT,source TEXT,first_seen REAL,last_seen REAL);
            CREATE TABLE sessions(device_id TEXT,bundle_id TEXT,start_ts REAL,end_ts REAL,PRIMARY KEY(device_id,bundle_id,start_ts));
            CREATE TABLE runs(run_at REAL,device_id TEXT,source TEXT,sessions_seen INTEGER,sessions_new INTEGER,status TEXT,message TEXT);''')
            db.execute("INSERT INTO devices VALUES ('phone','iPhone','ios','','biome:App.InFocus',0,0)")
            db.execute("INSERT INTO devices VALUES ('mac','Mac','macos','','knowledgeC:/app/usage',0,0)")
            rows=[('phone','com.tencent.xin','2026-11-09T03:30','2026-11-09T04:30'),
                ('phone','tv.danmaku.bilianime','2026-11-09T04:00','2026-11-09T05:00'),
                ('phone','com.tencent.xin','2026-11-10T03:00','2026-11-10T04:30'),
                ('mac','com.google.Chrome','2026-11-09T04:00','2026-11-09T05:00')]
            db.executemany('INSERT INTO sessions VALUES (?,?,?,?)',[(d,b,stamp(a),stamp(z)) for d,b,a,z in rows])
        self.before=self.archive.read_bytes()
        self.store=Store(self.archive,self.root/'state')

    def tearDown(self):
        self.temp.cleanup()

    def params(self,**kw):
        return dict(start='2026-11-08T04:00',end='2026-11-11T04:00',devices='phone',group='day',**kw)

    def test_life_day_split_overlap_and_special_window(self):
        s=self.store.stats(self.params())
        self.assertEqual([d['seconds'] for d in s['days']],[1800,9000,1800])
        self.assertEqual(s['total'],12600)
        self.assertEqual(s['active'],10800)
        self.assertEqual(sum(d['special_seconds'] for d in s['days']),12600)
        self.assertEqual(s['days'][1]['first'],stamp('2026-11-09T04:00'))
        self.assertEqual(s['days'][1]['last'],stamp('2026-11-10T04:00'))

    def test_exact_range_clips_and_is_end_exclusive(self):
        s=self.store.stats(dict(start='2026-11-09T04:15',end='2026-11-09T04:45',devices='phone'))
        self.assertEqual(s['total'],2700)
        self.assertEqual(s['active'],1800)
        sessions=self.store.timeline(dict(start='2026-11-09T04:30',end='2026-11-09T05:00',devices='phone'))['items']
        self.assertEqual(len(sessions),1)
        self.assertEqual(sessions[0]['bundle'],'tv.danmaku.bilianime')

    def test_week_aggregation_and_conservation(self):
        p=self.params();p['group']='week'
        s=self.store.stats(p)
        self.assertEqual([b['date'] for b in s['buckets']],['2026-11-02','2026-11-09'])
        self.assertEqual(sum(b['seconds'] for b in s['buckets']),s['total'])
        self.assertEqual(sum(c['seconds'] for c in s['categories']),s['total'])
        self.assertAlmostEqual(sum(a['share'] for a in s['apps']),1)

    def test_rename_and_category_persist_without_touching_archive(self):
        self.store.save('app',{'bundle':'com.tencent.xin','name':'手机微信','category':'work'})
        s=Store(self.archive,self.root/'state').stats(self.params())
        a=next(a for a in s['apps'] if a['bundle']=='com.tencent.xin')
        self.assertEqual((a['name'],a['category']),('手机微信','work'))
        self.assertEqual(self.before,self.archive.read_bytes())

    def test_device_filter_and_union(self):
        p=self.params();p['devices']='mac'
        self.assertEqual(self.store.stats(p)['total'],3600)
        p['devices']='phone,mac'
        self.assertEqual(self.store.stats(p)['active'],14400)
        self.assertEqual(union_seconds([(0,3),(2,4),(10,12)]),6)

    def test_settings_repartition_without_changing_total(self):
        self.store.save('settings',{'boundary':5,'special_start':3,'special_end':4})
        s=self.store.stats(self.params())
        self.assertEqual(s['boundary'],5)
        self.assertEqual(s['total'],12600)
        self.assertEqual(sum(d['special_seconds'] for d in s['days']),5400)

    def test_device_timeline_long_range_keeps_exact_clipping(self):
        q=dict(start='2026-11-08T04:00',end='2026-11-12T04:00')
        with self.assertRaises(ValueError):
            self.store.timeline(q)
        result=self.store.timeline(q,max_days=366)
        self.assertEqual(len(result['items']),4)
        self.assertEqual({i['device'] for i in result['items']},{'phone','mac'})
        q=dict(start='2026-11-09T04:15',end='2026-11-09T04:45')
        result=self.store.timeline(q,max_days=366)
        self.assertEqual(len(result['items']),3)
        for item in result['items']:
            self.assertGreaterEqual(item['start'],stamp(q['start']))
            self.assertLessEqual(item['end'],stamp(q['end']))

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.save('settings',{'boundary':4,'special_start':5,'special_end':3})
        with self.assertRaises(ValueError):
            self.store.save('category',{'name':'x','color':'red; bad'})
        with self.assertRaises(ValueError):
            self.store.stats(dict(start='2020-01-01',end='2026-11-10'))
        with self.assertRaises(ValueError):
            self.store.save('app',{'bundle':'x','name':'x','category':'missing'})

    def test_http_auth_csrf_and_private_paths(self):
        srv=create_server(port=0,archive=self.archive,state=self.root/'http-state')
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        port=srv.server_address[1]
        def request(method,path,body=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',port)
            c.request(method,path,body,headers or {})
            r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
        try:
            for path in ['/api/meta','/api/stats','/api/timeline','/api/device-timeline','/app.js','/style.css','/../../server.py']:
                self.assertEqual(request('GET',path)[0],401,path)
            self.assertEqual(request('GET','/?token=wrong')[0],401)
            auth={'Authorization':'Bearer '+srv.token}
            self.assertEqual(request('POST','/api/app',json.dumps({'bundle':'x','name':'x','category':'work'}),{'Content-Type':'application/json'})[0],401)
            self.assertEqual(request('POST','/api/app',json.dumps({'bundle':'x','name':'x','category':'work'}),dict(auth,Origin='https://client.test'))[0],200)
            self.assertEqual(request('GET','/api/meta',headers=dict(auth,Host='evil.test'))[0],403)
            status,headers,body=request('GET','/?token='+srv.token)
            self.assertEqual(status,303)
            self.assertEqual(headers['Location'],'/')
            status,shared_headers,_=request('GET','/?token='+srv.token+'&view=timeline&day=2026-11-09')
            self.assertEqual(status,303)
            self.assertEqual(shared_headers['Location'],'/?view=timeline&day=2026-11-09')
            self.assertNotIn(srv.token,shared_headers['Location'])
            login_page=request('GET','/?view=timeline&day=2026-11-09')[2].decode()
            self.assertIn('action="/login?view=timeline&amp;day=2026-11-09"',login_page)
            status,login_headers,_=request('POST','/login?view=apps&appq=Chrome',urllib.parse.urlencode({'token':srv.token}),{'Origin':'null'})
            self.assertEqual(status,303)
            self.assertEqual(login_headers['Location'],'/?view=apps&appq=Chrome')

            self.assertIn('HttpOnly',headers['Set-Cookie'])
            self.assertIn('SameSite=Strict',headers['Set-Cookie'])
            cookie={'Cookie':headers['Set-Cookie'].split(';')[0]}
            self.assertEqual(request('POST','/api/app','{}',dict(cookie,Origin='https://evil.test'))[0],403)
            self.assertEqual(request('POST','/api/app','{}',{'Origin':'https://client.test'})[0],401)
            status,cors,_=request('OPTIONS','/api/app',headers={'Origin':'https://client.test','Access-Control-Request-Headers':'Authorization,Content-Type'})
            self.assertEqual(status,204)
            self.assertEqual(cors['Access-Control-Allow-Origin'],'*')
            self.assertIn('Authorization',cors['Access-Control-Allow-Headers'])
            self.assertNotIn('Access-Control-Allow-Credentials',cors)
            for origin in ('null','http://127.0.0.1:'+str(port)):
                self.assertEqual(request('POST','/login',urllib.parse.urlencode({'token':srv.token}),{'Origin':origin,'Content-Type':'application/x-www-form-urlencoded'})[0],303)
            self.assertEqual(request('POST','/login','token=wrong',{'Origin':'null'})[0],401)
            self.assertEqual(request('GET','/api/meta',headers=cookie)[0],200)
            self.assertEqual(request('GET','/',headers=cookie)[0],200)
            self.assertEqual(request('GET','/../../server.py',headers=cookie)[0],404)
            self.assertEqual(request('GET','/api/stats',headers=cookie)[0],400)
            self.assertEqual(request('POST','/api/logout','{}',cookie)[0],200)
            if os.name=='posix':
                self.assertEqual((self.root/'http-state/access-token').stat().st_mode & 0o777,0o600)
            self.assertEqual(self.before,self.archive.read_bytes())
        finally:
            srv.shutdown();srv.server_close();t.join()


if __name__=='__main__':
    unittest.main()
