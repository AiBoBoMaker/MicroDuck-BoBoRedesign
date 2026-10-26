from pathlib import Path
import hashlib, json, math, os, subprocess, sys
import numpy as np
BASE=Path(__file__).resolve().parent
SOURCE=BASE/'source/Microduck-Source-R17-v1.0.155'
FROZEN=BASE/'source/Microduck-Source-R17-v1.0.154'
sys.path.insert(0,str(BASE/'build152/python-tools'))
import onnxruntime as ort
record=json.loads((BASE/'native-tests154-final.json').read_text())
assert record['exit_code']==0
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
for rel,digest in record['source_sha256'].items():
    assert sha(SOURCE/rel)==digest,rel
binary=BASE/'build152/target-host/debug/deps/robotd-841120f08aa4bf66'
env={**os.environ,**json.loads((BASE/'build152/env-host.json').read_text())}
tests=[
'control::joint_uniform_tests::joint_uniform_real_onnx_uses_bundled_scale_and_official_filters_in_every_posture',
'control::joint_uniform_tests::joint_uniform_reload_keeps_raw_memory_and_reset_clears_it',
'control::selftrained_checks::explicit_home_ends_sitting_and_rising_and_resumes_the_walk_teacher']
results=[]
with (BASE/'home-policy155-native.log').open('w') as log:
    for test in tests:
        cmd=[str(binary),test,'--exact','--test-threads=1']
        log.write('COMMAND: '+' '.join(cmd)+'\n');log.flush()
        code=subprocess.call(cmd,cwd=BASE,env=env,stdout=log,stderr=subprocess.STDOUT)
        results.append({'test':test,'exit_code':code})
        assert code==0,test
model=SOURCE/'packaging/models/1cbf8730eadd75a5704332c9f3c10f60'
c=json.loads((model/'deployment-contract.json').read_text())
r=json.loads((model/'deployment-execution.json').read_text())
opts=ort.SessionOptions(); opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
sess=ort.InferenceSession(str(model/'policy.onnx'),opts,providers=['CPUExecutionProvider'])
name=sess.get_inputs()[0].name
home=np.array(c['runtime_home_rad'],dtype=np.float64)
names=c['runtime_joint_order']
head=set(c['action_filter']['head_joints'])
alpha=np.array([r['head_lowpass'] if n in head else r['legs_lowpass'] for n in names])
# A fixed synthetic observation sequence isolates episode reset and action mapping.
# This does not model robot dynamics, prove a physical cause, or predict falls.
def episode(position_delta_deg=0,tilt_deg=0):
    previous_action=np.zeros(14,dtype=np.float32)
    previous_target=None;targets=[]
    for tick in range(100):
        obs=np.zeros((1,61),dtype=np.float32)
        a=math.radians(tilt_deg)
        obs[0,3:6]=[math.sin(a),0,-math.cos(a)]
        # Synthetic equal and opposite hip pitch residuals, still inside the existing 5 degree guard.
        delta=np.zeros(14,dtype=np.float32)
        delta[2]=-math.radians(position_delta_deg);delta[11]=math.radians(position_delta_deg)
        obs[0,6:20]=delta
        obs[0,34:48]=previous_action
        action=sess.run(None,{name:obs})[0].reshape(14)
        target=home+r['action_scale']*action.astype(np.float64)
        if previous_target is not None:target=alpha*target+(1-alpha)*previous_target
        targets.append(target.copy());previous_target=target;previous_action=action
    return np.stack(targets)
a=episode();b=episode();lag=episode(4,8)
assert np.array_equal(a,b)
out={'hardware_tested':False,'source_native_unchanged_from_tested154':True,'native_tests':results,
'model_sha256':sha(model/'policy.onnx'),'runtime_execution':r,
'fixed_offline_sequence_not_physics':True,
'home_episodes_repeated':2,'ticks_per_episode':100,
'identical_home_episode_max_target_difference_deg':float(np.max(np.abs(a-b))*180/math.pi),
'synthetic_lag':{'max_joint_residual_deg':4,'imu_tilt_deg':8,'within_existing_start_guard':True,
'first_target_difference_from_exact_home_deg':float(np.max(np.abs(lag[0]-a[0]))*180/math.pi),
'max_target_difference_over_fixed_sequence_deg':float(np.max(np.abs(lag-a))*180/math.pi)},
'first_targets_exact_home_deg':dict(zip(names,np.round(a[0]*180/math.pi,6).tolist())),
'first_targets_synthetic_lag_deg':dict(zip(names,np.round(lag[0]*180/math.pi,6).tolist()))}
(BASE/'home-policy155-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if not k.startswith('first_targets')},ensure_ascii=False,indent=2))
