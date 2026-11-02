import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/role_management.dart';
import 'package:airlink_isp_os/section_access.dart';
import 'account_type_fixtures.dart';

void main() {
  testWidgets(
    'owner edits and deletes system access roles; Owner stays protected',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final rows = builtInAccountTypes
          .map((r) => Map<String, dynamic>.from(r))
          .toList();
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'GET') {
            return http.Response(jsonEncode(rows), 200);
          }
          final id = request.url.path.split('/').last;
          if (request.method == 'PUT') {
            rows
                .firstWhere((r) => r['id'] == id)
                .addAll(jsonDecode(request.body) as Map<String, dynamic>);
            return http.Response('{}', 200);
          }
          expect(request.method, 'DELETE');
          rows.removeWhere((r) => r['id'] == id);
          return http.Response('', 204);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RoleManagement(
                api: api,
                accessGroups: true,
                onChanged: () async {},
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final ownerTile = find.widgetWithText(ListTile, 'Owner');
      expect(
        tester
            .widget<IconButton>(
              find.descendant(
                of: ownerTile,
                matching: find.byWidgetPredicate(
                  (w) => w is IconButton && w.tooltip == 'Edit access role',
                ),
              ),
            )
            .onPressed,
        isNull,
      );
      for (final kind in ['Manager', 'Technician', 'Viewer']) {
        final tile = find.widgetWithText(ListTile, kind);
        await tester.tap(
          find.descendant(
            of: tile,
            matching: find.byTooltip('Edit access role'),
          ),
        );
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextFormField), '$kind team');
        await tester.tap(find.byKey(const ValueKey('read-dashboard')));
        await tester.tap(find.text('Save'));
        await tester.pumpAndSettle();
        expect(rows.firstWhere((r) => r['name'] == '$kind team')['sections'], [
          'dashboard',
        ]);
        await tester.tap(
          find.descendant(
            of: find.widgetWithText(ListTile, '$kind team'),
            matching: find.byTooltip('Delete access role'),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
        await tester.pumpAndSettle();
        expect(find.text('$kind team'), findsNothing);
      }
      expect(tester.takeException(), isNull);
    },
  );

  test('configured Viewer uses its saved read edit and delete permissions', () {
    final user = <String, dynamic>{
      'role': 'viewer',
      'access_policy_configured': true,
      'sections': ['towers'],
      'editable_sections': ['towers'],
      'deletable_sections': [],
    };
    expect(hasSection(user, 'towers'), isTrue);
    expect(hasSection(user, 'dashboard'), isFalse);
    expect(canEditSection(user, 'towers'), isTrue);
    expect(canDeleteSection(user, 'towers'), isFalse);
    expect(hasSection(user, 'managers'), isFalse);
  });
}
