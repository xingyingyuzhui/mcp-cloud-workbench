#!/usr/bin/env python3
"""Render launchd plists to private runtime only; does not install or start services."""
import argparse,json,os,plistlib
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def render(runtime,python,output,with_forward=False):
 runtime=Path(runtime).resolve();python=Path(python).resolve();output=Path(output).resolve()
 if not python.is_file():raise ValueError('Python interpreter does not exist; create the venv first')
 output.mkdir(parents=True,exist_ok=True);output.chmod(0o700)
 logs=runtime/'logs';logs.mkdir(exist_ok=True);logs.chmod(0o700)
 tunnel=json.loads((runtime/'tunnel.json').read_text());names={f['name'] for f in tunnel['forwards']}
 jobs={}
 for name in ['blender','comfyui']:
  if name in names:jobs[name+'-http']=[str(python),str(REPO/'mac'/f'{name}_http.py'),'--runtime',str(runtime)]
 if names:jobs['mac-tunnel']=[str(python),str(REPO/'mac/tunnel.py'),'reverse','--runtime',str(runtime)]
 if with_forward:jobs['hub-forward']=[str(python),str(REPO/'mac/tunnel.py'),'forward','--runtime',str(runtime)]
 expected={'local.mcp-cloud-workbench.'+n+'.plist' for n in jobs}
 for old in output.glob('local.mcp-cloud-workbench.*.plist'):
  if old.name not in expected:old.unlink()
 for name,args in jobs.items():
  label='local.mcp-cloud-workbench.'+name
  d={'Label':label,'ProgramArguments':args,'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,'WorkingDirectory':str(REPO),'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin:/usr/sbin:/sbin')},'StandardOutPath':str(logs/(label+'.out.log')),'StandardErrorPath':str(logs/(label+'.err.log'))}
  path=output/(label+'.plist');path.write_bytes(plistlib.dumps(d));path.chmod(0o600)
 print('Rendered',len(jobs),'launch agents into',output,'(not installed)')
 return jobs
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',type=Path,default=REPO/'runtime/mac-bridge');p.add_argument('--python',type=Path,default=REPO/'.venv/bin/python');p.add_argument('--output',type=Path,default=REPO/'runtime/launchagents');p.add_argument('--with-forward',action='store_true');a=p.parse_args();render(a.runtime,a.python,a.output,a.with_forward)
