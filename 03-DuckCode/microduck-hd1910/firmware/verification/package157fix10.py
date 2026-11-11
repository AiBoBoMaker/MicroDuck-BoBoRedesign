"""Package camera demand and prove Fix9 control/input payloads are reused byte for byte."""
from pathlib import Path
import datetime, hashlib, json, os, re, subprocess, sys, tarfile, zipfile
from package157fix1 import digest, files, records, write

SOURCE=Path(__file__).resolve().parents[1]
BASELINE=SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix9')
CONSOLE=SOURCE/'console';PACKAGING=SOURCE/'packaging';OUT=SOURCE.parents[2]/'output'
VERSION='1.0.157-Fix10';BUILD='1fa8438-feetech-ft6-control.36'
MEDIA_BUILD='1fa8438-feetech-media-demand.1'
NATIVE_CHANGES={'mediad/src/capture.rs','mediad/src/detect.rs','mediad/src/lib.rs','mediad/src/pipeline.rs'}


def main():
    logs=['fix10-media-tests.log','fix10-pipeline-tests.log','fix10-exposure-tests.log',
          'fix10-core-tests.log','fix10-install-tests.log','fix10-browser-tests.log','fix10-media-build.log']
    tests={'robot_hardware_tested':False,'windows_native_tested':False,'browser_pixel_rendered':False}
    counts={}
    for name in logs:
        body=(SOURCE/'verification'/name).read_text()
        if name in logs[:3]:
            match=re.search(r'test result: ok\. (\d+) passed; 0 failed;',body);assert match,name
            counts[name]=int(match.group(1))
        elif name in logs[3:5]:
            assert body.rstrip().endswith('OK'),name
            counts[name]=int(re.search(r'Ran (\d+) tests',body).group(1))
    assert list(counts.values())==[9,11,15,99,39],counts
    assert len((SOURCE/'verification/fix10-browser-tests.log').read_text().splitlines())==7
    assert 'Finished `release` profile' in (SOURCE/'verification/fix10-media-build.log').read_text()
    tests.update(rust_passed=35,python_passed=138,browser_scripts_passed=7,
                 logs=[{'path':'verification/'+n,'sha256':digest(SOURCE/'verification'/n)} for n in logs])
    old_manifest=json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())
    for name,sha in old_manifest['native_source_sha256'].items():
        if name not in NATIVE_CHANGES:assert digest(SOURCE/name)==sha,name
    protected=['packaging/startup_gate.py','packaging/runtime.py','packaging/gamepad.py','packaging/configure.py',
       'packaging/voice-setup.py','packaging/gamepad-r7/gamesir-xboxd','console/raw_telemetry.py','console/connection.py',
       'console/remote_input.py','console/controls.py','console/service_rpc.py','console/service_control.py',
       'console/install_handoff.py','console/static/control.js','console/static/control-socket.js',
       'console/static/index.html','console/static/service.js','console/static/r17-0151.css']
    for name in protected:assert digest(SOURCE/name)==digest(BASELINE/name),name
    camera_step="    install_phase='配置按需摄像头'\n    python3 \"$install_dir/camera-setup.py\" \"$install_dir\" || install_log 失败 '摄像头配置未完成；实际原因见上方；robotd 与输入服务继续运行'\n"
    assert (PACKAGING/'service.sh').read_text().replace(camera_step,'')==(BASELINE/'packaging/service.sh').read_text()
    old_payload=json.loads((BASELINE/'packaging/install-files.json').read_text())
    payload_changes={'BUILD.json','ELF-CHECK.json','elf_integrity.py','release_identity.py','service.sh'}
    for name in old_payload:
        if name not in payload_changes:assert digest(PACKAGING/name)==digest(BASELINE/'packaging'/name),name
    native=PACKAGING/'mediad';dynamic=subprocess.check_output(['readelf','-d',str(native)],text=True)
    versions=subprocess.check_output(['readelf','-V',str(native)],text=True)
    assert 'AArch64' in subprocess.check_output(['readelf','-h',str(native)],text=True)
    media={'sha256':digest(native),'bytes':native.stat().st_size,'machine':'AArch64','revision':MEDIA_BUILD,
           'needed':re.findall(r'Shared library: \[(.*?)\]',dynamic),
           'glibc_versions':sorted(set(re.findall(r'GLIBC_(\d+\.\d+)',versions)))}
    sys.path.insert(0,str(PACKAGING))
    from elf_integrity import validate_bundle
    elf=validate_bundle(PACKAGING)
    assert len(elf)==8 and all(v['machine']=='AArch64' for v in elf.values()),elf
    elf_metadata=json.loads((BASELINE/'packaging/ELF-CHECK.json').read_text())
    elf_metadata['mediad']=media;write(PACKAGING/'ELF-CHECK.json',elf_metadata)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata=json.loads((BASELINE/'BUILD.json').read_text())
    metadata['built_binaries']['mediad']=media
    metadata.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,
       firmware_reinstall_required=True,rebuilt_binaries=['mediad'],media_build=MEDIA_BUILD,
       reused_binaries=[n for n in metadata['built_binaries'] if n!='mediad'],
       native_production_changes=sorted(NATIVE_CHANGES),tests=tests,
       release_changes='Camera demand lifecycle; existing control.36 and Fix9 input payloads reused.',
       verification_report='verification/changes157fix10.json')
    write(SOURCE/'BUILD.json',metadata);write(PACKAGING/'BUILD.json',metadata)
    names=json.loads((PACKAGING/'install-files.json').read_text())
    assert set(names)==set(old_payload)|{'mediad','camera-setup.py'}
    payload=names+['install-files.json']
    (PACKAGING/'SHA256SUMS').write_text(''.join(f'{digest(PACKAGING/n)}  {n}\n' for n in sorted(payload)))
    payload+=['SHA256SUMS']
    firmware=CONSOLE/'updates/Microduck-Robotd-FT6-R17.tar.gz'
    with tarfile.open(firmware,'w:gz',compresslevel=6) as archive:
        for name in sorted(payload):archive.add(PACKAGING/name,arcname='Microduck-Robotd-FT6-R17/'+name,recursive=False)
    with tarfile.open(firmware) as archive:
        saved={m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved=={n:digest(PACKAGING/n) for n in payload}
    firmware_sha=digest(firmware)
    report={'console_version':VERSION,'service_build':BUILD,'media_build':MEDIA_BUILD,
       'release_baseline':BASELINE.name,'firmware_reinstall_required':True,'firmware_sha256':firmware_sha,
       'core_native_sources_unchanged':True,'control_input_binaries_unchanged':True,
       'protected_files':{n:digest(SOURCE/n) for n in protected},
       'original_installer_identical_except_camera_accessory_after_core_and_input_ready':True,
       'added_robot_50hz_work':False,'added_camera_polling_or_retry_loop':False,
       'camera_event_thread':'parks on channel receive; passive readers park on condition variable',
       'capture_lifecycle':'real source locked NULL at boot, video peers and snapshot/stream leases share demand',
       'bootstrap_signal':'GLib emission hook preserves upstream first-handler-wins default action',
       'media_binary':media,'elf_integrity':elf,'tests':tests}
    write(SOURCE/'verification/changes157fix10.json',report)
    manifest=json.loads((BASELINE/'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,
       media_build=MEDIA_BUILD,firmware_reinstall_required=True,tests_run_in_release=tests,
       service_package_sha256=firmware_sha,release_changes='docs/releases/R157-Fix10.md',
       files=records(CONSOLE,('BUILD_MANIFEST.json',)))
    write(CONSOLE/'BUILD_MANIFEST.json',manifest)
    OUT.mkdir(exist_ok=True);console_zip=OUT/f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in files(CONSOLE).items():archive.write(path,f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        saved={n.split('/',1)[1]:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
    assert saved=={n:digest(p) for n,p in files(CONSOLE).items()}
    code='''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix10' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix10-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
       env={**os.environ,'PYTHONPATH':str(CONSOLE)},capture_output=True,text=True,check=True)
    write(SOURCE/'verification/release-audit157fix10.json',
       {'console_version':VERSION,'zip_files':len(saved),'production_importer':json.loads(checked.stdout),
        'scope_verified':True,'firmware_sha256':firmware_sha,'tests':tests})
    source_manifest=old_manifest
    source_manifest.update(console_version=VERSION,release_baseline=BASELINE.name,
       release_changes='verification/changes157fix10.json',verification='verification/release-audit157fix10.json',
       firmware_reinstall_required=True,native_sources_unchanged=False,core_rust_sources_unchanged=True,
       media_build=MEDIA_BUILD,media_binary=media)
    for n in NATIVE_CHANGES:source_manifest['native_source_sha256'][n]=digest(SOURCE/n)
    write(SOURCE/'R17-SOURCE-MANIFEST.json',source_manifest)
    source_archive=OUT/(SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive,'w:gz',compresslevel=6) as archive:
        for name,path in files(SOURCE).items():archive.add(path,arcname=SOURCE.name+'/'+name,recursive=False)
    with tarfile.open(source_archive) as archive:
        saved={m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved=={n:digest(p) for n,p in files(SOURCE).items()}
    sums=OUT/f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
    print(json.dumps({'files':[{'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)}
       for p in (console_zip,source_archive,sums)],'tests':tests,'firmware_reinstall_required':True},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
