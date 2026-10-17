import contextlib,importlib.util,io,json,os,plistlib,stat,sys,tempfile,unittest
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,REPO/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
init=module('config_init','scripts/init_config.py');tunnel=module('tunnel_test','mac/tunnel.py');launch=module('launch_test','mac/render_launchagents.py')
class ConfigTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.config=json.loads((REPO/'config/workbench.example.json').read_text())
 def tearDown(self):self.tmp.cleanup()
 def generate(self):
  with contextlib.redirect_stdout(io.StringIO()):return init.generate(self.config,self.path/'runtime')
 def test_private_runtime_and_stable_keys(self):
  root=self.generate();secret=json.loads((root/'secrets.json').read_text());self.generate();self.assertEqual(secret,json.loads((root/'secrets.json').read_text()))
  self.assertEqual(stat.S_IMODE((root/'secrets.json').stat().st_mode),0o600)
  self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o700)
  import base64
  self.assertEqual(len(base64.b64decode(secret['credential_encryption_key'])),32)
  self.assertIn('MCPHUB_GATEWAY=172.18.0.1',(root/'cloud.env').read_text());self.assertIn('MCPHUB_SUBNET=172.18.0.0/16',(root/'mcphub.env').read_text())
  changes=json.loads((root/'hub-changes.json').read_text());self.assertEqual(set(changes['servers']),{'android-build'});self.assertEqual(changes['keys'][0]['allowedServers'],['android-build']);self.assertIn('token',changes['keys'][0])
 def test_mac_group_and_android_token_reuse(self):
  token='test-only-android-bearer-token-0123456789';f=self.path/'android-bearer';f.write_text(token)
  for e in self.config['mac'].values():e['enabled']=True
  self.config['mac']['android']['token_file']=str(f)
  root=self.generate();changes=json.loads((root/'hub-changes.json').read_text());self.assertEqual(len(changes['servers']),4)
  self.assertEqual(changes['servers']['mac-android']['headers']['Authorization'],'Bearer '+token)
  self.assertEqual(len(changes['groups'][0]['servers']),3)
 def test_external_comfy_rejected(self):
  self.config['mac']['comfyui'].update(enabled=True,upstream_url='http://example.com/mcp')
  with self.assertRaises(ValueError):self.generate()
 def test_duplicate_port_rejected(self):
  for name in ['blender','comfyui']:self.config['mac'][name]['enabled']=True
  self.config['mac']['comfyui']['local_port']=18190
  with self.assertRaises(ValueError):self.generate()
 def test_public_docker_subnet_rejected(self):
  self.config['cloud'].update(docker_gateway='203.0.113.1',docker_subnet='203.0.113.0/24')
  with self.assertRaises(ValueError):self.generate()
 def test_strict_ssh_commands(self):
  self.config['mac']['blender']['enabled']=True;root=self.generate();cfg=json.loads((root/'mac-bridge/tunnel.json').read_text())
  cmd=tunnel.command(cfg,'reverse');self.assertIn('StrictHostKeyChecking=yes',cmd);self.assertIn('172.18.0.1:28190:127.0.0.1:18190',cmd)
  cfg['host']='-oProxyCommand=bad'
  with self.assertRaises(ValueError):tunnel.command(cfg,'reverse')
 def test_launchagents_render_only_and_remove_stale(self):
  self.config['mac']['blender']['enabled']=True;root=self.generate();out=root/'plists'
  with contextlib.redirect_stdout(io.StringIO()):jobs=launch.render(root/'mac-bridge',sys.executable,out)
  self.assertEqual(len(jobs),2)
  files=list(out.glob('*.plist'));self.assertEqual(len(files),2)
  for f in files:
   d=plistlib.loads(f.read_bytes());self.assertTrue(d['KeepAlive']);self.assertEqual(d['ProgramArguments'][0],str(Path(sys.executable).resolve()))
  self.config['mac']['blender']['enabled']=False;root=self.generate()
  with contextlib.redirect_stdout(io.StringIO()):launch.render(root/'mac-bridge',sys.executable,out)
  self.assertEqual(list(out.glob('*.plist')),[])
if __name__=='__main__':unittest.main()
