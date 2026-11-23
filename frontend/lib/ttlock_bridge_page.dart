import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'mobile_session.dart';
import 'ttlock_mobile_service.dart';
import 'ttlock_remote_service.dart';
import 'ttlock_device_page.dart';

class TTLockBridgePage extends StatefulWidget {
  final Api api;
  final TTLockMobileService? service;
  const TTLockBridgePage({super.key, required this.api, this.service});
  @override
  State<TTLockBridgePage> createState() => _TTLockBridgePageState();
}

class _TTLockBridgePageState extends State<TTLockBridgePage>
    with WidgetsBindingObserver {
  late final service = widget.service ?? TTLockMobileService(widget.api);
  final name = TextEditingController(text: 'My Bluetooth phone');
  String? bridgeId, token, message, error;
  Map<String, dynamic>? job, pendingResult;
  bool busy = false, polling = false, foreground = true;
  Timer? timer;
  static const path = TTLockRemoteService.bridgePath;
  String get resultKey =>
      'airlink.ttlock.bridge-result.${Api.base}.${widget.api.user?['id']}';
  Map<String, String> get headers => {'X-AirLink-Bridge': token!};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    if (foreground) unawaited(poll());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    name.dispose();
    if (bridgeId != null) {
      unawaited(
        widget.api
            .request(
              '$path/phones/$bridgeId',
              method: 'DELETE',
              headers: headers,
              retry: false,
            )
            .then<void>((_) {}, onError: (_) {}),
      );
    }
    super.dispose();
  }

  Future<void> perform(Future<void> Function() action) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> start() => perform(() async {
    if (name.text.trim().isEmpty) throw Exception('Enter a phone name.');
    final saved = await mobileSecrets.read(key: resultKey);
    if (saved != null && saved != '{}') {
      pendingResult = Map<String, dynamic>.from(jsonDecode(saved));
      await sendResult();
    }
    await service.bluetooth.ready();
    await mobileSecrets.write(key: resultKey, value: '{}');
    final response = await widget.api
        .request(
          '$path/phones',
          method: 'POST',
          body: {'name': name.text.trim()},
          retry: false,
        )
        .timeout(const Duration(seconds: 30));
    if (!mounted) return;
    setState(() {
      bridgeId = response['id'];
      token = response['token'];
      message =
          'Ready. Select this phone from Use phone Bluetooth on the website.';
    });
    timer = Timer.periodic(const Duration(seconds: 5), (_) => poll());
  });

  Future<void> poll() async {
    if (!mounted || !foreground || busy || polling || bridgeId == null) return;
    polling = true;
    try {
      final response = await widget.api
          .request(
            '$path/phones/$bridgeId/poll',
            method: 'POST',
            headers: headers,
          )
          .timeout(const Duration(seconds: 20));
      if (mounted && !busy) {
        setState(() {
          job = response['job'] == null
              ? null
              : Map<String, dynamic>.from(response['job']);
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      polling = false;
    }
  }

  void progress(String text) {
    if (mounted) setState(() => message = text);
  }

  Future<void> sendResult() async {
    final saved = pendingResult;
    if (saved == null) return;
    await widget.api
        .request(
          '$path/jobs/${saved['id']}/complete',
          method: 'POST',
          body: saved['body'],
          retry: false,
        )
        .timeout(const Duration(seconds: 30));
    await mobileSecrets.delete(key: resultKey);
    if (mounted) {
      setState(() {
        pendingResult = null;
        job = null;
      });
    }
    progress('Result sent to the website.');
  }

  Future<void> approve() => perform(() async {
    if (!foreground || job == null || pendingResult != null) return;
    await service.bluetooth.ready();
    // Ensure durable result storage is available before claiming any physical work.
    await mobileSecrets.write(key: resultKey, value: '{}');
    final id = job!['id'];
    final claimed = await widget.api
        .request(
          '$path/jobs/$id/claim',
          method: 'POST',
          headers: headers,
          retry: false,
        )
        .timeout(const Duration(seconds: 30));
    // The server will not deliver a claimed request again, even after an app crash.
    final params = Map<String, dynamic>.from(claimed['parameters']);
    Map<String, dynamic> result;
    String status;
    try {
      result = claimed['operation'] == true
          ? await service.run({...params, 'request_id': id}, progress)
          : await service.command(
              params['lock_id'],
              params['lock_page'],
              params['action'],
              const {},
              progress,
            );
      status = 'succeeded';
    } catch (e) {
      status = 'unknown';
      result = {
        'message':
            '${e.toString()} Check this phone and the physical lock before repeating the action.',
      };
    }
    pendingResult = {
      'id': id,
      'body': {
        'claim_token': claimed['claim_token'],
        'status': status,
        'result': result,
      },
    };
    try {
      await mobileSecrets.write(
        key: resultKey,
        value: jsonEncode(pendingResult),
      );
    } catch (_) {
      progress(
        'Local storage failed. Keep the app open until the result is sent.',
      );
    }
    if (mounted) setState(() => job = null);
    await sendResult();
  });

  Future<void> reject() => perform(() async {
    await widget.api.request(
      '$path/jobs/${job!['id']}/cancel',
      method: 'POST',
      retry: false,
    );
    if (mounted) setState(() => job = null);
    progress('Request declined. No Bluetooth action was sent.');
  });

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(title: const Text('Share Bluetooth with website')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Icon(Icons.phonelink_ring, size: 56),
          const SizedBox(height: 16),
          const Text(
            'Use this phone near your locks while controlling them from Chrome on a computer, Android or iPhone. Sign in to the same AirLink server and owner account on both devices.',
          ),
          const SizedBox(height: 12),
          const Text(
            'Keep this AirLink app open. Approve each website request here before Bluetooth runs. A sleeping app cannot receive new requests; queued requests expire after two minutes.',
          ),
          const SizedBox(height: 16),
          if (bridgeId == null) ...[
            TextField(
              controller: name,
              maxLength: 80,
              decoration: const InputDecoration(labelText: 'Phone name'),
            ),
            FilledButton.icon(
              onPressed: busy || !service.bluetooth.available ? null : start,
              icon: const Icon(Icons.bluetooth),
              label: const Text('Start Bluetooth sharing'),
            ),
          ] else
            Text(
              'Sharing as ${name.text}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
          if (busy) const LinearProgressIndicator(),
          if (message != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(message!),
            ),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (pendingResult != null)
            FilledButton(
              onPressed: busy ? null : () => perform(sendResult),
              child: const Text('Retry sending result only'),
            ),
          if (job != null && pendingResult == null)
            Card.outlined(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      job!['lock_name'],
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Text(
                      'Requested action: ${job!['action'].toString().replaceAll('_', ' ')}',
                    ),
                    if (job!['name'] != null && job!['name'] != '')
                      Text('Name: ${job!['name']}'),
                    if (job!['credential_id'] != null)
                      Text('Credential ID: ${job!['credential_id']}'),
                    if (job!['start'] != null)
                      Text(
                        job!['start'] == 0 && job!['end'] == 0
                            ? 'Permanent access'
                            : 'Validity: ${DateTime.fromMillisecondsSinceEpoch(job!['start']).toLocal()} → ${DateTime.fromMillisecondsSinceEpoch(job!['end']).toLocal()}',
                      ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 12,
                      children: [
                        FilledButton(
                          onPressed: busy ? null : approve,
                          child: const Text('Approve and run'),
                        ),
                        TextButton(
                          onPressed: busy ? null : reject,
                          child: const Text('Decline'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          if (bridgeId != null)
            TextButton(
              onPressed: busy
                  ? null
                  : () async {
                      await perform(() async {
                        await widget.api.request(
                          '$path/phones/$bridgeId',
                          method: 'DELETE',
                          headers: headers,
                          retry: false,
                        );
                        timer?.cancel();
                        if (mounted) {
                          setState(() {
                            bridgeId = null;
                            token = null;
                            job = null;
                            message = 'Bluetooth sharing stopped.';
                          });
                        }
                      });
                    },
              child: const Text('Stop sharing'),
            ),
        ],
      ),
    ),
  );
}

class TTLockPhonePicker extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> lock;
  final int lockPage;
  const TTLockPhonePicker({
    super.key,
    required this.api,
    required this.lock,
    required this.lockPage,
  });
  @override
  State<TTLockPhonePicker> createState() => _TTLockPhonePickerState();
}

class _TTLockPhonePickerState extends State<TTLockPhonePicker> {
  List<Map<String, dynamic>> phones = [];
  String? error;
  bool loading = true;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '${TTLockRemoteService.bridgePath}/phones',
      );
      if (mounted) {
        setState(
          () => phones = (result['items'] as List)
              .map((p) => Map<String, dynamic>.from(p))
              .toList(),
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Use phone Bluetooth'),
      actions: [
        IconButton(
          onPressed: loading ? null : load,
          tooltip: 'Refresh phones',
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          widget.lock['name'],
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 12),
        const Text(
          'On a nearby Android or iPhone, open the AirLink app → TTLock → Share Bluetooth with website. Use the same server and owner account. The native app handles Bluetooth; Chrome sends requests and displays results.',
        ),
        const SizedBox(height: 12),
        const Text(
          'Keep the phone app open and approve each request there. If using Chrome on that same phone, switch back to AirLink promptly to approve; another nearby phone is more convenient.',
        ),
        if (loading) const LinearProgressIndicator(),
        if (error != null) Text(error!),
        if (!loading && error == null && phones.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Text(
              'No phone is sharing Bluetooth. Start sharing in the AirLink mobile app, then refresh.',
            ),
          ),
        for (final phone in phones)
          Card.outlined(
            child: ListTile(
              leading: const Icon(Icons.phonelink_ring),
              title: Text(phone['name']),
              subtitle: const Text(
                'Recently available • approval on phone required',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => TTLockDevicePage(
                    api: widget.api,
                    lock: widget.lock,
                    lockPage: widget.lockPage,
                    service: TTLockRemoteService(
                      widget.api,
                      bridgeId: phone['id'],
                      phoneName: phone['name'],
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    ),
  );
}
