import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/system_terminal.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:xterm/xterm.dart';

void main() {
  test('terminal bounds application-driven resize', () {
    final terminal = SystemShellTerminal();
    terminal.write('\x1b[8;999999;999999t');
    expect(terminal.viewWidth, lessThanOrEqualTo(300));
    expect(terminal.viewHeight, lessThanOrEqualTo(120));
  });

  testWidgets('terminal hidden for managers', (tester) async {
    final api = Api()..user = {'role': 'manager'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SystemTerminalButton(api: api)),
      ),
    );
    expect(find.text('System terminal'), findsNothing);
  });

  testWidgets('preview explains availability without offering a shell', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'supported': false,
            'reason': 'Available on installed AirLink Linux only.',
          }),
          200,
        ),
      ),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SystemTerminalButton(api: api)),
      ),
    );
    await tester.tap(find.text('System terminal'));
    await tester.pumpAndSettle();
    expect(
      find.text('Available on installed AirLink Linux only.'),
      findsOneWidget,
    );
    expect(find.text('Open terminal'), findsNothing);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
  });

  testWidgets(
    'owner authenticates, sends interactive input, and closes shell',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final exchanges = <Map<String, dynamic>>[];
      var closed = false;
      var opened = false;
      final api = Api(
        client: MockClient((request) async {
          final path = request.url.path;
          if (path.endsWith('/open')) {
            final body = jsonDecode(request.body);
            expect(body['password'], 'Owner-Password-Example!');
            opened = true;
            return http.Response(jsonEncode({'session_id': 'a' * 48}), 201);
          }
          if (path.endsWith('/exchange')) {
            exchanges.add(Map<String, dynamic>.from(jsonDecode(request.body)));
            return http.Response(
              jsonEncode({
                'output': 'AirLink root / # ',
                'cursor': 16,
                'closed': false,
              }),
              200,
            );
          }
          if (path.endsWith('/close')) {
            closed = true;
            return http.Response('{"closed":true}', 200);
          }
          return http.Response('{"supported":true}', 200);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: SystemTerminalButton(api: api)),
        ),
      );
      await tester.tap(find.text('System terminal'));
      await tester.pumpAndSettle();
      expect(opened, isFalse);
      await tester.enterText(find.byType(TextField), 'Owner-Password-Example!');
      await tester.tap(find.text('Open terminal'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(opened, isTrue);
      final view = tester.widget<TerminalView>(find.byType(TerminalView));
      view.terminal.textInput('pwd\r');
      await tester.pump(const Duration(milliseconds: 250));
      expect(exchanges.any((e) => e['data'] == 'pwd\r'), isTrue);
      await tester.tap(find.text('Ctrl+C'));
      await tester.pump(const Duration(milliseconds: 250));
      expect(exchanges.any((e) => e['data'] == '\x03'), isTrue);
      await tester.tap(find.text('Close terminal'));
      await tester.pumpAndSettle();
      expect(closed, isTrue);
      expect(find.byType(TerminalView), findsNothing);
    },
  );
}
