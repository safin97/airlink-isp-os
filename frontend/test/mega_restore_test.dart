import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/mega_restore.dart';

void main() {
  const filename = 'AirLink-20261117T120000Z-abcdef01.tar.airlink';
  const token = 'abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdef';
  http.Response json(Object value) => http.Response(
    jsonEncode(value),
    200,
    headers: {'content-type': 'application/json'},
  );
  Future<void> mount(WidgetTester tester, Api api) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: MegaRestoreDialog(api: api)),
      ),
    );
    await tester.pumpAndSettle();
  }

  Finder field(String label) => find.byWidgetPredicate(
    (w) => w is TextField && w.decoration?.labelText == label,
  );

  testWidgets('verification precedes explicit restore confirmation', (
    tester,
  ) async {
    Map<String, dynamic> state = {};
    final posts = <String>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/files')) {
          return json({
            'files': [
              {'filename': filename, 'size': 99},
            ],
          });
        }
        if (request.method == 'POST') {
          posts.add(request.url.path);
          final body = jsonDecode(request.body);
          if (request.url.path.endsWith('/prepare')) {
            expect(body['filename'], filename);
            expect(body['password'], 'backup-encryption-password');
            state = {
              'status': 'ready',
              'filename': filename,
              'token': token,
              'local_mode': true,
            };
          } else if (request.url.path.endsWith('/confirm')) {
            expect(body, {'token': token, 'confirmation': 'RESTORE'});
            state = {
              'status': 'awaiting_restart',
              'message':
                  'Stop the local server and run ./scripts/live.sh again.',
            };
          }
        }
        return json(state);
      }),
    )..user = {'role': 'owner'};
    await mount(tester, api);
    expect(posts, isEmpty);
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('$filename (99 bytes)').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      field('Backup encryption password'),
      'backup-encryption-password',
    );
    await tester.pump();
    await tester.tap(find.text('Download and verify backup'));
    await tester.pumpAndSettle();
    expect(posts, ['/api/backups/mega/restore/prepare']);
    expect(find.textContaining('stop the local server'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Confirm restore'),
          )
          .onPressed,
      isNull,
    );
    await tester.enterText(
      field('Type RESTORE to replace current data'),
      'yes',
    );
    await tester.pump();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Confirm restore'),
          )
          .onPressed,
      isNull,
    );
    await tester.enterText(
      field('Type RESTORE to replace current data'),
      'RESTORE',
    );
    await tester.pump();
    await tester.tap(find.text('Confirm restore'));
    await tester.pumpAndSettle();
    expect(posts.last, '/api/backups/mega/restore/confirm');
    expect(find.text('Recovery status: awaiting_restart'), findsOneWidget);
    expect(find.text('Confirm restore'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('verification failure displays error and never confirms', (
    tester,
  ) async {
    final api = Api(
      client: MockClient((request) async {
        expect(request.method, 'GET');
        return json(
          request.url.path.endsWith('/files')
              ? {'files': []}
              : {
                  'status': 'failed',
                  'error':
                      'Backup password is incorrect or the encrypted file is damaged',
                },
        );
      }),
    )..user = {'role': 'owner'};
    await mount(tester, api);
    expect(find.textContaining('password is incorrect'), findsOneWidget);
    expect(find.text('Confirm restore'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('nonowners cannot load restore data', (tester) async {
    final api = Api(
      client: MockClient((_) async => throw StateError('Unauthorized request')),
    )..user = {'role': 'manager'};
    await mount(tester, api);
    expect(find.text('Restore from MEGA'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
