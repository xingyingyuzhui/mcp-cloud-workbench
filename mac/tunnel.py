#!/usr/bin/env python3
"""SSH local management forward / constrained reverse MCP forwards. No public listeners."""
import argparse,ipaddress,json,os,re,shlex
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def command(config,mode):
 host=config['host']
 if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9.-]*',host):raise ValueError('Expected DNS hostname or IPv4 address')
 user=config['tunnel_user'] if mode=='reverse' else config['ssh_user']
 if not re.fullmatch('[a-z_][a-z0-9_-]{0,31}',user):raise ValueError('Invalid SSH username')
 key=config['tunnel_key'] if mode=='reverse' else config['ssh_key']
 args=['/usr/bin/ssh','-NT','-i',key,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+config['known_hosts_file'],'-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3']
 def port(n):
  n=int(n)
  if not 1024<=n<=65535:raise ValueError('Invalid forwarding port')
  return n
 if mode=='reverse':
  gateway=ipaddress.ip_address(config['docker_gateway'])
  if gateway.version!=4 or not gateway.is_private or gateway.is_loopback:raise ValueError('Reverse listeners must bind to a private Docker IPv4 gateway')
  if not config['forwards']:raise ValueError('No enabled Mac services; nothing to reverse-forward')
  for f in config['forwards']:args+=['-R',f"{gateway}:{port(f['remote_port'])}:127.0.0.1:{port(f['local_port'])}"]
 elif mode=='forward':args+=['-L',f"127.0.0.1:{port(config['local_hub_port'])}:127.0.0.1:{port(config['hub_port'])}"]
 else:raise ValueError('Unknown tunnel mode')
 return args+[user+'@'+host]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['forward','reverse']);p.add_argument('--runtime',type=Path,default=REPO/'runtime/mac-bridge');p.add_argument('--print-command',action='store_true');a=p.parse_args()
 cfg=json.loads((a.runtime/'tunnel.json').read_text());args=command(cfg,a.mode)
 if a.print_command:print(shlex.join(args));return
 for name in ['known_hosts_file','tunnel_key' if a.mode=='reverse' else 'ssh_key']:
  if not Path(cfg[name]).is_file():raise SystemExit('Missing '+name+': '+cfg[name])
 if cfg['host'].endswith('.example.com'):raise SystemExit('Configure your real cloud hostname before connecting')
 os.execv(args[0],args)
if __name__=='__main__':main()
