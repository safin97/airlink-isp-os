import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/google_drive_backup.dart';

void main() {
  Map<String, dynamic> configuration() => {
    'client_id': '1234567890-airlink.apps.googleusercontent.com',
    'redirect_uri':
        'https://airlink.example.com/api/backups/google-drive/callback',
    'folder_name': 'AirLink Backups',
    'has_client_secret': true,
    'has_backup_password': true,
    'connected': true,
    'account_email': 'owner@example.com',
    'automatic_enabled': true,
    'weekday': 6,
    'time': '02:00',
    'timezone': 'Europe/Zurich',
    'supported': true,
    'running': false,
    'state': <String, dynamic>{},
  };
  http.Response json(Object value, [int status = 200]) => http.Response(
    jsonEncode(value),
    status,
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
          body: SingleChildScrollView(child: GoogleDriveBackup(api: api)),
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

  testWidgets(
    'weekly settings preserve saved secrets and polling preserves edits',
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
      expect(find.text('Connected: owner@example.com'), findsOneWidget);
      expect(find.text('Sunday'), findsOneWidget);
      expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        isTrue,
      );
      final secret = tester.widget<TextFormField>(field('OAuth client secret'));
      expect(secret.controller!.text, isEmpty);
      final editable = find.descendant(
        of: field('OAuth client secret'),
        matching: find.byType(EditableText),
      );
      expect(tester.widget<EditableText>(editable).obscureText, isTrue);
      await tester.enterText(field('Backup folder name'), 'Weekly ISP backups');
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextFormField>(field('Backup folder name'))
            .controller!
            .text,
        'Weekly ISP backups',
      );
      final save = find.widgetWithText(FilledButton, 'Save backup settings');
      await tester.ensureVisible(save);
      await tester.tap(save);
      await tester.pumpAndSettle();
      expect(saved!['automatic_enabled'], isTrue);
      expect(saved!['weekday'], 6);
      expect(saved!['time'], '02:00');
      expect(saved!['timezone'], 'Europe/Zurich');
      expect(saved!['folder_name'], 'Weekly ISP backups');
      expect(saved!['client_secret'], isNull);
      expect(saved!['backup_password'], isNull);
      expect(find.text('Backup settings saved.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('manual backup shows progress then verified history', (
    tester,
  ) async {
    final state = configuration();
    final actions = <String>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          actions.add(request.url.path);
          state['running'] = true;
          state['state'] = {
            'status': 'uploading',
            'uploaded_bytes': 50,
            'total_bytes': 100,
          };
        }
        return json(state);
      }),
    );
    await mount(tester, api);
    final button = find.widgetWithText(FilledButton, 'Back up now');
    await tester.tap(button);
    await tester.pump();
    await tester.pump();
    expect(actions, ['/api/backups/google-drive/run']);
    expect(tester.widget<FilledButton>(button).onPressed, isNull);
    expect(find.text('Backup status: uploading'), findsOneWidget);
    expect(
      tester
          .widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator))
          .value,
      .5,
    );
    state['running'] = false;
    state['state'] = {
      'status': 'completed',
      'last_success_at': '2026-11-09T22:00:00Z',
      'history': [
        {
          'status': 'completed',
          'started_at': '2026-11-09T22:00:00Z',
          'backup': {'filename': 'AirLink-weekly.tar.airlink'},
        },
      ],
    };
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(find.text('Backup status: completed'), findsOneWidget);
    expect(find.text('Recent backups'), findsOneWidget);
    expect(find.text('AirLink-weekly.tar.airlink'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('failed save remains visible across status polling', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async => request.method == 'PUT'
            ? json({'detail': 'Google client rejected'}, 409)
            : json(configuration()),
      ),
    );
    await mount(tester, api);
    final save = find.widgetWithText(FilledButton, 'Save backup settings');
    await tester.ensureVisible(save);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(find.text('Google client rejected'), findsOneWidget);
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    expect(find.text('Google client rejected'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('local preview cannot start production backup', (tester) async {
    final api = Api(
      client: MockClient(
        (_) async => json({...configuration(), 'supported': false}),
      ),
    );
    await mount(tester, api);
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Back up now'),
          )
          .onPressed,
      isNull,
    );
    expect(
      find.textContaining('unavailable in the local preview'),
      findsOneWidget,
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('manager cannot view settings or trigger any requests', (
    tester,
  ) async {
    final api =
        Api(
            client: MockClient((_) async {
              fail('No backup request permitted');
            }),
          )
          ..user = {
            'role': 'manager',
            'sections': ['settings'],
          };
    await mount(tester, api);
    expect(find.byType(TextFormField), findsNothing);
    expect(find.text('Back up now'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
