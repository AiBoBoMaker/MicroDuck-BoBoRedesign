import {officialStandingDegrees} from './joint-reference.js';

const SERVO_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14];

export function demoRequested() {
  const hash = decodeURIComponent(location.hash.replace(/^#/, '')).replace(/\/+$/, '');
  return hash === 'demo' || hash.endsWith('/demo') || hash === 'diagnosticsdemo';
}

function wave(tick, speed, amount) {
  return Math.sin(tick * speed) * amount;
}

export function startDemo(cfg, render) {
  let tick = 0;
  const frame = () => render(demoSnapshot(cfg, tick++));
  frame();
  const timer = setInterval(frame, 200);
  window.addEventListener('pagehide', () => clearInterval(timer));
  if (location.hash.replace(/^#/, '').startsWith('diagnostics')) {
    requestAnimationFrame(() => document.getElementById('diagnostics')?.scrollIntoView());
  }
}

export function demoSnapshot(cfg, tick = 0) {
  const ids = cfg.ids?.length === SERVO_IDS.length ? cfg.ids : SERVO_IDS;
  const names = cfg.names || [];
  const labels = cfg.labels || [];
  const now = Date.now() / 1000;
  const volts = 7.4 + wave(tick, 0.08, 0.06);
  const temp = 34 + wave(tick, 0.05, 0.6);
  const roll = wave(tick, 0.07, 2.2);
  const pitch = -1.1 + wave(tick, 0.05, 1.4);
  const rollRad = roll * Math.PI / 180;
  const pitchRad = pitch * Math.PI / 180;
  const gravity = [
    Math.sin(pitchRad),
    -Math.sin(rollRad) * Math.cos(pitchRad),
    -Math.cos(rollRad) * Math.cos(pitchRad),
  ];
  const byId = {};
  const servos = ids.map((id, index) => {
    const name = names[index] || labels[index] || `关节 ${id}`;
    const label = labels[index] || name;
    const stand = officialStandingDegrees[id] ?? 0;
    const angle = stand + wave(tick + index, 0.09, 0.35);
    const position = Math.round(2048 + angle * 4096 / 360);
    byId[id] = {missing: 0, timeout: 0, consecutive_timeout: 0, consecutive_missing: 0};
    return {
      id, name, label, index,
      group: index < 5 ? 'left' : index < 10 ? 'head' : 'right',
      status: 'live',
      calibrated: true,
      source: 'demo',
      position_raw: position,
      goal_position_raw: position,
      angle_deg: angle,
      target_deg: angle,
      error_deg: 0,
      speed_raw: 0,
      load_raw: 0,
      current_raw: 12 + (index % 4),
      voltage_v: volts - index * 0.004,
      temperature_c: temp + (index % 5) * 0.3,
      torque_enabled: false,
      hardware_error: 0,
      moving: false,
      sample_age_ms: 28,
      calibration: {id, name, calibrated: true, zero_raw: 2048, direction: 1, min_rad: -0.8, max_rad: 0.8},
    };
  });
  byId[200] = {missing: 0, timeout: 0, consecutive_timeout: 0, consecutive_missing: 0};
  const distances = Array.from({length: 64}, (_, i) => 420 + ((i * 37 + tick * 3) % 900));
  const channel = (age = 30) => ({status: 'live', age_ms: age, error: '', seq: tick});
  return {
    schema: 'microduck-console/v1',
    demo: true,
    mode: 'service',
    read_only: true,
    connection_paused: true,
    service_sample_fresh: true,
    service_sample_age_ms: 28,
    service_compatible: true,
    calibrated_count: 15,
    saved_calibrated_count: 15,
    pose_calibrated: true,
    at: now,
    uptime: 5400 + tick * 0.2,
    connection: {active: false, connected: false},
    channels: {
      bus: channel(28),
      health: channel(40),
      system: channel(80),
      tof: channel(50),
      calibration: channel(120),
      startup: channel(0),
      state: {status: 'waiting', age_ms: null, error: '', seq: 0},
      capabilities: {status: 'waiting', age_ms: null, error: '', seq: 0},
    },
    bus: {
      mode: 'commissioning',
      phase: 'ready',
      torque_state: 'off',
      build: 'demo · 0.15.1 BoBo修改版',
      session: 'demo',
      cycle: 80 + tick,
      target_hz: 50,
      achieved_hz: 50 + wave(tick, 0.11, 0.35),
      total_cycles: 240 + tick,
      total_communication_failures: 0,
      errors_by_id: {},
      imu_mount_verified: true,
      device_communication: {
        classification: 'exclusive-v2',
        total_reads: 240 + tick,
        complete_but_late: 0,
        by_id: byId,
      },
      native: {
        torque_state_confirmed: false,
        sync: {address: 56, length: 15, request_sent: true, missing_ids: [], elapsed_us: 1900, complete_but_late: false, deadline_exceeded: false},
        telemetry: {total_reads: 240 + tick, failed_reads: 0, missing_by_id: {}, complete_but_late: 0, session: 'demo'},
      },
    },
    health: {
      healthy: true,
      battery: {volts},
      motors: {max_c: temp + 1.2, mean_c: temp, hottest: labels[0] || '左髋旋转'},
      control_loop: {target_hz: 50, missed: 0, achieved_hz: 50, last_tick_age_ms: 18},
      imu: {ready: true, consecutive_stale_blocks: 0, stale_blocks: 0},
      bus: {consecutive_errors: 0, startup_failures: 0},
    },
    imu: {
      status: 'live',
      ready: true,
      mount_verified: true,
      gravity,
      roll_deg: roll,
      pitch_deg: pitch,
      gyro: [0.01, -0.02, wave(tick, 0.2, 0.01)],
      quat: [1, 0, 0, 0],
      source: 'demo',
      reason: '',
    },
    state: {
      odom: {position: [0.35 + wave(tick, 0.02, 0.08), -0.12 + wave(tick, 0.017, 0.05), 0], yaw: 0.15},
      move: {requested: [0, 0, 0], applied: [0, 0, 0], limited_by: []},
      safety: {fallen: false, gravity},
      policy: 'demo',
    },
    system: {
      hostname: 'duck-demo',
      cpu_temp_c: 47 + wave(tick, 0.03, 0.8),
      cpu_percent: 22 + wave(tick, 0.06, 4),
      memory_total: 4 * 1024 ** 3,
      memory_available: 2.6 * 1024 ** 3,
      uptime_s: 5400 + tick * 0.2,
      identities: {robotd: {revision: 'demo'}},
    },
    tof: {rows: 8, cols: 8, seq: 12 + tick, distance_mm: distances, status: Array(64).fill(5)},
    servos,
    startup: {steps: {1: {status: 'ok', detail: '演示'}, 2: {status: 'ok', detail: '演示'}, 3: {status: 'ok', detail: '演示'}, 4: {status: 'ok', detail: '演示'}}},
    events: [{at: now, channel: 'bus', level: 'info', message: '演示数据：15 颗舵机通信正常'}],
    service_control: {available: false},
    control: {available: false, connected: false},
  };
}
