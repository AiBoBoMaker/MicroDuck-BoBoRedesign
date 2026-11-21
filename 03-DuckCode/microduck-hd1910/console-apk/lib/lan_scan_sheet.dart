import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import 'lan_scan.dart';
import 'theme.dart';

/// Lists devices on the phone's current LAN. Pops with the selected IP.
class LanScanSheet extends StatefulWidget {
  const LanScanSheet({super.key});

  @override
  State<LanScanSheet> createState() => _LanScanSheetState();
}

class _LanScanSheetState extends State<LanScanSheet> {
  final List<LanDevice> _devices = [];
  LanScanner _scanner = LanScanner();
  List<LanSubnet> _subnets = [];
  var _scanning = true;
  var _done = 0;
  var _total = 0;
  String? _error;
  var _generation = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_start());
  }

  @override
  void dispose() {
    _generation += 1;
    _scanner.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    final generation = ++_generation;
    _scanner.cancel();
    _scanner = LanScanner();
    setState(() {
      _devices.clear();
      _subnets = [];
      _scanning = true;
      _done = 0;
      _total = 0;
      _error = null;
    });
    List<LanSubnet> subnets;
    try {
      final interfaces = await NetworkInterface.list(
        includeLinkLocal: false,
        type: InternetAddressType.IPv4,
      );
      subnets = selectSubnets([
        for (final iface in interfaces)
          for (final address in iface.addresses) (name: iface.name, address: address.address),
      ]);
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _scanning = false;
        _error = '读不到本机网卡：$error';
      });
      return;
    }
    if (!mounted || generation != _generation) return;
    if (subnets.isEmpty) {
      setState(() {
        _scanning = false;
        _error = '没有发现局域网。请让手机和鸭子连同一个热点或 Wi-Fi。';
      });
      return;
    }
    final total = subnets.fold<int>(0, (sum, subnet) => sum + subnet.hosts.length);
    setState(() {
      _subnets = subnets;
      _total = total;
    });
    await _scanner.scan(
      subnets: subnets,
      onDevice: (device) {
        if (!mounted || generation != _generation) return;
        setState(() {
          _devices.removeWhere((item) => item.ip == device.ip);
          _devices.add(device);
          _devices.sort(_byPreference);
        });
        unawaited(_annotate(device.ip, generation));
      },
      onProgress: (done, total) {
        if (!mounted || generation != _generation) return;
        setState(() {
          _done = done;
          _total = total;
        });
      },
    );
    if (!mounted || generation != _generation) return;
    final arp = await readArpTable();
    if (!mounted || generation != _generation) return;
    setState(() {
      _scanning = false;
      for (var i = 0; i < _devices.length; i++) {
        final mac = arp[_devices[i].ip];
        if (mac != null) _devices[i] = _devices[i].copyWith(mac: mac);
      }
    });
  }

  Future<void> _annotate(String ip, int generation) async {
    final results = await Future.wait([lookupHostName(ip), readArpTable()]);
    if (!mounted || generation != _generation) return;
    final host = results[0] as String?;
    final arp = results[1] as Map<String, String>;
    final index = _devices.indexWhere((device) => device.ip == ip);
    if (index < 0) return;
    if (host == null && arp[ip] == null) return;
    setState(() {
      _devices[index] = _devices[index].copyWith(host: host, mac: arp[ip]);
    });
  }

  int _byPreference(LanDevice a, LanDevice b) {
    if (a.sshOpen != b.sshOpen) return a.sshOpen ? -1 : 1;
    return compareIpv4(a.ip, b.ip);
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.sizeOf(context).height * 0.72;
    final progress = _total == 0 ? null : _done / _total;
    return SafeArea(
      child: SizedBox(
        height: height,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 12, 4),
              child: Row(
                children: [
                  const Expanded(
                    child: Text(
                      '局域网设备',
                      style: TextStyle(color: paper, fontSize: 18, fontWeight: FontWeight.w800),
                    ),
                  ),
                  IconButton(
                    tooltip: '重新扫描',
                    onPressed: _scanning ? null : _start,
                    icon: const Icon(Icons.refresh, color: paper),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(_statusLine(), style: const TextStyle(color: muted, fontSize: 13, height: 1.35)),
            ),
            if (_scanning)
              LinearProgressIndicator(
                value: progress,
                minHeight: 3,
                color: accent,
                backgroundColor: line,
              ),
            Expanded(child: _body()),
          ],
        ),
      ),
    );
  }

  String _statusLine() {
    if (_error != null) return _error!;
    final nets = _subnets.map((subnet) => '${subnet.label} · ${subnet.interfaceName}').join('，');
    final self = _subnets.expand((subnet) => subnet.selfIps).join('、');
    if (_scanning) {
      final seen = _total == 0 ? '' : '已检查 $_done/$_total。';
      return '正在扫描 $nets。$seen本机 $self 已跳过。开着 SSH 的排在前面。';
    }
    if (_devices.isEmpty) {
      return '扫描结束，没有发现在线设备。请确认鸭子和手机在同一个热点，且热点没有打开设备隔离。';
    }
    final sshCount = _devices.where((device) => device.sshOpen).length;
    return '找到 ${_devices.length} 台，其中 $sshCount 台开着 SSH。点一台，IP 会填进 SSH 地址。';
  }

  Widget _body() {
    if (_error != null) {
      return const SizedBox.shrink();
    }
    if (_devices.isEmpty) {
      return Center(
        child: Text(
          _scanning ? '正在找设备…' : '这个网段里没有应答的设备',
          style: const TextStyle(color: muted),
        ),
      );
    }
    return ListView.separated(
      itemCount: _devices.length,
      separatorBuilder: (_, _) => const Divider(height: 1, color: line),
      itemBuilder: (context, index) {
        final device = _devices[index];
        final details = <String>[
          if (device.host != null) device.host!,
          if (device.mac != null) device.mac!,
          device.sshOpen ? 'SSH 可连接，点选填入地址' : '在线，22 端口没开',
        ];
        return ListTile(
          title: Text(
            device.ip,
            style: const TextStyle(color: paper, fontWeight: FontWeight.w800, fontSize: 16),
          ),
          subtitle: Text(details.join(' · '), style: TextStyle(color: device.sshOpen ? accent : muted)),
          trailing: device.sshOpen
              ? const Text('SSH', style: TextStyle(color: accent, fontWeight: FontWeight.w800))
              : const Icon(Icons.chevron_right, color: muted),
          onTap: () => Navigator.pop(context, device.ip),
        );
      },
    );
  }
}
