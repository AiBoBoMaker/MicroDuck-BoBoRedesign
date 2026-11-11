"""Targeted repair, input and existing installation/startup regressions."""
from pathlib import Path
import json, os, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'PYTHONPATH':os.pathsep.join(map(str,[ROOT/'console',ROOT/'console/verification',ROOT/'packaging']))}
RESULTS = []


def run(name, command):
    result = subprocess.run(command,cwd=ROOT,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log = ROOT/'verification'/('fix9-'+name+'.log');log.write_text(result.stdout)
    RESULTS.append({'name':name,'exit_code':result.returncode,'log':str(log.relative_to(ROOT))})
    print(name,result.returncode,result.stdout[-500:] if result.returncode else result.stdout[-150:],flush=True)


for name, modules in [
    ('repair',['test_gamepad_repair']),
    ('input',['test_fix157pc','test_input157','test_console_exit156','test_connection_recovery']),
    ('order',['test_robotd_first157']),
    ('install',['test_install_log157','test_atomic_install']),
]:
    run(name,[sys.executable,'-m','unittest','-v',*modules])
for name in ['test_gamepad_repair_ui','test_fix157pc','test_robotd_first157','test_startup_ui','test_connection_ui155','test_controls154']:
    run(name,['node',str(ROOT/'console/verification'/f'{name}.mjs'),str(ROOT/'console/static')])
for name, source in [('mapping','gamepad-r7/test_mapping.c'),('disconnect','gamepad-r7/tests/test_gamesir_disconnect.c')]:
    executable='/tmp/r17-fix9-'+name
    run(name+'-compile',['cc','-O2','-Wall','-Wextra','-Werror',source,'-o',executable])
    if RESULTS[-1]['exit_code']==0:run(name,[executable])
write = ROOT/'verification/fix9-tests.json'
write.write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2)+'\n')
assert all(r['exit_code']==0 for r in RESULTS), 'See named regression logs'
