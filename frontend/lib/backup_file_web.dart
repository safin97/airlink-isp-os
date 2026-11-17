import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';
import 'package:web/web.dart' as web;

Future<void> saveBackupFile(Uint8List bytes, String filename) async {
  final blob = web.Blob(
    [bytes.toJS].toJS,
    web.BlobPropertyBag(type: 'application/octet-stream'),
  );
  final url = web.URL.createObjectURL(blob);
  final link = web.HTMLAnchorElement()
    ..href = url
    ..download = filename;
  web.document.body!.append(link);
  link.click();
  link.remove();
  Timer(const Duration(minutes: 1), () => web.URL.revokeObjectURL(url));
}
