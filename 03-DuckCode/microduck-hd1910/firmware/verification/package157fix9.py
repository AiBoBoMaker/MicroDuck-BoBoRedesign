"""Ship the HID connection correction, preserving every Fix8 installed byte."""
from pathlib import Path
import datetime, hashlib, json, os, re, subprocess, sys, tarfile, zipfile
from package157fix1 import digest, files, records, write

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix8')
CONSOLE = SOURCE/'console'
OUT = SOURCE.parents[2]/'output'
VERSION = '1.0.157-Fix9'
BUILD = '1fa8438-feetech-ft6-control.36'


def main():
    runs = json.loads((SOURCE/'verification/fix9-tests.json').read_text())
    assert len(runs) == 14 and all(r['exit_code'] == 0 for r in runs)
    counts = {}
    for run in runs:
        log = SOURCE/run['log']
        run['sha256'] = digest(log)
        if run['name'] in {'repair', 'input', 'order', 'install'}:
            text = log.read_text()
            counts[run['name']] = int(re.search(r'Ran (\d+) tests', text).group(1))
            assert text.rstrip().endswith('OK')
    assert counts == {'repair':36, 'input':38, 'order':17, 'install':32}, counts
    tests = {'python_passed':sum(counts.values()), 'frontend_logic_scripts_passed':6,
             'c_regression_executables_passed':2, 'runs':runs, 'robot_hardware_tested':False,
             'windows_native_tested':False, 'browser_pixel_rendered':False}
    generated = {'BUILD.json', 'R17-SOURCE-MANIFEST.json', 'console/BUILD_MANIFEST.json'}
    old_files, new_files = files(BASELINE), files(SOURCE)
    changed = [n for n in sorted(old_files.keys() | new_files.keys())
               if not n.startswith('verification/') and n not in generated
               and (n not in old_files or n not in new_files or digest(old_files[n]) != digest(new_files[n]))]
    assert set(changed) == {'console/gamepad_repair.py', 'console/release_identity.py',
                            'console/verification/test_gamepad_repair.py', 'console/README.zh-CN.md',
                            'console/docs/releases/R157-Fix9.md', 'docs/design/r17-connection-design.md'}, changed
    firmware = CONSOLE/'updates/Microduck-Robotd-FT6-R17.tar.gz'
    firmware_sha = digest(firmware)
    assert firmware_sha == digest(BASELINE/'console/updates/Microduck-Robotd-FT6-R17.tar.gz')
    old_native = json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())['native_source_sha256']
    for name, sha in old_native.items():
        assert digest(SOURCE/name) == sha, name
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report = {'console_version':VERSION, 'service_build':BUILD, 'release_baseline':BASELINE.name,
              'production_changed_files':changed, 'installed_packaging_all_files_byte_identical':True,
              'robotd_startup_install_data_and_mutual_exclusion_unchanged':True,
              'firmware_reinstall_required_from_fix8':False, 'firmware_sha256':firmware_sha,
              'pair_connected_without_hid_reproduced_by_fault_injection':True,
              'explicit_hid_connection_once_after_pair':True,
              'bluetooth_connected_missing_physical_input_gets_one_hid_connect':True,
              'failed_connect_preserves_bond_address_and_bluez_error':True,
              'disconnection_during_input_wait_reported_as_bluetooth_failure':True,
              'main_service_wait_only_reported_when_observed':True,
              'no_added_resident_services_or_polling':True, 'tests':tests}
    write(SOURCE/'verification/changes157fix9.json', report)
    metadata = json.loads((BASELINE/'BUILD.json').read_text())
    metadata.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz',
                    generated_at_utc=now, firmware_reinstall_required=False,
                    rebuilt_binaries=[], native_production_changes=[], tests=tests,
                    release_changes='Explicit HID connection after pairing; accurate input-layer failure attribution.',
                    verification_report='verification/changes157fix9.json')
    write(SOURCE/'BUILD.json', metadata)
    manifest = json.loads((BASELINE/'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz',
                    generated_at_utc=now, firmware_reinstall_required=False,
                    tests_run_in_release=tests, service_package_sha256=firmware_sha,
                    release_changes='docs/releases/R157-Fix9.md', files=records(CONSOLE, ('BUILD_MANIFEST.json',)))
    write(CONSOLE/'BUILD_MANIFEST.json', manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT/f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files(CONSOLE).items():
            archive.write(path, f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped = {n.split('/',1)[1]:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
    assert zipped == {name:digest(path) for name,path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix9' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix9-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable,'-c',code,str(console_zip)], cwd=CONSOLE,
                             env={**os.environ,'PYTHONPATH':str(CONSOLE)}, capture_output=True,text=True,check=True)
    write(SOURCE/'verification/release-audit157fix9.json',
          {'console_version':VERSION, 'zip_files':len(zipped), 'scope_verified':True,
           'production_importer':json.loads(checked.stdout), 'firmware_sha256':firmware_sha, 'tests':tests})
    source_manifest = json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())
    source_manifest.update(console_version=VERSION, release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix9.json',
                           verification='verification/release-audit157fix9.json',
                           firmware_reinstall_required=False, native_sources_unchanged=True,
                           core_rust_sources_unchanged=True)
    write(SOURCE/'R17-SOURCE-MANIFEST.json', source_manifest)
    source_archive = OUT/(SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive, 'w:gz', compresslevel=6) as archive:
        for name,path in files(SOURCE).items():
            archive.add(path, arcname=SOURCE.name+'/'+name, recursive=False)
    with tarfile.open(source_archive, 'r:gz') as archive:
        archived = {m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert archived == {name:digest(path) for name,path in files(SOURCE).items()}
    sums = OUT/f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (console_zip,source_archive)))
    print(json.dumps({'files':[{'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)}
                               for p in (console_zip,source_archive,sums)], 'tests':tests,
                      'firmware_sha256':firmware_sha, 'firmware_reinstall_required_from_fix8':False},
                     ensure_ascii=False,indent=2))


if __name__ == '__main__':main()
