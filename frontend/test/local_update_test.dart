import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/backup_selection.dart';
import 'package:airlink_isp_os/update_center.dart';

void main() {
  for (final mode in ['install', 'cancel', 'invalid']) {
    testWidgets('Local upload with online source unavailable: $mode', (
      tester,
    ) async {
      final actions = <String>[];
      final content = Uint8List.fromList(List.generate(40000, (i) => i % 256));
      var installed = false;
      final api = Api(
        client: MockClient((req) async {
          Object value = {};
          var status = 200;
          if (req.method == 'POST') {
            actions.add(req.url.path);
            final body = jsonDecode(req.body) as Map;
            switch (req.url.path) {
              case '/api/updates/check':
                value = {'detail': 'GitHub unavailable'};
                status = 503;
              case '/api/updates/local/start':
                expect(body['size'], content.length);
                value = {'token': 'upload-token', 'received': 0};
              case '/api/updates/local/chunk':
                final offset = body['offset'] as int;
                final bytes = base64Decode(body['data']);
                expect(bytes, content.sublist(offset, offset + bytes.length));
                expect(body['token'], 'upload-token');
                value = {'received': offset + bytes.length};
              case '/api/updates/local/finish':
                if (mode == 'invalid') {
                  value = {'detail': 'Invalid update signature'};
                  status = 409;
                } else {
                  value = {
                    'status': 'ready',
                    'release': {
                      'version': '0.2.0',
                      'sequence': 2,
                      'release_notes': 'Offline test',
                    },
                  };
                }
              case '/api/updates/local/install':
                expect(body, {
                  'token': 'upload-token',
                  'version': '0.2.0',
                  'sequence': 2,
                  'confirm': true,
                });
                installed = true;
                value = {'status': 'install', 'version': '0.2.0'};
              case '/api/updates/local/cancel':
                expect(body, {'token': 'upload-token'});
              default:
                fail('Unexpected network update action: ${req.url.path}');
            }
          } else {
            value = {
              'current_version': installed ? '0.2.0' : '0.1.0',
              'history': [],
              'state': {
                'configured': true,
                'local_update_supported': true,
                'install_supported': true,
                'state': installed
                    ? {
                        'status': 'installed',
                        'version': '0.2.0',
                        'finished': 123,
                      }
                    : {'status': 'idle'},
              },
            };
          }
          return http.Response(
            jsonEncode(value),
            status,
            headers: {'content-type': 'application/json'},
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: UpdateCenter(
                api: api,
                pickLocalFile: () async => BackupSelection(
                  name: 'release.airlink-update',
                  size: content.length,
                  read: (start, end) async => content.sublist(start, end),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('GitHub unavailable'), findsOneWidget);
      final open = find.widgetWithText(OutlinedButton, 'Update from file');
      await tester.ensureVisible(open);
      expect(tester.widget<OutlinedButton>(open).onPressed, isNotNull);
      await tester.tap(open);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Browse update file'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Upload and verify'));
      await tester.pumpAndSettle();
      expect(actions.where((p) => p.endsWith('/chunk')).length, 2);
      expect(installed, false);
      if (mode == 'invalid') {
        expect(find.text('Invalid update signature'), findsOneWidget);
        expect(find.text('Install verified update'), findsNothing);
      } else {
        expect(find.text('Verified release: 0.2.0'), findsOneWidget);
      }
      if (mode == 'install') {
        await tester.tap(find.text('Install verified update'));
        await tester.pumpAndSettle();
        expect(installed, true);
        expect(find.text('Update installed successfully.'), findsOneWidget);
        expect(actions, isNot(contains('/api/updates/local/cancel')));
      } else {
        await tester.tap(find.text('Cancel'));
        await tester.pumpAndSettle();
        expect(actions.last, '/api/updates/local/cancel');
        expect(installed, false);
      }
      expect(actions, isNot(contains('/api/updates/download')));
      await tester.pumpWidget(const SizedBox());
    });
  }
}
