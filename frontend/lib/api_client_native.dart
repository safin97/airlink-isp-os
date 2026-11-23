import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'mobile_session.dart';

// Preserve the existing HttpOnly refresh-cookie protocol on native platforms.
// Only the configured HTTPS origin and /api/auth path receive the cookie.
class NativeApiClient extends http.BaseClient {
  final http.Client inner;
  NativeApiClient({http.Client? inner}) : inner = inner ?? IOClient();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final origin = mobileServer ?? const String.fromEnvironment('API_BASE');
    if (request.url.scheme != 'https' || request.url.origin != origin) {
      throw const FormatException(
        'Configure your trusted HTTPS AirLink server in the mobile app.',
      );
    }
    request.followRedirects = false;
    final auth = request.url.path.startsWith('/api/auth/');
    final storageKey = 'airlink.refresh.$origin';
    if (auth) {
      final cookie = await mobileSecrets.read(key: storageKey);
      if (cookie != null) {
        request.headers[HttpHeaders.cookieHeader] = 'airlink_refresh=$cookie';
      }
    }
    final response = await inner.send(request);
    if (auth) {
      final header = response.headers[HttpHeaders.setCookieHeader];
      if (header != null) {
        final cookie = Cookie.fromSetCookieValue(header);
        if (cookie.name == 'airlink_refresh') {
          if (cookie.value.isEmpty || cookie.maxAge == 0) {
            await mobileSecrets.delete(key: storageKey);
          } else {
            await mobileSecrets.write(key: storageKey, value: cookie.value);
          }
        }
      }
    }
    return response;
  }

  @override
  void close() => inner.close();
}

http.Client createApiClient() => NativeApiClient();

Future<void> clearNativeSession() => mobileSecrets.delete(
  key: 'airlink.refresh.${mobileServer ?? const String.fromEnvironment('API_BASE')}',
);
