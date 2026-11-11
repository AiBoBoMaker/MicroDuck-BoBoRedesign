"""Package v154 with archive-verified baseline bytes and intact ARM libraries."""
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
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.154'
OLD_CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.151'
OLD_PAYLOAD=BASE/'firmware154-base/Microduck-Robotd-FT6-R17'
STAGE=BASE/'package154/Microduck-Robotd-FT6-R17'
CONSOLE=BASE/'work/Microduck-Console-R17-v1.0.154'
OUT=BASE/'output'
BUILD='1fa8438-feetech-ft6-control.33'
VERSION='1.0.154'
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

# Validate every production source fingerprint before using a cached binary.
native=json.loads((BASE/'native-build154-final.json').read_text())
test_record=json.loads((BASE/'native-tests154-final.json').read_text())
gains=json.loads((BASE/'native-gain-kick154.json').read_text())
for record in (native,test_record,gains):
    assert record['exit_code']==0 and record['source_sha256_unchanged'] is True
    for name,expected in record.get('source_sha256',record.get('source_sha256_after',{})).items():
        assert digest(SOURCE/name)==expected,name
assert gains['passed']==135 and gains['failed']==0
native_results=re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', (BASE/'native-tests154-final.log').read_text())
assert len(native_results)==len(test_record['commands']) and all(f=='0' for _,f,_ in native_results)
backend=(BASE/'python-backend154.log').read_text()
assert re.search(r'\nOK\s*$',backend) and re.findall(r'Ran (\d+) tests',backend)==['74']
frontend=(SOURCE/'console/verification/frontend-controls154.log').read_text()
assert len(re.findall(r'^PASS',frontend,re.M))==3
binary=BASE/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
assert digest(binary)==native['binaries']['robotd'] and BUILD.encode() in binary.read_bytes()
assert digest(SOURCE/'Cargo.lock')==digest(BASE/'source/Microduck-Source-R17-v1.0.153/Cargo.lock')
rust=(SOURCE/'robotd/src/main.rs').read_text()+(SOURCE/'robotd/src/feetech_commissioning.rs').read_text()
assert 'retry_feetech_startup' not in rust and 'FEETECH_STARTUP_ATTEMPTS' not in rust
profile=json.loads((SOURCE/'config/r17-management.json').read_text())
assert all(json.loads((SOURCE/n).read_text())==profile for n in ('packaging/management-profile.json','console/management-profile.json'))
assert 'servo' not in profile['defaults'] and len(profile['builtin_models'])==5
assert not any(r['slot']=='stand' or 'import_supported' in r for r in profile['actions'])
assert not any(r['id']=='a481d9f211f31d9476ab1a319fe362a2' for r in profile['builtin_models'])
assert all(not (SOURCE/n).exists() for n in ('packaging/advanced_parameters.py','packaging/model_preflight.py','duck-control/src/hd1910_test.rs'))

baseline=json.loads((BASE/'baseline-restored154.json').read_text())
assert baseline['declared_original_checksums_verified'] is True
assert digest(Path(baseline['archive']))==baseline['archive_sha256']
assert hashes(OLD_PAYLOAD)=={n:r['sha256'] for n,r in baseline['files'].items()}
if STAGE.parent.exists():shutil.rmtree(STAGE.parent)
STAGE.parent.mkdir();copy_tree(OLD_PAYLOAD,STAGE)
assert hashes(STAGE)==hashes(OLD_PAYLOAD)
# Overlay only files present in the verified release payload. Deleted source
# modules are removed here rather than resurrected from the historical baseline.
for name in files(OLD_PAYLOAD):
    if name.startswith('models/') or name in {'BUILD.json','ELF-CHECK.json','SHA256SUMS','install-files.json','robotd'}:continue
    src=SOURCE/'packaging'/name
    if src.exists():
        shutil.copy2(src,STAGE/name)
        assert digest(src)==digest(STAGE/name)
    else:(STAGE/name).unlink()
shutil.copy2(binary,STAGE/'robotd');(STAGE/'robotd').chmod(0o755)
shutil.rmtree(STAGE/'models')
for row in profile['builtin_models']:
    ident=row['id'];copy_tree(SOURCE/'packaging/models'/ident,STAGE/'models'/ident)
    assert hashes(STAGE/'models'/ident)==hashes(SOURCE/'packaging/models'/ident)
shutil.copy2(SOURCE/'console/docs/releases/R154.md',STAGE/'R154.md')
assert not (STAGE/'models/a481d9f211f31d9476ab1a319fe362a2').exists()
sys.path.insert(0,str(SOURCE/'packaging'))
from elf_integrity import validate_bundle
integrity=validate_bundle(STAGE)
elf={n:elf_record(STAGE/n) for n in ('robotd','robotctl','padd','sounds','gamepad-r7/gamesir-xboxd',
    'onnxruntime/libonnxruntime.so.1.28.0','onnxruntime/libonnxruntime_providers_shared.so')}
for n in elf:
    if n!='robotd':assert digest(STAGE/n)==digest(OLD_PAYLOAD/n),n
library=STAGE/'onnxruntime/libonnxruntime.so.1.28.0'
assert library.stat().st_size==20591712
assert digest(library)=='f1ec1a08eb99bd6e5401340f0a2b101381bf4694415480291dc13bcaa30f9ec7'
arm=json.loads((BASE/'arm-policy154.json').read_text())
assert arm['robotd_sha256']==digest(STAGE/'robotd') and arm['library_sha256']==digest(library)
assert len(arm['results'])==5
for r in arm['results']:
    assert r['exit_code']==0 and r['result']=={'actions':14,'input':'obs','observations':61,'valid':True}
    assert digest(STAGE/'models'/r['id']/'policy.onnx')==r['model_sha256']
# Existing builtin weights and training contracts remain byte-for-byte intact.
for row in profile['builtin_models']:
    old=OLD_PAYLOAD/'models'/row['id']
    if old.exists():assert hashes(old)==hashes(STAGE/'models'/row['id'])
logs=['native-build154-final.log','native-build154-final.json','native-tests154-final.log','native-tests154-final.json',
      'native-tests154-first.log','native-tests154-first.json','native-tests154-unfiltered-restored.log',
      'native-gain-kick154.log','native-gain-kick154.json','native-gain-kick154-first.log',
      'python-backend154.log','python-packaging154.log','python-backend154-integration-initial.log',
      'python-identity154.log','host-ort-restored154.json','baseline-restored154.json','restore_baseline154.py','arm-policy154.json','run_arm154.py','run154.py']
logs += [r['log'] for r in arm['results']]
for name in logs:shutil.copy2(BASE/name,SOURCE/'verification'/name)
shutil.copy2(BASE/'python-backend154.log',SOURCE/'console/verification/python-backend154.log')
shutil.copy2(Path(__file__),SOURCE/'verification/package154.py')
tests={'duck_control':{'passed':135,'failed':0,'log':'verification/native-gain-kick154.log'},
       'robotd_focused':{'passed':sum(int(p) for p,_,_ in native_results),'failed':0,'commands':test_record['commands'],'log':'verification/native-tests154-final.log'},
       'python_backend':{'passed':74,'failed':0,'log':'verification/python-backend154.log','scope':'55 targeted feature tests and 19 repaired historical fixture checks; not a claim of all discovery passing'},
       'frontend':{'passed':3,'log':'console/verification/frontend-controls154.log'},
       'arm64_policy_load':{'passed':5,'failed':0,'record':'verification/arm-policy154.json'},
       'hardware':{'tested':False,'temperature_verified':False,'reboot_verified':False}}
report={'console_version':VERSION,'service_build':BUILD,'tests':tests,'hardware_tested':False,
        'servo':{'p_source':'model contract kp_fw; current builtins 5','scope':'all 15 including mouth','p_write_register':50,'p_write_bytes':1,'register_48_written':False,'register_51_written':False,'relax_restores_prior_p_only':True,'preserves_existing_d_and_torque_limit':True,'upgrade_removes_old_test_json':True},
        'models':{'runtime_count':5,'model_import_ui_api_cli_removed':True,'firmware_zip_upload_preserved':True,'right_kick_id':'67ad09d82f4865d222a7ae06f250cf9f','one_shot_seconds':0.5,'raw_training_assets_unchanged':True},
        'recovery':{'stand_test_removed_from_configuration':True,'teacher_absent_from_runtime_payload':True,'teacher_source_fixture_retained':True,'walk_union_handles_recovery':True,'default_lb':'kick_left','left_kick_model_bound':False,'default_rb':'kick_right','custom_pad_bindings_preserved':True},
        'firmware_display':{'source':'verified bundle_info.build','hardcoded_18_removed':True,'failure_clears_prior_label':True},
        'inherited_fixes':{'complete_arm_ort':True,'ssh_endpoint_errors_separate':True,'startup_max_uart_opens':2,'same_handle_retry_removed':True},
        'inference_hz':50,'no_new_steady_state_polling':True}
write_json(SOURCE/'verification/changes154.json',report)
build=json.loads((SOURCE/'BUILD.json').read_text())
obsolete=['default_servo_test_draft','servo_test_enabled_on_upgrade','servo_test_config','parameter_apply','temporary_modules','manual_recovery_test','manual_lb_recovery']
for key in obsolete:build.pop(key,None)
models=build['models'];models.pop('stand',None)
kickid='67ad09d82f4865d222a7ae06f250cf9f'
models['kick_right']={'id':kickid,'sha256':digest(STAGE/'models'/kickid/'policy.onnx'),'task':'Mjlab-BallKick-Flat-MicroDuck','epochs':10000,'num_envs':4096,'base_action_scale':1.0,'head_alpha':1.0,'legs_alpha':1.0,'target_filter':'passthrough','duration_seconds':0.5,'deployment_verified':False}
execution=json.loads((STAGE/'models/1cbf8730eadd75a5704332c9f3c10f60/deployment-execution.json').read_text())
build['joint_execution'].update(profile=execution,profile_sha256=digest(STAGE/'models/1cbf8730eadd75a5704332c9f3c10f60/deployment-execution.json'))
build.update(build=BUILD,console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',
             generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),hardware_verified=False,
             tests=tests,built_binaries=elf,rebuilt_binaries=['robotd'],reused_binaries=['robotctl','padd','sounds','gamepad-r7/gamesir-xboxd'],
             release_changes='Remove servo override and model import; contract P-only write preserves 48/51; integrate original right-kick builtin on RB; retire separate LB teacher; display verified firmware build. Retain v153 library/startup/SSH fixes.',
             native_production_changes=changed(native['source_sha256'],json.loads((BASE/'native-build152-final.json').read_text())['source_sha256']),
             release_changed_native_source_files=[n for n in native['source_sha256'] if digest(SOURCE/n)!=digest(BASE/'source/Microduck-Source-R17-v1.0.153'/n)],
             verification_report='verification/changes154.json',runtime_model_count=5,
             release_baseline={'console':'1.0.153','firmware_build':'1fa8438-feetech-ft6-control.32','previous_tests_are_historical':True},
             servo_register_policy=report['servo'],builtin_controls=report['models'],standalone_recovery_retired=report['recovery'])
build['action_replacement_ids']['kick_right']=kickid
build['runtime_integrity'].update(bytes=library.stat().st_size,sha256=digest(library),original_archive_sha256=baseline['archive_sha256'],elf_validation=integrity)
write_json(SOURCE/'BUILD.json',build);write_json(STAGE/'BUILD.json',build)
write_json(SOURCE/'ELF-CHECK.json',elf);write_json(STAGE/'ELF-CHECK.json',elf)
write_json(STAGE/'install-files.json',list(files(STAGE,('SHA256SUMS','install-files.json'))))
(STAGE/'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {r['path']}\n" for r in records(STAGE,('SHA256SUMS',))))
payload_changes=changed(hashes(OLD_PAYLOAD),hashes(STAGE))
# Sync the actual runtime payload into the source distribution without reviving
# retired modules. The unbound old teacher remains only as a source test fixture.
for n,p in files(STAGE).items():
    dest=SOURCE/'packaging'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    assert digest(dest)==digest(p)
validate_bundle(SOURCE/'packaging')
archive=SOURCE/'console/updates/Microduck-Robotd-FT6-R17.tar.gz'
make_tar(STAGE,archive);verify_tar(STAGE,archive)
assert archive.stat().st_size<=32*1024*1024
manifest=json.loads((SOURCE/'console/BUILD_MANIFEST.json').read_text())
for key in obsolete:manifest.pop(key,None)
manifest.update(console_version=VERSION,service_build=BUILD,source_distribution=SOURCE.name+'.tar.gz',
                service_package_sha256=digest(archive),hardware_verified=False,generated_at_utc=build['generated_at_utc'],
                models=models,joint_execution=build['joint_execution'],tests_run_in_release=tests,
                merge_verification={'baseline_console':'1.0.153','baseline_native_build':'control.32','hardware_tested':False,'payload_changed_files':payload_changes,'report':'verification/changes154.json'},
                reboot_recovery=build['reboot_recovery'],runtime_integrity=build['runtime_integrity'],
                servo_register_policy=report['servo'],builtin_controls=report['models'],standalone_recovery_retired=report['recovery'],
                firmware_version_display=report['firmware_display'])
manifest['gamepad_connection_repair'].update(service_payload_rebuilt=True,service_package_unchanged=False)
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
code='''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.154' and info['build']=='1fa8438-feetech-ft6-control.33'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release154-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
importer=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
                         env={**os.environ,'PYTHONPATH':str(CONSOLE)},text=True,capture_output=True,check=True)
audit={'version':VERSION,'build':BUILD,'payload_changed_files':payload_changes,
       'unchanged_native_binaries':['robotctl','padd','sounds','gamepad-r7/gamesir-xboxd'],
       'existing_builtin_asset_bytes_unchanged':True,'native_source_hashes_verified':True,
       'production_firmware_importer':json.loads(importer.stdout),'original_baseline_verified':True,
       'runtime_integrity':build['runtime_integrity'],'hardware_tested':False}
write_json(SOURCE/'verification/release-audit154.json',audit)
source_archive=OUT/(SOURCE.name+'.tar.gz');make_tar(SOURCE,source_archive);verify_tar(SOURCE,source_archive)
sums=OUT/'SHA256SUMS-v1.0.154.txt'
sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
print(json.dumps({'console':str(console_zip),'source':str(source_archive),'checksums':str(sums),'console_bytes':console_zip.stat().st_size,'source_bytes':source_archive.stat().st_size,'console_sha256':digest(console_zip),'source_sha256':digest(source_archive),'firmware_sha256':digest(archive)},ensure_ascii=False,indent=2))
