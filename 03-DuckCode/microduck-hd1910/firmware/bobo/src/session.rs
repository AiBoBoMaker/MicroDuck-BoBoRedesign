//! One voice call: connect, hello, then listen until the button hangs up.
//!
//! The button is edge-triggered. The first press enters here; a later press aborts a
//! sentence or closes the socket, which is the reference firmware's boot button.

use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU8, Ordering};
use std::sync::Arc;
use std::time::Duration;

use futures_util::{Sink, SinkExt, Stream, StreamExt};
use tokio::time::timeout;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use crate::audio::Audio;
use crate::identity::{client_id, device_id};
use crate::keywords::KeywordRule;
use crate::machine::{Effect, Machine, Phase, Press};
use crate::ota::{self, Endpoint};
use crate::protocol::{self, authorization_value};

const HELLO_TIMEOUT: Duration = Duration::from_secs(10);
const IDLE_TIMEOUT: Duration = Duration::from_secs(120);

/// How long the sound card hand-off may take before the call carries on without it.
///
/// `systemctl` is a blocking D-Bus round-trip, and on this board the audio units can sit in a
/// stop/start job for tens of seconds: an `arecord` that ignores SIGTERM, or a start queued
/// behind a stale stop. That must never hold the runtime that serves `/run/robotd.sock` — the
/// pad times out after three seconds and the whole robot looks dead. Ten seconds clears the
/// 3 s + 2 s the stop path itself budgets, and is bounded so the call still ends.
const SYSTEMCTL_TIMEOUT: Duration = Duration::from_secs(10);

pub struct SessionConfig {
    pub enabled: bool,
    pub url: String,
    pub token: String,
    pub client_id_path: String,
    pub capture_device: String,
    pub playback_device: String,
    /// STT keyword → action rules (snapshot at call start; robotd may also hot-reload).
    pub keywords: Vec<KeywordRule>,
}

/// Compact phase code for telemetry (`Phase::code`).
pub fn phase_code(phase: &AtomicU8) -> u8 {
    phase.load(Ordering::Relaxed)
}

fn publish_phase(phase: &AtomicU8, machine: &Machine) {
    phase.store(machine.phase().code(), Ordering::Relaxed);
}

/// Wait for button presses and run one call at a time.
pub async fn run(
    mut toggles: tokio::sync::mpsc::Receiver<()>,
    speaker: Arc<AtomicBool>,
    talking: Arc<AtomicBool>,
    mouth_open: Arc<AtomicU32>,
    phase: Arc<AtomicU8>,
    emotion: Arc<AtomicU8>,
    expression_seed: Arc<AtomicU32>,
    keyword_tx: tokio::sync::mpsc::Sender<String>,
    keywords_live: Arc<std::sync::RwLock<Vec<KeywordRule>>>,
    cfg: SessionConfig,
) {
    while toggles.recv().await.is_some() {
        if !cfg.enabled {
            tracing::warn!("语音对话已在配置里关闭");
            continue;
        }
        let url = cfg.url.trim();
        if url.is_empty() {
            tracing::warn!("还没有配置 [bobo] url，右摇杆和菜单键暂时不能通话");
            continue;
        }
        if !(url.starts_with("ws://")
            || url.starts_with("wss://")
            || url.starts_with("http://")
            || url.starts_with("https://"))
        {
            tracing::warn!(%url, "语音服务器地址要以 ws://、wss:// 或 OTA 的 http(s):// 开头");
            continue;
        }
        speaker.store(true, Ordering::Relaxed);
        phase.store(Phase::Connecting.code(), Ordering::Relaxed);
        emotion.store(0, Ordering::Relaxed);
        // OPi duckmix holds hw:aic3104. Release it for the whole call so beeps
        // and our arecord|sox pipeline own the card (FIFO stayed peak=1 otherwise).
        let opi = uses_opi_pipeline(&cfg.capture_device);
        if opi {
            systemctl_duckmix("stop").await;
            // The call's own speaker level, set before the first `aplay` rather than only after
            // hang-up: the boot script still leaves the codec at full scale.
            crate::audio::set_opi_playback_volume().await;
        }
        let mut audio = Audio::start(
            cfg.capture_device.clone(),
            cfg.playback_device.clone(),
            Arc::clone(&mouth_open),
        );
        if let Err(error) = conversation(
            &mut toggles,
            &mut audio,
            &cfg,
            &talking,
            &phase,
            &emotion,
            &expression_seed,
            &keyword_tx,
            &keywords_live,
        )
        .await
        {
            tracing::warn!(%error, "语音对话没有接通");
        }
        // Free the card before duckmix / robotd chirps may open it. Clearing
        // `speaker` only after this — otherwise LT/RT quacks race a dying aplay
        // and the exclusive codec stays wedged for the rest of the boot.
        audio.shutdown().await;
        if opi {
            crate::audio::restore_opi_codec_after_call().await;
            systemctl_duckmix("start").await;
            // Let duckmix's arecord settle before robotd chirps share the card.
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        talking.store(false, Ordering::Relaxed);
        mouth_open.store(0, Ordering::Relaxed);
        emotion.store(0, Ordering::Relaxed);
        speaker.store(false, Ordering::Relaxed);
        phase.store(Phase::Idle.code(), Ordering::Relaxed);
        tracing::warn!("语音对话已结束");
    }
}

fn uses_opi_pipeline(capture_device: &str) -> bool {
    let d = capture_device.trim();
    d == "duckmix_cap" || d == "opi_aic3104"
}

/// Stop or start `duckmix-capture` without stalling the async runtime.
///
/// The work itself blocks on purpose — it waits on systemd — so it runs on the blocking pool
/// and is bounded here. A hand-off that overruns carries on in the background; the call moves
/// on either way, which is what keeps `/run/robotd.sock` answering while the card changes hands.
async fn systemctl_duckmix(action: &'static str) {
    tracing::warn!(%action, "通话切换 duckmix-capture");
    let hand_off = tokio::task::spawn_blocking(move || systemctl_duckmix_blocking(action));
    match timeout(SYSTEMCTL_TIMEOUT, hand_off).await {
        Ok(Ok(())) => {}
        Ok(Err(error)) => tracing::warn!(%action, %error, "duckmix 切换线程失败"),
        Err(_) => tracing::warn!(
            %action,
            timeout_s = SYSTEMCTL_TIMEOUT.as_secs(),
            "duckmix 切换超时，语音流程继续"
        ),
    }
}

/// The blocking half: every step here may wait on systemd, so it never runs on the runtime.
fn systemctl_duckmix_blocking(action: &'static str) {
    // FIFO writers can block forever on stop. Restart=always means a bare
    // SIGKILL only respawns duckmix 2s later and steals the card again (peak=1).
    if action == "stop" {
        let _ = std::process::Command::new("timeout")
            .args(["3s", "systemctl", "stop", "duckmix-capture"])
            .status();
        if duckmix_is_active() {
            tracing::warn!("duckmix-capture 仍在跑，SIGKILL 后再 stop（防止 Restart=always）");
            let _ = std::process::Command::new("systemctl")
                .args(["kill", "-s", "SIGKILL", "duckmix-capture"])
                .status();
            let _ = std::process::Command::new("timeout")
                .args(["2s", "systemctl", "stop", "duckmix-capture"])
                .status();
            let _ = std::process::Command::new("systemctl")
                .args(["reset-failed", "duckmix-capture"])
                .status();
        }
        // Let ALSA finish releasing hw:aic3104 before our arecord opens it.
        std::thread::sleep(std::time::Duration::from_millis(150));
        return;
    }
    let _ = std::process::Command::new("systemctl")
        .args([action, "duckmix-capture"])
        .status();
}

fn duckmix_is_active() -> bool {
    std::process::Command::new("systemctl")
        .args(["is-active", "--quiet", "duckmix-capture"])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn publish_expression(
    emotion: &AtomicU8,
    expression_seed: &AtomicU32,
    machine: &mut Machine,
) {
    emotion.store(machine.emotion().code(), Ordering::Relaxed);
    if machine.take_sentence_bump() {
        expression_seed.fetch_add(1, Ordering::Relaxed);
    }
}

async fn conversation(
    toggles: &mut tokio::sync::mpsc::Receiver<()>,
    audio: &mut Audio,
    cfg: &SessionConfig,
    talking: &AtomicBool,
    phase: &AtomicU8,
    emotion: &AtomicU8,
    expression_seed: &AtomicU32,
    keyword_tx: &tokio::sync::mpsc::Sender<String>,
    keywords_live: &Arc<std::sync::RwLock<Vec<KeywordRule>>>,
) -> Result<(), String> {
    let live = keywords_live
        .read()
        .map(|g| g.clone())
        .unwrap_or_else(|_| cfg.keywords.clone());
    let mut machine = Machine::with_keywords(live);
    // The button press that entered this function already means "connect".
    machine.on_press();
    publish_phase(phase, &machine);
    publish_expression(emotion, expression_seed, &mut machine);

    tracing::warn!(url = %cfg.url, "正在连接语音服务器");
    let endpoint = tokio::select! {
        result = timeout(HELLO_TIMEOUT, ota::resolve_endpoint(&cfg.url, &cfg.token, &cfg.client_id_path)) => {
            result.map_err(|_| "OTA / 地址解析 10 秒没有完成".to_owned())?
        }
        Some(()) = toggles.recv() => {
            machine.on_press();
            publish_phase(phase, &machine);
            return Ok(());
        }
    }?;

    let socket = tokio::select! {
        result = timeout(HELLO_TIMEOUT, connect(&endpoint)) => {
            result.map_err(|_| "语音服务器 10 秒没有连上".to_owned())?
        }
        Some(()) = toggles.recv() => {
            machine.on_press();
            publish_phase(phase, &machine);
            return Ok(());
        }
    }?;

    let (mut write, mut read) = socket.split();
    write
        .send(Message::Text(protocol::hello_message().into()))
        .await
        .map_err(|error| format!("hello 没有发出去: {error}"))?;

    let hello = tokio::select! {
        message = timeout(HELLO_TIMEOUT, next_text(&mut read)) => {
            message.map_err(|_| "语音服务器没有回应 hello".to_owned())?
        }
        Some(()) = toggles.recv() => {
            machine.on_press();
            publish_phase(phase, &machine);
            return Ok(());
        }
    }?;
    let value = serde_json::from_str::<serde_json::Value>(&hello)
        .map_err(|error| format!("hello 不是 JSON: {error}"))?;
    let parsed = protocol::parse_server_hello(&value).ok_or("服务器 hello 的 transport 不是 websocket")?;
    tracing::warn!(session = %parsed.session_id, rate = parsed.sample_rate, "语音服务器已接通");
    // OPi AIC3104 is exclusive: aplay 滴滴 before arecord leaves capture at peak=1
    // even after waiting for aplay to exit. Skip beeps; open the mic immediately.
    if uses_opi_pipeline(&cfg.capture_device) {
        tracing::warn!("OPi 独占声卡：跳过接通滴滴，直接开麦");
    } else {
        audio.play_ready_beeps().await;
    }
    apply(
        &mut machine.on_server_hello(parsed),
        &mut write,
        audio,
        talking,
        machine.server_rate(),
        keyword_tx,
    )
    .await?;
    publish_phase(phase, &machine);

    let mut last_rx = tokio::time::Instant::now();
    loop {
        publish_phase(phase, &machine);
        if machine.phase() == Phase::Idle {
            return Ok(());
        }
        let idle_left = IDLE_TIMEOUT.saturating_sub(last_rx.elapsed());
        tokio::select! {
            biased;
            Some(()) = toggles.recv() => {
                match machine.on_press() {
                    Press::Connect => {}
                    Press::HangUp => {
                        tracing::warn!("挂断语音对话");
                        apply(
                            &mut machine.on_disconnected(),
                            &mut write,
                            audio,
                            talking,
                            machine.server_rate(),
                            keyword_tx,
                        )
                        .await
                        .ok();
                        publish_phase(phase, &machine);
                        publish_expression(emotion, expression_seed, &mut machine);
                        return Ok(());
                    }
                }
            }
            incoming = read.next() => {
                last_rx = tokio::time::Instant::now();
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        match serde_json::from_str::<serde_json::Value>(&text) {
                            Ok(value) => {
                                // Pick up console edits mid-call without hanging up.
                                if let Ok(guard) = keywords_live.read() {
                                    machine.set_keywords(guard.clone());
                                }
                                let mut effects = machine.on_json(&value);
                                publish_phase(phase, &machine);
                                publish_expression(emotion, expression_seed, &mut machine);
                                apply(
                                    &mut effects,
                                    &mut write,
                                    audio,
                                    talking,
                                    machine.server_rate(),
                                    keyword_tx,
                                )
                                .await?;
                            }
                            Err(error) => tracing::warn!(%error, "语音服务器发来的文本不是 JSON"),
                        }
                    }
                    Some(Ok(Message::Binary(packet))) if machine.phase() == Phase::Speaking => {
                        // First real TTS frame: release the mic before aplay
                        // (exclusive AIC3104). Empty tts start/stop never gets here.
                        if machine.take_mute_capture_for_tts() {
                            audio.set_capture_wait(false).await;
                        }
                        audio.play(packet.to_vec());
                    }
                    Some(Ok(Message::Binary(_))) => {}
                    Some(Ok(Message::Ping(_) | Message::Pong(_) | Message::Frame(_))) => {}
                    Some(Ok(Message::Close(_))) | None => {
                        tracing::warn!("语音服务器断开了");
                        let mut effects = machine.on_disconnected();
                        apply(
                            &mut effects,
                            &mut write,
                            audio,
                            talking,
                            machine.server_rate(),
                            keyword_tx,
                        )
                        .await
                        .ok();
                        return Ok(());
                    }
                    Some(Err(error)) => {
                        let mut effects = machine.on_disconnected();
                        apply(
                            &mut effects,
                            &mut write,
                            audio,
                            talking,
                            machine.server_rate(),
                            keyword_tx,
                        )
                        .await
                        .ok();
                        return Err(format!("语音连接中断: {error}"));
                    }
                }
            }
            Some(packet) = audio.uplink().recv(), if machine.uplink() => {
                write
                    .send(Message::Binary(packet.into()))
                    .await
                    .map_err(|error| format!("麦克风数据没有发出去: {error}"))?;
            }
            _ = tokio::time::sleep(idle_left) => {
                tracing::warn!("语音服务器 120 秒没有消息，挂断");
                let mut effects = machine.on_disconnected();
                apply(
                    &mut effects,
                    &mut write,
                    audio,
                    talking,
                    machine.server_rate(),
                    keyword_tx,
                )
                .await
                .ok();
                return Ok(());
            }
        }
    }
}

async fn apply(
    effects: &mut Vec<Effect>,
    write: &mut (impl Sink<Message, Error = tokio_tungstenite::tungstenite::Error> + Unpin),
    audio: &mut Audio,
    talking: &AtomicBool,
    sample_rate: u32,
    keyword_tx: &tokio::sync::mpsc::Sender<String>,
) -> Result<(), String> {
    for effect in effects.drain(..) {
        match effect {
            Effect::Send(text) => {
                write
                    .send(Message::Text(text.into()))
                    .await
                    .map_err(|error| format!("消息没有发出去: {error}"))?;
            }
            Effect::Capture(on) => {
                if on {
                    while audio.uplink().try_recv().is_ok() {}
                    // Capture thread Hard-reclocks and keeps the first live arecord
                    // (no separate prepare that opens-then-kills a good pipe).
                    audio.set_capture(true);
                } else {
                    // AIC3104 is exclusive: wait until arecord releases before aplay.
                    audio.set_capture_wait(false).await;
                }
            }
            Effect::Playback(true) => {
                // The beak starts moving with the server's voice, and stays shut until then.
                talking.store(true, Ordering::Relaxed);
                audio.start_playback(sample_rate);
            }
            Effect::Playback(false) => {
                audio.stop_playback().await;
                talking.store(false, Ordering::Relaxed);
            }
            Effect::Keyword(action) => {
                // Drop if the control loop is not draining — never block the call.
                if keyword_tx.try_send(action).is_err() {
                    tracing::debug!("关键词动作队列已满或控制环未接，已忽略");
                }
            }
        }
    }
    Ok(())
}

async fn connect(
    endpoint: &Endpoint,
) -> Result<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
    String,
> {
    use tokio_tungstenite::tungstenite::{client::IntoClientRequest, http::HeaderValue};

    let mut request = endpoint
        .ws_url
        .trim()
        .into_client_request()
        .map_err(|error| format!("语音服务器地址无效: {error}"))?;
    let headers = request.headers_mut();
    headers.insert(
        "Protocol-Version",
        HeaderValue::from_static("1"),
    );
    let device = device_id();
    let client = client_id(std::path::Path::new(&endpoint.client_id_path));
    headers.insert(
        "Device-Id",
        HeaderValue::from_str(&device).map_err(|_| "设备 MAC 不能放进请求头".to_owned())?,
    );
    headers.insert(
        "Client-Id",
        HeaderValue::from_str(&client).map_err(|_| "客户端编号不能放进请求头".to_owned())?,
    );
    if let Some(authorization) = authorization_value(&endpoint.token) {
        headers.insert(
            "Authorization",
            HeaderValue::from_str(&authorization).map_err(|_| "令牌不能放进请求头".to_owned())?,
        );
    }
    connect_async(request)
        .await
        .map(|(socket, _)| socket)
        .map_err(|error| format!("连不上语音服务器: {error}"))
}

async fn next_text(
    read: &mut (impl Stream<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin),
) -> Result<String, String> {
    loop {
        match read.next().await {
            Some(Ok(Message::Text(text))) => return Ok(text.to_string()),
            Some(Ok(Message::Ping(_) | Message::Pong(_) | Message::Frame(_))) => {}
            Some(Ok(Message::Binary(_))) => {}
            Some(Ok(Message::Close(frame))) => {
                return Err(format!("服务器在 hello 之前关闭了连接: {frame:?}"));
            }
            Some(Err(error)) => return Err(format!("读取 hello 失败: {error}")),
            None => return Err("服务器在 hello 之前断开了".to_owned()),
        }
    }
}
