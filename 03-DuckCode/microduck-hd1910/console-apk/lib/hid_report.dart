import 'dart:typed_data';

import 'protocol.dart';

/// Bluetooth HID input report for a GameSir-Nova 2 Lite stand-in, without the report ID.
///
/// The duck's repair scan and `gamesir-xboxd` both require this exact device. The bridge
/// grabs the raw node and republishes an Xbox 360 pad, and padd drives that virtual pad.
/// Xbox ordinals put physical X on BTN_NORTH and physical Y on BTN_WEST, so HID button 4
/// is the phone's X and button 5 is the phone's Y. Triggers are axes, not buttons:
/// usage Z rests at -127 and is RT, usage Rz rests at -127 and is LT. The bridge treats
/// an endpoint axis as a trigger and swaps the lower-numbered one onto RT.
Uint8List hidReport(PadFrame frame) {
  var low = 0;
  var high = 0;
  void press(int usage, bool down) {
    if (!down) return;
    final bit = usage - 1;
    if (bit < 8) {
      low |= 1 << bit;
    } else {
      high |= 1 << (bit - 8);
    }
  }

  final buttons = frame.buttons;
  press(1, buttons.contains('a'));
  press(2, buttons.contains('b'));
  press(4, buttons.contains('x'));
  press(5, buttons.contains('y'));
  press(7, buttons.contains('lb'));
  press(8, buttons.contains('rb'));
  press(11, buttons.contains('select'));
  press(12, buttons.contains('start'));
  // Usage 15 is BTN_THUMBR, the right-stick click padd uses for the voice call.
  // Usages 1-12 stay in the same bits; the old 4-bit pad shrinks to 1 bit.
  press(15, buttons.contains('r3'));

  final dx = frame.axes['dx']!.round().clamp(-1, 1);
  final dy = frame.axes['dy']!.round().clamp(-1, 1);
  return Uint8List.fromList([
    low,
    high,
    _hat(dx, dy),
    _axis(frame.axes['lx']!),
    _axis(frame.axes['ly']!),
    _trigger(frame.axes['rt']!),
    _axis(frame.axes['rx']!),
    _axis(frame.axes['ry']!),
    _trigger(frame.axes['lt']!),
  ]);
}

int _hat(int dx, int dy) {
  if (dx == 0 && dy == 0) return 15;
  if (dy < 0 && dx == 0) return 0;
  if (dy < 0 && dx > 0) return 1;
  if (dx > 0 && dy == 0) return 2;
  if (dy > 0 && dx > 0) return 3;
  if (dy > 0 && dx == 0) return 4;
  if (dy > 0 && dx < 0) return 5;
  if (dx < 0 && dy == 0) return 6;
  return 7;
}

int _axis(double value) => (value.clamp(-1.0, 1.0) * 127).round().clamp(-127, 127) & 0xFF;

/// Released stays on the minimum so the GameSir bridge classifies the axis as a trigger.
int _trigger(double value) => value > 0 ? 127 : 129;
