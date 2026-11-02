import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class Sas4Reports extends StatefulWidget {
  final Api api;
  const Sas4Reports({super.key, required this.api});
  @override
  State<Sas4Reports> createState() => _Sas4ReportsState();
}

class _Sas4ReportsState extends State<Sas4Reports> with LanguageRebuild {
  final search = TextEditingController();
  List<dynamic> reports = [], managers = [];
  int managerId = -1, requestVersion = 0;
  Timer? searchTimer;
  String? managerError;
  String selected = 'activation-statistics';
  String operation = 'deposit', period = 'monthly';
  int year = DateTime.now().year, month = DateTime.now().month;
  bool get statistics => selected == 'activation-statistics';
  String appliedSearch = '';
  DateTime? start, end, appliedStart, appliedEnd;
  Map<String, dynamic>? result;
  String? error;
  bool busy = true;

  @override
  void initState() {
    super.initState();
    initialize();
  }

  @override
  void dispose() {
    searchTimer?.cancel();
    search.dispose();
    super.dispose();
  }

  Future<void> initialize() async {
    try {
      final data = await Future.wait<dynamic>([
        widget.api.request('/integrations/sas4/reports'),
        loadManagers().then<dynamic>((_) => null),
      ]);
      if (!mounted) return;
      setState(() => reports = List<dynamic>.from(data[0]));
      await load(apply: true);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          busy = false;
        });
      }
    }
  }

  Future<void> loadManagers() async {
    try {
      final data = await widget.api.request(
        '/integrations/sas4/reports/managers',
      );
      if (mounted) {
        setState(() {
          managers = List<dynamic>.from(data);
          managerError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => managerError = 'SAS4 manager list unavailable');
      }
    }
  }

  void searchChanged(String value) {
    searchTimer?.cancel();
    requestVersion++;
    searchTimer = Timer(
      const Duration(milliseconds: 400),
      () => load(apply: true),
    );
  }

  String dateText(DateTime value) => value.toIso8601String().substring(0, 10);

  Future<void> chooseDate(bool from) async {
    final value = await showDatePicker(
      context: context,
      initialDate: (from ? start : end) ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (mounted && value != null) {
      setState(() {
        if (from) {
          start = value;
        } else {
          end = value;
        }
      });
      await load(apply: true);
    }
  }

  Future<void> load({int page = 1, bool apply = false}) async {
    searchTimer?.cancel();
    final version = ++requestVersion;
    if (apply &&
        !statistics &&
        start != null &&
        end != null &&
        start!.isAfter(end!)) {
      setState(() {
        error = 'From date must be before or equal to To date';
        busy = false;
      });
      return;
    }
    if (apply) {
      appliedSearch = search.text.trim();
      appliedStart = start;
      appliedEnd = end;
    }
    setState(() {
      busy = true;
      error = null;
    });
    final query = Uri(
      queryParameters: {
        'page': '$page',
        'manager_id': '$managerId',
        if (selected == 'activations') 'search': appliedSearch,
        if (selected == 'money-transfers') 'operation': operation,
        if (statistics) ...{
          'period': period,
          'year': '$year',
          'month': '$month',
        },
        if (!statistics && appliedStart != null)
          'date_start': dateText(appliedStart!),
        if (!statistics && appliedEnd != null)
          'date_end': dateText(appliedEnd!),
      },
    ).query;
    try {
      final data = await widget.api.request(
        '/integrations/sas4/reports/$selected?$query',
      );
      if (mounted && version == requestVersion) {
        setState(() => result = Map<String, dynamic>.from(data));
      }
    } catch (e) {
      if (mounted && version == requestVersion) {
        setState(() {
          error = e.toString();
          result = null;
        });
      }
    } finally {
      if (mounted && version == requestVersion) setState(() => busy = false);
    }
  }

  String display(dynamic value, String key) {
    if (value == null) return '—';
    if (key == 'paid' || key == 'refunded') {
      if (value == true || value == 1 || value == '1') return tr('Yes');
      if (value == false || value == 0 || value == '0') return tr('No');
    }
    return '$value';
  }

  @override
  Widget build(BuildContext context) {
    final columns = result?['columns'] as List? ?? [];
    final rows = result?['rows'] as List? ?? [];
    final page = result?['page'] as int? ?? 1;
    final lastPage = result?['last_page'] as int? ?? 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppText(
          'SAS4 Reports',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 240,
              child: DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: reports.any((r) => r['id'] == selected)
                    ? selected
                    : null,
                decoration: InputDecoration(labelText: tr('Report type')),
                items: reports
                    .map(
                      (r) => DropdownMenuItem<String>(
                        value: r['id'],
                        child: AppText(r['name']),
                      ),
                    )
                    .toList(),
                onChanged: busy
                    ? null
                    : (value) {
                        if (value != null) {
                          setState(() {
                            selected = value;
                            result = null;
                          });
                          load(apply: true);
                        }
                      },
              ),
            ),
            if (selected == 'activations')
              SizedBox(
                width: 230,
                child: TextField(
                  key: const ValueKey('sas4-report-search'),
                  controller: search,
                  enabled: reports.isNotEmpty,
                  maxLength: 200,
                  decoration: InputDecoration(
                    labelText: tr('Search'),
                    counterText: '',
                    prefixIcon: const Icon(Icons.search),
                  ),
                  onChanged: searchChanged,
                  onSubmitted: (_) => load(apply: true),
                ),
              ),
            if (!statistics)
              OutlinedButton.icon(
                onPressed: busy ? null : () => chooseDate(true),
                icon: const Icon(Icons.calendar_today, size: 16),
                label: Text(
                  start == null
                      ? tr('From date')
                      : '${tr('From date')}: ${dateText(start!)}',
                ),
              ),
            if (!statistics)
              OutlinedButton.icon(
                onPressed: busy ? null : () => chooseDate(false),
                icon: const Icon(Icons.calendar_today, size: 16),
                label: Text(
                  end == null
                      ? tr('To date')
                      : '${tr('To date')}: ${dateText(end!)}',
                ),
              ),
            if (!statistics && (start != null || end != null))
              IconButton(
                tooltip: tr('Clear dates'),
                onPressed: busy
                    ? null
                    : () {
                        setState(() {
                          start = null;
                          end = null;
                        });
                        load(apply: true);
                      },
                icon: const Icon(Icons.clear),
              ),
            if (selected == 'money-transfers')
              SizedBox(
                width: 180,
                child: DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: operation,
                  decoration: InputDecoration(labelText: tr('Operation')),
                  items: const [
                    DropdownMenuItem(
                      value: 'deposit',
                      child: AppText('Deposit'),
                    ),
                    DropdownMenuItem(
                      value: 'withdrawal',
                      child: AppText('Withdrawal'),
                    ),
                  ],
                  onChanged: busy
                      ? null
                      : (value) {
                          if (value != null) {
                            setState(() => operation = value);
                            load(apply: true);
                          }
                        },
                ),
              ),
            if (statistics) ...[
              SizedBox(
                width: 120,
                child: DropdownButtonFormField<int>(
                  isExpanded: true,
                  initialValue: month,
                  decoration: InputDecoration(labelText: tr('Month')),
                  items: [
                    for (var m = 1; m <= 12; m++)
                      DropdownMenuItem(value: m, child: Text('$m')),
                  ],
                  onChanged: busy
                      ? null
                      : (value) {
                          if (value != null) {
                            setState(() => month = value);
                            load(apply: true);
                          }
                        },
                ),
              ),
              SizedBox(
                width: 150,
                child: DropdownButtonFormField<String>(
                  isExpanded: true,
                  initialValue: period,
                  decoration: InputDecoration(labelText: tr('Group by')),
                  items: const [
                    DropdownMenuItem(value: 'daily', child: AppText('Daily')),
                    DropdownMenuItem(
                      value: 'monthly',
                      child: AppText('Monthly'),
                    ),
                  ],
                  onChanged: busy
                      ? null
                      : (value) {
                          if (value != null) {
                            setState(() => period = value);
                            load(apply: true);
                          }
                        },
                ),
              ),
              SizedBox(
                width: 120,
                child: DropdownButtonFormField<int>(
                  isExpanded: true,
                  initialValue: year,
                  decoration: InputDecoration(labelText: tr('Year')),
                  items: [
                    for (var y = DateTime.now().year; y >= 2017; y--)
                      DropdownMenuItem(value: y, child: Text('$y')),
                  ],
                  onChanged: busy
                      ? null
                      : (value) {
                          if (value != null) {
                            setState(() => year = value);
                            load(apply: true);
                          }
                        },
                ),
              ),
            ],
            SizedBox(
              width: 230,
              child: Autocomplete<Map<String, dynamic>>(
                displayStringForOption: (manager) =>
                    manager['username'] as String,
                optionsBuilder: (value) {
                  final query = value.text.trim().toLowerCase();
                  if (query.length < 2) {
                    return const Iterable<Map<String, dynamic>>.empty();
                  }
                  return managers
                      .where(
                        (manager) => (manager['username'] as String)
                            .toLowerCase()
                            .contains(query),
                      )
                      .map((manager) => Map<String, dynamic>.from(manager));
                },
                onSelected: (manager) {
                  setState(() => managerId = manager['id'] as int);
                  load(apply: true);
                },
                fieldViewBuilder:
                    (context, controller, focusNode, onSubmitted) => TextField(
                      key: const ValueKey('sas4-report-manager'),
                      controller: controller,
                      focusNode: focusNode,
                      enabled: !busy,
                      decoration: InputDecoration(
                        labelText: tr('SAS4 manager'),
                        hintText: tr('All managers'),
                        helperText: tr('Type at least 2 letters'),
                        errorText: managerError,
                        prefixIcon: const Icon(Icons.search),
                        suffixIcon: IconButton(
                          tooltip: tr('All managers'),
                          onPressed: busy
                              ? null
                              : () {
                                  controller.clear();
                                  focusNode.unfocus();
                                  if (managerId != -1) {
                                    setState(() => managerId = -1);
                                    load(apply: true);
                                  }
                                },
                          icon: const Icon(Icons.clear),
                        ),
                      ),
                      onSubmitted: (_) => onSubmitted(),
                      onChanged: (value) {
                        if (value.isEmpty && managerId != -1) {
                          setState(() => managerId = -1);
                          load(apply: true);
                        }
                      },
                    ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (busy) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (error != null && !busy)
          TextButton(
            onPressed: () => reports.isEmpty ? initialize() : load(apply: true),
            child: const AppText('Retry'),
          ),
        if (result != null) ...[
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text('${tr('Total records')}: ${result!['total']}'),
          ),
          if (rows.isEmpty && !busy)
            const Padding(
              padding: EdgeInsets.all(20),
              child: AppText('No records found for these filters.'),
            ),
          if (rows.isNotEmpty)
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingRowHeight: 40,
                dataRowMinHeight: 40,
                dataRowMaxHeight: 56,
                columnSpacing: 24,
                columns: columns
                    .map((c) => DataColumn(label: AppText(c['label'])))
                    .toList(),
                rows: rows
                    .map(
                      (row) => DataRow(
                        cells: columns
                            .map(
                              (c) => DataCell(
                                ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 250,
                                  ),
                                  child: Text(
                                    display(row[c['key']], c['key']),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ),
                            )
                            .toList(),
                      ),
                    )
                    .toList(),
              ),
            ),
          Row(
            children: [
              IconButton(
                tooltip: tr('Previous page'),
                onPressed: busy || page <= 1
                    ? null
                    : () => load(page: page - 1),
                icon: const Icon(Icons.chevron_left),
              ),
              Text('$page / $lastPage'),
              IconButton(
                tooltip: tr('Next page'),
                onPressed: busy || page >= lastPage
                    ? null
                    : () => load(page: page + 1),
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
