/** Page connection settings share the original SSH channels and sudo credential. */
export class SSHConnection {
  constructor(cfg,beforeChange,changed){
    this.cfg=cfg;this.beforeChange=beforeChange;this.changed=changed;this.working=false;this.scanning=false;this.scanTicket=0;
    this.$=id=>document.getElementById(id);
    this.$('ssh-target').value=cfg.ssh_target||'';
    this.$('ssh-target').disabled=!cfg.connection_ui;
    this.$('ssh-form').onsubmit=e=>{e.preventDefault();this.submit('connect');};
    this.$('ssh-disconnect').onclick=()=>this.submit('disconnect');
    this.$('ssh-scan').onclick=()=>this.scan();
    this.paint();
  }
  async postScan(action){
    const response=await fetch('/api/lan-scan',{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':this.cfg.control_token},body:JSON.stringify({action})});
    const data=await response.json();
    if(!response.ok)throw Error(data.error||'局域网搜索失败');
    return data;
  }
  fillTarget(ip){
    const current=this.$('ssh-target').value.trim();
    const at=current.indexOf('@');
    const user=at>0?current.slice(0,at).trim():'radxa';
    this.$('ssh-target').value=(user||'radxa')+'@'+ip;
  }
  renderScan(data){
    const nets=(data.subnets||[]).map(net=>net.prefix+'.0/24').join('、');
    const ssh=(data.devices||[]).filter(device=>device.ssh_open).length;
    const panel=this.$('ssh-scan-panel');
    panel.hidden=false;
    this.$('ssh-scan-summary').textContent=data.error?data.error:data.scanning
      ?`正在搜索 ${nets||'本机网段'}，已查 ${data.done}/${data.total}。开着 SSH 的排在前面`
      :(data.devices||[]).length
        ?`找到 ${data.devices.length} 台，其中 ${ssh} 台开着 SSH。点一台，地址会填进 SSH 地址`
        :'没有发现设备。请确认电脑和鸭子在同一局域网，并且路由器没有打开客户端隔离';
    const list=this.$('ssh-scan-list');
    list.replaceChildren(...(data.devices||[]).map(device=>{
      const item=document.createElement('li');
      const button=document.createElement('button');
      button.type='button';
      const label=document.createElement('span');
      label.textContent=device.ip+(device.host?`  ${device.host}`:'');
      const meta=document.createElement('span');
      meta.className='scan-meta';
      meta.textContent=device.ssh_open?'SSH 22 开着':device.mac||'在线';
      if(device.ssh_open)meta.classList.add('ssh-open');
      button.append(label,meta);
      button.onclick=()=>this.fillTarget(device.ip);
      item.append(button);
      return item;
    }));
  }
  async scan(){
    if(!this.cfg.connection_ui)return;
    const ticket=++this.scanTicket;
    this.scanning=true;this.paint();
    this.$('ssh-scan-panel').hidden=false;
    this.$('ssh-scan-summary').textContent='正在搜索局域网…';
    this.$('ssh-scan-list').replaceChildren();
    try{
      await this.postScan('start');
      while(this.scanTicket===ticket){
        const data=await this.postScan('status');
        if(this.scanTicket!==ticket)return;
        this.renderScan(data);
        if(!data.scanning)break;
        await new Promise(resolve=>setTimeout(resolve,400));
      }
    }catch(e){if(this.scanTicket===ticket)this.$('ssh-scan-summary').textContent=e.message;}
    finally{if(this.scanTicket===ticket){this.scanning=false;this.paint();}}
  }
  async submit(action){
    if(this.working||!this.cfg.connection_ui)return;
    this.working=true;this.paint();this.beforeChange();
    try{
      const response=await fetch('/api/connection',{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':this.cfg.control_token},
        body:JSON.stringify({action,target:this.$('ssh-target').value,password:this.$('service-sudo-password').value})});
      const data=await response.json();if(!response.ok||!data.accepted)throw Error(data.error||'连接设置未完成');
      this.cfg.ssh_target=data.target;this.cfg.camera_host=data.camera_host;
      this.$('ssh-target').value=data.target;this.state=data;this.changed(data);
      this.$('ssh-status').textContent=action==='connect'?'正在连接，等待 Zero 实时数据…':'连接已暂停';
    }catch(e){this.$('ssh-status').textContent=e.message;}
    finally{this.working=false;this.paint();}
  }
  render(snapshot){
    if(!snapshot.connection||this.working)return;
    this.state=snapshot.connection;
    this.$('ssh-status').textContent=this.state.connected?'SSH 已连接':this.state.active?this.state.error||'正在连接，等待 Zero 实时数据…':'未连接，填写地址和密码后连接';
    this.paint();
  }
  paint(){
    this.$('ssh-connect').disabled=this.working||!this.cfg.connection_ui;
    this.$('ssh-connect').textContent=this.working?'连接中…':this.state?.active?'重连':'连接';
    this.$('ssh-disconnect').disabled=this.working||!this.state?.active;
    this.$('ssh-scan').disabled=!this.cfg.connection_ui;
    this.$('ssh-scan').textContent=this.scanning?'重新搜索':'搜索局域网';
  }
}
