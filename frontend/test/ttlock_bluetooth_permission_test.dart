import 'dart:async';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/ttlock.dart';
import 'package:airlink_isp_os/ttlock_bluetooth.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:permission_handler/permission_handler.dart';

class PermissionBluetooth extends TTLockBluetooth {
  bool native = true;
  TTLockBluetoothPermission access = TTLockBluetoothPermission.needed;
  int requests = 0, settings = 0;
  Completer<TTLockBluetoothPermission>? pending;
  @override
  bool get available => native;
  @override
  Future<TTLockBluetoothPermission> permissionStatus() async =>
      native ? access : TTLockBluetoothPermission.unsupported;
  @override
  Future<TTLockBluetoothPermission> requestPermission() async {
    requests++;
    return pending == null ? access : await pending!.future;
  }

  @override
  Future<bool> openSettings() async {
    settings++;
    return true;
  }
}

class NativeBluetooth extends TTLockBluetooth {
  @override
  bool get available => true;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  Future<void> show(WidgetTester tester, PermissionBluetooth bluetooth) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = Api(
      client: MockClient((r) async {
        expect(r.method, 'GET');
        return http.Response(
          r.url.path.endsWith('/application')
              ? '{"configured":true,"region":"eu","client_id":"test"}'
              : '{"configured":false}',
          200,
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TTLockPage(api: api, bluetooth: bluetooth),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'TTLock entry offers permission, Not now leaves login available, rapid taps request once',
    (tester) async {
      final bluetooth = PermissionBluetooth();
      await show(tester, bluetooth);
      expect(find.text('Allow Bluetooth for TTLock?'), findsOneWidget);
      expect(bluetooth.requests, 0);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      expect(find.text('TTLock login'), findsOneWidget);
      await tester.drag(find.byType(ListView).first, const Offset(0, -1000));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).first, const Offset(0, 1000));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsNothing);
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Allow Bluetooth'),
      );
      bluetooth.pending = Completer<TTLockBluetoothPermission>();
      button.onPressed!();
      button.onPressed!();
      await tester.pump();
      expect(bluetooth.requests, 1);
      bluetooth.pending!.complete(TTLockBluetoothPermission.granted);
      await tester.pumpAndSettle();
      expect(find.text('Bluetooth permission allowed'), findsOneWidget);
      expect(
        find.textContaining('does not mean a lock is connected'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Allow in entry dialog requests OS permission and handles denial',
    (tester) async {
      final bluetooth = PermissionBluetooth();
      await show(tester, bluetooth);
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Allow Bluetooth'),
        ),
      );
      await tester.pumpAndSettle();
      expect(bluetooth.requests, 1);
      expect(find.text('Bluetooth permission allowed'), findsNothing);
      expect(
        find.widgetWithText(FilledButton, 'Allow Bluetooth'),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'blocked permission opens settings and refreshes when returning',
    (tester) async {
      final bluetooth = PermissionBluetooth()
        ..access = TTLockBluetoothPermission.settings;
      await show(tester, bluetooth);
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Open app settings'),
        ),
      );
      await tester.pumpAndSettle();
      expect(bluetooth.settings, 1);
      expect(bluetooth.requests, 0);
      bluetooth.access = TTLockBluetoothPermission.granted;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Bluetooth permission allowed'), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);
    },
  );

  testWidgets('already allowed does not prompt again', (tester) async {
    final bluetooth = PermissionBluetooth()
      ..access = TTLockBluetoothPermission.granted;
    await show(tester, bluetooth);
    expect(find.byType(AlertDialog), findsNothing);
    expect(bluetooth.requests, 0);
    expect(find.text('Bluetooth permission allowed'), findsOneWidget);
  });

  testWidgets(
    'browser shows phone bridge setup without requesting OS permission',
    (tester) async {
      final bluetooth = PermissionBluetooth()..native = false;
      await show(tester, bluetooth);
      expect(find.byType(AlertDialog), findsNothing);
      await tester.tap(find.text('Bluetooth setup'));
      await tester.pumpAndSettle();
      expect(find.text('Connect Bluetooth through your phone'), findsOneWidget);
      expect(
        find.textContaining('Share Bluetooth with website'),
        findsOneWidget,
      );
      expect(bluetooth.requests, 0);
      expect(bluetooth.settings, 0);
      expect(tester.takeException(), isNull);
    },
  );

  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    test(
      'real permission handler mapping for $platform requires every permission',
      () async {
        debugDefaultTargetPlatformOverride = platform;
        const channel = MethodChannel(
          'flutter.baseflow.com/permissions/methods',
        );
        final permissions = platform == TargetPlatform.android
            ? [
                Permission.bluetoothScan.value,
                Permission.bluetoothConnect.value,
                Permission.locationWhenInUse.value,
              ]
            : [Permission.bluetooth.value];
        var status = PermissionStatus.denied.index;
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, (call) async {
              if (call.method == 'checkPermissionStatus') {
                expect(permissions, contains(call.arguments));
                return status;
              }
              expect(call.method, 'requestPermissions');
              expect(call.arguments, permissions);
              return {for (final p in permissions) p: status};
            });
        addTearDown(() {
          debugDefaultTargetPlatformOverride = null;
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
              .setMockMethodCallHandler(channel, null);
        });
        final bluetooth = NativeBluetooth();
        expect(
          await bluetooth.permissionStatus(),
          TTLockBluetoothPermission.needed,
        );
        status = PermissionStatus.permanentlyDenied.index;
        expect(
          await bluetooth.requestPermission(),
          TTLockBluetoothPermission.settings,
        );
        status = PermissionStatus.restricted.index;
        expect(
          await bluetooth.permissionStatus(),
          TTLockBluetoothPermission.restricted,
        );
        status = PermissionStatus.granted.index;
        expect(
          await bluetooth.requestPermission(),
          TTLockBluetoothPermission.granted,
        );
      },
    );
  }
}
