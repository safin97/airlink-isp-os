import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/local_backup.dart';

void main() {
  testWidgets(
    'validates passwords, creates, polls and downloads authenticated bytes',
    (tester) async {
      final calls = <http.Request>[];
      Uint8List? saved;
      String? filename;
      final api =
          Api(
              client: MockClient((request) async {
                calls.add(request);
                expect(request.headers['authorization'], 'Bearer owner-token');
                if (request.url.path.endsWith('/file')) {
                  return http.Response.bytes(
                    [0, 255, 128, 12],
                    200,
                    headers: {'content-type': 'application/octet-stream'},
                  );
                }
                return http.Response(
                  jsonEncode({
                    'id': 'job1',
                    'status': request.method == 'POST' ? 'creating' : 'ready',
                    'filename': 'backup.tar.airlink',
                    'size': 4,
                  }),
                  request.method == 'POST' ? 202 : 200,
                );
              }),
            )
            ..user = {'role': 'owner'}
            ..token = 'owner-token';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: LocalBackup(
                api: api,
                saveFile: (bytes, name) async {
                  saved = bytes;
                  filename = name;
                },
              ),
            ),
          ),
        ),
      );
      final fields = find.byType(TextFormField);
      await tester.tap(find.text('Create backup'));
      await tester.pump();
      expect(find.text('Use 12–1024 characters'), findsOneWidget);
      expect(calls, isEmpty);
      await tester.enterText(fields.at(0), 'my-recovery-password');
      await tester.enterText(fields.at(1), 'different-password');
      await tester.tap(find.text('Create backup'));
      await tester.pump();
      expect(find.text('Passwords do not match'), findsOneWidget);
      expect(calls, isEmpty);
      await tester.enterText(fields.at(1), 'my-recovery-password');
      await tester.tap(find.text('Create backup'));
      await tester.pump();
      expect(jsonDecode(calls.single.body), {
        'password': 'my-recovery-password',
      });
      expect(
        tester.widget<TextFormField>(fields.at(0)).controller!.text,
        isEmpty,
      );
      expect(
        find.text('Creating your encrypted backup… Keep this page open.'),
        findsOneWidget,
      );
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Download backup'));
      await tester.tap(find.text('Download backup'));
      await tester.pumpAndSettle();
      expect(saved, [0, 255, 128, 12]);
      expect(filename, 'backup.tar.airlink');
      expect(calls.map((request) => request.url.path), [
        '/api/backups/downloads',
        '/api/backups/downloads/job1',
        '/api/backups/downloads/job1/file',
      ]);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test(
    'binary download refreshes expired authentication without corrupting bytes',
    () async {
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path == '/api/auth/refresh') {
            return http.Response(
              jsonEncode({
                'access_token': 'fresh',
                'user': {'role': 'owner'},
              }),
              200,
            );
          }
          if (request.headers['authorization'] == 'Bearer expired') {
            return http.Response('{}', 401);
          }
          expect(request.headers['authorization'], 'Bearer fresh');
          return http.Response.bytes([0, 255, 128], 200);
        }),
      )..token = 'expired';
      expect(await api.request('/backups/downloads/job/file', binary: true), [
        0,
        255,
        128,
      ]);
    },
  );

  testWidgets('nonowners do not see download controls', (tester) async {
    final api = Api()..user = {'role': 'manager'};
    await tester.pumpWidget(MaterialApp(home: LocalBackup(api: api)));
    expect(find.text('Create backup'), findsNothing);
  });
}
