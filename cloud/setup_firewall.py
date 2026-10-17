"""Allow Docker Hub containers to reach only the private MCP listener ports."""
import argparse,os,re,shlex,subprocess
from pathlib import Path
from network_info import bridge
MARKER='# Managed by mcp-cloud-workbench setup_firewall.py\n'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--network',default='mcphub_default');p.add_argument('--ports',default='28189,28190,28192');p.add_argument('--apply',action='store_true');a=p.parse_args()
 if os.geteuid()!=0:raise ValueError('Run as root')
 if not re.fullmatch('[A-Za-z0-9_.-]+',a.network):raise ValueError('Invalid network name')
 ports=sorted(set(int(x) for x in a.ports.split(',')))
 if not ports or len(ports)>15 or any(not 1024<=x<=65535 for x in ports):raise ValueError('Expected at most 15 unprivileged TCP ports')
 interface,subnet,gateway=bridge(a.network)
 if a.apply:
  args=['INPUT','-i',interface,'-s',subnet,'-d',gateway,'-p','tcp','-m','multiport','--dports',','.join(map(str,ports)),'-m','comment','--comment','mcp-cloud-workbench','-j','ACCEPT']
  if subprocess.run(['iptables','-C',*args],stderr=subprocess.DEVNULL).returncode:subprocess.run(['iptables','-I',args[0],'1',*args[1:]],check=True)
  return
 root=Path('/opt/mcp-cloud-network');root.mkdir(mode=0o755,exist_ok=True)
 service=Path('/etc/systemd/system/mcp-cloud-firewall.service')
 if service.exists() and MARKER not in service.read_text():raise ValueError('Existing unmanaged service; refusing to overwrite')
 for name in ['setup_firewall.py','network_info.py']:(root/name).write_bytes(Path(__file__).with_name(name).read_bytes())
 service.write_text(MARKER+f'''[Unit]
Description=Private Docker MCP listener access
After=docker.service
Requires=docker.service
PartOf=docker.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {root}/setup_firewall.py --apply --network {a.network} --ports {','.join(map(str,ports))}
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
''')
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','enable','mcp-cloud-firewall'],check=True);subprocess.run(['systemctl','restart','mcp-cloud-firewall'],check=True)
 print('Private Docker firewall installed; restart mcp-cloud-firewall after recreating the Docker network')
if __name__=='__main__':main()
