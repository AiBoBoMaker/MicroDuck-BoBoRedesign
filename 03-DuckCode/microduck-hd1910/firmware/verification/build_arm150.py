from pathlib import Path
import datetime, hashlib, json, os, subprocess

root=Path('/workspace/scratch/5a402859beee')
source=root/'source/Microduck-Source-R17-v1.0.149'
target=Path('/tmp/r17-native-arm150')
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def sources():
    return {str(p.relative_to(source)):digest(p) for p in source.rglob('*')
            if p.is_file() and 'verification' not in p.relative_to(source).parts
            and (p.suffix=='.rs' or p.name in ('Cargo.toml','Cargo.lock'))}
record={'source_sha256':sources(),'hardware_tested':False,'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
env=os.environ.copy()
env.update(CARGO_TARGET_DIR=str(target),CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0')
command=['bash','-c','source /workspace/scratch/5a402859beee/scratch/build_environment150/env-arm64.sh\nexport CARGO_TARGET_DIR=/tmp/r17-native-arm150\nexport CARGO_BUILD_JOBS=2\nexport CARGO_INCREMENTAL=0\ncargo zigbuild -p robotd -p robotctl -p padd --release --target aarch64-unknown-linux-gnu.2.31 --frozen']
record['command']=command
with (root/'native-build150.log').open('w') as log:
    proc=subprocess.Popen(command,cwd=source,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    for line in proc.stdout:
        log.write(line);log.flush();print(line,end='',flush=True)
    record['exit_code']=proc.wait()
record['source_sha256_unchanged']=sources()==record['source_sha256']
record['finished_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
if record['exit_code']==0:
    record['binaries']={n:digest(target/'aarch64-unknown-linux-gnu/release'/n) for n in ('robotd','robotctl','padd')}
(root/'native-build150.json').write_text(json.dumps(record,indent=2)+'\n')
assert record['source_sha256_unchanged'],'sources changed during release build'
raise SystemExit(record['exit_code'])
