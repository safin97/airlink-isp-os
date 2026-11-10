import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Full-page device workspace. Credentials stay in the selected saved profile.
class TowerDevicePanel extends StatefulWidget {
  final Map<String, dynamic> data;
  final bool busy, stale, canEdit;
  final String? error, message;
  final Future<void> Function() onRefresh;
  final Future<void> Function(Map<String, dynamic>) onSave;
  final VoidCallback onClose, onChangeLogin;
  const TowerDevicePanel({
    super.key,
    required this.data,
    required this.busy,
    required this.stale,
    required this.canEdit,
    this.error,
    this.message,
    required this.onRefresh,
    required this.onSave,
    required this.onClose,
    required this.onChangeLogin,
  });
  @override
  State<TowerDevicePanel> createState() => _TowerDevicePanelState();
}

class _TowerDevicePanelState extends State<TowerDevicePanel> {
  Timer? timer;
  bool editing = false, automatic = true;
  int tab = 0;
  String search = '', portFilter = 'All', settingsFilter = 'All';
  Color get accent => dark ? const Color(0xff70d7df) : const Color(0xff087f8c);
  Color get green => dark ? const Color(0xff6ce0b4) : const Color(0xff087f5b);
  static const tabs = ['Overview', 'Ethernet', 'Wireless', 'Settings'];
  static const icons = [
    Icons.dashboard_outlined,
    Icons.settings_ethernet,
    Icons.wifi,
    Icons.tune,
  ];
  List<Map> rows(String key) =>
      (widget.data[key] as List? ?? []).whereType<Map>().toList();
  List<Map> get ports => rows('ethernet');
  List<Map> get radios => rows('wireless');
  List<Map> get sections => rows('tower_settings');
  bool get locked => widget.busy || widget.stale || editing;
  Map get system =>
      (widget.data['groups']?['System'] as List? ?? []).firstOrNull as Map? ??
      {};
  bool get dark => Theme.of(context).brightness == Brightness.dark;
  Color get muted => Theme.of(context).colorScheme.onSurfaceVariant;

  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted && automatic && !editing && !widget.busy && !widget.stale) {
        widget.onRefresh();
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  String value(dynamic v) => v == null || '$v'.isEmpty ? '—' : '$v';
  String rate(dynamic v) =>
      v is num ? '${(v / 1000000).toStringAsFixed(2)} Mbps' : '—';
  String speed(dynamic v) => v is num
      ? v >= 1000
            ? '${(v / 1000).toStringAsFixed(v % 1000 == 0 ? 0 : 1)} Gbps'
            : '$v Mbps'
      : '—';
  num? total(String key) {
    final known = ports.map((p) => p[key]).whereType<num>();
    return known.isEmpty ? null : known.fold<num>(0, (a, b) => a + b);
  }

  String get updated {
    final date = DateTime.tryParse('${widget.data['fetched_at']}')?.toLocal();
    return date == null
        ? 'Latest reading'
        : 'Updated ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}:${date.second.toString().padLeft(2, '0')}';
  }

  void navigate(int index) => setState(() => tab = index);
  Color statusColor(dynamic status) => status == 'running'
      ? green
      : status == 'disabled'
      ? const Color(0xffb45309)
      : muted;
  String statusLabel(dynamic status) => status == 'running'
      ? 'Running'
      : status == 'not running'
      ? 'No link'
      : status == 'disabled'
      ? 'Disabled'
      : 'Unknown';

  Widget badge(String label, Color color, {bool dot = true}) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .10),
      borderRadius: BorderRadius.circular(30),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (dot) ...[
          Icon(Icons.circle, size: 7, color: color),
          const SizedBox(width: 6),
        ],
        Text(
          label,
          style: TextStyle(
            color: color,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );

  Widget surface({
    required Widget child,
    EdgeInsets padding = const EdgeInsets.all(22),
  }) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surface,
      border: Border.all(
        color: Theme.of(
          context,
        ).colorScheme.outlineVariant.withValues(alpha: .65),
      ),
      borderRadius: BorderRadius.circular(20),
    ),
    child: child,
  );

  Widget heading(String title, String subtitle, {Widget? action}) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(subtitle, style: TextStyle(color: muted, fontSize: 13)),
            ],
          ),
        ),
        if (action != null) action,
      ],
    ),
  );

  Widget metric(
    String title,
    String number,
    String detail,
    IconData icon,
    Color color,
  ) => surface(
    padding: const EdgeInsets.all(18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(title, style: TextStyle(color: muted, fontSize: 12)),
            ),
          ],
        ),
        const SizedBox(height: 14),
        Text(
          number,
          style: const TextStyle(
            fontSize: 24,
            fontWeight: FontWeight.w700,
            letterSpacing: -.6,
          ),
        ),
        const SizedBox(height: 6),
        Text(detail, style: TextStyle(fontSize: 12, color: muted)),
      ],
    ),
  );

  Widget metrics() => LayoutBuilder(
    builder: (_, box) {
      final count = box.maxWidth >= 1000 ? 4 : 2;
      final width = (box.maxWidth - (count - 1) * 12) / count;
      final running = ports.where((p) => p['status'] == 'running').length;
      return Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          SizedBox(
            width: width,
            child: metric(
              'Ethernet ports',
              '$running / ${ports.length}',
              'Ports with a running link',
              Icons.settings_ethernet,
              accent,
            ),
          ),
          SizedBox(
            width: width,
            child: metric(
              'Receiving · RX',
              rate(total('rx_bps')),
              '${ports.where((p) => p['rx_bps'] is num).length}/${ports.length} ports reporting',
              Icons.south_west,
              const Color(0xff2563eb),
            ),
          ),
          SizedBox(
            width: width,
            child: metric(
              'Sending · TX',
              rate(total('tx_bps')),
              '${ports.where((p) => p['tx_bps'] is num).length}/${ports.length} ports reporting',
              Icons.north_east,
              green,
            ),
          ),
          SizedBox(
            width: width,
            child: metric(
              'Wireless clients',
              '${rows('registrations').length}',
              '${radios.length} wireless interfaces',
              Icons.wifi,
              const Color(0xff7c3aed),
            ),
          ),
        ],
      );
    },
  );

  Future<void> edit(Map section, Map? record, {bool remove = false}) async {
    setState(() => editing = true);
    try {
      final change = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (_) => _SettingsEditor(
          section: section,
          record: record,
          interfaces: (widget.data['interfaces'] as List? ?? []).cast<String>(),
          remove: remove,
        ),
      );
      if (change != null && mounted) await widget.onSave(change);
    } finally {
      if (mounted) setState(() => editing = false);
    }
  }

  void editInterface(String name, {bool wireless = false}) {
    for (final section in sections) {
      if (wireless
          ? !['wireless', 'wifi', 'wifiwave2'].contains(section['resource'])
          : section['resource'] != 'ethernet') {
        continue;
      }
      for (final row in section['rows'] as List? ?? []) {
        if (row['values']?['name'] == name &&
            row['editable'] == true &&
            widget.canEdit &&
            !locked) {
          edit(section, row as Map);
          return;
        }
      }
    }
    setState(() {
      tab = wireless ? 2 : 1;
      search = name;
    });
  }

  Widget portMap() => surface(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        heading(
          'Port overview',
          'Select a port to view or edit it.',
          action: TextButton(
            onPressed: () => navigate(1),
            child: const Text('View all'),
          ),
        ),
        if (ports.isEmpty)
          empty(
            Icons.settings_ethernet,
            'No Ethernet ports reported',
            'Check the device API read permissions.',
          )
        else
          LayoutBuilder(
            builder: (_, box) {
              final columns = (box.maxWidth / 108).floor().clamp(2, 12);
              final width = (box.maxWidth - (columns - 1) * 8) / columns;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final port in ports)
                    SizedBox(
                      width: width,
                      child: Material(
                        color: statusColor(
                          port['status'],
                        ).withValues(alpha: .06),
                        borderRadius: BorderRadius.circular(12),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: widget.busy || editing
                              ? null
                              : () => editInterface('${port['name']}'),
                          child: Tooltip(
                            message:
                                '${port['name']} · ${statusLabel(port['status'])} · ${speed(port['speed_mbps'])}',
                            child: Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                                vertical: 14,
                              ),
                              child: Column(
                                children: [
                                  Icon(
                                    Icons.settings_ethernet,
                                    color: statusColor(port['status']),
                                    size: 26,
                                  ),
                                  const SizedBox(height: 7),
                                  Text(
                                    value(port['name']),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 12,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    statusLabel(port['status']),
                                    style: TextStyle(
                                      color: statusColor(port['status']),
                                      fontSize: 10,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              );
            },
          ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          runSpacing: 8,
          children: [
            badge('Running', green),
            badge('No link / unknown', muted),
            badge('Disabled', const Color(0xffb45309)),
          ],
        ),
      ],
    ),
  );

  Widget empty(IconData icon, String title, String detail) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 24),
    child: Center(
      child: Column(
        children: [
          Icon(icon, color: muted.withValues(alpha: .6), size: 36),
          const SizedBox(height: 12),
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text(
            detail,
            textAlign: TextAlign.center,
            style: TextStyle(color: muted, fontSize: 13),
          ),
        ],
      ),
    ),
  );

  Widget wirelessCards() => surface(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        heading(
          'Wireless interfaces (${radios.length})',
          'SSID, signal and traffic at a glance.',
        ),
        if (radios.isEmpty)
          empty(
            Icons.wifi_off_outlined,
            'No wireless interfaces reported',
            'This device may be Ethernet-only.',
          )
        else
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              for (final radio in radios)
                LayoutBuilder(
                  builder: (_, box) => Container(
                    width: box.maxWidth >= 680
                        ? (box.maxWidth - 12) / 2
                        : box.maxWidth,
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: accent.withValues(alpha: .04),
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: accent.withValues(alpha: .12)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(Icons.wifi, color: accent),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                value(radio['name']),
                                style: TextStyle(color: muted),
                              ),
                            ),
                            badge(
                              statusLabel(radio['status']),
                              statusColor(radio['status']),
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Text(
                          value(radio['ssid']),
                          style: const TextStyle(
                            fontSize: 21,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 20,
                          runSpacing: 10,
                          children: [
                            Text(
                              'Signal  ${radio['signal_dbm'] == null ? '—' : '${radio['signal_dbm']} dBm'}',
                            ),
                            Text('RX  ${rate(radio['rx_bps'])}'),
                            Text('TX  ${rate(radio['tx_bps'])}'),
                          ],
                        ),
                        if (widget.canEdit)
                          Padding(
                            padding: const EdgeInsets.only(top: 12),
                            child: TextButton.icon(
                              onPressed: locked
                                  ? null
                                  : () => editInterface(
                                      '${radio['name']}',
                                      wireless: true,
                                    ),
                              icon: const Icon(Icons.tune, size: 17),
                              label: const Text('Wireless settings'),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
      ],
    ),
  );

  Widget table(
    String title,
    List<Map> data,
    List<String> labels,
    List<Widget> Function(Map) cells,
  ) => surface(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        heading(
          '$title (${data.length})',
          'Readings from the latest successful refresh.',
        ),
        if (data.isEmpty)
          empty(
            Icons.search_off,
            'No results',
            'Try another filter or refresh the readings.',
          )
        else
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowColor: WidgetStatePropertyAll(
                accent.withValues(alpha: .05),
              ),
              horizontalMargin: 12,
              columnSpacing: 28,
              columns: [
                for (final label in labels)
                  DataColumn(
                    label: Text(
                      label,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
              ],
              rows: [
                for (final row in data)
                  DataRow(
                    cells: [for (final cell in cells(row)) DataCell(cell)],
                  ),
              ],
            ),
          ),
      ],
    ),
  );

  Widget ethernet() {
    final filtered = ports
        .where(
          (p) =>
              '${p['name']}'.toLowerCase().contains(search.toLowerCase()) &&
              (portFilter == 'All' ||
                  (portFilter == 'Running'
                      ? p['status'] == 'running'
                      : p['status'] != 'running')),
        )
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        heading(
          'Ethernet',
          'All physical ports, including SFP. RX / TX are from the device perspective.',
        ),
        Wrap(
          spacing: 16,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 270,
              child: TextFormField(
                key: ValueKey('port-search-$tab'),
                initialValue: search,
                onChanged: (v) => setState(() => search = v),
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  labelText: 'Search ports',
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            for (final filter in ['All', 'Running', 'Inactive'])
              ChoiceChip(
                label: Text(filter),
                selected: portFilter == filter,
                onSelected: (_) => setState(() => portFilter = filter),
              ),
          ],
        ),
        const SizedBox(height: 20),
        table(
          'Ethernet ports',
          filtered,
          [
            'Port',
            'Status',
            'Link speed',
            'Duplex',
            'RX traffic',
            'TX traffic',
            if (widget.canEdit) 'Settings',
          ],
          (r) => [
            Text(
              value(r['name']),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            badge(statusLabel(r['status']), statusColor(r['status'])),
            Text(speed(r['speed_mbps'])),
            Text(
              r['full_duplex'] == null
                  ? '—'
                  : '${r['full_duplex']}' == 'true'
                  ? 'Full'
                  : 'Half',
            ),
            Text(rate(r['rx_bps'])),
            Text(rate(r['tx_bps'])),
            if (widget.canEdit)
              IconButton(
                tooltip: 'Edit ${r['name']}',
                onPressed: locked ? null : () => editInterface('${r['name']}'),
                icon: const Icon(Icons.tune, size: 18),
              ),
          ],
        ),
      ],
    );
  }

  IconData sectionIcon(dynamic resource) => switch (resource) {
    'ethernet' => Icons.settings_ethernet,
    'wireless' || 'wifi' || 'wifiwave2' => Icons.wifi,
    'addresses' => Icons.lan_outlined,
    'dns' => Icons.public,
    'routes' => Icons.alt_route,
    _ => Icons.router_outlined,
  };
  String sectionHint(dynamic resource) => switch (resource) {
    'ethernet' => 'Port names, link settings and enabled state',
    'wireless' ||
    'wifi' ||
    'wifiwave2' => 'Network name, frequency and radio settings',
    'addresses' => 'Manage IPv4 addresses and interfaces',
    'dns' => 'Name servers and DNS requests',
    'routes' => 'Destinations, gateways and priorities',
    _ => 'Give this device a recognizable name',
  };

  Widget settings(Map section) {
    final records = section['rows'] as List? ?? [];
    final labels = {
      for (final f in section['fields'] as List? ?? []) f['key']: f['label'],
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: surface(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: ExpansionTile(
          key: PageStorageKey('settings-${section['resource']}'),
          shape: const Border(),
          collapsedShape: const Border(),
          leading: Icon(sectionIcon(section['resource']), color: accent),
          title: Text(
            '${section['title']} settings (${records.length})',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          subtitle: Text(
            sectionHint(section['resource']),
            style: TextStyle(color: muted, fontSize: 12),
          ),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (section['can_add'] == true && widget.canEdit)
              TextButton.icon(
                onPressed: locked ? null : () => edit(section, null),
                icon: const Icon(Icons.add),
                label: Text('Add ${section['title']}'),
              ),
            for (final item in records)
              Builder(
                builder: (_) {
                  final row = item as Map;
                  final values = row['values'] as Map;
                  final enabled =
                      widget.canEdit && row['editable'] == true && !locked;
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: ListTile(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      tileColor: accent.withValues(alpha: .04),
                      title: Text(
                        '${values['name'] ?? values['address'] ?? values['dst-address'] ?? section['title']}',
                      ),
                      subtitle: Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          [
                            for (final entry in values.entries)
                              '${labels[entry.key] ?? entry.key}: ${value(entry.value)}',
                            if (row['reason'] != null) '${row['reason']}',
                          ].join(' • '),
                        ),
                      ),
                      trailing: widget.canEdit
                          ? Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  tooltip: 'Edit ${section['title']}',
                                  onPressed: enabled
                                      ? () => edit(section, row)
                                      : null,
                                  icon: const Icon(
                                    Icons.edit_outlined,
                                    size: 20,
                                  ),
                                ),
                                if (section['can_delete'] == true)
                                  IconButton(
                                    tooltip: 'Delete ${section['title']}',
                                    onPressed: enabled
                                        ? () => edit(section, row, remove: true)
                                        : null,
                                    icon: const Icon(
                                      Icons.delete_outline,
                                      size: 20,
                                    ),
                                  ),
                              ],
                            )
                          : const Icon(Icons.lock_outline, size: 18),
                    ),
                  );
                },
              ),
            if (records.isEmpty)
              const Padding(
                padding: EdgeInsets.all(12),
                child: Text('No configured records.'),
              ),
          ],
        ),
      ),
    );
  }

  Widget settingsPage() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading(
        'Device settings',
        widget.canEdit
            ? 'Choose a section. Every change has a review step before it is saved.'
            : 'Read-only. Your account needs Towers edit permission to change settings.',
      ),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          ChoiceChip(
            label: const Text('All settings'),
            selected: settingsFilter == 'All',
            onSelected: (_) => setState(() => settingsFilter = 'All'),
          ),
          for (final section in sections)
            ChoiceChip(
              label: Text('${section['title']}'),
              selected: settingsFilter == section['resource'],
              onSelected: (_) =>
                  setState(() => settingsFilter = '${section['resource']}'),
            ),
        ],
      ),
      const SizedBox(height: 20),
      for (final section in sections)
        if (settingsFilter == 'All' || settingsFilter == section['resource'])
          settings(section),
    ],
  );

  Widget overview() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      metrics(),
      const SizedBox(height: 22),
      surface(
        child: Wrap(
          spacing: 36,
          runSpacing: 18,
          children: [
            for (final entry in {
              'Model': system['board-name'],
              'RouterOS': system['version'],
              'Uptime': system['uptime'],
              'CPU usage': system['cpu-load'] == null
                  ? null
                  : '${system['cpu-load']}%',
            }.entries)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(entry.key, style: TextStyle(color: muted, fontSize: 12)),
                  const SizedBox(height: 5),
                  Text(
                    value(entry.value),
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 15,
                    ),
                  ),
                ],
              ),
          ],
        ),
      ),
      const SizedBox(height: 22),
      portMap(),
      const SizedBox(height: 22),
      wirelessCards(),
      const SizedBox(height: 22),
      surface(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            heading(
              'Quick settings',
              widget.canEdit
                  ? 'Everything you need to manage this device.'
                  : 'View the device configuration. Editing requires Towers edit permission.',
            ),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final section in sections)
                  OutlinedButton.icon(
                    onPressed: () => setState(() {
                      settingsFilter = '${section['resource']}';
                      tab = 3;
                    }),
                    icon: Icon(sectionIcon(section['resource']), size: 18),
                    label: Text('${section['title']}'),
                  ),
              ],
            ),
          ],
        ),
      ),
    ],
  );

  Widget notice(String text, {bool error = false}) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: (error ? const Color(0xffb45309) : accent).withValues(alpha: .09),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          error ? Icons.info_outline : Icons.check_circle_outline,
          size: 20,
          color: error ? const Color(0xffb45309) : accent,
        ),
        const SizedBox(width: 10),
        Expanded(child: Text(text)),
      ],
    ),
  );

  Widget navigation() {
    final compact = MediaQuery.sizeOf(context).width < 600;
    Widget button(int i) => Semantics(
      selected: tab == i,
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 2 : 4,
          vertical: 10,
        ),
        child: TextButton(
          key: ValueKey('device-tab-$i'),
          onPressed: () => navigate(i),
          style: TextButton.styleFrom(
            foregroundColor: tab == i ? accent : muted,
            backgroundColor: tab == i
                ? accent.withValues(alpha: .10)
                : Colors.transparent,
            padding: EdgeInsets.symmetric(
              horizontal: compact ? 4 : 16,
              vertical: 12,
            ),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
          child: compact
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(icons[i], size: 20),
                    const SizedBox(height: 5),
                    Text(tabs[i], style: const TextStyle(fontSize: 11)),
                  ],
                )
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(icons[i], size: 18),
                    const SizedBox(width: 8),
                    Text(tabs[i]),
                  ],
                ),
        ),
      ),
    );
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1440),
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 16),
            child: Row(
              children: [
                if (compact) ...[
                  for (var i = 0; i < tabs.length; i++)
                    Expanded(child: button(i)),
                ] else ...[
                  Expanded(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          for (var i = 0; i < tabs.length; i++) button(i),
                        ],
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Refresh device',
                    onPressed: widget.busy || editing ? null : widget.onRefresh,
                    icon: Icon(Icons.refresh, color: accent),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Dialog.fullscreen(
    child: ColoredBox(
      color: dark ? const Color(0xff121c25) : const Color(0xfff4f7fa),
      child: Column(
        children: [
          Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                colors: [Color(0xff102e41), Color(0xff0d545e)],
              ),
            ),
            child: SafeArea(
              bottom: false,
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1440),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(24, 18, 16, 20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.hub_outlined,
                              color: Color(0xff7cdbd4),
                              size: 18,
                            ),
                            const SizedBox(width: 8),
                            const Expanded(
                              child: Text(
                                'AIRLINK  /  DEVICE MANAGER',
                                style: TextStyle(
                                  color: Color(0xffb6d5dc),
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 1.5,
                                ),
                              ),
                            ),
                            if (MediaQuery.sizeOf(context).width < 600)
                              IconButton(
                                tooltip: 'Refresh device',
                                onPressed: widget.busy || editing
                                    ? null
                                    : widget.onRefresh,
                                icon: const Icon(
                                  Icons.refresh,
                                  color: Colors.white,
                                ),
                              ),
                            IconButton(
                              tooltip: 'Close',
                              onPressed: widget.busy || editing
                                  ? null
                                  : widget.onClose,
                              icon: const Icon(
                                Icons.close,
                                color: Colors.white,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Wrap(
                          spacing: 12,
                          runSpacing: 8,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              '${widget.data['username'] ?? 'MikroTik device'}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 28,
                                fontWeight: FontWeight.w700,
                                letterSpacing: -.7,
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 5,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: .12),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                widget.stale
                                    ? 'Needs refresh'
                                    : widget.busy
                                    ? 'Refreshing…'
                                    : 'Connected',
                                style: TextStyle(
                                  color: widget.stale
                                      ? const Color(0xffffd491)
                                      : const Color(0xff91eed5),
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Wrap(
                          spacing: 14,
                          runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              'MikroTik · ${widget.data['ip_address'] ?? ''}',
                              style: const TextStyle(color: Color(0xffc0d7dc)),
                            ),
                            IconButton(
                              tooltip: 'Copy IP address',
                              visualDensity: VisualDensity.compact,
                              onPressed: () => Clipboard.setData(
                                ClipboardData(
                                  text: '${widget.data['ip_address'] ?? ''}',
                                ),
                              ),
                              icon: const Icon(
                                Icons.copy_outlined,
                                color: Color(0xffc0d7dc),
                                size: 15,
                              ),
                            ),
                            Text(
                              'Login: ${widget.data['credential_source'] ?? ''}',
                              style: const TextStyle(
                                color: Color(0xff9fbec6),
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
          if (widget.busy) LinearProgressIndicator(minHeight: 2, color: accent),
          navigation(),
          Expanded(
            child: SingleChildScrollView(
              key: ValueKey('device-page-$tab'),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1440),
                  child: Padding(
                    padding: EdgeInsets.all(
                      MediaQuery.sizeOf(context).width < 600 ? 14 : 24,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                widget.stale
                                    ? 'Refresh to verify the current device state.'
                                    : '$updated · ${editing
                                          ? 'Refresh paused while editing'
                                          : automatic
                                          ? 'Live readings every 15s'
                                          : 'Automatic refresh paused'}',
                                style: TextStyle(color: muted, fontSize: 12),
                              ),
                            ),
                            const Text('Auto', style: TextStyle(fontSize: 12)),
                            Transform.scale(
                              scale: .8,
                              child: Switch(
                                value: automatic,
                                onChanged: (v) => setState(() => automatic = v),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        if (widget.error != null)
                          notice(widget.error!, error: true),
                        if (widget.message != null) notice(widget.message!),
                        for (final warning
                            in widget.data['warnings'] as List? ?? [])
                          notice('$warning', error: true),
                        if (tab == 0) overview(),
                        if (tab == 1) ethernet(),
                        if (tab == 2) ...[
                          wirelessCards(),
                          const SizedBox(height: 20),
                          table(
                            'Registered clients',
                            rows('registrations'),
                            [
                              'Interface',
                              'MAC address',
                              'Signal',
                              'RX rate',
                              'TX rate',
                              'Uptime',
                            ],
                            (r) => [
                              for (final v in [
                                r['interface'],
                                r['mac-address'],
                                r['signal-strength'] ?? r['signal'],
                                r['rx-rate'],
                                r['tx-rate'],
                                r['uptime'],
                              ])
                                Text(value(v)),
                            ],
                          ),
                        ],
                        if (tab == 3) settingsPage(),
                        const SizedBox(height: 22),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: widget.busy || editing
                                ? null
                                : widget.onChangeLogin,
                            icon: const Icon(Icons.swap_horiz, size: 18),
                            label: const Text('Change device login'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

class _SettingsEditor extends StatefulWidget {
  final Map section;
  final Map? record;
  final List<String> interfaces;
  final bool remove;
  const _SettingsEditor({
    required this.section,
    required this.record,
    required this.interfaces,
    required this.remove,
  });
  @override
  State<_SettingsEditor> createState() => _SettingsEditorState();
}

class _SettingsEditorState extends State<_SettingsEditor> {
  final controllers = <String, TextEditingController>{};
  final touched = <String>{};
  final form = GlobalKey<FormState>();
  bool review = false;
  late final Map<String, dynamic> previous = Map<String, dynamic>.from(
    widget.record?['values'] ?? {},
  );
  late final List fields = widget.section['fields'] as List;
  @override
  void initState() {
    super.initState();
    for (final field in fields) {
      final key = '${field['key']}';
      controllers[key] = TextEditingController(text: '${previous[key] ?? ''}');
    }
  }

  @override
  void dispose() {
    for (final c in controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Map<String, String> changes() => {
    for (final key in touched)
      if (controllers[key]!.text != previous[key]) key: controllers[key]!.text,
  };
  @override
  Widget build(BuildContext context) {
    final diff = changes();
    return AlertDialog(
      title: Text(
        '${widget.remove
            ? 'Delete'
            : widget.record == null
            ? 'Add'
            : 'Edit'} ${widget.section['title']}',
      ),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (review || widget.remove) ...[
                  const Text(
                    'Review changes before sending them to the device.',
                  ),
                  const SizedBox(height: 12),
                  if (widget.remove)
                    Text(
                      'Delete: ${previous.entries.map((e) => '${e.key}: ${e.value}').join(', ')}',
                    )
                  else
                    for (final entry in diff.entries)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Text(
                          '${entry.key}: ${previous[entry.key] ?? '(unset)'} → ${entry.value.isEmpty ? '(empty)' : entry.value}',
                        ),
                      ),
                  const SizedBox(height: 16),
                  const Text(
                    'Changing a port, wireless, IP address, DNS or route may disconnect this device or its clients. If the connection is lost, reconnect and verify before retrying.',
                  ),
                ] else
                  for (final f in fields)
                    Builder(
                      builder: (_) {
                        final key = '${f['key']}';
                        final controller = controllers[key]!;
                        if (f['kind'] == 'bool') {
                          return SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text('${f['label']}'),
                            value: controller.text == 'true',
                            onChanged: (v) => setState(() {
                              controller.text = '$v';
                              touched.add(key);
                            }),
                          );
                        }
                        if (f['kind'] == 'interface') {
                          return DropdownButtonFormField<String>(
                            initialValue:
                                widget.interfaces.contains(controller.text)
                                ? controller.text
                                : null,
                            decoration: InputDecoration(
                              labelText: '${f['label']}',
                            ),
                            isExpanded: true,
                            items: [
                              for (final name in widget.interfaces.toSet())
                                DropdownMenuItem(
                                  value: name,
                                  child: Text(name),
                                ),
                            ],
                            onChanged: (v) => setState(() {
                              controller.text = v ?? '';
                              touched.add(key);
                            }),
                            validator: (_) =>
                                widget.record == null && controller.text.isEmpty
                                ? 'Choose an interface'
                                : null,
                          );
                        }
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: TextFormField(
                            controller: controller,
                            decoration: InputDecoration(
                              labelText: '${f['label']}',
                            ),
                            onChanged: (_) => setState(() => touched.add(key)),
                            validator: (v) {
                              if ((widget.record == null ||
                                      touched.contains(key)) &&
                                  [
                                    'name',
                                    'address',
                                    'dst-address',
                                    'gateway',
                                    'ssid',
                                    'configuration.ssid',
                                  ].contains(key) &&
                                  (v ?? '').isEmpty) {
                                return 'Required';
                              }
                              if (touched.contains(key) &&
                                  f['kind'] == 'number' &&
                                  int.tryParse(v ?? '') == null) {
                                return 'Enter a whole number';
                              }
                              return null;
                            },
                          ),
                        );
                      },
                    ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        if (review)
          TextButton(
            onPressed: () => setState(() => review = false),
            child: const Text('Back'),
          ),
        FilledButton(
          onPressed: widget.remove || review
              ? () => Navigator.pop(context, <String, dynamic>{
                  'resource': widget.section['resource'],
                  'action': widget.remove
                      ? 'remove'
                      : widget.record == null
                      ? 'add'
                      : 'set',
                  'record_id': widget.record?['id'] ?? '',
                  'previous': {
                    ...previous,
                    for (final key in diff.keys)
                      if (!previous.containsKey(key)) key: null,
                  },
                  'changes': widget.remove ? <String, String>{} : diff,
                })
              : () {
                  if (form.currentState!.validate() && changes().isNotEmpty) {
                    setState(() => review = true);
                  }
                },
          child: Text(
            widget.remove
                ? 'Delete from device'
                : review
                ? 'Save to device'
                : 'Review',
          ),
        ),
      ],
    );
  }
}
