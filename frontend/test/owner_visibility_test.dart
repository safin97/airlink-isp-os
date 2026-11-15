import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/role_management.dart';
import 'package:airlink_isp_os/owner_visibility.dart';
import 'package:airlink_isp_os/section_access.dart';
import 'live_socket_fixture.dart';

void main() {
  testWidgets(
    'owner row edits shown pages, preserves recovery controls and saves immediately',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1440, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      Map<String, dynamic> row = {
        'id': 'builtin:owner',
        'account_type': 'owner',
        'name': 'Owner',
        'can_manage': true,
        'can_delete': false,
        'visible_sections': ownerSections.keys.toList(),
      };
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            expect(
              request.url.path,
              '/api/access-roles/builtin:owner/visibility',
            );
            saved = Map<String, dynamic>.from(jsonDecode(request.body));
            row = {...row, ...saved!};
            return http.Response(jsonEncode(row), 200);
          }
          return http.Response(jsonEncode([row]), 200);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: RoleManagement(
              api: api,
              accessGroups: true,
              onChanged: () async {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<IconButton>(
              find.byWidgetPredicate(
                (w) => w is IconButton && w.tooltip == 'Delete access role',
              ),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(find.byTooltip('Edit access role'));
      await tester.pumpAndSettle();
      expect(find.byType(OwnerVisibilityDialog), findsOneWidget);
      expect(find.textContaining('all owner accounts'), findsOneWidget);
      for (final key in pinnedOwnerSections) {
        final box = tester.widget<CheckboxListTile>(
          find.byKey(ValueKey('owner-show-$key')),
        );
        expect(box.value, isTrue);
        expect(box.onChanged, isNull);
      }
      await tester.tap(find.text('Hide optional sections'));
      await tester.pump();
      expect(
        tester
            .widget<CheckboxListTile>(
              find.byKey(const ValueKey('owner-show-diagnostics')),
            )
            .value,
        isFalse,
      );
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(saved!.keys, ['visible_sections']);
      expect(saved!['visible_sections'], unorderedEquals(pinnedOwnerSections));
      expect(
        api.user!['visible_sections'],
        unorderedEquals(pinnedOwnerSections),
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'owner navigation follows visibility and live changes without losing recovery pages',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1440, 1100));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final socket = FakeSocket();
      final account = <String, dynamic>{
        'role': 'owner',
        'username': 'owner',
        'visible_sections': ['dashboard', 'towers'],
      };
      final api =
          Api(
              liveConnector: (uri, token) => socket,
              client: MockClient(
                (r) async => http.Response(
                  jsonEncode(
                    r.url.path == '/api/dashboard'
                        ? {}
                        : r.url.path == '/api/auth/me'
                        ? account
                        : [],
                  ),
                  200,
                ),
              ),
            )
            ..user = account
            ..token = 'test-live-owner';
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.widgetWithText(ListTile, 'Dashboard'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'Towers'), findsOneWidget);
      for (final name in [
        'Settings',
        'Diagnostics',
        'Managers',
        'Device login',
        'Towers API',
        'Deye Solar',
      ]) {
        expect(find.widgetWithText(ListTile, name), findsNothing);
      }
      socket.controller.add({
        'type': 'patch',
        'user': {
          ...account,
          'visible_sections': ['diagnostics'],
        },
      });
      await tester.pumpAndSettle();
      expect(find.widgetWithText(ListTile, 'Dashboard'), findsNothing);
      expect(find.widgetWithText(ListTile, 'Diagnostics'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'Settings'), findsNothing);
      expect(
        tester
            .widget<ListTile>(find.widgetWithText(ListTile, 'Access Roles'))
            .selected,
        isTrue,
      );
      expect(find.widgetWithText(ListTile, 'My account'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test(
    'owner defaults and authorization stay intact while a section is hidden',
    () {
      expect(hasSection({'role': 'owner'}, 'diagnostics'), isTrue);
      final owner = <String, dynamic>{'role': 'owner', 'visible_sections': []};
      expect(hasSection(owner, 'towers'), isFalse);
      expect(hasSection(owner, 'access_roles'), isTrue);
      expect(hasSection(owner, 'my_account'), isTrue);
      expect(canEditSection(owner, 'towers'), isTrue);
      expect(canDeleteSection(owner, 'towers'), isTrue);
    },
  );
}
