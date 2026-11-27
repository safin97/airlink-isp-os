import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ssh_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('SSH settings are hidden from managers', (tester) async {
    final api = Api()..user = {'role': 'manager'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SshSettings(api: api)),
      ),
    );
    expect(find.text('SSH remote access'), findsNothing);
  });

  testWidgets('owner configures port 2742 and disables SSH', (tester) async {
    tester.view.physicalSize = const Size(1440, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var enabled = false;
    final writes = <Map<String, dynamic>>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          writes.add(Map<String, dynamic>.from(jsonDecode(request.body)));
          enabled = request.url.path.endsWith('/enable');
        }
        return http.Response(
          jsonEncode({
            'supported': true,
            'server_installed': true,
            'enabled': enabled,
            'active': enabled,
            'sources': <String>[],
            'client_ip': '192.168.1.12',
            'port': 2742,
            'username': 'airlink-admin',
            'install': {'status': 'idle'},
          }),
          200,
        );
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: SshSettings(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final fields = find.byType(TextField);
    expect(
      tester.widget<TextField>(fields.at(0)).controller!.text,
      '192.168.1.12',
    );
    expect(find.textContaining('Port: 2742'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.text('SSH password for airlink-admin'), findsNothing);
    await tester.enterText(fields.at(1), 'Owner-Password-Example!');
    await tester.tap(find.text('Enable SSH on port 2742'));
    await tester.pumpAndSettle();
    expect(writes.single, {
      'sources': ['192.168.1.12'],
      'owner_password': 'Owner-Password-Example!',
    });
    expect(find.text('SSH is running'), findsOneWidget);
    expect(tester.widget<TextField>(fields.at(1)).controller!.text, isEmpty);
    await tester.enterText(fields.at(1), 'Owner-Password-Example!');
    await tester.tap(find.text('Disable SSH'));
    await tester.pumpAndSettle();
    expect(writes.last.keys, ['owner_password']);
    expect(find.text('SSH is disabled'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('missing component offers installation without enabling SSH', (
    tester,
  ) async {
    var installRequested = false;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          expect(request.url.path, '/api/system/ssh/install');
          expect(jsonDecode(request.body), {
            'owner_password': 'Owner-Password-Example!',
          });
          installRequested = true;
        }
        return http.Response(
          jsonEncode({
            'supported': true,
            'server_installed': false,
            'enabled': false,
            'install': {'status': installRequested ? 'queued' : 'idle'},
          }),
          request.method == 'POST' ? 202 : 200,
        );
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: SshSettings(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Owner-Password-Example!');
    await tester.ensureVisible(find.text('Install SSH component'));
    await tester.tap(find.text('Install SSH component'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(installRequested, isTrue);
    expect(find.text('Installing SSH component…'), findsOneWidget);
    expect(find.text('Enable SSH on port 2742'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
