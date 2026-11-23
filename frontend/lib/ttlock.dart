import 'dart:math';
import 'dart:async';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'ttlock_style.dart';
import 'ttlock_dashboard.dart';
import 'ttlock_gateway_page.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';
import 'api.dart';
import 'app_language.dart';
import 'ttlock_bluetooth.dart';
import 'ttlock_device_page.dart';
import 'ttlock_pair_page.dart';
import 'ttlock_mobile_service.dart';
import 'ttlock_bridge_page.dart';

class TTLockPage extends StatefulWidget {
  final Api api;
  const TTLockPage({super.key, required this.api});
  @override
  State<TTLockPage> createState() => _TTLockPageState();
}

class _TTLockPageState extends State<TTLockPage> {
  final username = TextEditingController(), password = TextEditingController();
  final clientId = TextEditingController(),
      clientSecret = TextEditingController();
  final form = GlobalKey<FormState>();
  final setupForm = GlobalKey<FormState>();
  final scroll = ScrollController();
  bool applicationConfigured = false;
  bool confirming = false;
  Timer? stateExpiry;
  bool busy = false, loading = false, configured = false, editing = true;
  String region = 'eu';
  String? error, message, observedAt;
  int page = 1, pages = 0, total = 0;
  List<Map<String, dynamic>> locks = [];
  final states = <int, Map<String, dynamic>>{};
  static const path = '/integrations/ttlock';

  @override
  void initState() {
    super.initState();
    load();
    stateExpiry = Timer.periodic(const Duration(seconds: 30), (_) {
      if (!mounted) return;
      final expired = states.entries
          .where((e) {
            final date = DateTime.tryParse(e.value['received_at'] ?? '');
            return date == null ||
                DateTime.now().difference(date).inMinutes >= 2;
          })
          .map((e) => e.key)
          .toList();
      if (expired.isNotEmpty) {
        setState(() {
          for (final id in expired) {
            states.remove(id);
          }
        });
      }
    });
  }

  @override
  void dispose() {
    for (final controller in [username, password, clientId, clientSecret]) {
      controller.dispose();
    }
    stateExpiry?.cancel();
    scroll.dispose();
    super.dispose();
  }

  Future<dynamic> request(
    String suffix, {
    String method = 'GET',
    Object? body,
  }) => widget.api.request(
    '$path$suffix',
    method: method,
    body: body,
    retry: !suffix.endsWith('/action') && !suffix.endsWith('/name'),
  );

  void applyLocks(Map<String, dynamic> data) {
    locks = (data['items'] as List)
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    page = data['page'];
    pages = data['pages'];
    total = data['total'];
    observedAt = data['observed_at'];
    states.clear();
  }

  void showError(Object problem) {
    if (!mounted) return;
    setState(() => error = problem.toString());
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && scroll.hasClients) {
        scroll.animateTo(
          0,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> load({bool discardDraft = false}) async {
    if (busy || loading) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      // Application metadata must not hide the login form or block account reads.
      try {
        final app = await request('/application');
        if (!mounted) return;
        setState(() {
          applicationConfigured = app['configured'] == true;
          if (applicationConfigured) {
            region = app['region'];
            clientId.text = app['client_id'];
          }
        });
      } catch (e) {
        showError(e);
      }
      final data = await request('');
      if (!mounted) return;
      setState(() {
        final keepDraft =
            !discardDraft &&
            editing &&
            (username.text.isNotEmpty || password.text.isNotEmpty);
        configured = data['configured'] == true;
        editing = !configured || keepDraft;
        if (configured && !keepDraft) username.text = data['username'];
      });
      if (configured && !editing) {
        final result = await request('/locks?page=$page');
        if (mounted) {
          setState(() => applyLocks(Map<String, dynamic>.from(result)));
        }
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted) {
        setState(() {
          loading = false;
          if (!configured) editing = true;
        });
      }
    }
  }

  Future<void> connect() async {
    if (busy || loading) return;
    if (!form.currentState!.validate()) {
      showError('Enter your TTLock username and password.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final data = await request(
        '',
        method: 'PUT',
        body: {'username': username.text.trim(), 'password': password.text},
      );
      if (mounted) {
        setState(() {
          configured = true;
          applicationConfigured = true;
          editing = false;
          applyLocks(Map<String, dynamic>.from(data['locks']));
          message = 'TTLock connected.';
        });
      }
    } catch (e) {
      showError(e);
    } finally {
      password.clear();
      clientSecret.clear();
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> saveApplication() async {
    if (busy || loading || !setupForm.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await request(
        '/application',
        method: 'PUT',
        body: {
          'region': region,
          'client_id': clientId.text.trim(),
          'client_secret': clientSecret.text,
        },
      );
      if (mounted) {
        setState(() {
          applicationConfigured = true;
          message =
              'Integration setup saved. Sign in with your TTLock username and password.';
        });
      }
    } catch (e) {
      showError(e);
    } finally {
      clientSecret.clear();
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> disconnect() async {
    if (busy || loading) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppText('Disconnect TTLock?'),
        content: const AppText(
          'This removes the saved connection from AirLink. Your locks stay in your TTLock account.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted || busy || loading) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await request('', method: 'DELETE');
      if (mounted) {
        setState(() {
          configured = false;
          editing = true;
          locks = [];
          states.clear();
        });
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> checkState(Map<String, dynamic> lock) async {
    if (busy ||
        loading ||
        (!TTLockBluetooth().available && lock['has_gateway'] != true)) {
      return;
    }
    setState(() {
      busy = true;
      error = null;
      states.remove(lock['id']);
    });
    try {
      final result = TTLockBluetooth().available
          ? await TTLockMobileService(
              widget.api,
            ).command(lock['id'], page, 'status', {}, (_) {})
          : await request('/locks/${lock['id']}/state?page=$page');
      if (TTLockBluetooth().available) {
        result['state'] = result['state'] == 'lock'
            ? 'locked'
            : result['state'] == 'unlock'
            ? 'unlocked'
            : 'unknown';
        result['observed_at'] = DateTime.now().toIso8601String();
      }
      if (mounted) {
        setState(
          () => states[lock['id']] = {
            ...Map<String, dynamic>.from(result),
            'connection': 'online',
            'received_at': DateTime.now().toIso8601String(),
          },
        );
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => states[lock['id']] = {
            'state': 'unknown',
            'connection': 'failed',
            'received_at': DateTime.now().toIso8601String(),
          },
        );
      }
      showError(e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> operate(Map<String, dynamic> lock, String action) async {
    if (busy ||
        loading ||
        confirming ||
        (!TTLockBluetooth().available && lock['has_gateway'] != true)) {
      return;
    }
    confirming = true;
    final label = action == 'unlock' ? 'Unlock' : 'Lock';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${tr(label)} ${lock['name']}?'),
        content: Text(
          '${tr('Send this command to the physical lock?')}\n\n${tr('Lock ID')}: ${lock['id']}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: AppText('Confirm $label'),
          ),
        ],
      ),
    );
    confirming = false;
    if (confirmed != true || !mounted || busy || loading) return;
    final random = Random.secure();
    final requestId = List.generate(
      32,
      (_) => random.nextInt(16).toRadixString(16),
    ).join();
    setState(() {
      busy = true;
      error = null;
      message = null;
      states.remove(lock['id']);
    });
    try {
      if (TTLockBluetooth().available) {
        await TTLockMobileService(
          widget.api,
        ).command(lock['id'], page, action, {}, (_) {});
      } else {
        await request(
          '/locks/${lock['id']}/action',
          method: 'POST',
          body: {'action': action, 'request_id': requestId, 'page': page},
        );
      }
      if (mounted) {
        setState(
          () => message =
              '${tr('TTLock confirmed the command for')} ${lock['name']}. ${tr('Check status for a fresh reading.')}',
        );
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> syncDevices() async {
    if (busy || loading) return;
    page = 1;
    await load();
  }

  Future<void> deviceAppGuide({Map<String, dynamic>? lock}) async {
    if (TTLockBluetooth().available) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => lock == null
              ? TTLockPairPage(api: widget.api)
              : TTLockDevicePage(api: widget.api, lock: lock, lockPage: page),
        ),
      );
      if (mounted) await syncDevices();
      return;
    }
    final removing = lock != null;
    final sync = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: AppText(
          removing ? 'Remove device in TTLock app' : 'Add device in TTLock app',
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (removing) ...[
                Text('${lock['name']} • ${tr('Lock ID')}: ${lock['id']}'),
                const SizedBox(height: 12),
                const AppText(
                  'Open this lock in the TTLock mobile app using its administrator account. Complete its delete/reset process while near the lock with Bluetooth enabled.',
                ),
                const SizedBox(height: 12),
                const AppText(
                  'Removal deletes the lock and its keys, passcodes, cards, fingerprints and unlock records. Reset the physical lock before removing its cloud record.',
                ),
              ] else ...[
                const AppText(
                  'Open the TTLock mobile app with the same account connected here. Enable Bluetooth, stay near the lock, and use Add Lock to pair it.',
                ),
                const SizedBox(height: 12),
                const AppText(
                  'After pairing finishes, return here and sync devices. Locks already owned by this account appear automatically.',
                ),
              ],
              const SizedBox(height: 12),
              const AppText(
                'AirLink web cannot perform Bluetooth pairing or reset. Sync devices only refreshes the list; it does not add or delete a physical lock.',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Close'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Sync devices'),
          ),
        ],
      ),
    );
    if (sync == true && mounted) await syncDevices();
  }

  Future<void> editDevice(Map<String, dynamic> lock) async {
    if (busy || loading) return;
    var draft = lock['name'] as String;
    final editForm = GlobalKey<FormState>();
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppText('Edit device name'),
        content: Form(
          key: editForm,
          child: TextFormField(
            initialValue: draft,
            onChanged: (value) => draft = value,
            autofocus: true,
            maxLength: 100,
            decoration: InputDecoration(labelText: tr('Device name')),
            validator: (value) =>
                value == null || value.trim().isEmpty ? tr('Required') : null,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (editForm.currentState!.validate()) {
                Navigator.pop(context, draft.trim());
              }
            },
            child: const AppText('Save name'),
          ),
        ],
      ),
    );
    if (name == null || !mounted || busy || loading || name == lock['name']) {
      return;
    }
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final result = await request(
        '/locks/${lock['id']}/name',
        method: 'PUT',
        body: {'name': name, 'page': page},
      );
      if (mounted) {
        setState(() {
          lock['name'] = result['name'];
          message = 'Device name updated in TTLock.';
        });
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> openLock(Map<String, dynamic> lock, String tab) async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => TTLockDevicePage(
          api: widget.api,
          lock: lock,
          lockPage: page,
          initialTab: tab,
        ),
      ),
    );
    if (mounted) await load();
  }

  Widget input(
    TextEditingController controller,
    String label, {
    bool secret = false,
    String? hint,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: TextFormField(
      controller: controller,
      enabled: !busy,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      decoration: InputDecoration(
        labelText: tr(label),
        helperText: hint,
        helperMaxLines: 3,
      ),
      validator: (value) =>
          value == null || value.trim().isEmpty ? tr('Required') : null,
      onFieldSubmitted: (_) {
        if (controller == username || controller == password) connect();
      },
    ),
  );

  @override
  Widget build(BuildContext context) =>
      TTTheme(child: Builder(builder: _buildContent));

  Widget _buildContent(BuildContext context) => ColoredBox(
    color: Theme.of(context).scaffoldBackgroundColor,
    child: ListView(
      controller: scroll,
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          children: [
            const Icon(LucideIcons.lockKeyhole, size: 30),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                'TTLock',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
            IconButton(
              tooltip: tr('Refresh'),
              onPressed: (busy || loading) ? null : load,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const AppText(
          'AirLink smart access. Your doors, devices and permissions in one place.',
        ),
        const SizedBox(height: 16),
        if (busy || loading) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (message != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(message!),
          ),
        if (editing)
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 620),
              child: Card.outlined(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Form(
                    key: form,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          tr('TTLock login'),
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 12),
                        const AppText(
                          'Sign in with your TTLock app username and password.',
                        ),
                        const SizedBox(height: 16),
                        input(
                          username,
                          'TTLock username / phone',
                          hint:
                              'For phone accounts, include the country code, for example +964…',
                        ),
                        input(password, 'TTLock password', secret: true),
                        FilledButton.icon(
                          onPressed: (busy || loading) ? null : connect,
                          icon: const Icon(Icons.login),
                          label: AppText(
                            busy
                                ? 'Connecting…'
                                : loading
                                ? 'Checking connection…'
                                : 'Sign in to TTLock',
                          ),
                        ),
                        if (configured)
                          TextButton(
                            onPressed: (busy || loading)
                                ? null
                                : () {
                                    password.clear();
                                    clientSecret.clear();
                                    load(discardDraft: true);
                                  },
                            child: const AppText('Cancel'),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        if (editing)
          Card.outlined(
            child: ExpansionTile(
              key: ValueKey('ttlock-setup-$applicationConfigured'),
              title: const AppText('One-time integration setup'),
              subtitle: AppText(
                applicationConfigured
                    ? 'Saved on this AirLink account'
                    : 'Required before first sign-in',
              ),
              childrenPadding: const EdgeInsets.all(20),
              children: [
                Form(
                  key: setupForm,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const AppText(
                        'TTLock requires an approved developer application. Save its Client ID and Client Secret once; normal login then uses only your username and password.',
                      ),
                      Link(
                        uri: Uri.parse(
                          'https://euopen.ttlock.com/document-pages/en/userGuide/getStarted',
                        ),
                        target: LinkTarget.blank,
                        builder: (context, followLink) => TextButton(
                          onPressed: followLink,
                          child: const AppText('TTLock setup guide'),
                        ),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        isExpanded: true,
                        initialValue: region,
                        decoration: const InputDecoration(
                          labelText: 'TTLock region',
                        ),
                        items: const [
                          DropdownMenuItem(value: 'eu', child: Text('Europe')),
                          DropdownMenuItem(value: 'cn', child: Text('China')),
                        ],
                        onChanged: (busy || loading)
                            ? null
                            : (value) => setState(() => region = value!),
                      ),
                      const SizedBox(height: 16),
                      input(clientId, 'Client ID'),
                      input(clientSecret, 'Client Secret', secret: true),
                      FilledButton(
                        onPressed: (busy || loading) ? null : saveApplication,
                        child: const AppText('Save integration setup'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        if (configured && !editing)
          TTLockDashboard(
            locks: locks,
            states: states,
            total: total,
            page: page,
            pages: pages,
            busy: busy,
            loading: loading,
            native: TTLockBluetooth().available,
            account: username.text,
            synced: observedAt,
            refresh: () => load(),
            add: () => deviceAppGuide(),
            gateways: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => TTLockGatewayPage(api: widget.api, page: page),
              ),
            ),
            reconnect: () => setState(() => editing = true),
            disconnect: disconnect,
            previous: () {
              page--;
              load();
            },
            next: () {
              page++;
              load();
            },
            share: TTLockBluetooth().available
                ? () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => TTLockBridgePage(api: widget.api),
                    ),
                  )
                : null,
            open: openLock,
            operate: operate,
            check: checkState,
            edit: editDevice,
            remove: (lock) => deviceAppGuide(lock: lock),
            phone: (lock) async {
              await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => TTLockPhonePicker(
                    api: widget.api,
                    lock: lock,
                    lockPage: page,
                  ),
                ),
              );
              if (mounted) await load();
            },
          ),
      ],
    ),
  );
}
