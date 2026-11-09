import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ethernet_ports_dialog.dart';

void main() {
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
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(find.text('Unknown'), findsOneWidget);
      expect(find.text('1.000 Mbps'), findsNothing);
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(find.text('ether1'), findsNothing);
      expect(find.textContaining('Access denied'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      expect(tester.takeException(), isNull);
    },
  );
}
