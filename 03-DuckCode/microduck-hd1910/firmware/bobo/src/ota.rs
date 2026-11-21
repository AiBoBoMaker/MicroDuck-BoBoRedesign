//! OTA check-in before a voice WebSocket, matching `cankao/py-xiaozhi-main` `Ota`.
//!
//! The duck posts device identity to an HTTP(S) OTA URL; the JSON reply names the
//! websocket endpoint (and optionally a token). Direct `ws://` / `wss://` URLs skip this.

use serde_json::Value;

use crate::identity::{client_id, device_id};
use crate::protocol::authorization_value;

const APP_NAME: &str = "microduck";
const BOARD_TYPE: &str = "microduck-opi";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone)]
pub struct Endpoint {
    pub ws_url: String,
    pub token: String,
    pub client_id_path: String,
}

/// Resolve `[bobo] url` into a websocket endpoint.
///
/// - `ws://` / `wss://` — used as-is, with the configured token.
/// - `http://` / `https://` — treated as OTA (py-xiaozhi `OTA_VERSION_URL`).
pub async fn resolve_endpoint(url: &str, token: &str, client_id_path: &str) -> Result<Endpoint, String> {
    let url = url.trim();
    if url.starts_with("ws://") || url.starts_with("wss://") {
        return Ok(Endpoint {
            ws_url: url.to_owned(),
            token: token.to_owned(),
            client_id_path: client_id_path.to_owned(),
        });
    }
    if url.starts_with("http://") || url.starts_with("https://") {
        return fetch_from_ota(url, token, client_id_path).await;
    }
    Err("语音服务器地址要以 ws://、wss:// 或 OTA 的 http(s):// 开头".to_owned())
}

async fn fetch_from_ota(ota_url: &str, token: &str, client_id_path: &str) -> Result<Endpoint, String> {
    let device = device_id();
    let client = client_id(std::path::Path::new(client_id_path));
    let local_ip = local_ip().unwrap_or_else(|| "127.0.0.1".to_owned());

    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert("Device-Id", header(&device)?);
    headers.insert("Client-Id", header(&client)?);
    headers.insert(
        reqwest::header::CONTENT_TYPE,
        header("application/json")?,
    );
    headers.insert(
        reqwest::header::USER_AGENT,
        header(&format!("{BOARD_TYPE}/{APP_NAME}-{APP_VERSION}"))?,
    );
    headers.insert(
        reqwest::header::ACCEPT_LANGUAGE,
        header("zh-CN")?,
    );
    if let Some(authorization) = authorization_value(token) {
        headers.insert(reqwest::header::AUTHORIZATION, header(&authorization)?);
    }

    let payload = serde_json::json!({
        "application": {
            "version": APP_VERSION,
            "elf_sha256": client,
        },
        "board": {
            "type": BOARD_TYPE,
            "name": APP_NAME,
            "ip": local_ip,
            "mac": device,
        },
    });

    tracing::warn!(%ota_url, %device, "正在向 OTA 索取语音服务器地址");
    let response = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|error| format!("无法创建 OTA 客户端: {error}"))?
        .post(ota_url)
        .headers(headers)
        .json(&payload)
        .send()
        .await
        .map_err(|error| format!("OTA 请求失败: {error}"))?;

    let status = response.status();
    if !status.is_success() {
        return Err(format!("OTA 服务器返回 HTTP {status}"));
    }

    let body = response
        .text()
        .await
        .map_err(|error| format!("OTA 响应读不出来: {error}"))?;
    let mut endpoint = parse_ota_body(&body, token)?;
    endpoint.client_id_path = client_id_path.to_owned();
    Ok(endpoint)
}

fn parse_ota_body(body: &str, fallback_token: &str) -> Result<Endpoint, String> {
    let value: Value = serde_json::from_str(body).map_err(|error| {
        format!("OTA 响应不是 JSON（需要 websocket.url）: {error}")
    })?;
    let websocket = value
        .get("websocket")
        .ok_or_else(|| "OTA 响应里没有 websocket".to_owned())?;
    let ws_url = websocket
        .get("url")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|url| !url.is_empty())
        .ok_or_else(|| "OTA 响应里没有 websocket.url".to_owned())?
        .to_owned();
    if !(ws_url.starts_with("ws://") || ws_url.starts_with("wss://")) {
        return Err(format!("OTA 下发的地址不是 websocket: {ws_url}"));
    }
    let ota_token = websocket
        .get("token")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|token| !token.is_empty())
        .unwrap_or("");
    let token = if ota_token.is_empty() {
        fallback_token.to_owned()
    } else {
        ota_token.to_owned()
    };
    tracing::warn!(%ws_url, "OTA 已下发语音服务器地址");
    Ok(Endpoint {
        ws_url,
        token,
        client_id_path: String::new(),
    })
}

fn header(value: &str) -> Result<reqwest::header::HeaderValue, String> {
    reqwest::header::HeaderValue::from_str(value)
        .map_err(|_| format!("请求头值无效: {value}"))
}

fn local_ip() -> Option<String> {
    let socket = std::net::UdpSocket::bind("0.0.0.0:0").ok()?;
    socket.connect("8.8.8.8:80").ok()?;
    Some(socket.local_addr().ok()?.ip().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ota_json_yields_websocket_and_token() {
        let body = r#"{
            "websocket": {"url": "ws://114.242.62.141:8899/xiaozhi/v1/", "token": "abc"}
        }"#;
        let endpoint = parse_ota_body(body, "fallback").unwrap();
        assert_eq!(endpoint.ws_url, "ws://114.242.62.141:8899/xiaozhi/v1/");
        assert_eq!(endpoint.token, "abc");
    }

    #[test]
    fn empty_ota_token_keeps_configured_token() {
        let body = r#"{"websocket": {"url": "wss://example/v1/", "token": ""}}"#;
        let endpoint = parse_ota_body(body, "kept").unwrap();
        assert_eq!(endpoint.token, "kept");
    }

    #[tokio::test]
    async fn ws_url_skips_ota() {
        let endpoint = resolve_endpoint("ws://direct/v1/", "t", "/tmp/unused-bobo-id")
            .await
            .unwrap();
        assert_eq!(endpoint.ws_url, "ws://direct/v1/");
        assert_eq!(endpoint.token, "t");
    }
}
