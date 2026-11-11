"""Scan the computer's own private IPv4 /24s for SSH, matching the phone console."""
import os
import re
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

# Same skips and preferences as console-apk/lib/lan_scan.dart, plus the
# virtual adapters a Windows PC commonly adds beside the real LAN.
_SKIP = re.compile(
    r"^(lo|dummy|rmnet|ccmni|pdp|tun|tap|ipsec|ppp|wwan|sit|gre|ifb|teql|rev_rmnet|wifi-aware|clat|epdg)"
    r"|loopback|vethernet|hyper-?v|wsl|vmware|virtualbox|vbox|docker|bluetooth|isatap|teredo|npcap|virbr|tailscale|zerotier",
    re.I,
)
_REFUSED = re.compile(r"refused|拒绝", re.I)
PROBE_TIMEOUT = 0.45
HOST_TIMEOUT = 0.7
WORKERS = 32
_JOBS = threading.Lock()
_job = None


def parse_ipv4(text):
    match = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", str(text).strip())
    if not match:
        return None
    parts = [int(part) for part in match.groups()]
    if any(part > 255 for part in parts):
        return None
    return ".".join(str(part) for part in parts)


def is_private_ipv4(ip):
    """Same three ranges as the phone scanner: 10/8, 172.16/12, 192.168/16."""
    try:
        parts = [int(part) for part in ip.split(".")]
    except ValueError:
        return False
    if len(parts) != 4 or any(part > 255 for part in parts):
        return False
    if parts[0] == 10 or (parts[0] == 192 and parts[1] == 168):
        return True
    return parts[0] == 172 and 16 <= parts[1] <= 31


def is_skipped_interface(name):
    return bool(_SKIP.search(name or ""))


def select_subnets(interfaces):
    """Keep every private /24 on a real adapter. Cellular, VPN and virtual names are skipped."""
    chosen = []
    for name, raw in interfaces:
        if is_skipped_interface(name):
            continue
        ip = parse_ipv4(raw)
        if not ip or not is_private_ipv4(ip):
            continue
        chosen.append({"name": name, "self": ip, "prefix": ip.rsplit(".", 1)[0]})
    grouped = {}
    for item in chosen:
        grouped.setdefault(item["prefix"], {"prefix": item["prefix"], "name": item["name"], "selves": []})
        if item["self"] not in grouped[item["prefix"]]["selves"]:
            grouped[item["prefix"]]["selves"].append(item["self"])
    return list(grouped.values())


def hosts_for(subnet):
    selves = set(subnet["selves"])
    return [f"{subnet['prefix']}.{host}" for host in range(1, 255) if f"{subnet['prefix']}.{host}" not in selves]


def _refused(exc):
    if isinstance(exc, ConnectionRefusedError):
        return True
    for code in (getattr(exc, "winerror", None), getattr(exc, "errno", None)):
        if code in (111, 10061, 61):
            return True
    return bool(_REFUSED.search(str(exc)))


def probe_port(ip, port, timeout=PROBE_TIMEOUT):
    """Return open, refused, or closed. A refused port still means the host is up."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, int(port)))
        return "open"
    except OSError as exc:
        return "refused" if _refused(exc) else "closed"
    finally:
        sock.close()


def _probe_host(ip, cancel):
    if cancel.is_set():
        return None
    ssh = probe_port(ip, 22)
    if cancel.is_set():
        return None
    web = "closed" if ssh == "open" else probe_port(ip, 80)
    up = ssh in ("open", "refused") or web in ("open", "refused")
    if not up:
        return None
    return {"ip": ip, "ssh_open": ssh == "open", "mac": "", "host": ""}


def _lookup_host(ip):
    done = threading.Event()
    found = {}

    def run():
        try:
            name = socket.getnameinfo((ip, 0), socket.NI_NAMEREQD)[0]
            if name and name != ip:
                found["host"] = name[:-1].lower() if name.endswith(".") else name.lower()
        except (OSError, UnicodeError):
            pass
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    done.wait(HOST_TIMEOUT)
    return found.get("host", "")


def _arp_table():
    text = ""
    if os.path.exists("/proc/net/arp"):
        try:
            text = open("/proc/net/arp", encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
    elif sys.platform == "win32":
        try:
            proc = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=3, encoding="utf-8", errors="replace")
            text = proc.stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            text = ""
    table = {}
    for line in text.splitlines():
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f]{2}(?::[0-9a-f]{2}){5}|[0-9a-f]{2}(?:-[0-9a-f]{2}){5})", line, re.I)
        if not match:
            continue
        mac = match.group(2).replace("-", ":").lower()
        if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
            continue
        table[match.group(1)] = mac
    return table


def _windows_interfaces():
    import ctypes
    from ctypes import wintypes

    class IP_ADDR_STRING(ctypes.Structure):
        pass

    ptr = ctypes.POINTER(IP_ADDR_STRING)
    IP_ADDR_STRING._fields_ = [
        ("next", ptr), ("ipAddress", ctypes.c_char * 16), ("ipMask", ctypes.c_char * 16), ("context", wintypes.DWORD),
    ]

    class IP_ADAPTER_INFO(ctypes.Structure):
        pass

    adapter_ptr = ctypes.POINTER(IP_ADAPTER_INFO)
    IP_ADAPTER_INFO._fields_ = [
        ("next", adapter_ptr),
        ("comboIndex", wintypes.DWORD),
        ("adapterName", ctypes.c_char * 260),
        ("description", ctypes.c_char * 132),
        ("addressLength", wintypes.UINT),
        ("address", ctypes.c_ubyte * 8),
        ("index", wintypes.DWORD),
        ("type", wintypes.UINT),
        ("dhcpEnabled", wintypes.UINT),
        ("currentIpAddress", ptr),
        ("ipAddressList", IP_ADDR_STRING),
        ("gatewayList", IP_ADDR_STRING),
        ("dhcpServer", IP_ADDR_STRING),
        ("haveWins", wintypes.BOOL),
        ("primaryWinsServer", IP_ADDR_STRING),
        ("secondaryWinsServer", IP_ADDR_STRING),
        ("leaseObtained", wintypes.DWORD),
        ("leaseExpires", wintypes.DWORD),
    ]
    size = wintypes.ULONG(0)
    ctypes.WinDLL("iphlpapi").GetAdaptersInfo(None, ctypes.byref(size))
    if not size.value:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if ctypes.WinDLL("iphlpapi").GetAdaptersInfo(buf, ctypes.byref(size)) != 0:
        return []
    found, adapter = [], ctypes.cast(buf, adapter_ptr)
    while adapter:
        item = adapter.contents
        name = item.description.split(b"\x00", 1)[0].decode("mbcs", "replace")
        entry = item.ipAddressList
        while True:
            ip = entry.ipAddress.split(b"\x00", 1)[0].decode("ascii", "replace")
            if parse_ipv4(ip) and ip != "0.0.0.0":
                found.append((name, ip))
            if not entry.next:
                break
            entry = entry.next.contents
        adapter = item.next
    return found


def _posix_interfaces():
    if not os.path.isdir("/sys/class/net"):
        return []
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in os.listdir("/sys/class/net"):
            try:
                packed = __import__("fcntl").ioctl(sock.fileno(), 0x8915, __import__("struct").pack("256s", name.encode()[:15]))
            except OSError:
                continue
            found.append((name, socket.inet_ntoa(packed[20:24])))
    finally:
        sock.close()
    return found


def local_interfaces():
    try:
        if sys.platform == "win32":
            found = _windows_interfaces()
        else:
            found = _posix_interfaces()
    except (OSError, AttributeError, ValueError):
        found = []
    if found:
        return found
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        ip = sock.getsockname()[0]
    except OSError:
        return []
    finally:
        sock.close()
    return [("default", ip)] if parse_ipv4(ip) else []


def _annotate(devices, cancel):
    arp = _arp_table()
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="lan-name") as pool:
        names = list(pool.map(lambda device: "" if cancel.is_set() else _lookup_host(device["ip"]), devices))
    for device, name in zip(devices, names):
        device["mac"] = arp.get(device["ip"], "")
        device["host"] = name
    devices.sort(key=lambda device: (0 if device["ssh_open"] else 1, *(int(part) for part in device["ip"].split("."))))


def _snapshot(job):
    with job["lock"]:
        devices = [dict(device) for device in job["devices"]]
        devices.sort(key=lambda device: (0 if device["ssh_open"] else 1, *(int(part) for part in device["ip"].split("."))))
        return {
            "scanning": not job["finished"],
            "done": job["done"],
            "total": job["total"],
            "subnets": list(job["subnets"]),
            "devices": devices,
            "error": job["error"],
        }


def _run(job):
    cancel = job["cancel"]
    try:
        subnets = select_subnets(local_interfaces())
        pending = [(subnet, ip) for subnet in subnets for ip in hosts_for(subnet)]
        with job["lock"]:
            job["subnets"] = [{"prefix": subnet["prefix"], "name": subnet["name"], "selves": subnet["selves"]} for subnet in subnets]
            job["total"] = len(pending)
        if not pending or cancel.is_set():
            return
        def task(ip):
            device = _probe_host(ip, cancel)
            with job["lock"]:
                job["done"] += 1
                if device:
                    job["devices"].append(device)
            return device
        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="lan-scan") as pool:
            futures = [pool.submit(task, ip) for _, ip in pending]
            for future in futures:
                if cancel.is_set():
                    break
                future.result()
        with job["lock"]:
            found = list(job["devices"])
        if not cancel.is_set() and found:
            _annotate(found, cancel)
            with job["lock"]:
                job["devices"] = found
    except Exception as exc:
        with job["lock"]:
            job["error"] = str(exc) or type(exc).__name__
    finally:
        with job["lock"]:
            job["finished"] = True
            job["done"] = job["total"]


def start_scan():
    """Start one scan and cancel the previous one. Returns the current snapshot."""
    global _job
    job = {"cancel": threading.Event(), "lock": threading.Lock(), "devices": [], "done": 0, "total": 0,
           "subnets": [], "error": "", "finished": False}
    with _JOBS:
        if _job is not None:
            _job["cancel"].set()
        _job = job
    threading.Thread(target=_run, args=(job,), daemon=True, name="lan-scan").start()
    return _snapshot(job)


def scan_status():
    with _JOBS:
        job = _job
    if job is None:
        return {"scanning": False, "done": 0, "total": 0, "subnets": [], "devices": [], "error": ""}
    return _snapshot(job)


def handle(payload):
    if not isinstance(payload, dict):
        raise ValueError("扫描请求无效")
    action = payload.get("action")
    if action == "start":
        return start_scan()
    if action == "status":
        return scan_status()
    raise ValueError("未知的局域网扫描动作")
