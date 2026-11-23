import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'live_socket_fixture.dart';

void main() {
  for (final width in [390.0, 1440.0]) {
    testWidgets('TTLock login renders through dashboard navigation at $width', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final account = <String, dynamic>{
        'role': 'owner',
        'username': 'owner',
        'visible_sections': ['dashboard', 'ttlock'],
      };
      final socket = FakeSocket();
      final api =
          Api(
              liveConnector: (uri, token) => socket,
              client: MockClient((request) async {
                final path = request.url.path;
                return http.Response(
                  jsonEncode(
                    path.startsWith('/api/integrations/ttlock')
                        ? {'configured': false}
                        : path == '/api/auth/me'
                        ? account
                        : path == '/api/dashboard'
                        ? {}
                        : [],
                  ),
                  200,
                );
              }),
            )
            ..user = account
            ..token = 'test-owner';
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      if (width < 1000) {
        final scaffold = tester.state<ScaffoldState>(
          find.byType(Scaffold).first,
        );
        scaffold.openDrawer();
        await tester.pumpAndSettle();
      }
      final navigation = find.widgetWithText(ListTile, 'TTLock');
      await tester.ensureVisible(navigation);
      await tester.tap(navigation);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('TTLock login'), findsOneWidget);
      final username = find.widgetWithText(
        TextFormField,
        'TTLock username / phone',
      );
      final password = find.widgetWithText(TextFormField, 'TTLock password');
      await tester.ensureVisible(username);
      await tester.enterText(username, 'test-user');
      await tester.ensureVisible(password);
      await tester.enterText(password, 'test-password');
      await tester.ensureVisible(find.text('Sign in to TTLock'));
      expect(find.text('Sign in to TTLock').hitTestable(), findsOneWidget);
      await tester.ensureVisible(find.text('One-time integration setup'));
      await tester.tap(find.text('One-time integration setup'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Save integration setup'));
      await tester.pumpAndSettle();
      expect(find.text('Save integration setup').hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      api.stopLive();
    });
  }
}
