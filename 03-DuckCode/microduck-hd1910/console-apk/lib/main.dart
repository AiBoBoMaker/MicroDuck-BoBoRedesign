import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'console_page.dart';
import 'hid_link.dart';
import 'pad_page.dart';
import 'theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations(const [
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  runApp(const ConsoleApp());
}

class ConsoleApp extends StatefulWidget {
  const ConsoleApp({super.key});

  @override
  State<ConsoleApp> createState() => _ConsoleAppState();
}

class _ConsoleAppState extends State<ConsoleApp> {
  final HidLink link = HidLink();
  Future<void> Function(String script)? _runJs;
  int _page = 0;
  bool _expert = false;
  bool _consoleReady = false;

  @override
  void dispose() {
    link.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MicroDuck',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: ink,
        colorScheme: const ColorScheme.dark(
          primary: accent,
          surface: panel,
          onPrimary: Color(0xFF14200F),
          onSurface: paper,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(backgroundColor: accent, foregroundColor: const Color(0xFF14200F)),
        ),
      ),
      home: Scaffold(
        body: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
                child: Row(
                  children: [
                    const _BrandMark(),
                    const SizedBox(width: 6),
                    const Text(
                      'MicroDuck',
                      style: TextStyle(
                        color: Color(0xFFFFFFFF),
                        fontSize: 14,
                        fontWeight: FontWeight.w900,
                        height: 1,
                        shadows: [Shadow(offset: Offset(2, 2), color: Color(0xFF7A7A7A))],
                      ),
                    ),
                    const SizedBox(width: 6),
                    _tab('管理', 0),
                    const SizedBox(width: 6),
                    _tab('手柄', 1),
                    const Spacer(),
                    _expertSwitch(),
                    const SizedBox(width: 6),
                    _settingsButton(),
                  ],
                ),
              ),
              Expanded(
                child: IndexedStack(
                  index: _page,
                  children: [
                    ConsolePage(
                      onBind: (run) => _runJs = run,
                      onExpert: (expert) {
                        if (!mounted) return;
                        setState(() {
                          _consoleReady = true;
                          _expert = expert;
                        });
                      },
                    ),
                    PadPage(link: link),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _tab(String label, int index) {
    final selected = _page == index;
    return TextButton(
      style: TextButton.styleFrom(
        backgroundColor: selected ? accent : panel,
        foregroundColor: selected ? const Color(0xFF14200F) : paper,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(999),
          side: const BorderSide(color: line),
        ),
      ),
      onPressed: () => setState(() => _page = index),
      child: Text(label, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
    );
  }

  Future<void> _toggleExpert() async {
    if (!_consoleReady) return;
    setState(() => _expert = !_expert);
    await _runJs?.call("document.getElementById('bobo-expert')?.click()");
  }

  Future<void> _openSettings() async {
    if (!_consoleReady) return;
    setState(() => _page = 0);
    await _runJs?.call("document.getElementById('settings-button')?.click()");
  }

  Widget _expertSwitch() {
    return Tooltip(
      message: '专家模式',
      child: Semantics(
        button: true,
        toggled: _expert,
        label: '专家模式',
        child: GestureDetector(
          onTap: _consoleReady ? _toggleExpert : null,
          child: Opacity(
            opacity: _consoleReady ? 1 : 0.45,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              width: 42,
              height: 24,
              padding: const EdgeInsets.all(2),
              decoration: BoxDecoration(
                color: _expert ? const Color(0xFF3DFF8A) : const Color(0xFF6E6E6E),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: const Color(0xFF141414), width: 2),
              ),
              child: AnimatedAlign(
                duration: const Duration(milliseconds: 180),
                alignment: _expert ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  width: 16,
                  height: 16,
                  decoration: BoxDecoration(
                    color: const Color(0xFFF7F7F7),
                    shape: BoxShape.circle,
                    border: Border.all(color: const Color(0xFF141414), width: 2),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _settingsButton() {
    return IconButton(
      tooltip: '连接与数据说明',
      onPressed: _consoleReady ? _openSettings : null,
      icon: const Text('⚙', style: TextStyle(fontSize: 16, color: paper, height: 1)),
      style: IconButton.styleFrom(
        backgroundColor: const Color(0xFF1C1C1C),
        foregroundColor: paper,
        side: const BorderSide(color: Color(0xFFF4F1EA), width: 2),
        fixedSize: const Size(30, 30),
        minimumSize: const Size(30, 30),
        padding: EdgeInsets.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) {
    return const CustomPaint(
      size: Size(28, 32),
      painter: _BrandMarkPainter(),
    );
  }
}

class _BrandMarkPainter extends CustomPainter {
  const _BrandMarkPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 64);
    final paper = Paint()..color = const Color(0xFFF7F7F7);
    final ink = Paint()..color = const Color(0xFF141414);
    final spray = Paint()..color = const Color(0xFFE8FF47);
    final drip = Paint()..color = const Color(0xFF8A8A8A);
    canvas.drawRRect(
      RRect.fromRectAndRadius(const Rect.fromLTWH(4, 6, 56, 50), const Radius.circular(16)),
      paper,
    );
    canvas.drawPath(_drip(18, 54, const [1, 7, 4, 11, 2, 16, -1, -6, -3, -10, -2, -16]), drip);
    canvas.drawPath(_drip(30, 54, const [2, 8, 5, 13, 2, 18, -2, -6, -4, -11, -2, -18]), drip);
    canvas.drawPath(_drip(44, 54, const [1, 6, 3, 9, 1, 14, -1, -5, -2, -8, -1, -14]), drip);
    canvas.drawRRect(
      RRect.fromRectAndRadius(const Rect.fromLTWH(16, 24, 32, 22), const Radius.circular(7)),
      ink,
    );
    canvas.drawCircle(const Offset(27, 35), 3.4, spray);
    canvas.drawCircle(const Offset(37, 35), 3.4, spray);
    canvas.drawRRect(
      RRect.fromRectAndRadius(const Rect.fromLTWH(29, 14, 6, 11), const Radius.circular(3)),
      ink,
    );
    canvas.drawCircle(const Offset(32, 12), 3.5, ink);
    canvas.drawPath(_star(), spray);
  }

  Path _drip(double x, double y, List<double> c) {
    final path = Path()..moveTo(x, y);
    path.cubicTo(x + c[0], y + c[1], x + c[2], y + c[3], x + c[4], y + c[5]);
    final endX = x + c[4];
    final endY = y + c[5];
    path.cubicTo(endX + c[6], endY + c[7], endX + c[8], endY + c[9], endX + c[10], endY + c[11]);
    path.close();
    return path;
  }

  Path _star() {
    const points = <Offset>[
      Offset(50, 16),
      Offset(51.4, 19.2),
      Offset(54.8, 19.5),
      Offset(52.2, 21.7),
      Offset(53, 25.1),
      Offset(50, 23.3),
      Offset(47, 25.1),
      Offset(47.8, 21.7),
      Offset(45.2, 19.5),
      Offset(48.6, 19.2),
    ];
    return Path()..addPolygon(points, true);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
