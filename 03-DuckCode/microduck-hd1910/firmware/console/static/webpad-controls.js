import {showFeedback} from './feedback.js';
const initial=()=>({lx:0,ly:0,rx:0,ry:0,lt:0,rt:0,dx:0,dy:0});
const VOICE_BUTTONS=new Set(['rs','guide']);
export class PadControls {
  constructor(panel){
    this.panel=panel;this.root=panel.root.querySelector('.official-pad');this.axes=initial();this.buttons=new Set();this.inputs=new Map();
    // R3 / Guide latch: green while BoBo call is up; click again to hang up.
    this.voiceLatched=false;this.voicePulse=null;
    for(const stick of this.root.querySelectorAll('[data-stick]')){
      stick.addEventListener('pointerdown',e=>{if(e.button||panel.disabled)return;e.preventDefault();stick.setPointerCapture(e.pointerId);this.inputs.set(e.pointerId,{stick});this.drag(stick,e);});
      stick.addEventListener('pointermove',e=>{if(this.inputs.get(e.pointerId)?.stick===stick)this.drag(stick,e);});
      stick.addEventListener('lostpointercapture',e=>this.release(e.pointerId));stick.addEventListener('contextmenu',e=>e.preventDefault());
    }
    for(const button of this.root.querySelectorAll('[data-button],[data-dpad],[data-trigger]')){
      button.addEventListener('pointerdown',e=>{
        if(e.button)return;
        if(button.disabled||panel.disabled){
          if(button.dataset.button==='start')this.applyButton(button,true);
          return;
        }
        e.preventDefault();
        if(VOICE_BUTTONS.has(button.dataset.button)){
          this.toggleVoice(button);
          return;
        }
        button.setPointerCapture(e.pointerId);this.inputs.set(e.pointerId,{button});this.applyButton(button,true);
      });
      button.addEventListener('lostpointercapture',e=>this.release(e.pointerId));
      button.addEventListener('keydown',e=>{
        if(!['Space','Enter'].includes(e.code)||e.repeat||button.disabled||panel.disabled)return;
        e.preventDefault();
        if(VOICE_BUTTONS.has(button.dataset.button)){this.toggleVoice(button);return;}
        this.applyButton(button,true);
      });
      button.addEventListener('keyup',e=>{
        if(!['Space','Enter'].includes(e.code))return;
        e.preventDefault();
        if(VOICE_BUTTONS.has(button.dataset.button))return;
        this.applyButton(button,false);
      });
      button.addEventListener('blur',()=>{
        if(VOICE_BUTTONS.has(button.dataset.button))return;
        if(button.classList.contains('held'))this.applyButton(button,false);
      });
    }
    for(const trigger of this.root.querySelectorAll('[data-axis]')){
      trigger.addEventListener('input',()=>{this.axes[trigger.dataset.axis]=Number(trigger.value);panel.change();});
      for(const event of ['pointerup','pointercancel','blur'])trigger.addEventListener(event,()=>{trigger.value=0;this.axes[trigger.dataset.axis]=0;panel.change(false);});
    }
    window.addEventListener('pointerup',e=>this.release(e.pointerId));window.addEventListener('pointercancel',e=>this.release(e.pointerId));
    this.root.querySelector('[data-pad-center]').onclick=()=>{this.reset();panel.change(false);};
  }
  /** Click toggles call latch; pulse rs/guide once so remote_input sees a down edge. */
  toggleVoice(button){
    if(button.disabled&&!this.voiceLatched)return;
    this.voiceLatched=!this.voiceLatched;
    this.paintVoice();
    const name=button.dataset.button;
    // Force an edge even if the pad was mid-suspend: clear then set.
    this.buttons.delete('rs');
    this.buttons.delete('guide');
    this.buttons.add(name);
    this.panel.change(true);
    if(this.voicePulse)clearTimeout(this.voicePulse);
    this.voicePulse=setTimeout(()=>{
      this.buttons.delete('rs');
      this.buttons.delete('guide');
      this.voicePulse=null;
    },120);
    const tip=this.voiceLatched?'语音对话已接通（绿灯保持；再点挂断）':'语音对话已挂断（鸭子自有语音已恢复）';
    showFeedback(this.panel.feedback,tip,'running');
  }
  paintVoice(){
    for(const button of this.root.querySelectorAll('[data-button="rs"],[data-button="guide"]')){
      button.classList.toggle('held',this.voiceLatched);
      button.classList.toggle('voice-active',this.voiceLatched);
      button.setAttribute('aria-pressed',String(this.voiceLatched));
    }
  }
  applyButton(button,pressed){
    if(button.dataset.button==='start'&&pressed){
      const blocked=button.disabled||button.dataset.unavailable==='true'||this.panel.disabled;
      const status=this.panel.root.querySelector('#control-status')?.textContent||'';
      const reason=this.panel.root.querySelector('#control-reason')?.textContent||'';
      showFeedback(this.panel.feedback,blocked?`Start 未发送：网页手柄未就绪 · ${status} · ${reason}`:'Start 已按下，正在发往机器人',blocked?'warning':'running');
    }
    if(pressed&&(button.disabled||button.dataset.unavailable==='true'||this.panel.disabled))return;
    if(button.dataset.trigger){this.axes[button.dataset.trigger]=pressed?1:0;}
    else if(button.dataset.button){if(pressed)this.buttons.add(button.dataset.button);else this.buttons.delete(button.dataset.button);}
    else {const [axis,value]=button.dataset.dpad.split(':');this.axes[axis]=pressed?Number(value):0;}
    button.classList.toggle('held',pressed);button.setAttribute('aria-pressed',String(pressed));this.panel.change(pressed);
  }
  drag(stick,e){
    const r=stick.getBoundingClientRect(),x=Math.max(-1,Math.min(1,(e.clientX-r.left-r.width/2)/(r.width/2))),y=Math.max(-1,Math.min(1,(e.clientY-r.top-r.height/2)/(r.height/2)));
    const prefix=stick.dataset.stick;this.axes[prefix+'x']=x;this.axes[prefix+'y']=y;
    stick.querySelector('i').style.transform=`translate(${x*35}px,${y*35}px)`;this.panel.change();
  }
  release(id){
    const input=this.inputs.get(id);if(!input)return;this.inputs.delete(id);
    if(input.button){
      if(VOICE_BUTTONS.has(input.button.dataset.button))return;
      this.applyButton(input.button,false);
    }
    if(input.stick){const p=input.stick.dataset.stick;this.axes[p+'x']=this.axes[p+'y']=0;input.stick.querySelector('i').style.transform='translate(0,0)';this.panel.change(false);}
  }
  active(){return this.buttons.size>0||Object.values(this.axes).some(v=>v!==0);}
  frame(){return {axes:{...this.axes},buttons:[...this.buttons]};}
  reset(){
    this.inputs.clear();this.axes=initial();this.buttons.clear();
    // Do NOT clear voiceLatched: pad suspend/blur must not drop the green call state.
    if(this.voicePulse){clearTimeout(this.voicePulse);this.voicePulse=null;}
    for(const dot of this.root.querySelectorAll('[data-stick] i'))dot.style.transform='translate(0,0)';
    for(const b of this.root.querySelectorAll('.held')){
      if(VOICE_BUTTONS.has(b.dataset.button))continue;
      b.classList.remove('held');b.setAttribute('aria-pressed','false');
    }
    for(const input of this.root.querySelectorAll('[data-axis]'))input.value=0;
    this.paintVoice();
  }
  /** Call ended on the robot (hang up / idle timeout) — drop the green latch. */
  clearVoiceLatch(){
    this.voiceLatched=false;
    if(this.voicePulse){clearTimeout(this.voicePulse);this.voicePulse=null;}
    this.buttons.delete('rs');
    this.buttons.delete('guide');
    this.paintVoice();
  }
  /** Align green latch with robotd `system.bobo` without sending another edge. */
  syncVoiceLatch(active){
    const next=!!active;
    if(this.voiceLatched===next)return;
    this.voiceLatched=next;
    if(!next){this.buttons.delete('rs');this.buttons.delete('guide');}
    this.paintVoice();
  }
  paint(){
    for(const button of this.root.querySelectorAll('button')){
      if(button.dataset.padHelp)continue;
      // Keep R3/Guide clickable while latched even if other pad inputs are disabled.
      if(VOICE_BUTTONS.has(button.dataset.button)&&this.voiceLatched){
        button.disabled=false;
        continue;
      }
      button.disabled=this.panel.disabled||button.dataset.unavailable==='true';
    }
    for(const input of this.root.querySelectorAll('input'))input.disabled=this.panel.disabled;
    for(const stick of this.root.querySelectorAll('[data-stick]'))stick.setAttribute('aria-disabled',String(this.panel.disabled));
    this.paintVoice();
  }
}
