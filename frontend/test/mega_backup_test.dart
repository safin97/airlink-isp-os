import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/mega_backup.dart';

void main() {
  Map<String, dynamic> configuration() => {
    'email': 'owner@example.com',
    'folder': 'AirLink Backups',
    'has_account_password': true,
    'has_backup_password': true,
    'connected': true,
    'automatic_enabled': true,
    'weekday': 6,
    'time': '02:00',
    'timezone': 'Europe/Zurich',
    'supported': true,
    'transfer_available': true,
    'local_mode': false,
    'running': false,
    'testing': false,
    'state': <String, dynamic>{},
  };
  http.Response json(Object value, [int code = 200]) => http.Response(
    jsonEncode(value),
    code,
    headers: {'content-type': 'application/json'},
  );
  Future<void> mount(WidgetTester tester, Api api) async {
    tester.view.physicalSize = const Size(1200, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    api.user ??= {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: MegaBackup(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Finder field(String label) => find.ancestor(
    of: find.byWidgetPredicate(
      (widget) => widget is TextField && widget.decoration?.labelText == label,
    ),
    matching: find.byType(TextFormField),
  );
  Future<void> openForm(WidgetTester tester) async {
    await tester.tap(find.text('MEGA account and weekly schedule'));
    await tester.pumpAndSettle();
  }

  testWidgets(
    'weekly settings preserve secrets and polling does not overwrite edits',
    (tester) async {
      final state = configuration();
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            saved = jsonDecode(request.body) as Map<String, dynamic>;
            state.addAll(saved!);
          }
          return json(state);
        }),
      );
      await mount(tester, api);
      await openForm(tester);
      expect(
        tester
            .widget<TextFormField>(field('MEGA account password'))
            .controller!
            .text,
        isEmpty,
      );
      expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        isTrue,
      );
      await tester.enterText(field('MEGA backup folder'), 'AirLink Weekly');
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextFormField>(field('MEGA backup folder'))
            .controller!
            .text,
        'AirLink Weekly',
      );
      expect(
        tester
            .widget<OutlinedButton>(
              find.widgetWithText(OutlinedButton, 'Test MEGA connection'),
            )
            .onPressed,
        isNull,
      );
      await tester.ensureVisible(find.text('Save MEGA settings'));
      await tester.tap(find.text('Save MEGA settings'));
      await tester.pumpAndSettle();
      expect(saved!['account_password'], isNull);
      expect(saved!['backup_password'], isNull);
      expect(saved!['automatic_enabled'], isTrue);
      expect(saved!['weekday'], 6);
      expect(saved!['timezone'], 'Europe/Zurich');
      expect(saved!['folder'], 'AirLink Weekly');
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'requires matching encryption passwords and clears secrets after saving',
    (tester) async {
      final state = configuration()
        ..addAll({
          'email': '',
          'connected': false,
          'has_account_password': false,
          'has_backup_password': false,
        });
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            saved = jsonDecode(request.body);
            return json({
              ...state,
              'email': saved!['email'],
              'has_account_password': true,
              'has_backup_password': true,
            });
          }
          return json(state);
        }),
      );
      await mount(tester, api);
      await openForm(tester);
      await tester.enterText(field('MEGA email'), 'backup@example.com');
      await tester.enterText(
        field('MEGA account password'),
        'private-account-password',
      );
      await tester.enterText(
        field('MEGA backup encryption password'),
        'private-backup-password',
      );
      await tester.enterText(
        field('Confirm MEGA backup password'),
        'wrong-password',
      );
      await tester.ensureVisible(find.text('Save MEGA settings'));
      await tester.tap(find.text('Save MEGA settings'));
      await tester.pumpAndSettle();
      expect(saved, isNull);
      expect(find.text('Passwords do not match'), findsOneWidget);
      await tester.enterText(
        field('Confirm MEGA backup password'),
        'private-backup-password',
      );
      await tester.ensureVisible(find.text('Save MEGA settings'));
      await tester.tap(find.text('Save MEGA settings'));
      await tester.pumpAndSettle();
      expect(saved!['account_password'], 'private-account-password');
      expect(saved!['backup_password'], 'private-backup-password');
      expect(
        tester
            .widget<TextFormField>(field('MEGA account password'))
            .controller!
            .text,
        isEmpty,
      );
      expect(
        tester
            .widget<TextFormField>(field('MEGA backup encryption password'))
            .controller!
            .text,
        isEmpty,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'connection, upload, verified history and disconnect use the right endpoints',
    (tester) async {
      final state = configuration()..['connected'] = false;
      final posts = <String>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            posts.add(request.url.path);
            if (request.url.path.endsWith('/test')) state['connected'] = true;
            if (request.url.path.endsWith('/run')) {
              state['running'] = true;
              state['state'] = {'status': 'uploading'};
            }
            if (request.url.path.endsWith('/disconnect')) {
              state.addAll({
                'connected': false,
                'has_account_password': false,
                'automatic_enabled': false,
              });
            }
          }
          return json(state);
        }),
      );
      await mount(tester, api);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Back up to MEGA now'),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(find.text('Test MEGA connection'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Back up to MEGA now'));
      await tester.pump();
      expect(find.text('MEGA status: uploading'), findsOneWidget);
      state['running'] = false;
      state['state'] = {
        'status': 'completed',
        'last_success_at': '2026-11-17T10:00:00Z',
        'last_backup': {'remote_path': 'AirLink Backups/backup.tar.airlink'},
      };
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      expect(find.text('MEGA status: completed'), findsOneWidget);
      expect(find.textContaining('Last verified file:'), findsOneWidget);
      await tester.tap(find.text('Disconnect MEGA'));
      await tester.pumpAndSettle();
      expect(find.text('MEGA is not connected'), findsOneWidget);
      expect(posts, [
        '/api/backups/mega/test',
        '/api/backups/mega/run',
        '/api/backups/mega/disconnect',
      ]);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('missing transfer support disables connection and uploads', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (_) async => json({
          ...configuration(),
          'supported': false,
          'transfer_available': false,
        }),
      ),
    );
    await mount(tester, api);
    expect(
      find.textContaining('MEGA transfer support is not installed'),
      findsOneWidget,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Test MEGA connection'),
          )
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Back up to MEGA now'),
          )
          .onPressed,
      isNull,
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('nonowner cannot see MEGA settings or trigger requests', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (_) async => throw StateError('Must not request MEGA'),
      ),
    )..user = {'role': 'manager'};
    await mount(tester, api);
    expect(find.text('MEGA cloud backup'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
