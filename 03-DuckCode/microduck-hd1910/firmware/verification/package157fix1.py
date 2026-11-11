"""Package the PC-only 157-Fix1 release; assert original control.35 bytes unchanged."""
from pathlib import Path
import datetime,hashlib,json,os,re,subprocess,sys,tarfile,zipfile
SOURCE=Path(__file__).resolve().parents[1]
BASELINE=SOURCE.with_name('Microduck-Source-R17-v1.0.157')
CONSOLE=SOURCE/'console';OUT=SOURCE.parents[2]/'output'
VERSION='1.0.157-Fix1';BUILD='1fa8438-feetech-ft6-control.35'
CACHES={'.git','__pycache__','target','.pytest_cache','.venv','node_modules'}
def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def files(root,exclude=()):
 return {p.relative_to(root).as_posix():p for p in sorted(root.rglob('*')) if p.is_file() and not CACHES.intersection(p.relative_to(root).parts) and p.relative_to(root).as_posix() not in exclude}
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def records(root,exclude=()):return [{'path':name,'bytes':p.stat().st_size,'sha256':digest(p)} for name,p in files(root,exclude).items()]
def main():
 runs=json.loads((SOURCE/'verification/fix157-tests.json').read_text());assert all(run['exit_code']==0 for run in runs)
 counts={run['name']:int(re.search(r'Ran (\d+) tests',(SOURCE/run['log']).read_text()).group(1)) for run in runs if run['name'] in {'pc-fix','streams'}}
 assert counts=={'pc-fix':38,'streams':32},counts
 for run in runs:run['sha256']=digest(SOURCE/run['log'])
 tests={'python_passed':sum(counts.values()),'browser_scripts_passed':len(runs)-2,'runs':runs,'robot_hardware_tested':False,'windows_native_tested':False,'native_suite_rerun':False,'full_historical_suite_rerun':False,'socket_boundary_note':'Executor prohibits AF_UNIX creation. Production framing/request tests substitute loopback TCP at the OS socket boundary.'}
 # Every native source and every installed payload is exactly the prior release.
 old_native=json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())['native_source_sha256']
 for name,sha in old_native.items():assert digest(SOURCE/name)==sha,name
 payload=json.loads((SOURCE/'packaging/install-files.json').read_text())
 for name in set(payload)|{'install-files.json','SHA256SUMS'}:assert digest(SOURCE/'packaging'/name)==digest(BASELINE/'packaging'/name),name
 firmware=CONSOLE/'updates/Microduck-Robotd-FT6-R17.tar.gz'
 firmware_sha=digest(firmware);assert firmware_sha==digest(BASELINE/'console/updates'/firmware.name)=='65595d5127407dcb85b150ebc4fbc9dafc363ca5d0774faab6ac570eaf40da66'
 changed=[name for name,p in files(SOURCE).items() if not (BASELINE/name).is_file() or digest(p)!=digest(BASELINE/name)]
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 report={'console_version':VERSION,'service_build':BUILD,'release_baseline':BASELINE.name,'firmware_reinstall_required':False,'firmware_archive_byte_identical':True,'firmware_sha256':firmware_sha,'native_sources_unchanged':True,'installed_payloads_unchanged':True,'model_weights_unchanged':True,'added_robot_polling':False,'added_50hz_work':False,'removed_shortcut':{'button':'management-kick-right','service_action':'run-skill','rb_official_input_preserved':True},'changes':['Preserve healthy input WebSocket/SSH during service work and ordinary action refusal; neutralize input once on explicit restart.','Clear robotd endpoint state after subscription ACK while keeping independent ToF and raw connection generation.','Expose four-stage startup snapshots to the browser and PC checks.','Disable gated skill buttons using already received fresh motion/policy/model/HOME/IMU/torque state.','Default workflow log plus full detail log using the original single writer thread.'],'changed_files':changed,'tests':tests,'previous_native_test_results':'Historical v157 native results retained in verification/changes157.json; not rerun in this PC-only release.'}
 write(SOURCE/'verification/changes157fix1.json',report)
 build=json.loads((BASELINE/'BUILD.json').read_text());build.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,release_changes='PC connection handoff, persistent ready input, skill gates, concise logs and removal of redundant kick shortcut.',firmware_reinstall_required=False,rebuilt_binaries=[],reused_binaries=list(build['built_binaries']),native_production_changes=[],tests=tests,verification_report='verification/changes157fix1.json',previous_native_build='verification/native-build157-final.json')
 write(SOURCE/'BUILD.json',build)
 manifest=json.loads((BASELINE/'console/BUILD_MANIFEST.json').read_text());manifest.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,firmware_reinstall_required=False,tests_run_in_release=tests,release_changes='docs/releases/R157-Fix1.md',service_package_sha256=firmware_sha,files=records(CONSOLE,('BUILD_MANIFEST.json',)))
 write(CONSOLE/'BUILD_MANIFEST.json',manifest)
 OUT.mkdir(exist_ok=True)
 console_zip=OUT/f'Microduck-Console-R17-v{VERSION}.zip'
 with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as archive:
  for name,p in files(CONSOLE).items():archive.write(p,f'Microduck-Console-R17-v{VERSION}/'+name)
 with zipfile.ZipFile(console_zip) as archive:
  assert archive.testzip() is None
  zipped={name.split('/',1)[1]:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
 assert zipped=={name:digest(p) for name,p in files(CONSOLE).items()}
 code='''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix1' and info['build']=='1fa8438-feetech-ft6-control.35'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix157-verification')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
 checked=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,env={**os.environ,'PYTHONPATH':str(CONSOLE)},capture_output=True,text=True,check=True)
 audit={'console_version':VERSION,'service_build':BUILD,'firmware_sha256':firmware_sha,'firmware_archive_byte_identical':True,'production_firmware_importer':json.loads(checked.stdout),'zip_files':len(zipped),'tests':tests,'robot_hardware_tested':False,'windows_native_tested':False}
 write(SOURCE/'verification/release-audit157fix1.json',audit)
 source_manifest=json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text());source_manifest.update(console_version=VERSION,release_baseline=BASELINE.name,release_changes='verification/changes157fix1.json',verification='verification/release-audit157fix1.json',firmware_reinstall_required=False,native_sources_unchanged=True)
 write(SOURCE/'R17-SOURCE-MANIFEST.json',source_manifest)
 source_archive=OUT/(SOURCE.name+'.tar.gz')
 with tarfile.open(source_archive,'w:gz',compresslevel=6) as archive:
  for name,p in files(SOURCE).items():archive.add(p,arcname=SOURCE.name+'/'+name,recursive=False)
 with tarfile.open(source_archive,'r:gz') as archive:
  saved={m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
 assert saved=={name:digest(p) for name,p in files(SOURCE).items()}
 sums=OUT/f'SHA256SUMS-v{VERSION}.txt';sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
 print(json.dumps({'files':[{'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)} for p in (console_zip,source_archive,sums)],'tests':{'python_passed':tests['python_passed'],'browser_scripts_passed':tests['browser_scripts_passed']},'firmware_sha256':firmware_sha},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
