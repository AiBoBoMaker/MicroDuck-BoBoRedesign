"""Release only the GameSir repair/UI and bridge device-wait changes."""
from pathlib import Path
import ast, datetime, hashlib, importlib.util, json, os, re, subprocess, sys, tarfile, zipfile
from package157fix1 import digest, files, records, write

SOURCE = Path(__file__).resolve().parents[1]
BASELINE = SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix7')
CONSOLE = SOURCE/'console'; PACKAGING = SOURCE/'packaging'; OUT = SOURCE.parents[2]/'output'
VERSION = '1.0.157-Fix8'; BUILD = '1fa8438-feetech-ft6-control.36'
BRIDGE = 'gamepad-r7/gamesir-xboxd'


class NonRepairScope(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        if node.name == 'repair_gamepad':return ast.Pass()
        return self.generic_visit(node)
    def visit_Dict(self, node):
        node = self.generic_visit(node)
        for n, key in enumerate(node.keys):
            if isinstance(key, ast.Constant) and key.value == 'repair-gamepad':node.values[n] = ast.Constant(None)
        return node
    def visit_If(self, node):
        node = self.generic_visit(node)
        if ast.unparse(node.test) in ["action == 'repair-gamepad'", "command['action'] == 'repair-gamepad'"]:
            node.body = [ast.Pass()]
        return node


def main():
    runs = json.loads((SOURCE/'verification/fix8-tests.json').read_text())
    counts = {}
    for run in runs:
        assert run['exit_code'] == 0, run
        log = SOURCE/run['log'];run['sha256'] = digest(log)
        if run['name'] in {'repair','input','order','install'}:
            body = log.read_text();counts[run['name']] = int(re.search(r'Ran (\d+) tests',body).group(1))
            assert body.rstrip().endswith('OK'), run
    assert counts == {'repair':30,'input':38,'order':17,'install':32}, counts
    tests = {'python_passed':sum(counts.values()), 'frontend_logic_scripts_passed':6,
             'c_regression_executables_passed':2, 'runs':runs, 'actual_linux_inotify_tested':True,
             'robot_hardware_tested':False, 'windows_native_tested':False, 'browser_pixel_rendered':False,
             'rust_native_suite_rerun':False}
    old_manifest = json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())
    for name, sha in old_manifest['native_source_sha256'].items():assert digest(SOURCE/name) == sha, name
    a = ast.dump(NonRepairScope().visit(ast.parse((CONSOLE/'service_control.py').read_text())))
    b = ast.dump(NonRepairScope().visit(ast.parse((BASELINE/'console/service_control.py').read_text())))
    assert a == b, 'Non-repair service flow changed'
    protected = ['packaging/service.sh','packaging/startup_gate.py','packaging/runtime.py','packaging/gamepad.py',
                 'packaging/configure.py','packaging/voice-setup.py','console/raw_telemetry.py','console/remote_input.py',
                 'console/controls.py','console/service_rpc.py','console/connection.py','console/static/control.js',
                 'console/static/control-socket.js','console/static/service.js','console/static/index.html',
                 'console/static/r17-0151.css']
    for name in protected:assert digest(SOURCE/name) == digest(BASELINE/name), name
    old_c = (BASELINE/'gamepad-r7/gamesir-xboxd.c').read_text()
    new_c = (SOURCE/'gamepad-r7/gamesir-xboxd.c').read_text()
    assert old_c[:old_c.index('static int64_t monotonic_ms')] == new_c[:new_c.index('struct input_watch')].replace('#include <sys/inotify.h>\n','')
    segment = lambda text:text[text.index('static bool input_disconnected'):text.index('static int run_bridge')]
    assert segment(old_c) == segment(new_c), 'Input forwarding changed'
    prefix = lambda text:text[text.index('static int run_bridge'):text.index('    struct pollfd pollfds[')]
    assert prefix(old_c) == prefix(new_c).replace(', struct input_watch *watch',''), 'Mapping setup changed'
    assert 'sleep(' not in new_c and 'retry_consumer_input' not in new_c
    assert digest(SOURCE/BRIDGE) == digest(PACKAGING/BRIDGE)
    spec = importlib.util.spec_from_file_location('release_elf',PACKAGING/'elf_integrity.py')
    integrity = importlib.util.module_from_spec(spec);spec.loader.exec_module(integrity)
    elf = integrity.validate_bundle(PACKAGING)
    for name in integrity.NATIVE_FILES:
        if name != BRIDGE:assert digest(PACKAGING/name) == digest(BASELINE/'packaging'/name), name
    current_payload = files(PACKAGING)
    changed_payload = [name for name,path in current_payload.items() if not (BASELINE/'packaging'/name).is_file() or digest(path) != digest(BASELINE/'packaging'/name)]
    assert set(changed_payload)-{'BUILD.json','SHA256SUMS'} == {BRIDGE,'release_identity.py'}, changed_payload
    current_console = files(CONSOLE)
    changed_console = [name for name,path in current_console.items() if not (BASELINE/'console'/name).is_file() or digest(path) != digest(BASELINE/'console'/name)]
    assert set(changed_console)-{'BUILD_MANIFEST.json','updates/Microduck-Robotd-FT6-R17.tar.gz'} == {'service_control.py','release_identity.py','gamepad_repair.py','README.zh-CN.md',
                                   'static/control.css','static/gamepad-repair.js','docs/releases/R157-Fix8.md',
                                   'verification/test_gamepad_repair.py','verification/test_gamepad_repair_ui.mjs'}, changed_console
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = json.loads((BASELINE/'BUILD.json').read_text())
    dynamic = subprocess.check_output(['readelf','-d',str(PACKAGING/BRIDGE)],text=True)
    versions = subprocess.check_output(['readelf','-V',str(PACKAGING/BRIDGE)],text=True)
    metadata['built_binaries'][BRIDGE] = {'sha256':digest(PACKAGING/BRIDGE),'machine':'AArch64',
                                        'bytes':(PACKAGING/BRIDGE).stat().st_size,
                                        'needed':re.findall(r'Shared library: \[(.*?)\]',dynamic),
                                        'glibc_versions':sorted(set(re.findall(r'GLIBC_(\d+\.\d+)',versions)))}
    assert metadata['built_binaries'][BRIDGE]['glibc_versions'] == ['2.17']
    metadata.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz', generated_at_utc=now,
                    firmware_reinstall_required=True, rebuilt_binaries=[BRIDGE],
                    reused_binaries=[n for n in metadata['built_binaries'] if n != BRIDGE],
                    native_production_changes=['gamepad-r7/gamesir-xboxd.c'],tests=tests,
                    release_changes='Scoped GameSir connection recovery, explicit pairing, original btd state restoration and hotplug-only bridge discovery.',
                    verification_report='verification/changes157fix8.json')
    write(SOURCE/'BUILD.json',metadata);write(PACKAGING/'BUILD.json',metadata)
    names = json.loads((BASELINE/'packaging/install-files.json').read_text())
    assert json.loads((PACKAGING/'install-files.json').read_text()) == names
    payload = names+['install-files.json']
    (PACKAGING/'SHA256SUMS').write_text(''.join(f'{digest(PACKAGING/name)}  {name}\n' for name in sorted(payload)))
    payload += ['SHA256SUMS']
    firmware = CONSOLE/'updates/Microduck-Robotd-FT6-R17.tar.gz'
    with tarfile.open(firmware,'w:gz',compresslevel=6) as archive:
        for name in sorted(payload):archive.add(PACKAGING/name,arcname='Microduck-Robotd-FT6-R17/'+name,recursive=False)
    with tarfile.open(firmware,'r:gz') as archive:
        saved = {m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved == {name:digest(PACKAGING/name) for name in payload}
    firmware_sha = digest(firmware)
    report = {'console_version':VERSION,'service_build':BUILD,'release_baseline':BASELINE.name,
              'firmware_reinstall_required':True,'firmware_sha256':firmware_sha,
              'robotd_robotctl_padd_sounds_onnx_models_unchanged':True,'core_rust_sources_unchanged':True,
              'non_repair_service_controller_ast_identical':True,'protected_files':{n:digest(SOURCE/n) for n in protected},
              'startup_four_steps_and_install_sequence_unchanged':True,'raw_ssh_webpad_arbitration_unchanged':True,
              'r7_mapping_and_input_forwarding_identical':True,'bridge_binary':metadata['built_binaries'][BRIDGE],
              'changed_installed_payloads':[BRIDGE,'release_identity.py','BUILD.json','SHA256SUMS'],
              'added_robot_50hz_work':False,'added_resident_services_or_threads':False,
              'routine_repair':{'healthy_noop':True,'keeps_old_bond_on_connection_failure':True,
                                'only_missing_or_failed_layer_started_or_restarted':True,'startup_waiters_not_restarted':True,
                                'no_robotd_restart_or_torque_command':True,'no_phone_service_action':True},
              'explicit_pairing':{'user_selected_only':True,'existing_relax_confirmation_reused':True,'target_bond_only':True,
                                  'adapter_reset_once':True,'no_automatic_reboot':True,'btd_original_running_state_only':True,
                                  'unit_enable_disable_never_written':True,'phone_restore_error_separate':True},
              'input_wait':{'real_inotify':True,'no_periodic_device_scan':True,'temporary_repair_watcher':True,
                            'padd_device_open_checked':True,'padd_open_does_not_prove_multi_pad_priority':True},
              'logging':{'named_step_terminal_outcomes':True,'raw_progress_json_not_displayed':True,
                         'last_check_separate_from_current_input_events':True,'robot_motion_state_separate':True},
              'tests':tests,'elf_integrity':elf,'changed_console_files':changed_console}
    write(SOURCE/'verification/changes157fix8.json',report)
    manifest = json.loads((BASELINE/'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION, source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,
                    firmware_reinstall_required=True,tests_run_in_release=tests,service_package_sha256=firmware_sha,
                    release_changes='docs/releases/R157-Fix8.md',files=records(CONSOLE,('BUILD_MANIFEST.json',)))
    write(CONSOLE/'BUILD_MANIFEST.json',manifest)
    OUT.mkdir(exist_ok=True)
    console_zip = OUT/f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in files(CONSOLE).items():archive.write(path,f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped = {name.split('/',1)[1]:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    assert zipped == {name:digest(path) for name,path in files(CONSOLE).items()}
    code = '''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix8' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix8-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked = subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
                             env={**os.environ,'PYTHONPATH':str(CONSOLE)},capture_output=True,text=True,check=True)
    write(SOURCE/'verification/release-audit157fix8.json',
          {'console_version':VERSION,'zip_files':len(zipped),'production_importer':json.loads(checked.stdout),
           'scope_verified':True,'firmware_sha256':firmware_sha,'tests':tests})
    source_manifest = json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())
    source_manifest.update(console_version=VERSION,release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix8.json',verification='verification/release-audit157fix8.json',
                           firmware_reinstall_required=True,native_sources_unchanged=False,core_rust_sources_unchanged=True,
                           gamepad_bridge_source_sha256=digest(SOURCE/'gamepad-r7/gamesir-xboxd.c'))
    write(SOURCE/'R17-SOURCE-MANIFEST.json',source_manifest)
    source_archive = OUT/(SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive,'w:gz',compresslevel=6) as archive:
        for name,path in files(SOURCE).items():archive.add(path,arcname=SOURCE.name+'/'+name,recursive=False)
    with tarfile.open(source_archive,'r:gz') as archive:
        saved = {m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved == {name:digest(path) for name,path in files(SOURCE).items()}
    sums = OUT/f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip,source_archive)))
    print(json.dumps({'files':[{'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path)}
                               for path in (console_zip,source_archive,sums)],'tests':tests,
                      'firmware_reinstall_required':True,'service_build':BUILD},ensure_ascii=False,indent=2))


if __name__ == '__main__':main()
