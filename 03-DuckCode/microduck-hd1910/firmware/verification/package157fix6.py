"""Package installation logging and handoff changes with unchanged control.36."""
from pathlib import Path
import datetime,hashlib,importlib.util,json,os,re,subprocess,sys,tarfile,zipfile
from package157fix1 import digest,files,records,write

SOURCE=Path(__file__).resolve().parents[1]
BASELINE=SOURCE.with_name('Microduck-Source-R17-v1.0.157-Fix5')
CONSOLE=SOURCE/'console';PACKAGING=SOURCE/'packaging';OUT=SOURCE.parents[2]/'output'
VERSION='1.0.157-Fix6';BUILD='1fa8438-feetech-ft6-control.36'


def main():
    runs=json.loads((SOURCE/'verification/fix6-tests.json').read_text())
    counts={}
    for run in runs:
        assert run['exit_code']==0,run
        log=SOURCE/run['log'];run['sha256']=digest(log)
        if run['name'] in {'pc-fix','streams','query','install','order','runtime'}:
            body=log.read_text();counts[run['name']]=int(re.search(r'Ran (\d+) tests',body).group(1))
            assert body.rstrip().endswith('OK'),run
    assert counts=={'pc-fix':38,'streams':32,'query':15,'install':32,'order':17,'runtime':17},counts
    tests={'python_passed':sum(counts.values()),'browser_scripts_passed':len(runs)-6,
           'runs':runs,'robot_hardware_tested':False,'windows_native_tested':False,
           'native_suite_rerun':False,'full_historical_suite_rerun':False,
           'socket_boundary_note':'Loopback TCP is substituted only at the OS boundary where AF_UNIX creation is restricted; upload receiver is executed locally on real files.'}
    assert tests['browser_scripts_passed']==10
    old_manifest=json.loads((BASELINE/'R17-SOURCE-MANIFEST.json').read_text())
    for name,sha in old_manifest['native_source_sha256'].items():assert digest(SOURCE/name)==sha,name
    spec=importlib.util.spec_from_file_location('release_elf',PACKAGING/'elf_integrity.py')
    integrity=importlib.util.module_from_spec(spec);spec.loader.exec_module(integrity)
    elf_ranges=integrity.validate_bundle(PACKAGING)
    for name in integrity.NATIVE_FILES:assert digest(PACKAGING/name)==digest(BASELINE/'packaging'/name),name
    for name,path in files(PACKAGING).items():
        if name.startswith('models/'):assert digest(path)==digest(BASELINE/'packaging'/name),name
    allowed={'service.sh','runtime.py','gamepad.py','voice-setup.py','elf_integrity.py',
             'release_identity.py','README.zh-CN.md','BUILD.json'}
    old_payload=json.loads((BASELINE/'packaging/install-files.json').read_text())
    payload_changes=[]
    for name in old_payload:
        if digest(PACKAGING/name)!=digest(BASELINE/'packaging'/name):
            assert name in allowed,name;payload_changes.append(name)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    build=json.loads((BASELINE/'BUILD.json').read_text())
    build.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,
                 release_changes='Robotd four-step push readiness before data/input; remove legacy startup migrations; shared process query and named model logs.',
                 firmware_reinstall_required=True,rebuilt_binaries=[],reused_binaries=list(build['built_binaries']),
                 native_production_changes=[],tests=tests,verification_report='verification/changes157fix6.json',
                 previous_native_build='verification/native-build157fix2.json')
    write(SOURCE/'BUILD.json',build);write(PACKAGING/'BUILD.json',build)
    names=sorted(set(old_payload)|{'R157-Fix6.md','startup_gate.py'})
    write(PACKAGING/'install-files.json',names)
    payload=names+['install-files.json']
    (PACKAGING/'SHA256SUMS').write_text(''.join(f'{digest(PACKAGING/name)}  {name}\n' for name in sorted(payload)))
    payload.append('SHA256SUMS')
    firmware=CONSOLE/'updates/Microduck-Robotd-FT6-R17.tar.gz'
    with tarfile.open(firmware,'w:gz',compresslevel=6) as archive:
        for name in sorted(payload):archive.add(PACKAGING/name,arcname='Microduck-Robotd-FT6-R17/'+name,recursive=False)
    with tarfile.open(firmware,'r:gz') as archive:
        stored={m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert stored=={name:digest(PACKAGING/name) for name in payload}
    firmware_sha=digest(firmware)
    changed=[name for name,path in files(SOURCE).items() if not (BASELINE/name).is_file() or digest(path)!=digest(BASELINE/name)]
    report={'console_version':VERSION,'service_build':BUILD,'release_baseline':BASELINE.name,
            'firmware_reinstall_required':True,'firmware_archive_byte_identical':False,'firmware_sha256':firmware_sha,
            'native_sources_unchanged':True,'native_binaries_unchanged':True,'model_weights_unchanged':True,
            'hat_firmware_unchanged':True,'added_50hz_work':False,'added_robot_threads_or_polling':False,
            'installed_script_changes':sorted(set(payload_changes)|{'BUILD.json','startup_gate.py'}),
            'installation':{'robotd_before_input_setup':True,'four_steps_from_installer_push_events':True,'optional_setup_failure_keeps_robotd_running':True,'recovery_setting_idempotent':True,'step_result_logging':True,'complete_error_causes_preserved':True,
                            'raw_success_commands_and_receipts_not_displayed':True,
                            'upload_progress_from_existing_byte_writes':True,'remote_fsync_and_sha256_comparison':True,
                            'install_bus_status_query_removed':True,'missing_success_receipt_is_failure':True,
                            'robot_stop_failure_aborts_install':True,'input_failure_does_not_gate_robotd':True},
            'boot_input':{'four_step_event_gate':True,'inotify_socket_creation':True,'native_exec_after_ready':True,'temporary_waiters':True,'failed_wait_does_not_restart_robotd':True},
            'legacy_startup_migration_removed':True,'process_query_shared_per_instance':True,'model_log_lists_names':True,
            'handoff':{'close_old_data_and_startup_streams':True,'condition_wait_during_install':True,
                       'resume_only_after_all_four_core_steps':True,'initial_reconnect_attempts':1,
                       'first_reconnect_failure_stops_automatic_attempts':True,'manual_ssh_connect_unpauses':True,
                       'independent_tof_preserved':True,'startup_snapshot_subscription_preserved':True,'early_state_separate_from_raw':True,'extra_startup_thread_removed':True,'ssh_forward_reused_at_raw_handoff':True},
            'tests':tests,'elf_ranges':elf_ranges,'changed_files':changed,
            'previous_native_results':'verification/native-build157fix2.json; historical, not rerun'}
    write(SOURCE/'verification/changes157fix6.json',report)
    manifest=json.loads((BASELINE/'console/BUILD_MANIFEST.json').read_text())
    manifest.update(console_version=VERSION,source_distribution=SOURCE.name+'.tar.gz',generated_at_utc=now,
                    firmware_reinstall_required=True,tests_run_in_release=tests,release_changes='docs/releases/R157-Fix6.md',
                    service_package_sha256=firmware_sha,files=records(CONSOLE,('BUILD_MANIFEST.json',)))
    write(CONSOLE/'BUILD_MANIFEST.json',manifest)
    OUT.mkdir(exist_ok=True);console_zip=OUT/f'Microduck-Console-R17-v{VERSION}.zip'
    with zipfile.ZipFile(console_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in files(CONSOLE).items():archive.write(path,f'Microduck-Console-R17-v{VERSION}/'+name)
    with zipfile.ZipFile(console_zip) as archive:
        assert archive.testzip() is None
        zipped={name.split('/',1)[1]:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    assert zipped=={name:digest(path) for name,path in files(CONSOLE).items()}
    code='''import hashlib,json,sys
from pathlib import Path
from firmware_packages import bundle_info,PreparedFirmware
p=Path(sys.argv[1]);info=bundle_info()
assert info['console_version']=='1.0.157-Fix6' and info['build']=='1fa8438-feetech-ft6-control.36'
with p.open('rb') as stream:
 prepared=PreparedFirmware(p.name,stream,p.stat().st_size,'fix6-release-audit')
 try:assert hashlib.sha256(prepared.path.read_bytes()).hexdigest()==info['sha256']
 finally:prepared.close()
print(json.dumps(info,ensure_ascii=False))
'''
    checked=subprocess.run([sys.executable,'-c',code,str(console_zip)],cwd=CONSOLE,
                           env={**os.environ,'PYTHONPATH':str(CONSOLE)},capture_output=True,text=True,check=True)
    write(SOURCE/'verification/release-audit157fix6.json',
          {'console_version':VERSION,'service_build':BUILD,'firmware_sha256':firmware_sha,
           'production_firmware_importer':json.loads(checked.stdout),'zip_files':len(zipped),'tests':tests,
           'native_binaries_unchanged':True,'elf_ranges_checked':True})
    source_manifest=dict(old_manifest)
    source_manifest.update(console_version=VERSION,release_baseline=BASELINE.name,
                           release_changes='verification/changes157fix6.json',verification='verification/release-audit157fix6.json',
                           firmware_reinstall_required=True,native_sources_unchanged=True)
    write(SOURCE/'R17-SOURCE-MANIFEST.json',source_manifest)
    source_archive=OUT/(SOURCE.name+'.tar.gz')
    with tarfile.open(source_archive,'w:gz',compresslevel=6) as archive:
        for name,path in files(SOURCE).items():archive.add(path,arcname=SOURCE.name+'/'+name,recursive=False)
    with tarfile.open(source_archive,'r:gz') as archive:
        saved={m.name.split('/',1)[1]:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive}
    assert saved=={name:digest(path) for name,path in files(SOURCE).items()}
    sums=OUT/f'SHA256SUMS-v{VERSION}.txt'
    sums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in (console_zip,source_archive)))
    print(json.dumps({'files':[{'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path)} for path in (console_zip,source_archive,sums)],
                      'tests':{'python_passed':tests['python_passed'],'browser_scripts_passed':tests['browser_scripts_passed']},
                      'firmware_sha256':firmware_sha,'firmware_reinstall_required':True},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
