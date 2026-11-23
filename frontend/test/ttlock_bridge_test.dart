import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock_bridge_page.dart';
import 'package:airlink_isp_os/ttlock_mobile_service.dart';
import 'package:airlink_isp_os/ttlock_remote_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'ttlock_mobile_test.dart' show FakeBluetooth;

class BridgeHardware extends TTLockMobileService {
  int commands = 0;
  BridgeHardware(super.api) : super(bluetooth: FakeBluetooth());
  @override
  Future<Map<String, dynamic>> command(
    int lockId,
    int page,
    String action,
    Map<String, dynamic> options,
    void Function(String) progress,
  ) async {
    expect(lockId, 42);
    expect(action, 'unlock');
    commands++;
    return {'battery': 75};
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('browser sends one job and waits for an actual phone result', () async {
    var creates = 0, reads = 0;
    String? id;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          creates++;
          final body = jsonDecode(request.body);
          id = body['request_id'];
          expect(body['parameters'], {
            'lock_id': 42,
            'lock_page': 1,
            'action': 'battery',
          });
          expect(body['bridge_id'], 'phone');
          return http.Response('{"status":"queued"}', 200);
        }
        expect(request.url.path.endsWith(id!), isTrue);
        reads++;
        return http.Response(
          jsonEncode(
            reads == 1
                ? {'status': 'queued'}
                : reads == 2
                ? {'status': 'running'}
                : {
                    'status': 'succeeded',
                    'result': {
                      'status': 'succeeded',
                      'data': {'battery': 75},
                    },
                  },
          ),
          200,
        );
      }),
    );
    final service = TTLockRemoteService(
      api,
      bridgeId: 'phone',
      phoneName: 'Office phone',
      pollInterval: Duration.zero,
    );
    final progress = <String>[];
    final result = await service.command(42, 1, 'battery', {}, progress.add);
    expect(result['battery'], 75);
    expect(creates, 1);
    expect(reads, 3);
    expect(progress.any((s) => s.contains('approve')), isTrue);
    expect(service.activeJob, isNull);
  });

  test(
    'unknown phone outcome never automatically resends a physical request',
    () async {
      var creates = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            creates++;
            return http.Response('{"status":"queued"}', 200);
          }
          return http.Response('{"status":"unknown"}', 200);
        }),
      );
      final service = TTLockRemoteService(
        api,
        bridgeId: 'phone',
        phoneName: 'Phone',
        pollInterval: Duration.zero,
      );
      await expectLater(
        service.command(42, 1, 'unlock', {}, (_) {}),
        throwsException,
      );
      expect(creates, 1);
    },
  );

  testWidgets(
    'phone requires approval and retries delivery without repeating Bluetooth',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var claims = 0, completions = 0;
      final api = Api(
        client: MockClient((request) async {
          final path = request.url.path;
          if (path.endsWith('/phones')) {
            return http.Response(
              jsonEncode({'id': 'phone', 'token': 't' * 64}),
              200,
            );
          }
          if (path.endsWith('/poll')) {
            expect(request.headers['X-AirLink-Bridge'], 't' * 64);
            return http.Response(
              '{"job":{"id":"job1","lock_name":"Office door","action":"unlock"}}',
              200,
            );
          }
          if (path.endsWith('/claim')) {
            claims++;
            return http.Response(
              jsonEncode({
                'claim_token': 'c' * 64,
                'operation': false,
                'parameters': {
                  'lock_id': 42,
                  'lock_page': 1,
                  'action': 'unlock',
                },
              }),
              200,
            );
          }
          if (path.endsWith('/complete')) {
            completions++;
            expect(jsonDecode(request.body)['result'], {'battery': 75});
            return http.Response(
              completions == 1
                  ? '{"detail":"Offline"}'
                  : '{"status":"succeeded"}',
              completions == 1 ? 503 : 200,
            );
          }
          expect(request.method, 'DELETE');
          return http.Response('{"status":"stopped"}', 200);
        }),
      )..user = {'id': 'owner'};
      final hardware = BridgeHardware(api);
      await tester.pumpWidget(
        MaterialApp(
          home: TTLockBridgePage(api: api, service: hardware),
        ),
      );
      await tester.tap(find.text('Start Bluetooth sharing'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('Office door'), findsOneWidget);
      expect(claims, 0);
      expect(hardware.commands, 0);
      await tester.ensureVisible(find.text('Approve and run'));
      await tester.tap(find.text('Approve and run'));
      await tester.pumpAndSettle();
      expect(claims, 1);
      expect(hardware.commands, 1);
      expect(find.text('Retry sending result only'), findsOneWidget);
      await tester.ensureVisible(find.text('Retry sending result only'));
      await tester.tap(find.text('Retry sending result only'));
      await tester.pumpAndSettle();
      expect(completions, 2);
      expect(hardware.commands, 1);
      expect(find.text('Result sent to the website.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();
    },
  );

  testWidgets(
    'browser explains how to connect a phone when none are available',
    (tester) async {
      final api = Api(
        client: MockClient((_) async => http.Response('{"items":[]}', 200)),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: TTLockPhonePicker(
            api: api,
            lock: {'id': 42, 'name': 'Office door'},
            lockPage: 1,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('No phone is sharing Bluetooth'),
        findsOneWidget,
      );
      expect(
        find.textContaining('native app handles Bluetooth'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
