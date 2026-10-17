"""Single-worker Android build MCP. Control state never mounted into builds."""
import base64,binascii,hashlib,json,os,re,shutil,sqlite3,subprocess,tarfile,threading,time,uuid
from pathlib import Path
from contextlib import contextmanager
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
ROOT=Path(os.environ.get('ANDROID_BUILD_ROOT','/opt/android-build'))
STORE=Path(os.environ.get('ANDROID_BUILD_STORE','/srv/android-build'))
CONTROL=ROOT/'control';CONTROL.mkdir(exist_ok=True)
UPLOADS=CONTROL/'source-uploads';UPLOADS.mkdir(mode=0o700,exist_ok=True)
LOCK=threading.RLock(); ACTIVE=None
DEFAULT={'artifact_days':7,'failed_workspace_hours':24,'cache_days':14,'cache_max_gib':20,'host_free_min_gib':20,'store_free_min_gib':2,'job_timeout_minutes':30}
POLICY=CONTROL/'policy.json';PROJECTS=CONTROL/'projects.json'
def save(p,d):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2));t.chmod(0o600);t.replace(p)
if not POLICY.exists():save(POLICY,DEFAULT)
if not PROJECTS.exists():save(PROJECTS,{})
@contextmanager
def db():
 c=sqlite3.connect(CONTROL/'jobs.sqlite',timeout=30);c.row_factory=sqlite3.Row
 try:
  with c:yield c
 finally:c.close()
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
def all_jobs():
 with db() as c:return [json.loads(r['data']) for r in c.execute('SELECT data FROM jobs ORDER BY rowid')]
def job_get(i):
 if not re.fullmatch('[0-9a-f]{16}',i):raise ValueError('Invalid build ID')
 with db() as c:r=c.execute('SELECT data FROM jobs WHERE id=?',(i,)).fetchone()
 if not r:raise ValueError('Build not found')
 return json.loads(r['data'])
def job_put(j):
 with db() as c:c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(j['id'],json.dumps(j)))
def policy():return json.loads(POLICY.read_text())
def project(i):
 p=json.loads(PROJECTS.read_text())
 if i not in p:raise ValueError('Unknown project. Register a public GitHub repository first.')
 return p[i]
def upload_get(i):
 if not re.fullmatch('[0-9a-f]{32}',i):raise ValueError('Invalid upload ID')
 p=UPLOADS/(i+'.json')
 if not p.is_file():raise ValueError('Source upload not found or expired')
 return json.loads(p.read_text())
def upload_put(u):
 p=UPLOADS/(u['id']+'.json');t=p.with_suffix('.tmp');t.write_text(json.dumps(u));t.chmod(0o600);t.replace(p)
def upload_file(u):return STORE/'uploads'/(u['id']+'.tar.gz')
def validate_source_archive(path,expected_sha):
 with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 if digest!=expected_sha:raise ValueError('Source archive SHA256 mismatch')
 files=0;expanded=0;has_wrapper=False
 try:
  with tarfile.open(path,'r:gz') as archive:
   for member in archive:
    name=member.name
    parts=Path(name).parts
    if not name or name.startswith('/') or '\\' in name or '..' in parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):raise ValueError('Archive contains an unsafe path or unsupported file type')
    if len(name)>1024:raise ValueError('Archive path too long')
    if member.isfile():
     files+=1;expanded+=member.size
     if files>20000 or expanded>2*2**30:raise ValueError('Archive exceeds file count or expanded-size limit')
     if Path(name).name=='gradlew':has_wrapper=True
 except (tarfile.TarError,OSError) as e:raise ValueError('Invalid .tar.gz source archive') from e
 if not has_wrapper:raise ValueError('Gradle wrapper (gradlew) not found in source archive')
 return {'sha256':digest,'files':files,'expanded_bytes':expanded}
def du(p):
 if not p.exists():return 0
 r=subprocess.run(['du','-sx','--block-size=1','--',str(p)],capture_output=True,text=True,timeout=60)
 return int(r.stdout.split()[0]) if r.stdout else 0
def space():
 h=shutil.disk_usage('/');s=shutil.disk_usage(STORE);p=policy()
 return {'host_free_bytes':h.free,'store_free_bytes':s.free,'store_total_bytes':s.total,'store_used_bytes':s.used,'can_build':h.free>=p['host_free_min_gib']*2**30 and s.free>=p['store_free_min_gib']*2**30,'policy':p,'hard_limit':'40 GiB dedicated ext4 filesystem on the existing boot volume'}
def need_space():
 if not space()['can_build']:raise ValueError('Storage threshold reached; clean data before submitting more builds')
def jobdir(j):return STORE/'jobs'/j['id']
def rm(p):
 if p.is_symlink():p.unlink()
 elif p.is_dir():shutil.rmtree(p)
 elif p.exists():p.unlink()
def cache_path(j):return STORE/'cache'/j['cache_key']
def cleanup_plan():
 now=time.time();p=policy();plan=[];jobs=all_jobs();running=any(j['status'] in ['running','cancel_requested'] for j in jobs)
 for j in jobs:
  if j['status'] in ['queued','running','cancel_requested']:continue
  age=now-j.get('finished_at',j['created_at']);d=jobdir(j)
  if ((d/'workspace').exists() or (d/'source.tar.gz').exists()) and age>=p['failed_workspace_hours']*3600:plan.append({'build_id':j['id'],'kind':'workspace','bytes':du(d/'workspace')+du(d/'source.tar.gz')})
  if j.get('download_until',0)<=now and age>=p['artifact_days']*86400 and any((d/n).exists() for n in ['artifacts','build.log']):plan.append({'build_id':j['id'],'kind':'outputs','bytes':du(d/'artifacts')+du(d/'build.log')})
 for meta in UPLOADS.glob('*.json'):
  try:
   u=json.loads(meta.read_text());f=upload_file(u)
   if u.get('expires_at',0)<=now or now-u.get('created_at',now)>=7200:plan.append({'kind':'source_upload','upload_id':u['id'],'bytes':f.stat().st_size if f.exists() else 0})
  except (OSError,ValueError,KeyError):continue
 if not running:
  caches=sorted((x for x in (STORE/'cache').iterdir() if x.is_dir()),key=lambda x:x.stat().st_mtime)
  total=sum(du(x) for x in caches)
  for x in caches:
   n=du(x)
   if now-x.stat().st_mtime>=p['cache_days']*86400 or total>p['cache_max_gib']*2**30:
    plan.append({'kind':'cache','cache':x.name,'bytes':n});total-=n
 return plan
def trim_store():
 if os.path.ismount(STORE):
  try:subprocess.run(['fstrim','--minimum','1048576',str(STORE)],capture_output=True,timeout=30)
  except (OSError,subprocess.TimeoutExpired) as e:print('trim deferred',str(e),flush=True)
def cleanup_apply(plan):
 count=0;before=shutil.disk_usage(STORE).used
 for item in plan:
  if item['kind']=='cache':rm(STORE/'cache'/item['cache'])
  elif item['kind']=='source_upload':
   rm(UPLOADS/(item['upload_id']+'.json'));rm(STORE/'uploads'/(item['upload_id']+'.tar.gz'))
  else:
   j=job_get(item['build_id'])
   if j['status'] in ['queued','running','cancel_requested']:continue
   d=jobdir(j)
   if item['kind']=='workspace':rm(d/'workspace');rm(d/'source.tar.gz');j['workspace_cleaned']=True;j['source_cleaned']=True
   else:
    rm(d/'artifacts');rm(d/'build.log');j['outputs_cleaned']=True
   job_put(j)
   if d.exists() and not any(d.iterdir()):d.rmdir()
  count+=1
 released=max(0,before-shutil.disk_usage(STORE).used)
 if released:trim_store()
 return {'cleaned_items':count,'released_bytes':released}
def docker(*args,**kwargs):return subprocess.run(['docker',*args],**kwargs)
def stop_container(name):
 docker('rm','-f',name,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
def capture(proc,path):
 written=0;limit=20*2**20
 with path.open('wb') as f:
  while data:=proc.stdout.read1(16384):
   if written<limit:
    chunk=data[:limit-written];f.write(chunk);f.flush();written+=len(chunk)
  if written>=limit:f.write(b'\n[Log capped at 20 MiB; remaining output discarded]\n')
def collect(j):
 d=jobdir(j);w=d/'workspace';a=d/'artifacts';a.mkdir(exist_ok=True);items=[];total=0
 # Glob bounded by actual files and copy only regular, non-symlink files within workspace.
 for current,dirs,files in os.walk(w,followlinks=False):
  dirs[:]=[n for n in dirs if n not in ['.git','.gradle','node_modules'] and not (Path(current)/n).is_symlink()]
  for n in files:
   f=Path(current)/n;rel=f.relative_to(w);parts=rel.parts
   if f.is_symlink() or not f.is_file():continue
   artifact=n.endswith(('.apk','.aab')) and 'outputs' in parts
   report='reports' in parts or 'test-results' in parts
   if not (artifact or report):continue
   if not f.resolve().is_relative_to(w.resolve()):continue
   size=f.stat().st_size
   if len(items)>=400 or total+size>2**30 or len(str(rel))>1024:
    j['artifacts_truncated']=True;continue
   dest=a/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
   with dest.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
   items.append({'path':str(rel),'size_bytes':size,'sha256':digest});total+=size
 j['artifacts']=items
 commit=w/'.build-commit'
 if commit.is_file() and not commit.is_symlink():
  value=commit.read_text()[:100].strip()
  if re.fullmatch('[a-f0-9]{40}',value):j['commit']=value
 return j
def run_job(j):
 global ACTIVE
 name='android-build-'+j['id'];d=jobdir(j);w=d/'workspace';cache=cache_path(j)
 with LOCK:
  # A queued snapshot can have been cancelled since worker selected it.
  j=job_get(j['id'])
  if j['status']!='queued':return
  need_space();w.mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True)
  os.chown(w,10001,10001);os.chown(cache,10001,10001)
  j['status']='running';j['started_at']=time.time();job_put(j);ACTIVE=j['id']
  inp=CONTROL/(j['id']+'.json');save(inp,{k:j[k] for k in ['repository','ref','subdir','tasks','source_archive','module'] if k in j});inp.chmod(0o644)
 args=['run','--rm','--name',name,'--label','local.android-build.managed=true','--network','android-build-net','--dns','1.1.1.1','--dns','8.8.8.8','--user','10001:10001','--cpus','2','--memory','8g','--memory-swap','8g','--pids-limit','512','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=1g','--log-driver','none','-v',str(w)+':/workspace','-v',str(cache)+':/gradle','-v',str(STORE/'sdk')+':/opt/android-sdk:ro','-v',str(inp)+':/job-input.json:ro','-v',str(ROOT/'run_job.py')+':/run_job.py:ro']
 if j.get('source_archive'):args+=['-v',str(d/'source.tar.gz')+':/source.tar.gz:ro']
 args += [(ROOT/'image-id').read_text().strip(),'python3','/run_job.py']
 proc=None;thread=None;reason=None
 try:
  proc=subprocess.Popen(['docker',*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  thread=threading.Thread(target=capture,args=(proc,d/'build.log'),daemon=True);thread.start()
  while proc.poll() is None:
   time.sleep(2)
   with LOCK:requested=job_get(j['id'])['status']=='cancel_requested'
   if requested:reason='cancelled'
   elif time.time()-j['started_at']>policy()['job_timeout_minutes']*60:reason='timeout'
   elif not space()['can_build']:reason='storage_threshold'
   if reason:stop_container(name);break
  proc.wait(timeout=30)
  if thread:thread.join(10)
  with LOCK:
   j=job_get(j['id']);j['exit_code']=proc.returncode;j['status']=reason or ('succeeded' if proc.returncode==0 else 'failed');collect(j)
 except Exception as e:
  stop_container(name)
  if proc:
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
  if thread:thread.join(10)
  j['status']='failed';j['error']=str(e)[:2000]
 finally:
  with LOCK:
   # Do not follow source-controlled symlinks on host cleanup.
   j['finished_at']=time.time();job_put(j);inp.unlink(missing_ok=True);ACTIVE=None
   if j['status'] in ['succeeded','cancelled','timeout','storage_threshold']:
    rm(w);rm(d/'source.tar.gz');j['workspace_cleaned']=True;j['source_cleaned']=True;job_put(j);trim_store()
   os.utime(cache,None)
def worker():
 while True:
  try:
   with LOCK:
    queued=next((j for j in all_jobs() if j['status']=='queued'),None)
   if queued:
    try:run_job(queued)
    except Exception as e:
     with LOCK:queued['status']='failed';queued['error']=str(e);queued['finished_at']=time.time();job_put(queued)
   else:time.sleep(2)
  except Exception as e:print('worker error',repr(e),flush=True);time.sleep(5)
def housekeeping():
 while True:
  try:
   with LOCK:
    cleanup_apply(cleanup_plan())
    # Orphan directory recovery and bounded control-history; only managed namespaces.
    jobs=all_jobs();known={j['id'] for j in jobs}
    for j in jobs:
     d=jobdir(j)
     if j['status'] not in ['queued','running','cancel_requested'] and d.exists() and not any(d.iterdir()):d.rmdir()
    for d in (STORE/'jobs').iterdir():
     if re.fullmatch('[a-f0-9]{16}',d.name) and d.name not in known and time.time()-d.stat().st_mtime>86400:rm(d)
    for j in jobs[:-1000]:
     if j['status'] not in ['queued','running','cancel_requested'] and not jobdir(j).exists():
      with db() as c:c.execute('DELETE FROM jobs WHERE id=?',(j['id'],))
  except Exception as e:print('cleanup error',repr(e),flush=True)
  time.sleep(900)
TOKEN=json.loads((ROOT/'secrets.json').read_text())['upstream']
mcp=FastMCP('Android Cloud Build',auth=StaticTokenVerifier(tokens={TOKEN:{'client_id':'mcphub-android-build','scopes':['build']}}))
@mcp.tool()
def environment_info()->dict:
 """Get installed Android/JDK profile and supported operations. No emulator or signing pipeline."""
 return {'host':'Linux ARM64 OCI A1','jdk':17,'sdk_platforms':['android-37.2'],'build_tools':['36.0.0','37.0.0 (ARM64 overrides)'],'gradle':'repository wrapper','concurrency':1,'cpu_limit':2,'memory_limit_gib':8,'source_support':'public GitHub repositories or direct .tar.gz source upload via MCP','source_upload_max_bytes':100*2**20,'source_upload_chunk_bytes':192*1024,'source_upload_retention_hours':2,'ndk_supported':False,'storage':space()}
@mcp.tool()
def register_project(project_id:str,repository:str,module:str='app',subdir:str='.',default_ref:str='main')->dict:
 """Register a PUBLIC GitHub Gradle Android app. No credentials, local paths or arbitrary build commands. ARM64 Linux NDK unsupported."""
 if not re.fullmatch('[a-z0-9][a-z0-9-]{0,49}',project_id):raise ValueError('Invalid project ID')
 if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?',repository):raise ValueError('Only public HTTPS github.com repositories accepted')
 if not re.fullmatch(r'[A-Za-z0-9_-]+',module):raise ValueError('Invalid module')
 if not re.fullmatch(r'[A-Za-z0-9_./-]+',subdir) or subdir.startswith('/') or '..' in Path(subdir).parts:raise ValueError('Invalid subdir')
 check_ref(default_ref)
 with LOCK:
  projects=json.loads(PROJECTS.read_text());projects[project_id]={'repository':repository,'module':module,'subdir':subdir,'default_ref':default_ref};save(PROJECTS,projects)
 return {'project_id':project_id,**projects[project_id]}
@mcp.tool()
def begin_source_upload(filename:str,total_bytes:int,sha256:str)->dict:
 """Begin direct source upload. Package a project as .tar.gz; max 100 MiB, wrapper required. Uploads expire after 2 hours."""
 if filename not in ['source.tar.gz','source.tgz']:raise ValueError('Only .tar.gz source archives are accepted')
 if not 1<=total_bytes<=100*2**20:raise ValueError('Source archive must be 1 byte to 100 MiB')
 if not re.fullmatch('[a-fA-F0-9]{64}',sha256):raise ValueError('Provide the archive SHA256')
 with LOCK:
  cleanup_apply(cleanup_plan());need_space()
  if len(list(UPLOADS.glob('*.json')))>=4:raise ValueError('Source upload limit reached; finish or clean an existing upload')
  i=uuid.uuid4().hex;u={'id':i,'filename':'source.tar.gz','total_bytes':total_bytes,'sha256':sha256.lower(),'received_bytes':0,'created_at':time.time(),'expires_at':time.time()+7200}
  f=upload_file(u);f.parent.mkdir(parents=True,exist_ok=True);f.touch(mode=0o600);upload_put(u)
  return {'upload_id':i,'chunk_bytes':192*1024,'total_bytes':total_bytes,'expires_at':u['expires_at']}
@mcp.tool()
def upload_source_chunk(upload_id:str,offset:int,data_base64:str)->dict:
 """Append the next sequential base64 chunk to a source archive upload (max decoded chunk 192 KiB)."""
 if not isinstance(data_base64,str) or len(data_base64)>4*((192*1024+2)//3):raise ValueError('Encoded chunk exceeds 192 KiB decoded limit')
 try:data=base64.b64decode(data_base64,validate=True)
 except (binascii.Error,ValueError) as e:raise ValueError('Invalid base64 chunk') from e
 if not data or len(data)>192*1024:raise ValueError('Chunk must be 1 byte to 192 KiB')
 with LOCK:
  u=upload_get(upload_id);f=upload_file(u)
  if u['expires_at']<=time.time():raise ValueError('Source upload expired')
  if offset!=u['received_bytes']:raise ValueError('Chunk offset does not match next expected byte')
  if offset+len(data)>u['total_bytes']:raise ValueError('Chunk exceeds declared archive size')
  with f.open('ab') as stream:stream.write(data)
  u['received_bytes']+=len(data);upload_put(u)
  return {'upload_id':upload_id,'received_bytes':u['received_bytes'],'total_bytes':u['total_bytes'],'complete':u['received_bytes']==u['total_bytes']}
@mcp.tool()
def cancel_source_upload(upload_id:str)->dict:
 """Discard an unfinished source upload."""
 with LOCK:
  u=upload_get(upload_id);rm(UPLOADS/(upload_id+'.json'));rm(upload_file(u));return {'upload_id':upload_id,'deleted':True}
@mcp.tool()
def submit_source_build(upload_id:str,module:str='app',subdir:str='.',mode:str='build',idempotency_key:str='')->dict:
 """Validate and compile an uploaded .tar.gz source tree without GitHub. Upload must contain the Gradle wrapper. Only debug APKs; no signing or NDK."""
 if not re.fullmatch(r'[A-Za-z0-9_-]+',module):raise ValueError('Invalid module')
 if not re.fullmatch(r'[A-Za-z0-9_./-]+',subdir) or subdir.startswith('/') or '..' in Path(subdir).parts:raise ValueError('Invalid subdir')
 if mode not in ['build','test','lint','full']:raise ValueError('Unknown mode')
 if len(idempotency_key)>100:raise ValueError('Idempotency key too long')
 with LOCK:
  u=upload_get(upload_id);f=upload_file(u)
  if u['expires_at']<=time.time():raise ValueError('Source upload expired')
  if u['received_bytes']!=u['total_bytes'] or not f.is_file() or f.stat().st_size!=u['total_bytes']:raise ValueError('Source archive upload is incomplete')
  info=validate_source_archive(f,u['sha256'])
  existing=next((j for j in all_jobs() if idempotency_key and j.get('idempotency_key')==idempotency_key),None)
  if existing:
   if (existing.get('source_sha256'),existing.get('module'),existing.get('subdir'),existing.get('mode'))!=(info['sha256'],module,subdir,mode):raise ValueError('Idempotency key already used with different inputs')
   rm(f);rm(UPLOADS/(upload_id+'.json'));return existing
  cleanup_apply(cleanup_plan());need_space()
  if sum(j['status'] in ['queued','running','cancel_requested'] for j in all_jobs())>=10:raise ValueError('Build queue full (10)')
  actions={'build':[f':{module}:assembleDebug'],'test':[f':{module}:testDebugUnitTest'],'lint':[f':{module}:lintDebug'],'full':[f':{module}:testDebugUnitTest',f':{module}:lintDebug',f':{module}:assembleDebug']}
  j={'id':uuid.uuid4().hex[:16],'project_id':'source-upload','repository':'uploaded-source','source_archive':True,'source_sha256':info['sha256'],'source_files':info['files'],'source_expanded_bytes':info['expanded_bytes'],'module':module,'subdir':subdir,'ref':'uploaded-source','mode':mode,'tasks':actions[mode],'status':'queued','created_at':time.time(),'idempotency_key':idempotency_key,'cache_key':'src-'+info['sha256'][:20],'artifacts':[]}
  d=jobdir(j);d.mkdir(parents=True);os.replace(f,d/'source.tar.gz');(UPLOADS/(upload_id+'.json')).unlink(missing_ok=True);job_put(j);return j
@mcp.tool()
def list_projects()->dict:
 """List registered projects and build settings."""
 with LOCK:return json.loads(PROJECTS.read_text())
def check_ref(ref):
 if len(ref)>200 or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_./-]*',ref) or '..' in ref:raise ValueError('Invalid Git ref')
@mcp.tool()
def submit_build(project_id:str,ref:str='',mode:str='build',idempotency_key:str='')->dict:
 """Queue asynchronous build of public GitHub ref/commit. Modes: build, test, lint, full. Poll job ID; use same idempotency key after retries. Debug APK only."""
 if len(idempotency_key)>100:raise ValueError('Idempotency key too long')
 with LOCK:
  p=project(project_id);ref=ref or p['default_ref'];check_ref(ref)
  if mode not in ['build','test','lint','full']:raise ValueError('Unknown mode')
  existing=next((j for j in all_jobs() if idempotency_key and j.get('idempotency_key')==idempotency_key),None)
  if existing:
   if (existing['project_id'],existing['ref'],existing['mode'])!=(project_id,ref,mode):raise ValueError('Idempotency key already used with different inputs')
   return existing
  cleanup_apply(cleanup_plan());need_space()
  history=all_jobs()
  for old in history:
   if len(history)<1000:break
   d=jobdir(old)
   if old['status'] not in ['queued','running','cancel_requested'] and (not d.exists() or not any(d.iterdir())):
    if d.exists():d.rmdir()
    with db() as c:c.execute('DELETE FROM jobs WHERE id=?',(old['id'],))
    history=[j for j in history if j['id']!=old['id']]
  if len(history)>=1000:raise ValueError('Build history limit (1000) reached; clean completed builds first')
  if sum(j['status'] in ['queued','running','cancel_requested'] for j in all_jobs())>=10:raise ValueError('Build queue full (10)')
  module=p['module'];actions={'build':[f':{module}:assembleDebug'],'test':[f':{module}:testDebugUnitTest'],'lint':[f':{module}:lintDebug'],'full':[f':{module}:testDebugUnitTest',f':{module}:lintDebug',f':{module}:assembleDebug']}
  j={'id':uuid.uuid4().hex[:16],'project_id':project_id,'repository':p['repository'],'subdir':p['subdir'],'ref':ref,'mode':mode,'tasks':actions[mode],'status':'queued','created_at':time.time(),'idempotency_key':idempotency_key,'cache_key':hashlib.sha256((p['repository']+'\0'+p['subdir']).encode()).hexdigest()[:20],'artifacts':[]}
  jobdir(j).mkdir(parents=True);job_put(j);return j
@mcp.tool()
def list_builds(limit:int=20)->list[dict]:
 """Recent build IDs, states, refs and commit IDs."""
 with LOCK:return [{k:v for k,v in j.items() if k!='artifacts'} for j in all_jobs()[-max(1,min(limit,100)):]][::-1]
@mcp.tool()
def get_build_status(build_id:str)->dict:
 """Return asynchronous build state, timings, commit and artifact metadata."""
 with LOCK:return job_get(build_id)
@mcp.tool()
def read_build_logs(build_id:str,offset:int=0,limit:int=16384)->dict:
 """Read bounded log chunks; offset and next_offset are byte positions."""
 if offset<0:raise ValueError('offset must be nonnegative')
 with LOCK:
  j=job_get(build_id);p=jobdir(j)/'build.log'
  if not p.exists():return {'text':'','next_offset':offset,'status':j['status'],'available':False}
  with p.open('rb') as f:f.seek(offset);data=f.read(max(1,min(limit,65536)))
  return {'text':data.decode('utf-8','replace'),'next_offset':offset+len(data),'status':j['status'],'available':True}
@mcp.tool()
def get_artifacts(build_id:str)->dict:
 """List retained APK/AAB and reports, SHA256, sizes. Fetch through read_artifact or SSH/SCP."""
 with LOCK:
  j=job_get(build_id);return {'build_id':build_id,'available':not j.get('outputs_cleaned',False),'artifacts':j['artifacts'],'ssh_directory':str(jobdir(j)/'artifacts')}
@mcp.tool()
def read_artifact(build_id:str,path:str,offset:int=0,limit:int=262144)->dict:
 """Fetch an artifact as base64 chunks (max 512 KiB). Join chunks and validate SHA256 from get_artifacts. Read and cleanup mutually exclude each other."""
 if offset<0:raise ValueError('Invalid offset')
 with LOCK:
  j=job_get(build_id);item=next((a for a in j['artifacts'] if a['path']==path),None)
  if not item or j.get('outputs_cleaned'):raise ValueError('Artifact unavailable')
  p=jobdir(j)/'artifacts'/path
  with p.open('rb') as f:f.seek(offset);data=f.read(max(1,min(limit,524288)))
  j['download_until']=time.time()+600;job_put(j)
  return {'base64':base64.b64encode(data).decode(),'next_offset':offset+len(data),'eof':offset+len(data)>=item['size_bytes'],'sha256':item['sha256'],'size_bytes':item['size_bytes']}
@mcp.tool()
def cancel_build(build_id:str)->dict:
 """Cancel queued or running build; running container is terminated by worker."""
 with LOCK:
  j=job_get(build_id)
  if j['status']=='queued':j['status']='cancelled';j['finished_at']=time.time()
  elif j['status']=='running':j['status']='cancel_requested'
  job_put(j);return j
@mcp.tool()
def storage_status()->dict:
 """Check hard quota, host free threshold, SDK, per-project cache and job disk usage."""
 with LOCK:return {**space(),'categories_bytes':{n:du(STORE/n) for n in ['jobs','cache','sdk','uploads']},'active_build':ACTIVE}
@mcp.tool()
def preview_cleanup()->dict:
 """Preview automatic expiry/cache cleanup with estimated reclaimable bytes; never changes files."""
 with LOCK:
  plan=cleanup_plan();return {'items':plan,'estimated_bytes':sum(i['bytes'] for i in plan)}
@mcp.tool()
def cleanup_expired()->dict:
 """Run expiry/cache cleanup now. Protect active jobs and 10-minute download leases."""
 with LOCK:return cleanup_apply(cleanup_plan())
@mcp.tool()
def cleanup_build(build_id:str)->dict:
 """Permanently delete workspace, APKs and logs of ONE completed build. Active jobs/downloads protected. Metadata remains."""
 with LOCK:
  j=job_get(build_id)
  if j['status'] in ['queued','running','cancel_requested'] or j.get('download_until',0)>time.time():raise ValueError('Build active or download lease active; retry after completion / 10 minutes')
  before=shutil.disk_usage(STORE).used;rm(jobdir(j));trim_store();j['outputs_cleaned']=True;j['workspace_cleaned']=True;job_put(j)
  return {'build_id':build_id,'released_bytes':max(0,before-shutil.disk_usage(STORE).used)}
@mcp.tool()
def set_retention(artifact_days:int=7,failed_workspace_hours:int=24,cache_days:int=14,cache_max_gib:int=20)->dict:
 """Set retention within fixed safety bounds. Changes affect automatic cleanup every 15min. Cannot remove hard disk quota or host free threshold."""
 if not 1<=artifact_days<=30 or not 1<=failed_workspace_hours<=72 or not 1<=cache_days<=30 or not 1<=cache_max_gib<=30:raise ValueError('Bounds: artifacts/cache 1..30 days, failure workspace 1..72h, cache 1..30GiB')
 with LOCK:
  p=policy();p.update(artifact_days=artifact_days,failed_workspace_hours=failed_workspace_hours,cache_days=cache_days,cache_max_gib=cache_max_gib);save(POLICY,p);return p

def start():
 if not os.path.ismount(STORE):raise RuntimeError('Storage filesystem not mounted; refusing to use host directory')
 # Recover own orphan containers and interrupted jobs on service restart.
 names=docker('ps','-aq','--filter','label=local.android-build.managed=true',capture_output=True,text=True,check=True).stdout.split()
 for name in names:stop_container(name)
 with LOCK:
  for j in all_jobs():
   if j['status'] in ['running','cancel_requested']:
    j['status']='interrupted';j['finished_at']=time.time();job_put(j)
 threading.Thread(target=worker,daemon=True).start();threading.Thread(target=housekeeping,daemon=True).start()
 mcp.run(transport='http',host=os.environ.get('ANDROID_BUILD_HOST','172.18.0.1'),port=int(os.environ.get('ANDROID_BUILD_PORT','18200')),stateless_http=True)
if __name__=='__main__':start()
