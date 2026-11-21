import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const source=path.resolve(process.argv[2]||fileURLToPath(new URL('../static',import.meta.url)));
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'microduck-commissioning-angle-'));
try{
  fs.cpSync(source,path.join(temporary,'static'),{recursive:true});
  fs.writeFileSync(path.join(temporary,'package.json'),'{"type":"module"}');
  const load=name=>import(pathToFileURL(path.join(temporary,'static',name)));
  const {adaptService}=await load('raw-telemetry.js');
  const {resolvePoseSample}=await load('pose-state.js');

  const ids=[20,21,22,23,24,30,31,32,33,34,10,11,12,13,14];
  const names=['left_hip_yaw','left_hip_roll','left_hip_pitch','left_knee','left_ankle','neck_pitch','head_pitch','head_yaw','head_roll','mouth','right_hip_yaw','right_hip_roll','right_hip_pitch','right_knee','right_ankle'];
  // Old machine zero near the far edge: at physical mid (2048) the file claims ~-163°.
  const staleZero=3900;
  const expectedSaved=(2048-staleZero)*360/4096;
  const joints=ids.map((id,index)=>({id,name:names[index],calibrated:true,direction:1,zero_raw:staleZero,min_rad:-2,max_rad:2}));
  const baseResult=()=>({
    channels:{bus:{status:'live',age_ms:0},state:{status:'waiting',age_ms:null},health:{status:'waiting',age_ms:null},tof:{status:'waiting',age_ms:null},system:{status:'waiting',age_ms:null},capabilities:{status:'waiting',age_ms:null},calibration:{status:'live',age_ms:0},startup:{status:'waiting',age_ms:null}},
    state:{},health:{},imu:{},servos:ids.map((id,index)=>({id,name:names[index],label:names[index],index,group:index<5?'left':index<10?'head':'right'})),
  });
  const sampleServos=ids.map((id,index)=>({id,joint:names[index],name:names[index],position_raw:2048,calibrated:true,speed_raw:0,load_raw:0,current_raw:0,voltage_v:12,temperature_c:35}));
  const report={mode:'commissioning',phase:'ready',updated_at_us:2_000_000,torque_state:'off',imu_mount_verified:true,motion:{},
    last_sample:{at_us:1_900_000,servos:sampleServos,imu:{gravity:[0,0,-1],valid:true}}};
  const calibration={calibration:{joints},calibration_path:'/etc/robot/feetech-ft5/hd1910-calibration.toml'};

  const check=(name,run)=>{run();console.log('PASS '+name);};

  check('commissioning keeps file conversion off live angle_deg and pose',()=>{
    const result=adaptService(baseResult(),structuredClone(report),structuredClone(calibration),20);
    for(const row of result.servos){
      assert.equal(row.position_raw,2048,`ID ${row.id} raw`);
      assert.equal(row.angle_deg,null,`ID ${row.id} must not expose file-corrected live angle`);
      assert.equal(row.target_deg,null);
      assert.equal(row.error_deg,null);
      assert.equal(row.calibrated,true);
      assert.equal(typeof row.saved_angle_deg,'number');
      assert.ok(Math.abs(row.saved_angle_deg-expectedSaved)<1e-9,`ID ${row.id} got ${row.saved_angle_deg}, want ${expectedSaved}`);
    }
    assert.equal(result.calibrated_count,15);
    assert.equal(result.saved_calibrated_count,15);
    const pose=resolvePoseSample({mode:'service',service_sample_fresh:true,servos:result.servos,channels:result.channels,imu:result.imu,bus:result.bus,state:{}});
    assert.equal(pose.live,false);
    assert.ok(pose.joints.every(v=>v===null),'3D must not follow a stale calibration file while commissioning');
  });

  check('motion mode still publishes live angles from robotd radians',()=>{
    const motionReport={mode:'motion',phase:'control',fresh_sample:true,policy_enabled:true,homed:true,torque_off_pending:false,read_recovery:'fresh',imu_mount_verified:true,
      native:{joints:ids.map((id,index)=>({id,joint:names[index],name:names[index],position_raw:2048,position_rad:0.1+index*0.01,calibrated:true,feedback_fresh:true})),torque_state_confirmed:true,imu_mount_verified:true}};
    const result=adaptService(baseResult(),motionReport,structuredClone(calibration),20);
    assert.equal(result.servos[0].saved_angle_deg,null);
    assert.ok(Math.abs(result.servos[0].angle_deg-(0.1*180/Math.PI))<1e-6);
    assert.equal(result.servos[0].calibrated,true);
  });
}finally{
  fs.rmSync(temporary,{recursive:true,force:true});
}
