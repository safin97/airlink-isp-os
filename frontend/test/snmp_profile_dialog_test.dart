import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/snmp_profile_dialog.dart';

void main() {
  testWidgets('v2c saves community only and v3 fields switch cleanly', (
    tester,
  ) async {
    Map<String, dynamic>? saved;
    final api = Api(
      client: MockClient((request) async {
        saved = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response('{"id":"profile","version":"2c"}', 201);
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showDialog<bool>(
                context: context,
                builder: (_) => SnmpProfileDialog(api: api),
              ),
              child: const Text('Open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('name')), 'Radio');
    await tester.enterText(
      find.byKey(const ValueKey('community')),
      'private-lab',
    );
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('SNMP v3').last);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('community')), findsNothing);
    expect(find.byKey(const ValueKey('auth_key')), findsOneWidget);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('SNMP v2c').last);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('auth_key')), findsNothing);
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved, {
      'name': 'Radio',
      'version': '2c',
      'community': 'private-lab',
    });
    expect(find.byType(SnmpProfileDialog), findsNothing);
  });
}
