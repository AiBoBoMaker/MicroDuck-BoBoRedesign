"""Package v153 with archive-verified baseline bytes and intact ARM libraries."""
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
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.153'
OLD_CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.151'
OLD_PAYLOAD=BASE/'firmware153-base/Microduck-Robotd-FT6-R17'
STAGE=BASE/'package153/Microduck-Robotd-FT6-R17'
CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.153'
OUT=BASE/'output'
BUILD='1fa8438-feetech-ft6-control.32'
VERSION='1.0.153'
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
           'python-integrity153.log','python-diagnostic153.log','python-connection153.log','frontend-startup153.log','frontend-gamepad153.log']
for name in ['python-integrity153.log','python-diagnostic153.log']:
    log=(BASE/name).read_text();assert re.search(r'\nOK\s*$',log),name
for name in ['frontend-startup153.log','frontend-gamepad153.log']:assert (BASE/name).read_text().startswith('PASS'),name
connection_tests=(BASE/'python-connection153.log').read_text()
assert re.findall(r'Ran (\d+) tests',connection_tests)==['9','20']
assert len(re.findall(r'^OK\s*$',connection_tests,re.M))==2
rust=(SOURCE/'robotd/src/main.rs').read_text()+(SOURCE/'robotd/src/feetech_commissioning.rs').read_text()
assert 'retry_feetech_startup' not in rust and 'FEETECH_STARTUP_ATTEMPTS' not in rust
assert 'control.32' in (SOURCE/'robotd/src/feetech_commissioning.rs').read_text()
binary=BASE/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
assert digest(binary)==native['binaries']['robotd'] and BUILD.encode() in binary.read_bytes()
assert digest(SOURCE/'Cargo.lock')==digest(BASE/'source/Microduck-Source-R17-v1.0.150/Cargo.lock')
if STAGE.parent.exists():shutil.rmtree(STAGE.parent)
STAGE.parent.mkdir();copy_tree(OLD_PAYLOAD,STAGE)
baseline=json.loads((BASE/'baseline-restored153.json').read_text())
assert baseline['declared_original_checksums_verified'] is True
assert digest(Path(baseline['archive']))==baseline['archive_sha256'],'Original archive changed after restoration'
assert hashes(OLD_PAYLOAD)=={name:r['sha256'] for name,r in baseline['files'].items()}
assert hashes(STAGE)==hashes(OLD_PAYLOAD),'Baseline copy differs from original archive'
shutil.copy2(binary,STAGE/'robotd');(STAGE/'robotd').chmod(0o755)
for name in ['uart-service.py','runtime.py','release_identity.py','elf_integrity.py','service.sh','install-files.py']:shutil.copy2(SOURCE/'packaging'/name,STAGE/name)
shutil.copy2(SOURCE/'console/docs/releases/R153.md',STAGE/'R153.md')
sys.path.insert(0,str(SOURCE/'packaging'))
from elf_integrity import validate_bundle
integrity=validate_bundle(STAGE)
elf={name:elf_record(STAGE/name) for name in ('robotd','robotctl','padd','sounds','gamepad-r7/gamesir-xboxd',
    'onnxruntime/libonnxruntime.so.1.28.0','onnxruntime/libonnxruntime_providers_shared.so')}
library=STAGE/'onnxruntime/libonnxruntime.so.1.28.0'
assert library.stat().st_size==20591712
assert digest(library)=='f1ec1a08eb99bd6e5401340f0a2b101381bf4694415480291dc13bcaa30f9ec7'
reproduction=json.loads((BASE/'sigbus-repro/reproduction153.json').read_text())
assert len(reproduction['results'])==12
assert reproduction['new_robotd']['sha256']==digest(STAGE/'robotd')
assert reproduction['libraries']['complete']['sha256']==digest(library)
assert reproduction['libraries']['complete']['bytes']==library.stat().st_size
assert all(r['code']==(0 if r['library']=='complete' else -7) for r in reproduction['results'])
shutil.copy2(BASE/'sigbus-repro/reproduction153.json',SOURCE/'verification/reproduction153.json')
shutil.copy2(BASE/'sigbus-repro/truncated-sigbus-strace.log',SOURCE/'verification/truncated-sigbus-strace153.log')
shutil.copy2(BASE/'baseline-restored153.json',SOURCE/'verification/baseline-restored153.json')
shutil.copy2(BASE/'restore_baseline153.py',SOURCE/'verification/restore_baseline153.py')
native_results=re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', (BASE/'native-tests152-final.log').read_text())
assert len(native_results)==len(test_record['commands']) and all(failed=='0' for _,failed,_ in native_results)
tests={'inherited_unchanged_native_startup':{'passed':sum(int(p) for p,_,_ in native_results),'failed':0,'commands':test_record['commands'],
                         'log':'verification/native-tests152-final.log'},
       'python':{'elf_and_install_integrity':23,'diagnostic':5,'connection_recovery':4,'raw_telemetry_and_socket':20,'failed':0},
       'arm64_runtime':{'new_complete_library_models_passed':5,'old_complete_library_models_passed':5,
                        'truncated_library_sigbus_reproduced':2,'record':'verification/reproduction153.json'},
       'frontend':['startup_error_and_diagnostic_download','gamepad_repair'],
       'syntax':['changed Python modules','changed JavaScript modules','service.sh'],
       'inherited_arm64_build':{'binary_built_in':'1.0.152','exit_code':0,'target':native['target'],
                               'source_sha256_unchanged':True,'robotd_sha256':digest(binary)},
       'hardware':{'tested':False,'temperature_verified':False,'reboot_verified':False}}
report={'console_version':VERSION,'service_build':BUILD,'tests':tests,
        'old_same_uart_five_attempts_removed':True,'startup_max_uart_opens':2,
        'no_new_steady_state_work':True,'hardware_tested':False,
        'evidence':{'failed_startup':'v152 robotd received SIGBUS after IPC startup; old control.31 IMU and loop were healthy',
                    'root_cause':'v152 ONNX Runtime library was truncated to 14073856 bytes instead of 20591712',
                    'confirmed':'Same ARM robotd/library/model command crashes with truncated library and succeeds with complete original bytes',
                    'console_connection':'v152 mistook robotd forwarded endpoint resets for SSH login failure; current CMD SSH/ping and live ToF show SSH remained available',
                    'actual_ssh_failure':'True TCP22 reachability/authentication errors are retained separately; not declared fixed by the UART change'}}
write_json(SOURCE/'verification/recovery153.json',report)
for name in log_names:shutil.copy2(BASE/name,SOURCE/'verification'/name)
shutil.copy2(BASE/'run152.py',SOURCE/'verification/run152.py')
shutil.copy2(Path(__file__),SOURCE/'verification/package153.py')
for name in ('python-diagnostic153.log','python-connection153.log','frontend-startup153.log','frontend-gamepad153.log'):
    shutil.copy2(BASE/name,SOURCE/'console/verification'/name)
build=json.loads((SOURCE/'BUILD.json').read_text())
build.update(build=BUILD,console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',
             generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),hardware_verified=False,
             tests=tests,built_binaries=elf,rebuilt_binaries=[],
             reused_binaries=['robotd (verified control.32 build)','robotctl','padd','sounds','gamepad-r7/gamesir-xboxd'],
             release_changes='Restore complete original ONNX Runtime after v152 truncation caused SIGBUS; validate original archive checksums, ELF load bounds and staged-copy hashes; separate authenticated SSH sessions from robotd telemetry failures without new polling; retain control.32 UART behavior; extend read-only SSH diagnostics.',
             native_production_changes=[],release_changed_native_source_files=[],
             verification_report='verification/recovery153.json',
             release_baseline={'console':'1.0.152','firmware_build':'1fa8438-feetech-ft6-control.32','previous_tests_are_historical':True},
             runtime_integrity={'bytes':library.stat().st_size,'sha256':digest(library),'original_archive_sha256':baseline['archive_sha256'],
                                'elf_validation':integrity,'sigbus_reproduced_and_corrected':True})
write_json(SOURCE/'BUILD.json',build);write_json(STAGE/'BUILD.json',build)
write_json(SOURCE/'ELF-CHECK.json',elf);write_json(STAGE/'ELF-CHECK.json',elf)
write_json(STAGE/'install-files.json',list(files(STAGE,('SHA256SUMS','install-files.json'))))
(STAGE/'SHA256SUMS').write_text(''.join(f"{row['sha256']}  {row['path']}\n" for row in records(STAGE,('SHA256SUMS',))))
allowed={'robotd','uart-service.py','runtime.py','release_identity.py','elf_integrity.py','service.sh','install-files.py','R153.md','BUILD.json','ELF-CHECK.json','install-files.json','SHA256SUMS'}
payload_changes=changed(hashes(OLD_PAYLOAD),hashes(STAGE))
assert set(payload_changes)<=allowed,payload_changes
for n,p in files(STAGE).items():
    dest=SOURCE/'packaging'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    assert digest(dest)==digest(p),('Source payload copy differs',n)
validate_bundle(SOURCE/'packaging')
archive=SOURCE/'console/updates/Microduck-Robotd-FT6-R17.tar.gz'
make_tar(STAGE,archive);verify_tar(STAGE,archive)
assert archive.stat().st_size<=32*1024*1024
manifest=json.loads((SOURCE/'console/BUILD_MANIFEST.json').read_text())
manifest.update(console_version=VERSION,service_build=BUILD,source_distribution=SOURCE.name+'.tar.gz',
                service_package_sha256=digest(archive),hardware_verified=False,generated_at_utc=build['generated_at_utc'],
                tests_run_in_release=tests,
                merge_verification={'baseline_console':'1.0.152','baseline_native_build':'control.32','hardware_tested':False,
                                    'payload_changed_files':payload_changes,'report':'verification/recovery153.json'},
                reboot_recovery=build['reboot_recovery'],runtime_integrity=build['runtime_integrity'])
manifest['ssh_connection_recovery']={'authenticated_forward_events':True,'robotd_endpoint_errors_are_not_ssh_errors':True,
                                     'generation_scoped':True,'new_polling':False,'motion_readiness_checks_unchanged':True,
                                     'log':'verification/python-connection153.log'}
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
assert info['console_version']=='1.0.153' and info['build']=='1fa8438-feetech-ft6-control.32'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release153-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
"""
importer=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
                         env={**os.environ,'PYTHONPATH':str(CONSOLE)},text=True,capture_output=True,check=True)
audit={'version':VERSION,'build':BUILD,'payload_changed_files':payload_changes,
       'robotctl_padd_bridge_models_calibration_byte_identical':True,
       'native_source_hashes_verified':True,'old_same_handle_retries_absent':True,
       'production_importer':json.loads(importer.stdout),'original_baseline_verified':True,
       'runtime_integrity':build['runtime_integrity'],'hardware_tested':False}
write_json(SOURCE/'verification/release-audit153.json',audit)
source_archive=OUT/(SOURCE.name+'.tar.gz');make_tar(SOURCE,source_archive);verify_tar(SOURCE,source_archive)
sums=OUT/'SHA256SUMS-v1.0.153.txt'
sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
print(json.dumps({'console':str(console_zip),'source':str(source_archive),'checksums':str(sums),'audit':audit},ensure_ascii=False,indent=2))
