/// In-memory pad state. [hid_report.dart] turns this into a Bluetooth HID report.
const padAxes = ['lx', 'ly', 'rx', 'ry', 'lt', 'rt', 'dx', 'dy'];

class PadFrame {
  PadFrame() : axes = {for (final key in padAxes) key: 0.0}, buttons = {};

  final Map<String, double> axes;
  final Set<String> buttons;

  void clear() {
    for (final key in axes.keys) {
      axes[key] = 0;
    }
    buttons.clear();
  }
}
