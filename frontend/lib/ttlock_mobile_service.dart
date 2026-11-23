import 'dart:convert';
import 'dart:math';
import 'api.dart';
import 'mobile_session.dart';
import 'ttlock_bluetooth.dart';

class TTLockMobileService {
  static final _memoryOutboxes = <String, Map<String, dynamic>>{};
  final Api api;
  final TTLockBluetooth bluetooth;
  bool get remote => false;
  String? get phoneName => null;
  Future<void> cancelRemote() async {}
  TTLockMobileService(this.api, {TTLockBluetooth? bluetooth})
    : bluetooth = bluetooth ?? TTLockBluetooth();
  String get _outboxKey =>
      'airlink.ttlock.outbox.${Api.base}.${api.user?['id']}';
  static const path = '/integrations/ttlock';

  Future<Map<String, dynamic>> run(
    Map<String, dynamic> parameters,
    void Function(String) progress, {
    Map<String, dynamic>? scan,
  }) async {
    await bluetooth.ready();
    final outbox = await readOutbox();
    // Confirm secure storage is usable before changing physical access.
    await mobileSecrets.write(key: _outboxKey, value: jsonEncode(outbox));
    final random = Random.secure();
    final id =
        parameters['request_id'] as String? ??
        List.generate(32, (_) => random.nextInt(16).toRadixString(16)).join();
    final prepared = Map<String, dynamic>.from(
      await api.request(
        '$path/mobile/prepare',
        method: 'POST',
        body: {
          ...parameters,
          'request_id': id,
          if (scan != null) 'lock_mac': scan['lockMac'],
        },
        retry: false,
      ),
    );
    progress('Connecting to the nearby lock…');
    final result = await bluetooth.execute(parameters['action'], {
      ...parameters,
      ...prepared,
      'scan': scan,
    }, progress);
    final body = {'sdk_success': true, ...result};
    // Save the SDK result before network synchronization; never replay Bluetooth.
    outbox[id] = body;
    _memoryOutboxes[_outboxKey] = outbox;
    var savedLocally = false;
    try {
      await mobileSecrets.write(key: _outboxKey, value: jsonEncode(outbox));
      savedLocally = true;
    } catch (_) {
      progress('Device changed. Saving its result to the server…');
    }
    try {
      final response = Map<String, dynamic>.from(
        await api.request(
          '$path/mobile/$id/complete',
          method: 'POST',
          body: body,
          retry: false,
        ),
      );
      outbox.remove(id);
      await mobileSecrets.write(key: _outboxKey, value: jsonEncode(outbox));
      return response;
    } catch (_) {
      throw Exception(
        'The Bluetooth change succeeded, but cloud sync is not confirmed. ${savedLocally ? '' : 'Local storage failed; keep this app open. '}Use Recover sync on this phone; do not repeat the device action.',
      );
    }
  }

  Future<Map<String, dynamic>> readOutbox() async {
    final value = await mobileSecrets.read(key: _outboxKey);
    return {
      if (value != null) ...Map<String, dynamic>.from(jsonDecode(value)),
      ...?_memoryOutboxes[_outboxKey],
    };
  }

  Future<void> recover() async {
    final outbox = await readOutbox();
    for (final id in outbox.keys.toList()) {
      await api.request(
        '$path/mobile/$id/complete',
        method: 'POST',
        body: outbox[id],
        retry: false,
      );
      outbox.remove(id);
      _memoryOutboxes[_outboxKey]?.remove(id);
      await mobileSecrets.write(key: _outboxKey, value: jsonEncode(outbox));
    }
  }

  Future<Map<String, dynamic>> command(
    int lockId,
    int page,
    String action,
    Map<String, dynamic> options,
    void Function(String) progress,
  ) async {
    await bluetooth.ready();
    final data = Map<String, dynamic>.from(
      await api.request('$path/locks/$lockId/bluetooth?page=$page'),
    );
    return bluetooth.execute(action, {...data, ...options}, progress);
  }
}
