import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'hid_link.dart';
import 'theme.dart';

class PadPage extends StatefulWidget {
  const PadPage({super.key, required this.link});

  final HidLink link;

  @override
  State<PadPage> createState() => _PadPageState();
}

class _PadPageState extends State<PadPage> {
  int _stickReset = 0;
  bool _wasLive = false;

  HidLink get link => widget.link;

  @override
  void initState() {
    super.initState();
    link.addListener(_onLink);
  }

  @override
  void dispose() {
    link.removeListener(_onLink);
    super.dispose();
  }

  void _onLink() {
    if (!mounted) return;
    if (_wasLive && !link.connected) _stickReset++;
    _wasLive = link.connected;
    setState(() {});
  }

  void _center() {
    link.centerSticks();
    setState(() => _stickReset++);
  }

  void _reject(String name) {
    final text = link.detail ?? link.message;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$name 未发送：$text')));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(10, 6, 10, 8),
          child: Column(
            children: [
              _statusBar(),
              const SizedBox(height: 6),
              Expanded(child: _pad(link.connected)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _statusBar() {
    final color = switch (link.phase) {
      HidPhase.connected => accent,
      HidPhase.advertising => const Color(0xFFE7C56A),
      HidPhase.fault => const Color(0xFFFF8D7A),
      HidPhase.idle => muted,
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 0),
      child: Row(
        children: [
          Icon(Icons.circle, size: 10, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(link.message, maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(
                  link.detail ?? '开启并允许被发现后，到中控手柄修复里勾选首次配对',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: muted, fontSize: 12),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: () {
              if (link.phase == HidPhase.idle || link.phase == HidPhase.fault) {
                link.start();
              } else {
                link.stop();
              }
            },
            child: Text(link.phase == HidPhase.idle || link.phase == HidPhase.fault ? '开启' : '停止'),
          ),
        ],
      ),
    );
  }

  Widget _pad(bool enabled) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: panel,
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: line),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Column(
          children: [
            Expanded(
              flex: 2,
              child: Row(
                children: [
                  Expanded(child: _cell(HoldButton(label: 'LT', caption: '长叫', enabled: enabled, onChanged: (down) => link.setTrigger('lt', down), onRejected: () => _reject('LT')))),
                  Expanded(child: _cell(HoldButton(label: 'RT', caption: '短叫', enabled: enabled, onChanged: (down) => link.setTrigger('rt', down), onRejected: () => _reject('RT')))),
                ],
              ),
            ),
            Expanded(
              flex: 2,
              child: Row(
                children: [
                  Expanded(child: _cell(HoldButton(label: 'LB', caption: '左踢', enabled: enabled, onChanged: (down) => link.setButton('lb', down), onRejected: () => _reject('LB')))),
                  Expanded(child: _cell(HoldButton(label: 'RB', caption: '右踢', enabled: enabled, onChanged: (down) => link.setButton('rb', down), onRejected: () => _reject('RB')))),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              flex: 5,
              child: Row(
                children: [
                  Expanded(child: Stick(label: '左摇杆', reset: _stickReset, enabled: enabled, onChanged: (x, y) => link.setStick('l', x, y))),
                  Expanded(child: Stick(label: '右摇杆', reset: _stickReset, enabled: enabled, onChanged: (x, y) => link.setStick('r', x, y))),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              flex: 5,
              child: Row(
                children: [
                  Expanded(child: _dpad(enabled)),
                  Expanded(child: _face(enabled)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 52,
              child: Row(
                children: [
                  Expanded(
                    child: _cell(VoiceButton(
                      enabled: enabled,
                      onPulse: (down) => link.setButton('r3', down),
                      onRejected: () => _reject('对话'),
                    )),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 64,
              child: Row(
                children: [
                  Expanded(child: _cell(HoldButton(label: 'Select', caption: '短按卸力 · 按住关机', enabled: enabled, onChanged: (down) => link.setButton('select', down), onRejected: () => _reject('Select')))),
                  Expanded(child: _cell(HoldButton(label: 'Start', caption: '策略开关', enabled: enabled, onChanged: (down) => link.setButton('start', down), onRejected: () => _reject('Start')))),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.all(4),
                      child: SizedBox.expand(
                        child: OutlinedButton(onPressed: enabled ? _center : null, child: const Text('摇杆回中', style: TextStyle(fontSize: 16))),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _cell(Widget child) => Padding(padding: const EdgeInsets.all(4), child: child);

  Widget _dpad(bool enabled) {
    HoldButton key(String label, String caption, String axis, double value) => HoldButton(
          label: label,
          caption: caption,
          enabled: enabled,
          onChanged: (down) => link.setHat(axis, value, down),
          onRejected: () => _reject(label),
        );
    return _diamond(
      north: key('↑', '轮式', 'dy', -1),
      west: key('←', '动作', 'dx', -1),
      east: key('→', '舵机', 'dx', 1),
      south: key('↓', '起坐', 'dy', 1),
    );
  }

  Widget _face(bool enabled) {
    HoldButton key(String name, String caption, Color color) => HoldButton(
          label: name,
          caption: caption,
          color: color,
          foreground: const Color(0xFF14200F),
          round: true,
          enabled: enabled,
          onChanged: (down) => link.setButton(name.toLowerCase(), down),
          onRejected: () => _reject(name),
        );
    return _diamond(
      north: key('Y', '头部', const Color(0xFFE7C56A)),
      west: key('X', '翻滚', const Color(0xFF7EB6FF)),
      east: key('B', '身体', const Color(0xFFFF8D7A)),
      south: key('A', '捡物', accent),
    );
  }

  Widget _diamond({required Widget north, required Widget west, required Widget east, required Widget south}) {
    Widget slot(Widget? child) => Expanded(child: child == null ? const SizedBox.shrink() : _cell(child));
    return Column(
      children: [
        Expanded(child: Row(children: [slot(null), slot(north), slot(null)])),
        Expanded(child: Row(children: [slot(west), slot(null), slot(east)])),
        Expanded(child: Row(children: [slot(null), slot(south), slot(null)])),
      ],
    );
  }
}

class Stick extends StatefulWidget {
  const Stick({super.key, required this.label, required this.reset, required this.enabled, required this.onChanged});

  final String label;
  final int reset;
  final bool enabled;
  final void Function(double x, double y) onChanged;

  @override
  State<Stick> createState() => _StickState();
}

class _StickState extends State<Stick> {
  Offset _knob = Offset.zero;

  @override
  void didUpdateWidget(Stick oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.reset != oldWidget.reset && _knob != Offset.zero) {
      _knob = Offset.zero;
    }
  }

  void _move(Offset local, Size size) {
    if (!widget.enabled) return;
    final dx = ((local.dx - size.width / 2) / (size.width / 2)).clamp(-1.0, 1.0);
    final dy = ((local.dy - size.height / 2) / (size.height / 2)).clamp(-1.0, 1.0);
    setState(() => _knob = Offset(dx, dy));
    widget.onChanged(dx, dy);
  }

  void _release() {
    if (_knob == Offset.zero && !widget.enabled) return;
    setState(() => _knob = Offset.zero);
    widget.onChanged(0, 0);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final side = math.min(constraints.maxWidth, constraints.maxHeight);
      final size = Size(side, side);
      final knob = side * 0.34;
      return Center(
        child: SizedBox(
          width: side,
          height: side,
          child: GestureDetector(
            onPanDown: widget.enabled ? (details) => _move(details.localPosition, size) : null,
            onPanUpdate: widget.enabled ? (details) => _move(details.localPosition, size) : null,
            onPanEnd: (_) => _release(),
            onPanCancel: _release,
            child: DecoratedBox(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF121A17),
                border: Border.all(color: widget.enabled ? accent : line, width: 3),
              ),
              child: Stack(
                children: [
                  Align(
                    alignment: Alignment(_knob.dx, _knob.dy),
                    child: Container(
                      width: knob,
                      height: knob,
                      decoration: BoxDecoration(shape: BoxShape.circle, color: widget.enabled ? paper : muted),
                    ),
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Text(widget.label, style: const TextStyle(color: muted, fontSize: 13)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    });
  }
}

/// Matches console webpad R3: each tap pulses one edge; green latch stays until next tap.
class VoiceButton extends StatefulWidget {
  const VoiceButton({
    super.key,
    required this.enabled,
    required this.onPulse,
    required this.onRejected,
  });

  final bool enabled;
  final ValueChanged<bool> onPulse;
  final VoidCallback onRejected;

  @override
  State<VoiceButton> createState() => _VoiceButtonState();
}

class _VoiceButtonState extends State<VoiceButton> {
  bool _latched = false;
  Timer? _pulse;

  @override
  void dispose() {
    _pulse?.cancel();
    if (_pulse != null) widget.onPulse(false);
    super.dispose();
  }

  @override
  void didUpdateWidget(VoiceButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_latched && !widget.enabled) {
      _pulse?.cancel();
      _pulse = null;
      widget.onPulse(false);
      setState(() => _latched = false);
    }
  }

  void _tap() {
    if (!widget.enabled && !_latched) {
      widget.onRejected();
      return;
    }
    setState(() => _latched = !_latched);
    _pulse?.cancel();
    widget.onPulse(false);
    widget.onPulse(true);
    _pulse = Timer(const Duration(milliseconds: 120), () {
      _pulse = null;
      if (mounted) widget.onPulse(false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final active = _latched;
    final enabled = widget.enabled || active;
    return GestureDetector(
      onTap: _tap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 80),
        width: double.infinity,
        height: double.infinity,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        decoration: BoxDecoration(
          color: active ? accent : const Color(0xFF24312C),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: active ? accent : line, width: active ? 3 : 1),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '对话',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: active ? const Color(0xFF14200F) : (enabled ? paper : muted),
              ),
            ),
            Text(
              active ? '已接通 · 再点挂断' : 'R3 · 接通后再按挂断',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 12,
                color: active ? const Color(0xFF14200F).withValues(alpha: 0.8) : muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class HoldButton extends StatefulWidget {
  const HoldButton({
    super.key,
    required this.label,
    required this.enabled,
    required this.onChanged,
    required this.onRejected,
    this.caption,
    this.color = const Color(0xFF24312C),
    this.foreground = paper,
    this.round = false,
  });

  final String label;
  final String? caption;
  final Color color;
  final Color foreground;
  final bool enabled;
  final bool round;
  final ValueChanged<bool> onChanged;
  final VoidCallback onRejected;

  @override
  State<HoldButton> createState() => _HoldButtonState();
}

class _HoldButtonState extends State<HoldButton> {
  bool _held = false;

  @override
  void didUpdateWidget(HoldButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_held && !widget.enabled) {
      _held = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_held) widget.onChanged(false);
      });
    }
  }

  void _press() {
    if (!widget.enabled) {
      widget.onRejected();
      return;
    }
    setState(() => _held = true);
    widget.onChanged(true);
  }

  void _release() {
    if (!_held) return;
    setState(() => _held = false);
    widget.onChanged(false);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.enabled;
    return GestureDetector(
      onTapDown: (_) => _press(),
      onTapUp: (_) => _release(),
      onTapCancel: _release,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 80),
        width: double.infinity,
        height: double.infinity,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        decoration: BoxDecoration(
          color: enabled ? widget.color : const Color(0xFF24312C),
          borderRadius: BorderRadius.circular(widget.round ? 999 : 18),
          border: Border.all(color: _held ? accent : line, width: _held ? 3 : 1),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(widget.label, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: enabled ? widget.foreground : muted)),
            if (widget.caption != null)
              Text(
                widget.caption!,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, color: enabled ? widget.foreground.withValues(alpha: 0.8) : muted),
              ),
          ],
        ),
      ),
    );
  }
}
