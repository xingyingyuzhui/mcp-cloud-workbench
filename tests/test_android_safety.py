"""Focused regressions: retention/download race, active task safety, quota gates, traversal."""
import importlib.util,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
class SafetyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();base=Path(self.tmp.name);root=base/'control-root';root.mkdir();store=base/'store';store.mkdir()
  for name in ['jobs','cache','sdk']:(store/name).mkdir()
  (root/'secrets.json').write_text(json.dumps({'upstream':'test-only-token'}))
  with patch.dict(os.environ,{'ANDROID_BUILD_ROOT':str(root),'ANDROID_BUILD_STORE':str(store)}):
   spec=importlib.util.spec_from_file_location('build_server_test',Path(__file__).resolve().parents[1]/'cloud/android-build/server.py');self.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.s)
  self.s.register_project('modbus-android','https://github.com/xingyingyuzhui/modbus_android.git')
 def tearDown(self):self.tmp.cleanup()
 def sample(self,**kw):
  j={'id':'abcdef0123456789','status':'succeeded','created_at':time.time()-20*86400,'finished_at':time.time()-10*86400,'artifacts':[]};j.update(kw)
  d=self.s.jobdir(j);d.mkdir();(d/'artifacts').mkdir();(d/'artifacts'/'test.apk').write_bytes(b'test');(d/'workspace').mkdir();(d/'workspace'/'temp').write_text('temp');(d/'build.log').write_text('log');self.s.job_put(j);return j,d
 def test_active_task_never_cleaned(self):
  j,d=self.sample(status='running');self.assertEqual(self.s.cleanup_plan(),[])
  with self.assertRaises(ValueError):self.s.cleanup_build(j['id'])
  self.assertTrue((d/'workspace').exists())
 def test_download_protects_outputs(self):
  j,d=self.sample(download_until=time.time()+600)
  plan=self.s.cleanup_plan();self.assertNotIn('outputs',[x['kind'] for x in plan]);self.s.cleanup_apply(plan)
  self.assertTrue((d/'artifacts'/'test.apk').exists())
  with self.assertRaises(ValueError):self.s.cleanup_build(j['id'])
 def test_expiry_and_workspace_removed(self):
  j,d=self.sample();result=self.s.cleanup_apply(self.s.cleanup_plan());self.assertGreaterEqual(result['cleaned_items'],2);self.assertFalse(d.exists());self.assertTrue(self.s.job_get(j['id'])['outputs_cleaned'])
 def test_history_prunes_empty_completed_builds(self):
  rows=[]
  for i in range(1000):
   j={'id':format(i,'016x'),'status':'cancelled','created_at':time.time()-86400,'finished_at':time.time()-86400,'artifacts':[]}
   rows.append((j['id'],json.dumps(j)))
  with self.s.db() as c:c.executemany('INSERT INTO jobs VALUES(?,?)',rows)
  with patch.object(self.s,'need_space'):
   new=self.s.submit_build('modbus-android',idempotency_key='bounded-history')
  self.assertEqual(len(self.s.all_jobs()),1000)
  self.assertEqual(self.s.job_get(new['id'])['status'],'queued')
  with self.assertRaises(ValueError):self.s.job_get('0000000000000000')
 def test_storage_gate(self):
  from collections import namedtuple
  Usage=namedtuple('Usage','total used free')
  with patch.object(self.s.shutil,'disk_usage',return_value=Usage(80*2**30,79*2**30,2**30)):
   with self.assertRaises(ValueError):self.s.need_space()
 def test_path_and_repository_validation(self):
  for repository in ['http://169.254.169.254/a','https://github.com/a/b;id','file:///tmp/project']:
   with self.assertRaises(ValueError):self.s.register_project('bad',repository)
  with self.assertRaises(ValueError):self.s.register_project('bad','https://github.com/a/b',subdir='../../etc')
  with self.assertRaises(ValueError):self.s.job_get('../../etc/passwd')
 def test_stale_queued_snapshot_does_not_restart_cancelled_job(self):
  with patch.object(self.s,'need_space'):
   queued=self.s.submit_build('modbus-android',idempotency_key='cancel-race')
  self.s.cancel_build(queued['id'])
  with patch.object(self.s.subprocess,'Popen') as popen:
   self.s.run_job(queued)
  popen.assert_not_called()
  self.assertEqual(self.s.job_get(queued['id'])['status'],'cancelled')
  self.assertFalse((self.s.jobdir(queued)/'workspace').exists())
 def test_cache_cleanup_waits_for_active_job(self):
  self.sample(status='running');cache=self.s.STORE/'cache'/'test';cache.mkdir();os.utime(cache,(0,0));self.assertNotIn('cache',[x['kind'] for x in self.s.cleanup_plan()])
if __name__=='__main__':unittest.main(verbosity=2)
