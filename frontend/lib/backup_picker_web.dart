import 'dart:async';
import 'dart:js_interop';
import 'package:web/web.dart' as web;
import 'backup_selection.dart';

Future<BackupSelection?> pickBackupFile() => pickFile('.airlink');

Future<BackupSelection?> pickUpdateFile() => pickFile('.airlink-update');

Future<BackupSelection?> pickFile(String accept) async {
  final input = web.HTMLInputElement()
    ..type = 'file'
    ..accept = accept
    ..style.display = 'none';
  final result = Completer<BackupSelection?>();
  input.addEventListener(
    'change',
    ((web.Event event) {
      final file = input.files?.item(0);
      if (result.isCompleted) return;
      result.complete(
        file == null
            ? null
            : BackupSelection(
                name: file.name,
                size: file.size,
                read: (start, end) async =>
                    (await file.slice(start, end).arrayBuffer().toDart).toDart
                        .asUint8List(),
              ),
      );
    }).toJS,
  );
  input.addEventListener(
    'cancel',
    ((web.Event event) {
      if (!result.isCompleted) result.complete(null);
    }).toJS,
  );
  web.document.body!.append(input);
  input.click();
  try {
    return await result.future;
  } finally {
    input.remove();
  }
}
