import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/update_center.dart';

void main() {
  Future<void> mount(WidgetTester tester, Api api) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: UpdateCenter(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Map<String, dynamic> release() => {
    'version': '0.2.0',
    'sequence': 2,
    'size': 1024 * 1024,
    'release_notes': 'Verified release notes',
    'reboot_required': false,
  };

  http.Response json(Object value, [int status = 200]) => http.Response(
    jsonEncode(value),
    status,
    headers: {'content-type': 'application/json'},
  );

  testWidgets(
    'Automatically checks releases without downloading or installing; cancel is safe',
    (tester) async {
      final actions = <String>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            actions.add(request.url.path);
            return json(release());
          }
          return json({
            'current_version': '0.1.0',
            'state': {
              'configured': true,
              'state': {'status': 'idle'},
              'available': release(),
            },
            'history': [],
          });
        }),
      );
      await mount(tester, api);
      expect(actions, ['/api/updates/check']);
      expect(find.text('Available release: 0.2.0'), findsOneWidget);
      expect(find.text('Open latest release'), findsNothing);
      final button = find.widgetWithText(FilledButton, 'Update now');
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(actions, ['/api/updates/check']);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'One confirmation downloads, verifies, installs and waits for actual completion',
    (tester) async {
      final actions = <String>[];
      final payloads = <Map>[];
      var installed = false;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            actions.add(request.url.path);
            if (request.url.path != '/api/updates/check') {
              payloads.add(jsonDecode(request.body) as Map);
            }
            if (request.url.path == '/api/updates/install') installed = true;
            return json(release());
          }
          return json({
            'current_version': installed ? '0.2.0' : '0.1.0',
            'state': {
              'configured': true,
              'state': installed
                  ? {
                      'status': 'installed',
                      'version': '0.2.0',
                      'finished': 123,
                      'reboot_required': false,
                    }
                  : {'status': 'idle'},
              'available': installed ? null : release(),
            },
            'history': [],
          });
        }),
      );
      await mount(tester, api);
      final button = find.widgetWithText(FilledButton, 'Update now');
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Update now').last);
      await tester.pumpAndSettle();
      expect(actions, [
        '/api/updates/check',
        '/api/updates/download',
        '/api/updates/verify',
        '/api/updates/install',
      ]);
      expect(
        payloads.every((p) => p['version'] == '0.2.0' && p['sequence'] == 2),
        isTrue,
      );
      expect(find.text('Update installed successfully.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('Failed verification stops before installation', (tester) async {
    final actions = <String>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          actions.add(request.url.path);
          if (request.url.path == '/api/updates/verify') {
            return json({'detail': 'Package digest mismatch'}, 409);
          }
          return json(release());
        }
        return json({
          'current_version': '0.1.0',
          'state': {
            'configured': true,
            'state': {'status': 'idle'},
            'available': release(),
          },
          'history': [],
        });
      }),
    );
    await mount(tester, api);
    final button = find.widgetWithText(FilledButton, 'Update now');
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Update now').last);
    await tester.pumpAndSettle();
    expect(actions, isNot(contains('/api/updates/install')));
    expect(find.text('Package digest mismatch'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('Local preview fetches release details but cannot install', (
    tester,
  ) async {
    var checks = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          checks++;
          return json(release());
        }
        return json({
          'current_version': '0.1.0',
          'state': {
            'configured': true,
            'preview': true,
            'install_supported': false,
            'state': {'status': 'idle'},
            'available': release(),
          },
          'history': [],
        });
      }),
    );
    await mount(tester, api);
    expect(checks, 1);
    expect(find.text('Available release: 0.2.0'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Update now'))
          .onPressed,
      isNull,
    );
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
    'Restart is confirmed, independent of available updates, and waits for a new boot',
    (tester) async {
      var requested = false;
      var newBoot = false;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path == '/api/system/restart') {
            expect(jsonDecode(request.body), {'confirm': true});
            requested = true;
            return json({
              'status': 'restart_requested',
              'boot_id': 'before',
              'delay_seconds': 5,
            }, 202);
          }
          return json({
            'current_version': '0.1.3-dev',
            'state': {
              'configured': false,
              'restart_supported': true,
              'restart': {
                'pending': requested && !newBoot,
                'boot_id': newBoot ? 'after' : 'before',
              },
              'state': {'status': 'idle'},
            },
            'history': [],
          });
        }),
      );
      await mount(tester, api);
      final button = find.widgetWithText(OutlinedButton, 'Restart system');
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(requested, isFalse);
      await tester.tap(button);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Restart system'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pump();
      expect(requested, isTrue);
      expect(find.text('System restarted successfully.'), findsNothing);
      newBoot = true;
      await tester.pumpAndSettle();
      expect(find.text('System restarted successfully.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final blocked in [
    'preview',
    'queued',
    'installing',
    'failed',
    'restart-pending',
  ]) {
    testWidgets('Restart is disabled for $blocked', (tester) async {
      final api = Api(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          return json({
            'state': {
              'configured': false,
              'restart_supported': blocked != 'preview',
              'restart': {
                'pending': blocked == 'restart-pending',
                'boot_id': 'same',
              },
              'state': {'status': blocked},
            },
            'history': [],
          });
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: UpdateCenter(api: api)),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(OutlinedButton, 'Restart system'),
            )
            .onPressed,
        isNull,
      );
      await tester.pumpWidget(const SizedBox());
    });
  }
}
