#!/usr/bin/env python3
"""Generate private runtime config; no deployment, connection, key upload or shell execution."""
import argparse,base64,ipaddress,json,os,re,secrets,uuid
from pathlib import Path
from urllib.parse import urlsplit
REPO=Path(__file__).resolve().parents[1]
def private_json(path,data):
 path.parent.mkdir(parents=True,exist_ok=True);path.parent.chmod(0o700)
 temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.chmod(0o600);temp.replace(path)
def expanded(value):return str(Path(os.path.expandvars(value)).expanduser().resolve())
def generate(config,output):
 c=config['cloud'];gateway=str(ipaddress.ip_address(c['docker_gateway']))
 network=ipaddress.ip_network(c['docker_subnet'],strict=True)
 if network.version!=4 or not any(network.subnet_of(ipaddress.ip_network(n)) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']):raise ValueError('Docker network must use RFC1918 IPv4')
 if not ipaddress.ip_address(gateway) in network or gateway in [str(network.network_address),str(network.broadcast_address)]:raise ValueError('Docker gateway outside usable subnet')
 if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*',c['docker_network']):raise ValueError('Invalid Docker network name')
 if int(c['hub_port'])!=3000:raise ValueError('This compose profile binds cloud hub_port=3000')
 output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);output.chmod(0o700)
 state=output/'secrets.json';s=json.loads(state.read_text()) if state.exists() else {}
 for key in ['admin_password','jwt_secret','android_build_upstream','android_build_agent','mac_tools_agent','artifact_delivery_service','artifact_delivery_agent','blender_upstream','comfyui_upstream','blender_agent','comfyui_agent','android_agent']:
  s.setdefault(key,secrets.token_urlsafe(36))
 s.setdefault('credential_encryption_key',base64.b64encode(secrets.token_bytes(32)).decode())
 private_json(state,s)
 network_env='MCPHUB_NETWORK='+c['docker_network']+'\nMCPHUB_GATEWAY='+gateway+'\nMCPHUB_SUBNET='+str(network)+'\n'
 net=output/'cloud.env';net.write_text(network_env);net.chmod(0o600)
 env=output/'mcphub.env';env.write_text(network_env+'ADMIN_PASSWORD='+s['admin_password']+'\nJWT_SECRET='+s['jwt_secret']+'\nMCPHUB_CREDENTIAL_ENCRYPTION_KEY='+s['credential_encryption_key']+'\n');env.chmod(0o600)
 private_json(output/'android-build/secrets.json',{'upstream':s['android_build_upstream']})
 bridge=output/'mac-bridge';private_json(bridge/'secrets.json',{'blender_upstream':s['blender_upstream'],'comfyui_upstream':s['comfyui_upstream']})
 servers={};keys=[];groups=[];forwards=[];clients={};local_port=int(c['local_hub_port'])
 if not 1024<=local_port<=65535:raise ValueError('Invalid local Hub port')
 used_local={local_port};used_remote=set()
 def port(value):
  n=int(value)
  if not 1024<=n<=65535:raise ValueError('Service ports must be 1024..65535')
  return n
 def add_key(name,token,allowed):
  keys.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'mcp-cloud-workbench/'+name)),'name':name,'token':token,'enabled':True,'kind':'system','accessType':'servers','allowedServers':allowed})
 def add_server(name,url,token,description,agent_token):
  servers[name]={'type':'streamable-http','url':url,'headers':{'Authorization':'Bearer '+token},'owner':'admin','visibility':'private','enableKeepAlive':False,'description':description,'options':{'timeout':600000}}
  add_key(name+'-agent',agent_token,[name]);clients[name]={'type':'http','url':f'http://127.0.0.1:{local_port}/mcp/{name}','headers':{'Authorization':'Bearer '+agent_token}}
 for name,entry in config['mac'].items():
  if not entry.get('enabled'):continue
  lp=port(entry['local_port']);rp=port(entry['remote_port'])
  if lp in used_local or rp in used_remote:raise ValueError('Duplicate local/remote MCP port')
  used_local.add(lp);used_remote.add(rp);forwards.append({'name':name,'remote_port':rp,'local_port':lp})
  if name=='blender':
   private_json(bridge/'blender-config.json',{'command':expanded(entry['command']) if '/' in entry['command'] else entry['command'],'args':entry.get('args',[]),'env':entry.get('env',{}),'port':lp})
   token=s['blender_upstream']
  elif name=='comfyui':
   url=urlsplit(entry['upstream_url'])
   if url.scheme!='http' or url.hostname not in ['localhost','127.0.0.1','::1']:raise ValueError('ComfyUI upstream must remain loopback HTTP')
   private_json(bridge/'comfyui-config.json',{'upstream_url':entry['upstream_url'],'port':lp});token=s['comfyui_upstream']
  elif name=='android':
   token=Path(expanded(entry['token_file'])).read_text().strip()
   if len(token)<24:raise ValueError('Existing Android HTTP bearer key is missing or too short')
  else:raise ValueError('Unknown Mac service '+name)
  add_server('mac-'+name,f'http://{gateway}:{rp}/mcp',token,'Existing Mac '+name+' MCP; shared local application state.',s[name+'_agent'])
 if forwards:
  groups.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'mcp-cloud-workbench/mac-tools')),'name':'mac-tools','servers':['mac-'+f['name'] for f in forwards],'owner':'admin','visibility':'private'})
  keys.append({'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'mcp-cloud-workbench/mac-tools-agent')),'name':'mac-tools-agent','token':s['mac_tools_agent'],'enabled':True,'kind':'system','accessType':'groups','allowedGroups':['mac-tools']})
  clients['mac-tools']={'type':'http','url':f'http://127.0.0.1:{local_port}/mcp/mac-tools','headers':{'Authorization':'Bearer '+s['mac_tools_agent']}}
 if config.get('android_build',{}).get('enabled',True):
  bp=port(config['android_build']['port'])
  if bp in used_remote:raise ValueError('Build port collides with reverse tunnel')
  if bp!=18200:raise ValueError('Build service v0.1 binds 18200; keep port=18200')
  add_server('android-build',f'http://{gateway}:{bp}/mcp',s['android_build_upstream'],'ARM64 Android compile queue, artifacts and bounded cleanup.',s['android_build_agent'])
  if any(f['name']=='android' for f in forwards):
   lp,rp=19102,28193
   if lp in used_local or rp in used_remote:raise ValueError('Android artifact delivery port collides with another service')
   used_local.add(lp);used_remote.add(rp);forwards.append({'name':'android-artifact-delivery','remote_port':rp,'local_port':lp})
   private_json(bridge/'artifact-delivery.json',{'build_url':f'http://127.0.0.1:{local_port}/mcp/android-build','build_token':s['android_build_agent'],'android_url':f'http://127.0.0.1:{local_port}/mcp/mac-android','android_token':s['android_agent'],'service_token':s['artifact_delivery_service'],'download_dir':'~/Library/Caches/MCPHub/android-build-apks'})
   add_server('mac-apk-delivery',f'http://{gateway}:{rp}/mcp',s['artifact_delivery_service'],'Download an OCI Android build APK to this Mac, verify SHA256, and install it on the configured emulator.',s['artifact_delivery_agent'])
   if groups and groups[0]['name']=='mac-tools':groups[0]['servers'].append('mac-apk-delivery')
   clients['mac-apk-delivery']={'type':'http','url':f'http://127.0.0.1:{local_port}/mcp/mac-apk-delivery','headers':{'Authorization':'Bearer '+s['artifact_delivery_agent']}}
 private_json(output/'hub-changes.json',{'servers':servers,'groups':groups,'keys':keys})
 private_json(output/'mcp-client.json',{'mcpServers':clients})
 tunnel={k:c[k] for k in ['host','ssh_user','docker_gateway','tunnel_user','hub_port','local_hub_port']}
 for k in ['ssh_key','tunnel_key','known_hosts_file']:tunnel[k]=expanded(c[k])
 tunnel['forwards']=forwards;private_json(bridge/'tunnel.json',tunnel)
 print('Generated private runtime files (no connection or deployment):',output)
 return output
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=REPO/'config/local.json');p.add_argument('--output',type=Path,default=REPO/'runtime');a=p.parse_args()
 generate(json.loads(a.config.read_text()),a.output)
