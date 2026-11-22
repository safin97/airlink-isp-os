import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class Sas4Cards extends StatefulWidget {
  final Api api;
  const Sas4Cards({super.key, required this.api});

  @override
  State<Sas4Cards> createState() => _Sas4CardsState();
}

class _Sas4CardsState extends State<Sas4Cards> with LanguageRebuild {
  final search = TextEditingController();
  Map<String, dynamic>? result;
  List<dynamic> managers = [];
  Map<String, dynamic> actions = {};
  String? series, error, managerError;
  bool busy = false, changing = false, dialogOpen = false, reveal = false;
  int managerId = -1, version = 0;
  Timer? debounce, refresh;

  @override
  void initState() {
    super.initState();
    load();
    loadManagers();
    refresh = Timer.periodic(const Duration(seconds: 15), (_) {
      if (!busy &&
          !changing &&
          !dialogOpen &&
          series == null &&
          !(debounce?.isActive ?? false)) {
        load(page: result?['page'] as int? ?? 1);
      }
    });
  }

  @override
  void dispose() {
    debounce?.cancel();
    refresh?.cancel();
    search.dispose();
    super.dispose();
  }

  Future<void> loadManagers() async {
    try {
      final data = await widget.api.request(
        '/integrations/sas4/reports/managers',
      );
      if (mounted) {
        setState(() {
          managers = data as List;
          managerError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => managerError = 'SAS4 manager list unavailable');
      }
    }
  }

  Future<void> load({int page = 1}) async {
    debounce?.cancel();
    final request = ++version;
    setState(() {
      busy = true;
      error = null;
    });
    final query = Uri(
      queryParameters: {
        'page': '$page',
        'search': search.text.trim(),
        if (series == null) 'manager_id': '$managerId',
        if (series != null) ...{'series': series!, 'reveal': '$reveal'},
      },
    ).query;
    try {
      final data = await widget.api.request(
        '/card-system/radius${series == null ? '' : '/cards'}?$query',
      );
      if (!mounted || request != version) return;
      setState(() {
        result = Map<String, dynamic>.from(data);
        if (series == null) {
          actions = Map<String, dynamic>.from(data['actions']);
        }
      });
    } catch (e) {
      if (mounted && request == version) {
        setState(() {
          error = e.toString();
          result = null;
        });
      }
    } finally {
      if (mounted && request == version) setState(() => busy = false);
    }
  }

  void openSeries(String? value) {
    setState(() {
      series = value;
      reveal = false;
      result = null;
      search.clear();
    });
    load();
  }

  static const actionLabels = {
    'suspend': 'Suspend series',
    'release': 'Release series',
    'owner': 'Change owner',
    'expiry': 'Change expiry',
    'delete': 'Delete series',
  };

  Future<void> change(Map row, String action) async {
    if (changing || busy || actions[action] != true) return;
    final id = '${row['series']}';
    int? newOwner;
    DateTime? newExpiry;
    setState(() => dialogOpen = true);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: AppText(actionLabels[action]!),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('SAS4 Radius series: $id'),
                const SizedBox(height: 12),
                AppText(
                  action == 'delete'
                      ? 'This permanently deletes the series in SAS4 Radius.'
                      : 'This changes the series directly in SAS4 Radius.',
                ),
                if (action == 'owner') ...[
                  const SizedBox(height: 16),
                  if (managerError != null) Text(managerError!),
                  DropdownButtonFormField<int>(
                    isExpanded: true,
                    initialValue: newOwner,
                    decoration: InputDecoration(labelText: tr('New owner')),
                    items: [
                      for (final manager in managers)
                        DropdownMenuItem(
                          value: manager['id'] as int,
                          child: Text(manager['username']),
                        ),
                    ],
                    onChanged: (value) => update(() => newOwner = value),
                  ),
                ],
                if (action == 'expiry') ...[
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.calendar_today),
                    label: Text(
                      newExpiry == null
                          ? tr('Choose expiry date')
                          : newExpiry!.toIso8601String().substring(0, 10),
                    ),
                    onPressed: () async {
                      final selected = await showDatePicker(
                        context: context,
                        initialDate: DateTime.now(),
                        firstDate: DateTime(2000),
                        lastDate: DateTime(2100),
                      );
                      if (selected != null && context.mounted) {
                        update(() => newExpiry = selected);
                      }
                    },
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const AppText('Cancel'),
            ),
            FilledButton(
              onPressed:
                  (action == 'owner' && newOwner == null) ||
                      (action == 'expiry' && newExpiry == null)
                  ? null
                  : () => Navigator.pop(context, true),
              child: const AppText('Confirm'),
            ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    setState(() => dialogOpen = false);
    if (confirmed != true) return;
    setState(() {
      changing = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/card-system/radius/action',
        method: 'POST',
        retry: false,
        body: {
          'series': id,
          'action': action,
          if (newOwner != null) 'owner_id': newOwner,
          if (newExpiry != null)
            'expiration': newExpiry!.toIso8601String().substring(0, 10),
        },
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: AppText('SAS4 card series updated')),
      );
      await load(page: action == 'delete' ? 1 : result?['page'] as int? ?? 1);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          result = null;
        });
      }
    } finally {
      if (mounted) setState(() => changing = false);
    }
  }

  String display(dynamic value, String key) {
    if (value == null || value == '') return '—';
    if (key == 'suspended') {
      return [true, 1, '1'].contains(value) ? tr('Yes') : tr('No');
    }
    if (key == 'type') {
      return switch ('$value') {
        '0' => tr('Refill Card'),
        '1' => tr('Prepaid User'),
        '2' => tr('Service Card'),
        _ => '$value',
      };
    }
    return '$value';
  }

  @override
  Widget build(BuildContext context) {
    final rows = result?['rows'] as List? ?? [];
    final columns = result?['columns'] as List? ?? [];
    final page = result?['page'] as int? ?? 1;
    final last = result?['last_page'] as int? ?? 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          series == null ? tr('SAS4 Radius cards') : '${tr('Series')}: $series',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        const AppText('Live cards from your saved SAS4 Radius connection.'),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            if (series != null)
              OutlinedButton.icon(
                onPressed: changing ? null : () => openSeries(null),
                icon: const Icon(Icons.arrow_back),
                label: const AppText('All series'),
              ),
            SizedBox(
              width: 240,
              child: TextField(
                key: const ValueKey('radius-card-search'),
                controller: search,
                enabled: !changing,
                maxLength: 200,
                decoration: InputDecoration(
                  labelText: tr('Search'),
                  counterText: '',
                  prefixIcon: const Icon(Icons.search),
                ),
                onChanged: (_) {
                  debounce?.cancel();
                  version++;
                  debounce = Timer(
                    const Duration(milliseconds: 400),
                    () => load(),
                  );
                },
                onSubmitted: (_) => load(),
              ),
            ),
            if (series == null)
              SizedBox(
                width: 240,
                child: DropdownButtonFormField<int>(
                  initialValue: managerId,
                  isExpanded: true,
                  decoration: InputDecoration(labelText: tr('Owner')),
                  items: [
                    const DropdownMenuItem(
                      value: -1,
                      child: AppText('All managers'),
                    ),
                    for (final manager in managers)
                      DropdownMenuItem(
                        value: manager['id'] as int,
                        child: Text(manager['username']),
                      ),
                  ],
                  onChanged: changing || busy
                      ? null
                      : (value) {
                          setState(() => managerId = value ?? -1);
                          load();
                        },
                ),
              ),
            if (series != null)
              OutlinedButton.icon(
                onPressed: busy || changing
                    ? null
                    : () {
                        setState(() {
                          reveal = !reveal;
                          result = null;
                        });
                        load(page: page);
                      },
                icon: Icon(reveal ? Icons.visibility_off : Icons.visibility),
                label: AppText(reveal ? 'Hide PINs' : 'Show PINs'),
              ),
            IconButton(
              tooltip: tr('Refresh'),
              onPressed: busy || changing
                  ? null
                  : () {
                      load(page: page);
                      loadManagers();
                    },
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        if (managerError != null && series == null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(managerError!),
          ),
        const SizedBox(height: 16),
        if (busy || changing) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (result != null && rows.isEmpty)
          const AppText('No SAS4 cards found.'),
        if (rows.isNotEmpty)
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: [
                for (final column in columns)
                  DataColumn(label: AppText(column['label'])),
                if (series == null) const DataColumn(label: AppText('Actions')),
              ],
              rows: [
                for (final row in rows)
                  DataRow(
                    cells: [
                      for (final column in columns)
                        DataCell(
                          column['key'] == 'series' && actions['cards'] == true
                              ? TextButton(
                                  onPressed: busy || changing
                                      ? null
                                      : () => openSeries('${row['series']}'),
                                  child: Text('${row['series']}'),
                                )
                              : SelectableText(
                                  display(row[column['key']], column['key']),
                                ),
                        ),
                      if (series == null)
                        DataCell(
                          PopupMenuButton<String>(
                            tooltip: tr('Manage series'),
                            enabled:
                                !busy &&
                                !changing &&
                                actionLabels.keys.any(
                                  (key) => actions[key] == true,
                                ),
                            onSelected: (action) => change(row as Map, action),
                            itemBuilder: (_) => [
                              for (final action in actionLabels.entries)
                                if (actions[action.key] == true)
                                  PopupMenuItem(
                                    value: action.key,
                                    child: AppText(action.value),
                                  ),
                            ],
                          ),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        if (result != null)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Wrap(
              spacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('${result!['total']} ${tr('records')} · $page / $last'),
                TextButton(
                  onPressed: busy || changing || page <= 1
                      ? null
                      : () => load(page: page - 1),
                  child: const AppText('Previous'),
                ),
                TextButton(
                  onPressed: busy || changing || page >= last
                      ? null
                      : () => load(page: page + 1),
                  child: const AppText('Next'),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
