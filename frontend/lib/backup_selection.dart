import 'dart:typed_data';

class BackupSelection {
  const BackupSelection({
    required this.name,
    required this.size,
    required this.read,
  });
  final String name;
  final int size;
  final Future<Uint8List> Function(int start, int end) read;
}
