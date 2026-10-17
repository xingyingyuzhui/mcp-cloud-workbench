"""Offline additive MCPHub configuration merge. Stop Hub before every invocation."""
import argparse,copy,datetime,json,os,subprocess,tempfile
from pathlib import Path

def merge(current,changes):
 out=copy.deepcopy(current)
 servers=changes.get('servers',{})
 groups=changes.get('groups',[])
 if 'group' in changes:groups=groups+[changes['group']]
 keys=changes.get('keys',[])
 for k in keys:
  if not k.get('token') or 'key' in k:raise ValueError('bearerKeys entries require token, never key')
 for section,incoming in [('groups',groups),('bearerKeys',keys)]:
  target=out.setdefault(section,[])
  for item in incoming:
   if not item.get('name'):raise ValueError('Every group/key requires a name')
   old=next((x for x in target if x.get('name')==item['name']),None)
   if old is not None and old!=item:raise ValueError('Refusing to replace existing '+section+' '+item['name'])
   if old is None:target.append(item)
 target=out.setdefault('mcpServers',{})
 for name,value in servers.items():
  if name in target and target[name]!=value:raise ValueError('Refusing to replace existing server '+name)
  target[name]=value
 return out

def stopped(container,settings):
 # Require the named container to exist, and refuse any active container mounting
 # the target directory. A failed Docker query never counts as a stopped Hub.
 state=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
 if state['State']['Running']:raise RuntimeError('Stop MCPHub before editing its on-disk configuration')
 ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
 if ids:
  for item in json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)):
   for mount in item.get('Mounts',[]):
    if settings.resolve().is_relative_to(Path(mount['Source']).resolve()):raise RuntimeError('An active container mounts the settings directory')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',type=Path,required=True);p.add_argument('--changes',type=Path,required=True);p.add_argument('--container',default='mcphub');a=p.parse_args()
 stopped(a.container,a.settings)
 current=json.loads(a.settings.read_text()) if a.settings.exists() else {}
 updated=merge(current,json.loads(a.changes.read_text()))
 a.settings.parent.mkdir(parents=True,exist_ok=True)
 if a.settings.exists():
  backup=a.settings.with_name(a.settings.name+'.backup-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
  fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as f:f.write(a.settings.read_text())
 fd,tmp=tempfile.mkstemp(dir=a.settings.parent,prefix='.mcp-settings-')
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'w') as f:json.dump(updated,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  stopped(a.container,a.settings)
  os.replace(tmp,a.settings)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 print('Added named configuration; existing entries preserved. Restart MCPHub to load it.')
if __name__=='__main__':main()
