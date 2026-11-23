import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/api_client_native.dart';
import 'package:airlink_isp_os/mobile_session.dart';
import 'package:airlink_isp_os/ttlock_bluetooth.dart';
import 'package:airlink_isp_os/ttlock_mobile_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeBluetooth extends TTLockBluetooth {
  int operations = 0;
  bool fail = false;
  @override
  bool get available => true;
  @override
  Future<void> ready() async {}
  @override
  Future<Map<String, dynamic>> execute(
    String action,
    Map<String, dynamic> data,
    void Function(String) progress,
  ) async {
    operations++;
    if (fail) throw Exception('Bluetooth failed');
    expect(data['lock_data'], 'secret-lock-data');
    return {'card_number': '12345'};
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    mobileServer = null;
    FlutterSecureStorage.setMockInitialValues({});
  });
  tearDown(() => mobileServer = null);

  test(
    'native refresh cookie is origin-bound, path-bound and persists securely',
    () async {
      mobileServer = 'https://airlink.example';
      var calls = 0;
      final native = NativeApiClient(
        inner: MockClient((request) async {
          calls++;
          expect(request.followRedirects, isFalse);
          if (request.url.path.endsWith('/login')) {
            return http.Response(
              '{}',
              200,
              headers: {
                'set-cookie':
                    'airlink_refresh=private-session; HttpOnly; Secure; Path=/api/auth',
              },
            );
          }
          if (request.url.path.endsWith('/refresh')) {
            expect(
              request.headers['cookie'],
              'airlink_refresh=private-session',
            );
          } else {
            expect(request.headers['cookie'], isNull);
          }
          return http.Response('{}', 200);
        }),
      );
      await native.post(Uri.parse('https://airlink.example/api/auth/login'));
      await native.post(Uri.parse('https://airlink.example/api/auth/refresh'));
      await native.get(
        Uri.parse('https://airlink.example/api/integrations/ttlock'),
      );
      expect(
        await mobileSecrets.read(
          key: 'airlink.refresh.https://airlink.example',
        ),
        'private-session',
      );
      await expectLater(
        native.get(Uri.parse('https://other.example/api/auth/refresh')),
        throwsFormatException,
      );
      await expectLater(
        native.get(Uri.parse('http://airlink.example/api/auth/refresh')),
        throwsFormatException,
      );
      expect(calls, 3);
    },
  );

  test(
    'Bluetooth success survives sync outage without repeating hardware work',
    () async {
      final bluetooth = FakeBluetooth();
      var online = false, completions = 0, prepares = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/prepare')) {
            prepares++;
            expect(bluetooth.operations, 0);
            final id = jsonDecode(request.body)['request_id'];
            return http.Response(
              jsonEncode({'request_id': id, 'lock_data': 'secret-lock-data'}),
              200,
            );
          }
          completions++;
          expect(bluetooth.operations, 1);
          expect(jsonDecode(request.body), {
            'sdk_success': true,
            'card_number': '12345',
          });
          if (!online) throw http.ClientException('Offline');
          return http.Response('{"status":"synced"}', 200);
        }),
      )..user = {'id': 'owner1', 'role': 'owner'};
      final service = TTLockMobileService(api, bluetooth: bluetooth);
      await expectLater(
        service.run({
          'action': 'card_add',
          'lock_id': 42,
          'name': 'Office',
          'start': 0,
          'end': 0,
        }, (_) {}),
        throwsException,
      );
      expect(prepares, 1);
      expect((await service.readOutbox()).length, 1);
      api.user = {'id': 'owner2', 'role': 'owner'};
      expect(await service.readOutbox(), isEmpty);
      api.user = {'id': 'owner1', 'role': 'owner'};
      online = true;
      await service.recover();
      expect(bluetooth.operations, 1);
      expect(completions, 2);
      expect(await service.readOutbox(), isEmpty);
    },
  );

  test('SDK failures never upload fake successful changes', () async {
    final bluetooth = FakeBluetooth()..fail = true;
    final api = Api(
      client: MockClient((request) async {
        expect(request.url.path.endsWith('/prepare'), isTrue);
        return http.Response(
          '{"request_id":"abc","lock_data":"secret-lock-data"}',
          200,
        );
      }),
    )..user = {'id': 'owner'};
    final service = TTLockMobileService(api, bluetooth: bluetooth);
    await expectLater(
      service.run({
        'action': 'card_delete',
        'lock_id': 42,
        'card_id': 7,
      }, (_) {}),
      throwsException,
    );
    expect(await service.readOutbox(), isEmpty);
  });

  test(
    'mobile server validation rejects insecure addresses and embedded credentials',
    () {
      expect(
        validateMobileServer('https://airlink.example/'),
        'https://airlink.example',
      );
      for (final value in [
        'http://airlink.example',
        'https://user:pass@airlink.example',
        'https://airlink.example/client',
        'https://airlink.example?token=secret',
      ]) {
        expect(() => validateMobileServer(value), throwsFormatException);
      }
    },
  );
}
