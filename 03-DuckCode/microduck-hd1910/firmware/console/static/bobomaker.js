const MODE_KEY = 'bobo-ui-mode';
const finite = value => typeof value === 'number' && Number.isFinite(value);
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

function paint(sample) {
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
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape') closePadHelp();
  });
  window.__boboPaint = paint;
}
