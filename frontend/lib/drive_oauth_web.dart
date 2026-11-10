import 'dart:async';
import 'dart:js_interop';
import 'package:web/web.dart' as web;

class DriveOAuth {
  final popup = web.window.open(
    'about:blank',
    'airlink-google-drive',
    'width=650,height=750',
  );
  JSFunction? listener;
  Timer? closedTimer;

  Future<Map<String, dynamic>> authorize(String url, String state) async {
    if (popup == null) {
      throw Exception('Allow pop-ups for AirLink, then connect again.');
    }
    final uri = Uri.parse(url);
    if (uri.scheme != 'https' || uri.host != 'accounts.google.com') {
      close();
      throw Exception('Invalid Google sign-in URL');
    }
    final done = Completer<Map<String, dynamic>>();
    listener = ((web.Event raw) {
      final event = raw as web.MessageEvent;
      if (event.origin != web.window.location.origin) return;
      final value = event.data.dartify();
      if (value is! Map ||
          value['type'] != 'airlink-google-drive' ||
          value['state'] != state) {
        return;
      }
      if (!done.isCompleted) done.complete(Map<String, dynamic>.from(value));
    }).toJS;
    web.window.addEventListener('message', listener);
    popup!.location.href = url;
    closedTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (popup!.closed && !done.isCompleted) {
        done.completeError(
          Exception('Google sign-in was closed. Connect again to retry.'),
        );
      }
    });
    try {
      return await done.future.timeout(const Duration(minutes: 10));
    } finally {
      close();
    }
  }

  void close() {
    if (listener != null) web.window.removeEventListener('message', listener);
    closedTimer?.cancel();
    popup?.close();
  }
}
