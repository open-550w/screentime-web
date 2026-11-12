import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from android_sync import import_events, SCHEMA
from server import Store


class AndroidSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.apple = self.root / 'apple.sqlite'
        with sqlite3.connect(self.apple) as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO devices VALUES ('iphone','iPhone','ios','','biome',0,0)")
            db.execute("INSERT INTO sessions VALUES ('iphone','com.tencent.xin',1794254400,1794254460)")
        self.original = self.apple.read_bytes()
        self.store = Store(self.apple, self.root)
        self.event = {'id': 1, 'timestamp': '2026-11-10T01:00:00Z', 'duration': 60,
                      'data': {'package': 'com.tencent.xin', 'app': '微信'}}

    def tearDown(self):
        self.temp.cleanup()

    def test_repeat_correction_platform_isolation_and_preserved_customization(self):
        first = import_events(self.root, 'android-phone', [self.event])
        self.assertEqual(first['new'], 1)
        self.store.save('app', {'bundle': 'android:com.tencent.xin', 'name': '我的 Android 微信', 'category': 'work'})
        self.event['duration'] = 120
        self.assertEqual(import_events(self.root, 'android-phone', [self.event])['new'], 0)
        meta = self.store.meta()
        self.assertEqual(len(meta['devices']), 2)
        app = next(a for a in meta['apps'] if a['bundle'] == 'android:com.tencent.xin')
        self.assertEqual((app['name'], app['category']), ('我的 Android 微信', 'work'))
        stats = self.store.stats({'start': '2026-11-10T00:00+08:00', 'end': '2026-11-11T00:00+08:00', 'devices': 'android-phone'})
        self.assertEqual(stats['total'], 120)
        self.assertEqual(stats['active'], 120)
        self.assertEqual(self.original, self.apple.read_bytes())

    def test_invalid_batch_preserves_previous_archive(self):
        import_events(self.root, 'android-phone', [self.event])
        previous = (self.root / 'android.sqlite').read_bytes()
        broken = dict(self.event, id=2, duration=float('inf'))
        with self.assertRaises(ValueError):
            import_events(self.root, 'android-phone', [self.event, broken])
        self.assertEqual(previous, (self.root / 'android.sqlite').read_bytes())


if __name__ == '__main__':
    unittest.main()
