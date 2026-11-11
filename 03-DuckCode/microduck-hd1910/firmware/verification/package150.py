#!/usr/bin/env python3
"""Assemble R150 after the root agent coordinates final verified inputs.

The shipped v149 console/firmware are the byte baseline. Business sources are
never modified here; an isolated source tree is synchronized for distribution.
No robot, systemd, serial port, uinput, Library upload or publication is used.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

B = Path('/workspace/scratch/5a402859beee')
SOURCE = B / 'source/Microduck-Source-R17-v1.0.149'
OLD_CONSOLE = B / 'work/Microduck-Console-R17-v1.0.149'
OLD_FIRMWARE = B / 'firmware149/Microduck-Robotd-FT6-R17'
OLD_SOURCE_ARCHIVE = B / 'inputs/宠物机器人/Microduck-Source-R17-v1.0.149.tar.gz'
NATIVE = Path('/tmp/r17-native-arm150/aarch64-unknown-linux-gnu/release')
WORK = B / 'scratch/package150'
OUT = B / 'output'
VERSION = '1.0.150'
BUILD = '1fa8438-feetech-ft6-control.31'
ARCHIVE_NAME = 'Microduck-Robotd-FT6-R17.tar.gz'
NATIVE_NAMES = ('robotd', 'robotctl', 'padd')
HELPER_NAMES = ('runtime.py', 'service.sh', 'release_identity.py')
CACHE_NAMES = {'__pycache__', '.git', '.venv', 'target', 'node_modules', '.pytest_cache'}
PAYLOAD_ALLOWED = set(NATIVE_NAMES + HELPER_NAMES) | {
    'BUILD.json', 'ELF-CHECK.json', 'install-files.json', 'SHA256SUMS', 'R150.md'}
CONSOLE_ALLOWED = {'release_identity.py', 'BUILD_MANIFEST.json',
                   'updates/' + ARCHIVE_NAME, 'docs/releases/R150.md'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def records(root, exclude=()):
    excluded = set(exclude)
    return [dict(path=p.relative_to(root).as_posix(), bytes=p.stat().st_size,
                 sha256=digest(p)) for p in sorted(root.rglob('*'))
            if p.is_file() and not (set(p.relative_to(root).parts) & CACHE_NAMES)
            and p.relative_to(root).as_posix() not in excluded]


def record_map(root):
    return {r['path']: r for r in records(root)}


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*CACHE_NAMES))


def elf_record(path):
    header = subprocess.check_output(['readelf', '-h', str(path)], text=True)
    dynamic = subprocess.check_output(['readelf', '-d', str(path)], text=True)
    versions = subprocess.check_output(['readelf', '--version-info', str(path)], text=True)
    assert 'AArch64' in header, f'Wrong ELF machine: {path}'
    glibc = sorted(set(re.findall(r'GLIBC_(\d+\.\d+)', versions)),
                   key=lambda item: tuple(map(int, item.split('.'))))
    assert glibc and max(tuple(map(int, v.split('.'))) for v in glibc) <= (2, 31), path
    return dict(sha256=digest(path), machine='AArch64',
                needed=re.findall(r'Shared library: \[(.*?)\]', dynamic),
                glibc_versions=glibc, bytes=path.stat().st_size)


def original_source_records():
    result = {}
    with tarfile.open(OLD_SOURCE_ARCHIVE, 'r:gz') as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            parts = Path(entry.name).parts
            if set(parts) & CACHE_NAMES:
                continue
            name = Path(*parts[1:]).as_posix()
            stream = archive.extractfile(entry)
            assert stream is not None
            result[name] = dict(path=name, bytes=entry.size,
                                sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    return result


def changed(old, new):
    return [name for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)]


def verify_checksums(root):
    listing = []
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        expected, separator, name = line.partition('  ')
        assert separator and digest(root / name) == expected, name
        listing.append(name)
    assert listing == [row['path'] for row in records(root, ['SHA256SUMS'])]


def make_tar(root, destination):
    with tarfile.open(destination, 'w:gz', compresslevel=9) as archive:
        archive.add(root, arcname=root.name,
                    filter=lambda item: None if set(Path(item.name).parts) & CACHE_NAMES else item)


def verify_tar(root, archive_path):
    actual = {}
    with tarfile.open(archive_path, 'r:gz') as archive:
        for entry in archive:
            parts = Path(entry.name).parts
            assert parts and parts[0] == root.name and '..' not in parts
            assert not (set(parts) & CACHE_NAMES)
            if not entry.isfile():
                assert entry.isdir(), f'Unexpected archive entry: {entry.name}'
                continue
            name = Path(*parts[1:]).as_posix()
            assert name not in actual, f'Duplicate archive file: {name}'
            stream = archive.extractfile(entry)
            assert stream is not None
            actual[name] = dict(path=name, bytes=entry.size,
                                sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    assert actual == record_map(root), f'Archive differs from its verified tree: {archive_path}'


def assemble():
    recovery_path = SOURCE / 'verification/recovery150.json'
    recovery = json.loads(recovery_path.read_text())
    # The owner's current report is authoritative. Historical test totals are
    # never promoted to a new result, and failures/limitations are not removed.
    tests = recovery.get('tests', recovery)
    assert isinstance(tests, dict)
    doc = SOURCE / 'console/docs/releases/R150.md'
    assert VERSION in doc.read_text() and BUILD in doc.read_text()
    assert all((NATIVE / name).is_file() for name in NATIVE_NAMES)
    assert BUILD.encode() in (NATIVE / 'robotd').read_bytes()
    native_build = json.loads((B / 'native-build150.json').read_text())
    assert native_build['exit_code'] == 0 and native_build['source_sha256_unchanged'] is True
    assert set(native_build['binaries']) == set(NATIVE_NAMES)
    assert all(digest(NATIVE / name) == expected for name, expected in native_build['binaries'].items())
    assert all(digest(SOURCE / name) == expected for name, expected in native_build['source_sha256'].items())
    elf = {name: elf_record(NATIVE / name) for name in NATIVE_NAMES}
    old_source = original_source_records()
    assert digest(SOURCE / 'Cargo.lock') == old_source['Cargo.lock']['sha256']
    before_source = record_map(SOURCE)
    old_firmware = record_map(OLD_FIRMWARE)
    old_console = record_map(OLD_CONSOLE)
    OUT.mkdir(parents=True, exist_ok=True)
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    stage = WORK / 'stage/Microduck-Robotd-FT6-R17'
    stage.parent.mkdir()
    copy_tree(OLD_FIRMWARE, stage)
    released = WORK / f'Microduck-Source-R17-v{VERSION}'
    copy_tree(SOURCE, released)
    console = released / 'console'
    shutil.rmtree(console)
    copy_tree(OLD_CONSOLE, console)
    (console / 'docs/releases').mkdir(parents=True, exist_ok=True)
    shutil.copy2(doc, console / 'docs/releases/R150.md')
    for name in HELPER_NAMES:
        shutil.copy2(SOURCE / 'packaging' / name, stage / name)
    for name in NATIVE_NAMES:
        shutil.copy2(NATIVE / name, stage / name)
        (stage / name).chmod(0o755)
    shutil.copy2(SOURCE / 'packaging/release_identity.py', console / 'release_identity.py')
    assert BUILD in (console / 'release_identity.py').read_text()
    assert VERSION in (console / 'release_identity.py').read_text()
    shutil.copy2(doc, stage / 'R150.md')
    elf.update({name: elf_record(stage / name) for name in ['sounds', 'gamepad-r7/gamesir-xboxd']})
    build = json.loads((SOURCE / 'BUILD.json').read_text())
    for name in ['build_status', 'merge_verification', 'release_native_production_changes',
                 'release_native_test_changes', 'release_changed_native_source_files']:
        build.pop(name, None)
    native_changed = [name for name, record in before_source.items()
                      if name.endswith('.rs') and old_source.get(name) != record]
    build.update(build=BUILD, console_version=VERSION, source_distribution=released.name + '.tar.gz',
                 generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 tests=tests, rebuilt_binaries=list(NATIVE_NAMES),
                 reused_binaries=['sounds', 'gamepad-r7/gamesir-xboxd'], built_binaries=elf,
                 padd_source_sha256=digest(SOURCE / 'padd/src/main.rs'),
                 release_changed_native_source_files=sorted(native_changed),
                 release_changes='Bounded startup recovery and gamepad reconnection fixes on the exact v149 payload; models, calibration, execution parameters, HAT and GameSir bridge bytes preserved.',
                 verification_report='verification/recovery150.json', hardware_verified=False,
                 release_baseline=dict(console='1.0.149', firmware_build='1fa8438-feetech-ft6-control.30',
                                       previous_tests_are_historical=True),
                 toolchain='Rust 1.99.0 / cargo-zigbuild 0.23.4 / Zig 0.14.1; aarch64-unknown-linux-gnu.2.31')
    for root in [stage, released]:
        write_json(root / 'BUILD.json', build)
        write_json(root / 'ELF-CHECK.json', elf)
    write_json(stage / 'install-files.json',
               [r['path'] for r in records(stage, ['SHA256SUMS', 'install-files.json'])])
    (stage / 'SHA256SUMS').write_text(''.join(
        f"{r['sha256']}  {r['path']}\n" for r in records(stage, ['SHA256SUMS'])))
    verify_checksums(stage)
    stage_records = record_map(stage)
    payload_changed = changed(old_firmware, stage_records)
    assert set(payload_changed) <= PAYLOAD_ALLOWED, payload_changed
    preserved = [name for name in old_firmware if name not in PAYLOAD_ALLOWED]
    assert all(old_firmware[name] == stage_records[name] for name in preserved)
    # Match packaged source helpers to the exact final firmware; retained source
    # test modules and build scripts remain in packaging beside the payload.
    packaging_sync = []
    for name in stage_records:
        original = before_source.get('packaging/' + name)
        target = released / 'packaging' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / name, target)
        if original is None or {**original, 'path': name} != stage_records[name]:
            packaging_sync.append(name)
    archive = console / 'updates' / ARCHIVE_NAME
    make_tar(stage, archive)
    verify_tar(stage, archive)
    assert archive.stat().st_size <= 32 * 1024 * 1024, 'Firmware exceeds the production importer limit'
    manifest = json.loads((OLD_CONSOLE / 'BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, service_build=BUILD,
                    service_package_sha256=digest(archive), source_distribution=released.name + '.tar.gz',
                    generated_at_utc=build['generated_at_utc'], tests_run_in_release=tests,
                    merge_verification=dict(baseline_console='1.0.149', hardware_tested=False,
                                            exact_payload_preserved=True, recovery_report='verification/recovery150.json'),
                    files=records(console, ['BUILD_MANIFEST.json']))
    write_json(console / 'BUILD_MANIFEST.json', manifest)
    console_records = record_map(console)
    console_changed = changed(old_console, console_records)
    assert set(console_changed) <= CONSOLE_ALLOWED, console_changed
    # Invoke the actual production importer in an isolated interpreter; its root
    # is the released console and no stale imported release identity is reused.
    console_zip = OUT / f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as package:
        for row in records(console):
            package.write(console / row['path'], f'Microduck-Console-R17-v{VERSION}/' + row['path'])
    with zipfile.ZipFile(console_zip) as package:
        assert package.testzip() is None
    code = '''import json,sys,hashlib
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]); info=bundle_info()
assert info['console_version']=='1.0.150' and info['build']=='1fa8438-feetech-ft6-control.31'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'release150-verification')
 try: assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally: prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    result = subprocess.run([sys.executable, '-c', code, str(console_zip)], cwd=console,
                            env={**dict(__import__('os').environ), 'PYTHONPATH': str(console)},
                            check=True, capture_output=True, text=True)
    sync = changed({k.removeprefix('console/'): {**v, 'path': k.removeprefix('console/')} for k, v in before_source.items()
                    if k.startswith('console/')}, console_records)
    verification = released / 'verification'
    # Copy only the owner's final verification records. Failed transient test
    # attempts remain outside this release and are described in its report.
    for name in ['native-build150.json', 'native-build150.log', 'native-tests150.log',
                 'pad-tests150.log', 'python-recovery150.log']:
        assert (B / name).is_file(), f'Missing final verification evidence: {name}'
        shutil.copy2(B / name, verification / name)
    shutil.copy2(B / 'scratch/build_arm150.py', verification / 'build_arm150.py')
    shutil.copy2(Path(__file__), verification / 'package150.py')
    public_tools = B / 'scratch/build_environment150'
    restore = json.loads((public_tools / 'toolchain-restore147.json').read_text())
    provenance = {key: restore[key] for key in ['tool_versions', 'python_versions', 'rust_downloads',
                                               'python_downloads', 'cargo_zigbuild', 'source_cargo_lock']}
    write_json(verification / 'toolchain-provenance150.json', provenance)
    for name in ['READY.json', 'libudev-sysroot.json', 'libudev-host.json', 'pkgconf.json']:
        shutil.copy2(public_tools / name, verification / ('build-environment150-' + name))
    audit = dict(console_version=VERSION, service_build=BUILD, tests=tests,
                 current_recovery_report_sha256=digest(recovery_path),
                 payload_changed_files=payload_changed, console_changed_files=console_changed,
                 source_console_synchronized_from_actual_v149=sync,
                 source_packaging_synchronized_to_final_payload=packaging_sync,
                 preserved_payload_files=[old_firmware[name] for name in sorted(preserved)],
                 payload_file_count=len(stage_records), source_native_changed_files=sorted(native_changed),
                 models_and_configs_byte_identical=True, hat_sha256=digest(console / 'updates/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin'),
                 bundle_info=json.loads(result.stdout), prepared_firmware_import_verified=True,
                 elf=elf, hardware_tested=False, signed_urls_in_provenance=False)
    write_json(verification / 'release-audit150.json', audit)
    summary = json.loads((SOURCE / 'R17-SOURCE-MANIFEST.json').read_text())
    summary.update(console_version=VERSION, service_build=BUILD,
                   release_changed_files=changed(old_source, record_map(released)),
                   release_removed_files=[name for name in old_source if not (released / name).exists()],
                   files=records(released, ['R17-SOURCE-MANIFEST.json', 'SHA256SUMS']))
    write_json(released / 'R17-SOURCE-MANIFEST.json', summary)
    (released / 'SHA256SUMS').write_text(''.join(
        f"{r['sha256']}  {r['path']}\n" for r in records(released, ['SHA256SUMS'])))
    verify_checksums(released)
    source_archive = OUT / (released.name + '.tar.gz')
    make_tar(released, source_archive)
    verify_tar(released, source_archive)
    artifacts = [console_zip, source_archive]
    sums = OUT / f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in artifacts))
    report = dict(artifacts=[dict(name=p.name, bytes=p.stat().st_size, sha256=digest(p)) for p in artifacts],
                  checksum_file=str(sums), stage=str(stage), released_source=str(released),
                  payload_changed_files=payload_changed, console_changed_files=console_changed,
                  verified=True, hardware_tested=False)
    write_json(WORK / 'package150-result.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assemble', action='store_true', help='Assemble once the root agent marks final verified inputs ready')
    args = parser.parse_args()
    if args.assemble:
        assemble()
    else:
        print(json.dumps(dict(mode='read-only-plan', ready_inputs=dict(
            baseline_console=OLD_CONSOLE.is_dir(), baseline_firmware=OLD_FIRMWARE.is_dir(),
            original_source=OLD_SOURCE_ARCHIVE.is_file(),
            recovery_report=(SOURCE / 'verification/recovery150.json').is_file(),
            arm_binaries={name: (NATIVE / name).is_file() for name in NATIVE_NAMES}),
            output_names=[f'Microduck-Console-R17-v{VERSION}.zip', f'Microduck-Source-R17-v{VERSION}.tar.gz'],
            mutations='isolated scratch staging and output only; original source untouched'), indent=2))


if __name__ == '__main__':
    main()
