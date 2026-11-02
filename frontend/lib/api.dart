import 'dart:async';
import 'live_socket.dart';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final String message;
  final int status;
  ApiException(this.message, this.status);
  @override
  String toString() => message;
}

class Api {
  final http.Client client;
  String? token;
  Map<String, dynamic>? user;
  Future<void>? _refreshing;
  final LiveConnector liveConnector;
  final _liveEvents = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get liveEvents => _liveEvents.stream;
  LiveSocket? _liveSocket;
  StreamSubscription<Map<String, dynamic>>? _liveSubscription;
  Timer? _liveRetry;
  bool _liveWanted = false;
  int _liveGeneration = 0;
  Api({http.Client? client, LiveConnector? liveConnector})
    : client = client ?? http.Client(),
      liveConnector = liveConnector ?? connectLiveSocket;

  void startLive() {
    if (_liveWanted) return;
    _liveWanted = true;
    _connectLive();
  }

  void stopLive() {
    _liveWanted = false;
    _liveGeneration++;
    _liveRetry?.cancel();
    _liveSubscription?.cancel();
    _liveSubscription = null;
    _liveSocket?.close();
    _liveSocket = null;
  }

  void _connectLive() {
    if (!_liveWanted || token == null) return;
    final generation = ++_liveGeneration;
    try {
      final origin = base.isEmpty ? Uri.base : Uri.parse(base);
      final endpoint = origin.resolve('/api/live');
      _liveSocket = liveConnector(
        endpoint.replace(scheme: endpoint.scheme == 'https' ? 'wss' : 'ws'),
        token!,
      );
      if (_liveSocket == null) return;
      bool ended = false;
      Future<void> disconnected([Object? error]) async {
        if (ended || generation != _liveGeneration || !_liveWanted) return;
        ended = true;
        _liveSocket?.close();
        _liveEvents.add({'type': 'connection', 'connected': false});
        if (error is LiveAuthenticationExpired) {
          try {
            await refresh();
          } catch (_) {
            if (_liveWanted && generation == _liveGeneration) {
              _liveEvents.add({'type': 'session_expired'});
              stopLive();
            }
            return;
          }
        }
        if (_liveWanted && generation == _liveGeneration) {
          _liveRetry = Timer(const Duration(seconds: 3), _connectLive);
        }
      }

      _liveSubscription = _liveSocket!.messages.listen(
        (event) {
          if (_liveWanted && generation == _liveGeneration) {
            _liveEvents.add(event);
          }
        },
        onError: (Object error) => disconnected(error),
        onDone: disconnected,
      );
    } catch (_) {
      if (_liveWanted) {
        _liveEvents.add({'type': 'connection', 'connected': false});
        _liveRetry = Timer(const Duration(seconds: 3), _connectLive);
      }
    }
  }

  static const base = String.fromEnvironment('API_BASE', defaultValue: '');

  Future<dynamic> request(
    String path, {
    String method = 'GET',
    Object? body,
    bool retry = true,
  }) async {
    final request = http.Request(method, Uri.parse('$base/api$path'));
    request.headers.addAll({
      'Content-Type': 'application/json',
      'X-AirLink-Request': '1',
      if (token != null) 'Authorization': 'Bearer $token',
    });
    if (body != null) request.body = jsonEncode(body);
    final response = await http.Response.fromStream(await client.send(request));
    if (response.statusCode == 401 &&
        retry &&
        token != null &&
        !path.startsWith('/auth/')) {
      await refresh();
      return this.request(path, method: method, body: body, retry: false);
    }
    if (response.statusCode >= 400) {
      String message = 'Request failed (${response.statusCode})';
      try {
        final detail = jsonDecode(response.body)['detail'];
        message = detail is String ? detail : detail.toString();
      } catch (_) {}
      throw ApiException(message, response.statusCode);
    }
    if (response.statusCode == 204) return null;
    if (response.headers['content-type']?.contains('text/csv') == true) {
      return response.body;
    }
    return jsonDecode(response.body);
  }

  Future<void> login(String username, String password) async {
    final data = await request(
      '/auth/login',
      method: 'POST',
      body: {'username': username, 'password': password},
    );
    token = data['access_token'];
    user = Map<String, dynamic>.from(data['user']);
  }

  Future<void> refresh() async {
    if (_refreshing != null) return _refreshing;
    _refreshing = _refresh();
    try {
      await _refreshing;
    } finally {
      _refreshing = null;
    }
  }

  Future<void> _refresh() async {
    final data = await request('/auth/refresh', method: 'POST', retry: false);
    token = data['access_token'];
    user = Map<String, dynamic>.from(data['user']);
  }

  Future<void> logout() async {
    stopLive();
    try {
      await request('/auth/logout', method: 'POST');
    } finally {
      token = null;
      user = null;
    }
  }
}
