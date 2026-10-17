"""Resolve a user-defined IPv4 Docker bridge; never accept a public gateway."""
import ipaddress,json,subprocess

def bridge(network):
 data=json.loads(subprocess.check_output(['docker','network','inspect',network],text=True))[0]
 if data['Driver']!='bridge' or data['Name']=='bridge':raise ValueError('Use a user-defined Docker bridge network')
 configs=[x for x in data['IPAM']['Config'] if ':' not in x.get('Subnet','')]
 if len(configs)!=1:raise ValueError('Expected one IPv4 subnet')
 subnet=ipaddress.ip_network(configs[0]['Subnet']);gateway=ipaddress.ip_address(configs[0]['Gateway'])
 private=[ipaddress.ip_network(x) for x in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']]
 if not any(subnet.subnet_of(x) for x in private) or gateway not in subnet:raise ValueError('Docker subnet must be RFC1918 private IPv4')
 interface=data.get('Options',{}).get('com.docker.network.bridge.name') or 'br-'+data['Id'][:12]
 return interface,str(subnet),str(gateway)
