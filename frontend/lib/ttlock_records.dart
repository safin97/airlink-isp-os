import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'ttlock_style.dart';

List<Map<String, dynamic>> ttParseRecords(dynamic raw) {
  final decoded = raw is String ? jsonDecode(raw) : raw;
  final items = decoded is List
      ? decoded
      : decoded is Map
      ? (decoded['records'] ?? decoded['list'])
      : null;
  if (items is! List || items.any((e) => e is! Map)) {
    throw const FormatException(
      'The device returned an unsupported records format.',
    );
  }
  return items.map((e) => Map<String, dynamic>.from(e)).toList();
}

class TTRecords extends StatefulWidget {
  final List<Map<String, dynamic>>? records;
  final String lockName;
  final VoidCallback? refresh;
  final bool busy;
  const TTRecords({
    super.key,
    required this.records,
    required this.lockName,
    this.refresh,
    this.busy = false,
  });
  @override
  State<TTRecords> createState() => _TTRecordsState();
}

class _TTRecordsState extends State<TTRecords> {
  String query = '', filter = 'All results';
  int page = 1;
  String who(Map r) =>
      '${r['username'] ?? r['userName'] ?? r['operatorName'] ?? (r['userId'] != null ? 'User ${r['userId']}' : 'User not reported')}';
  String method(Map r) =>
      '${r['method'] ?? r['recordTypeName'] ?? (r['recordType'] != null ? 'Method code ${r['recordType']}' : 'Method not reported')}';
  bool? success(Map r) => r['success'] is bool
      ? r['success']
      : r['isSuccess'] is bool
      ? r['isSuccess']
      : null;
  @override
  void didUpdateWidget(TTRecords old) {
    super.didUpdateWidget(old);
    if (old.records != widget.records) page = 1;
  }

  @override
  Widget build(BuildContext context) {
    final rows = (widget.records ?? [])
        .where(
          (r) =>
              ('${who(r)} ${method(r)} ${widget.lockName}')
                  .toLowerCase()
                  .contains(query.toLowerCase()) &&
              (filter == 'All results' ||
                  filter == 'Success' && success(r) == true ||
                  filter == 'Failure' && success(r) == false ||
                  filter == 'Not reported' && success(r) == null),
        )
        .toList();
    final pages = (rows.length / 20).ceil().clamp(1, 100000);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 16,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              'Access history',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            FilledButton.icon(
              onPressed: widget.busy ? null : widget.refresh,
              icon: const Icon(LucideIcons.refreshCw, size: 16),
              label: const Text('Refresh records'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          'Events read from the lock. Missing identities, methods and results remain unreported.',
          style: TextStyle(color: ttMuted(context)),
        ),
        const SizedBox(height: 20),
        if (widget.records == null)
          TTEmpty(
            title: 'No records loaded',
            message: widget.refresh == null
                ? 'Access records require a nearby AirLink app. Connect Use phone Bluetooth from the dashboard to retrieve this lock’s history.'
                : 'Refresh records to read the actual device history over Bluetooth.',
            icon: LucideIcons.history,
          )
        else ...[
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              SizedBox(
                width: 320,
                child: TextField(
                  onChanged: (s) => setState(() {
                    query = s;
                    page = 1;
                  }),
                  decoration: const InputDecoration(
                    hintText: 'Search user, method or lock',
                    prefixIcon: Icon(LucideIcons.search, size: 18),
                  ),
                ),
              ),
              SizedBox(
                width: 210,
                child: DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: filter,
                  decoration: const InputDecoration(labelText: 'Result'),
                  items: [
                    for (final s in [
                      'All results',
                      'Success',
                      'Failure',
                      'Not reported',
                    ])
                      DropdownMenuItem(value: s, child: Text(s)),
                  ],
                  onChanged: (s) => setState(() {
                    filter = s!;
                    page = 1;
                  }),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          if (rows.isEmpty)
            const TTEmpty(
              title: 'No matching events',
              message:
                  'The loaded device records contain no events matching these filters.',
              icon: LucideIcons.history,
            ),
          for (final r in rows.skip((page - 1) * 20).take(20))
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TTPanel(
                padding: const EdgeInsets.all(18),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: ttBlue.withValues(alpha: .08),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(
                        LucideIcons.history,
                        color: ttBlue,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            who(r),
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${widget.lockName} · ${method(r)}',
                            style: TextStyle(color: ttMuted(context)),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            ttDate(
                              r['operateDate'] ??
                                  r['lockDate'] ??
                                  r['date'] ??
                                  r['timestamp'],
                            ),
                            style: TextStyle(
                              fontSize: 12,
                              color: ttMuted(context),
                            ),
                          ),
                          const SizedBox(height: 8),
                          TTBadge(
                            success(r) == true
                                ? 'Success'
                                : success(r) == false
                                ? 'Failure'
                                : 'Result not reported',
                            color: success(r) == true
                                ? ttGreen
                                : success(r) == false
                                ? ttRed
                                : ttMuted(context),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          Wrap(
            spacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text('${rows.length} events · Page $page / $pages'),
              TextButton(
                onPressed: page <= 1 ? null : () => setState(() => page--),
                child: const Text('Previous records'),
              ),
              TextButton(
                onPressed: page >= pages ? null : () => setState(() => page++),
                child: const Text('Next records'),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
