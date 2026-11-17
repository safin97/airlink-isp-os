import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/backups.dart';
import 'package:airlink_isp_os/backup_selection.dart';
import 'package:airlink_isp_os/mega_restore.dart';

void main() {
  const token = 'abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdef';
  http.Response json(Object value) => http.Response(
    jsonEncode(value),
    200,
    headers: {'content-type': 'application/json'},
  );
  Future<void> mount(WidgetTester tester, Widget widget) async {
    tester.view.physicalSize = const Size(1200, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: widget)),
      ),
    );
    await tester.pumpAndSettle();
  }

  Finder field(String label) => find.byWidgetPredicate(
    (w) => w is TextField && w.decoration?.labelText == label,
  );

  testWidgets('browse streams bounded chunks then requires confirmation', (
    tester,
  ) async {
    final bytes = Uint8List.fromList(List.generate(70000, (i) => i % 256));
    final uploaded = <int>[];
    final posts = <String>[];
    Map<String, dynamic> state = {};
    final api = Api(
      client: MockClient((request) async {
        expect(request.url.path.startsWith('/api/backups/restore'), isTrue);
        if (request.method == 'POST') {
          posts.add(request.url.path);
          final body = jsonDecode(request.body);
          if (request.url.path.endsWith('/uploads')) {
            expect(body, {
              'filename': 'saved.tar.airlink',
              'size': bytes.length,
            });
            state = {'status': 'uploading', 'token': token};
          } else if (request.url.path.endsWith('/prepare')) {
            expect(uploaded, bytes);
            expect(body, {'token': token, 'password': 'my-backup-password'});
            state = {
              'status': 'ready',
              'filename': 'saved.tar.airlink',
              'token': token,
              'local_mode': true,
            };
          } else if (request.url.path.endsWith('/confirm')) {
            expect(body, {'token': token, 'confirmation': 'RESTORE'});
            state = {'status': 'awaiting_restart'};
          }
        }
        if (request.method == 'PUT') {
          final body = jsonDecode(request.body);
          expect(body['token'], token);
          expect(body['offset'], uploaded.length);
          final block = base64Decode(body['data']);
          expect(block.length, lessThanOrEqualTo(32768));
          uploaded.addAll(block);
          return json({'received': uploaded.length});
        }
        return json(state);
      }),
    )..user = {'role': 'owner'};
    await mount(
      tester,
      MegaRestoreDialog(
        api: api,
        fromComputer: true,
        pickFile: () async => BackupSelection(
          name: 'saved.tar.airlink',
          size: bytes.length,
          read: (start, end) async => Uint8List.sublistView(bytes, start, end),
        ),
      ),
    );
    await tester.tap(find.text('Browse backup file'));
    await tester.pumpAndSettle();
    await tester.enterText(
      field('Backup encryption password'),
      'my-backup-password',
    );
    await tester.pump();
    await tester.tap(find.text('Upload and verify backup'));
    await tester.pumpAndSettle();
    expect(posts, [
      '/api/backups/restore/uploads',
      '/api/backups/restore/prepare',
    ]);
    expect(find.text('Recovery status: ready'), findsOneWidget);
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
    expect(posts.last, '/api/backups/restore/confirm');
    expect(find.text('Recovery status: awaiting_restart'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('cancelled picker and unsupported file do not upload', (
    tester,
  ) async {
    var picked = false;
    final api = Api(
      client: MockClient((request) async {
        expect(request.method, 'GET');
        return json({});
      }),
    )..user = {'role': 'owner'};
    await mount(
      tester,
      MegaRestoreDialog(
        api: api,
        fromComputer: true,
        pickFile: () async {
          if (!picked) {
            picked = true;
            return null;
          }
          return BackupSelection(
            name: 'bad.sql',
            size: 20,
            read: (_, _) async => Uint8List(20),
          );
        },
      ),
    );
    await tester.tap(find.text('Browse backup file'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Upload and verify backup'),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.text('Browse backup file'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Choose an encrypted .tar.airlink backup'),
      findsOneWidget,
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'backup page has download, file restore and MEGA without Google',
    (tester) async {
      final paths = <String>[];
      final api = Api(
        client: MockClient((request) async {
          paths.add(request.url.path);
          return json({'state': {}, 'connected': false, 'running': false});
        }),
      )..user = {'role': 'owner'};
      await mount(tester, Backups(api: api));
      expect(find.text('Download a backup'), findsOneWidget);
      expect(find.text('Restore from PC file'), findsOneWidget);
      expect(find.text('MEGA cloud backup'), findsOneWidget);
      expect(find.textContaining('Google'), findsNothing);
      expect(paths, ['/api/backups/mega']);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('nonowners cannot open the file restore flow', (tester) async {
    final api = Api(
      client: MockClient((_) async => throw StateError('Unauthorized request')),
    )..user = {'role': 'manager'};
    await mount(tester, MegaRestoreDialog(api: api, fromComputer: true));
    expect(find.text('Browse backup file'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
