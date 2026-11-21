import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'hid_report.dart';
import 'protocol.dart';

enum HidPhase { idle, advertising, connected, fault }

/// Phone as a Bluetooth HID gamepad. The duck's `padd` reads it like any other pad.
class HidLink extends ChangeNotifier {
  HidLink() {
    _events.receiveBroadcastStream().listen(_onEvent, onError: _onError);
  }

  static const _methods = MethodChannel('com.microduck.console_apk/hid');
  static const _events = EventChannel('com.microduck.console_apk/hid_events');

  final PadFrame frame = PadFrame();
  HidPhase phase = HidPhase.idle;
  String message = '未开启';
  String? detail;

  bool get connected => phase == HidPhase.connected;

  Future<void> start() async {
    phase = HidPhase.advertising;
    message = '正在登记蓝牙手柄';
    detail = null;
    notifyListeners();
    try {
      await _methods.invokeMethod<void>('start');
    } on PlatformException catch (error) {
      phase = HidPhase.fault;
      message = '无法开启蓝牙手柄';
      detail = error.message ?? error.code;
      notifyListeners();
    }
  }

  Future<void> stop() async {
    frame.clear();
    try {
      await _methods.invokeMethod<void>('stop');
    } on PlatformException catch (error) {
      detail = error.message;
    }
    phase = HidPhase.idle;
    message = '已停止';
    notifyListeners();
  }

  void setStick(String prefix, double x, double y) {
    frame.axes['${prefix}x'] = _unit(x);
    frame.axes['${prefix}y'] = _unit(y);
    _send();
    notifyListeners();
  }

  void setButton(String name, bool pressed) {
    if (pressed) {
      frame.buttons.add(name);
    } else {
      frame.buttons.remove(name);
    }
    _send();
    notifyListeners();
  }

  void setTrigger(String axis, bool pressed) {
    frame.axes[axis] = pressed ? 1 : 0;
    _send();
    notifyListeners();
  }

  void setHat(String axis, double value, bool pressed) {
    frame.axes[axis] = pressed ? value : 0;
    _send();
    notifyListeners();
  }

  void centerSticks() {
    frame.axes['lx'] = frame.axes['ly'] = frame.axes['rx'] = frame.axes['ry'] = 0;
    _send();
    notifyListeners();
  }

  void _onEvent(dynamic event) {
    if (event is! Map) return;
    final state = event['state']?.toString() ?? '';
    final text = event['detail']?.toString();
    switch (state) {
      case 'discoverable':
        phase = HidPhase.advertising;
        message = '等待鸭子配对';
        detail = '保持本页在前台。中控手柄修复勾选首次配对；手机名是 GameSir-Nova 2 Lite';
      case 'connected':
        phase = HidPhase.connected;
        message = '鸭子已连上';
        detail = '可以操作。松手只回中，策略仍由鸭子上的 padd 决定';
        _send();
      case 'disconnected':
        if (phase != HidPhase.idle) {
          phase = HidPhase.advertising;
          message = '鸭子已断开';
          detail = text ?? '保持本页开启，鸭子会重新连接';
        }
      case 'error':
        phase = HidPhase.fault;
        message = '蓝牙手柄失败';
        detail = text;
      case 'stopped':
        phase = HidPhase.idle;
        message = '已停止';
        detail = null;
    }
    notifyListeners();
  }

  void _onError(Object error) {
    phase = HidPhase.fault;
    message = '蓝牙手柄失败';
    detail = error.toString();
    notifyListeners();
  }

  void _send() {
    if (!connected) return;
    unawaited(_methods.invokeMethod<void>('send', hidReport(frame)));
  }

  double _unit(double value) => (value.clamp(-1.0, 1.0) * 1000).round() / 1000;
}
