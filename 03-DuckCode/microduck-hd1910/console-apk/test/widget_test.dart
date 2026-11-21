import 'package:console_apk/hid_report.dart';
import 'package:console_apk/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('neutral report matches the GameSir axis layout', () {
    expect(hidReport(PadFrame()), [0, 0, 15, 0, 0, 129, 0, 0, 129]);
  });

  test('face buttons follow the Xbox ordinal the GameSir bridge publishes', () {
    final frame = PadFrame()..buttons.addAll(['a', 'b', 'y', 'x', 'lb', 'rb', 'select', 'start']);
    final report = hidReport(frame);
    expect(report[0], (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 7));
    expect(report[1], (1 << 2) | (1 << 3));

    final onlyX = hidReport(PadFrame()..buttons.add('x'));
    final onlyY = hidReport(PadFrame()..buttons.add('y'));
    expect(onlyX[0], 1 << 3);
    expect(onlyY[0], 1 << 4);
  });

  test('right stick click is button 15 and does not move the hat', () {
    final report = hidReport(PadFrame()..buttons.add('r3'));
    expect(report[0], 0);
    expect(report[1], 1 << 6);
    expect(report[2], 15);
    expect(report.length, 9);
  });

  test('finger up is negative HID Y, d-pad down is hat 4, triggers rest at the low end', () {
    final frame = PadFrame()
      ..axes['lx'] = 1
      ..axes['ly'] = -1
      ..axes['dy'] = 1
      ..axes['lt'] = 1;
    final report = hidReport(frame);
    expect(report.length, 9);
    expect(report[2], 4);
    expect(report[3], 127);
    expect(report[4], 129);
    expect(report[5], 129);
    expect(report[8], 127);
  });
}
