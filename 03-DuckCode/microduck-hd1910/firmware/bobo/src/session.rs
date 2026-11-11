//! One voice call: connect, hello, then listen until the button hangs up.
//!
//! The button is edge-triggered. The first press enters here; a later press aborts a
//! sentence or closes the socket, which is the reference firmware's boot button.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use futures_util::{Sink, SinkExt, Stream, StreamExt};
use tokio::time::timeout;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use crate::audio::Audio;
use crate::identity::{client_id, device_id};
use crate::machine::{Effect, Machine, Phase, Press};
use crate::protocol::{self, authorization_value};

const HELLO_TIMEOUT: Duration = Duration::from_secs(10);
const IDLE_TIMEOUT: Duration = Duration::from_secs(120);

pub struct SessionConfig {
    pub enabled: bool,
    pub url: String,
    pub token: String,
    pub client_id_path: String,
    pub capture_device: String,
    pub playback_device: String,
}

/// Wait for button presses and run one call at a time.
pub async fn run(
    mut toggles: tokio::sync::mpsc::Receiver<()>,
    speaker: Arc<AtomicBool>,
    talking: Arc<AtomicBool>,
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
        if !(url.starts_with("ws://") || url.starts_with("wss://")) {
            tracing::warn!(%url, "语音服务器地址要以 ws:// 或 wss:// 开头");
            continue;
        }
        speaker.store(true, Ordering::Relaxed);
        let mut audio = Audio::start(cfg.capture_device.clone(), cfg.playback_device.clone());
        if let Err(error) = conversation(&mut toggles, &mut audio, &cfg, &talking).await {
            tracing::warn!(%error, "语音对话没有接通");
        }
        audio.quiet();
        talking.store(false, Ordering::Relaxed);
        speaker.store(false, Ordering::Relaxed);
        tracing::warn!("语音对话已结束");
    }
}

async fn conversation(
    toggles: &mut tokio::sync::mpsc::Receiver<()>,
    audio: &mut Audio,
    cfg: &SessionConfig,
    talking: &AtomicBool,
) -> Result<(), String> {
    let mut machine = Machine::new();
    // The button press that entered this function already means "connect".
    machine.on_press();

    tracing::warn!(url = %cfg.url, "正在连接语音服务器");
    let socket = tokio::select! {
        result = timeout(HELLO_TIMEOUT, connect(cfg)) => {
            result.map_err(|_| "语音服务器 10 秒没有连上".to_owned())?
        }
        Some(()) = toggles.recv() => {
            machine.on_press();
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
            return Ok(());
        }
    }?;
    let value = serde_json::from_str::<serde_json::Value>(&hello)
        .map_err(|error| format!("hello 不是 JSON: {error}"))?;
    let parsed = protocol::parse_server_hello(&value).ok_or("服务器 hello 的 transport 不是 websocket")?;
    tracing::warn!(session = %parsed.session_id, rate = parsed.sample_rate, "语音服务器已接通");
    apply(
        &mut machine.on_server_hello(parsed),
        &mut write,
        audio,
        talking,
        machine.server_rate(),
    )
    .await?;

    let mut last_rx = tokio::time::Instant::now();
    loop {
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
                        apply(
                            &mut machine.on_disconnected(),
                            &mut write,
                            audio,
                            talking,
                            machine.server_rate(),
                        )
                        .await
                        .ok();
                        return Ok(());
                    }
                    Press::Abort(mut effects) => {
                        tracing::warn!("打断当前这句话");
                        apply(&mut effects, &mut write, audio, talking, machine.server_rate()).await?;
                    }
                }
            }
            incoming = read.next() => {
                last_rx = tokio::time::Instant::now();
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        match serde_json::from_str::<serde_json::Value>(&text) {
                            Ok(value) => {
                                let mut effects = machine.on_json(&value);
                                apply(
                                    &mut effects,
                                    &mut write,
                                    audio,
                                    talking,
                                    machine.server_rate(),
                                )
                                .await?;
                            }
                            Err(error) => tracing::warn!(%error, "语音服务器发来的文本不是 JSON"),
                        }
                    }
                    Some(Ok(Message::Binary(packet))) if machine.phase() == Phase::Speaking => {
                        audio.play(packet.to_vec());
                    }
                    Some(Ok(Message::Binary(_))) => {}
                    Some(Ok(Message::Ping(_) | Message::Pong(_) | Message::Frame(_))) => {}
                    Some(Ok(Message::Close(_))) | None => {
                        tracing::warn!("语音服务器断开了");
                        let mut effects = machine.on_disconnected();
                        apply(&mut effects, &mut write, audio, talking, machine.server_rate())
                            .await
                            .ok();
                        return Ok(());
                    }
                    Some(Err(error)) => {
                        let mut effects = machine.on_disconnected();
                        apply(&mut effects, &mut write, audio, talking, machine.server_rate())
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
                apply(&mut effects, &mut write, audio, talking, machine.server_rate())
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
                }
                audio.set_capture(on);
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
        }
    }
    Ok(())
}

async fn connect(
    cfg: &SessionConfig,
) -> Result<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
    String,
> {
    use tokio_tungstenite::tungstenite::{client::IntoClientRequest, http::HeaderValue};

    let mut request = cfg
        .url
        .trim()
        .into_client_request()
        .map_err(|error| format!("语音服务器地址无效: {error}"))?;
    let headers = request.headers_mut();
    headers.insert(
        "Protocol-Version",
        HeaderValue::from_static("1"),
    );
    let device = device_id();
    let client = client_id(std::path::Path::new(&cfg.client_id_path));
    headers.insert(
        "Device-Id",
        HeaderValue::from_str(&device).map_err(|_| "设备 MAC 不能放进请求头".to_owned())?,
    );
    headers.insert(
        "Client-Id",
        HeaderValue::from_str(&client).map_err(|_| "客户端编号不能放进请求头".to_owned())?,
    );
    if let Some(authorization) = authorization_value(&cfg.token) {
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
