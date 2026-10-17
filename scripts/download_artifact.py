# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp==3.4.5"]
# ///
"""uv run scripts/download_artifact.py BUILD_ID [--output /absolute/file.apk]
Uses private runtime/mcp-client.json; streams through MCP without printing base64.
"""
import argparse,asyncio,base64,hashlib,json,os,tempfile
from pathlib import Path
from fastmcp import Client
async def main():
 parser=argparse.ArgumentParser(description='Download Android build APK via MCPHub and verify SHA256')
 parser.add_argument('build_id');parser.add_argument('--output',type=Path);parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'runtime/mcp-client.json');args=parser.parse_args()
 cfg=json.loads(args.config.read_text())['mcpServers']['android-build']
 target=args.output or Path(__file__).resolve().parents[1]/'runtime/downloads'/(args.build_id+'.apk');target=target.resolve()
 if target.exists():raise SystemExit('Destination already exists; choose another --output path')
 target.parent.mkdir(parents=True,exist_ok=True)
 async with Client(cfg['url'],auth=cfg['headers']['Authorization'].removeprefix('Bearer '),timeout=120) as c:
  tools=await c.list_tools()
  async def call(name,**kwargs):
   result=await c.call_tool(next(t.name for t in tools if t.name.endswith('-'+name) or t.name==name),kwargs)
   if result.is_error:raise RuntimeError(str(result.content))
   return result.data
  listing=await call('get_artifacts',build_id=args.build_id)
  if not listing['available']:raise SystemExit('Artifacts have been cleaned')
  apk=next((a for a in listing['artifacts'] if a['path'].endswith('.apk')),None)
  if not apk:raise SystemExit('No APK available; inspect build status/logs')
  fd,temp=tempfile.mkstemp(prefix='.android-download-',suffix='.part',dir=target.parent);offset=0;sha=hashlib.sha256()
  try:
   with os.fdopen(fd,'wb') as f:
    while True:
     r=await call('read_artifact',build_id=args.build_id,path=apk['path'],offset=offset,limit=524288)
     chunk=base64.b64decode(r['base64']);f.write(chunk);sha.update(chunk);assert r['next_offset']==offset+len(chunk);offset=r['next_offset']
     if r['eof']:break
     if not chunk:raise RuntimeError('Unexpected empty artifact chunk before EOF')
   if offset!=apk['size_bytes'] or sha.hexdigest()!=apk['sha256']:raise RuntimeError('Artifact size/SHA256 mismatch')
   # Atomic creation refuses to replace an existing user file.
   os.link(temp,target);os.unlink(temp)
  finally:
   Path(temp).unlink(missing_ok=True)
  print(str(target));print('SHA256: '+sha.hexdigest())
asyncio.run(main())
