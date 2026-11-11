"""Local verification runner; records the exact native source used by the build."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parent
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.154'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_hashes():
    paths=[SOURCE/'Cargo.lock',SOURCE/'Cargo.toml']
    for folder in ('robotd','duck-control','robotd-params','duck-ipc-proto','kinematics','odometry','tof'):
        paths.extend((SOURCE/folder).rglob('*.rs'))
        paths.extend((SOURCE/folder).rglob('Cargo.toml'))
    return {str(p.relative_to(SOURCE)):sha(p) for p in sorted(set(paths))}

mode=sys.argv[1]
environment={**os.environ,**json.loads((BASE/'build152'/('env-arm.json' if mode=='arm' else 'env-host.json')).read_text())}
before=source_hashes();began=time.monotonic()
if mode=='arm':
    commands=[['cargo','zigbuild','-p','robotd','--release','--target','aarch64-unknown-linux-gnu.2.31','--frozen']]
    name='native-build154-final'
else:
    commands=[['cargo','test','-p','robotd','--bin','robotd','--frozen','startup','--','--test-threads=1'],
              ['cargo','test','-p','robotd','--bin','robotd','--frozen','cold_reopen','--','--test-threads=1'],
              ['cargo','test','-p','robotd','--bin','robotd','--frozen','reopened_uart','--','--test-threads=1'],
              ['cargo','test','-p','robotd','--bin','robotd','--frozen','r17_empty_snapshot','--','--test-threads=1'],
              ['cargo','test','-p','robotd','--bin','robotd','--frozen','unfiltered_skill','--','--test-threads=1']]
    name='native-tests154-final'
results=[]
with (BASE/(name+'.log')).open('w') as log:
    for command in commands:
        log.write('COMMAND: '+' '.join(command)+'\n');log.flush()
        code=subprocess.call(command,cwd=SOURCE,env=environment,stdout=log,stderr=subprocess.STDOUT)
        results.append({'command':command,'exit_code':code})
        if code:break
record={'commands':results,'exit_code':results[-1]['exit_code'],'elapsed_seconds':round(time.monotonic()-began,3),
        'source_sha256':before,'source_sha256_unchanged':before==source_hashes(),'hardware_tested':False}
if mode=='arm' and not record['exit_code']:
    binary=BASE/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
    record['binaries']={'robotd':sha(binary)}
    record['target']='aarch64-unknown-linux-gnu.2.31'
(BASE/(name+'.json')).write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='source_sha256'}),flush=True)
sys.exit(record['exit_code'])
