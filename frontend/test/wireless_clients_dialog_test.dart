import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/wireless_clients_dialog.dart';

void main() {
  testWidgets('client status updates preserve row order and last readings', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1600, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final rows = [
      for (final mac in ['AA:BB:CC:DD:EE:01', 'AA:BB:CC:DD:EE:02'])
        <String, dynamic>{
          'mac_address': mac,
          'ssid': 'North',
          'signal_dbm': -65,
          'status': 'up',
          'last_status': 'up',
          'last_seen': '2026-11-27T12:00:00Z',
          'status_since': '2026-11-27T12:00:00Z',
        },
    ];
    var fail = false;
    final api = Api(
      client: MockClient(
        (r) async => http.Response(
          jsonEncode({'status': 'available', 'clients': rows, 'total': 2}),
          fail ? 503 : 200,
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: WirelessClientsDialog(
            api: api,
            device: {'id': 'ap', 'name': 'AP'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    List<Key?> keys() => tester
        .widget<DataTable>(find.byType(DataTable))
        .rows
        .map((r) => r.key)
        .toList();
    final original = keys();
    expect(find.text('Up'), findsNWidgets(2));
    rows[0]['status'] = 'down';
    rows[0]['last_status'] = 'down';
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(keys(), original);
    expect(find.text('Down'), findsOneWidget);
    expect(find.text('-65 dBm'), findsNWidgets(2));
    expect(
      tester
          .widget<DataTable>(find.byType(DataTable))
          .rows
          .first
          .color
          ?.resolve({}),
      isNotNull,
    );
    rows[0]['status'] = 'up';
    rows[1]['status'] = 'unknown';
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(keys(), original);
    expect(find.text('Unknown'), findsOneWidget);
    expect(find.text('Up'), findsOneWidget);
    expect(
      tester.widget<DataTable>(find.byType(DataTable)).rows.first.color,
      isNull,
    );
    fail = true;
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(keys(), original);
    expect(find.text('Unknown'), findsNWidgets(2));
    await tester.pumpWidget(const SizedBox());
  });
}
