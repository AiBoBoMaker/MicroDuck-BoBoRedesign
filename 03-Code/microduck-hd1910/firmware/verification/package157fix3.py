"""Audit a PC-only update with byte-identical control.36 firmware."""
from pathlib import Path
import datetime, hashlib, json, os, re, subprocess, sys, tarfile, zipfile
from package157fix1 import digest, files, records, write

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix2')
CONSOLE = SOURCE / 'console'
OUT = SOURCE.parents[2] / 'output'
VERSION = '1.0.157-Fix3'
BUILD = '1fa8438-feetech-ft6-control.36'


def main():
    runs = json.loads((SOURCE / 'verification/fix3-tests.json').read_text())
    runs.append({'name': 'query', 'exit_code': 0, 'log': 'verification/fix3-query-tests.log'})
    counts = {}
    for run in runs:
        assert run['exit_code'] == 0, run
        log = SOURCE / run['log']
        run['sha256'] = digest(log)
        if run['name'] in {'pc-fix', 'streams', 'query'}:
            body = log.read_text()
            counts[run['name']] = int(re.search(r'Ran (\d+) tests', body).group(1))
            assert body.rstrip().endswith('OK'), run
    assert counts == {'pc-fix': 38, 'streams': 32, 'query': 15}, counts
    tests = {'python_passed': sum(counts.values()), 'browser_scripts_passed': len(runs)-3,
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
    assert firmware_sha == '6ba875422dc2fc49cce6cc7f9b35936d9ef192dfa01fda759c76e8ac0f972eb8'
    changed = [name for name, path in files(SOURCE).items()
               if not (BASELINE / name).is_file() or digest(path) != digest(BASELINE / name)]
    report = {'console_version': VERSION, 'service_build': BUILD, 'release_baseline': BASELINE.name,
              'firmware_reinstall_required': False, 'firmware_archive_byte_identical': True,
              'firmware_sha256': firmware_sha, 'native_sources_unchanged': True,
              'installed_payloads_unchanged': True, 'model_weights_unchanged': True,
              'removed_display': ['extra service status bar', 'gait preflight bar', 'duplicate four-step summary', 'duplicate recording export button'],
              'logging': {'system_log_source_filters': False, 'model_query_summary': True,
                          'volume_query_summary': True, 'process_query_summary': True,
                          'query_payloads_unchanged': True, 'full_explicit_output_preserved': True,
                          'query_failure_stdout_stderr_preserved': True,
                          'invalid_volume_not_reported_as_success': True},
              'added_queries_or_polling': False, 'added_robot_threads_or_loops': False,
              'changed_files': changed, 'tests': tests,
              'previous_native_results': 'verification/native-build157fix2.json and fix2-native-after.log; historical, not rerun'}
    write(SOURCE / 'verification/changes157fix3.json', report)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    build = json.loads((BASELINE / 'BUILD.json').read_text())
    build.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                 release_changes='Remove duplicate status UI; automatic model, process and volume queries log module outcomes.',
                 firmware_reinstall_required=False, rebuilt_binaries=[],
                 reused_binaries=list(build['built_binaries']), native_production_changes=[],
                 tests=tests, verification_report='verification/changes157fix3.json',
                 previous_native_build='verification/native-build157fix2.json')
    write(SOURCE / 'BUILD.json', build)
    manifest = json.loads((BASELINE / 'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                    firmware_reinstall_required=False, tests_run_in_release=tests,
                    release_changes='docs/releases/R157-Fix3.md', service_package_sha256=firmware_sha,
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
assert info['console_version']=='1.0.157-Fix3' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix3-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable,'-c',code,str(console_zip)], cwd=CONSOLE,
                             env={**os.environ,'PYTHONPATH':str(CONSOLE)}, capture_output=True,text=True,check=True)
    write(SOURCE / 'verification/release-audit157fix3.json',
          {'console_version': VERSION, 'service_build': BUILD, 'firmware_sha256': firmware_sha,
           'firmware_archive_byte_identical': True, 'production_firmware_importer': json.loads(checked.stdout),
           'zip_files': len(zipped), 'tests': tests, 'robot_hardware_tested': False, 'windows_native_tested': False})
    source_manifest = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())
    source_manifest.update(console_version=VERSION, release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix3.json', verification='verification/release-audit157fix3.json',
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
                      'tests': {'python_passed': 85, 'browser_scripts_passed': 8},
                      'firmware_sha256': firmware_sha, 'firmware_reinstall_required': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
