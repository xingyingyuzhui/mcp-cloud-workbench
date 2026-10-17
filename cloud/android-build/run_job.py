import json,os,subprocess,re,tarfile
from pathlib import Path
cfg=json.loads(Path('/job-input.json').read_text())
def run(args):
 print('+ '+' '.join(args),flush=True);subprocess.run(args,check=True)
os.makedirs('/tmp/home/.android',exist_ok=True)
os.environ['JAVA_TOOL_OPTIONS']='-Duser.home=/tmp/home'
if cfg.get('source_archive'):
 with tarfile.open('/source.tar.gz','r:gz') as archive:
  for member in archive:
   if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):raise RuntimeError('Unsupported archive entry')
   if member.name.startswith('/') or '..' in Path(member.name).parts or '\\' in member.name:raise RuntimeError('Unsafe archive path')
  archive.extractall('/workspace',filter='data')
 sha=cfg.get('source_sha256','')
else:
 run(['git','init','.'])
 run(['git','remote','add','origin',cfg['repository']])
 run(['git','-c','protocol.file.allow=never','fetch','--depth','1','origin',cfg['ref']])
 run(['git','checkout','--detach','FETCH_HEAD'])
 sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 Path('/workspace/.build-commit').write_text(sha)
project=Path('/workspace')/cfg['subdir'];os.chdir(project)
if not Path('gradlew').is_file():raise RuntimeError('Gradle wrapper missing')
Path('local.properties').write_text('sdk.dir=/opt/android-sdk\n')
print('BUILD_COMMIT='+sha,flush=True)
run(['sh','./gradlew','--no-daemon','--console=plain','--max-workers=2','-Dorg.gradle.jvmargs=-Xmx3g -Dfile.encoding=UTF-8','-Dkotlin.daemon.jvm.options=-Xmx2g','-Pandroid.aapt2FromMavenOverride=/opt/android-sdk/build-tools/37.0.0/aapt2']+cfg['tasks'])
