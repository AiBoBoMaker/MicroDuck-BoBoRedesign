"""Package and audit matched Fix2 console, control.36 ARM binary and source."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile

from package157 import digest, files, records, source_hashes, elf_record, write_json

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix1')
CONSOLE = SOURCE / 'console'
PACKAGING = SOURCE / 'packaging'
OUT = SOURCE.parents[2] / 'output'
VERSION = '1.0.157-Fix2'
BUILD = '1fa8438-feetech-ft6-control.36'


def main():
    runs = json.loads((SOURCE / 'verification/fix2-tests.json').read_text())
    for run in runs:
        assert run['exit_code'] == 0, run
        run['sha256'] = digest(SOURCE / run['log'])
    python_runs = []
    for name, count in [('pc-fix', 38), ('streams', 32), ('complete-log', 7)]:
        log = SOURCE / f'verification/fix2-{name}-tests.log'
        text = log.read_text()
        assert re.search(rf'Ran {count} tests\b', text) and text.rstrip().endswith('OK'), name
        python_runs.append({'name': name, 'passed': count, 'log': str(log.relative_to(SOURCE)), 'sha256': digest(log)})
    native_runs = []
    for name, count in [('native-after', 9), ('imu-tests', 6)]:
        log = SOURCE / f'verification/fix2-{name}.log'
        assert re.search(rf'test result: ok\. {count} passed; 0 failed;', log.read_text()), name
        native_runs.append({'name': name, 'passed': count, 'log': str(log.relative_to(SOURCE)), 'sha256': digest(log)})
    before = SOURCE / 'verification/fix2-native-before.log'
    assert 'left: 24s' in before.read_text() and '3 failed' in before.read_text()
    build_log = SOURCE / 'verification/native-build157fix2.log'
    assert 'Finished `release` profile' in build_log.read_text()
    tests = {'python_passed': 77, 'browser_scripts_passed': 8, 'native_focused_passed': 15,
             'python': python_runs, 'browser': [run for run in runs if run['name'].startswith('test_')],
             'native': native_runs, 'before_fix_regression': {'log': str(before.relative_to(SOURCE)), 'sha256': digest(before), 'expected_failure': True},
             'robot_hardware_tested': False, 'windows_native_tested': False,
             'full_historical_suite_rerun': False,
             'socket_boundary_note': 'Request and stream tests use loopback TCP at the OS boundary where the executor restricts AF_UNIX creation.'}

    native_source = source_hashes()
    old_native = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())['native_source_sha256']
    changed_native = sorted(name for name, sha in native_source.items() if old_native.get(name) != sha)
    assert changed_native == ['duck-control/src/imu.rs', 'robotd/src/feetech_commissioning.rs', 'robotd/src/main.rs'], changed_native
    binary = (PACKAGING / 'robotd').read_bytes()
    assert BUILD.encode() in binary and digest(PACKAGING / 'robotd') != digest(BASELINE / 'packaging/robotd')
    spec = importlib.util.spec_from_file_location('fix2_elf_integrity', PACKAGING / 'elf_integrity.py')
    integrity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integrity)
    ranges = integrity.validate_bundle(PACKAGING)
    binaries = {name: elf_record(PACKAGING / name) for name in integrity.NATIVE_FILES}
    for name in integrity.NATIVE_FILES:
        if name != 'robotd':
            assert digest(PACKAGING / name) == digest(BASELINE / 'packaging' / name), name
    for name in ('ELF-CHECK.json', 'packaging/ELF-CHECK.json'):
        write_json(SOURCE / name, binaries)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    native_build = {'build': BUILD, 'target': 'aarch64-unknown-linux-gnu.2.31',
                    'command': ['cargo', 'zigbuild', '-p', 'robotd', '--release', '--target', 'aarch64-unknown-linux-gnu.2.31', '--frozen'],
                    'exit_code': 0, 'source_sha256': native_source, 'binaries': {'robotd': binaries['robotd']},
                    'log': str(build_log.relative_to(SOURCE)), 'log_sha256': digest(build_log), 'hardware_tested': False}
    write_json(SOURCE / 'verification/native-build157fix2.json', native_build)
    report = {'console_version': VERSION, 'service_build': BUILD, 'release_baseline': BASELINE.name,
              'firmware_reinstall_required': True, 'native_production_changes': changed_native,
              'startup': {'imu_ready_samples': 25, 'max_short_waits': 24, 'short_wait': 'existing control period',
                          'nominal_wait_at_50hz_ms': 480, 'fault_backoff_seconds': 1,
                          'unchanged_ready_guard': True, 'startup_target_gain_torque_writes': False,
                          'new_threads_or_loops': False, 'steady_control_work_added': False},
              'log': {'all_sources_visible': True, 'workflow_markers': 'robotd startup 1/4 through 4/4',
                      'one_complete_file': True, 'one_existing_writer': True, 'passwords_redacted': True},
              'models': {'selection_removed': True, 'read_only_status': True,
                         'catalogue_api_retained_for_display_and_walk_scale': True, 'weights_unchanged': True},
              'hat_firmware_unchanged': True, 'uart_protocol_unchanged': True,
              'native_build': 'verification/native-build157fix2.json', 'elf_ranges': ranges,
              'tests': tests, 'hardware_verified': False}
    write_json(SOURCE / 'verification/changes157fix2.json', report)
    old = json.loads((BASELINE / 'BUILD.json').read_text())
    build = dict(old)
    build.update(build=BUILD, console_version=VERSION, source_distribution=SOURCE.name + '.tar.gz',
                 built_binaries=binaries, rebuilt_binaries=['robotd'],
                 reused_binaries=[name for name in binaries if name != 'robotd'],
                 generated_at_utc=now, firmware_reinstall_required=True,
                 native_production_changes=changed_native, hardware_verified=False,
                 release_changes='Full workflow-marked logs, bounded startup IMU confirmation at the existing control period, read-only model display.',
                 tests=tests, verification_report='verification/changes157fix2.json',
                 previous_native_build='verification/native-build157-final.json')
    build['startup_flow'] = {**build['startup_flow'], **report['startup']}
    write_json(SOURCE / 'BUILD.json', build)
    write_json(PACKAGING / 'BUILD.json', build)

    names = sorted(set(json.loads((PACKAGING / 'install-files.json').read_text())) | {'R157-Fix2.md'})
    assert not {'uart-service.py', 'webpad.py', 'microduck-webpad.service', 'microduck-webpad.socket'}.intersection(names)
    allowed = {'BUILD.json', 'ELF-CHECK.json', 'robotd', 'release_identity.py', 'README.zh-CN.md', 'R157-Fix2.md'}
    for name in names:
        assert (PACKAGING / name).is_file(), name
        if name not in allowed:
            assert digest(PACKAGING / name) == digest(BASELINE / 'packaging' / name), name
    write_json(PACKAGING / 'install-files.json', names)
    payload = sorted(set(names) | {'install-files.json'})
    (PACKAGING / 'SHA256SUMS').write_text(''.join(f'{digest(PACKAGING / name)}  {name}\n' for name in payload))
    payload.append('SHA256SUMS')
    firmware = CONSOLE / 'updates/Microduck-Robotd-FT6-R17.tar.gz'
    with tarfile.open(firmware, 'w:gz', compresslevel=6) as archive:
        for name in payload:
            archive.add(PACKAGING / name, arcname='Microduck-Robotd-FT6-R17/' + name, recursive=False)
    with tarfile.open(firmware, 'r:gz') as archive:
        stored = {m.name.split('/', 1)[1]: hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert stored == {name: digest(PACKAGING / name) for name in payload}

    manifest = json.loads((BASELINE / 'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, service_build=BUILD, source_distribution=SOURCE.name + '.tar.gz',
                    generated_at_utc=now, service_package_sha256=digest(firmware),
                    firmware_reinstall_required=True, startup_flow=build['startup_flow'],
                    release_changes='docs/releases/R157-Fix2.md', tests_run_in_release=tests,
                    files=records(CONSOLE, ('BUILD_MANIFEST.json',)))
    write_json(CONSOLE / 'BUILD_MANIFEST.json', manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT / f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files(CONSOLE).items():
            archive.write(path, f'Microduck-Console-R17-v{VERSION}/' + name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped = {name.split('/', 1)[1]: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    assert zipped == {name: digest(path) for name, path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix2' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix2-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable, '-c', code, str(console_zip)], cwd=CONSOLE,
                             env={**os.environ, 'PYTHONPATH': str(CONSOLE)}, text=True, capture_output=True, check=True)
    audit = {'console_version': VERSION, 'service_build': BUILD, 'firmware_sha256': digest(firmware),
             'production_firmware_importer': json.loads(checked.stdout), 'zip_files': len(zipped),
             'elf_ranges_checked': True, 'tests': tests, 'robot_hardware_tested': False, 'windows_native_tested': False}
    write_json(SOURCE / 'verification/release-audit157fix2.json', audit)
    source_manifest = {'console_version': VERSION, 'service_build': BUILD,
                       'official_baseline': old['official_revision'], 'release_baseline': BASELINE.name,
                       'release_changes': 'verification/changes157fix2.json', 'native_source_sha256': native_source,
                       'verification': 'verification/release-audit157fix2.json', 'hardware_verified': False,
                       'firmware_reinstall_required': True, 'native_sources_unchanged': False}
    write_json(SOURCE / 'R17-SOURCE-MANIFEST.json', source_manifest)
    source_archive = OUT / (SOURCE.name + '.tar.gz')
    with tarfile.open(source_archive, 'w:gz', compresslevel=6) as archive:
        for name, path in files(SOURCE).items():
            archive.add(path, arcname=SOURCE.name + '/' + name, recursive=False)
    with tarfile.open(source_archive, 'r:gz') as archive:
        saved = {m.name.split('/', 1)[1]: hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved == {name: digest(path) for name, path in files(SOURCE).items()}
    sums = OUT / f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip, source_archive)))
    print(json.dumps({'files': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                               for path in (console_zip, source_archive, sums)],
                      'firmware_sha256': digest(firmware), 'tests': {'python': 77, 'browser_scripts': 8, 'native': 15}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
