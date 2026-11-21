//! Microphone uplink and speaker downlink.
//!
//! Capture is `arecord` and playback is `aplay`, the same split the voice bank already
//! uses: the codec is exclusive, so one process owns it for the length of the call and
//! `robotd` yields its own sounds while the call holds the speaker flag.
//!
//! Opus exists on the robot. A host build still links the session, and the audio side
//! becomes a pair of channels that drop every frame — enough for the protocol tests.

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;

pub enum Downlink {
    Start(u32),
    Packet(Vec<u8>),
    /// Close the speaker and, when a waiter is present, tell it the tail has finished.
    Stop(Option<tokio::sync::oneshot::Sender<()>>),
    /// Two short beeps: the call is up and listening (R3 接通反馈).
    ReadyBeeps(Option<tokio::sync::oneshot::Sender<()>>),
}

pub struct Audio {
    stop: Arc<AtomicBool>,
    capture_enabled: Arc<AtomicBool>,
    /// True while arecord/sox (or FIFO read) holds the capture device.
    capture_busy: Arc<AtomicBool>,
    /// Set after TTS aplay — next mic open must hard-reclock AHUB.
    hard_recover: Arc<AtomicBool>,
    /// True once aplay actually opened for this TTS turn (not empty start/stop).
    aplay_opened: Arc<AtomicBool>,
    /// When true the FIFO reader closes its fd and waits.
    fifo_hold: Arc<AtomicBool>,
    uplink: tokio::sync::mpsc::Receiver<Vec<u8>>,
    downlink: std::sync::mpsc::Sender<Downlink>,
}

impl Audio {
    /// `mouth_open` is 0..=1000, written from decoded TTS amplitude for servo 34.
    pub fn start(
        capture_device: String,
        playback_device: String,
        mouth_open: Arc<AtomicU32>,
    ) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let capture_enabled = Arc::new(AtomicBool::new(false));
        let capture_busy = Arc::new(AtomicBool::new(false));
        let hard_recover = Arc::new(AtomicBool::new(false));
        let aplay_opened = Arc::new(AtomicBool::new(false));
        let fifo_hold = Arc::new(AtomicBool::new(false));
        let (uplink_tx, uplink) = tokio::sync::mpsc::channel(8);
        let (downlink, downlink_rx) = std::sync::mpsc::channel();

        spawn_capture(
            capture_device,
            Arc::clone(&stop),
            Arc::clone(&capture_enabled),
            Arc::clone(&capture_busy),
            Arc::clone(&hard_recover),
            Arc::clone(&fifo_hold),
            uplink_tx,
        );
        spawn_playback(
            playback_device,
            Arc::clone(&stop),
            Arc::clone(&mouth_open),
            Arc::clone(&aplay_opened),
            downlink_rx,
        );

        Self {
            stop,
            capture_enabled,
            capture_busy,
            hard_recover,
            aplay_opened,
            fifo_hold,
            uplink,
            downlink,
        }
    }

    pub fn set_capture(&self, on: bool) {
        self.capture_enabled.store(on, Ordering::Relaxed);
    }

    /// Turn capture off and wait until arecord has released the card (needed
    /// before aplay TTS on exclusive AIC3104).
    pub async fn set_capture_wait(&self, on: bool) {
        self.set_capture(on);
        if on {
            return;
        }
        for _ in 0..100 {
            if !self.capture_busy.load(Ordering::Relaxed) {
                // Device release can lag the process exit slightly.
                tokio::time::sleep(std::time::Duration::from_millis(40)).await;
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        tracing::warn!("关闭麦克风超时，喇叭可能抢不到声卡");
    }

    pub fn set_fifo_hold(&self, on: bool) {
        self.fifo_hold.store(on, Ordering::Relaxed);
    }

    pub fn uplink(&mut self) -> &mut tokio::sync::mpsc::Receiver<Vec<u8>> {
        &mut self.uplink
    }

    pub fn start_playback(&self, sample_rate: u32) {
        let rate = if sample_rate == 0 { 24_000 } else { sample_rate };
        self.aplay_opened.store(false, Ordering::Relaxed);
        let _ = self.downlink.send(Downlink::Start(rate));
    }

    pub fn play(&self, packet: Vec<u8>) {
        let _ = self.downlink.send(Downlink::Packet(packet));
    }

    /// Let the current sentence finish, then release the speaker. Bounded so a stuck
    /// `aplay` cannot hold the call open.
    pub async fn stop_playback(&self) {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if self.downlink.send(Downlink::Stop(Some(tx))).is_err() {
            return;
        }
        let _ = tokio::time::timeout(std::time::Duration::from_millis(800), rx).await;
        // Empty TTS never opened aplay — do not Hard-reprobe (keeps the live mic).
        if self.aplay_opened.swap(false, Ordering::Relaxed) {
            self.hard_recover.store(true, Ordering::Relaxed);
        }
    }

    /// Di-di: session hello succeeded, mic about to open.
    pub async fn play_ready_beeps(&self) {
        let (tx, rx) = tokio::sync::oneshot::channel();
        if self.downlink.send(Downlink::ReadyBeeps(Some(tx))).is_err() {
            return;
        }
        // Beeps are ~190 ms of PCM but aplay open/drain on AIC3104 is often >600 ms.
        // Timing out early starts arecord while aplay still holds the card → peak=1.
        let _ = tokio::time::timeout(std::time::Duration::from_secs(3), rx).await;
        // ALSA exclusive release lags process exit on this HAT.
        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    }

    pub fn quiet(&self) {
        self.set_capture(false);
        let _ = self.downlink.send(Downlink::Stop(None));
    }

    /// Hang up: stop mic/speaker threads and wait until the exclusive AIC3104 is free.
    /// Without this, restarting `duckmix-capture` (or robotd chirps) races the still-dying
    /// arecord/aplay and leaves LT/RT silent for the rest of the boot.
    pub async fn shutdown(self) {
        self.stop.store(true, Ordering::Relaxed);
        self.quiet();
        for _ in 0..100 {
            if !self.capture_busy.load(Ordering::Relaxed) {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        // ALSA exclusive release lags process exit on this HAT.
        tokio::time::sleep(std::time::Duration::from_millis(250)).await;
    }
}

/// Speaker level for the OPi codec, on the 0..=127 DAC scale the console uses: 75 ≈ 5 %,
/// about −26 dB. **Temporary** — the voice path used to force full scale (127).
#[cfg(target_os = "linux")]
const OPI_PLAYBACK_VOLUME: &str = "75,75";

/// Set the speaker level on its own.
///
/// Called as a call starts — so the first call after boot is already at this level instead of
/// whatever the boot script left — and again from [`restore_opi_codec_after_call`]. Blocking
/// `amixer` on the blocking pool for the same reason as the restore below.
#[cfg(target_os = "linux")]
pub async fn set_opi_playback_volume() {
    match tokio::task::spawn_blocking(|| {
        amixer_quiet(&["-c", "aic3104", "cset", "name=PCM Playback Volume", OPI_PLAYBACK_VOLUME]);
        amixer_quiet(&["-c", "aic3104", "cset", "name=Line Playback Switch", "on,on"]);
    })
    .await
    {
        Ok(()) => {}
        Err(error) => tracing::warn!(%error, "设置喇叭音量的线程失败"),
    }
}

#[cfg(not(target_os = "linux"))]
pub async fn set_opi_playback_volume() {}

/// After a voice call, put AHUB + AIC3104 back so robotd chirps/wheee and duckmix work again.
/// TTS recover cycles can leave the crossbar at NONE; duckmix restart alone is not enough
/// if it races the still-held card.
///
/// Async because every step is a blocking `amixer` spawn, and this runs on robotd's runtime:
/// a card that will not answer must not take the IPC socket down with it. The work itself runs
/// on the blocking pool.
#[cfg(target_os = "linux")]
pub async fn restore_opi_codec_after_call() {
    match tokio::task::spawn_blocking(restore_opi_codec_blocking).await {
        Ok(()) => {}
        Err(error) => tracing::warn!(%error, "恢复声卡路由的线程失败"),
    }
}

#[cfg(target_os = "linux")]
fn restore_opi_codec_blocking() {
    // Playback path (matches deploy/audio/aic3104-init.sh).
    amixer_quiet(&["-c", "aic3104", "cset", "name=PCM Playback Volume", OPI_PLAYBACK_VOLUME]);
    amixer_quiet(&["-c", "aic3104", "cset", "name=Line DAC Playback Volume", "118,118"]);
    amixer_quiet(&["-c", "aic3104", "cset", "name=Line Playback Switch", "on,on"]);
    amixer_quiet(&["-c", "aic3104", "cset", "name=Line Playback Volume", "9,9"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Left Line Mixer DACL1", "on"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Right Line Mixer DACR1", "on"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Left DAC Mux", "DAC_L1"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Right DAC Mux", "DAC_R1"]);
    // Capture + AHUB crossbar (same as duckmix / opi-mic-fix).
    apply_opi_mic_routing();
    tracing::warn!("通话结束：已恢复喇叭/麦克风路由");
}

#[cfg(not(target_os = "linux"))]
pub async fn restore_opi_codec_after_call() {}

/// Two 70 ms tones at 1.2 kHz with a 50 ms gap, 16 kHz mono S16.
fn ready_beep_pcm() -> Vec<u8> {
    const RATE: u32 = 16_000;
    const FREQ: f32 = 1_200.0;
    const AMP: f32 = 0.18;
    let beep = ((RATE as f32) * 0.070) as usize;
    let gap = ((RATE as f32) * 0.050) as usize;
    let mut samples = Vec::with_capacity(beep * 2 + gap);
    for i in 0..beep {
        let t = i as f32 / RATE as f32;
        let envelope = if i < 40 || i + 40 >= beep { 0.35 } else { 1.0 };
        let sample = (AMP * envelope * (2.0 * std::f32::consts::PI * FREQ * t).sin() * 32767.0)
            .clamp(-32768.0, 32767.0) as i16;
        samples.push(sample);
    }
    samples.extend(std::iter::repeat(0i16).take(gap));
    for i in 0..beep {
        let t = i as f32 / RATE as f32;
        let envelope = if i < 40 || i + 40 >= beep { 0.35 } else { 1.0 };
        let sample = (AMP * envelope * (2.0 * std::f32::consts::PI * FREQ * t).sin() * 32767.0)
            .clamp(-32768.0, 32767.0) as i16;
        samples.push(sample);
    }
    let mut bytes = Vec::with_capacity(samples.len() * 2);
    for sample in samples {
        bytes.extend_from_slice(&sample.to_le_bytes());
    }
    bytes
}

impl Drop for Audio {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.quiet();
    }
}

fn spawn_capture(
    device: String,
    stop: Arc<AtomicBool>,
    enabled: Arc<AtomicBool>,
    busy: Arc<AtomicBool>,
    hard_recover: Arc<AtomicBool>,
    fifo_hold: Arc<AtomicBool>,
    uplink: tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    std::thread::Builder::new()
        .name("bobo-mic".into())
        .spawn(move || {
            capture_loop(
                &device,
                &stop,
                &enabled,
                &busy,
                &hard_recover,
                &fifo_hold,
                &uplink,
            )
        })
        .ok();
}

fn spawn_playback(
    device: String,
    stop: Arc<AtomicBool>,
    mouth_open: Arc<AtomicU32>,
    aplay_opened: Arc<AtomicBool>,
    downlink: std::sync::mpsc::Receiver<Downlink>,
) {
    std::thread::Builder::new()
        .name("bobo-spk".into())
        .spawn(move || playback_loop(&device, &stop, &mouth_open, &aplay_opened, downlink))
        .ok();
}

/// Map a decoded float PCM peak to mouth open 0..=1000.
fn mouth_from_peak(peak: f32) -> u32 {
    // Speech peaks are often 0.05–0.4; scale so normal talk reaches ~full open.
    let open = (peak * 3.2).clamp(0.0, 1.0);
    (open * 1000.0).round() as u32
}

#[cfg(target_os = "linux")]
const FRAME_BYTES: usize = (crate::protocol::UPLINK_RATE as usize)
    * (crate::protocol::FRAME_MS as usize)
    / 1000
    * 2;

/// How to open the mic for this call.
///
/// `duckmix_cap` used to mean "read the duckmix FIFO". That races with aplay
/// (ready beeps / TTS) on the same AIC3104: arecord keeps running but the FIFO
/// becomes digital silence (`peak=1`). For OPi we now own `arecord|sox` for the
/// call (MIC2R, speed 0.5 → 16 kHz mono), matching the proven one-shot path.
fn capture_source(device: &str) -> CaptureSource<'_> {
    if device == "duckmix_cap" || device == "opi_aic3104" {
        CaptureSource::OpiHw
    } else if device.starts_with('/') {
        CaptureSource::Fifo(device)
    } else {
        CaptureSource::Arecord(device)
    }
}

#[derive(Debug, PartialEq, Eq)]
enum CaptureSource<'a> {
    OpiHw,
    Fifo(&'a str),
    Arecord(&'a str),
}

#[cfg(target_os = "linux")]
fn capture_loop(
    device: &str,
    stop: &AtomicBool,
    enabled: &AtomicBool,
    busy: &AtomicBool,
    hard_recover: &AtomicBool,
    fifo_hold: &AtomicBool,
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    match capture_source(device) {
        CaptureSource::OpiHw => {
            tracing::warn!("麦克风上行：本进程 arecord|sox（MIC2R, 48k→16k speed 0.5）");
            opi_hw_capture_loop(stop, enabled, busy, hard_recover, uplink);
        }
        CaptureSource::Fifo(path) => {
            tracing::warn!(%path, "麦克风上行：直接读 FIFO");
            let _ = hard_recover;
            fifo_capture_loop(path, stop, enabled, busy, fifo_hold, uplink);
        }
        CaptureSource::Arecord(name) => {
            tracing::warn!(device = %name, "麦克风上行：arecord");
            let _ = hard_recover;
            arecord_capture_loop(name, stop, enabled, busy, uplink);
        }
    }
}

/// Same conversion as deploy/audio/duckmix-capture.sh, but owned by this call so
/// aplay beeps cannot leave a background arecord stuck producing silence.
///
/// After aplay, AHUB often needs several arecord open cycles before peak rises.
/// Closing a *live* pipe and reopening kills it again — so we probe frames on the
/// candidate pipe and only keep the one that already has peak > silence.
#[cfg(target_os = "linux")]
fn opi_hw_capture_loop(
    stop: &AtomicBool,
    enabled: &AtomicBool,
    busy: &AtomicBool,
    hard_recover: &AtomicBool,
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    use std::io::Read;

    let mut encoder = match new_opus_encoder() {
        Some(encoder) => encoder,
        None => return,
    };
    let mut raw = vec![0u8; FRAME_BYTES];
    let mut pcm = vec![0i16; FRAME_BYTES / 2];
    let mut packet = vec![0u8; 1500];
    let mut sent_frames: u64 = 0;

    while !stop.load(Ordering::Relaxed) {
        if !enabled.load(Ordering::Relaxed) {
            busy.store(false, Ordering::Relaxed);
            std::thread::sleep(std::time::Duration::from_millis(20));
            continue;
        }

        let post_tts = hard_recover.swap(false, Ordering::Relaxed);
        busy.store(true, Ordering::Relaxed);
        let Some(mut pipe) = open_opi_pipeline_until_live(stop, enabled, post_tts, &mut raw, &mut pcm)
        else {
            busy.store(false, Ordering::Relaxed);
            if enabled.load(Ordering::Relaxed) {
                hard_recover.store(true, Ordering::Relaxed);
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            continue;
        };

        sent_frames = 0;
        // First live frame already sits in `raw`/`pcm` from the probe — uplink it.
        if !encode_and_send(&mut encoder, &raw, &mut pcm, &mut packet, uplink) {
            pipe.shutdown();
            return;
        }
        sent_frames = 1;
        {
            let mut peak: i32 = 0;
            for sample in pcm.iter().copied() {
                peak = peak.max(i32::from(sample.unsigned_abs()));
            }
            tracing::warn!(sent_frames, peak, "麦克风 Opus 已上行");
        }

        loop {
            if stop.load(Ordering::Relaxed) || !enabled.load(Ordering::Relaxed) {
                break;
            }
            if pipe.sox_out.read_exact(&mut raw).is_err() {
                tracing::warn!("OPi 采集管道断了，重开");
                hard_recover.store(true, Ordering::Relaxed);
                break;
            }
            if !encode_and_send(&mut encoder, &raw, &mut pcm, &mut packet, uplink) {
                pipe.shutdown();
                return;
            }
            sent_frames += 1;
            if sent_frames % 50 == 0 {
                let mut peak: i32 = 0;
                for sample in pcm.iter().copied() {
                    peak = peak.max(i32::from(sample.unsigned_abs()));
                }
                tracing::warn!(sent_frames, peak, "麦克风 Opus 已上行");
            }
        }
        pipe.shutdown();
        busy.store(false, Ordering::Relaxed);
    }
}

#[cfg(target_os = "linux")]
struct OpiPipe {
    arecord: std::process::Child,
    sox: std::process::Child,
    pump: Option<std::thread::JoinHandle<()>>,
    sox_out: std::process::ChildStdout,
}

#[cfg(target_os = "linux")]
impl OpiPipe {
    fn shutdown(&mut self) {
        let _ = self.arecord.kill();
        let _ = self.sox.kill();
        let _ = self.arecord.wait();
        let _ = self.sox.wait();
        if let Some(t) = self.pump.take() {
            let _ = t.join();
        }
    }
}

/// Open arecord|sox, reading until peak is live; keep that pipe (do not reopen).
#[cfg(target_os = "linux")]
fn open_opi_pipeline_until_live(
    stop: &AtomicBool,
    enabled: &AtomicBool,
    post_tts: bool,
    raw: &mut [u8],
    pcm: &mut [i16],
) -> Option<OpiPipe> {
    use std::io::{Read, Write};
    use std::process::{Command, Stdio};

    for attempt in 1u32..=6 {
        if stop.load(Ordering::Relaxed) || !enabled.load(Ordering::Relaxed) {
            return None;
        }
        // Post-TTS and retries: Hard. First connect: Soft.
        let strength = if post_tts || attempt > 1 {
            RecoverStrength::Hard
        } else {
            RecoverStrength::Soft
        };
        recover_opi_capture_clock(strength);
        tracing::warn!(attempt, ?strength, "启动 OPi 采集管道（探活，活了就留着）");

        let mut arecord = match Command::new("arecord")
            .args([
                "-D",
                "hw:aic3104,0",
                "-f",
                "S32_LE",
                "-r",
                "48000",
                "-c",
                "2",
                "-t",
                "raw",
                "-q",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                tracing::warn!(%error, "arecord(hw:aic3104) 启动失败");
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };
        let arecord_out = match arecord.stdout.take() {
            Some(out) => out,
            None => {
                let _ = arecord.kill();
                let _ = arecord.wait();
                continue;
            }
        };
        let mut sox = match Command::new("sox")
            .args([
                "-t", "raw", "-r", "48000", "-e", "signed", "-b", "32", "-c", "2", "-",
                "-t", "raw", "-r", "16000", "-e", "signed", "-b", "16", "-c", "1", "-",
                "remix", "-m", "1", "2", "speed", "0.5",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                tracing::warn!(%error, "sox 启动失败（需要 apt install sox）");
                let _ = arecord.kill();
                let _ = arecord.wait();
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };
        let mut sox_in = match sox.stdin.take() {
            Some(stdin) => stdin,
            None => {
                let _ = arecord.kill();
                let _ = sox.kill();
                let _ = arecord.wait();
                let _ = sox.wait();
                continue;
            }
        };
        let pump = std::thread::Builder::new()
            .name("bobo-mic-pump".into())
            .spawn(move || {
                let mut src = arecord_out;
                let mut buf = [0u8; 8192];
                loop {
                    match src.read(&mut buf) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => {
                            if sox_in.write_all(&buf[..n]).is_err() {
                                break;
                            }
                        }
                    }
                }
            })
            .ok();
        let mut sox_out = match sox.stdout.take() {
            Some(out) => out,
            None => {
                let _ = arecord.kill();
                let _ = sox.kill();
                let _ = arecord.wait();
                let _ = sox.wait();
                if let Some(t) = pump {
                    let _ = t.join();
                }
                continue;
            }
        };

        // Probe up to 8 frames (~480 ms). Keep the pipe if any frame is live.
        let mut live_peak: i32 = 0;
        let mut live = false;
        for _ in 0..8 {
            if stop.load(Ordering::Relaxed) || !enabled.load(Ordering::Relaxed) {
                break;
            }
            if sox_out.read_exact(raw).is_err() {
                break;
            }
            for (index, chunk) in raw.chunks_exact(2).enumerate() {
                pcm[index] = i16::from_le_bytes([chunk[0], chunk[1]]);
            }
            let mut peak: i32 = 0;
            for sample in pcm.iter().copied() {
                peak = peak.max(i32::from(sample.unsigned_abs()));
            }
            live_peak = live_peak.max(peak);
            if peak > 32 {
                live = true;
                break;
            }
        }

        if live {
            tracing::warn!(attempt, peak = live_peak, "采麦探活成功，管道留作上行");
            return Some(OpiPipe {
                arecord,
                sox,
                pump,
                sox_out,
            });
        }

        tracing::warn!(attempt, peak = live_peak, "采麦探活仍 peak≈1，关掉再试");
        let _ = arecord.kill();
        let _ = sox.kill();
        let _ = arecord.wait();
        let _ = sox.wait();
        if let Some(t) = pump {
            let _ = t.join();
        }
        std::thread::sleep(std::time::Duration::from_millis(40));
    }
    tracing::warn!("采麦探活 6 次仍失败");
    None
}

#[cfg(target_os = "linux")]
fn amixer_quiet(args: &[&str]) {
    use std::process::{Command, Stdio};
    let _ = Command::new("amixer")
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[derive(Debug, Clone, Copy)]
enum RecoverStrength {
    /// First connect open.
    Soft,
    /// Post-TTS / probe retry: double NONE→route (no throwaway — that open must
    /// be the uplink pipe, handled by open_opi_pipeline_until_live).
    Hard,
}

/// After aplay (TTS), sunxi AHUB capture often keeps producing digital silence
/// until the crossbar is cycled OFF→ON and the mic route is rewritten.
#[cfg(target_os = "linux")]
fn recover_opi_capture_clock(strength: RecoverStrength) {
    let cycles = match strength {
        RecoverStrength::Soft => 1,
        RecoverStrength::Hard => 2,
    };
    let none_ms = match strength {
        RecoverStrength::Soft => 60,
        RecoverStrength::Hard => 80,
    };
    for _ in 0..cycles {
        amixer_quiet(&["-c", "ahubdam", "sset", "I2S0 Src Select", "NONE"]);
        amixer_quiet(&["-c", "ahubdam", "sset", "APBIF0 Src Select", "NONE"]);
        std::thread::sleep(std::time::Duration::from_millis(none_ms));
        apply_opi_mic_routing();
    }
    std::thread::sleep(std::time::Duration::from_millis(60));
}

#[cfg(target_os = "linux")]
fn apply_opi_mic_routing() {
    // Match deploy/audio/opi-mic-fix.sh + duckmix-capture.sh (Mic3R on this board).
    amixer_quiet(&["-c", "ahubdam", "sset", "I2S0 Src Select", "APBIF_TXDIF0"]);
    amixer_quiet(&["-c", "ahubdam", "sset", "APBIF0 Src Select", "I2S0_TXDIF"]);
    for side in ["Left", "Right"] {
        for inp in [
            "Mic3L", "Mic3R", "Mic2L", "Mic2R", "Line1L", "Line1R", "Line2L", "Line2R",
        ] {
            let name = format!("{side} PGA Mixer {inp}");
            amixer_quiet(&["-c", "aic3104", "sset", &name, "off"]);
        }
    }
    // Pin 16: Mic3R on this board (Mic2R first if the control exists).
    amixer_quiet(&["-c", "aic3104", "sset", "Right PGA Mixer Mic2R", "on"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Right PGA Mixer Mic3R", "on"]);
    amixer_quiet(&["-c", "aic3104", "sset", "Left PGA Mixer Mic3R", "on"]);
    amixer_quiet(&["-c", "aic3104", "cset", "name=PGA Capture Switch", "on,on"]);
    amixer_quiet(&["-c", "aic3104", "cset", "name=PGA Capture Volume", "40,70"]);
    amixer_quiet(&["-c", "aic3104", "sset", "AGC", "off"]);
}

#[cfg(target_os = "linux")]
fn fifo_capture_loop(
    path: &str,
    stop: &AtomicBool,
    enabled: &AtomicBool,
    busy: &AtomicBool,
    fifo_hold: &AtomicBool,
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    use std::io::Read;

    let mut encoder = match new_opus_encoder() {
        Some(encoder) => encoder,
        None => return,
    };
    let mut raw = vec![0u8; FRAME_BYTES];
    let mut pcm = vec![0i16; FRAME_BYTES / 2];
    let mut packet = vec![0u8; 1500];
    let mut sent_frames: u64 = 0;
    let mut skip_after_enable: u32 = 0;
    let mut was_enabled = false;

    while !stop.load(Ordering::Relaxed) {
        if fifo_hold.load(Ordering::Relaxed) {
            busy.store(false, Ordering::Relaxed);
            std::thread::sleep(std::time::Duration::from_millis(40));
            continue;
        }
        let mut file = match std::fs::OpenOptions::new().read(true).open(path) {
            Ok(file) => {
                tracing::warn!(%path, "麦克风 FIFO 已打开");
                file
            }
            Err(error) => {
                tracing::warn!(%error, %path, "打不开麦克风 FIFO（duckmix-capture 在跑吗？）");
                busy.store(false, Ordering::Relaxed);
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };
        loop {
            if stop.load(Ordering::Relaxed) {
                busy.store(false, Ordering::Relaxed);
                return;
            }
            if fifo_hold.load(Ordering::Relaxed) {
                tracing::warn!(%path, "麦克风 FIFO hold：关掉 fd");
                busy.store(false, Ordering::Relaxed);
                break;
            }
            if file.read_exact(&mut raw).is_err() {
                tracing::warn!(%path, "麦克风 FIFO 断了；重新打开");
                busy.store(false, Ordering::Relaxed);
                std::thread::sleep(std::time::Duration::from_millis(100));
                break;
            }
            let now_enabled = enabled.load(Ordering::Relaxed);
            if now_enabled && !was_enabled {
                skip_after_enable = 5;
                sent_frames = 0;
            }
            was_enabled = now_enabled;
            if !now_enabled {
                busy.store(false, Ordering::Relaxed);
                continue;
            }
            busy.store(true, Ordering::Relaxed);
            if skip_after_enable > 0 {
                skip_after_enable -= 1;
                continue;
            }
            if !encode_and_send(&mut encoder, &raw, &mut pcm, &mut packet, uplink) {
                return;
            }
            sent_frames += 1;
            if sent_frames == 1 || sent_frames % 50 == 0 {
                let mut peak: i32 = 0;
                for sample in pcm.iter().copied() {
                    peak = peak.max(i32::from(sample.unsigned_abs()));
                }
                tracing::warn!(sent_frames, peak, "麦克风 Opus 已上行");
            }
        }
    }
}

#[cfg(target_os = "linux")]
fn arecord_capture_loop(
    device: &str,
    stop: &AtomicBool,
    enabled: &AtomicBool,
    busy: &AtomicBool,
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    use std::io::Read;
    use std::process::{Command, Stdio};

    while !stop.load(Ordering::Relaxed) {
        if !enabled.load(Ordering::Relaxed) {
            busy.store(false, Ordering::Relaxed);
            std::thread::sleep(std::time::Duration::from_millis(20));
            continue;
        }
        busy.store(true, Ordering::Relaxed);
        let mut child = match Command::new("arecord")
            .args([
                "-D",
                device,
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-t",
                "raw",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                tracing::warn!(%error, "arecord failed to start");
                busy.store(false, Ordering::Relaxed);
                std::thread::sleep(std::time::Duration::from_secs(1));
                continue;
            }
        };
        let mut stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                continue;
            }
        };
        let stderr = child.stderr.take();
        let mut encoder = match new_opus_encoder() {
            Some(encoder) => encoder,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                return;
            }
        };
        let mut raw = vec![0u8; FRAME_BYTES];
        let mut pcm = vec![0i16; FRAME_BYTES / 2];
        let mut packet = vec![0u8; 1500];
        loop {
            if stop.load(Ordering::Relaxed) {
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                return;
            }
            if !enabled.load(Ordering::Relaxed) {
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                break;
            }
            if stdout.read_exact(&mut raw).is_err() {
                let err = stderr
                    .and_then(|mut pipe| {
                        let mut text = String::new();
                        let _ = pipe.read_to_string(&mut text);
                        Some(text)
                    })
                    .unwrap_or_default();
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                tracing::warn!(%device, stderr = %err.trim(), "arecord stopped; opening the microphone again");
                std::thread::sleep(std::time::Duration::from_secs(1));
                break;
            }
            if !encode_and_send(&mut encoder, &raw, &mut pcm, &mut packet, uplink) {
                let _ = child.kill();
                let _ = child.wait();
                busy.store(false, Ordering::Relaxed);
                return;
            }
        }
    }
}

#[cfg(target_os = "linux")]
fn new_opus_encoder() -> Option<opus_rs::OpusEncoder> {
    match opus_rs::OpusEncoder::new(
        crate::protocol::UPLINK_RATE as i32,
        1,
        opus_rs::Application::Voip,
    ) {
        Ok(mut encoder) => {
            encoder.bitrate_bps = 24_000;
            Some(encoder)
        }
        Err(error) => {
            tracing::warn!(%error, "opus encoder failed");
            None
        }
    }
}

#[cfg(target_os = "linux")]
fn encode_and_send(
    encoder: &mut opus_rs::OpusEncoder,
    raw: &[u8],
    pcm: &mut [i16],
    packet: &mut [u8],
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) -> bool {
    for (index, chunk) in raw.chunks_exact(2).enumerate() {
        pcm[index] = i16::from_le_bytes([chunk[0], chunk[1]]);
    }
    match encoder.encode_i16(pcm, pcm.len(), packet) {
        Ok(size) if size > 0 => {
            if uplink.blocking_send(packet[..size].to_vec()).is_err() {
                return false;
            }
        }
        Ok(_) => {}
        Err(error) => tracing::warn!(%error, "opus encode failed"),
    }
    true
}

#[cfg(not(target_os = "linux"))]
fn capture_loop(
    _device: &str,
    stop: &AtomicBool,
    _enabled: &AtomicBool,
    _busy: &AtomicBool,
    _hard_recover: &AtomicBool,
    _fifo_hold: &AtomicBool,
    _uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    while !stop.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
}

#[cfg(target_os = "linux")]
fn playback_loop(
    device: &str,
    stop: &AtomicBool,
    mouth_open: &AtomicU32,
    aplay_opened: &AtomicBool,
    downlink: std::sync::mpsc::Receiver<Downlink>,
) {
    use std::io::Write;
    use std::process::{Command, Stdio};

    let mut child: Option<std::process::Child> = None;
    let mut stdin: Option<std::process::ChildStdin> = None;
    let mut decoder: Option<opus_rs::OpusDecoder> = None;
    let mut pending_rate: u32 = 24_000;
    let mut pcm = vec![0f32; 5760];

    while !stop.load(Ordering::Relaxed) {
        let command = match downlink.recv_timeout(std::time::Duration::from_millis(200)) {
            Ok(command) => command,
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => continue,
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        };
        match command {
            Downlink::Stop(done) => {
                mouth_open.store(0, Ordering::Relaxed);
                drop(stdin.take());
                if let Some(mut child) = child.take() {
                    let started = std::time::Instant::now();
                    loop {
                        match child.try_wait() {
                            Ok(Some(_)) | Err(_) => break,
                            Ok(None) if started.elapsed() > std::time::Duration::from_millis(700) => {
                                let _ = child.kill();
                                let _ = child.wait();
                                break;
                            }
                            Ok(None) => std::thread::sleep(std::time::Duration::from_millis(20)),
                        }
                    }
                }
                decoder = None;
                if let Some(done) = done {
                    let _ = done.send(());
                }
            }
            Downlink::Start(rate) => {
                // Prepare decoder only — do not open aplay until the first Opus
                // packet. Empty tts start/stop must not touch the exclusive card.
                mouth_open.store(0, Ordering::Relaxed);
                aplay_opened.store(false, Ordering::Relaxed);
                drop(stdin.take());
                if let Some(mut child) = child.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                pending_rate = if rate == 0 { 24_000 } else { rate };
                decoder = opus_rs::OpusDecoder::new(pending_rate as i32, 1)
                    .map_err(|error| tracing::warn!(%error, rate = pending_rate, "opus decoder failed"))
                    .ok();
            }
            Downlink::ReadyBeeps(done) => {
                mouth_open.store(0, Ordering::Relaxed);
                drop(stdin.take());
                if let Some(mut child) = child.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                decoder = None;
                let pcm = ready_beep_pcm();
                match Command::new("aplay")
                    .args([
                        "-q",
                        "-D",
                        device,
                        "-t",
                        "raw",
                        "-f",
                        "S16_LE",
                        "-c",
                        "1",
                        "-r",
                        "16000",
                    ])
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
                {
                    Ok(mut spawned) => {
                        if let Some(mut input) = spawned.stdin.take() {
                            let _ = input.write_all(&pcm);
                        }
                        let _ = spawned.wait();
                    }
                    Err(error) => tracing::warn!(%error, "ready beeps failed"),
                }
                if let Some(done) = done {
                    let _ = done.send(());
                }
            }
            Downlink::Packet(packet) => {
                let decoded = decoder.as_mut().and_then(|decoder| {
                    match decoder.decode(&packet, pcm.len(), &mut pcm) {
                        Ok(count) => Some(count),
                        Err(error) => {
                            tracing::warn!(%error, "opus decode failed");
                            None
                        }
                    }
                });
                let Some(count) = decoded else {
                    continue;
                };
                if child.is_none() {
                    match Command::new("aplay")
                        .args(["-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-c", "1", "-r"])
                        .arg(pending_rate.to_string())
                        .args(["--buffer-time=200000"])
                        .stdin(Stdio::piped())
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .spawn()
                    {
                        Ok(mut spawned) => {
                            stdin = spawned.stdin.take();
                            child = Some(spawned);
                            aplay_opened.store(true, Ordering::Relaxed);
                        }
                        Err(error) => {
                            tracing::warn!(%error, "aplay failed to start");
                            continue;
                        }
                    }
                }
                let mut peak = 0.0f32;
                let mut bytes = Vec::with_capacity(count * 2);
                for sample in &pcm[..count] {
                    peak = peak.max(sample.abs());
                    let scaled = (sample * 32767.0).clamp(-32768.0, 32767.0) as i16;
                    bytes.extend_from_slice(&scaled.to_le_bytes());
                }
                mouth_open.store(mouth_from_peak(peak), Ordering::Relaxed);
                let failed = stdin
                    .as_mut()
                    .is_some_and(|input| input.write_all(&bytes).is_err());
                if failed {
                    mouth_open.store(0, Ordering::Relaxed);
                    tracing::warn!("speaker closed");
                    drop(stdin.take());
                    if let Some(mut child) = child.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                    decoder = None;
                }
            }
        }
    }
    drop(stdin.take());
    if let Some(mut child) = child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg(test)]
mod codec_tests {
    use super::ready_beep_pcm;

    #[test]
    fn a_silent_frame_encodes_and_decodes() {
        let mut encoder =
            opus_rs::OpusEncoder::new(16_000, 1, opus_rs::Application::Voip).unwrap();
        encoder.bitrate_bps = 24_000;
        let pcm = vec![0i16; 960];
        let mut packet = vec![0u8; 1500];
        let size = encoder.encode_i16(&pcm, pcm.len(), &mut packet).unwrap();
        assert!(size > 1);
        let mut decoder = opus_rs::OpusDecoder::new(16_000, 1).unwrap();
        let mut decoded = vec![0f32; 960];
        let samples = decoder
            .decode(&packet[..size], decoded.len(), &mut decoded)
            .unwrap();
        assert_eq!(samples, 960);
    }

    #[test]
    fn ready_beeps_are_two_short_tones() {
        let pcm = ready_beep_pcm();
        // 70 ms + 50 ms + 70 ms at 16 kHz mono S16.
        assert_eq!(pcm.len(), ((0.070 + 0.050 + 0.070) * 16_000.0) as usize * 2);
        assert!(pcm.iter().any(|&b| b != 0));
    }

    #[test]
    fn duckmix_cap_uses_owned_opi_pipeline() {
        assert_eq!(
            super::capture_source("duckmix_cap"),
            super::CaptureSource::OpiHw
        );
        assert_eq!(
            super::capture_source("plughw:aic3104,0"),
            super::CaptureSource::Arecord("plughw:aic3104,0")
        );
    }
}

#[cfg(not(target_os = "linux"))]
fn playback_loop(
    _device: &str,
    stop: &AtomicBool,
    mouth_open: &AtomicU32,
    aplay_opened: &AtomicBool,
    downlink: std::sync::mpsc::Receiver<Downlink>,
) {
    while !stop.load(Ordering::Relaxed) {
        match downlink.recv_timeout(std::time::Duration::from_millis(200)) {
            Ok(Downlink::Stop(done)) => {
                mouth_open.store(0, Ordering::Relaxed);
                if let Some(done) = done {
                    let _ = done.send(());
                }
            }
            Ok(Downlink::Start(rate)) => {
                mouth_open.store(0, Ordering::Relaxed);
                aplay_opened.store(false, Ordering::Relaxed);
                let _ = rate;
            }
            Ok(Downlink::ReadyBeeps(done)) => {
                mouth_open.store(0, Ordering::Relaxed);
                if let Some(done) = done {
                    let _ = done.send(());
                }
            }
            Ok(Downlink::Packet(packet)) => {
                aplay_opened.store(true, Ordering::Relaxed);
                let _ = packet;
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}
