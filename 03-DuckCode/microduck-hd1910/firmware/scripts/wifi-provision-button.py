#!/usr/bin/env python3
"""Boot-time Wi-Fi provision button.

Header pin 7 on the Radxa ZERO 3W is reserved for this. That pin is GPIO3_C4
(Linux gpio 116, line 20 on the gpiochip labelled gpio3). Wire a momentary
button between pin 7 and pin 9 (GND). Pins 3 and 5 are the codec I2C bus, and
pins 8 and 10 are UART2, which this board uses as the servo port — neither
pair can be the button.

The line is active-low. Each sample asks the kernel for a pull-up, so an
unconnected pin reads released and does not open the hotspot. A reader that
cannot request that pull-up refuses to decide, because a floating pin would
otherwise look like a press and take the robot off its network.

The window is the first 5 seconds of uptime. A press in that window — or a
button still held when this process starts late — opens the same hotspot the
first-boot page uses (Microduck / 12345678, http://10.42.0.1:8088) and
speaks a prompt. The hotspot profile is marked not to reconnect on later boots.
"""

from __future__ import annotations

import glob
import html
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

HEADER_PIN = 7
GPIO_BANK_LABEL = "gpio3"
GPIO_LINE = 20
WINDOW_S = 5.0
# Two lows, 20 ms apart: a tap counts, one floating sample does not.
DEBOUNCE = 2
SAMPLE_S = 0.02
POLL_CAP = 400

SSID = "Microduck"
AP_PSK = "12345678"
HOTSPOT_CON = "microduck-provision"
PORT = 8088
PROVISION_S = 600
# wlan0 on the ZERO 3W. Another board sets WIFI_PROVISION_WLAN in
# /etc/wifi-provision.env (see install-wifi-provision.sh).
WLAN = os.environ.get("WIFI_PROVISION_WLAN", "wlan0")
PHRASE = "进入配网模式。请连接热点，密码一二三四五六七八。然后打开十点四十二点零点一，端口八零八八。"

_stop = False


def next_action(uptime_s, pressed, streak, samples, window_s=WINDOW_S, need=DEBOUNCE):
    """Decide what one sample means.

    Returns ``(action, streak, samples)`` where action is ``poll``, ``enter``
    or ``stop``. Inside the boot window a released button keeps the watch
    open. After the window only a button that is still down can finish the
    debounce; a released one means the chance has passed.
    """
    samples += 1
    streak = streak + 1 if pressed else 0
    if streak >= need:
        return "enter", streak, samples
    if uptime_s <= window_s:
        return "poll", streak, samples
    if pressed:
        return "poll", streak, samples
    return "stop", streak, samples


def parse_gpioget(text):
    """Line level from ``gpioget`` stdout. 0 is electrical low."""
    raw = text.strip().lower()
    if not raw:
        raise ValueError("empty gpioget output")
    # "inactive" contains "active"; the longer word has to win.
    if "inactive" in raw:
        return 0
    if "active" in raw:
        return 1
    for token in raw.replace("=", " ").replace(":", " ").split():
        if token in ("0", "1"):
            return int(token)
    raise ValueError("unrecognised gpioget output: %r" % text.strip())


def chip_from_detect(text):
    """gpiochip name whose label is ``gpio3``, from ``gpiodetect`` output."""
    for line in text.splitlines():
        if "[%s]" % GPIO_BANK_LABEL in line:
            name = line.split()[0]
            if name.startswith("gpiochip"):
                return name
    return None


def uptime_s():
    with open("/proc/uptime", "r", encoding="ascii") as handle:
        return float(handle.read().split()[0])


def log(message):
    print("wifi-provision: %s" % message, file=sys.stderr, flush=True)


def _run(args, timeout, check=False):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def find_chip():
    override = os.environ.get("WIFI_PROVISION_GPIO_CHIP")
    if override:
        return override
    if shutil.which("gpiodetect") is None:
        return None
    found = _run(["gpiodetect"], 5)
    return chip_from_detect(found.stdout)


def gpioget_args(chip, line):
    """Argument lists to try, bias first. A no-bias read is not offered."""
    line_s = str(line)
    return [
        ["gpioget", "--bias=pull-up", chip, line_s],
        ["gpioget", "-c", chip, "-B", "pull-up", line_s],
        ["gpioget", "-B", "pull-up", chip, line_s],
    ]


class GpioReader:
    """One working ``gpioget`` invocation, chosen on the first successful read."""

    def __init__(self, chip, line):
        self.chip = chip
        self.line = line
        self.command = None

    def level(self):
        commands = [self.command] if self.command else gpioget_args(self.chip, self.line)
        last = "gpioget failed"
        for command in commands:
            if command is None or shutil.which(command[0]) is None:
                last = "gpioget is not installed"
                continue
            try:
                found = _run(command, 2)
            except (OSError, subprocess.TimeoutExpired) as exc:
                last = str(exc)
                continue
            if found.returncode != 0:
                last = (found.stderr or found.stdout or "gpioget failed").strip()
                continue
            try:
                level = parse_gpioget(found.stdout)
            except ValueError as exc:
                last = str(exc)
                continue
            self.command = command
            return level
        raise RuntimeError(last)


def watch_button(reader, uptime=uptime_s, sleep=time.sleep):
    """True when the button was pressed inside the boot window."""
    streak = 0
    samples = 0
    while samples < POLL_CAP:
        try:
            now = uptime()
        except (OSError, ValueError) as exc:
            log("no uptime (%s); not entering provision mode" % exc)
            return False
        try:
            level = reader.level()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            # The gpiochip can show up a moment after userspace. Keep trying
            # until the boot window has passed, then give up rather than
            # treating a missing pin as a press.
            if now > WINDOW_S:
                log("button unreadable (%s); not entering provision mode" % exc)
                return False
            sleep(SAMPLE_S)
            continue
        action, streak, samples = next_action(now, level == 0, streak, samples)
        if action == "enter":
            return True
        if action == "stop":
            return False
        sleep(SAMPLE_S)
    log("button watch exceeded its sample cap")
    return False


def wait_wlan(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not _stop:
        if shutil.which("nmcli") is None:
            time.sleep(1)
            continue
        found = _run(["nmcli", "-t", "-f", "DEVICE", "device", "status"], 10)
        if any(line.strip() == WLAN for line in found.stdout.splitlines()):
            return True
        time.sleep(1)
    return False


def scan_networks():
    _run(["nmcli", "radio", "wifi", "on"], 10)
    _run(["nmcli", "device", "wifi", "rescan", "ifname", WLAN], 20)
    time.sleep(3)
    found = _run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", WLAN],
        15,
    )
    rows = []
    seen = set()
    for line in found.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ssid = parts[0].replace("\\:", ":").strip()
        if not ssid or ssid in seen or ssid == SSID:
            continue
        seen.add(ssid)
        signal = parts[1]
        security = parts[2] if len(parts) > 2 else ""
        rows.append((ssid, signal, security))
    return rows


def start_hotspot():
    _run(["nmcli", "radio", "wifi", "on"], 10)
    _run(["nmcli", "connection", "down", HOTSPOT_CON], 20)
    _run(["nmcli", "connection", "delete", HOTSPOT_CON], 20)
    made = _run(
        [
            "nmcli",
            "device",
            "wifi",
            "hotspot",
            "ifname",
            WLAN,
            "con-name",
            HOTSPOT_CON,
            "ssid",
            SSID,
            "password",
            AP_PSK,
        ],
        40,
    )
    if made.returncode != 0:
        detail = (made.stderr or made.stdout or "hotspot failed").strip()
        raise RuntimeError(detail)
    # A leftover autoconnect would open this known-password hotspot on every
    # later boot, which is the opposite of a button. Some NetworkManager
    # versions name the profile Hotspot and ignore con-name; disarm both.
    for name in (HOTSPOT_CON, "Hotspot"):
        mode = _run(["nmcli", "-g", "802-11-wireless.mode", "connection", "show", name], 15)
        if mode.returncode == 0 and "ap" in mode.stdout.lower():
            _run(
                ["nmcli", "connection", "modify", name, "connection.autoconnect", "no"],
                15,
            )


def stop_hotspot():
    names = [HOTSPOT_CON]
    active = _run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"], 15)
    for line in active.stdout.splitlines():
        name = line.strip()
        if name and name not in names:
            ssid = _run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name], 10)
            mode = _run(["nmcli", "-g", "802-11-wireless.mode", "connection", "show", name], 10)
            if ssid.stdout.strip() == SSID and "ap" in mode.stdout.lower():
                names.append(name)
    for name in names:
        _run(["nmcli", "connection", "down", name], 20)
        _run(["nmcli", "connection", "modify", name, "connection.autoconnect", "no"], 15)


def redirect_http(install):
    if shutil.which("iptables") is None:
        return
    rule = [
        "iptables",
        "-t",
        "nat",
        "-i",
        WLAN,
        "-p",
        "tcp",
        "--dport",
        "80",
        "-j",
        "REDIRECT",
        "--to-ports",
        str(PORT),
    ]
    if install:
        have = _run(rule[:3] + ["-C", "PREROUTING"] + rule[3:], 10)
        if have.returncode != 0:
            _run(rule[:3] + ["-A", "PREROUTING"] + rule[3:], 10)
    else:
        _run(rule[:3] + ["-D", "PREROUTING"] + rule[3:], 10)


def redact(text, secret):
    if secret:
        return text.replace(secret, "********")
    return text


def connect_home(ssid, psk):
    stop_hotspot()
    joined = subprocess.run(
        [
            "nmcli",
            "--wait",
            "45",
            "device",
            "wifi",
            "connect",
            ssid,
            "password",
            psk,
            "ifname",
            WLAN,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if joined.returncode != 0:
        detail = redact((joined.stderr or joined.stdout or "连接失败").strip(), psk)
        try:
            start_hotspot()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            detail = "%s；热点也没有重新打开：%s" % (detail, exc)
        return False, detail
    return True, ""


def _play(wav, device):
    played = subprocess.run(
        ["aplay", "-D", device, "-q", wav],
        timeout=12,
        check=False,
    )
    if played.returncode == 0:
        return True
    fallback = subprocess.run(["aplay", "-q", wav], timeout=12, check=False)
    return fallback.returncode == 0


def _espeak(phrase, device):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe is None or shutil.which("aplay") is None:
        return False
    wav = "/tmp/wifi-provision-prompt.wav"
    for voice in ("cmn", "zh", None):
        args = [exe]
        if voice:
            args.extend(["-v", voice])
        args.extend(["-w", wav, phrase])
        try:
            made = subprocess.run(args, timeout=25, check=False, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if made.returncode != 0:
            continue
        return _play(wav, device)
    return False


def announce():
    """Duck greet, then a spoken sentence, once the codec is up."""
    device = os.environ.get("WIFI_PROVISION_ALSA", "plughw:aic3104")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and not _stop:
        try:
            cards = open("/proc/asound/cards", "r", encoding="utf-8", errors="replace").read()
        except OSError:
            cards = ""
        if "aic3104" in cards.lower() or "tlv320" in cards.lower():
            break
        time.sleep(0.5)
    bank = os.environ.get("WIFI_PROVISION_BANK", "/var/lib/robot/sounds")
    wavs = sorted(glob.glob(os.path.join(bank, "greet", "*.wav")))
    if wavs and shutil.which("aplay"):
        _play(wavs[0], device)
    if not _espeak(PHRASE, device):
        log("spoken prompt unavailable; page is http://10.42.0.1:%s" % PORT)


_MARK = (
    '<svg class="brand-mark" viewBox="0 0 64 64" aria-hidden="true">'
    '<rect class="mark-paper" x="4" y="6" width="56" height="50" rx="16"/>'
    '<path class="mark-drip" d="M18 54c1 7 4 11 2 16-1-6-3-10-2-16zm12 0c2 8 5 13 2 18-2-6-4-11-2-18zm14 0c1 6 3 9 1 14-1-5-2-8-1-14z"/>'
    '<rect class="mark-ink" x="16" y="24" width="32" height="22" rx="7"/>'
    '<circle class="mark-spray" cx="27" cy="35" r="3.4"/>'
    '<circle class="mark-spray" cx="37" cy="35" r="3.4"/>'
    '<rect class="mark-ink" x="29" y="14" width="6" height="11" rx="3"/>'
    '<circle class="mark-ink" cx="32" cy="12" r="3.5"/>'
    '<path class="mark-spray" d="M50 16l1.4 3.2 3.4.3-2.6 2.2.8 3.4-3-1.8-3 1.8.8-3.4-2.6-2.2 3.4-.3z"/>'
    "</svg>"
)


def page(rows, message):
    """Phone page in the console's BoBo sticker chrome. The hotspot name is Microduck."""
    nets = []
    for ssid, signal, _security in rows:
        nets.append(
            '<label class="net"><input type="radio" name="ssid" value="%s">'
            "<span>%s</span><small>信号 %s</small></label>"
            % (
                html.escape(ssid, quote=True),
                html.escape(ssid),
                html.escape(signal or "—"),
            )
        )
    if nets:
        choice = '<div class="nets" role="radiogroup" aria-label="附近的网络">%s</div>' % "".join(nets)
    else:
        choice = '<p class="empty">没有扫到网络，请直接填写名称。</p>'
    if message:
        kind = "ok" if message.startswith("已连上") else "warn"
        note = '<p class="banner %s" role="status">%s</p>' % (kind, html.escape(message))
    else:
        note = ""
    html_doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>MicroDuck · 配置 Wi-Fi</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#0c0c0c;color:#f4f1ea;
 font:15px/1.55 "Microsoft YaHei",Arial,sans-serif;
 background-image:
  radial-gradient(circle at 8% 12%,#ffffff22 0 10px,transparent 12px),
  radial-gradient(circle at 92% 80%,#ffffff18 0 18px,transparent 20px),
  radial-gradient(circle at 18% 92%,#e8ff4722 0 9px,transparent 11px)}
.wrap{max-width:32rem;margin:0 auto;padding:22px 16px 32px}
.brand{display:flex;align-items:flex-start;gap:12px}
.brand-mark{width:52px;height:52px;flex:none}
.mark-paper{fill:#f7f7f7}.mark-ink{fill:#141414}.mark-spray{fill:#e8ff47}.mark-drip{fill:#8a8a8a}
.brand-lockup{display:block;font-family:Arial Black,"Microsoft YaHei",sans-serif;font-size:20px;
 font-weight:900;letter-spacing:-.04em;line-height:1;color:#fff;text-shadow:3px 3px 0 #7a7a7a}
.brand-sub{display:block;margin-top:6px;font-size:13px;font-weight:800}
h1{margin:22px 0 8px;font-family:Arial Black,"Microsoft YaHei",sans-serif;font-size:28px;
 font-weight:900;letter-spacing:-.04em;color:#fff;text-shadow:4px 4px 0 #6d6d6d}
.lead{margin:0 0 8px;color:#f4f1ea}
.lead.hint{margin:0 0 16px;color:#bdbdbd}
.chip{display:inline-block;margin:0 6px 0 0;padding:2px 8px;border-radius:999px;
 border:1px solid #f4f1ea55;color:#e8ff47;font-weight:800}
.panel{background:#161616;border:3px solid #f4f1ea;border-radius:18px;
 box-shadow:6px 6px 0 #5a5a5a;padding:16px}
.banner{margin:0 0 14px;padding:11px 14px;border-radius:12px;font-size:14px}
.banner.warn{border:2px solid #ffb4a8;background:#2c201c;color:#ffd0c8}
.banner.ok{border:2px solid #e8ff47;background:#1c2414;color:#e8ff47}
.nets{display:grid;gap:8px;margin-bottom:14px}
.net{display:flex;align-items:center;gap:10px;padding:10px 12px;border:2px solid #f4f1ea;
 border-radius:14px;background:#101010}
.net:has(input:checked){border-color:#e8ff47;box-shadow:3px 3px 0 #5c5c5c}
.net input{accent-color:#e8ff47;width:18px;height:18px;flex:none}
.net span{font-weight:700;overflow-wrap:anywhere}
.net small{margin-left:auto;color:#bdbdbd;white-space:nowrap}
.empty{margin:0 0 14px;color:#bdbdbd}
label.field{display:block;margin:12px 0;font-size:13px;font-weight:700;color:#f4f1ea}
input[type=text],input[type=password]{display:block;width:100%;margin-top:6px;padding:10px 12px;
 background:#101010;color:#f4f1ea;border:2px solid #f4f1ea;border-radius:10px;font:inherit}
button{display:block;width:100%;margin-top:8px;padding:12px 16px;border:2px solid #141414;
 border-radius:999px;background:#e8ff47;color:#141414;font:inherit;font-weight:800;cursor:pointer;
 box-shadow:3px 3px 0 #5c5c5c}
button:hover{background:#f4ff8a}
footer{margin-top:18px;color:#9a9a9a;font-size:11px;letter-spacing:.14em}
</style></head><body>
<div class="wrap">
<div class="brand">@@MARK@@<span><span class="brand-lockup">MicroDuck</span><span class="brand-sub">鸭子配网</span></span></div>
<h1>配置 Wi-Fi</h1>
<p class="lead">热点 <span class="chip">@@SSID@@</span>密码 <span class="chip">@@PSK@@</span></p>
<p class="lead hint">提交后手机会离开这个热点。</p>
<section class="panel">@@NOTE@@
<form method="post" action="/connect">
@@CHOICE@@
<label class="field">网络名称<input type="text" name="ssid_manual" autocomplete="off" placeholder="上面没有就自己填"></label>
<label class="field">密码<input type="password" name="psk" autocomplete="off"></label>
<button type="submit">连接</button>
</form></section>
<footer>BOBOMAKER / MICRODUCK</footer>
</div></body></html>"""
    return (
        html_doc.replace("@@MARK@@", _MARK)
        .replace("@@SSID@@", html.escape(SSID))
        .replace("@@PSK@@", html.escape(AP_PSK))
        .replace("@@NOTE@@", note)
        .replace("@@CHOICE@@", choice)
    )


class Portal:
    def __init__(self, rows):
        self.rows = rows
        self.message = ""
        self.done = False
        self.lock = threading.Lock()


def make_handler(portal):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, code, body):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            with portal.lock:
                body = page(portal.rows, portal.message)
            self._send(200, body)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/connect":
                self._send(404, page(portal.rows, "未知地址"))
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(min(length, 4096)).decode("utf-8", "replace")
            form = parse_qs(raw, keep_blank_values=True)
            manual = (form.get("ssid_manual") or [""])[0].strip()
            chosen = (form.get("ssid") or [""])[0].strip()
            ssid = manual or chosen
            psk = (form.get("psk") or [""])[0]
            if not ssid:
                with portal.lock:
                    portal.message = "请填写网络名称。"
                    body = page(portal.rows, portal.message)
                self._send(400, body)
                return
            log("joining a network named %s" % ssid)
            try:
                ok, detail = connect_home(ssid, psk)
            except (OSError, subprocess.TimeoutExpired) as exc:
                ok, detail = False, str(exc)
            with portal.lock:
                if ok:
                    portal.done = True
                    portal.message = "已连上 %s。热点会关闭，请把手机连回这个网络。" % ssid
                else:
                    portal.message = detail or "没有连上，热点已重新打开。"
                body = page(portal.rows, portal.message)
            self._send(200 if ok else 400, body)

    return Handler


def serve(portal):
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(portal))
    except OSError as exc:
        log("cannot listen on port %s (%s)" % (PORT, exc))
        return
    httpd.timeout = 1
    deadline = time.monotonic() + PROVISION_S
    log("provision page on http://10.42.0.1:%s for %s minutes" % (PORT, PROVISION_S // 60))
    while time.monotonic() < deadline and not portal.done and not _stop:
        httpd.handle_request()
    httpd.server_close()
    if not portal.done:
        log("provision window ended without a new network")


def _on_signal(signum, _frame):
    global _stop
    _stop = True
    log("stopping on signal %s" % signum)


def provision():
    log("button pressed; waiting for wlan0")
    threading.Thread(target=announce, name="wifi-provision-voice", daemon=True).start()
    if not wait_wlan():
        log("wlan0 did not appear; provision mode aborted")
        return 1
    try:
        rows = scan_networks()
    except (OSError, subprocess.TimeoutExpired) as exc:
        log("scan failed (%s); the page will take a typed name" % exc)
        rows = []
    try:
        start_hotspot()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        log("hotspot failed: %s" % exc)
        return 1
    redirect_http(True)
    try:
        serve(Portal(rows))
    finally:
        redirect_http(False)
        stop_hotspot()
    return 0


def main(argv):
    if "--check" in argv:
        chip = find_chip()
        line = int(os.environ.get("WIFI_PROVISION_GPIO_LINE", str(GPIO_LINE)))
        if not chip:
            log("no gpiochip labelled %s" % GPIO_BANK_LABEL)
            return 1
        try:
            level = GpioReader(chip, line).level()
        except (OSError, RuntimeError) as exc:
            log("%s" % exc)
            return 1
        log(
            "pin %s %s line %s level %s (%s)"
            % (HEADER_PIN, chip, line, level, "pressed" if level == 0 else "released")
        )
        return 0

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        boot = uptime_s()
    except (OSError, ValueError) as exc:
        log("no uptime (%s); not entering provision mode" % exc)
        return 0
    if boot > WINDOW_S + 30:
        # A manual restart long after boot is not the power-on window. Holding
        # the button still counts, and next_action allows that. A late start
        # with the button released must leave the network alone — the watch
        # does that in one sample. Nothing extra to refuse here.
        pass
    chip = find_chip()
    line = int(os.environ.get("WIFI_PROVISION_GPIO_LINE", str(GPIO_LINE)))
    if not chip:
        log("no gpiochip labelled %s (install gpiod); skipping" % GPIO_BANK_LABEL)
        return 0
    if watch_button(GpioReader(chip, line)):
        log("provision mode")
        return provision()
    log("button not pressed in the first %.0fs" % WINDOW_S)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
