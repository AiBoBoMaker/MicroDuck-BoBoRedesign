//! Microphone uplink and speaker downlink.
//!
//! Capture is `arecord` and playback is `aplay`, the same split the voice bank already
//! uses: the codec is exclusive, so one process owns it for the length of the call and
//! `robotd` yields its own sounds while the call holds the speaker flag.
//!
//! Opus exists on the robot. A host build still links the session, and the audio side
//! becomes a pair of channels that drop every frame — enough for the protocol tests.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

pub enum Downlink {
    Start(u32),
    Packet(Vec<u8>),
    /// Close the speaker and, when a waiter is present, tell it the tail has finished.
    Stop(Option<tokio::sync::oneshot::Sender<()>>),
}

pub struct Audio {
    stop: Arc<AtomicBool>,
    capture_enabled: Arc<AtomicBool>,
    uplink: tokio::sync::mpsc::Receiver<Vec<u8>>,
    downlink: std::sync::mpsc::Sender<Downlink>,
}

impl Audio {
    pub fn start(capture_device: String, playback_device: String) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let capture_enabled = Arc::new(AtomicBool::new(false));
        let (uplink_tx, uplink) = tokio::sync::mpsc::channel(8);
        let (downlink, downlink_rx) = std::sync::mpsc::channel();

        spawn_capture(
            capture_device,
            Arc::clone(&stop),
            Arc::clone(&capture_enabled),
            uplink_tx,
        );
        spawn_playback(playback_device, Arc::clone(&stop), downlink_rx);

        Self {
            stop,
            capture_enabled,
            uplink,
            downlink,
        }
    }

    pub fn set_capture(&self, on: bool) {
        self.capture_enabled.store(on, Ordering::Relaxed);
    }

    pub fn uplink(&mut self) -> &mut tokio::sync::mpsc::Receiver<Vec<u8>> {
        &mut self.uplink
    }

    pub fn start_playback(&self, sample_rate: u32) {
        let rate = if sample_rate == 0 { 24_000 } else { sample_rate };
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
    }

    pub fn quiet(&self) {
        self.set_capture(false);
        let _ = self.downlink.send(Downlink::Stop(None));
    }
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
    uplink: tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    std::thread::Builder::new()
        .name("bobo-mic".into())
        .spawn(move || capture_loop(&device, &stop, &enabled, &uplink))
        .ok();
}

fn spawn_playback(
    device: String,
    stop: Arc<AtomicBool>,
    downlink: std::sync::mpsc::Receiver<Downlink>,
) {
    std::thread::Builder::new()
        .name("bobo-spk".into())
        .spawn(move || playback_loop(&device, &stop, downlink))
        .ok();
}

#[cfg(target_os = "linux")]
fn capture_loop(
    device: &str,
    stop: &AtomicBool,
    enabled: &AtomicBool,
    uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    use std::io::Read;
    use std::process::{Command, Stdio};

    const FRAME_BYTES: usize = (crate::protocol::UPLINK_RATE as usize)
        * (crate::protocol::FRAME_MS as usize)
        / 1000
        * 2;

    while !stop.load(Ordering::Relaxed) {
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
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                tracing::warn!(%error, "arecord failed to start");
                std::thread::sleep(std::time::Duration::from_secs(1));
                continue;
            }
        };
        let mut stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                continue;
            }
        };
        let mut encoder = match opus_rs::OpusEncoder::new(
            crate::protocol::UPLINK_RATE as i32,
            1,
            opus_rs::Application::Voip,
        ) {
            Ok(mut encoder) => {
                encoder.bitrate_bps = 24_000;
                encoder
            }
            Err(error) => {
                tracing::warn!(%error, "opus encoder failed");
                let _ = child.kill();
                let _ = child.wait();
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
                return;
            }
            if stdout.read_exact(&mut raw).is_err() {
                let _ = child.kill();
                let _ = child.wait();
                tracing::warn!("arecord stopped; opening the microphone again");
                std::thread::sleep(std::time::Duration::from_secs(1));
                break;
            }
            if !enabled.load(Ordering::Relaxed) {
                continue;
            }
            for (index, chunk) in raw.chunks_exact(2).enumerate() {
                pcm[index] = i16::from_le_bytes([chunk[0], chunk[1]]);
            }
            match encoder.encode_i16(&pcm, pcm.len(), &mut packet) {
                Ok(size) if size > 0 => {
                    if uplink.blocking_send(packet[..size].to_vec()).is_err() {
                        let _ = child.kill();
                        let _ = child.wait();
                        return;
                    }
                }
                Ok(_) => {}
                Err(error) => tracing::warn!(%error, "opus encode failed"),
            }
        }
    }
}

#[cfg(not(target_os = "linux"))]
fn capture_loop(
    _device: &str,
    stop: &AtomicBool,
    _enabled: &AtomicBool,
    _uplink: &tokio::sync::mpsc::Sender<Vec<u8>>,
) {
    while !stop.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
}

#[cfg(target_os = "linux")]
fn playback_loop(device: &str, stop: &AtomicBool, downlink: std::sync::mpsc::Receiver<Downlink>) {
    use std::io::Write;
    use std::process::{Command, Stdio};

    let mut child: Option<std::process::Child> = None;
    let mut stdin: Option<std::process::ChildStdin> = None;
    let mut decoder: Option<opus_rs::OpusDecoder> = None;
    let mut pcm = vec![0f32; 5760];

    while !stop.load(Ordering::Relaxed) {
        let command = match downlink.recv_timeout(std::time::Duration::from_millis(200)) {
            Ok(command) => command,
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => continue,
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        };
        match command {
            Downlink::Stop(done) => {
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
                drop(stdin.take());
                if let Some(mut child) = child.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                decoder = opus_rs::OpusDecoder::new(rate as i32, 1)
                    .map_err(|error| tracing::warn!(%error, rate, "opus decoder failed"))
                    .ok();
                match Command::new("aplay")
                    .args(["-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-c", "1", "-r"])
                    .arg(rate.to_string())
                    .args(["--buffer-time=200000"])
                    .stdin(Stdio::piped())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
                {
                    Ok(mut spawned) => {
                        stdin = spawned.stdin.take();
                        child = Some(spawned);
                    }
                    Err(error) => tracing::warn!(%error, "aplay failed to start"),
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
                let mut bytes = Vec::with_capacity(count * 2);
                for sample in &pcm[..count] {
                    let scaled = (sample * 32767.0).clamp(-32768.0, 32767.0) as i16;
                    bytes.extend_from_slice(&scaled.to_le_bytes());
                }
                let failed = stdin
                    .as_mut()
                    .is_some_and(|input| input.write_all(&bytes).is_err());
                if failed {
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
}

#[cfg(not(target_os = "linux"))]
fn playback_loop(_device: &str, stop: &AtomicBool, downlink: std::sync::mpsc::Receiver<Downlink>) {
    while !stop.load(Ordering::Relaxed) {
        match downlink.recv_timeout(std::time::Duration::from_millis(200)) {
            Ok(Downlink::Stop(done)) => {
                if let Some(done) = done {
                    let _ = done.send(());
                }
            }
            Ok(Downlink::Start(rate)) => {
                let _ = rate;
            }
            Ok(Downlink::Packet(packet)) => {
                let _ = packet;
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}
