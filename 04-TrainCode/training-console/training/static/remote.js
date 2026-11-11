'use strict';
let remoteState=null,remoteUiBusy=false,remoteWasBusy=false,passwordPrompt=false,unlinkPending=false,modelUploading=false;
const sshLinkKey='microduck-ssh-linked';
function rememberLinked(on){try{if(on)sessionStorage.setItem(sshLinkKey,'1');else sessionStorage.removeItem(sshLinkKey);}catch(error){}}
let linkedByUser=false;
try{linkedByUser=sessionStorage.getItem(sshLinkKey)==='1';}catch(error){}
function markLinked(){if(remoteState&&remoteState.status==='connected'){linkedByUser=true;rememberLinked(true);}}
function clearLinked(){linkedByUser=false;rememberLinked(false);}
function activeConnection(){
 const value={...remoteState?.connection};
 return {host:(value.host||'').trim(),user:(value.user||'').trim(),port:Number(value.port)||22,identity:(value.identity||'').trim(),workspace:(value.workspace||'').trim(),auth:value.auth==='key'?'key':'password'};
}
function serverLabel(value){return value&&value.host?`${value.user||'ubuntu'}@${value.host}:${value.port||22}`:'尚未选择服务器';}
function renderSaved(busy){
 const select=$('ssh-saved-select');
 const list=remoteState.saved_servers||[];
 const signature=list.map(item=>item.id+'|'+serverLabel(item)).join('\n');
 if(select.dataset.signature!==signature){
  select.replaceChildren();
  if(!list.length){
   const empty=document.createElement('option');
   empty.value='';
   empty.textContent='还没有保存的服务器';
   select.append(empty);
  }
  for(const item of list){
   const option=document.createElement('option');
   option.value=item.id;
   option.textContent=serverLabel(item);
   select.append(option);
  }
  select.dataset.signature=signature;
 }
 const chosen=list.find(item=>item.active)?.id||list.find(item=>item.host===(remoteState.connection||{}).host)?.id||'';
 if(document.activeElement!==select)select.value=chosen;
 select.disabled=busy||!list.length;
 $('ssh-forget').disabled=busy||!select.value;
}
function renderRemote(){
 if(!remoteState)return;
 const busy=remoteUiBusy||remoteState.busy,connected=remoteState.status==='connected';
 const current=remoteState.connection||{},ssh=remoteState.target==='ssh',wsl=!!current.wsl_distro,ready=ssh&&!!current.host;
 const passwordMode=(current.auth||'password')==='password';
 const showServer=ready&&!wsl;
 if(!connected&&!remoteState.busy&&!remoteUiBusy&&remoteState.status!=='connecting'&&remoteState.status!=='deploying')clearLinked();
 const linked=linkedByUser&&connected&&!unlinkPending;
 for(const input of document.querySelectorAll('input[name="training-target"]')){input.checked=input.value===remoteState.target;input.disabled=busy;}
 $('ssh-add').disabled=busy||$('ssh-dialog').open;
 $('ssh-current').hidden=!showServer;
 $('ssh-current-kicker').textContent='当前服务器';
 $('ssh-current-name').textContent=serverLabel(current);
 $('ssh-live').hidden=!(showServer&&connected);
 $('ssh-current-meta').textContent=showServer?`${current.workspace||''} · ${passwordMode?'密码登录':'密钥登录'}`:'';
 $('ssh-current-name').classList.toggle('remote-failed',showServer&&remoteState.status==='failed');
 renderSaved(busy);
 $('ssh-section').hidden=!showServer&&!wsl;
 if(remoteState.password_available)passwordPrompt=false;
 const askPassword=passwordPrompt&&showServer&&passwordMode&&!remoteState.password_available;
 $('ssh-password-row').hidden=!askPassword;
 $('ssh-password-note').hidden=!askPassword;
 $('ssh-password').disabled=busy;
 $('ssh-host-verification').hidden=!remoteState.pending_host;
 $('ssh-host-fingerprint').textContent=remoteState.pending_host?remoteState.pending_host.hostname+' · '+remoteState.pending_host.key_type+'\n'+remoteState.pending_host.fingerprint:'';
 $('ssh-trust-host').disabled=busy;
 $('ssh-status').hidden=!((linked&&connected)||remoteState.status==='failed');
 $('ssh-status').textContent=remoteState.message||'';
 $('ssh-status').classList.toggle('remote-failed',remoteState.status==='failed');
 $('ssh-gpu').hidden=!showServer||!remoteState.info?.gpu;
 $('ssh-gpu').textContent=remoteState.info?.gpu||'';
 $('ssh-connect').disabled=busy||!showServer;
 $('ssh-linked-actions').hidden=!linked;
 $('ssh-deploy').disabled=busy||!linked;
 $('ssh-disconnect').disabled=busy||!linked;
 $('ssh-model-pick').disabled=busy||!linked||modelUploading;
 $('model-transfer-status').hidden=!linked;
 $('wsl-test').disabled=busy||!remoteState.wsl_test_supported;
 $('wsl-test-distro').disabled=busy||!remoteState.wsl_test_supported;
 $('ssh-restore').hidden=!remoteState.has_server_backup;
 $('ssh-restore').disabled=busy;
 $('wsl-test').textContent=remoteState.busy&&remoteState.wsl_test_supported?'正在测试…':'本机 WSL 测试';
 $('wsl-test-note').textContent=remoteState.wsl_test_supported?'用 SSH 测试服务器通道；原本机 / WSL 训练继续使用原通道。':'WSL测试入口需在Windows中启动中控；当前可使用Linux本机或SSH服务器。';
 $('server-model-upload').disabled=busy||!linked||modelUploading;
 $('ssh-deploy').textContent=remoteState.status==='deploying'?'正在部署…':'部署并准备环境';
 $('ssh-connect').textContent=remoteState.status==='connecting'?'正在连接…':'连接 / 重连';
 const key=current.identity?' -i "'+String(current.identity).replace(/"/g,'')+'"':'';
 $('ssh-login-command').textContent=`ssh -p ${current.port||22}${key} ${current.user||'ubuntu'}@${current.host||'服务器IP'}`;
}
function dialogConnection(){
 const auth=$('dialog-auth').value;
 return {host:$('dialog-host').value.trim(),user:$('dialog-user').value.trim(),port:Number($('dialog-port').value),auth,identity:auth==='key'?$('dialog-identity').value.trim():'',workspace:$('dialog-workspace').value.trim()};
}
function syncDialogAuth(){
 const key=$('dialog-auth').value==='key';
 $('dialog-password-row').hidden=key;
 $('dialog-identity-row').hidden=!key;
}
async function pollRemote(){
 try{const response=await fetch('/api/remote/state',{signal:AbortSignal.timeout(4000)});if(response.ok){remoteState=await response.json();if(remoteWasBusy&&!remoteState.busy&&remoteState.status==='connected')markLinked();renderRemote();if(remoteWasBusy&&!remoteState.busy&&remoteState.status==='connected'){remoteWasBusy=false;location.reload();return;}remoteWasBusy=remoteWasBusy||remoteState.busy;}}
 catch{ /* Main state polling owns the dashboard connectivity banner. */ }
 setTimeout(pollRemote,2000);
}
async function remoteAction(action,save=true){
 if(remoteUiBusy)return;
 remoteUiBusy=true;renderRemote();
 try{
  if(save){remoteState=await post('/api/remote/configure',{connection:activeConnection(),password:$('ssh-password').value});$('ssh-password').value='';}
  if(action)remoteState=await post('/api/remote/'+action,{});
  if(action==='deploy'||action==='connect'){remoteWasBusy=true;markLinked();}
  if(action==='disconnect')clearLinked();
  tell(remoteState.message||'服务器连接已保存。');
 }catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
}
for(const input of document.querySelectorAll('input[name="training-target"]'))input.onchange=async()=>{
 const target=input.value;
 if(target===remoteState?.target)return;
 if(typeof launchFlow!=='undefined'&&launchFlow.busy){tell('请等待当前训练启动流程完成后再切换位置。');renderRemote();return;}
 remoteUiBusy=true;renderRemote();
 try{await post('/api/remote/select',{target});location.reload();}catch(error){tell(error.message);remoteUiBusy=false;renderRemote();}
};
$('ssh-saved-select').onchange=()=>{
 const id=$('ssh-saved-select').value;
 if(!id)return;
 const active=(remoteState.saved_servers||[]).find(item=>item.active);
 if(active?.id===id&&remoteState.target==='ssh')return;
 useServer(id);
};
$('ssh-forget').onclick=()=>{
 const id=$('ssh-saved-select').value;
 const item=(remoteState.saved_servers||[]).find(server=>server.id===id);
 if(item)forgetServer(item.id,serverLabel(item));
};
$('ssh-add').onclick=()=>{
 $('dialog-host').value='';
 $('dialog-user').value='ubuntu';
 $('dialog-port').value='22';
 $('dialog-auth').value='password';
 $('dialog-password').value='';
 $('dialog-identity').value='';
 $('dialog-workspace').value=remoteState?.connection?.workspace||'~/microduck-training-ssh';
 syncDialogAuth();
 $('ssh-dialog').showModal();
 renderRemote();
};
$('dialog-auth').onchange=syncDialogAuth;
$('ssh-dialog-cancel').onclick=()=>$('ssh-dialog').close();
$('ssh-dialog').addEventListener('close',renderRemote);
$('ssh-dialog-form').onsubmit=async event=>{
 event.preventDefault();
 if(remoteUiBusy)return;
 remoteUiBusy=true;renderRemote();
 try{
  remoteState=await post('/api/remote/configure',{connection:dialogConnection(),password:$('dialog-password').value});
  $('dialog-password').value='';$('ssh-password').value='';passwordPrompt=false;
  if(remoteState.target!=='ssh')remoteState=await post('/api/remote/select',{target:'ssh'});
  $('ssh-dialog').close();
  tell('服务器已保存。需要时再点连接。');
 }catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
};
async function useServer(id){
 if(remoteUiBusy)return;
 const previous=remoteState?.target;
 passwordPrompt=false;$('ssh-password').value='';
 clearLinked();
 remoteUiBusy=true;renderRemote();
 try{
  remoteState=await post('/api/remote/use',{id});
  if(previous!=='ssh'){location.reload();return;}
  tell('已切换服务器。点连接后再使用这台机器。');
 }catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
}
async function forgetServer(id,label){
 if(remoteUiBusy)return;
 if(!window.confirm(`删除已保存的服务器 ${label}？\n只删除本机这份记录，不会改服务器上的训练。`))return;
 remoteUiBusy=true;renderRemote();
 try{remoteState=await post('/api/remote/forget',{id});tell('已从列表删除。');}
 catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
}
function passwordReady(){
 const current=remoteState?.connection||{};
 const passwordMode=(current.auth||'password')!=='key';
 if(remoteState?.target!=='ssh'||!current.host||current.wsl_distro||!passwordMode||remoteState.password_available||$('ssh-password').value)return true;
 passwordPrompt=true;renderRemote();$('ssh-password').focus();
 return false;
}
$('ssh-deploy').onclick=()=>{if(passwordReady())remoteAction('deploy');};
$('ssh-model-pick').onclick=()=>{if(!$('server-model-upload').disabled)$('server-model-upload').click();};
$('ssh-connect').onclick=()=>{if(passwordReady())remoteAction('connect');};
$('ssh-trust-host').onclick=async()=>{
 if(remoteUiBusy||!remoteState.pending_host)return;
 remoteUiBusy=true;renderRemote();
 try{remoteState=await post('/api/remote/trust-host',{fingerprint:remoteState.pending_host.fingerprint});remoteWasBusy=true;tell(remoteState.message);}
 catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
};
$('ssh-disconnect').onclick=async()=>{
 unlinkPending=true;clearLinked();renderRemote();
 try{await remoteAction('disconnect',false);await loadState();}
 finally{unlinkPending=false;renderRemote();}
};
$('wsl-test').onclick=async()=>{
 if(remoteUiBusy)return;
 if(typeof launchFlow!=='undefined'&&launchFlow.busy){tell('请等待当前训练启动流程完成后再测试。');return;}
 remoteUiBusy=true;renderRemote();
 try{remoteState=await post('/api/remote/wsl-test',{distro:$('wsl-test-distro').value.trim()});remoteWasBusy=true;tell(remoteState.message);}
 catch(error){tell(error.message);}
 finally{remoteUiBusy=false;renderRemote();}
};
$('ssh-restore').onclick=async()=>{await remoteAction('server-restore',false);renderRemote();await loadState();};
$('server-model-upload').onchange=async event=>{
 const file=event.target.files[0];if(!file)return;
 try{
  if(file.size>30*1024*1024)throw Error('请上传30MB以内的完整老师/续训模型ZIP。');
  modelUploading=true;$('ssh-model-pick').disabled=true;$('model-transfer-status').textContent='正在上传模型，训练来源和动作配置会保留…';
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const result=await post('/api/models/import',{name:file.name,data:btoa(binary)},{signal:AbortSignal.timeout(180000)});
  selected=result.job_id;await loadState();
  $('model-transfer-status').textContent=result.resume_supported===false?'老师已上传；旧包缺少原训练并行数，可作老师，续训需原训练快照。':'模型已上传，可在老师选择或续训来源中选择。';tell('模型已上传，原倍率、滤波和P已保留。');
 }catch(error){$('model-transfer-status').textContent=error.message;tell(error.message);}
 finally{modelUploading=false;event.target.value='';renderRemote();}
};
pollRemote();
