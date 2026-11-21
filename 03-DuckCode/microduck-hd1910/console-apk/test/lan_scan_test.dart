import 'dart:io';

import 'package:console_apk/lan_scan.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('wifi and hotspot subnets are scanned, cellular is not', () {
    final subnets = selectSubnets([
      (name: 'wlan0', address: '192.168.1.20'),
      (name: 'ap0', address: '192.168.43.1'),
      (name: 'rmnet_data0', address: '10.8.0.4'),
      (name: 'tun0', address: '10.8.1.2'),
    ]);

    expect(subnets.map((subnet) => subnet.prefix), ['192.168.1', '192.168.43']);
    expect(subnets.first.hosts, isNot(contains('192.168.1.20')));
    expect(subnets.first.hosts, isNot(contains('192.168.1.0')));
    expect(subnets.first.hosts, isNot(contains('192.168.1.255')));
    expect(subnets.first.hosts.length, 253);
    expect(subnets.last.selfIps, {'192.168.43.1'});
  });

  test('an unknown private adapter is used only when no wifi adapter exists', () {
    expect(selectSubnets([(name: 'oem0', address: '192.168.49.1')]).single.prefix, '192.168.49');
    expect(
      selectSubnets([
        (name: 'oem0', address: '192.168.49.1'),
        (name: 'wlan0', address: '192.168.8.6'),
      ]).map((subnet) => subnet.prefix),
      ['192.168.8'],
    );
  });

  test('cellular alone does not become a scan target', () {
    expect(selectSubnets([(name: 'ccmni0', address: '10.1.2.3')]), isEmpty);
    expect(selectSubnets([(name: 'wlan0', address: '8.8.8.8')]), isEmpty);
  });

  test('two addresses on the same subnet are both skipped', () {
    final subnet = selectSubnets([
      (name: 'wlan0', address: '192.168.6.10'),
      (name: 'wlan0', address: '192.168.6.11'),
    ]).single;
    expect(subnet.hosts.length, 252);
    expect(subnet.hosts, isNot(contains('192.168.6.10')));
    expect(subnet.hosts, isNot(contains('192.168.6.11')));
  });

  test('probePort tells an open listener from a closed port', () async {
    final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((socket) => socket.destroy());
    addTearDown(() async {
      await subscription.cancel();
      await server.close();
    });
    expect(
      await probePort('127.0.0.1', server.port, const Duration(seconds: 2)),
      PortProbe.open,
    );
  });

  test('connection refused means the host answered', () {
    expect(
      connectionRefused(const SocketException('failed', osError: OSError('Connection refused', 111))),
      isTrue,
    );
    expect(connectionRefused(const SocketException('Connection timed out')), isFalse);
  });
}
