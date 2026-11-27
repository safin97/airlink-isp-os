import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ethernet_ports_dialog.dart';

void main() {
  for (final succeeds in [true, false]) {
    testWidgets(
      'Unused ports are excluded and resolving a down port (success: $succeeds)',
      (tester) async {
        tester.view.physicalSize = const Size(1800, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var resolved = false;
        var changed = 0;
        final writes = <Map<String, dynamic>>[];
        final api = Api(
          client: MockClient((request) async {
            if (request.method == 'POST') {
              expect(request.url.path, '/api/devices/1/ethernet-ports/resolve');
              writes.add(jsonDecode(request.body));
              if (!succeeds) {
                return http.Response('{"detail":"Refresh this outage"}', 409);
              }
              resolved = true;
              return http.Response('{}', 200);
            }
            return http.Response(
              jsonEncode({
                'supported': true,
                'source': 'API',
                'connection_status': 'connected',
                'ports': [
                  {
                    'name': 'ether1',
                    'state': 'disconnected',
                    'usage_status': 'unused',
                    'can_resolve': false,
                  },
                  {
                    'name': 'ether2',
                    'state': 'disconnected',
                    'usage_status': resolved ? 'resolved' : 'down',
                    'can_resolve': !resolved,
                    'down_since': '2026-11-28T00:00:00+00:00',
                  },
                  {
                    'name': 'ether3',
                    'state': 'connected',
                    'usage_status': 'running',
                  },
                ],
              }),
              200,
            );
          }),
        );
        await tester.pumpWidget(
          MaterialApp(
            home: EthernetPortsDialog(
              api: api,
              device: const {'id': '1', 'name': 'Switch'},
              onChanged: () async {
                changed++;
              },
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Unused'), findsOneWidget);
        expect(
          find.text('3 ports · 1 running · 1 down · 0 unknown · 1 unused'),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey('resolve-ethernet-ether1')),
          findsNothing,
        );
        final button = find.byKey(const ValueKey('resolve-ethernet-ether2'));
        await tester.ensureVisible(button);
        await tester.tap(button);
        await tester.pumpAndSettle();
        expect(writes, [
          {'port': 'ether2', 'down_since': '2026-11-28T00:00:00+00:00'},
        ]);
        expect(changed, succeeds ? 1 : 0);
        if (succeeds) {
          expect(find.text('Resolved'), findsOneWidget);
          expect(
            find.text(
              '3 ports · 1 running · 0 down · 0 unknown · 1 unused · 1 resolved',
            ),
            findsOneWidget,
          );
          expect(button, findsNothing);
        } else {
          expect(find.textContaining('Refresh this outage'), findsOneWidget);
          expect(button, findsOneWidget);
        }
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets('Moving a cable updates Running and Down on the next refresh', (
    tester,
  ) async {
    var moved = false;
    final api = Api(
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'supported': true,
            'source': 'API',
            'connection_status': 'connected',
            'ports': [
              {'name': 'ether1', 'state': moved ? 'disconnected' : 'connected'},
              {'name': 'ether2', 'state': moved ? 'connected' : 'disconnected'},
            ],
          }),
          200,
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: EthernetPortsDialog(
          api: api,
          device: const {'id': '1', 'name': 'Switch'},
        ),
      ),
    );
    await tester.pumpAndSettle();
    void expectStates(String first, String second) {
      final rows = tester.widget<DataTable>(find.byType(DataTable)).rows;
      expect((rows[0].cells[0].child as Text).data, 'ether1');
      expect((rows[1].cells[0].child as Text).data, 'ether2');
      expect(
        ((rows[0].cells[1].child as Row).children.last as Text).data,
        first,
      );
      expect(
        ((rows[1].cells[1].child as Row).children.last as Text).data,
        second,
      );
    }

    expectStates('Running', 'Down');
    moved = true;
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expectStates('Down', 'Running');
    expect(
      find.text('2 ports · 1 running · 1 down · 0 unknown'),
      findsOneWidget,
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('Select a displayed port, persist it and restore Automatic', (
    tester,
  ) async {
    String? stored = 'ether2';
    var changed = 0;
    var holdRefresh = false;
    Completer<http.Response>? pendingRefresh;
    http.Response? oldResponse;
    final requests = <Map<String, dynamic>>[];
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          final body = Map<String, dynamic>.from(jsonDecode(request.body));
          requests.add(body);
          stored = body['port'];
          return http.Response(
            jsonEncode({'ethernet_speed_port': stored}),
            200,
          );
        }
        final response = http.Response(
          jsonEncode({
            'supported': false,
            'speed_port': stored,
            'speed_port_choices': ['ether1', 'ether2', 'sfp1'],
            'can_select_speed_port': true,
            'ports': [],
          }),
          200,
        );
        if (holdRefresh) {
          holdRefresh = false;
          oldResponse = response;
          pendingRefresh = Completer<http.Response>();
          return pendingRefresh!.future;
        }
        return response;
      }),
    );
    Future<void> open() async {
      await tester.pumpWidget(
        MaterialApp(
          home: EthernetPortsDialog(
            api: api,
            device: const {'id': '1', 'name': 'Radio'},
            onChanged: () async {
              changed++;
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    await open();
    expect(
      tester
          .widget<DropdownButton<String>>(
            find.byKey(const ValueKey('ethernet-speed-port')),
          )
          .value,
      'ether2',
    );
    await tester.tap(find.byKey(const ValueKey('ethernet-speed-port')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('sfp1').last);
    await tester.pumpAndSettle();
    // The timer must not replace an unsaved choice with the server's old value.
    holdRefresh = true;
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<DropdownButton<String>>(
            find.byKey(const ValueKey('ethernet-speed-port')),
          )
          .value,
      'sfp1',
    );
    await tester.tap(find.text('Save displayed port'));
    await tester.pumpAndSettle();
    expect(requests, [
      {'port': 'sfp1'},
    ]);
    expect(changed, 1);
    expect(find.text('Displayed port saved.'), findsOneWidget);
    pendingRefresh!.complete(oldResponse!);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<DropdownButton<String>>(
            find.byKey(const ValueKey('ethernet-speed-port')),
          )
          .value,
      'sfp1',
    );
    await tester.pumpWidget(const SizedBox());
    await open();
    expect(
      tester
          .widget<DropdownButton<String>>(
            find.byKey(const ValueKey('ethernet-speed-port')),
          )
          .value,
      'sfp1',
    );
    await tester.tap(find.byKey(const ValueKey('ethernet-speed-port')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Automatic (available port)').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save displayed port'));
    await tester.pumpAndSettle();
    expect(requests.last, {'port': null});
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('Read-only viewers cannot choose the displayed port', (
    tester,
  ) async {
    final api = Api(
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'supported': false,
            'speed_port': 'ether2',
            'speed_port_choices': ['ether2'],
            'can_select_speed_port': false,
            'ports': [],
          }),
          200,
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: EthernetPortsDialog(
          api: api,
          device: const {'id': '1', 'name': 'Radio'},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('ethernet-speed-port')), findsNothing);
    expect(find.text('Save displayed port'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'Auto refresh replaces readings with unknown and clears them on failure',
    (tester) async {
      var calls = 0;
      final api = Api(
        client: MockClient((request) async {
          calls++;
          if (calls > 2) {
            return http.Response('{"detail":"Access denied"}', 403);
          }
          return http.Response(
            jsonEncode({
              'supported': true,
              'snmp_status': calls == 1 ? 'connected' : 'stale',
              'poll_interval': 60,
              'ports': [
                {
                  'name': 'ether1',
                  'state': calls == 1 ? 'connected' : 'unknown',
                  'rx_bps': calls == 1 ? 1000000 : null,
                },
              ],
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: EthernetPortsDialog(
            api: api,
            device: const {'id': '1', 'name': 'Switch'},
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('1.000 Mbps'), findsOneWidget);
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('Unknown'), findsOneWidget);
      expect(find.text('1.000 Mbps'), findsNothing);
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('ether1'), findsNothing);
      expect(find.textContaining('Access denied'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );
}
