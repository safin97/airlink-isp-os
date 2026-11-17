import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/deye_sharing.dart';
import 'package:airlink_isp_os/deye_solar.dart';
import 'package:airlink_isp_os/section_access.dart';

void main() {
  testWidgets(
    'owner shows and hides solar for a Wakil, failed changes stay unchanged',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <bool>[];
      bool fail = false;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            expect(request.url.path, '/api/integrations/deye/sharing/wakil1');
            final enabled = jsonDecode(request.body)['enabled'] as bool;
            writes.add(enabled);
            return fail
                ? http.Response('{"detail":"Could not save"}', 409)
                : http.Response(
                    jsonEncode({'id': 'wakil1', 'enabled': enabled}),
                    200,
                  );
          }
          return http.Response(
            jsonEncode([
              {
                'id': 'wakil1',
                'username': 'north-wakil',
                'role_name': 'Wakil',
                'enabled': false,
                'shared_by_other_owner': false,
              },
              {
                'id': 'other',
                'username': 'other',
                'role_name': 'Manager',
                'enabled': false,
                'shared_by_other_owner': true,
              },
            ]),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DeyeSharing(api: api)),
        ),
      );
      await tester.pumpAndSettle();
      final toggle = find.byKey(const ValueKey('deye-share-wakil1'));
      expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
      expect(
        tester
            .widget<SwitchListTile>(
              find.byKey(const ValueKey('deye-share-other')),
            )
            .onChanged,
        isNull,
      );
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(toggle).value, isTrue);
      expect(find.text('Solar readings visible · read-only'), findsOneWidget);
      fail = true;
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(toggle).value, isTrue);
      expect(find.text('Could not save'), findsOneWidget);
      fail = false;
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
      expect(writes, [true, false, false]);
    },
  );

  testWidgets(
    'shared reader sees owner setup status without any configuration controls',
    (tester) async {
      final api =
          Api(
              client: MockClient((request) async {
                expect(request.method, 'GET');
                return http.Response(
                  '{"configured":false,"shared":true,"dashboard_station":null}',
                  200,
                );
              }),
            )
            ..user = {
              'role': 'manager',
              'show_deye_solar': true,
              'sections': ['deye'],
              'editable_sections': ['deye'],
              'deletable_sections': ['deye'],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: DeyeSolar(api: api)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('The owner has not connected'),
        findsOneWidget,
      );
      expect(find.text('Connect Deye Cloud'), findsNothing);
      expect(find.text('Show solar readings'), findsNothing);
      expect(find.byType(TextField), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test(
    'owner visibility overrides legacy role bits and all shared users are read-only',
    () {
      final wakil = <String, dynamic>{
        'role': 'manager',
        'show_deye_solar': false,
        'sections': ['deye'],
        'editable_sections': ['deye'],
        'deletable_sections': ['deye'],
      };
      expect(hasSection(wakil, 'deye'), isFalse);
      wakil['show_deye_solar'] = true;
      expect(hasSection(wakil, 'deye'), isTrue);
      expect(canEditSection(wakil, 'deye'), isFalse);
      expect(canDeleteSection(wakil, 'deye'), isFalse);
      expect(
        hasSection({'role': 'viewer', 'show_deye_solar': true}, 'deye'),
        isTrue,
      );
    },
  );
}
