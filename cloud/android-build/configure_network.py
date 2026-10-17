import json,os,subprocess
from network_info import bridge

def run(*a):subprocess.run(a,check=True)
def rule(chain,*args):
 if subprocess.run(['iptables','-C',chain,*args],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:run('iptables','-I',chain,'1',*args)
interface,subnet,gateway=bridge(os.environ.get('MCPHUB_NETWORK','mcphub_default'))
_,build_subnet,_=bridge('android-build-net')
build_info=json.loads(subprocess.check_output(['docker','network','inspect','android-build-net'],text=True))[0]
if build_info.get('EnableIPv6'):raise ValueError('IPv6 must be disabled on the build network')
if build_subnet!= '172.30.0.0/24':raise ValueError('android-build-net must use dedicated 172.30.0.0/24 subnet')
subprocess.run(['iptables','-N','ANDROID-BUILD-EGRESS'],stderr=subprocess.DEVNULL)
run('iptables','-F','ANDROID-BUILD-EGRESS')
for cidr in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','127.0.0.0/8','224.0.0.0/4','240.0.0.0/4']:
 run('iptables','-A','ANDROID-BUILD-EGRESS','-d',cidr,'-j','REJECT')
run('iptables','-A','ANDROID-BUILD-EGRESS','-j','RETURN')
rule('DOCKER-USER','-s',build_subnet,'-j','ANDROID-BUILD-EGRESS')
rule('INPUT','-s',build_subnet,'-j','REJECT')
rule('INPUT','-i',interface,'-s',subnet,'-d',gateway,'-p','tcp','--dport',os.environ.get('ANDROID_BUILD_PORT','18200'),'-j','ACCEPT')
