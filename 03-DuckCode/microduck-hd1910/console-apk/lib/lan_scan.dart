import 'dart:io';

/// One IPv4 LAN the phone is already on. Hosts are the /24 except this phone.
class LanSubnet {
  const LanSubnet({
    required this.interfaceName,
    required this.prefix,
    required this.selfIps,
  });

  final String interfaceName;
  final String prefix;
  final Set<String> selfIps;

  String get label => '$prefix.0/24';

  List<String> get hosts => [
        for (var host = 1; host <= 254; host++)
          if (!selfIps.contains('$prefix.$host')) '$prefix.$host',
      ];
}

class LanDevice {
  const LanDevice({required this.ip, required this.sshOpen, this.mac, this.host});

  final String ip;
  final bool sshOpen;
  final String? mac;
  final String? host;

  LanDevice copyWith({String? mac, String? host}) {
    return LanDevice(
      ip: ip,
      sshOpen: sshOpen,
      mac: mac ?? this.mac,
      host: host ?? this.host,
    );
  }
}

List<int>? parseIpv4(String address) {
  final parts = address.split('.');
  if (parts.length != 4) return null;
  final octets = <int>[];
  for (final part in parts) {
    final value = int.tryParse(part);
    if (value == null || value < 0 || value > 255) return null;
    octets.add(value);
  }
  return octets;
}

bool isPrivateIpv4(String address) {
  final octets = parseIpv4(address);
  if (octets == null) return false;
  final a = octets[0];
  final b = octets[1];
  if (a == 10) return true;
  if (a == 192 && b == 168) return true;
  if (a == 172 && b >= 16 && b <= 31) return true;
  return false;
}

bool isSkippedInterface(String name) {
  return RegExp(
    r'^(lo|dummy|rmnet|ccmni|pdp|tun|tap|ipsec|ppp|wwan|sit|gre|ifb|teql|rev_rmnet|wifi-aware|clat|epdg)',
  ).hasMatch(name.toLowerCase());
}

bool isLanInterface(String name) {
  return RegExp(
    r'(wlan|wifi|swlan|softap|eth|usb|rndis|bnep|uap|bridge|(^|_)ap\d)',
  ).hasMatch(name.toLowerCase());
}

/// Prefer Wi-Fi and hotspot adapters. Cellular and VPN names are left out.
List<LanSubnet> selectSubnets(List<({String name, String address})> interfaces) {
  final usable = <({String name, String address, String prefix})>[];
  for (final iface in interfaces) {
    if (isSkippedInterface(iface.name) || !isPrivateIpv4(iface.address)) continue;
    final octets = parseIpv4(iface.address);
    if (octets == null) continue;
    usable.add((name: iface.name, address: iface.address, prefix: '${octets[0]}.${octets[1]}.${octets[2]}'));
  }
  final preferred = usable.where((iface) => isLanInterface(iface.name)).toList();
  final chosen = preferred.isNotEmpty ? preferred : usable;
  final groups = <String, ({String name, Set<String> self})>{};
  for (final iface in chosen) {
    final group = groups.putIfAbsent(iface.prefix, () => (name: iface.name, self: <String>{}));
    group.self.add(iface.address);
  }
  final prefixes = groups.keys.toList()..sort(compareIpv4);
  return [
    for (final prefix in prefixes)
      LanSubnet(
        interfaceName: groups[prefix]!.name,
        prefix: prefix,
        selfIps: groups[prefix]!.self,
      ),
  ];
}

int compareIpv4(String a, String b) {
  final left = parseIpv4(a) ?? parseIpv4('$a.0') ?? const [0, 0, 0, 0];
  final right = parseIpv4(b) ?? parseIpv4('$b.0') ?? const [0, 0, 0, 0];
  for (var i = 0; i < 4; i++) {
    final order = (i < left.length ? left[i] : 0).compareTo(i < right.length ? right[i] : 0);
    if (order != 0) return order;
  }
  return 0;
}

bool connectionRefused(SocketException error) {
  final code = error.osError?.errorCode;
  if (code == 111 || code == 10061 || code == 61) return true;
  final message = '${error.osError?.message ?? ''} ${error.message}'.toLowerCase();
  return message.contains('refused') || message.contains('拒绝');
}

enum PortProbe { open, refused, dead }

Future<PortProbe> probePort(String ip, int port, Duration timeout) async {
  try {
    final socket = await Socket.connect(ip, port, timeout: timeout);
    try {
      await socket.close();
    } catch (_) {}
    return PortProbe.open;
  } on SocketException catch (error) {
    if (connectionRefused(error)) return PortProbe.refused;
    return PortProbe.dead;
  } catch (_) {
    return PortProbe.dead;
  }
}

/// A host counts as online when port 22 or 80 answers, including a refusal.
Future<LanDevice?> probeHost(String ip, {Duration timeout = const Duration(milliseconds: 450)}) async {
  final results = await Future.wait([
    probePort(ip, 22, timeout),
    probePort(ip, 80, timeout),
  ]);
  final ssh = results[0];
  final web = results[1];
  if (ssh == PortProbe.dead && web == PortProbe.dead) return null;
  return LanDevice(ip: ip, sshOpen: ssh == PortProbe.open);
}

class LanScanner {
  var _cancelled = false;

  void cancel() => _cancelled = true;

  Future<void> scan({
    required List<LanSubnet> subnets,
    required void Function(LanDevice device) onDevice,
    required void Function(int done, int total) onProgress,
    Duration timeout = const Duration(milliseconds: 450),
    int concurrency = 32,
  }) async {
    final hosts = <String>{
      for (final subnet in subnets) ...subnet.hosts,
    }.toList();
    final total = hosts.length;
    var cursor = 0;
    var done = 0;
    onProgress(0, total);

    Future<void> worker() async {
      while (!_cancelled) {
        final index = cursor;
        if (index >= hosts.length) return;
        cursor += 1;
        final device = await probeHost(hosts[index], timeout: timeout);
        if (_cancelled) return;
        done += 1;
        onProgress(done, total);
        if (device != null) onDevice(device);
      }
    }

    if (hosts.isEmpty) return;
    final workers = concurrency.clamp(1, hosts.length);
    await Future.wait([for (var i = 0; i < workers; i++) worker()]);
  }
}

Future<Map<String, String>> readArpTable() async {
  try {
    final file = File('/proc/net/arp');
    if (!await file.exists()) return {};
    final lines = await file.readAsLines();
    final table = <String, String>{};
    for (final line in lines.skip(1)) {
      final parts = line.trim().split(RegExp(r'\s+'));
      if (parts.length < 4) continue;
      final mac = parts[3].toLowerCase();
      if (!RegExp(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$').hasMatch(mac)) continue;
      if (mac == '00:00:00:00:00:00') continue;
      table[parts[0]] = mac;
    }
    return table;
  } catch (_) {
    return {};
  }
}

Future<String?> lookupHostName(String ip) async {
  try {
    final resolved = await InternetAddress(ip).reverse().timeout(const Duration(milliseconds: 700));
    final host = resolved.host.trim();
    if (host.isEmpty || host == ip) return null;
    return host;
  } catch (_) {
    return null;
  }
}
