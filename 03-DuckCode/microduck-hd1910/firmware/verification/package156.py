"""Package v156 console lifecycle changes with byte-identical v155 firmware."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

BASE=Path(__file__).resolve().parent
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.156'
OLD_CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.151'
OLD_PAYLOAD=BASE/'firmware155-base/Microduck-Robotd-FT6-R17'
STAGE=BASE/'package155/Microduck-Robotd-FT6-R17'
CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.156'
OUT=BASE/'output'
BUILD='1fa8438-feetech-ft6-control.34'
VERSION='1.0.156'
CACHES={'.git','__pycache__','target','.pytest_cache','.venv','node_modules'}

def digest(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def write_json(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def files(root,exclude=()):
    return {p.relative_to(root).as_posix():p for p in sorted(root.rglob('*'))
            if p.is_file() and not set(p.relative_to(root).parts)&CACHES
            and p.relative_to(root).as_posix() not in exclude}

def records(root,exclude=()):
    return [{'path':n,'bytes':p.stat().st_size,'sha256':digest(p)} for n,p in files(root,exclude).items()]

def hashes(root,exclude=()):return {n:digest(p) for n,p in files(root,exclude).items()}

def copy_tree(source,destination):
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns(*CACHES))

def elf_record(path):
    header=subprocess.check_output(['readelf','-h',str(path)],text=True)
    dynamic=subprocess.check_output(['readelf','-d',str(path)],text=True)
    versions=subprocess.check_output(['readelf','--version-info',str(path)],text=True)
    assert 'AArch64' in header,path
    glibc=sorted(set(re.findall(r'GLIBC_(\d+\.\d+)',versions)),key=lambda s:tuple(map(int,s.split('.'))))
    assert glibc and all(tuple(map(int,v.split('.')))<=(2,31) for v in glibc),path
    return {'sha256':digest(path),'machine':'AArch64','needed':re.findall(r'Shared library: \[(.*?)\]',dynamic),
            'glibc_versions':glibc,'bytes':path.stat().st_size}

def make_tar(root,path):
    with tarfile.open(path,'w:gz',compresslevel=6) as archive:
        archive.add(root,arcname=root.name,filter=lambda item:None if set(Path(item.name).parts)&CACHES else item)

def verify_tar(root,path):
    found={}
    with tarfile.open(path,'r:gz') as archive:
        for item in archive:
            parts=Path(item.name).parts
            assert parts[0]==root.name and '..' not in parts and not set(parts)&CACHES
            if item.isfile():
                name=Path(*parts[1:]).as_posix();assert name not in found
                with archive.extractfile(item) as stream:found[name]=hashlib.file_digest(stream,'sha256').hexdigest()
            else:assert item.isdir(),item.name
    assert found==hashes(root),path

def changed(old,new):return [n for n in sorted(old.keys()|new.keys()) if old.get(n)!=new.get(n)]

PREVIOUS=BASE/'source/Microduck-Source-R17-v1.0.155'
payload='console/updates/Microduck-Robotd-FT6-R17.tar.gz'
assert digest(SOURCE/payload)==digest(PREVIOUS/payload)=='373003a7db50d02c0db91b380b78d1277f29ce3a0111a1d27f012537d8919a70'
assert hashes(SOURCE/'packaging')==hashes(PREVIOUS/'packaging')
assert hashes(SOURCE/'console/static')==hashes(PREVIOUS/'console/static')
native=json.loads((BASE/'native-build155-final.json').read_text())
for name,expected in native['source_sha256'].items():assert digest(SOURCE/name)==expected,name
for folder in ('config','duck-control','robotd','duck-ipc-proto','robotd-params'):
    assert hashes(SOURCE/folder)==hashes(PREVIOUS/folder),folder
tests=json.loads((SOURCE/'console/verification/tests156.json').read_text())
assert tests['exit_code']==0 and tests['windows_native_tested'] is False
lifecycle=json.loads((SOURCE/'console/verification/process-lifecycle156.json').read_text())
assert lifecycle['exit_code']==0 and lifecycle['tests_passed']==12
for name,expected in lifecycle['source_sha256'].items():assert digest(SOURCE/name)==expected,name
assert digest(SOURCE/'console/verification/process-lifecycle156.log')==lifecycle['log_sha256']
for test in tests['runs']:
    assert test['exit_code']==0
    assert digest(SOURCE/'console/verification'/test['log'])==test['log_sha256']
    assert test['passed']>0
production=['console.py','connection.py','process_lifecycle.py','service_channel.py','socket_transport.py','staging_upload.py','system_log.py','start.cmd','release_identity.py']
report={'console_version':VERSION,'service_build':BUILD,'scope':'PC console shutdown and reconnect lifecycle only',
        'firmware_archive_unchanged':True,'firmware_reinstall_required':False,
        'native_source_unchanged':True,'saved_calibration_direction_unchanged':True,
        'address_and_password_preferences_preserved':True,'new_periodic_work':False,
        'windows_native_tested':False,'robot_hardware_tested':False,'tests':tests,
        'windows_boundary':'Kill-on-job-close protects assigned child trees; force termination between suspended creation and assignment is not covered.',
        'old_orphans':'No process-name scan or termination of earlier sessions or unrelated applications.',
        'production_sha256':{name:digest(SOURCE/'console'/name) for name in production}}
write_json(SOURCE/'verification/changes156.json',report)
shutil.copy2(Path(__file__),SOURCE/'verification/package156.py')
build=json.loads((SOURCE/'BUILD.json').read_text())
build.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',
             generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
             release_changes='PC console exit releases owned child processes and logs; launcher uses temporary working directory; reconnect closes retired maintenance channels and joins collectors outside the state lock.',
             rebuilt_binaries=[],reused_binaries=list(build['built_binaries']),
             native_production_changes=[],release_changed_native_source_files=[],
             hardware_verified=False,verification_report='verification/changes156.json',
             release_baseline={'console':'1.0.155','firmware_build':BUILD,'previous_tests_are_historical':True},
             tests={'console156':tests,'firmware155_validation':'unchanged native code and exact firmware archive; prior verification remains in source'},
             shutdown_lifecycle=report)
write_json(SOURCE/'BUILD.json',build)
manifest=json.loads((SOURCE/'console/BUILD_MANIFEST.json').read_text())
manifest.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=build['generated_at_utc'],
                tests_run_in_release=tests,shutdown_lifecycle=report,
                merge_verification={'baseline_console':'1.0.155','native_and_firmware_unchanged':True,'report':'verification/changes156.json'},
                hardware_verified=False)
manifest['files']=records(SOURCE/'console',('BUILD_MANIFEST.json',));write_json(SOURCE/'console/BUILD_MANIFEST.json',manifest)
if CONSOLE.exists():shutil.rmtree(CONSOLE)
copy_tree(SOURCE/'console',CONSOLE)
OUT.mkdir(exist_ok=True);console_zip=OUT/(CONSOLE.name+'.zip')
with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as package:
    for n,p in files(CONSOLE).items():package.write(p,CONSOLE.name+'/'+n)
with zipfile.ZipFile(console_zip) as package:
    assert package.testzip() is None
    assert {n.removeprefix(CONSOLE.name+'/'):hashlib.sha256(package.read(n)).hexdigest() for n in package.namelist()}==hashes(CONSOLE)
code='''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.156' and info['build']=='1fa8438-feetech-ft6-control.34'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release156-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
importer=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,env={**os.environ,'PYTHONPATH':str(CONSOLE)},text=True,capture_output=True,check=True)
write_json(SOURCE/'verification/release-audit156.json',{'console_version':VERSION,'build':BUILD,
          'firmware_sha256':digest(SOURCE/payload),'production_firmware_importer':json.loads(importer.stdout),
          'native_source_hashes_verified':True,'packaging_unchanged':True,'windows_native_tested':False,'hardware_tested':False})
source_archive=OUT/(SOURCE.name+'.tar.gz');make_tar(SOURCE,source_archive);verify_tar(SOURCE,source_archive)
sums=OUT/'SHA256SUMS-v1.0.156.txt';sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
print(json.dumps({'console':str(console_zip),'source':str(source_archive),'checksums':str(sums),
      'console_bytes':console_zip.stat().st_size,'source_bytes':source_archive.stat().st_size,
      'console_sha256':digest(console_zip),'source_sha256':digest(source_archive),'firmware_sha256':digest(SOURCE/payload)},indent=2))

