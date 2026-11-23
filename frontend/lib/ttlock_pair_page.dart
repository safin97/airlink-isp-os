import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'ttlock_mobile_service.dart';

class TTLockPairPage extends StatefulWidget {
  final Api api;
  const TTLockPairPage({super.key, required this.api});
  @override
  State<TTLockPairPage> createState() => _TTLockPairPageState();
}

class _TTLockPairPageState extends State<TTLockPairPage> {
  late final service = TTLockMobileService(widget.api);
  final Map<String, Map<String, dynamic>> locks = {};
  bool scanning = false, busy = false;
  String? error, message;
  Timer? timer;
  @override
  void dispose() {
    timer?.cancel();
    service.bluetooth.stopScan();
    super.dispose();
  }

  Future<void> scan() async {
    setState(() {
      scanning = true;
      error = null;
      locks.clear();
    });
    try {
      await service.bluetooth.scan((lock) {
        if (mounted) setState(() => locks[lock['lockMac']] = lock);
      });
      timer?.cancel();
      timer = Timer(const Duration(seconds: 20), () {
        service.bluetooth.stopScan();
        if (mounted) setState(() => scanning = false);
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          scanning = false;
        });
      }
    }
  }

  Future<void> pair(Map<String, dynamic> lock) async {
    service.bluetooth.stopScan();
    timer?.cancel();
    setState(() => scanning = false);
    var name = lock['lockName'] as String;
    final form = GlobalKey<FormState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add nearby lock'),
        content: Form(
          key: form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${lock['lockName']} • ${lock['lockMac']}\nThis pairs the lock to your connected TTLock account.',
              ),
              TextFormField(
                initialValue: name,
                maxLength: 100,
                decoration: const InputDecoration(labelText: 'Device name'),
                onChanged: (value) => name = value,
                validator: (value) => value == null || value.trim().isEmpty
                    ? 'Enter a name'
                    : null,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (form.currentState!.validate()) Navigator.pop(context, true);
            },
            child: const Text('Pair this lock'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await service.run(
        {'action': 'lock_init', 'name': name.trim()},
        (value) {
          if (mounted) setState(() => message = value);
        },
        scan: lock,
      );
      if (!mounted) return;
      if (result['status'] == 'synced') {
        Navigator.pop(context, true);
      } else {
        setState(() => message = result['message']);
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> recover() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await service.recover();
      final pending = await widget.api.request(
        '/integrations/ttlock/mobile/pending',
      );
      for (final item in pending['items']) {
        if (item['status'] == 'sync_pending' ||
            item['status'] == 'device_complete') {
          final result = await widget.api.request(
            '/integrations/ttlock/mobile/${item['request_id']}/sync',
            method: 'POST',
            retry: false,
          );
          if (result['status'] != 'synced') throw Exception(result['message']);
        }
      }
      if (mounted) {
        setState(
          () => message =
              'Saved results synchronized. Refresh devices to check the account.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(title: const Text('Add Bluetooth device')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Wake the lock and put it in pairing mode. Stay nearby with Bluetooth enabled. Only uninitialized locks can be paired.',
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            children: [
              FilledButton.icon(
                onPressed: busy || scanning ? null : scan,
                icon: const Icon(Icons.bluetooth_searching),
                label: const Text('Scan nearby locks'),
              ),
              OutlinedButton(
                onPressed: busy || scanning ? null : recover,
                child: const Text('Recover sync'),
              ),
            ],
          ),
          if (busy || scanning)
            const Padding(
              padding: EdgeInsets.all(12),
              child: LinearProgressIndicator(),
            ),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (message != null) Text(message!),
          for (final lock in locks.values)
            Card.outlined(
              child: ListTile(
                title: Text(lock['lockName']),
                subtitle: Text(
                  '${lock['lockMac']} • ${lock['rssi']} dBm${lock['isInited'] == true ? ' • Already paired' : ''}',
                ),
                trailing: FilledButton(
                  onPressed: busy || lock['isInited'] == true
                      ? null
                      : () => pair(lock),
                  child: const Text('Add'),
                ),
              ),
            ),
          if (!scanning && locks.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('No nearby locks found yet.'),
            ),
        ],
      ),
    ),
  );
}
