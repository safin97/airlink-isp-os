import 'dart:async';
import 'dart:math';
import 'api.dart';
import 'ttlock_mobile_service.dart';

class TTLockRemoteService extends TTLockMobileService {
  final String bridgeId;
  @override
  final String phoneName;
  final Duration pollInterval;
  String? activeJob;
  @override
  bool get remote => true;
  TTLockRemoteService(
    super.api, {
    required this.bridgeId,
    required this.phoneName,
    this.pollInterval = const Duration(seconds: 2),
  });
  static const bridgePath = '/integrations/ttlock/bridge';

  Future<Map<String, dynamic>> send(
    Map<String, dynamic> parameters,
    void Function(String) progress,
  ) async {
    if (activeJob != null) {
      throw Exception('Finish the current phone request first.');
    }
    final random = Random.secure();
    final id = List.generate(
      32,
      (_) => random.nextInt(16).toRadixString(16),
    ).join();
    activeJob = id;
    try {
      progress('Sending to $phoneName…');
      // Never automatically retry creation or any physical action.
      await api
          .request(
            '$bridgePath/jobs',
            method: 'POST',
            retry: false,
            body: {
              'request_id': id,
              'bridge_id': bridgeId,
              'parameters': parameters,
            },
          )
          .timeout(const Duration(seconds: 30));
      final deadline = DateTime.now().add(const Duration(minutes: 6));
      String? previous;
      while (DateTime.now().isBefore(deadline)) {
        final response = await api.request('$bridgePath/jobs/$id');
        final status = response['status'];
        if (status != previous) {
          progress(
            status == 'queued'
                ? 'Open AirLink on $phoneName and approve this request. Keep the phone near the lock.'
                : 'Phone is working. Keep its AirLink app open and wait for the lock result.',
          );
          previous = status;
        }
        if (status == 'succeeded') {
          return Map<String, dynamic>.from(response['result']['data']);
        }
        if (['failed', 'unknown', 'expired', 'cancelled'].contains(status)) {
          throw Exception(
            response['result']?['data']?['message'] ??
                'Phone request $status. Check the phone and physical lock before sending another action.',
          );
        }
        await Future<void>.delayed(pollInterval);
      }
      throw Exception(
        'Phone result is unknown. Check the phone and lock; do not repeat the action.',
      );
    } on ApiException catch (e) {
      if (e.status < 500) rethrow;
      throw Exception(
        'Phone request outcome is not confirmed. Check $phoneName before repeating the action. Request: $id. $e',
      );
    } on TimeoutException {
      throw Exception(
        'Phone request timed out. Check $phoneName before repeating the action. Request: $id.',
      );
    } finally {
      activeJob = null;
    }
  }

  @override
  Future<void> cancelRemote() async {
    final id = activeJob;
    if (id != null) {
      await api.request(
        '$bridgePath/jobs/$id/cancel',
        method: 'POST',
        retry: false,
      );
    }
  }

  @override
  Future<Map<String, dynamic>> run(
    Map<String, dynamic> parameters,
    void Function(String) progress, {
    Map<String, dynamic>? scan,
  }) => send(parameters, progress);

  @override
  Future<Map<String, dynamic>> command(
    int lockId,
    int page,
    String action,
    Map<String, dynamic> options,
    void Function(String) progress,
  ) => send({
    'lock_id': lockId,
    'lock_page': page,
    'action': action,
    ...options,
  }, progress);

  @override
  Future<void> recover() async =>
      throw Exception('Use Recover sync on $phoneName.');
}
