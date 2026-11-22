import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/client_speed_test.dart';

void main() {
  test(
    'browser tests use public endpoint without account data and respect data cap',
    () async {
      int total = 0, uploads = 0;
      final stages = <String>[];
      final test = ClientSpeedTest(
        client: MockClient((request) async {
          expect(request.url.host, 'speed.cloudflare.com');
          expect(request.url.scheme, 'https');
          expect(request.headers.containsKey('authorization'), false);
          expect(request.headers.containsKey('cookie'), false);
          expect(
            request.url.queryParameters.keys,
            everyElement(isIn(['airlink_test', 'bytes'])),
          );
          if (request.method == 'POST') {
            uploads++;
            total += request.bodyBytes.length;
            expect(request.headers['content-type'], 'text/plain');
            expect(request.bodyBytes.toSet().length, greaterThan(200));
            return http.Response('{}', 200);
          }
          final bytes = int.parse(request.url.queryParameters['bytes']!);
          total += bytes;
          return http.Response.bytes(Uint8List(bytes), 200);
        }),
      );
      final result = await test.run(stages.add);
      expect(
        result.keys,
        containsAll([
          'latency_ms',
          'jitter_ms',
          'download_mbps',
          'upload_mbps',
        ]),
      );
      expect(result.values.every((v) => v.isFinite && v >= 0), true);
      expect(total, lessThanOrEqualTo(26000000));
      expect(uploads, 2);
      expect(stages, [
        'Checking internet…',
        'Testing download…',
        'Testing upload…',
      ]);
      test.close();
    },
  );
  test('failed or incomplete responses never report a speed', () async {
    for (final status in [200, 403]) {
      final test = ClientSpeedTest(
        client: MockClient((_) async => http.Response('bad', status)),
      );
      await expectLater(test.transfer(100), throwsStateError);
      expect(test.stopped, true);
    }
  });
  test('stopped tests cannot start another network transfer', () async {
    final test = ClientSpeedTest(
      client: MockClient((_) async => throw StateError('Must not connect')),
    );
    test.close();
    await expectLater(test.checkInternet(), throwsStateError);
  });
}
