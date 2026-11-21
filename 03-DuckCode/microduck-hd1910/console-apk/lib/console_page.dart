import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'lan_scan.dart';
import 'lan_scan_sheet.dart';
import 'theme.dart';

const _chromeWatch = '''
(() => {
  const send = () => {
    try {
      BoboChrome.postMessage(JSON.stringify({
        expert: document.body.classList.contains('ui-expert')
      }));
    } catch (e) {}
  };
  if (!window.__boboChromeBound) {
    window.__boboChromeBound = true;
    new MutationObserver(send).observe(document.body, {attributes: true, attributeFilter: ['class']});
  }
  send();
})();
''';

class ConsolePage extends StatefulWidget {
  const ConsolePage({super.key, this.onBind, this.onExpert});

  final void Function(Future<void> Function(String script) run)? onBind;
  final ValueChanged<bool>? onExpert;

  @override
  State<ConsolePage> createState() => _ConsolePageState();
}

class _ConsolePageState extends State<ConsolePage> {
  static final _uri = Uri.parse('http://127.0.0.1:8090/');
  late final WebViewController _web;
  Timer? _retry;
  var _tries = 0;
  var _up = false;
  var _failed = false;
  String? _queuedIp;

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(ink)
      ..addJavaScriptChannel(
        'BoboChrome',
        onMessageReceived: (message) {
          if (!mounted) return;
          try {
            final decoded = jsonDecode(message.message);
            if (decoded is! Map) return;
            widget.onExpert?.call(decoded['expert'] == true);
          } catch (_) {}
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) => _failed = false,
          onPageFinished: (_) async {
            if (!mounted || _failed) return;
            _retry?.cancel();
            setState(() => _up = true);
            try {
              await _web.runJavaScript(_chromeWatch);
            } catch (_) {}
            final queued = _queuedIp;
            if (queued != null) await _fillSshIp(queued);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame != true) return;
            _failed = true;
            _schedule();
          },
        ),
      )
      ..setOnJavaScriptAlertDialog((request) async {
        if (!mounted) return;
        await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            content: SingleChildScrollView(child: Text(request.message)),
            actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('确定'))],
          ),
        );
      })
      ..setOnJavaScriptConfirmDialog((request) async {
        if (!mounted) return false;
        final answer = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            content: SingleChildScrollView(child: Text(request.message)),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
              TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('确定')),
            ],
          ),
        );
        return answer ?? false;
      })
      ..setOnJavaScriptTextInputDialog((request) async => request.defaultText ?? '');
    widget.onBind?.call(_web.runJavaScript);
    _load();
  }

  @override
  void dispose() {
    _retry?.cancel();
    super.dispose();
  }

  void _schedule() {
    if (_up) return;
    _retry?.cancel();
    _retry = Timer(const Duration(milliseconds: 700), () {
      if (mounted && !_up) _load();
    });
  }

  Future<void> _load() async {
    _tries += 1;
    if (mounted) setState(() {});
    try {
      await _web.loadRequest(_uri);
    } catch (_) {
      _schedule();
    }
  }

  Future<void> _openLanScan() async {
    final ip = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: panel,
      builder: (context) => const LanScanSheet(),
    );
    if (!mounted || ip == null || parseIpv4(ip) == null) return;
    await _fillSshIp(ip);
  }

  Future<void> _fillSshIp(String ip) async {
    if (parseIpv4(ip) == null) return;
    if (!_up) {
      setState(() => _queuedIp = ip);
      _toast('中控还在启动，选中的 $ip 会在页面打开后填入');
      return;
    }
    try {
      final filled = _jsText(await _web.runJavaScriptReturningResult(_sshFillScript(ip)));
      if (filled == null || !filled.endsWith('@$ip')) {
        setState(() => _queuedIp = ip);
        _toast('页面上还没有 SSH 地址框，稍后再写入 $ip');
        return;
      }
      if (mounted) setState(() => _queuedIp = null);
      _toast('已填入 SSH 地址 $filled');
    } catch (_) {
      if (!mounted) return;
      setState(() => _queuedIp = ip);
      _toast('页面暂时写不进去，已记下 $ip');
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  String? _jsText(Object? value) {
    if (value is! String) return null;
    final text = value.trim();
    if (text.isEmpty || text == 'null') return null;
    if (text.startsWith('"')) {
      try {
        final decoded = jsonDecode(text);
        if (decoded is String && decoded.isNotEmpty) return decoded;
      } catch (_) {}
    }
    return text;
  }

  String _sshFillScript(String ip) {
    return '''
(() => {
  const el = document.getElementById('ssh-target');
  if (!el) return '';
  const current = String(el.value || '').trim();
  const at = current.indexOf('@');
  const user = (at > 0 ? current.slice(0, at) : 'radxa').trim() || 'radxa';
  el.value = user + '@$ip';
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  try { el.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
  return el.value;
})()
''';
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  _up
                      ? '鸭子连上热点后，搜索局域网并点一台，IP 会填进 SSH 地址。'
                      : '正在启动本机中控。可以先搜索局域网，页面打开后会填入选中的 IP。',
                  style: TextStyle(color: muted, fontSize: _tries > 8 && !_up ? 14 : 12, height: 1.35),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _openLanScan,
                style: FilledButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: const Text('搜索设备', style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ],
          ),
        ),
        Expanded(child: WebViewWidget(controller: _web)),
      ],
    );
  }
}
