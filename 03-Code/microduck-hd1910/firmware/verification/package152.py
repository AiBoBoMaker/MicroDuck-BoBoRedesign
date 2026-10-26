"""Package the verified v152 sources and one rebuilt ARM64 robotd."""
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
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.152'
OLD_CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.151'
OLD_PAYLOAD=BASE/'firmware150/Microduck-Robotd-FT6-R17'
STAGE=BASE/'package152/Microduck-Robotd-FT6-R17'
CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.152'
OUT=BASE/'output'
BUILD='1fa8438-feetech-ft6-control.32'
VERSION='1.0.152'
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
    with tarfile.open(path,'w:gz',compresslevel=9) as archive:
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

native=json.loads((BASE/'native-build152-final.json').read_text())
assert native['exit_code']==0 and native['source_sha256_unchanged'] is True
for name,expected in native['source_sha256'].items():assert digest(SOURCE/name)==expected,name
test_record=json.loads((BASE/'native-tests152-final.json').read_text())
assert test_record['exit_code']==0 and test_record['source_sha256_unchanged'] is True
for name,expected in test_record['source_sha256'].items():assert digest(SOURCE/name)==expected,name
log_names=['native-build152-final.log','native-build152-final.json','native-tests152-final.log','native-tests152-final.json',
           'python-recovery152.log','python-diagnostic152.log','python-gamepad152.log','python-console152.log','frontend-startup152.log','frontend-gamepad152.log']
for name in ['python-recovery152.log','python-diagnostic152.log','python-gamepad152.log','python-console152.log']:
    log=(BASE/name).read_text();assert re.search(r'\nOK\s*$',log),name
for name in ['frontend-startup152.log','frontend-gamepad152.log']:assert (BASE/name).read_text().startswith('PASS'),name
rust=(SOURCE/'robotd/src/main.rs').read_text()+(SOURCE/'robotd/src/feetech_commissioning.rs').read_text()
assert 'retry_feetech_startup' not in rust and 'FEETECH_STARTUP_ATTEMPTS' not in rust
assert 'control.32' in (SOURCE/'robotd/src/feetech_commissioning.rs').read_text()
binary=BASE/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
assert digest(binary)==native['binaries']['robotd'] and BUILD.encode() in binary.read_bytes()
assert digest(SOURCE/'Cargo.lock')==digest(BASE/'source/Microduck-Source-R17-v1.0.150/Cargo.lock')
if STAGE.parent.exists():shutil.rmtree(STAGE.parent)
STAGE.parent.mkdir();copy_tree(OLD_PAYLOAD,STAGE)
shutil.copy2(binary,STAGE/'robotd');(STAGE/'robotd').chmod(0o755)
for name in ['uart-service.py','runtime.py','release_identity.py']:shutil.copy2(SOURCE/'packaging'/name,STAGE/name)
shutil.copy2(SOURCE/'console/docs/releases/R152.md',STAGE/'R152.md')
elf={name:elf_record(STAGE/name) for name in ('robotd','robotctl','padd','sounds','gamepad-r7/gamesir-xboxd')}
native_results=re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', (BASE/'native-tests152-final.log').read_text())
assert len(native_results)==len(test_record['commands']) and all(failed=='0' for _,failed,_ in native_results)
tests={'native_startup':{'passed':sum(int(p) for p,_,_ in native_results),'failed':0,'commands':test_record['commands'],
                         'log':'verification/native-tests152-final.log'},
       'python':{'startup_and_service':41,'diagnostic':4,'gamepad_repair':18,'console_regression':27,'failed':0},
       'frontend':['startup_error_and_diagnostic_download','gamepad_repair'],
       'syntax':['changed Python modules','changed JavaScript modules','service.sh'],
       'arm64_build':{'exit_code':0,'target':native['target'],'source_sha256_unchanged':True,'robotd_sha256':digest(binary)},
       'hardware':{'tested':False,'temperature_verified':False,'reboot_verified':False}}
report={'console_version':VERSION,'service_build':BUILD,'tests':tests,
        'old_same_uart_five_attempts_removed':True,'startup_max_uart_opens':2,
        'no_new_steady_state_work':True,'hardware_tested':False,
        'evidence':{'failed_startup':'All 15 servo torque readback responses missing; ticks=0 before IMU identity read',
                    'later_old_build':'Same control.31 build later reported ready IMU and approximately 50 Hz',
                    'inference':'Prioritize UART/startup state; specific kernel/radio root cause is not established',
                    'ssh_failure':'Requires kernel/network evidence; not declared fixed by the UART change'}}
write_json(SOURCE/'verification/recovery152.json',report)
for name in log_names:shutil.copy2(BASE/name,SOURCE/'verification'/name)
shutil.copy2(BASE/'run152.py',SOURCE/'verification/run152.py')
shutil.copy2(Path(__file__),SOURCE/'verification/package152.py')
for name in ('python-diagnostic152.log','frontend-startup152.log','python-gamepad152.log','frontend-gamepad152.log'):
    shutil.copy2(BASE/name,SOURCE/'console/verification'/name)
build=json.loads((SOURCE/'BUILD.json').read_text())
build.update(build=BUILD,console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',
             generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),hardware_verified=False,
             tests=tests,built_binaries=elf,rebuilt_binaries=['robotd'],
             reused_binaries=['robotctl','padd','sounds','gamepad-r7/gamesir-xboxd'],
             release_changes='Replace same-UART five retries with at most one complete UART reopen and generation-scoped FIFO/IRQ setup; require live control for service startup; add read-only boot diagnostic export.',
             native_production_changes=['robotd/src/main.rs','robotd/src/feetech_commissioning.rs','duck-control/src/feetech.rs'],
             release_changed_native_source_files=['robotd/src/main.rs','robotd/src/feetech_commissioning.rs','duck-control/src/feetech.rs'],
             verification_report='verification/recovery152.json',
             release_baseline={'console':'1.0.151','firmware_build':'1fa8438-feetech-ft6-control.31','previous_tests_are_historical':True})
write_json(SOURCE/'BUILD.json',build);write_json(STAGE/'BUILD.json',build)
write_json(SOURCE/'ELF-CHECK.json',elf);write_json(STAGE/'ELF-CHECK.json',elf)
write_json(STAGE/'install-files.json',list(files(STAGE,('SHA256SUMS','install-files.json'))))
(STAGE/'SHA256SUMS').write_text(''.join(f"{row['sha256']}  {row['path']}\n" for row in records(STAGE,('SHA256SUMS',))))
allowed={'robotd','uart-service.py','runtime.py','release_identity.py','R152.md','BUILD.json','ELF-CHECK.json','install-files.json','SHA256SUMS'}
payload_changes=changed(hashes(OLD_PAYLOAD),hashes(STAGE))
assert set(payload_changes)<=allowed,payload_changes
for n,p in files(STAGE).items():
    dest=SOURCE/'packaging'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
archive=SOURCE/'console/updates/Microduck-Robotd-FT6-R17.tar.gz'
make_tar(STAGE,archive);verify_tar(STAGE,archive)
assert archive.stat().st_size<=32*1024*1024
manifest=json.loads((SOURCE/'console/BUILD_MANIFEST.json').read_text())
manifest.update(console_version=VERSION,service_build=BUILD,source_distribution=SOURCE.name+'.tar.gz',
                service_package_sha256=digest(archive),hardware_verified=False,generated_at_utc=build['generated_at_utc'],
                tests_run_in_release=tests,
                merge_verification={'baseline_console':'1.0.151','baseline_native_build':'control.31','hardware_tested':False,
                                    'payload_changed_files':payload_changes,'report':'verification/recovery152.json'},
                reboot_recovery=build['reboot_recovery'])
manifest['gamepad_connection_repair'].update(service_payload_rebuilt=True,service_package_unchanged=False,
                                            implementation_inherited_from='1.0.151')
manifest['gamepad_connection_repair'].pop('service_payload_reused_from',None)
manifest['files']=records(SOURCE/'console',('BUILD_MANIFEST.json',))
write_json(SOURCE/'console/BUILD_MANIFEST.json',manifest)
if CONSOLE.exists():shutil.rmtree(CONSOLE)
copy_tree(SOURCE/'console',CONSOLE)
console_zip=OUT/(CONSOLE.name+'.zip');OUT.mkdir(exist_ok=True)
with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as package:
    for n,p in files(CONSOLE).items():package.write(p,CONSOLE.name+'/'+n)
with zipfile.ZipFile(console_zip) as package:
    assert package.testzip() is None
    assert {n.removeprefix(CONSOLE.name+'/'):hashlib.sha256(package.read(n)).hexdigest() for n in package.namelist()}==hashes(CONSOLE)
code="""import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.152' and info['build']=='1fa8438-feetech-ft6-control.32'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release152-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
"""
importer=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
                         env={**os.environ,'PYTHONPATH':str(CONSOLE)},text=True,capture_output=True,check=True)
audit={'version':VERSION,'build':BUILD,'payload_changed_files':payload_changes,
       'robotctl_padd_bridge_models_calibration_byte_identical':True,
       'native_source_hashes_verified':True,'old_same_handle_retries_absent':True,
       'production_importer':json.loads(importer.stdout),'hardware_tested':False}
write_json(SOURCE/'verification/release-audit152.json',audit)
source_archive=OUT/(SOURCE.name+'.tar.gz');make_tar(SOURCE,source_archive);verify_tar(SOURCE,source_archive)
sums=OUT/'SHA256SUMS-v1.0.152.txt'
sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
print(json.dumps({'console':str(console_zip),'source':str(source_archive),'checksums':str(sums),'audit':audit},ensure_ascii=False,indent=2))
