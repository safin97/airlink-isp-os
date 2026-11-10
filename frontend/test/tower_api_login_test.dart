import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/app_theme.dart';
import 'package:airlink_isp_os/online_device_dialog.dart';
import 'package:airlink_isp_os/tower_api_login.dart';

const profile = {
  'id': 'p',
  'name': 'Tower operations',
  'username': 'network-admin',
  'transport': 'routeros_tls',
  'port': 8729,
  'verify_tls': true,
  'enabled': true,
};
const device = {
  'username': 'North tower switch',
  'ip_address': '192.0.2.1',
  'vendor': 'mikrotik_switch',
};

void main() {
  testWidgets(
    'Loading, explicit profile choice, failure and retry use the same saved login',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final profiles = Completer<http.Response>();
      final pending = Completer<http.Response>();
      var requests = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/login-profiles')) {
            return profiles.future;
          }
          expect(request.url.path, '/api/devices/d/login');
          expect(jsonDecode(request.body), {'profile_id': 'p'});
          requests++;
          if (requests == 1) return pending.future;
          return http.Response(
            jsonEncode({'detail': 'Device API connection timed out.'}),
            504,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: OnlineDeviceDialog(api: api, row: device, towerDeviceId: 'd'),
        ),
      );
      await tester.pump();
      expect(find.text('Loading saved logins…'), findsOneWidget);
      expect(find.text('Connecting and reading device details…'), findsNothing);
      profiles.complete(http.Response(jsonEncode([profile]), 200));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Connect'))
            .onPressed,
        isNull,
      );
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tower operations — network-admin').last);
      await tester.pumpAndSettle();
      expect(find.text('MikroTik API-SSL'), findsOneWidget);
      expect(find.text('8729'), findsOneWidget);
      expect(find.text('TLS · certificate verification on'), findsOneWidget);
      expect(requests, 0);
      await tester.tap(find.text('Connect'));
      await tester.pump();
      expect(requests, 1);
      expect(
        find.text('Connecting and reading device details…'),
        findsOneWidget,
      );
      expect(
        tester
            .widget<DropdownButtonFormField<String>>(
              find.byType(DropdownButtonFormField<String>),
            )
            .onChanged,
        isNull,
      );
      pending.complete(
        http.Response(
          jsonEncode({
            'detail':
                'Device login rejected. Check the saved username, password and device permissions.',
          }),
          502,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Login was rejected'), findsOneWidget);
      expect(find.text('Retry connection'), findsOneWidget);
      await tester.tap(find.text('Retry connection'));
      await tester.pumpAndSettle();
      expect(requests, 2);
      expect(find.text('Connection timed out'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Manager with no granted logins has guidance and cannot create or connect',
    (tester) async {
      final api =
          Api(client: MockClient((request) async => http.Response('[]', 200)))
            ..user = {
              'role': 'manager',
              'sections': ['towers'],
              'editable_sections': [],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: OnlineDeviceDialog(api: api, row: device, towerDeviceId: 'd'),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('No saved logins available'), findsOneWidget);
      expect(
        find.text(
          'Ask the owner to share a Towers API login with your account.',
        ),
        findsOneWidget,
      );
      expect(find.text('Add saved login'), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Connect'))
            .onPressed,
        isNull,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Profile reload recovers fetch errors and clears revoked selection',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var reads = 0;
      final api = Api(
        client: MockClient((request) async {
          expect(request.url.path, '/api/devices/d/login-profiles');
          reads++;
          if (reads == 1) {
            return http.Response(
              jsonEncode({'detail': 'Service temporarily unavailable'}),
              503,
            );
          }
          return http.Response(jsonEncode(reads == 2 ? [profile] : []), 200);
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: OnlineDeviceDialog(api: api, row: device, towerDeviceId: 'd'),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Saved logins could not be loaded'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Connect'))
            .onPressed,
        isNull,
      );
      await tester.tap(find.text('Reload logins'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tower operations — network-admin').last);
      await tester.pumpAndSettle();
      expect(find.text('Device username'), findsOneWidget);
      await tester.tap(find.text('Reload logins'));
      await tester.pumpAndSettle();
      expect(find.text('No saved logins available'), findsOneWidget);
      expect(find.text('Device username'), findsNothing);
      expect(find.text('Add saved login'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Connect'))
            .onPressed,
        isNull,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final layout in [(390.0, Brightness.light), (1280.0, Brightness.dark)]) {
    final (width, brightness) = layout;
    testWidgets('Connection card fits $width $brightness', (tester) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final fonts = Platform.environment['AIRLINK_TEST_FONTS'];
      if (fonts != null) {
        await tester.runAsync(() async {
          for (final entry in {
            'sans-serif': 'Roboto-Regular.ttf',
            'MaterialIcons': 'MaterialIcons-Regular.otf',
          }.entries) {
            final loader = FontLoader(entry.key)
              ..addFont(
                File(
                  '$fonts/${entry.value}',
                ).readAsBytes().then(ByteData.sublistView),
              );
            await loader.load();
          }
        });
      }
      final key = GlobalKey();
      await tester.pumpWidget(
        MaterialApp(
          theme: airLinkTheme(brightness),
          home: RepaintBoundary(
            key: key,
            child: Scaffold(
              body: TowerApiLogin(
                device: device,
                profiles: const [profile],
                profileId: 'p',
                busy: false,
                loadingProfiles: false,
                profilesLoaded: true,
                owner: true,
                canEdit: true,
                onSelect: (_) {},
                onConnect: () {},
                onReload: () {},
                onClose: () {},
                onAddProfile: () {},
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Device username'), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (Platform.environment['AIRLINK_PANEL_SCREENSHOTS'] == '1') {
        await tester.runAsync(() async {
          final image =
              await (key.currentContext!.findRenderObject()
                      as RenderRepaintBoundary)
                  .toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File(
            '/tmp/airlink-api-login-${width.toInt()}.png',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
      await tester.pumpWidget(const SizedBox());
    });
  }
}
