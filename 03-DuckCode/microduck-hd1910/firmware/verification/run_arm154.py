from pathlib import Path
import json, hashlib, os, subprocess, time
B=Path(__file__).resolve().parent
S=B/'source/Microduck-Source-R17-v1.0.154'
binary=B/'build152/target-arm/aarch64-unknown-linux-gnu/release/robotd'
library=B/'firmware154-base/Microduck-Robotd-FT6-R17/onnxruntime/libonnxruntime.so.1.28.0'
prefix=B/'sigbus-repro/root241'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
models=json.loads((S/'config/r17-management.json').read_text())['builtin_models']
results=[]
env={**os.environ,'LD_LIBRARY_PATH':str(prefix/'usr/lib/aarch64-linux-gnu'),'TOKIO_WORKER_THREADS':'2'}
for model in models:
 path=S/'packaging/models'/model['id']/'policy.onnx'
 cmd=[str(B/'sigbus-repro/qemu/usr/bin/qemu-aarch64-static'),'-L',str(prefix),'-E','ORT_DYLIB_PATH='+str(library),str(binary),'validate-policy',str(path)]
 start=time.monotonic();r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=60)
 (B/('arm154-'+model['id']+'.log')).write_text(r.stdout+r.stderr)
 valid=json.loads(r.stdout) if r.returncode==0 else None
 results.append({'slot':model['slot'],'id':model['id'],'model_sha256':sha(path),'command':cmd,'exit_code':r.returncode,'elapsed_seconds':round(time.monotonic()-start,3),'result':valid,'log':'arm154-'+model['id']+'.log'})
 print(model['slot'],r.returncode,valid,flush=True)
record={'build':'1fa8438-feetech-ft6-control.33','robotd_sha256':sha(binary),'library_sha256':sha(library),'library_bytes':library.stat().st_size,'results':results,'environment_fixture':'QEMU ARM A55 proc/sys cpuinfo prefix retained from reproduction153; not deployed','hardware_tested':False}
(B/'arm-policy154.json').write_text(json.dumps(record,indent=2)+'\n')
assert len(results)==5 and all(r['exit_code']==0 and r['result']=={'actions':14,'input':'obs','observations':61,'valid':True} for r in results)
