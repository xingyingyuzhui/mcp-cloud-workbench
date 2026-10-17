#!/usr/bin/env python3
"""Repository hygiene guard, not a substitute for a full secret scanner.
Reports locations only; never prints potential credential values.
"""
import ipaddress,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def candidates():
 p=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True)
 if p.returncode==0:return [ROOT/s.decode() for s in p.stdout.split(b'\0') if s]
 return [p for p in ROOT.rglob('*') if p.is_file() and not any(n in {'.git','.venv','runtime','__pycache__'} for n in p.relative_to(ROOT).parts)]
def inspect(path):
 rel=path.relative_to(ROOT);name=path.name;issues=[]
 if any(n in {'runtime','.oci','.venv'} for n in rel.parts) or rel.as_posix()=='config/local.json' or name=='secrets.json' or name=='mcp_settings.json' or name=='.env' or path.suffix in {'.pem','.key','.jks','.keystore','.sqlite','.apk','.aab','.img'}:
  return [(0,'private/runtime file included')]
 try:text=path.read_text()
 except (UnicodeDecodeError,OSError):return [(0,'unexpected non-text or unreadable file')]
 patterns=[(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----','private key'),(r'/Users/[A-Za-z0-9_-]+/','personal Mac path'),(r'ocid1\.[a-z0-9]+\.[a-z0-9.]{24,}','OCI account/resource identifier'),(r'gh[pousr]_[A-Za-z0-9]{30,}','GitHub token'),(r'github_pat_[A-Za-z0-9_]{30,}','GitHub token')]
 for number,line in enumerate(text.splitlines(),1):
  for pattern,label in patterns:
   if re.search(pattern,line):issues.append((number,label))
  for value in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',line):
   try:ip=ipaddress.ip_address(value)
   except ValueError:continue
   if ip.is_global and not ip.is_multicast and not ip.is_reserved and value not in {'1.1.1.1','8.8.8.8'}:issues.append((number,'public IP address; use a configurable placeholder'))
 return issues
def main():
 findings=[]
 for p in candidates():
  if p.is_file():findings.extend((str(p.relative_to(ROOT)),n,label) for n,label in inspect(p))
 for path,n,label in findings:print(f'{path}:{n}: {label}')
 if findings:raise SystemExit(1)
 print('Public-tree hygiene checks passed')
if __name__=='__main__':main()
