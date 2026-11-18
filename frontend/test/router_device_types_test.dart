import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_clients.dart';
import 'package:airlink_isp_os/customer_device_access.dart';

void main() {
  testWidgets(
    'online users show all new device brands without invented telemetry',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(1600, 1100));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final labels = ['Tenda', 'TP-Link', 'Ruijie / Reyee', 'Hikvision'];
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path == '/api/integrations/sas4') {
            return http.Response('{"configured":true}', 200);
          }
          return http.Response(
            jsonEncode({
              'clients': [
                for (var i = 0; i < labels.length; i++)
                  {
                    'username': 'customer-$i',
                    'online': true,
                    'ip_address': '10.0.0.${i + 1}',
                    'vendor_label': labels[i],
                    'telemetry_status': 'identity_only',
                    'ethernet_links': [],
                    'vendor_detection_source': 'Public device page',
                  },
              ],
              'total': 4,
              'page': 1,
              'last_page': 1,
              'collection_status': 'available',
              'fetched_at': '2026-11-18T00:00:00Z',
            }),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Sas4Clients(api: api, showDashboard: false, showOnline: true),
          ),
        ),
      );
      await tester.pumpAndSettle();
      for (final label in labels) {
        expect(find.text(label), findsOneWidget);
      }
      expect(find.textContaining('dBm'), findsNothing);
      expect(
        find.byTooltip(
          'Device brand detected from its public page. Live readings require supported SNMP access; device login is not supported for every brand.',
        ),
        findsWidgets,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('brand-only automatic detection can be saved without credentials', (
    tester,
  ) async {
    Map? saved;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          saved = jsonDecode(request.body);
        }
        return http.Response(
          '{"enabled":true,"api_username":"","has_api_password":false,"has_community":false}',
          200,
        );
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CustomerDeviceAccess(api: api, embedded: true),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Save device login'));
    await tester.tap(find.text('Save device login'));
    await tester.pumpAndSettle();
    expect(saved?['enabled'], isTrue);
    expect(saved?['api_username'], '');
    expect(saved?['api_password'], isNull);
    expect(saved?['try_public_snmp'], isFalse);
    expect(tester.takeException(), isNull);
  });
}
