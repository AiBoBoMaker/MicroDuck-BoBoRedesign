"""Package v155 with archive-verified baseline bytes and intact ARM libraries."""
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
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.155'
OLD_CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.151'
OLD_PAYLOAD=BASE/'firmware155-base/Microduck-Robotd-FT6-R17'
STAGE=BASE/'package155/Microduck-Robotd-FT6-R17'
CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.155'
OUT=BASE/'output'
BUILD='1fa8438-feetech-ft6-control.34'
VERSION='1.0.155'
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

native=json.loads((BASE/'native-build155-final.json').read_text())
checks=json.loads((BASE/'native-tests155-final.json').read_text())
for record in (native,checks):
    assert record['exit_code']==0 and record['source_sha256_unchanged'] is True
    for name,expected in record['source_sha256'].items():assert digest(SOURCE/name)==expected,name
binary=BASE/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
assert digest(binary)==native['binaries']['robotd'] and BUILD.encode() in binary.read_bytes()
assert digest(SOURCE/'Cargo.lock')==digest(BASE/'source/Microduck-Source-R17-v1.0.154/Cargo.lock')
python=(BASE/'python-compat155.log').read_text();assert re.search(r'\nOK\s*$',python)
frontend_direction=(SOURCE/'console/verification/frontend-direction155.log').read_text()
assert len(re.findall('^PASS',frontend_direction,re.M))==4
connection=json.loads((SOURCE/'console/verification/frontend-connection155.json').read_text())
assert connection['exit']==0 and len(connection['tests'])==4
assert all(r['exit']==0 for r in connection['tests'])
frontend_connection=(SOURCE/'console/verification/frontend-connection155.log').read_text()
assert len(re.findall('^PASS',frontend_connection,re.M))>=4
baseline=json.loads((BASE/'baseline-restored155.json').read_text())
assert baseline['declared_original_checksums_verified'] is True
assert digest(Path(baseline['archive']))==baseline['archive_sha256']
assert hashes(OLD_PAYLOAD)=={n:r['sha256'] for n,r in baseline['files'].items()}
if STAGE.parent.exists():shutil.rmtree(STAGE.parent)
STAGE.parent.mkdir();copy_tree(OLD_PAYLOAD,STAGE)
assert hashes(STAGE)==hashes(OLD_PAYLOAD)
for n in files(OLD_PAYLOAD):
    if n.startswith('models/') or n in {'robotd','BUILD.json','SHA256SUMS','ELF-CHECK.json','install-files.json'}:continue
    src=SOURCE/'packaging'/n
    assert src.exists(),n
    shutil.copy2(src,STAGE/n)
shutil.copy2(binary,STAGE/'robotd');(STAGE/'robotd').chmod(0o755)
shutil.copy2(SOURCE/'console/docs/releases/R155.md',STAGE/'R155.md')
profile=json.loads((SOURCE/'config/r17-management.json').read_text())
assert len(profile['builtin_models'])==5 and all(json.loads((SOURCE/n).read_text())==profile for n in ('console/management-profile.json','packaging/management-profile.json'))
for row in profile['builtin_models']:
    assert hashes(STAGE/'models'/row['id'])==hashes(SOURCE/'packaging/models'/row['id'])
assert len([p for p in (STAGE/'models').iterdir() if p.is_dir()])==5
assert not any((STAGE/n).exists() for n in ('advanced_parameters.py','model_preflight.py','models/a481d9f211f31d9476ab1a319fe362a2'))
sys.path.insert(0,str(SOURCE/'packaging'))
from elf_integrity import validate_bundle
integrity=validate_bundle(STAGE)
elf={n:elf_record(STAGE/n) for n in ('robotd','robotctl','padd','sounds','gamepad-r7/gamesir-xboxd',
    'onnxruntime/libonnxruntime.so.1.28.0','onnxruntime/libonnxruntime_providers_shared.so')}
for n in elf:
    if n!='robotd':assert digest(STAGE/n)==digest(OLD_PAYLOAD/n),n
library=STAGE/'onnxruntime/libonnxruntime.so.1.28.0'
assert library.stat().st_size==20591712 and digest(library)=='f1ec1a08eb99bd6e5401340f0a2b101381bf4694415480291dc13bcaa30f9ec7'
arm=json.loads((BASE/'arm-policy155.json').read_text())
assert arm['robotd_sha256']==digest(STAGE/'robotd') and arm['library_sha256']==digest(library) and len(arm['results'])==5
for r in arm['results']:
    assert r['exit_code']==0 and r['result']=={'actions':14,'input':'obs','observations':61,'valid':True}
    assert digest(STAGE/'models'/r['id']/'policy.onnx')==r['model_sha256']
native_results=re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', (BASE/'native-tests155-final.log').read_text())
assert len(native_results)==len(checks['commands']) and all(int(p)>0 and f=='0' for p,f,_ in native_results)
logs=['native-build155-final.log','native-build155-final.json','native-tests155-final.log','native-tests155-final.json',
      'python-compat155.log','baseline-restored155.json','restore_baseline155.py','arm-policy155.json','run_arm155.py','run155.py',
      'run_native_home155.py','home-policy155-audit.py','home-policy155-audit.json','home-policy155-native.log']
logs += [r['log'] for r in arm['results']]
logs += [p.name for p in BASE.glob('native-home155-red*') if p.is_file() and p.suffix in {'.log','.json'}]
for n in logs:shutil.copy2(BASE/n,SOURCE/'verification'/n)
shutil.copy2(Path(__file__),SOURCE/'verification/package155.py')
old_native=json.loads((BASE/'native-build154-final.json').read_text())['source_sha256']
changed_native=changed(old_native,native['source_sha256'])
tests={'native_focused':{'passed':sum(int(p) for p,_,_ in native_results),'failed':0,'commands':checks['commands'],'log':'verification/native-tests155-final.log'},
       'frontend_connection':{'scripts':4,'log':'console/verification/frontend-connection155.log'},
       'frontend_direction':{'cases':4,'log':'console/verification/frontend-direction155.log'},
       'python_compatibility':{'passed':int(re.findall(r'Ran (\d+) tests',python)[0]),'failed':0,'log':'verification/python-compat155.log'},
       'arm64_policy_load':{'passed':5,'failed':0,'record':'verification/arm-policy155.json'},
       'hardware':{'tested':False,'temperature_verified':False,'reboot_verified':False}}
report={'console_version':VERSION,'service_build':BUILD,'tests':tests,'hardware_tested':False,
        'connection_notice':{'connecting_and_first_feedback_neutral':True,'real_errors_preserved':True,'prior_generation_reports_not_displayed':True,'new_polling':False},
        'joint_direction':{'source':'saved installation calibration matched by ID and name','all_15':True,'unknown_is_not_assumed_forward':True,'changes_measurements_or_configuration':False},
        'home_return':{'paused_explicit_disable_requests_absolute_home':True,'ready_init_without_sample_keeps_home_destination':True,'web_running_policy_home_remains_direct':True,'existing_init_two_second_interpolation_unchanged':True,'startup_does_not_arm':True,'policy_not_automatically_replayed':True,'new_polling_or_retry_loop':False,'model_gain_filter_pose_changes':False,'softness_root_cause_confirmed_on_robot':False},
        'native_source_changed':changed_native,'inference_hz':50,'no_new_periodic_io_or_inference':True}
write_json(SOURCE/'verification/changes155.json',report)
build=json.loads((SOURCE/'BUILD.json').read_text())
build.update(build=BUILD,console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
             hardware_verified=False,tests=tests,built_binaries=elf,rebuilt_binaries=['robotd'],reused_binaries=['robotctl','padd','sounds','gamepad-r7/gamesir-xboxd'],
             release_changes='Neutral connection progress before first feedback; saved direction for all 15 joints; preserve absolute HOME after sensor pause and lost read while keeping direct web HOME and existing Init interpolation; no gain, filter, model, pose or recurring workload changes.',
             native_production_changes=[n for n in changed_native if '/tests/' not in n and not n.endswith('_tests.rs')],release_changed_native_source_files=changed_native,
             verification_report='verification/changes155.json',release_baseline={'console':'1.0.154','firmware_build':'1fa8438-feetech-ft6-control.33','previous_tests_are_historical':True},
             home_return_fix=report['home_return'],joint_direction_display=report['joint_direction'],connection_notice=report['connection_notice'])
build['runtime_integrity'].update(bytes=library.stat().st_size,sha256=digest(library),original_archive_sha256=baseline['archive_sha256'],elf_validation=integrity)
write_json(SOURCE/'BUILD.json',build);write_json(STAGE/'BUILD.json',build)
write_json(SOURCE/'ELF-CHECK.json',elf);write_json(STAGE/'ELF-CHECK.json',elf)
write_json(STAGE/'install-files.json',list(files(STAGE,('SHA256SUMS','install-files.json'))))
(STAGE/'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {r['path']}\n" for r in records(STAGE,('SHA256SUMS',))))
payload_changes=changed(hashes(OLD_PAYLOAD),hashes(STAGE))
allowed={'robotd','release_identity.py','README.zh-CN.md','BUILD.json','ELF-CHECK.json','SHA256SUMS','install-files.json','R155.md'}
assert set(payload_changes)<=allowed,payload_changes
for n,p in files(STAGE).items():
    dest=SOURCE/'packaging'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);assert digest(dest)==digest(p)
validate_bundle(SOURCE/'packaging')
archive=SOURCE/'console/updates/Microduck-Robotd-FT6-R17.tar.gz'
make_tar(STAGE,archive);verify_tar(STAGE,archive);assert archive.stat().st_size<=32*1024*1024
manifest=json.loads((SOURCE/'console/BUILD_MANIFEST.json').read_text())
manifest.update(console_version=VERSION,service_build=BUILD,source_distribution=SOURCE.name+'.tar.gz',service_package_sha256=digest(archive),hardware_verified=False,
                generated_at_utc=build['generated_at_utc'],tests_run_in_release=tests,home_return_fix=report['home_return'],joint_direction_display=report['joint_direction'],connection_notice=report['connection_notice'],runtime_integrity=build['runtime_integrity'],
                merge_verification={'baseline_console':'1.0.154','baseline_native_build':'control.33','hardware_tested':False,'payload_changed_files':payload_changes,'report':'verification/changes155.json'})
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
assert info['console_version']=='1.0.155' and info['build']=='1fa8438-feetech-ft6-control.34'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release155-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
importer=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,env={**os.environ,'PYTHONPATH':str(CONSOLE)},text=True,capture_output=True,check=True)
audit={'console_version':VERSION,'build':BUILD,'native_sha256':digest(binary),'payload_changed_files':payload_changes,'unchanged_models_and_calibration':True,
       'unchanged_other_native_binaries':True,'native_source_hashes_verified':True,'original_baseline_verified':True,'production_firmware_importer':json.loads(importer.stdout),'hardware_tested':False}
write_json(SOURCE/'verification/release-audit155.json',audit)
source_archive=OUT/(SOURCE.name+'.tar.gz');make_tar(SOURCE,source_archive);verify_tar(SOURCE,source_archive)
sums=OUT/'SHA256SUMS-v1.0.155.txt';sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
print(json.dumps({'console':str(console_zip),'source':str(source_archive),'checksums':str(sums),'console_bytes':console_zip.stat().st_size,'source_bytes':source_archive.stat().st_size,'console_sha256':digest(console_zip),'source_sha256':digest(source_archive),'firmware_sha256':digest(archive)},indent=2))
