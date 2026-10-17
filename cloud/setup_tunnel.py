"""Install a restricted SSH reverse-tunnel account; preserve unrelated keys/config."""
import argparse,os,pwd,re,shutil,subprocess
from pathlib import Path
from network_info import bridge
MARKER='# Managed by mcp-cloud-workbench setup_tunnel.py\n'
def run(*a):return subprocess.run(a,check=True,capture_output=True,text=True)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--public-key',type=Path,required=True);p.add_argument('--user',default='mcphub-bridge');p.add_argument('--network',default='mcphub_default');p.add_argument('--ports',default='28189,28190,28192');a=p.parse_args()
 if os.geteuid()!=0:raise ValueError('Run as root')
 if not re.fullmatch('[a-z][a-z0-9-]{0,30}',a.user):raise ValueError('Invalid dedicated username')
 ports=[int(x) for x in a.ports.split(',')]
 if not ports or any(not 1024<=x<=65535 for x in ports):raise ValueError('Unprivileged TCP ports required')
 _,_,gateway=bridge(a.network)
 key=a.public_key.read_text().strip()
 if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?',key):raise ValueError('Expected one Ed25519 public key')
 target=Path('/etc/ssh/sshd_config.d')/('90-'+a.user+'.conf')
 original=target.read_bytes() if target.exists() else None
 if original is not None and not original.decode().startswith(MARKER):raise ValueError('Existing SSH snippet is not managed by this installer')
 try:account=pwd.getpwnam(a.user)
 except KeyError:
  run('useradd','--create-home','--shell','/bin/false',a.user);account=pwd.getpwnam(a.user)
 if account.pw_shell not in ['/bin/false','/usr/sbin/nologin','/sbin/nologin']:raise ValueError('Refusing to restrict an existing interactive account')
 ssh=Path(account.pw_dir)/'.ssh';ssh.mkdir(mode=0o700,exist_ok=True)
 auth=ssh/'authorized_keys'
 if ssh.is_symlink() or auth.is_symlink():raise ValueError('SSH paths may not be symlinks')
 oldauth=auth.read_bytes() if auth.exists() else None
 existing=oldauth.decode().splitlines() if oldauth else []
 blob=key.split()[1]
 if any(blob in line and '# mcp-cloud-workbench' not in line for line in existing):raise ValueError('This key already has unmanaged permissions; inspect authorized_keys')
 line='restrict,port-forwarding,'+','.join(f'permitlisten="{gateway}:{port}"' for port in ports)+' '+' '.join(key.split()[:2])+' # mcp-cloud-workbench'
 content='\n'.join([x for x in existing if blob not in x]+[line])+'\n'
 body=MARKER+f'''Match User {a.user}
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    GatewayPorts clientspecified
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    PermitListen {' '.join(f'{gateway}:{port}' for port in ports)}
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    MaxSessions 0
Match all
'''
 try:
  auth.write_text(content);auth.chmod(0o600);ssh.chmod(0o700)
  os.chown(ssh,account.pw_uid,account.pw_gid);os.chown(auth,account.pw_uid,account.pw_gid)
  target.write_text(body);target.chmod(0o644)
  run('/usr/sbin/sshd','-t');run('systemctl','reload','ssh')
 except Exception:
  if original is None:target.unlink(missing_ok=True)
  else:target.write_bytes(original)
  if oldauth is None:auth.unlink(missing_ok=True)
  else:auth.write_bytes(oldauth);auth.chmod(0o600)
  raise
 print('Restricted tunnel account configured for private Docker gateway',gateway)
if __name__=='__main__':main()
