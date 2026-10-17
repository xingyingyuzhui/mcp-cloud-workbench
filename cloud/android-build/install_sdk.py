"""Provision official SDK archives, local package metadata, and checksum-verified ARM64 tools.
SDK licence acceptance is part of installing this Android build environment.
Native Google Android CLI is x86_64; no CLI execution is required on A1.
"""
import copy,hashlib,json,os,shutil,subprocess,urllib.request,xml.etree.ElementTree as E,zipfile
from pathlib import Path
sdk=Path('/srv/android-build/sdk');tmp=Path('/srv/android-build/sdk-download');tmp.mkdir(exist_ok=True)
root=E.fromstring(urllib.request.urlopen('https://dl.google.com/android/repository/repository2-4.xml').read())
manifest_path=Path('/opt/android-build/sdk-manifest.json');manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
E.register_namespace('repo','http://schemas.android.com/repository/android/common/02')
for package in ['platforms;android-37.2','build-tools;36.0.0','build-tools;37.0.0']:
 p=next(p for p in root.findall('remotePackage') if p.attrib['path']==package)
 a=next(a for a in p.findall('./archives/archive') if a.findtext('host-os') in [None,'linux'])
 url='https://dl.google.com/android/repository/'+a.findtext('./complete/url');expected=a.findtext('./complete/checksum')
 target=sdk/package.replace(';','/')
 if not target.exists():
  dest=tmp/(package.replace(';','-')+'.zip');print('Download',package,flush=True);urllib.request.urlretrieve(url,dest)
  sha1=hashlib.sha1(dest.read_bytes()).hexdigest();assert sha1==expected
  manifest[package]={'url':url,'sha1':sha1,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
  extracted=tmp/package.replace(';','-');extracted.mkdir(exist_ok=True)
  with zipfile.ZipFile(dest) as z:z.extractall(extracted)
  target.parent.mkdir(parents=True,exist_ok=True);shutil.move(next(extracted.iterdir()),target)
  for f in target.rglob('*'):
   if f.is_file():
    with f.open('rb') as h:head=h.read(4)
    if f.parent.name=='bin' or head==b'\x7fELF':f.chmod(0o755)
  dest.unlink();shutil.rmtree(extracted)
 # SDK metadata from Google's manifest, without remote-only download fields.
 metadata=E.Element('{http://schemas.android.com/repository/android/common/02}repository',{'xmlns:sdk':'http://schemas.android.com/sdk/android/repo/repository2/04','xmlns:generic':'http://schemas.android.com/repository/android/generic/02'})
 license_id=p.find('uses-license').attrib['ref'];license=next(x for x in root.findall('license') if x.attrib['id']==license_id)
 metadata.append(copy.deepcopy(license));local=copy.deepcopy(p);local.tag='localPackage';local.set('obsolete','false')
 for tag in ['archives','channelRef']:
  for element in local.findall(tag):local.remove(element)
 metadata.append(local);E.ElementTree(metadata).write(target/'package.xml',encoding='utf-8',xml_declaration=True)
 # Standard SDK licence hash format, equivalent to sdkmanager acceptance.
 accepted=sdk/'licenses'/license_id;accepted.parent.mkdir(exist_ok=True)
 digest=hashlib.sha1(license.text.strip().encode()).hexdigest()
 current=accepted.read_text().splitlines() if accepted.exists() else []
 if digest not in current:accepted.write_text('\n'.join(current+[digest])+'\n')
 if package.startswith('build-tools;'):
  version=package.split(';')[1];base=f'https://github.com/Commit451/android-arm-build-tools/releases/download/platform-tools-{version}/'
  sums=urllib.request.urlopen(base+'SHA256SUMS').read().decode();manifest['arm64-build-tools-'+version]={'release':base,'SHA256SUMS':sums}
  for name in ['aapt2','aidl','zipalign','split-select']:
   data=urllib.request.urlopen(base+name).read();expected=next(l.split()[0] for l in sums.splitlines() if l.split()[-1].lstrip('*')==name)
   assert hashlib.sha256(data).hexdigest()==expected
   path=target/name;path.write_bytes(data);path.chmod(0o755)
manifest_path.write_text(json.dumps(manifest,indent=2));shutil.rmtree(tmp)
subprocess.run(['chown','-R','10001:10001',str(sdk)],check=True)
print('SDK platforms, local metadata, licences, ARM64 build-tools ready',flush=True)
