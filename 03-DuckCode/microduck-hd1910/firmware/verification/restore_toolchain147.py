#!/usr/bin/env python3
"""Restore pinned R17 build tools locally; never build or modify project sources."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import threading
import urllib.request

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source/Microduck-Source-R17-v1.0.147'
CACHE = Path('/tmp/r17-toolchain-downloads')
RUST = Path('/tmp/r17-rust/toolchains/1.99.0-x86_64-unknown-linux-gnu')
TOOLS = Path('/tmp/r17-native-tools')
CARGO = Path('/tmp/r17-cargo')
REPORT = BASE / 'toolchain-restore147.json'
LOCK = threading.Lock()
RECORD = {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'source': str(SOURCE), 'source_build_or_test_run': False,
          'rust_downloads': [], 'python_downloads': [], 'commands': []}


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save():
    with LOCK:
        REPORT.write_text(json.dumps(RECORD, indent=2) + '\n')


def fetch(url, path):
    path = Path(path)
    if not path.exists():
        part = path.with_suffix(path.suffix + '.part')
        print('Downloading', url, flush=True)
        with urllib.request.urlopen(url, timeout=120) as r, part.open('wb') as f:
            while chunk := r.read(1024 * 1024):
                f.write(chunk)
        part.replace(path)
    return path


def run(args, name, env=None, cwd=None):
    logfile = BASE / (name + '.log')
    print('Running', name, flush=True)
    with logfile.open('w') as log:
        result = subprocess.run([str(a) for a in args], stdout=log, stderr=subprocess.STDOUT,
                                env=env, cwd=cwd)
    with LOCK:
        RECORD['commands'].append({'args': [str(a) for a in args], 'log': str(logfile),
                                   'cwd': str(cwd) if cwd else None,
                                   'exit_code': result.returncode})
    save()
    if result.returncode:
        raise RuntimeError(f'{name} failed ({result.returncode}): {logfile}')


def rust_component(stem):
    url = 'https://static.rust-lang.org/dist/' + stem + '.tar.xz'
    sha_url = url + '.sha256'
    sha_file = fetch(sha_url, CACHE / (stem + '.tar.xz.sha256'))
    expected = sha_file.read_text().split()[0]
    archive = fetch(url, CACHE / (stem + '.tar.xz'))
    actual = digest(archive)
    if actual != expected:
        raise ValueError('Rust component checksum mismatch: ' + stem)
    with LOCK:
        RECORD['rust_downloads'].append({'url': url, 'sha256_url': sha_url,
                                         'sha256': actual, 'verified': True})
    save()
    return archive


def install_rust():
    components = ['rustc-1.99.0-x86_64-unknown-linux-gnu',
                  'cargo-1.99.0-x86_64-unknown-linux-gnu',
                  'rust-std-1.99.0-x86_64-unknown-linux-gnu',
                  'rust-std-1.99.0-aarch64-unknown-linux-gnu',
                  'rustfmt-1.99.0-x86_64-unknown-linux-gnu']
    with ThreadPoolExecutor(max_workers=5) as pool:
        archives = list(pool.map(rust_component, components))
    for stem, archive in zip(components, archives):
        dest = CACHE / stem
        if not dest.is_dir():
            with tarfile.open(archive) as tar:
                tar.extractall(CACHE, filter='data')
        run(['bash', dest / 'install.sh', '--prefix=' + str(RUST), '--disable-ldconfig'],
            'restore147-' + stem)
    print('RUST_READY', str(RUST), flush=True)


def install_python():
    wheel_dir = CACHE / 'wheels'
    wheel_dir.mkdir(exist_ok=True)
    requirements = ['onnx==1.23.2', 'onnxruntime==1.28.0', 'ziglang==0.14.1',
                    'numpy==2.5.3', 'protobuf==7.36.2', 'typing_extensions==4.16.0',
                    'ml_dtypes==0.6.0', 'flatbuffers==25.12.19', 'packaging==26.3']
    run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--dest', wheel_dir,
         '--index-url', 'https://pypi.org/simple', *requirements], 'restore147-pip-download')
    # Verify every downloaded wheel against its official PyPI JSON release digest.
    from packaging.utils import parse_wheel_filename
    for wheel in sorted(wheel_dir.glob('*.whl')):
        name, version, _, _ = parse_wheel_filename(wheel.name)
        metadata_url = f'https://pypi.org/pypi/{name}/{version}/json'
        with urllib.request.urlopen(metadata_url, timeout=60) as response:
            metadata = json.load(response)
        artifact = next(row for row in metadata['urls'] if row['filename'] == wheel.name)
        actual = digest(wheel)
        if actual != artifact['digests']['sha256']:
            raise ValueError('PyPI wheel checksum mismatch: ' + wheel.name)
        with LOCK:
            RECORD['python_downloads'].append({'package': str(name), 'version': str(version),
                'url': artifact['url'], 'metadata_url': metadata_url, 'filename': wheel.name,
                'sha256': actual, 'verified': True})
    save()
    run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', wheel_dir,
         '--target', TOOLS, '--upgrade', *requirements], 'restore147-pip-install')
    print('PYTHON_READY', str(TOOLS), flush=True)


def environment():
    env = os.environ.copy()
    env.update(PATH=f'{RUST}/bin:{TOOLS}/bin:{TOOLS}/ziglang:' + env['PATH'],
               PYTHONPATH=str(TOOLS), CARGO_HOME=str(CARGO), RUSTUP_HOME='/tmp/r17-rust',
               ORT_DYLIB_PATH=str(TOOLS / 'onnxruntime/capi/libonnxruntime.so.1.28.0'))
    return env


def bootstrap_cargo():
    env = environment()
    env['CARGO_TARGET_DIR'] = '/tmp/r17-bootstrap-target'
    run(['cargo', 'install', 'cargo-zigbuild', '--version', '0.23.4', '--locked',
         '--root', TOOLS], 'restore147-cargo-zigbuild', env=env)


def fetch_source_dependencies():
    env = environment()
    env['CARGO_TARGET_DIR'] = '/tmp/r17-native-target'
    lock = SOURCE / 'Cargo.lock'
    before = digest(lock)
    run(['cargo', 'fetch', '--locked'], 'restore147-cargo-fetch', env=env, cwd=SOURCE)
    after = digest(lock)
    RECORD['source_cargo_lock'] = {'before_sha256': before, 'after_sha256': after,
                                   'unchanged': before == after}
    save()
    if before != after:
        raise RuntimeError('Project Cargo.lock changed during locked fetch')


def cargo_provenance():
    index = next((CARGO / 'registry/index').glob('*/.cache/ca/rg/cargo-zigbuild'))
    rows = [json.loads(item) for item in index.read_bytes().split(b'\0')
            if item.startswith(b'{')]
    metadata = next(row for row in rows if row['vers'] == '0.23.4')
    archive = next((CARGO / 'registry/cache').glob('*/cargo-zigbuild-0.23.4.crate'))
    actual = digest(archive)
    if actual != metadata['cksum']:
        raise ValueError('cargo-zigbuild registry checksum mismatch')
    return {'package': 'cargo-zigbuild', 'version': '0.23.4',
            'url': 'https://static.crates.io/crates/cargo-zigbuild/cargo-zigbuild-0.23.4.crate',
            'registry_metadata_url': 'https://index.crates.io/ca/rg/cargo-zigbuild',
            'sha256': actual, 'verified': True,
            'installed_binary_sha256': digest(TOOLS / 'bin/cargo-zigbuild')}


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)
    CARGO.mkdir(parents=True, exist_ok=True)
    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(install_rust), pool.submit(install_python)]
        for future in futures:
            future.result()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(bootstrap_cargo), pool.submit(fetch_source_dependencies)]
        for future in futures:
            future.result()
    env = environment()
    RECORD['tool_versions'] = {}
    for name, args in [('rustc', ['rustc', '--version']), ('cargo', ['cargo', '--version']),
                       ('rustfmt', ['rustfmt', '--version']),
                       ('cargo-zigbuild', ['cargo-zigbuild', '--version']), ('zig', ['zig', 'version'])]:
        RECORD['tool_versions'][name] = subprocess.check_output(args, env=env, text=True).strip()
    RECORD['python_versions'] = json.loads(subprocess.check_output([sys.executable, '-c',
        'import onnx,onnxruntime,numpy,json; print(json.dumps(dict(onnx=onnx.__version__,onnxruntime=onnxruntime.__version__,numpy=numpy.__version__)))'], env=env, text=True))
    RECORD['environment'] = {key: env[key] for key in
        ('PATH', 'PYTHONPATH', 'CARGO_HOME', 'RUSTUP_HOME', 'ORT_DYLIB_PATH')}
    RECORD['rustlib_targets'] = [p.name for p in (RUST / 'lib/rustlib').iterdir()
                                  if p.is_dir() and (p / 'lib').is_dir()]
    RECORD['cargo_zigbuild'] = cargo_provenance()
    RECORD['restore_script_sha256'] = digest(Path(__file__))
    RECORD['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    RECORD['ready'] = True
    save()
    print(json.dumps({key: RECORD[key] for key in ('tool_versions', 'python_versions', 'ready')}, indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        RECORD['error'] = str(exc)
        save()
        raise
