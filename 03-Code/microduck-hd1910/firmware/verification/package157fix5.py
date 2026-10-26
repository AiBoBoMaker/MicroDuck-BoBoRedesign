"""Audit a PC-only update with byte-identical control.36 firmware."""
from pathlib import Path
import datetime, hashlib, json, os, re, subprocess, sys, tarfile, zipfile
from package157fix1 import digest, files, records, write

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix4')
CONSOLE = SOURCE / 'console'
OUT = SOURCE.parents[2] / 'output'
VERSION = '1.0.157-Fix5'
BUILD = '1fa8438-feetech-ft6-control.36'


def main():
    runs = json.loads((SOURCE / 'verification/fix5-tests.json').read_text())
    counts = {}
    for run in runs:
        assert run['exit_code'] == 0, run
        log = SOURCE / run['log']
        run['sha256'] = digest(log)
        if run['name'] in {'pc-fix', 'streams', 'query', 'install'}:
            body = log.read_text()
            counts[run['name']] = int(re.search(r'Ran (\d+) tests', body).group(1))
            assert body.rstrip().endswith('OK'), run
    assert counts == {'pc-fix': 38, 'streams': 32, 'query': 15, 'install': 32}, counts
    tests = {'python_passed': sum(counts.values()), 'browser_scripts_passed': len(runs)-4,
             'runs': runs, 'robot_hardware_tested': False, 'windows_native_tested': False,
             'native_suite_rerun': False, 'full_historical_suite_rerun': False,
             'socket_boundary_note': 'Loopback TCP is substituted only at the OS socket boundary where the executor restricts AF_UNIX creation.'}
    old_native = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())['native_source_sha256']
    for name, sha in old_native.items():
        assert digest(SOURCE / name) == sha, name
    payload = json.loads((SOURCE / 'packaging/install-files.json').read_text())
    for name in set(payload) | {'install-files.json', 'SHA256SUMS'}:
        assert digest(SOURCE / 'packaging' / name) == digest(BASELINE / 'packaging' / name), name
    firmware = CONSOLE / 'updates/Microduck-Robotd-FT6-R17.tar.gz'
    firmware_sha = digest(firmware)
    assert firmware_sha == digest(BASELINE / 'console/updates' / firmware.name)
    assert firmware_sha == 'e14f1f327d840adafb32bd3e60d01ffcc964929527affb599727dc659431898a'
    changed = [name for name, path in files(SOURCE).items()
               if not (BASELINE / name).is_file() or digest(path) != digest(BASELINE / name)]
    report = {'console_version': VERSION, 'service_build': BUILD, 'release_baseline': BASELINE.name,
              'firmware_reinstall_required': False, 'firmware_archive_byte_identical': True,
              'firmware_sha256': firmware_sha, 'native_sources_unchanged': True,
              'installed_payloads_unchanged': True, 'model_weights_unchanged': True,
              'removed_display': ['live display pause button', 'system log pause button', 'page-width connection banner'],
              'ssh_module': {'in_heading': True, 'connection_feedback_in_own_status_row': True,
                             'original_credential_and_connection_channels_reused': True},
              'remote_installer_path': {'posixpath_join': True, 'windows_path_semantics_regression_passed': True},
              'logging': {'system_log_source_filters': False, 'workflow_terminal_outcomes_only': True,
                          'wait_events_still_delivered': True, 'upload_byte_progress_preserved': True,
                          'installer_execution_failure_named': True, 'failure_reasons_preserved': True},
              'display_pause_state_and_guards_removed': True,
              'replay_and_real_connection_pause_preserved': True,
              'install_handoff_unchanged': True,
              'placement_structure_verified': True, 'browser_pixel_rendered': False,
              'added_queries_or_polling': False, 'added_robot_threads_or_loops': False,
              'changed_files': changed, 'tests': tests,
              'previous_native_results': 'Historical native results retained from earlier releases; not rerun for this PC-only update'}
    write(SOURCE / 'verification/changes157fix5.json', report)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    build = json.loads((BASELINE / 'BUILD.json').read_text())
    build.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                 release_changes='Fix Windows remote Linux installer path; move SSH controls and feedback into heading; remove display pause and log start rows.',
                 firmware_reinstall_required=False, rebuilt_binaries=[],
                 reused_binaries=list(build['built_binaries']), native_production_changes=[],
                 tests=tests, verification_report='verification/changes157fix5.json',
                 previous_native_build='verification/native-build157fix2.json')
    write(SOURCE / 'BUILD.json', build)
    manifest = json.loads((BASELINE / 'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                    firmware_reinstall_required=False, tests_run_in_release=tests,
                    release_changes='docs/releases/R157-Fix5.md', service_package_sha256=firmware_sha,
                    files=records(CONSOLE, ('BUILD_MANIFEST.json',)))
    write(CONSOLE / 'BUILD_MANIFEST.json', manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT / f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files(CONSOLE).items(): archive.write(path, f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped = {name.split('/',1)[1]: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    assert zipped == {name: digest(path) for name, path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix5' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix5-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable,'-c',code,str(console_zip)], cwd=CONSOLE,
                             env={**os.environ,'PYTHONPATH':str(CONSOLE)}, capture_output=True,text=True,check=True)
    write(SOURCE / 'verification/release-audit157fix5.json',
          {'console_version': VERSION, 'service_build': BUILD, 'firmware_sha256': firmware_sha,
           'firmware_archive_byte_identical': True, 'production_firmware_importer': json.loads(checked.stdout),
           'zip_files': len(zipped), 'tests': tests, 'robot_hardware_tested': False, 'windows_native_tested': False})
    source_manifest = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())
    source_manifest.update(console_version=VERSION, release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix5.json', verification='verification/release-audit157fix5.json',
                           firmware_reinstall_required=False, native_sources_unchanged=True)
    write(SOURCE / 'R17-SOURCE-MANIFEST.json', source_manifest)
    source_archive = OUT / (SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive, 'w:gz', compresslevel=6) as archive:
        for name, path in files(SOURCE).items(): archive.add(path, arcname=SOURCE.name+'/'+name, recursive=False)
    with tarfile.open(source_archive, 'r:gz') as archive:
        saved = {m.name.split('/',1)[1]: hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved == {name: digest(path) for name, path in files(SOURCE).items()}
    sums = OUT / f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip, source_archive)))
    print(json.dumps({'files': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                               for path in (console_zip, source_archive, sums)],
                      'tests': {'python_passed': tests['python_passed'], 'browser_scripts_passed': tests['browser_scripts_passed']},
                      'firmware_sha256': firmware_sha, 'firmware_reinstall_required': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
