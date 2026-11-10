import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/tower_device_panel.dart';
import 'package:airlink_isp_os/app_theme.dart';
import 'tower_device_panel_test.dart' show fixture;

void main() {
  for (final layout in [
    (390.0, Brightness.light),
    (1440.0, Brightness.light),
    (390.0, Brightness.dark),
    (1440.0, Brightness.dark),
  ]) {
    final (width, brightness) = layout;
    testWidgets(
      'Device workspace navigation and filters at width $width $brightness',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final key = GlobalKey();
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
        final data = fixture();
        data['groups'] = {
          'System': [
            {
              'board-name': 'CRS328-24P-4S+',
              'version': '7.16.2',
              'uptime': '12d 8h 42m',
              'cpu-load': '8',
            },
          ],
        };
        await tester.pumpWidget(
          MaterialApp(
            theme: airLinkTheme(brightness),
            home: RepaintBoundary(
              key: key,
              child: TowerDevicePanel(
                data: data,
                busy: false,
                stale: false,
                canEdit: false,
                onRefresh: () async {},
                onSave: (_) async {
                  fail('Read-only');
                },
                onClose: () {},
                onChangeLogin: () {},
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Port overview'), findsOneWidget);
        expect(tester.takeException(), isNull);
        if (Platform.environment['AIRLINK_PANEL_SCREENSHOTS'] == '1') {
          await tester.runAsync(() async {
            final image =
                await (key.currentContext!.findRenderObject()
                        as RenderRepaintBoundary)
                    .toImage();
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await File(
              '/tmp/airlink-device-overview-${width.toInt()}-${brightness.name}.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.tap(find.byKey(const ValueKey('device-tab-1')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Inactive'));
        await tester.tap(find.text('Inactive'));
        await tester.pumpAndSettle();
        expect(find.text('Ethernet ports (1)'), findsOneWidget);
        expect(find.text('ether2'), findsOneWidget);
        await tester.enterText(
          find.widgetWithText(TextFormField, 'Search ports'),
          'ether9',
        );
        await tester.pumpAndSettle();
        expect(find.text('No results'), findsOneWidget);
        await tester.ensureVisible(find.byKey(const ValueKey('device-tab-2')));
        await tester.tap(find.byKey(const ValueKey('device-tab-2')));
        await tester.pumpAndSettle();
        expect(find.text('AirLink'), findsOneWidget);
        expect(find.text('Registered clients (0)'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.ensureVisible(find.byKey(const ValueKey('device-tab-3')));
        await tester.tap(find.byKey(const ValueKey('device-tab-3')));
        await tester.pumpAndSettle();
        expect(find.text('Device identity settings (1)'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
