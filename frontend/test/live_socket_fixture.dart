import 'dart:async';
import 'package:airlink_isp_os/live_socket_types.dart';

class FakeSocket implements LiveSocket {
  final controller = StreamController<Map<String, dynamic>>();
  bool closed = false;
  @override
  Stream<Map<String, dynamic>> get messages => controller.stream;
  @override
  void close() {
    if (closed) return;
    closed = true;
    controller.close();
  }
}
