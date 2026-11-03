import 'live_socket_fixture.dart';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/section_access.dart';

void main() {
  testWidgets('manager navigation and requests follow live section changes', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final account = <String, dynamic>{
      'id': 'm',
      'username': 'manager',
      'role': 'manager',
      'sections': ['towers'],
    };
    final requests = <String>[];
    final socket = FakeSocket();
    final api =
        Api(
            liveConnector: (uri, token) => socket,
            client: MockClient((request) async {
              requests.add(request.url.path);
              final Object body = request.url.path == '/api/auth/me'
                  ? account
                  : [];
              return http.Response(
                jsonEncode(body),
                200,
                headers: {'content-type': 'application/json'},
              );
            }),
          )
          ..token = 'live-test-token'
          ..user = Map<String, dynamic>.from(account);
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ListTile, 'Towers'), findsOneWidget);
    for (final label in [
      'Dashboard',
      'Managers',
      'Settings',
      'Software Updates',
      'ISP Card',
      'Reports',
    ]) {
      expect(find.widgetWithText(ListTile, label), findsNothing);
    }
    expect(find.widgetWithText(ListTile, 'My account'), findsOneWidget);
    expect(requests, isNot(contains('/api/dashboard')));
    expect(requests, isNot(contains('/api/alerts')));
    requests.clear();
    account['sections'] = ['reports'];
    socket.controller.add({
      'type': 'patch',
      'user': Map<String, dynamic>.from(account),
      'rows': <String, dynamic>{
        'towers': [],
        'places': [],
        'devices': [],
        'sectors': [],
      },
      'summary': <String, dynamic>{},
    });
    await tester.pumpAndSettle();
    expect(find.widgetWithText(ListTile, 'Towers'), findsNothing);
    expect(find.widgetWithText(ListTile, 'Reports'), findsOneWidget);
    expect(find.text('Generate report'), findsOneWidget);
    expect(requests, isEmpty);
    account['sections'] = <String>[];
    socket.controller.add({
      'type': 'patch',
      'user': Map<String, dynamic>.from(account),
      'rows': <String, dynamic>{
        'towers': [],
        'places': [],
        'devices': [],
        'sectors': [],
      },
      'summary': <String, dynamic>{},
    });
    await tester.pumpAndSettle();
    expect(find.text('No sections assigned'), findsOneWidget);
    expect(find.widgetWithText(ListTile, 'My account'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('granted managers can open Settings and Software Updates', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final account = <String, dynamic>{
      'username': 'manager',
      'role': 'manager',
      'sections': ['settings'],
    };
    final requests = <String>[];
    final socket = FakeSocket();
    final api =
        Api(
            liveConnector: (uri, token) => socket,
            client: MockClient((request) async {
              requests.add(request.url.path);
              final Object body = switch (request.url.path) {
                '/api/auth/me' => account,
                '/api/network' => {'interfaces': <dynamic>[]},
                '/api/updates' => {
                  'current_version': 'test',
                  'state': {
                    'configured': true,
                    'state': {'status': 'idle'},
                  },
                  'history': <dynamic>[],
                },
                '/api/updates/check' => <String, dynamic>{},
                _ => <dynamic>[],
              };
              return http.Response(
                jsonEncode(body),
                200,
                headers: {'content-type': 'application/json'},
              );
            }),
          )
          ..token = 'live-test-token'
          ..user = Map<String, dynamic>.from(account);
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Choose a settings page'), findsOneWidget);
    expect(find.text('Device API logins'), findsNothing);
    expect(requests, isNot(contains('/api/network')));
    await tester.tap(find.widgetWithText(ListTile, 'SNMP profiles').last);
    await tester.pumpAndSettle();
    expect(find.text('SNMP credential profiles'), findsOneWidget);
    await tester.tap(find.widgetWithText(ListTile, 'Network'));
    await tester.pumpAndSettle();
    expect(requests, contains('/api/network'));
    expect(requests, contains('/api/snmp-profiles'));
    expect(find.widgetWithText(ListTile, 'Managers'), findsNothing);
    expect(find.widgetWithText(ListTile, 'Software Updates'), findsNothing);
    account['sections'] = ['software_updates'];
    socket.controller.add({
      'type': 'patch',
      'user': Map<String, dynamic>.from(account),
      'rows': <String, dynamic>{
        'towers': [],
        'places': [],
        'devices': [],
        'sectors': [],
      },
      'summary': <String, dynamic>{},
    });
    await tester.pumpAndSettle();
    expect(find.text('Software Update Center'), findsOneWidget);
    expect(find.widgetWithText(ListTile, 'Settings'), findsNothing);
    expect(requests, contains('/api/updates/check'));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'owner retains full navigation and saves selected manager sections',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            expect(request.url.path, '/api/users/m/sections');
            saved = Map<String, dynamic>.from(jsonDecode(request.body));
            return http.Response('{}', 200);
          }
          final Object body = request.url.path == '/api/users'
              ? [
                  {
                    'id': 'm',
                    'username': 'manager',
                    'role': 'manager',
                    'active': true,
                    'sections': ['towers'],
                  },
                ]
              : request.url.path == '/api/dashboard'
              ? <String, dynamic>{}
              : [];
          return http.Response(jsonEncode(body), 200);
        }),
      )..user = {'username': 'owner', 'role': 'owner', 'sections': <String>[]};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      for (final label in [
        'Managers',
        'Settings',
        'Software Updates',
        'ISP Card',
      ]) {
        expect(find.widgetWithText(ListTile, label), findsOneWidget);
      }
      await tester.tap(find.widgetWithText(ListTile, 'Managers'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Section access'));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(SectionAccessDialog),
          matching: find.byType(CheckboxListTile),
        ),
        findsNWidgets(assignableSections.length),
      );
      await tester.tap(find.text('Clear all'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(CheckboxListTile, 'Reports'));
      await tester.pumpAndSettle();
      await tester.tap(
        find.widgetWithText(CheckboxListTile, 'Software Updates'),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(CheckboxListTile, 'Settings'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('edit-settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save access'));
      await tester.pumpAndSettle();
      expect(saved, {
        'sections': ['reports', 'software_updates', 'settings'],
        'editable_sections': ['settings'],
        'deletable_sections': [],
      });
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('read-only sections show data and disable mutations', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final account = <String, dynamic>{
      'role': 'manager',
      'username': 'reader',
      'sections': ['settings', 'software_updates'],
      'editable_sections': [],
    };
    final writes = <String>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method != 'GET') writes.add(request.url.path);
        final Object body = switch (request.url.path) {
          '/api/auth/me' => account,
          '/api/network' => {'interfaces': []},
          '/api/updates' => {
            'current_version': 'test',
            'state': {
              'configured': true,
              'restart_supported': true,
              'state': {'status': 'idle'},
              'available': {'version': 'next', 'size': 1024},
            },
            'history': [],
          },
          _ => [],
        };
        return http.Response(jsonEncode(body), 200);
      }),
    )..user = account;
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Current version: test'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Update now'))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Restart system'),
          )
          .onPressed,
      isNull,
    );
    await tester.pump(const Duration(seconds: 30));
    await tester.pumpAndSettle();
    expect(writes, isEmpty);
    await tester.tap(find.widgetWithText(ListTile, 'Settings'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'SNMP profiles').last);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Add SNMP profile'),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.widgetWithText(ListTile, 'Network'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Apply configuration'),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.widgetWithText(ListTile, 'Audit log'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'View audit log'),
          )
          .onPressed,
      isNotNull,
    );
    expect(tester.takeException(), isNull);
    expect(writes, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });

  test('edit permissions require visible sections, with owner full access', () {
    final manager = <String, dynamic>{
      'role': 'manager',
      'sections': ['towers'],
      'editable_sections': [],
    };
    expect(hasSection(manager, 'towers'), isTrue);
    expect(canEditSection(manager, 'towers'), isFalse);
    manager['editable_sections'] = ['settings', 'towers'];
    expect(canEditSection(manager, 'towers'), isTrue);
    expect(canEditSection(manager, 'settings'), isFalse);
    expect(
      canEditSection({'role': 'owner', 'editable_sections': []}, 'settings'),
      isTrue,
    );
    expect(canEditSection({'role': 'viewer'}, 'towers'), isFalse);
  });
}
