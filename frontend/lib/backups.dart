import 'section_access.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'local_backup.dart';
import 'mega_backup.dart';

class Backups extends StatelessWidget {
  const Backups({super.key, required this.api});
  final Api api;

  @override
  Widget build(BuildContext context) {
    if (!hasSection(api.user ?? {}, 'backups')) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LocalBackup(api: api),
        const SizedBox(height: 24),
        MegaBackup(api: api),
      ],
    );
  }
}
