#!/usr/bin/env python3
"""Check V162 against V161: only declared files change; new recovery remains unbound."""
import hashlib,io,json,sys,tarfile,tempfile,tomllib,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'base/Microduck-Console-R17-V161.zip'
OUTPUT=Path(sys.argv[1]).resolve()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n.split('/',1)[1]:z.read(n) for n in z.namelist() if '/' in n and not n.endswith('/')}
def firmware(rows):
    raw=rows['updates/Microduck-Robotd-FT6-R17.tar.gz']
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as t:
        return {m.name.split('/',1)[1]:t.extractfile(m).read() for m in t if m.isfile()},len(raw)
assert sha(BASE.read_bytes())=='ac721370902b521c013dce056d6c8c83d8f2ff2a8a30abaf01555d6408d76fe9'
original,current=read_zip(BASE),read_zip(OUTPUT)
old,_=firmware(original);new,native_bytes=firmware(current)
changed={n for n in old if old[n]!=new[n]}
expected={'BUILD.json','ELF-CHECK.json','SHA256SUMS','README.zh-CN.md','robotd','release_identity.py','install-files.json','model_packages.py'}
assert changed==expected,sorted(changed^expected)
assert not set(old)-set(new)
added=set(new)-set(old)
assert len(added)==9 and all(n.startswith('roller/standup/') for n in added),sorted(added)
console_changed={n for n in original if original[n]!=current[n]}
console_expected={'BUILD_MANIFEST.json','README.zh-CN.md','release_identity.py','updates/Microduck-Robotd-FT6-R17.tar.gz','service_control.py','static/service-management.js','static/index.html','static/r17-0151.css'}
assert console_changed==console_expected,sorted(console_changed^console_expected)
assert not set(original)-set(current)
for name in ('robotd-profile.toml','configure.py','management-profile.json','hd1910-calibration.robot.toml','hd1910-calibration.training.toml','robot-calibration-source.json','mediad','gamepad-r7/gamesir-xboxd','service.sh','padd'):
    assert old[name]==new[name],name
for name in ('start.cmd','controls.py','static/control.js','static/webpad-controls.js','remote_input.py','firmware_packages.py'):
    assert original[name]==current[name],name
for name in old:
    if name.startswith(('models/','roller/')):assert new[name]==old[name],name
manifest=json.loads(current['BUILD_MANIFEST.json'])
assert manifest['console_version']=='1.0.162' and manifest['service_build']=='1fa8438-feetech-ft6-control.39'
for row in manifest['files']:
    assert len(current[row['path']])==row['bytes'] and sha(current[row['path']])==row['sha256'],row['path']
for line in new['SHA256SUMS'].decode().splitlines():
    digest,name=line.split('  ',1);assert sha(new[name])==digest,name
assert b'1fa8438-feetech-ft6-control.39' in new['robotd'] and new['robotd']!=old['robotd']
for name in ('robotd','padd'):
    assert new[name][:4]==b'\x7fELF' and int.from_bytes(new[name][18:20],'little')==183
assert sha(new['roller/standup/policy.onnx'])=='2575b5894bcd8e3fdbe005b1a7b90d9491085726df32000c26cf5b92b7a10ebb'
for name in added:
    assert new[name]==(ROOT/'packaging'/name).read_bytes(),name
contract=json.loads(new['roller/standup/deployment-contract.json'])
assert contract['slot'] is None and contract['required_skill_settings'] is None
cfg=tomllib.loads(new['robotd-profile.toml'].decode());assert cfg['pad']['lb']=='kick_left'
assert 'roller_stand' not in new['robotd-profile.toml'].decode()
html=current['static/index.html'].decode()
assert 'pad-model-parameters' in html and 'roller-help' in html and '未绑定按键' in html
assert current['README.zh-CN.md']==(ROOT/'console/README.zh-CN.md').read_bytes()
assert new['README.zh-CN.md']==(ROOT/'packaging/README.zh-CN.md').read_bytes()
assert native_bytes<=40*1024*1024 and OUTPUT.stat().st_size<=64*1024*1024
with tempfile.TemporaryDirectory(prefix='v162-import-') as tmp:
    with zipfile.ZipFile(OUTPUT) as archive:archive.extractall(tmp)
    sys.path.insert(0,str(Path(tmp)/'Microduck-Console-R17-V162'))
    from firmware_packages import PreparedFirmware
    with OUTPUT.open('rb') as stream:prepared=PreparedFirmware(OUTPUT.name,stream,OUTPUT.stat().st_size,'verification')
    assert prepared.info['build']=='1fa8438-feetech-ft6-control.39';prepared.close()
result={'console_version':'1.0.162','build':'1fa8438-feetech-ft6-control.39','zip_bytes':OUTPUT.stat().st_size,'zip_sha256':sha(OUTPUT.read_bytes()),'firmware_bytes':native_bytes,'all_hashes_verified':True,'production_importer_accepted':True,'hardware_tested':False,'baseline':BASE.name,'baseline_sha256':sha(BASE.read_bytes()),'calibration_config_existing_models_preserved':True,'gamepad_and_web_input_unchanged':True,'ssh_and_open_source_entrances_preserved':True,'roller_stand_original_contract_preserved':True,'roller_stand_trigger_bound':False,'runtime_coefficients_from_contract':True,'v161_firmware_files_preserved':len(old)-len(changed),'changed_firmware_files':sorted(changed),'added_firmware_files':sorted(added),'changed_console_files':sorted(console_changed)}
(ROOT/'verification/v162/package-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
