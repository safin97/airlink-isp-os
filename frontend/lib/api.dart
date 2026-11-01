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
  Api({http.Client? client}) : client = client ?? http.Client();
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
    try {
      await request('/auth/logout', method: 'POST');
    } finally {
      token = null;
      user = null;
    }
  }
}
