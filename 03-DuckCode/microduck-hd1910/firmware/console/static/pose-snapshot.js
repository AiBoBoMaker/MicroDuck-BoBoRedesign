/** One-click readout of every servo angle for pose capture / training targets. */

const finite = v => typeof v === 'number' && Number.isFinite(v);
const fmt = (n, d = 2) => (finite(n) ? n.toFixed(d) : '—');
const degToRad = d => (finite(d) ? d * Math.PI / 180 : null);

function angleDeg(row, snapshot) {
  const commissioning = snapshot?.mode === 'service' && snapshot?.bus?.mode === 'commissioning';
  if (commissioning) return finite(row.saved_angle_deg) ? row.saved_angle_deg : null;
  return finite(row.angle_deg) ? row.angle_deg : null;
}

function rowsFrom(snapshot, cfg) {
  const ids = cfg?.ids || [];
  const names = cfg?.names || [];
  const labels = cfg?.labels || [];
  const byId = new Map((snapshot?.servos || []).map(row => [row.id, row]));
  return ids.map((id, index) => {
    const row = byId.get(id) || {};
    const deg = angleDeg(row, snapshot);
    return {
      id,
      label: row.label || labels[index] || `舵机 ${id}`,
      name: row.name || names[index] || `joint_${id}`,
      status: row.status || 'waiting',
      deg,
      rad: degToRad(deg),
      group: index < 5 ? 'left' : index < 10 ? 'head' : 'right',
    };
  });
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  document.body.append(area);
  area.select();
  document.execCommand('copy');
  area.remove();
}

function textTable(rows) {
  const lines = [
    'ID\t中文名\t关节名\t角度°\t弧度 rad\t状态',
    ...rows.map(r => `${r.id}\t${r.label}\t${r.name}\t${fmt(r.deg, 2)}\t${fmt(r.rad, 4)}\t${r.status}`),
  ];
  return lines.join('\n');
}

function dictText(rows, {legsOnly = false, unit = 'rad'} = {}) {
  const pick = legsOnly ? rows.filter(r => r.group === 'left' || r.group === 'right') : rows;
  const body = pick.map(r => {
    const value = unit === 'deg' ? r.deg : r.rad;
    const shown = finite(value) ? (unit === 'deg' ? value.toFixed(2) : value.toFixed(4)) : 'null';
    return `  '${r.name}': ${shown},  # ID ${r.id} ${r.label}`;
  }).join('\n');
  return `{\n${body}\n}`;
}

export class PoseSnapshotPanel {
  constructor({getSnapshot, getConfig, notify}) {
    this.getSnapshot = getSnapshot;
    this.getConfig = getConfig;
    this.notify = notify || (() => {});
    this.frozen = null;
    this.live = false;
    this.$ = id => document.getElementById(id);
    this.bind();
  }

  bind() {
    this.$('pose-snapshot-read')?.addEventListener('click', () => this.capture(true));
    this.$('pose-snapshot-live')?.addEventListener('change', e => {
      this.live = !!e.target.checked;
      if (this.live) this.capture(false);
      else this.render();
    });
    this.$('pose-snapshot-copy-text')?.addEventListener('click', () => this.copy('text'));
    this.$('pose-snapshot-copy-rad')?.addEventListener('click', () => this.copy('rad'));
    this.$('pose-snapshot-copy-deg')?.addEventListener('click', () => this.copy('deg'));
    this.$('pose-snapshot-copy-legs')?.addEventListener('click', () => this.copy('legs'));
  }

  currentRows() {
    if (this.live || !this.frozen) return rowsFrom(this.getSnapshot(), this.getConfig());
    return this.frozen;
  }

  capture(notify) {
    const rows = rowsFrom(this.getSnapshot(), this.getConfig());
    this.frozen = rows;
    const liveCount = rows.filter(r => r.status === 'live' && finite(r.deg)).length;
    this.render();
    if (notify) this.notify(`已读取 ${liveCount}/${rows.length} 个有效关节角`);
  }

  async copy(kind) {
    const rows = this.currentRows();
    if (!rows.length) {
      this.notify('还没有可复制的关节角');
      return;
    }
    let text = '';
    if (kind === 'text') text = textTable(rows);
    else if (kind === 'deg') text = dictText(rows, {unit: 'deg'});
    else if (kind === 'legs') text = dictText(rows, {legsOnly: true, unit: 'rad'});
    else text = dictText(rows, {unit: 'rad'});
    try {
      await copyText(text);
      this.notify(kind === 'legs' ? '已复制腿部弧度字典' : kind === 'deg' ? '已复制角度字典' : kind === 'text' ? '已复制表格文本' : '已复制弧度字典');
    } catch (error) {
      this.notify(error.message || String(error));
    }
  }

  onSnapshot() {
    if (this.live) this.render();
  }

  render() {
    const body = this.$('pose-snapshot-rows');
    const status = this.$('pose-snapshot-status');
    const badge = this.$('pose-snapshot-badge');
    if (!body) return;
    const rows = this.currentRows();
    const liveCount = rows.filter(r => r.status === 'live' && finite(r.deg)).length;
    const stamp = this.live ? '持续刷新中' : (this.frozen ? '已冻结快照' : '尚未读取');
    if (status) status.textContent = `${stamp} · 有效 ${liveCount}/${rows.length || 15}`;
    if (badge) {
      badge.className = `badge ${liveCount === 15 ? '' : liveCount ? 'warn' : 'neutral'}`;
      badge.textContent = this.live ? 'LIVE' : this.frozen ? '快照' : '等待';
    }
    body.innerHTML = rows.map(r => {
      const live = r.status === 'live' && finite(r.deg);
      return `<tr class="${live ? '' : 'old-sample'}">
        <td><span class="servo-id">${r.id}</span><span class="servo-name">${r.label}</span></td>
        <td><code>${r.name}</code></td>
        <td>${fmt(r.deg, 2)}</td>
        <td>${fmt(r.rad, 4)}</td>
        <td>${live ? '实时' : (r.status === 'live' ? '无角度' : r.status)}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="5" class="muted">等待实机反馈</td></tr>';
  }
}
