import {actionSlots} from './service-builds.js';

const MODE_KEY = 'bobo-ui-mode';
const finite = value => typeof value === 'number' && Number.isFinite(value);
const DEFAULT_PRESETS = [
  {id: 'preset:sway', label: '摇头晃脑'},
  {id: 'preset:nod', label: '点头'},
  {id: 'preset:shake_hard', label: '使劲摇头'},
  {id: 'preset:laugh', label: '哈哈大笑'},
];
const SLOT_LABEL = Object.fromEntries(actionSlots.map(row => [row.slot, row.label.split(' / ')[0]]));
SLOT_LABEL.sit_toggle = '坐下／站起';
SLOT_LABEL.ground_pick = '地面捡取';
SLOT_LABEL.stand_test = '倒地起身测试';

let keywordDraft = null;
let keywordSynced = '';
let keywordActionOptions = [...DEFAULT_PRESETS];
let keywordBusy = false;
let exprAmpDirty = false;
let exprAmpBusy = false;
let exprAmpSynced = null;

function ampToPercent(amp) {
  const value = finite(amp) ? amp : 1;
  return Math.round(Math.min(200, Math.max(0, value * 100)));
}

function percentToAmp(percent) {
  return Math.round(Math.min(200, Math.max(0, Number(percent) || 0)) * 5) / 500;
}

function paintExprAmpLabel(percent) {
  const out = document.getElementById('bobo-expr-amp-value');
  if (out) out.textContent = `${percent}%`;
}
const SERVOS = [
  {n: 1, id: 20, name: '左髋旋转'}, {n: 2, id: 21, name: '左髋侧摆'}, {n: 3, id: 22, name: '左髋俯仰'},
  {n: 4, id: 23, name: '左膝'}, {n: 5, id: 24, name: '左踝'},
  {n: 6, id: 30, name: '颈部俯仰'}, {n: 7, id: 31, name: '头部俯仰'}, {n: 8, id: 32, name: '头部转向'},
  {n: 9, id: 33, name: '头部侧倾'}, {n: 10, id: 34, name: '嘴巴'},
  {n: 11, id: 10, name: '右髋旋转'}, {n: 12, id: 11, name: '右髋侧摆'}, {n: 13, id: 12, name: '右髋俯仰'},
  {n: 14, id: 13, name: '右膝'}, {n: 15, id: 14, name: '右踝'},
];

const hints = {
  debug: '调试是校准机器，需要将每个关节都转到标准位置校准',
  run: '运行是运动模式，用来操纵鸭子。点调试会切回标定模式。',
};

let robotTab = 'debug';

function readMode() {
  try {
    return localStorage.getItem(MODE_KEY) === 'expert' ? 'expert' : 'simple';
  } catch {
    return 'simple';
  }
}

function store(mode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch { /* private mode still switches for this visit */ }
}

function requestServiceMode(target) {
  const button = document.getElementById(target === 'motion' ? 'service-mode-motion' : 'service-mode-calibrate');
  if (!button) return;
  const disabled = button.disabled;
  button.disabled = false;
  button.click();
  button.disabled = disabled;
}

function showBarTip(button) {
  let tip = document.getElementById('servo-bay-tip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'servo-bay-tip';
    tip.setAttribute('role', 'tooltip');
    document.body.append(tip);
  }
  tip.textContent = button.dataset.tip || '';
  tip.hidden = false;
  const rect = button.getBoundingClientRect();
  const width = tip.offsetWidth;
  tip.style.left = `${Math.min(window.innerWidth - width - 8, Math.max(8, rect.left + rect.width / 2 - width / 2))}px`;
  tip.style.top = `${Math.max(8, rect.top - tip.offsetHeight - 8)}px`;
}

function hideBarTip() {
  const tip = document.getElementById('servo-bay-tip');
  if (tip) tip.hidden = true;
}

function bar(item) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'servo-bar idle';
  button.dataset.id = String(item.id);
  button.dataset.n = String(item.n);
  button.innerHTML = `<i aria-hidden="true"></i><span>${item.n}</span>`;
  button.onclick = () => {
    const select = document.getElementById('service-joint-select');
    if (select) {
      select.value = String(item.id);
      select.dispatchEvent(new Event('change'));
    }
    document.querySelectorAll('.servo-bar').forEach(node => node.classList.toggle('picked', node === button));
  };
  button.addEventListener('pointerenter', () => showBarTip(button));
  button.addEventListener('pointerleave', hideBarTip);
  button.addEventListener('focus', () => showBarTip(button));
  button.addEventListener('blur', hideBarTip);
  return button;
}

function ensureBay() {
  const host = document.getElementById('service-inspection');
  if (!host || document.getElementById('servo-bay')) return;
  const bay = document.createElement('div');
  bay.id = 'servo-bay';
  bay.className = 'servo-bay';
  bay.innerHTML = `<div class="bay-summary"><strong id="servo-bay-count">等待 15 颗舵机</strong><div class="bay-legend"><span class="good">在线</span><span class="warn">留意</span><span class="bad">异常</span><span class="idle">等待</span></div></div>
    <div class="bay-bars" id="servo-bay-bars" aria-label="15 颗舵机健康柱状图"></div>
    <p class="bay-note">柱子越高越健康。绿是在线，黄是留意，红是异常，灰是等待。鼠标放上去看编号和读数，点一下会切到关节工作台。</p>`;
  host.querySelector('.panel-head').after(bay);
  document.getElementById('servo-bay-bars').append(...SERVOS.map(bar));
}

function toneOf(row, cell) {
  if (cell?.classList.contains('bad') || row?.status === 'error') return 'bad';
  if (cell?.classList.contains('warn') || row?.status === 'stale') return 'warn';
  if (cell?.classList.contains('good') || row?.status === 'live') return row?.calibrated === false ? 'warn' : 'good';
  return 'idle';
}

const toneText = {good: '在线', warn: '留意', bad: '异常', idle: '等待'};

/** py-xiaozhi UIPlugin.STATE_TEXT_MAP */
const VOICE_STATUS = {
  idle: {text: '待命', badge: '待命', hint: 'R3 / 菜单键接通', link: '未连接', tone: ''},
  connecting: {text: '连接中...', badge: '连接中', hint: '正在接通语音服务器', link: '连接中', tone: 'warn'},
  listening: {text: '聆听中...', badge: '聆听中', hint: '再按 R3 / 菜单键挂断', link: '已连接', tone: 'live'},
  speaking: {text: '说话中...', badge: '说话中', hint: '再按可打断并挂断', link: '已连接', tone: 'live'},
};

function actionLabel(id) {
  const preset = DEFAULT_PRESETS.find(row => row.id === id);
  if (preset) return preset.label;
  return SLOT_LABEL[id] || id;
}

function buildActionOptions(sample) {
  const presets = Array.isArray(sample?.system?.bobo?.presets) && sample.system.bobo.presets.length
    ? sample.system.bobo.presets.map(row => ({
      id: String(row.id || ''),
      label: String(row.label || actionLabel(row.id)),
    })).filter(row => row.id)
    : DEFAULT_PRESETS;
  const skills = [];
  const seen = new Set(presets.map(row => row.id));
  const push = id => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    skills.push({id, label: `模型 · ${actionLabel(id)}`});
  };
  const caps = sample?.capabilities;
  if (caps?.ground_pick) push('ground_pick');
  if (caps?.sitstand || caps?.sit_toggle) push('sit_toggle');
  if (Array.isArray(caps?.skills)) caps.skills.forEach(push);
  if (Array.isArray(caps?.built_in)) caps.built_in.forEach(push);
  // Fall back to catalog slots so the dropdown is usable before capabilities arrive.
  if (!skills.length) {
    for (const slot of ['ground_pick', 'sit_toggle', 'roulade', 'kick_left', 'kick_right']) push(slot);
  }
  return [
    ...presets.map(row => ({id: row.id, label: `预设 · ${row.label}`})),
    ...skills,
  ];
}

function readKeywordRows() {
  return [...document.querySelectorAll('#bobo-keyword-rows .bobo-keyword-row')].map(row => ({
    match: row.querySelector('.bobo-keyword-match')?.value?.trim() || '',
    action: row.querySelector('.bobo-keyword-action')?.value || '',
  }));
}

function renderKeywordRows(rows) {
  const host = document.getElementById('bobo-keyword-rows');
  if (!host) return;
  host.replaceChildren();
  const list = rows?.length ? rows : [{match: '', action: keywordActionOptions[0]?.id || 'preset:nod'}];
  for (const row of list) {
    const el = document.createElement('div');
    el.className = 'bobo-keyword-row';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'bobo-keyword-match';
    input.placeholder = '例如：点头';
    input.maxLength = 64;
    input.value = row.match || '';
    input.addEventListener('input', () => { keywordDraft = readKeywordRows(); });
    const select = document.createElement('select');
    select.className = 'bobo-keyword-action';
    const selected = row.action || keywordActionOptions[0]?.id || '';
    const options = [...keywordActionOptions];
    if (selected && !options.some(opt => opt.id === selected)) {
      options.push({id: selected, label: `模型 · ${actionLabel(selected)}`});
    }
    for (const opt of options) {
      const option = document.createElement('option');
      option.value = opt.id;
      option.textContent = opt.label;
      if (opt.id === selected) option.selected = true;
      select.append(option);
    }
    select.addEventListener('change', () => { keywordDraft = readKeywordRows(); });
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'bobo-keyword-del';
    del.textContent = '删';
    del.addEventListener('click', () => {
      el.remove();
      if (!host.childElementCount) renderKeywordRows([]);
      keywordDraft = readKeywordRows();
    });
    el.append(input, select, del);
    host.append(el);
  }
  keywordDraft = readKeywordRows();
}

async function saveExpressionAmp() {
  const status = document.getElementById('bobo-expr-amp-status');
  const button = document.getElementById('bobo-expr-amp-save');
  const slider = document.getElementById('bobo-expr-amp');
  if (exprAmpBusy || !slider) return;
  const percent = Number(slider.value);
  const expression_amp = percentToAmp(percent);
  exprAmpBusy = true;
  if (button) button.disabled = true;
  if (status) status.textContent = '正在保存头部幅度到鸭子…';
  try {
    const cfg = window.__boboConfig || {};
    const password = document.getElementById('service-sudo-password')?.value || '';
    const command = {action: 'set-bobo-expression', expression_amp, supported: true};
    if (password) command.sudo_password = password;
    const body = JSON.stringify({client: 'bobo-expression', seq: Date.now(), command});
    const response = await fetch('/api/service', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Control-Token': cfg.control_token || '',
      },
      body,
      signal: AbortSignal.timeout(120000),
    });
    const data = await response.json();
    if (!response.ok || !data.accepted) throw new Error(data.error || '保存失败');
    exprAmpSynced = expression_amp;
    exprAmpDirty = false;
    paintExprAmpLabel(ampToPercent(expression_amp));
    if (status) {
      status.textContent = `已保存 ${ampToPercent(expression_amp)}%（amp=${expression_amp.toFixed(2)}）；约 2 秒后生效，单轴不超过 ±0.18 rad。`;
    }
  } catch (error) {
    if (status) status.textContent = error.message || String(error);
  } finally {
    exprAmpBusy = false;
    if (button) button.disabled = false;
  }
}

function paintExpressionAmp(sample) {
  const slider = document.getElementById('bobo-expr-amp');
  const status = document.getElementById('bobo-expr-amp-status');
  if (!slider) return;
  const bobo = sample?.system?.bobo;
  const remote = finite(bobo?.expression_amp) ? bobo.expression_amp : null;
  const limit = finite(bobo?.expression_offset_limit_rad) ? bobo.expression_offset_limit_rad : 0.18;
  const maxAmp = finite(bobo?.expression_amp_max) ? bobo.expression_amp_max : 2;
  if (remote != null && !exprAmpDirty && !exprAmpBusy) {
    const percent = ampToPercent(remote);
    if (Number(slider.value) !== percent) slider.value = String(percent);
    paintExprAmpLabel(percent);
    exprAmpSynced = remote;
    if (status) {
      status.textContent = `当前 ${percent}%（设计 100%，上限 ${ampToPercent(maxAmp)}%）；舵机安全限位 ±${limit.toFixed(2)} rad。`;
    }
  } else if (remote == null && status && !exprAmpDirty) {
    status.textContent = '等待系统遥测中的表情幅度（需新版 robotd）。';
  }
}

async function saveKeywords() {
  const status = document.getElementById('bobo-keyword-status');
  const button = document.getElementById('bobo-keyword-save');
  if (keywordBusy) return;
  const rows = readKeywordRows();
  if (rows.some(row => (row.match && !row.action) || (!row.match && row.action))) {
    if (status) status.textContent = '请把每一行的关键词和动作都填完整，或删掉空行。';
    return;
  }
  const keywords = rows.filter(row => row.match && row.action);
  keywordBusy = true;
  if (button) button.disabled = true;
  if (status) status.textContent = '正在保存关键词到鸭子…';
  try {
    const cfg = window.__boboConfig || {};
    const password = document.getElementById('service-sudo-password')?.value || '';
    const command = {action: 'set-bobo-keywords', keywords, supported: true};
    if (password) command.sudo_password = password;
    const body = JSON.stringify({client: 'bobo-keywords', seq: Date.now(), command});
    const response = await fetch('/api/service', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Control-Token': cfg.control_token || '',
      },
      body,
      signal: AbortSignal.timeout(120000),
    });
    const data = await response.json();
    if (!response.ok || !data.accepted) throw new Error(data.error || '保存失败');
    keywordSynced = JSON.stringify(keywords);
    keywordDraft = keywords;
    if (status) status.textContent = `已保存 ${keywords.length} 条；约 2 秒后生效，无需重启。`;
  } catch (error) {
    if (status) status.textContent = error.message || String(error);
  } finally {
    keywordBusy = false;
    if (button) button.disabled = false;
  }
}

function paintKeywords(sample) {
  const status = document.getElementById('bobo-keyword-status');
  const host = document.getElementById('bobo-keyword-rows');
  if (!host) return;
  keywordActionOptions = buildActionOptions(sample);
  const remote = Array.isArray(sample?.system?.bobo?.keywords)
    ? sample.system.bobo.keywords.map(row => ({
      match: String(row.match || '').trim(),
      action: String(row.action || '').trim(),
    })).filter(row => row.match && row.action)
    : null;
  const remoteKey = remote ? JSON.stringify(remote) : '';
  const editing = keywordDraft && JSON.stringify(keywordDraft) !== keywordSynced;
  if (remote && remoteKey !== keywordSynced && !editing && !keywordBusy) {
    keywordSynced = remoteKey;
    renderKeywordRows(remote);
    if (status) {
      status.textContent = remote.length
        ? `鸭子上有 ${remote.length} 条关键词；改完后点「保存到鸭子」。`
        : '鸭子上还没有关键词；左侧填词，右侧选动作后保存。';
    }
  } else if (!keywordDraft) {
    renderKeywordRows([]);
  } else {
    // Keep current draft; refresh option lists if selects are empty of new skills.
    const current = readKeywordRows();
    const focused = document.activeElement;
    if (!focused || !host.contains(focused)) renderKeywordRows(current);
  }
}

function paintVoice(sample) {
  const macEl = document.getElementById('bobo-wlan-mac');
  const statusEl = document.getElementById('bobo-voice-status');
  const badge = document.getElementById('bobo-voice-badge');
  const linkEl = document.getElementById('bobo-voice-link');
  const hintEl = document.getElementById('bobo-voice-hint');
  const detail = document.getElementById('bobo-voice-detail');
  if (!macEl || !statusEl) return;
  const bobo = sample?.system?.bobo;
  const mac = typeof bobo?.wlan_mac === 'string' && bobo.wlan_mac ? bobo.wlan_mac : '—';
  if (macEl.textContent !== mac) macEl.textContent = mac;
  const phase = typeof bobo?.phase === 'string' ? bobo.phase : 'idle';
  const view = VOICE_STATUS[phase] || VOICE_STATUS.idle;
  const statusText = `状态: ${view.text}`;
  if (statusEl.textContent !== statusText) statusEl.textContent = statusText;
  if (badge) {
    badge.textContent = view.badge;
    badge.className = 'badge ' + (view.tone || 'neutral');
  }
  if (linkEl) linkEl.textContent = view.link;
  if (hintEl) hintEl.textContent = view.hint;
  const emotionEl = document.getElementById('bobo-voice-emotion');
  const emotion = typeof bobo?.emotion === 'string' && bobo.emotion ? bobo.emotion : 'neutral';
  if (emotionEl && emotionEl.textContent !== emotion) emotionEl.textContent = emotion;
  if (detail) {
    if (bobo?.enabled === false) {
      detail.textContent = bobo.refusal ? `语音未启用：${bobo.refusal}` : '语音未启用：检查 [bobo] / [audio]';
    } else if (!bobo) {
      detail.textContent = '等待 robotd 系统遥测中的 bobo 字段（约 2 秒刷新）。';
    } else {
      detail.textContent = phase === 'idle'
        ? '已配置 BoBo；按 R3 或菜单键接通，状态与小智客户端一致。'
        : `通话进行中 · phase=${phase} · 表情 ${emotion}`;
    }
  }
  // Keep web pad R3/Guide green latch aligned with a live call when robotd reports it.
  if (bobo) {
    window.__boboSyncVoiceLatch?.(phase !== 'idle' || bobo.call_active === true);
  }
  paintKeywords(sample);
  paintExpressionAmp(sample);
}

function paint(sample) {
  paintVoice(sample);
  const bay = document.getElementById('servo-bay');
  if (!bay || !sample) return;
  const counts = {good: 0, warn: 0, bad: 0, idle: 0};
  const selected = document.getElementById('service-joint-select')?.value;
  for (const item of SERVOS) {
    const button = bay.querySelector(`.servo-bar[data-id="${item.id}"]`);
    if (!button) continue;
    const row = sample.servos?.find(entry => entry.id === item.id);
    const cell = document.querySelector(`#inspection-devices .inspection-device[data-id="${item.id}"]`);
    const tone = toneOf(row, cell);
    counts[tone] += 1;
    button.classList.toggle('good', tone === 'good');
    button.classList.toggle('warn', tone === 'warn');
    button.classList.toggle('bad', tone === 'bad');
    button.classList.toggle('idle', tone === 'idle');
    button.classList.toggle('picked', selected === String(item.id));
    const bits = [toneText[tone]];
    if (row?.calibrated === false) bits.push('未标定');
    if (finite(row?.voltage_v)) bits.push(`${row.voltage_v.toFixed(1)}V`);
    if (finite(row?.temperature_c)) bits.push(`${Math.round(row.temperature_c)}°C`);
    const line = `${item.n}号 ${item.name}\nID ${item.id} · ${bits.join(' · ')}`;
    if (button.dataset.tip !== line) button.dataset.tip = line;
    button.title = line.replace('\n', ' · ');
    button.setAttribute('aria-label', line.replace('\n', '，'));
  }
  const count = document.getElementById('servo-bay-count');
  if (count) count.textContent = `在线 ${counts.good} · 留意 ${counts.warn} · 异常 ${counts.bad} · 等待 ${counts.idle}`;
  const stop = document.getElementById('service-quick-stop');
  const proxy = document.getElementById('bobo-stop');
  if (stop && proxy) proxy.disabled = stop.disabled;
}

function apply(mode) {
  const simple = mode !== 'expert';
  document.body.classList.add('bobo');
  document.body.classList.toggle('ui-simple', simple);
  document.body.classList.toggle('ui-expert', !simple);
  document.body.classList.toggle('simple-debug', simple && robotTab !== 'run');
  document.body.classList.toggle('simple-run', simple && robotTab === 'run');
  const debug = document.getElementById('bobo-tab-debug');
  const run = document.getElementById('bobo-tab-run');
  if (debug) {
    debug.disabled = false;
    debug.setAttribute('aria-selected', String(robotTab !== 'run'));
  }
  if (run) {
    run.disabled = false;
    run.setAttribute('aria-selected', String(robotTab === 'run'));
  }
  const hint = document.getElementById('bobo-hint');
  if (hint) hint.textContent = hints[robotTab === 'run' ? 'run' : 'debug'];
  const expert = document.getElementById('bobo-expert');
  if (expert) {
    expert.setAttribute('aria-pressed', String(!simple));
    expert.title = simple ? '当前是简约模式，按下进入专家模式' : '当前是专家模式，再按回到简约模式';
  }
  placeImu(true);
  placeExpertChrome(!simple);
  closePadHelp();
  requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
}

let imuHome = null;
function placeExpertChrome(expert) {
  const hero = document.getElementById('service-hero');
  if (!hero) return;
  let stack = document.getElementById('bobo-expert-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'bobo-expert-stack';
    hero.after(stack);
  }
  const params = document.querySelector('.runtime-parameters');
  const paramHome = document.querySelector('#control-panel .pad-model-parameters');
  if (expert) {
    if (params) stack.append(params);
    stack.hidden = stack.childElementCount === 0;
  } else {
    if (params && paramHome && params.parentElement !== paramHome) paramHome.append(params);
    stack.hidden = true;
  }
}

function placeImu(simple) {
  const imu = document.querySelector('section.imu-panel');
  const row = document.getElementById('service-joint-row');
  if (!imu || !row) return;
  if (!imuHome) imuHome = {parent: imu.parentElement, next: imu.nextSibling};
  if (simple) {
    if (imu.parentElement !== row || row.firstElementChild !== imu) row.prepend(imu);
  } else if (imu.parentElement !== imuHome.parent) {
    const next = imuHome.next && imuHome.next.parentNode === imuHome.parent ? imuHome.next : null;
    imuHome.parent.insertBefore(imu, next);
  }
}

function closePadHelp() {
  document.querySelector('#control-panel .pad-help')?.classList.remove('is-open');
  document.getElementById('pad-help-scrim')?.remove();
}

function openPadHelp() {
  const help = document.querySelector('#control-panel .pad-help');
  if (!help) return;
  if (help.classList.contains('is-open')) {
    closePadHelp();
    return;
  }
  help.classList.add('is-open');
  const scrim = document.createElement('button');
  scrim.id = 'pad-help-scrim';
  scrim.type = 'button';
  scrim.setAttribute('aria-label', '关闭按键说明');
  scrim.addEventListener('click', closePadHelp);
  document.body.append(scrim);
}

export function syncRobotMode(mode, known) {
  const next = known && mode === 'motion' ? 'run' : 'debug';
  if (next === robotTab) return;
  robotTab = next;
  const ui = document.body.classList.contains('ui-expert') ? 'expert' : 'simple';
  apply(ui);
}

export function mountBoBoMaker() {
  ensureBay();
  let mode = readMode();
  apply(mode);
  window.__boboSyncMode = syncRobotMode;
  document.getElementById('bobo-tab-debug')?.addEventListener('click', () => requestServiceMode('commissioning'));
  document.getElementById('bobo-tab-run')?.addEventListener('click', () => requestServiceMode('motion'));
  document.getElementById('bobo-expert')?.addEventListener('click', () => {
    mode = mode === 'expert' ? 'simple' : 'expert';
    store(mode);
    apply(mode);
    window.scrollTo({top: 0, behavior: 'smooth'});
  });
  document.getElementById('bobo-stop')?.addEventListener('click', () => document.getElementById('service-quick-stop')?.click());
  document.getElementById('pad-help-open')?.addEventListener('click', openPadHelp);
  document.querySelector('#control-panel .pad-help-close')?.addEventListener('click', closePadHelp);
  document.getElementById('bobo-keyword-add')?.addEventListener('click', () => {
    const rows = readKeywordRows();
    rows.push({match: '', action: keywordActionOptions[0]?.id || 'preset:nod'});
    renderKeywordRows(rows);
  });
  document.getElementById('bobo-keyword-save')?.addEventListener('click', () => { void saveKeywords(); });
  document.getElementById('bobo-expr-amp')?.addEventListener('input', event => {
    exprAmpDirty = true;
    paintExprAmpLabel(Number(event.target.value) || 0);
    const status = document.getElementById('bobo-expr-amp-status');
    if (status) status.textContent = '已改动，点「保存幅度」写入鸭子。';
  });
  document.getElementById('bobo-expr-amp-save')?.addEventListener('click', () => { void saveExpressionAmp(); });
  renderKeywordRows([]);
  paintExprAmpLabel(100);
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape') closePadHelp();
  });
  window.__boboPaint = paint;
}
