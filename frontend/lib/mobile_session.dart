import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const mobileSecrets = FlutterSecureStorage();
String? mobileServer;

String validateMobileServer(String value) {
  final uri = Uri.tryParse(value.trim());
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    throw const FormatException(
      'Enter an HTTPS server address, without a path.',
    );
  }
  return uri.origin;
}
