import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';
import 'package:airlink_isp_os/network_map.dart';

class TestTiles extends TileProvider {
  @override
  ImageProvider getImage(
    TileCoordinates coordinates,
    TileLayer options,
  ) => MemoryImage(
    base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    ),
  );
}

void main() {
  testWidgets('defaults to Zakho without inventing tower coordinates', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: NetworkMap(
            towers: [
              {'id': 'missing', 'name': 'No GPS'},
            ],
            expanded: true,
            toggleExpanded: () {},
            openDevices: (_) {},
            tileProvider: TestTiles(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final map = tester.widget<FlutterMap>(find.byType(FlutterMap));
    expect(
      map.mapController!.camera.center.latitude,
      closeTo(zakhoCenter.latitude, .001),
    );
    expect(
      map.mapController!.camera.center.longitude,
      closeTo(zakhoCenter.longitude, .001),
    );
    expect(
      tester.widget<MarkerLayer>(find.byType(MarkerLayer)).markers,
      isEmpty,
    );
    expect(find.text('1 without GPS'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('shows and fits every saved tower; marker opens its devices', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? opened;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: NetworkMap(
            towers: [
              {
                'id': 'a',
                'name': 'North',
                'latitude': 37.3,
                'longitude': 42.8,
                'status': 'online',
              },
              {
                'id': 'b',
                'name': 'South',
                'latitude': 37.0,
                'longitude': 42.5,
                'status': 'offline',
              },
              {'id': 'c', 'name': 'No GPS'},
            ],
            expanded: true,
            toggleExpanded: () {},
            openDevices: (id) => opened = id,
            tileProvider: TestTiles(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final map = tester.widget<FlutterMap>(find.byType(FlutterMap));
    expect(
      tester.widget<MarkerLayer>(find.byType(MarkerLayer)).markers.length,
      2,
    );
    expect(
      map.mapController!.camera.visibleBounds.contains(
        const LatLng(37.3, 42.8),
      ),
      isTrue,
    );
    expect(
      map.mapController!.camera.visibleBounds.contains(
        const LatLng(37.0, 42.5),
      ),
      isTrue,
    );
    await tester.tap(find.text('North'));
    expect(opened, 'a');
    await tester.tap(find.text('Zakho'));
    await tester.pumpAndSettle();
    expect(
      map.mapController!.camera.center.latitude,
      closeTo(zakhoCenter.latitude, .001),
    );
    await tester.tap(find.text('Fit all towers'));
    await tester.pumpAndSettle();
    expect(
      map.mapController!.camera.visibleBounds.contains(
        const LatLng(37.0, 42.5),
      ),
      isTrue,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
