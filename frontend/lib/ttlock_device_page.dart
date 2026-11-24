import 'section_access.dart';
import 'dart:math';
import 'dart:async';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'ttlock_style.dart';
import 'ttlock_records.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'ttlock_mobile_service.dart';

class TTLockDevicePage extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> lock;
  final int lockPage;
  final TTLockMobileService? service;
  final String initialTab;
  const TTLockDevicePage({
    super.key,
    required this.api,
    required this.lock,
    required this.lockPage,
    this.service,
    this.initialTab = 'card',
  });
  @override
  State<TTLockDevicePage> createState() => _TTLockDevicePageState();
}

class _TTLockDevicePageState extends State<TTLockDevicePage> {
  late final service = widget.service ?? TTLockMobileService(widget.api);
  bool busy = false, loading = true;
  String? error, message;
  DateTime? bluetoothVerifiedAt;
  int? bluetoothBattery;
  int page = 1, pages = 0;
  String kind = 'card';
  late String tab = widget.initialTab;
  String lockState = 'unknown';
  String? checkedAt, rawRecords;
  List<Map<String, dynamic>>? records;
  bool confirming = false;
  Timer? stateExpiry;
  final revealed = <int>{};
  String get credentialLabel => kind == 'card' ? 'card' : kind;
  String get credentialTitle => kind == 'card'
      ? 'Access cards'
      : kind == 'passcode'
      ? 'Passcodes'
      : 'Fingerprints';
  List<Map<String, dynamic>> cards = [], pending = [];
  String get path => '/integrations/ttlock/locks/${widget.lock['id']}';
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'ttlock');
  bool get canDelete => canDeleteSection(widget.api.user ?? {}, 'ttlock');
  bool get mobile => service.bluetooth.available || service.remote;
  @override
  void initState() {
    super.initState();
    if (['card', 'passcode', 'fingerprint'].contains(tab)) kind = tab;
    load();
    stateExpiry = Timer.periodic(const Duration(seconds: 30), (_) {
      final checked = DateTime.tryParse(checkedAt ?? '');
      if (mounted &&
          checked != null &&
          DateTime.now().difference(checked).inMinutes >= 2 &&
          lockState != 'unknown') {
        setState(() => lockState = 'unknown');
      }
    });
  }

  @override
  void dispose() {
    stateExpiry?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = ['card', 'passcode', 'fingerprint'].contains(tab)
          ? await widget.api.request(
              '$path/credentials/$kind?page=$page&lock_page=${widget.lockPage}',
            )
          : {'items': <dynamic>[], 'pages': 0};
      final work = await widget.api.request(
        '/integrations/ttlock/mobile/pending',
      );
      if (mounted) {
        setState(() {
          cards = (result['items'] as List)
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
          pages = result['pages'];
          pending = (work['items'] as List)
              .map((e) => Map<String, dynamic>.from(e))
              .where((e) => e['lock_id'] == widget.lock['id'])
              .toList();
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void progress(String value) {
    if (mounted) setState(() => message = value);
  }

  Future<void> perform(Future<void> Function() action) async {
    if (busy || loading) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString());
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Action not completed. $e')));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> connectBluetooth() => perform(() async {
    setState(() {
      bluetoothVerifiedAt = null;
      bluetoothBattery = null;
    });
    progress('Connecting to ${widget.lock['name']} over Bluetooth…');
    final result = await service.command(
      widget.lock['id'],
      widget.lockPage,
      'battery',
      const {},
      progress,
    );
    if (!mounted) return;
    final battery = result['battery'];
    setState(() {
      bluetoothVerifiedAt = DateTime.now();
      bluetoothBattery = battery is int && battery >= 0 && battery <= 100
          ? battery
          : null;
      message =
          'Bluetooth communication verified. You can now manage this lock nearby.';
    });
  });

  Future<bool> confirm(String title, String detail) async {
    if (busy || loading || confirming) return false;
    confirming = true;
    final answer = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(detail),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
    confirming = false;
    return answer == true;
  }

  Future<void> cardAction(String action, [Map<String, dynamic>? card]) async {
    Map<String, dynamic>? values;
    if (action.endsWith('_delete')) {
      if (!await confirm(
        'Remove $credentialLabel?',
        'Remove ${card!['name']} from ${widget.lock['name']}? This $credentialLabel will lose access after the lock confirms deletion.',
      )) {
        return;
      }
      values = {};
    } else {
      values = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (_) => TTLockCardForm(
          card: card,
          periodOnly: action.endsWith('_period'),
          kind: kind,
        ),
      );
    }
    if (values == null || !mounted) return;
    await perform(() async {
      final result = await service.run({
        'action': action,
        'lock_id': widget.lock['id'],
        'lock_page': widget.lockPage,
        'card_page': page,
        if (card != null) 'card_id': card['id'],
        ...values!,
      }, progress);
      progress(
        result['status'] == 'synced'
            ? 'Device change confirmed and synced.'
            : result['message'],
      );
      await load();
    });
  }

  Future<void> rename(Map<String, dynamic> card) async {
    var name = card['name'] as String;
    final form = GlobalKey<FormState>();
    final value = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Rename $credentialLabel'),
        content: Form(
          key: form,
          child: TextFormField(
            initialValue: name,
            maxLength: 100,
            decoration: const InputDecoration(labelText: 'Name'),
            onChanged: (value) => name = value,
            validator: (value) =>
                value == null || value.trim().isEmpty ? 'Enter a name' : null,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (form.currentState!.validate()) {
                Navigator.pop(context, name.trim());
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (value == null || !mounted) return;
    await perform(() async {
      await widget.api.request(
        '$path/credentials/$kind/${card['id']}/name?lock_page=${widget.lockPage}',
        method: 'PUT',
        body: {'name': value, 'page': page},
        retry: false,
      );
      progress('Name updated.');
      await load();
    });
  }

  Future<void> command(
    String action,
    String label, {
    Map<String, dynamic> options = const {},
  }) async {
    if (['lock', 'unlock', 'time'].contains(action) &&
        !await confirm(
          '$label?',
          service.remote
              ? '${widget.lock['name']} • approve this request on ${service.phoneName} near the lock.'
              : mobile
              ? '${widget.lock['name']} • stay near this lock with Bluetooth enabled.'
              : '${widget.lock['name']} • TTLock must authorize the command through the linked gateway.',
        )) {
      return;
    }
    await perform(() async {
      lockState = 'unknown';
      final Map<String, dynamic> result;
      if (mobile) {
        result = await service.command(
          widget.lock['id'],
          widget.lockPage,
          action,
          options,
          progress,
        );
      } else if (widget.lock['has_gateway'] == true && action == 'status') {
        result = Map<String, dynamic>.from(
          await widget.api.request('$path/state?page=${widget.lockPage}'),
        );
      } else if (widget.lock['has_gateway'] == true &&
          ['lock', 'unlock'].contains(action)) {
        final random = Random.secure();
        result = Map<String, dynamic>.from(
          await widget.api.request(
            '$path/action',
            method: 'POST',
            retry: false,
            body: {
              'action': action,
              'page': widget.lockPage,
              'request_id': List.generate(
                32,
                (_) => random.nextInt(16).toRadixString(16),
              ).join(),
            },
          ),
        );
      } else {
        throw Exception(
          'Connect a nearby phone to use this Bluetooth operation.',
        );
      }
      if (action == 'status') {
        checkedAt = DateTime.now().toIso8601String();
        lockState = switch (result['state']) {
          'lock' || 'locked' => 'locked',
          'unlock' || 'unlocked' => 'unlocked',
          _ => 'unknown',
        };
      }
      if (result['battery'] is int) bluetoothBattery = result['battery'];
      if (!mounted) return;
      if (action == 'records') {
        rawRecords = result['records']?.toString();
        final parsed = ttParseRecords(result['records']);
        setState(() {
          records = parsed;
          tab = 'records';
        });
        progress('${parsed.length} device records loaded.');
      } else {
        progress(
          action == 'status'
              ? 'Lock state: ${result['state']}'
              : action == 'battery'
              ? 'Battery: ${result['battery']}%'
              : '$label confirmed by the lock.',
        );
      }
    });
  }

  Future<void> reset() async {
    if (!await confirm(
      'Reset and remove this lock?',
      '${widget.lock['name']} will be reset over Bluetooth. Its keys, cards, passcodes, fingerprints and cloud records will be removed. Stay near the correct lock.',
    )) {
      return;
    }
    await perform(() async {
      final result = await service.run({
        'action': 'lock_reset',
        'lock_id': widget.lock['id'],
        'lock_page': widget.lockPage,
      }, progress);
      if (!mounted) return;
      if (result['status'] == 'synced') {
        Navigator.pop(context, true);
      } else {
        progress(result['message']);
        await load();
      }
    });
  }

  String dateLabel(dynamic value) {
    if (value == 0) return 'Permanent';
    if (value is! int) return 'Not reported';
    return DateTime.fromMillisecondsSinceEpoch(
      value,
    ).toLocal().toString().split('.').first;
  }

  Future<void> selectTab(String value) async {
    if (busy || loading) return;
    setState(() {
      tab = value;
      page = 1;
      revealed.clear();
      cards = [];
      if (['card', 'passcode', 'fingerprint'].contains(value)) kind = value;
    });
    await load();
  }

  Future<void> renameLock() async {
    var name = widget.lock['name'] as String;
    final form = GlobalKey<FormState>();
    final changed = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Edit device name'),
        content: Form(
          key: form,
          child: TextFormField(
            initialValue: name,
            maxLength: 100,
            decoration: const InputDecoration(labelText: 'Device name'),
            onChanged: (s) => name = s,
            validator: (s) =>
                s == null || s.trim().isEmpty ? 'Enter a device name' : null,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (form.currentState!.validate()) Navigator.pop(c, name.trim());
            },
            child: const Text('Save name'),
          ),
        ],
      ),
    );
    if (changed == null || !mounted) return;
    await perform(() async {
      final result = await widget.api.request(
        '$path/name',
        method: 'PUT',
        retry: false,
        body: {'name': changed, 'page': widget.lockPage},
      );
      if (mounted) setState(() => widget.lock['name'] = result['name']);
      progress('Device name updated in TTLock.');
    });
  }

  @override
  Widget build(BuildContext context) =>
      TTTheme(child: Builder(builder: _screen));
  Widget _screen(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.lock['name']),
            Text(
              'Lock ID: ${widget.lock['id']}',
              style: TextStyle(fontSize: 12, color: ttMuted(context)),
            ),
          ],
        ),
        actions: [
          IconButton(
            onPressed: busy || loading ? null : load,
            tooltip: 'Refresh cards',
            icon: const Icon(LucideIcons.refreshCw),
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            color: ttSurface(context),
            width: double.infinity,
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Row(
                children: [
                  for (final item in [
                    ('Overview', 'overview', LucideIcons.lockKeyhole),
                    ('eKeys', 'ekeys', LucideIcons.keyRound),
                    ('Passcodes', 'passcode', LucideIcons.grid2x2),
                    ('Cards', 'card', LucideIcons.creditCard),
                    ('Fingerprints', 'fingerprint', LucideIcons.fingerprint),
                    ('Records', 'records', LucideIcons.history),
                    ('Settings', 'settings', LucideIcons.settings2),
                  ])
                    Padding(
                      padding: const EdgeInsetsDirectional.only(end: 8),
                      child: ChoiceChip(
                        label: Text(item.$1),
                        avatar: Icon(item.$3, size: 16),
                        selected: tab == item.$2,
                        onSelected: busy || loading
                            ? null
                            : (_) => selectTab(item.$2),
                      ),
                    ),
                ],
              ),
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                if (busy || loading)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 16),
                    child: LinearProgressIndicator(minHeight: 3),
                  ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: TTPanel(
                      child: Text(error!, style: const TextStyle(color: ttRed)),
                    ),
                  ),
                if (message != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: TTBadge(message!, icon: LucideIcons.info),
                  ),
                if (service.remote && busy)
                  TextButton(
                    onPressed: () async {
                      try {
                        await service.cancelRemote();
                      } catch (e) {
                        if (mounted) setState(() => error = e.toString());
                      }
                    },
                    child: const Text('Cancel waiting request'),
                  ),
                if (tab == 'overview') ...overview(context),
                if (['card', 'passcode', 'fingerprint'].contains(tab)) ...[
                  TTPanel(
                    child: Row(
                      children: [
                        Icon(
                          kind == 'card'
                              ? LucideIcons.creditCard
                              : kind == 'passcode'
                              ? LucideIcons.keyRound
                              : LucideIcons.fingerprint,
                          color: ttBlue,
                          size: 28,
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: Text(
                            mobile
                                ? (service.remote
                                      ? 'Changes run through ${service.phoneName}, after approval on the phone.'
                                      : 'Access changes use Bluetooth near this lock. Supported features are checked by the device SDK.')
                                : 'Use the AirLink Android or iPhone app near this lock, or select Use phone Bluetooth from the dashboard, to change access.',
                            style: TextStyle(
                              color: ttMuted(context),
                              height: 1.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  if (kind == 'passcode') ...[
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        const TTBadge(
                          'Permanent & timed',
                          icon: LucideIcons.calendarClock,
                        ),
                        for (final text in ['Recurring', 'One-time'])
                          Tooltip(
                            message:
                                'This passcode type is not supported by the current integration.',
                            child: OutlinedButton(
                              onPressed: null,
                              child: Text(text),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 16),
                  ],
                  ...credentialWidgets(context),
                  const SizedBox(height: 12),
                  Tooltip(
                    message:
                        'Assigning a TTLock user is not supported. Use credential names to label existing access.',
                    child: const OutlinedButton(
                      onPressed: null,
                      child: Text('Assign user'),
                    ),
                  ),
                ],
                if (tab == 'ekeys')
                  TTEmpty(
                    title: 'eKey management is not connected',
                    icon: LucideIcons.keyRound,
                    message:
                        'The existing integration does not expose eKey listing, sending or revocation. Manage permanent and temporary eKeys in the official TTLock app. No access has been changed.',
                    action: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final text in [
                          'Send eKey',
                          'View active eKeys',
                          'Revoke access',
                        ])
                          Tooltip(
                            message:
                                'Not supported by the current API integration.',
                            child: OutlinedButton(
                              onPressed: null,
                              child: Text(text),
                            ),
                          ),
                      ],
                    ),
                  ),
                if (tab == 'records') ...[
                  TTRecords(
                    records: records,
                    lockName: widget.lock['name'],
                    busy: busy || loading,
                    refresh: mobile
                        ? () => command('records', 'Read access records')
                        : null,
                  ),
                  if (rawRecords != null)
                    ExpansionTile(
                      title: const Text('Original device data'),
                      children: [SelectableText(rawRecords!)],
                    ),
                ],
                if (tab == 'settings') ...[
                  TTPanel(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Device settings',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Name: ${widget.lock['name']}\nLock ID: ${widget.lock['id']}',
                        ),
                        const SizedBox(height: 16),
                        OutlinedButton.icon(
                          onPressed: !canEdit || busy || loading ? null : renameLock,
                          icon: const Icon(LucideIcons.pencil, size: 16),
                          label: const Text('Edit name'),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Device names are saved to your existing TTLock account. Hardware reset requires a separate confirmation.',
                          style: TextStyle(color: ttMuted(context)),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  ...settingsWidgets(context),
                ],
              ],
            ),
          ),
        ],
      ),
    ),
  );

  List<Widget> overview(BuildContext context) {
    final canControl = mobile || widget.lock['has_gateway'] == true;
    return [
      TTPanel(
        child: LayoutBuilder(
          builder: (context, c) => Wrap(
            spacing: 32,
            runSpacing: 24,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              SizedBox(
                width: c.maxWidth < 650 ? c.maxWidth : 260,
                child: Column(
                  children: [
                    const TTLockIllustration(size: 104),
                    const SizedBox(height: 24),
                    Text(
                      lockState == 'locked'
                          ? 'Locked'
                          : lockState == 'unlocked'
                          ? 'Unlocked'
                          : 'State Unknown',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 16),
                    IconButton.filled(
                      onPressed: !canEdit || busy || loading || !canControl
                          ? null
                          : () => command(
                              lockState == 'locked'
                                  ? 'unlock'
                                  : lockState == 'unlocked'
                                  ? 'lock'
                                  : 'status',
                              lockState == 'locked'
                                  ? 'Unlock'
                                  : lockState == 'unlocked'
                                  ? 'Lock'
                                  : 'Check status',
                            ),
                      tooltip: 'Verify or control lock',
                      style: IconButton.styleFrom(
                        padding: const EdgeInsets.all(24),
                        backgroundColor: ttBlue,
                        foregroundColor: Colors.white,
                      ),
                      icon: Icon(
                        lockState == 'locked'
                            ? LucideIcons.lockKeyhole
                            : lockState == 'unlocked'
                            ? LucideIcons.lockKeyholeOpen
                            : LucideIcons.circleHelp,
                        size: 36,
                      ),
                    ),
                  ],
                ),
              ),
              SizedBox(
                width: c.maxWidth < 650 ? c.maxWidth : (c.maxWidth - 292),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Connection overview',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 16),
                    TTBattery(bluetoothBattery ?? widget.lock['battery']),
                    const SizedBox(height: 16),
                    Text(
                      'Gateway: ${widget.lock['has_gateway'] == true ? 'Linked · online status not supplied' : 'No gateway reported'}',
                      style: TextStyle(color: ttMuted(context)),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      service.remote
                          ? 'Bluetooth via ${service.phoneName}'
                          : mobile
                          ? 'Nearby Bluetooth management'
                          : 'Browser Bluetooth requires a phone bridge',
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Last state check: ${ttDate(checkedAt)}',
                      style: TextStyle(color: ttMuted(context)),
                    ),
                    const SizedBox(height: 20),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final item in [
                          ('unlock', 'Unlock', LucideIcons.lockKeyholeOpen),
                          ('lock', 'Lock', LucideIcons.lockKeyhole),
                          ('status', 'Check status', LucideIcons.refreshCw),
                        ])
                          OutlinedButton.icon(
                            onPressed: !canEdit || busy || loading || !canControl
                                ? null
                                : () => command(item.$1, item.$2),
                            icon: Icon(item.$3, size: 16),
                            label: Text(item.$2),
                          ),
                      ],
                    ),
                    if (!canControl)
                      const Padding(
                        padding: EdgeInsets.only(top: 12),
                        child: Text(
                          'No compatible gateway or direct Bluetooth connection. Connect Use phone Bluetooth from the dashboard.',
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 20),
      if (mobile)
        TTPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TTBadge(
                bluetoothVerifiedAt == null
                    ? 'Bluetooth not verified'
                    : 'Bluetooth verified at ${TimeOfDay.fromDateTime(bluetoothVerifiedAt!).format(context)}',
                icon: LucideIcons.bluetooth,
              ),
              const SizedBox(height: 12),
              Text(
                service.remote
                    ? 'Keep ${service.phoneName} near the lock and approve requests in its AirLink app.'
                    : 'Wake the lock and keep this phone nearby. Each action reconnects; a past check does not imply an ongoing connection.',
                style: TextStyle(color: ttMuted(context), height: 1.5),
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: !canEdit || busy || loading ? null : connectBluetooth,
                    icon: const Icon(LucideIcons.bluetoothConnected, size: 18),
                    label: Text(
                      service.remote
                          ? 'Check phone Bluetooth'
                          : 'Connect via Bluetooth',
                    ),
                  ),
                  for (final item in [
                    ('battery', 'Battery', LucideIcons.battery),
                    ('time', 'Sync clock', LucideIcons.clock),
                  ])
                    OutlinedButton.icon(
                      onPressed: busy || loading
                          ? null
                          : () => command(item.$1, item.$2),
                      icon: Icon(item.$3, size: 16),
                      label: Text(item.$2),
                    ),
                  if (!service.remote)
                    OutlinedButton(
                      onPressed: busy || loading
                          ? null
                          : () => perform(() async {
                              await service.recover();
                              progress('Saved Bluetooth results uploaded.');
                              await load();
                            }),
                      child: const Text('Recover sync'),
                    ),
                ],
              ),
            ],
          ),
        ),
    ];
  }

  List<Widget> credentialWidgets(BuildContext context) => [
    Row(
      children: [
        Expanded(
          child: Text(
            credentialTitle,
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
        FilledButton.icon(
          onPressed: !canEdit || !mobile || busy || loading
              ? null
              : () => cardAction('${kind}_add'),
          icon: const Icon(Icons.add_card),
          label: Text('Add $credentialLabel'),
        ),
      ],
    ),
    const SizedBox(height: 12),
    if (!loading && cards.isEmpty)
      Text('No ${credentialTitle.toLowerCase()} are listed on this page.'),
    for (final card in cards)
      Card.outlined(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                card['name'],
                style: Theme.of(context).textTheme.titleMedium,
              ),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      kind == 'passcode' && !revealed.contains(card['id'])
                          ? 'Passcode: ••••••'
                          : '${kind == 'passcode' ? 'Passcode' : 'Number'}: ${card['number']}',
                    ),
                  ),
                  if (kind == 'passcode')
                    IconButton(
                      tooltip: 'Show or hide passcode',
                      onPressed: () => setState(() {
                        if (!revealed.add(card['id'])) {
                          revealed.remove(card['id']);
                        }
                      }),
                      icon: const Icon(Icons.visibility_outlined),
                    ),
                ],
              ),
              Text(
                card['cyclic'] == true
                    ? 'Recurring schedule — manage in TTLock app'
                    : card['start'] == 0 && card['end'] == 0
                    ? 'Permanent access'
                    : '${dateLabel(card['start'])} → ${dateLabel(card['end'])}',
              ),
              Wrap(
                spacing: 8,
                children: [
                  TextButton(
                    onPressed: !canEdit || busy || loading ? null : () => rename(card),
                    child: const Text('Rename'),
                  ),
                  TextButton(
                    onPressed:
                        !canEdit || !mobile || busy || loading || card['cyclic'] == true
                        ? null
                        : () => cardAction('${kind}_period', card),
                    child: const Text('Change validity'),
                  ),
                  TextButton(
                    onPressed: !canDelete || !mobile || busy || loading
                        ? null
                        : () => cardAction('${kind}_delete', card),
                    child: Text('Remove $credentialLabel'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 8,
      children: [
        TextButton(
          onPressed: busy || loading || page <= 1
              ? null
              : () {
                  page--;
                  load();
                },
          child: const Text('Previous'),
        ),
        Text('Page $page / ${pages == 0 ? 1 : pages}'),
        TextButton(
          onPressed: busy || loading || page >= pages
              ? null
              : () {
                  page++;
                  load();
                },
          child: const Text('Next'),
        ),
      ],
    ),
  ];
  List<Widget> settingsWidgets(BuildContext context) => [
    if (pending.isNotEmpty) ...[
      const SizedBox(height: 20),
      const Text('Pending synchronization'),
      for (final item in pending)
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text('${item['action']} • ${item['status']}'),
          subtitle: Text(
            item['status'] == 'prepared'
                ? 'Device result not received. Use Recover sync on the original phone; otherwise inspect the lock before repeating any action.'
                : 'Bluetooth succeeded. Only cloud synchronization remains.',
          ),
          trailing: item['status'] == 'prepared'
              ? null
              : IconButton(
                  tooltip: 'Retry cloud sync',
                  icon: const Icon(Icons.cloud_sync),
                  onPressed: busy || loading
                      ? null
                      : () => perform(() async {
                          final result = await widget.api.request(
                            '/integrations/ttlock/mobile/${item['request_id']}/sync',
                            method: 'POST',
                            retry: false,
                          );
                          progress(
                            result['status'] == 'synced'
                                ? 'Cloud sync completed.'
                                : result['message'],
                          );
                          await load();
                        }),
                ),
        ),
    ],
    if (mobile)
      Padding(
        padding: const EdgeInsets.only(top: 24),
        child: TextButton.icon(
          onPressed: !canDelete || busy || loading ? null : reset,
          icon: const Icon(Icons.delete_outline),
          label: const Text('Reset and remove device'),
        ),
      ),
  ];
}

class TTLockCardForm extends StatefulWidget {
  final Map<String, dynamic>? card;
  final bool periodOnly;
  final String kind;
  const TTLockCardForm({
    super.key,
    this.card,
    this.periodOnly = false,
    this.kind = 'card',
  });
  @override
  State<TTLockCardForm> createState() => _TTLockCardFormState();
}

class _TTLockCardFormState extends State<TTLockCardForm> {
  final form = GlobalKey<FormState>();
  String name = '', passcode = '';
  bool permanent = false;
  DateTime start = DateTime.now(),
      end = DateTime.now().add(const Duration(days: 30));
  String? error;
  @override
  void initState() {
    super.initState();
    final card = widget.card;
    if (card != null && card['start'] is int && card['start'] > 0) {
      start = DateTime.fromMillisecondsSinceEpoch(card['start']);
    }
    if (card != null && card['end'] is int && card['end'] > 0) {
      end = DateTime.fromMillisecondsSinceEpoch(card['end']);
    }
  }

  Future<void> pick(bool from) async {
    final value = from ? start : end;
    final day = await showDatePicker(
      context: context,
      initialDate: value,
      firstDate: DateTime(2000),
      lastDate: DateTime(2099),
    );
    if (day == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(value),
    );
    if (time == null || !mounted) return;
    setState(() {
      final selected = DateTime(
        day.year,
        day.month,
        day.day,
        time.hour,
        time.minute,
      );
      if (from) {
        start = selected;
      } else {
        end = selected;
      }
    });
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(
      widget.periodOnly
          ? 'Change ${widget.kind} validity'
          : 'Add ${widget.kind}',
    ),
    content: SingleChildScrollView(
      child: Form(
        key: form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!widget.periodOnly) ...[
              Text(
                widget.kind == 'card'
                    ? 'This grants access to this lock. When prompted, tap the physical card on its reader.'
                    : widget.kind == 'fingerprint'
                    ? 'This grants access to this lock. Follow the prompts to scan a finger on the lock sensor. AirLink stores only the enrollment reference, not a fingerprint image.'
                    : 'This grants access to this lock using the custom passcode you choose.',
              ),
              TextFormField(
                decoration: const InputDecoration(labelText: 'Name'),
                maxLength: 100,
                onChanged: (value) => name = value,
                validator: (value) => value == null || value.trim().isEmpty
                    ? 'Enter a name'
                    : null,
              ),
              if (widget.kind == 'passcode')
                TextFormField(
                  decoration: const InputDecoration(
                    labelText: 'Passcode (4–9 digits)',
                  ),
                  keyboardType: TextInputType.number,
                  obscureText: true,
                  enableSuggestions: false,
                  autocorrect: false,
                  maxLength: 9,
                  onChanged: (value) => passcode = value,
                  validator: (value) =>
                      RegExp(r'^[0-9]{4,9}$').hasMatch(value ?? '')
                      ? null
                      : 'Enter 4–9 digits',
                ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Permanent access'),
                value: permanent,
                onChanged: (value) => setState(() => permanent = value),
              ),
            ],
            if (!permanent) ...[
              TextButton(
                onPressed: () => pick(true),
                child: Text('From: ${start.toString().split('.').first}'),
              ),
              TextButton(
                onPressed: () => pick(false),
                child: Text('Until: ${end.toString().split('.').first}'),
              ),
              const Text('Times use this phone’s local time zone.'),
            ],
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () {
          if (!form.currentState!.validate()) return;
          if (!permanent &&
              (!end.isAfter(start) || !end.isAfter(DateTime.now()))) {
            setState(
              () => error =
                  'End time must be after start time and in the future.',
            );
            return;
          }
          Navigator.pop(context, <String, dynamic>{
            if (!widget.periodOnly) 'name': name.trim(),
            if (!widget.periodOnly && widget.kind == 'passcode')
              'passcode': passcode,
            'start': permanent ? 0 : start.millisecondsSinceEpoch,
            'end': permanent ? 0 : end.millisecondsSinceEpoch,
          });
        },
        child: Text(widget.periodOnly ? 'Update validity' : 'Start enrollment'),
      ),
    ],
  );
}
