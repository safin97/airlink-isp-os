import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets('My account shows one selected page and keeps SAS4 separate', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final writes = <http.Request>[];
    final reads = <String>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          writes.add(request);
          return http.Response('{"ok":true}', 200);
        }
        reads.add(request.url.path);
        return http.Response(
          jsonEncode(
            request.url.path == '/api/dashboard'
                ? {}
                : request.url.path == '/api/integrations/sas4'
                ? {'username': '', 'configured': false}
                : request.url.path == '/api/integrations/sas4/device-access'
                ? {'enabled': true, 'try_public_snmp': true}
                : [],
          ),
          200,
        );
      }),
    )..user = {'username': 'my-manager', 'role': 'manager'};
    await tester.pumpWidget(
      MaterialApp(
        home: Operations(api: api, logout: () async {}),
      ),
    );
    await tester.pumpAndSettle();

    Finder navigationItem(String label) => find.widgetWithText(ListTile, label);
    Future<void> openPage(String label) async {
      await tester.ensureVisible(navigationItem(label));
      await tester.tap(navigationItem(label));
      await tester.pumpAndSettle();
    }

    void expectSelected(String label) {
      expect(tester.widget<ListTile>(navigationItem(label)).selected, isTrue);
    }

    reads.clear();
    await openPage('My account');
    expect(find.byType(Dialog), findsNothing);
    expectSelected('My account');
    expectSelected('Account profile');
    expect(find.text('Role: manager'), findsOneWidget);
    expect(find.byType(TextFormField), findsNothing);
    expect(find.text('Automatic detection'), findsNothing);
    expect(find.text('FIB client ID'), findsNothing);
    expect(find.text('SAS4 manager username'), findsNothing);
    expect(reads, isEmpty);

    await openPage('Change password');
    expectSelected('Change password');
    expect(find.text('Role: manager'), findsNothing);
    expect(find.text('Automatic detection'), findsNothing);
    expect(find.text('FIB client ID'), findsNothing);
    expect(find.byType(TextFormField), findsNWidgets(3));
    await tester.enterText(
      find.byType(TextFormField).at(0),
      'Current-Password-573!',
    );
    await tester.enterText(
      find.byType(TextFormField).at(1),
      'New-Password-For-Account-492!',
    );
    await tester.enterText(
      find.byType(TextFormField).at(2),
      'New-Password-For-Account-492!',
    );
    await tester.ensureVisible(
      find.widgetWithText(FilledButton, 'Change password'),
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Change password'));
    await tester.pumpAndSettle();
    expect(writes.single.url.path, '/api/auth/password');
    expect(jsonDecode(writes.single.body), {
      'current_password': 'Current-Password-573!',
      'new_password': 'New-Password-For-Account-492!',
      'confirm_password': 'New-Password-For-Account-492!',
    });
    expect(
      find.text('Password changed. Your other sessions have been signed out.'),
      findsOneWidget,
    );
    expect(
      tester
          .widget<TextFormField>(find.byType(TextFormField).first)
          .controller!
          .text,
      isEmpty,
    );

    await openPage('Customer device access');
    expectSelected('Customer device access');
    expect(find.text('Automatic detection'), findsOneWidget);
    expect(find.text('Read-only SNMP community'), findsOneWidget);
    expect(find.text('Current password'), findsNothing);
    expect(find.text('Role: manager'), findsNothing);
    expect(find.text('FIB client ID'), findsNothing);
    expect(find.byType(ExpansionTile), findsNothing);

    await openPage('Payment setup');
    expectSelected('Payment setup');
    expect(find.text('FIB client ID'), findsOneWidget);
    expect(find.text('FastPay store ID'), findsOneWidget);
    expect(find.text('Automatic detection'), findsNothing);
    expect(find.text('Current password'), findsNothing);
    expect(find.text('Role: manager'), findsNothing);
    expect(find.byType(ExpansionTile), findsNothing);
    expect(reads, [
      '/api/integrations/sas4/device-access',
      '/api/payments/gateways',
    ]);

    await openPage('Towers');
    expect(find.text('Current password'), findsNothing);
    expect(
      tester.widget<ListTile>(navigationItem('My account')).selected,
      isFalse,
    );
    expect(navigationItem('Account profile'), findsNothing);
    await openPage('My account');
    expect(find.byType(Dialog), findsNothing);
    expectSelected('Account profile');
    expect(find.text('Role: manager'), findsOneWidget);
    expect(find.byType(TextFormField), findsNothing);
    await openPage('Change password');
    expect(
      tester
          .widget<TextFormField>(find.byType(TextFormField).first)
          .controller!
          .text,
      isEmpty,
    );
    await openPage('Account profile');
    expectSelected('Account profile');

    await openPage('SAS4 connection');
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('SAS4 manager username'), findsOneWidget);
    expect(find.text('SAS4 manager password'), findsOneWidget);
    expect(find.text('Save SAS4 connection'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.text('Current password'),
      ),
      findsNothing,
    );
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();
    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Current password'), findsNothing);
    expect(find.text('Role: manager'), findsOneWidget);
    expectSelected('My account');
    expectSelected('Account profile');
    expect(writes, hasLength(1));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
