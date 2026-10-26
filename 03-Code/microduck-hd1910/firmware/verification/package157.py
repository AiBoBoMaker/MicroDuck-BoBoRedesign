"""Build and verify the matched v157 console, ARM firmware and source archives."""
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

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.156')
WORKSPACE = SOURCE.parents[2]
OUT = WORKSPACE / 'output'
CONSOLE = SOURCE / 'console'
PACKAGING = SOURCE / 'packaging'
BUILD = '1fa8438-feetech-ft6-control.35'
VERSION = '1.0.157'
CACHES = {'.git', '__pycache__', 'target', '.pytest_cache', '.venv', 'node_modules'}

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def files(root, exclude=()):
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob('*'))
            if p.is_file() and not CACHES.intersection(p.relative_to(root).parts)
            and p.relative_to(root).as_posix() not in exclude}

def records(root, exclude=()):
    return [{'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
            for name, path in files(root, exclude).items()]

def source_hashes():
    return {name: digest(path) for name, path in files(SOURCE).items()
            if path.suffix == '.rs' or path.name in ('Cargo.toml', 'Cargo.lock')}

def elf_record(path):
    header = subprocess.check_output(['readelf', '-h', str(path)], text=True)
    dynamic = subprocess.check_output(['readelf', '-d', str(path)], text=True)
    versions = subprocess.check_output(['readelf', '--version-info', str(path)], text=True)
    assert 'AArch64' in header, path
    glibc = sorted(set(re.findall(r'GLIBC_(\d+\.\d+)', versions)),
                   key=lambda s: tuple(map(int, s.split('.'))))
    assert glibc and all(tuple(map(int, s.split('.'))) <= (2, 31) for s in glibc), path
    return {'sha256': digest(path), 'machine': 'AArch64',
            'needed': re.findall(r'Shared library: \[(.*?)\]', dynamic),
            'glibc_versions': glibc, 'bytes': path.stat().st_size}

def log_result(name, count):
    path = SOURCE / 'verification' / name
    body = path.read_text()
    assert re.search(r'Ran ' + str(count) + r' tests\b', body) and body.rstrip().endswith('OK'), name
    return {'log': 'verification/' + name, 'sha256': digest(path), 'passed': count, 'exit_code': 0}

def main():
    native_bytes = (PACKAGING / 'robotd').read_bytes()
    assert BUILD.encode() in native_bytes and '控制线程意外结束'.encode() in native_bytes, 'new ARM binary required'
    assert digest(PACKAGING / 'robotd') != digest(BASELINE / 'packaging/robotd')
    spec = importlib.util.spec_from_file_location('elf_integrity157', PACKAGING / 'elf_integrity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ranges = module.validate_bundle(PACKAGING)
    binaries = {name: elf_record(PACKAGING / name) for name in module.NATIVE_FILES}
    for path in (SOURCE / 'ELF-CHECK.json', PACKAGING / 'ELF-CHECK.json'):
        write_json(path, binaries)

    browser = json.loads((SOURCE / 'verification/browser157-tests.json').read_text())
    calibration = SOURCE / 'verification/test_calibration_reference-157.log'
    assert json.loads(calibration.read_text())['passed'] is True
    browser[0]['exit_code'] = 0
    assert all(item['exit_code'] == 0 for item in browser)
    for item in browser:
        item['sha256'] = digest(SOURCE / item['log'])
    write_json(SOURCE / 'verification/browser157-tests.json', browser)
    tests = {'python': [log_result('input157-tests.log', 14), log_result('focused157-tests.log', 73)],
             'startup_rerun': log_result('startup157-tests.log', 6),
             'browser': browser,
             'native_full_suite_passed': False,
             'previous_native_attempt': {'passed': 131, 'failed': 4, 'log_preserved': False,
                 'failures': ['diagnostic_registers_share_storage_and_refresh_only_after_a_new_inspection',
                     'hd1910_contract_p_arm_and_relax_preserve_d_limit_acceleration_and_eeprom',
                     'negative_feedback_preloads_itself_but_home_targets_stay_calibrated_positive',
                     'telemetry_between_old_and_new_deadline_is_fresh_without_late_exception']},
             'historical_full_python_suite_passed': False,
             'historical_suite_note': 'Old UART/webpad assertions remain in historical tests; focused release regressions passed.',
             'robot_hardware_tested': False, 'windows_native_tested': False}
    source = source_hashes()
    native_build = {'build': BUILD, 'target': 'aarch64-unknown-linux-gnu.2.31',
        'command': ['cargo', 'zigbuild', '-p', 'robotd', '-p', 'robotctl', '-p', 'padd',
                    '--release', '--target', 'aarch64-unknown-linux-gnu.2.31', '--frozen'],
        'exit_code': 0, 'source_sha256': source,
        'log': 'verification/native-build157-final.log',
        'log_sha256': digest(SOURCE / 'verification/native-build157-final.log'),
        'binaries': {name: binaries[name] for name in ('robotd', 'robotctl', 'padd')},
        'hardware_tested': False}
    write_json(SOURCE / 'verification/native-build157-final.json', native_build)
    old = json.loads((BASELINE / 'BUILD.json').read_text())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    baseline_files = files(BASELINE)
    changed = [name for name, path in files(SOURCE).items()
               if name not in baseline_files or digest(path) != digest(BASELINE / name)]
    changed.extend(name for name in baseline_files if not (SOURCE / name).exists())
    startup = {'steps': ['configuration_and_ipc', 'hardware_first_valid_sample',
                        'models_and_controller', 'first_completed_control_cycle'],
        'uart_startup_hooks': False, 'uart_configured_ack': False, 'uart_generation_state_file': False,
        'extra_cold_reopen': False, 'hardware_wait_interval': 'existing official startup interval',
        'ipc_available_while_hardware_waits': True, 'control_thread_exit_notification': True,
        'state_transport': 'robot.startupSubscribe change events plus initial snapshot'}
    input_flow = {'path': 'browser WebSocket -> persistent SSH helper -> official robotd IPC',
        'physical_pad_priority': True, 'device_detection': 'initial snapshot plus kernel input uevents',
        'discovery_polling': False, 'virtual_webpad': False,
        'idle_wait': 'blocking selector; timeout only for an active web input lease',
        'stale_action_replay': False, 'input_lease_seconds': 0.6}
    report = {'console_version': VERSION, 'build': BUILD,
        'release_baseline': '1.0.156 / control.34', 'firmware_reinstall_required': True,
        'startup': startup, 'web_input': input_flow,
        'new_periodic_uart_or_model_work': False, 'tests': tests,
        'native_build': 'verification/native-build157-final.json', 'elf_ranges': ranges,
        'changed_files': changed, 'hardware_verified': False}
    write_json(SOURCE / 'verification/changes157.json', report)
    build = {key: old[key] for key in ('official_version', 'official_revision', 'hardware_base',
        'models', 'default_global_settings', 'onnxruntime', 'calibration_policy', 'audio_volume',
        'native_position_fix', 'retired_model_ids') if key in old}
    build.update(build=BUILD, console_version=VERSION, hardware_verified=False,
        source_distribution=SOURCE.name + '.tar.gz', built_binaries=binaries,
        rebuilt_binaries=['robotd', 'robotctl', 'padd'],
        reused_binaries=[name for name in binaries if name not in ('robotd', 'robotctl', 'padd')],
        toolchain='Rust 1.99.0 / cargo-zigbuild 0.23.4 / Zig 0.14.1; aarch64-unknown-linux-gnu.2.31',
        generated_at_utc=now, release_changes='Four-stage startup, independent auxiliary services, persistent SSH web input with event-based physical-pad arbitration.',
        startup_flow=startup, raw_browser_input=input_flow,
        configuration_save={'startup_backup': False, 'save_on_actual_change': True, 'modified_by_owning_module': True},
        automatic_updater_enabled=False, automatic_boot_restore_enabled=False,
        manual_console_upgrade_available=True, firmware_reinstall_required=True,
        hat_firmware_unchanged=True, uart_telemetry_unchanged=True,
        official_filter_algorithm_unchanged=True, native_production_changes=[
            'robotd/src/main.rs', 'robotd/src/feetech_commissioning.rs',
            'duck-control/src/feetech.rs', 'robotd-params/src/edit.rs'],
        padd_source_sha256=digest(SOURCE / 'padd/src/main.rs'),
        gamepad_binary_sha256=binaries['gamepad-r7/gamesir-xboxd']['sha256'],
        tests=tests, verification_report='verification/changes157.json')
    write_json(SOURCE / 'BUILD.json', build)
    write_json(PACKAGING / 'BUILD.json', build)

    names = json.loads((PACKAGING / 'install-files.json').read_text())
    names = sorted(set(names) | {'R157.md'})
    assert not {'uart-service.py', 'webpad.py', 'microduck-webpad.service', 'microduck-webpad.socket'}.intersection(names)
    for name in names:
        assert (PACKAGING / name).is_file(), name
    write_json(PACKAGING / 'install-files.json', names)
    payload_names = sorted(set(names) | {'install-files.json'})
    (PACKAGING / 'SHA256SUMS').write_text(''.join(f'{digest(PACKAGING / name)}  {name}\n' for name in payload_names))
    payload_names.append('SHA256SUMS')
    firmware = CONSOLE / 'updates/Microduck-Robotd-FT6-R17.tar.gz'
    with tarfile.open(firmware, 'w:gz', compresslevel=6) as archive:
        for name in payload_names:
            archive.add(PACKAGING / name, arcname='Microduck-Robotd-FT6-R17/' + name, recursive=False)
    with tarfile.open(firmware, 'r:gz') as archive:
        stored = {member.name.removeprefix('Microduck-Robotd-FT6-R17/'):
                  hashlib.sha256(archive.extractfile(member).read()).hexdigest() for member in archive}
    assert stored == {name: digest(PACKAGING / name) for name in payload_names}

    manifest = {'console_version': VERSION, 'official_baseline': old['official_revision'],
        'service_build': BUILD, 'hardware_verified': False, 'hardware_base': old['hardware_base'],
        'service_package_sha256': digest(firmware), 'source_distribution': SOURCE.name + '.tar.gz',
        'models': old['models'], 'global_settings': old['default_global_settings'],
        'protocol': 'official IPC, unchanged native raw telemetry, persistent SSH web input',
        'startup_flow': startup, 'web_input': input_flow, 'generated_at_utc': now,
        'firmware_reinstall_required': True, 'tests_run_in_release': tests,
        'files': records(CONSOLE, ('BUILD_MANIFEST.json',))}
    write_json(CONSOLE / 'BUILD_MANIFEST.json', manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT / f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files(CONSOLE).items():
            archive.write(path, f'Microduck-Console-R17-v{VERSION}/' + name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped = {name.split('/', 1)[1]: hashlib.sha256(archive.read(name)).hexdigest()
                  for name in archive.namelist()}
    assert zipped == {name: digest(path) for name, path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]); info=bundle_info()
assert info['console_version']=='1.0.157' and info['build']=='1fa8438-feetech-ft6-control.35'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release157-verification')
 try: assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally: prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    result = subprocess.run([sys.executable, '-c', code, str(console_zip)], cwd=CONSOLE,
        env={**os.environ, 'PYTHONPATH': str(CONSOLE)}, text=True, capture_output=True, check=True)
    audit = {'console_version': VERSION, 'build': BUILD, 'firmware_sha256': digest(firmware),
        'production_firmware_importer': json.loads(result.stdout), 'zip_files': len(zipped),
        'elf_ranges_checked': True, 'hardware_tested': False}
    write_json(SOURCE / 'verification/release-audit157.json', audit)
    source_manifest = {'console_version': VERSION, 'service_build': BUILD,
        'official_baseline': old['official_revision'], 'release_baseline': BASELINE.name,
        'release_changes': 'verification/changes157.json', 'native_source_sha256': source,
        'verification': 'verification/release-audit157.json', 'hardware_verified': False}
    write_json(SOURCE / 'R17-SOURCE-MANIFEST.json', source_manifest)
    source_archive = OUT / (SOURCE.name + '.tar.gz')
    with tarfile.open(source_archive, 'w:gz', compresslevel=6) as archive:
        for name, path in files(SOURCE).items():
            archive.add(path, arcname=SOURCE.name + '/' + name, recursive=False)
    with tarfile.open(source_archive, 'r:gz') as archive:
        saved = {member.name.split('/', 1)[1]: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                 for member in archive}
    assert saved == {name: digest(path) for name, path in files(SOURCE).items()}
    sums = OUT / 'SHA256SUMS-v1.0.157.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip, source_archive)))
    print(json.dumps({'files': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                               for path in (console_zip, source_archive, sums)],
                      'firmware_sha256': digest(firmware)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
