import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/role_management.dart';
import 'package:airlink_isp_os/section_access.dart';

void main() {
  testWidgets('role reader can view details but cannot edit or delete', (
    tester,
  ) async {
    final requests = <String>[];
    final api =
        Api(
            client: MockClient((r) async {
              requests.add('${r.method} ${r.url.path}');
              return http.Response(
                jsonEncode(
                  r.url.path == '/api/access-roles'
                      ? [
                          {
                            'id': 'r',
                            'name': 'Support',
                            'access_role_id': 'g',
                            'access_role_name': 'Readers',
                            'sections': ['towers'],
                            'editable_sections': [],
                            'deletable_sections': [],
                            'can_manage': true,
                          },
                        ]
                      : [
                          {'id': 'g', 'name': 'Readers'},
                        ],
                ),
                200,
              );
            }),
          )
          ..user = {
            'role': 'manager',
            'sections': ['access_roles'],
            'editable_sections': [],
            'deletable_sections': [],
          };
    expect(hasSection(api.user!, 'roles'), isFalse);
    expect(hasSection(api.user!, 'access_roles'), isTrue);
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
    expect(requests, ['GET /api/access-roles']);
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Add access role'),
          )
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<IconButton>(
            find.byWidgetPredicate(
              (w) => w is IconButton && w.tooltip == 'Edit access role',
            ),
          )
          .onPressed,
      isNull,
    );
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
    await tester.tap(find.byTooltip('View access role'));
    await tester.pumpAndSettle();
    expect(find.text('View access role'), findsOneWidget);
    expect(find.text('Save'), findsNothing);
    expect(
      tester.widget<TextFormField>(find.byType(TextFormField)).enabled,
      isFalse,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'manager permission picker includes role sections and independent deletion',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((r) async {
          saved = jsonDecode(r.body);
          return http.Response('{}', 200);
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SectionAccessDialog(
              api: api,
              account: const {
                'id': 'm',
                'username': 'manager',
                'sections': [],
                'editable_sections': [],
                'deletable_sections': [],
              },
            ),
          ),
        ),
      );
      await tester.tap(find.widgetWithText(CheckboxListTile, 'Access Roles'));
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('edit-access_roles')));
      await tester.tap(find.byKey(const ValueKey('delete-access_roles')));
      await tester.pump();
      await tester.tap(find.text('Save access'));
      await tester.pumpAndSettle();
      expect(saved, {
        'sections': ['access_roles'],
        'editable_sections': ['access_roles'],
        'deletable_sections': ['access_roles'],
      });
      expect(tester.takeException(), isNull);
    },
  );
}
