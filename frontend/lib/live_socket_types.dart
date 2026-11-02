abstract class LiveSocket {
  Stream<Map<String, dynamic>> get messages;
  void close();
}

class LiveAuthenticationExpired implements Exception {}

typedef LiveConnector = LiveSocket? Function(Uri uri, String token);
