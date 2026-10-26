"""Package a layout-only console release without rewriting the Fix6 firmware."""
from pathlib import Path
import datetime, hashlib, json, os, subprocess, sys, tarfile, zipfile
from html.parser import HTMLParser
from package157fix1 import digest, files, records, write

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix6')
CONSOLE = SOURCE / 'console'
OUT = SOURCE.parents[2] / 'output'
VERSION = '1.0.157-Fix7'
BUILD = '1fa8438-feetech-ft6-control.36'


def main():
    # Inspect the shipped DOM, including controls' ancestry and unique IDs.
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__(); self.stack = []; self.ids = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                assert attrs['id'] not in self.ids, attrs['id']
                self.ids[attrs['id']] = list(self.stack)
            if tag not in {'meta','link','img','input','br','hr','source','area','wbr','embed','param','track','col'}:
                self.stack.append((tag, attrs.get('class', ''), attrs.get('id', '')))
        def handle_endtag(self, tag):
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]; break
    dom = Controls(); dom.feed((CONSOLE / 'static/index.html').read_text())
    for name in ('export', 'last-update'):
        assert any(tag == 'header' and cls == 'topbar' for tag, cls, _ in dom.ids[name]), name
        assert not any(cls == 'page-heading' for _, cls, _ in dom.ids[name]), name
    assert any(cls == 'heading-actions' for _, cls, _ in dom.ids['ssh-form'])
    old_dom = Controls(); old_dom.feed((BASELINE / 'console/static/index.html').read_text())
    assert dom.ids.keys() == old_dom.ids.keys()
    css = (CONSOLE / 'static/r17-0151.css').read_text()
    assert '.metrics{grid-template-columns:repeat(var(--health-columns),minmax(0,1fr));column-gap:var(--health-gap)}' in css
    assert '.page-heading{display:grid;grid-template-columns:repeat(var(--health-columns),minmax(0,1fr));column-gap:var(--health-gap);align-items:start}' in css
    assert '@media(min-width:2400px){.page-heading>:first-child{grid-column:1/-2}.page-heading .heading-actions{grid-column:-2/-1}}' in css
    assert 'max-width:720px' not in css
    runs = []
    for name in ('test_fix157pc', 'test_connection_ui155'):
        result = subprocess.run(['node', str(CONSOLE / 'verification' / (name+'.mjs')), str(CONSOLE / 'static')], capture_output=True, text=True)
        log = SOURCE / 'verification' / ('fix7-'+name+'.log')
        log.write_text(result.stdout+result.stderr)
        assert result.returncode == 0, result.stderr
        runs.append({'name': name, 'exit_code': result.returncode, 'log': str(log.relative_to(SOURCE)), 'sha256': digest(log)})
    tests = {'frontend_logic_scripts_passed': len(runs), 'runs': runs,
             'dom_structure_and_unique_ids_verified': True,
             'shared_grid_tracks_verified': True, 'browser_pixel_rendered': False,
             'robot_hardware_tested': False, 'native_suite_rerun': False}
    native = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())['native_source_sha256']
    for name, sha in native.items(): assert digest(SOURCE / name) == sha, name
    assert {k:digest(v) for k,v in files(SOURCE/'packaging').items()} == {k:digest(v) for k,v in files(BASELINE/'packaging').items()}
    firmware = CONSOLE / 'updates/Microduck-Robotd-FT6-R17.tar.gz'
    firmware_sha = digest(firmware)
    assert firmware_sha == digest(BASELINE / 'console/updates' / firmware.name)
    assert firmware_sha == '657c22814fea6038feb34a3d776bf4756969abc405388a51d7c8db54b930c51a'
    # The request changes no JavaScript, backend or robot payload.
    changes = [k for k,v in files(CONSOLE).items() if not (BASELINE/'console'/k).is_file() or digest(v) != digest(BASELINE/'console'/k)]
    assert set(changes) == {'static/index.html','static/r17-0151.css','README.zh-CN.md','docs/releases/R157-Fix7.md','release_identity.py'}, changes
    assert (CONSOLE/'release_identity.py').read_text() == (BASELINE/'console/release_identity.py').read_text().replace('1.0.157-Fix6','1.0.157-Fix7')
    report = {'console_version': VERSION, 'service_build': BUILD, 'release_baseline': BASELINE.name,
              'firmware_reinstall_required': False, 'firmware_archive_byte_identical': True,
              'firmware_sha256': firmware_sha, 'native_sources_unchanged': True, 'installed_payloads_unchanged': True,
              'javascript_and_backend_logic_unchanged': True, 'recording_controls_in_topbar': True,
              'ssh_shared_health_grid': True, 'desktop_wide_screen_zero_temperature_bounds_match': True,
              'narrow_screen_ssh_spans_multiple_columns': True, 'added_queries_or_polling': False,
              'changed_console_files': changes, 'tests': tests}
    write(SOURCE / 'verification/changes157fix7.json', report)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    build = json.loads((BASELINE / 'BUILD.json').read_text())
    build.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                 release_changes='Move recording export and time to the topbar; align SSH with health-card grid tracks.',
                 firmware_reinstall_required=False, rebuilt_binaries=[], reused_binaries=list(build['built_binaries']),
                 native_production_changes=[], tests=tests, verification_report='verification/changes157fix7.json')
    write(SOURCE / 'BUILD.json', build)
    manifest = json.loads((BASELINE / 'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                    firmware_reinstall_required=False, tests_run_in_release=tests,
                    release_changes='docs/releases/R157-Fix7.md', service_package_sha256=firmware_sha,
                    files=records(CONSOLE, ('BUILD_MANIFEST.json',)))
    write(CONSOLE / 'BUILD_MANIFEST.json', manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT / f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files(CONSOLE).items(): archive.write(path, f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        stored = {name.split('/',1)[1]:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    assert stored == {name:digest(path) for name,path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix7' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix7-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable, '-c', code, str(console_zip)], cwd=CONSOLE,
                             env={**os.environ, 'PYTHONPATH':str(CONSOLE)}, capture_output=True, text=True, check=True)
    write(SOURCE / 'verification/release-audit157fix7.json',
          {'console_version':VERSION, 'firmware_archive_byte_identical':True, 'firmware_sha256':firmware_sha,
           'zip_files':len(stored), 'production_firmware_importer':json.loads(checked.stdout), 'tests':tests})
    source_manifest = json.loads((BASELINE / 'R17-SOURCE-MANIFEST.json').read_text())
    source_manifest.update(console_version=VERSION, release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix7.json', verification='verification/release-audit157fix7.json',
                           firmware_reinstall_required=False, native_sources_unchanged=True)
    write(SOURCE / 'R17-SOURCE-MANIFEST.json', source_manifest)
    source_archive = OUT / (SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive, 'w:gz', compresslevel=6) as archive:
        for name,path in files(SOURCE).items(): archive.add(path, arcname=SOURCE.name+'/'+name, recursive=False)
    with tarfile.open(source_archive, 'r:gz') as archive:
        saved = {m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved == {name:digest(path) for name,path in files(SOURCE).items()}
    sums = OUT / f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip,source_archive)))
    print(json.dumps({'files':[{'path':str(path), 'bytes':path.stat().st_size, 'sha256':digest(path)}
                               for path in (console_zip,source_archive,sums)],
                      'tests':tests, 'firmware_reinstall_required':False}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
