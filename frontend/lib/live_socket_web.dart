import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'package:web/web.dart' as web;
import 'live_socket_types.dart';

LiveSocket connectLiveSocket(Uri uri, String token) =>
    BrowserLiveSocket(uri, token);

class BrowserLiveSocket implements LiveSocket {
  final controller = StreamController<Map<String, dynamic>>();
  late final web.WebSocket socket;
  bool closed = false;
  BrowserLiveSocket(Uri uri, String token) {
    socket = web.WebSocket(uri.toString());
    socket.onopen = ((web.Event event) {
      if (!closed) socket.send(jsonEncode({'token': token}).toJS);
    }).toJS;
    socket.onmessage = ((web.MessageEvent event) {
      if (closed) return;
      try {
        controller.add(
          Map<String, dynamic>.from(
            jsonDecode((event.data as JSString).toDart),
          ),
        );
      } catch (error) {
        controller.addError(error);
        close();
      }
    }).toJS;
    socket.onclose = ((web.CloseEvent event) {
      if (closed) return;
      if (event.code == 4401) controller.addError(LiveAuthenticationExpired());
      close();
    }).toJS;
    socket.onerror = ((web.Event event) {
      if (!closed) {
        controller.addError(StateError('Live connection interrupted'));
        close();
      }
    }).toJS;
  }
  @override
  Stream<Map<String, dynamic>> get messages => controller.stream;
  @override
  void close() {
    if (closed) return;
    closed = true;
    socket.close();
    unawaited(controller.close());
  }
}
