#!/usr/bin/env python3
"""Download a cloud build APK on this Mac and install it through the configured Android MCP."""
import argparse,asyncio,base64,hashlib,json,os,re,tempfile
from pathlib import Path
from fastmcp import FastMCP,Client
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

def result_data(result):
 if result.is_error:raise RuntimeError('; '.join(x.text for x in result.content if getattr(x,'text',None)) or 'MCP call failed')
 structured=getattr(result,'structured_content',None)
 if isinstance(structured,dict):return structured
 for item in result.content:
  text=getattr(item,'text',None)
  if text:
   try:
    value=json.loads(text)
    if isinstance(value,dict):return value
   except json.JSONDecodeError:pass
 raise RuntimeError('MCP returned no structured result')

def load_config(path):
 c=json.loads(path.read_text())
 for key in ['build_url','build_token','android_url','android_token','service_token','download_dir']:
  if not isinstance(c.get(key),str) or not c[key]:raise ValueError('Missing config field: '+key)
 return c

def create_app(config):
 mcp=FastMCP('Android Build Artifact Delivery',auth=StaticTokenVerifier(tokens={config['service_token']:{'client_id':'mac-apk-delivery','scopes':['install']}}))
 @mcp.tool()
 async def install_build_apk(build_id:str,artifact_path:str='',device:str='auto')->dict:
  """Fetch a retained APK from Android Build MCP directly onto this Mac, verify SHA256, then install it on the configured Android emulator. No APK bytes pass through the agent conversation."""
  if not re.fullmatch('[0-9a-f]{16}',build_id):raise ValueError('Invalid build ID')
  if device not in ['auto','']:raise ValueError('Only the configured emulator (auto) is supported')
  async with Client(config['build_url'],auth=config['build_token'],timeout=180) as build:
   listing=result_data(await build.call_tool('android-build-get_artifacts',{'build_id':build_id}))
   if not listing.get('available'):raise ValueError('Build artifacts have expired or were cleaned')
   artifacts=[a for a in listing.get('artifacts',[]) if a.get('path','').lower().endswith('.apk')]
   if artifact_path:artifacts=[a for a in artifacts if a.get('path')==artifact_path]
   if len(artifacts)!=1:raise ValueError('Expected exactly one APK; specify artifact_path from get_artifacts')
   artifact=artifacts[0]
   if artifact.get('size_bytes',0)>1024**3:raise ValueError('APK exceeds 1 GiB safety limit')
   directory=Path(config['download_dir']).expanduser().resolve();directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
   fd,temp_name=tempfile.mkstemp(prefix=build_id+'-',suffix='.apk.part',dir=directory);os.fchmod(fd,0o600)
   digest=hashlib.sha256();offset=0
   try:
    with os.fdopen(fd,'wb') as output:
     while offset<artifact['size_bytes']:
      chunk=result_data(await build.call_tool('android-build-read_artifact',{'build_id':build_id,'path':artifact['path'],'offset':offset,'limit':262144}))
      data=base64.b64decode(chunk['base64'],validate=True)
      if not data or len(data)>262144 or offset+len(data)>artifact['size_bytes']:raise ValueError('Invalid artifact chunk')
      output.write(data);digest.update(data);offset+=len(data)
      if chunk.get('next_offset')!=offset:raise ValueError('Artifact offset mismatch')
     output.flush();os.fsync(output.fileno())
    if offset!=artifact['size_bytes'] or digest.hexdigest()!=artifact['sha256']:raise ValueError('Downloaded APK SHA256 or size mismatch')
    final_path=directory/(build_id+'-'+Path(artifact['path']).name)
    os.replace(temp_name,final_path);os.chmod(final_path,0o600)
    async with Client(config['android_url'],auth=config['android_token'],timeout=180) as android:
     installed=result_data(await android.call_tool('mac-android-mobile_install_app',{'device':'auto','path':str(final_path)}))
    return {'build_id':build_id,'artifact':artifact['path'],'size_bytes':offset,'sha256':digest.hexdigest(),'installed':True,'emulator_result':installed}
   finally:
    Path(temp_name).unlink(missing_ok=True)
    if 'final_path' in locals():final_path.unlink(missing_ok=True)
 return mcp

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
 c=load_config(a.config);create_app(c).run(transport='http',host='127.0.0.1',port=19102,stateless_http=True)
if __name__=='__main__':main()
