#!/usr/bin/env python3
"""Validate the deliverable and explicitly bound the permitted changes."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'base/Microduck-Console-R17-V162.zip'
OUTPUT = Path(sys.argv[1]).resolve()
BUILD = '1fa8438-feetech-ft6-control.40'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read_zip(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n.split('/',1)[1]:z.read(n) for n in z.namelist() if '/' in n and not n.endswith('/')}
def firmware(rows):
    raw = rows['updates/Microduck-Robotd-FT6-R17.tar.gz']
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as t:
        return {m.name.split('/',1)[1]:t.extractfile(m).read() for m in t if m.isfile()}, len(raw)
assert sha(BASE.read_bytes()) == '9e8d82ea6a57dfbfa15592fab980e57a1e67fb2dff1b6e7bfb63f773a2283a5e'
original, current = read_zip(BASE), read_zip(OUTPUT)
old, _ = firmware(original); new, native_bytes = firmware(current)
changed = {n for n in old if old[n]!=new[n]}
expected = {'BUILD.json','ELF-CHECK.json','SHA256SUMS','README.zh-CN.md','robotd','padd','release_identity.py','model_packages.py','robotd-profile.toml'}
assert changed==expected, sorted(changed^expected)
assert set(old)==set(new)
console_changed = {n for n in original if original[n]!=current[n]}
console_expected = {'BUILD_MANIFEST.json','README.zh-CN.md','release_identity.py','updates/Microduck-Robotd-FT6-R17.tar.gz','service_control.py','static/index.html'}
assert console_changed==console_expected, sorted(console_changed^console_expected)
assert not set(original)-set(current)
added_console = set(current)-set(original)
assert added_console and all(n.startswith('verification/v163/') for n in added_console)
for name in old:
    if name not in expected: assert old[name]==new[name], name
for name in ('start.cmd','controls.py','static/control.js','static/webpad-controls.js','remote_input.py','firmware_packages.py'):
    assert original[name]==current[name], name
for name in old:
    if name.startswith(('models/','roller/')): assert new[name]==old[name], name
manifest = json.loads(current['BUILD_MANIFEST.json'])
assert manifest['console_version']=='1.0.163' and manifest['service_build']==BUILD
assert manifest['service_package_sha256']==sha(current['updates/Microduck-Robotd-FT6-R17.tar.gz'])
assert {row['path'] for row in manifest['files']}==set(current)-{'BUILD_MANIFEST.json'}
for row in manifest['files']:
    assert len(current[row['path']])==row['bytes'] and sha(current[row['path']])==row['sha256'], row['path']
inventory = json.loads(new['install-files.json'])
assert set(new)==set(inventory)|{'install-files.json','SHA256SUMS'}
for line in new['SHA256SUMS'].decode().splitlines():
    digest, name = line.split('  ',1); assert sha(new[name])==digest, name
assert BUILD.encode() in new['robotd']
elf = json.loads(new['ELF-CHECK.json'])
for name in ('robotd','padd'):
    assert new[name][:4]==b'\x7fELF' and int.from_bytes(new[name][18:20],'little')==183
    assert new[name]!=old[name] and sha(new[name])==elf[name]['sha256']
    assert new[name]==(ROOT/'packaging'/name).read_bytes()
assert sha(new['roller/standup/policy.onnx'])=='2575b5894bcd8e3fdbe005b1a7b90d9491085726df32000c26cf5b92b7a10ebb'
contract = json.loads(new['roller/standup/deployment-contract.json'])
assert contract['slot'] is None and contract['required_skill_settings'] is None
cfg = tomllib.loads(new['robotd-profile.toml'].decode())
old_cfg = tomllib.loads(old['robotd-profile.toml'].decode())
skills = [s for s in cfg['policy']['skill'] if s['name']=='roller_stand']
assert len(skills)==1
assert skills[0]['duration']==5.0 and skills[0]['chain'] is False and skills[0]['command']==[0,0,0]
without_test = json.loads(json.dumps(cfg)); without_test['policy']['skill']=[s for s in cfg['policy']['skill'] if s['name']!='roller_stand']
assert without_test==old_cfg
assert cfg['pad']['lb']=='kick_left'
assert current['README.zh-CN.md']==(ROOT/'console/README.zh-CN.md').read_bytes()
assert new['README.zh-CN.md']==(ROOT/'packaging/README.zh-CN.md').read_bytes()
assert native_bytes<=40*1024*1024 and OUTPUT.stat().st_size<=64*1024*1024
with tempfile.TemporaryDirectory(prefix='v163-import-') as tmp:
    with zipfile.ZipFile(OUTPUT) as archive: archive.extractall(tmp)
    sys.path.insert(0,str(Path(tmp)/'Microduck-Console-R17-V163'))
    from firmware_packages import PreparedFirmware
    with OUTPUT.open('rb') as stream: prepared = PreparedFirmware(OUTPUT.name,stream,OUTPUT.stat().st_size,'verification')
    assert prepared.info['build']==BUILD
    prepared.close()
result = {'console_version':'1.0.163','build':BUILD,'zip_bytes':OUTPUT.stat().st_size,'zip_sha256':sha(OUTPUT.read_bytes()),
    'firmware_bytes':native_bytes,'all_hashes_verified':True,'production_importer_accepted':True,'hardware_tested':False,
    'baseline':BASE.name,'baseline_sha256':sha(BASE.read_bytes()),'calibration_models_and_service_files_preserved':True,
    'ssh_open_source_and_web_input_preserved':True,'roller_stand_original_contract_preserved':True,
    'roller_stand_trigger':'physical_L3_guarded','manual_test_duration_s':5.0,'automatic_recovery':False,
    'changed_firmware_files':sorted(changed),'changed_console_files':sorted(console_changed)}
(ROOT/'verification/v163/package-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
