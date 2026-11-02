import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets('Create a place and add a tower inside it', (tester) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final places = <Map<String, dynamic>>[];
    final towers = <Map<String, dynamic>>[];
    final api = Api(
      client: MockClient((request) async {
        Object result = [];
        if (request.url.path == '/api/dashboard') result = <String, dynamic>{};
        if (request.url.path == '/api/places') {
          if (request.method == 'POST') {
            final body = jsonDecode(request.body);
            places.add({'id': 'zakho', 'name': body['name'], 'tower_count': 0});
            result = places.last;
          } else {
            result = places;
          }
        }
        if (request.url.path == '/api/towers') {
          if (request.method == 'POST') {
            final body = Map<String, dynamic>.from(jsonDecode(request.body));
            expect(body['place_id'], 'zakho');
            towers.add({...body, 'id': 'north', 'status': 'unknown'});
            places[0]['tower_count'] = 1;
            result = towers.last;
          } else {
            result = towers;
          }
        }
        return http.Response(
          jsonEncode(result),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    )..user = {'username': 'owner', 'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ListTile, 'Towers'));
    await tester.pumpAndSettle();
    expect(find.text('Add tower'), findsNothing);
    await tester.tap(find.text('Add place'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Place name'),
      'Zakho',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Back to places'), findsOneWidget);
    expect(find.text('Zakho'), findsOneWidget);
    await tester.tap(find.text('Add tower'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Tower name'),
      'North',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('North'), findsOneWidget);
    await tester.tap(find.text('North'));
    await tester.pumpAndSettle();
    expect(find.text('Devices at North'), findsOneWidget);
    await tester.tap(find.text('Back to Towers'));
    await tester.pumpAndSettle();
    expect(find.text('Back to places'), findsOneWidget);
    await tester.tap(find.text('Back to places'));
    await tester.pumpAndSettle();
    expect(find.text('Zakho'), findsOneWidget);
    expect(find.text('North'), findsNothing);
    expect(find.text('Add tower'), findsNothing);
    await tester.tap(find.text('Zakho'));
    await tester.pumpAndSettle();
    expect(find.text('North'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
