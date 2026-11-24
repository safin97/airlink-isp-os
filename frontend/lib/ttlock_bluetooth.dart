import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:ttlock_flutter/ttlock.dart';
import 'mobile_platform.dart';

enum TTLockBluetoothPermission {
  unsupported,
  needed,
  granted,
  settings,
  restricted,
}

class TTLockBluetooth {
  bool get available => isMobileDevice;
  static bool _active = false;
  bool _scanning = false;

  List<Permission> get _permissions =>
      defaultTargetPlatform == TargetPlatform.android
      ? [
          Permission.bluetoothScan,
          Permission.bluetoothConnect,
          Permission.locationWhenInUse,
        ]
      : [Permission.bluetooth];

  TTLockBluetoothPermission _access(Iterable<PermissionStatus> values) {
    if (values.any((s) => s.isRestricted)) {
      return TTLockBluetoothPermission.restricted;
    }
    if (values.any((s) => s.isPermanentlyDenied)) {
      return TTLockBluetoothPermission.settings;
    }
    return values.isNotEmpty && values.every((s) => s.isGranted)
        ? TTLockBluetoothPermission.granted
        : TTLockBluetoothPermission.needed;
  }

  Future<TTLockBluetoothPermission> permissionStatus() async {
    if (!available) return TTLockBluetoothPermission.unsupported;
    return _access(await Future.wait(_permissions.map((p) => p.status)));
  }

  Future<TTLockBluetoothPermission> requestPermission() async {
    if (!available) return TTLockBluetoothPermission.unsupported;
    final result = await _permissions.request();
    return _access(
      _permissions.map((p) => result[p] ?? PermissionStatus.denied),
    );
  }

  Future<bool> openSettings() => openAppSettings();

  Future<void> ready() async {
    if (!available) {
      throw Exception(
        'Bluetooth requires the AirLink Android or iPhone app near the lock.',
      );
    }
    if (await requestPermission() != TTLockBluetoothPermission.granted) {
      throw Exception(
        'Allow Bluetooth / Nearby devices in phone Settings. Android also needs location permission for lock discovery.',
      );
    }
    TTLock.printLog = false;
    final state = Completer<TTBluetoothState>();
    TTLock.getBluetoothState((value) {
      if (!state.isCompleted) state.complete(value);
    });
    if (await state.future.timeout(const Duration(seconds: 8)) !=
        TTBluetoothState.turnOn) {
      throw Exception('Turn on Bluetooth before using the lock.');
    }
  }

  Future<void> scan(void Function(Map<String, dynamic>) found) async {
    await ready();
    if (_active) throw Exception('Wait for the current Bluetooth operation.');
    _scanning = true;
    TTLock.startScanLock((lock) {
      if (_scanning) {
        found({
          'lockName': lock.lockName,
          'lockMac': lock.lockMac,
          'lockVersion': lock.lockVersion,
          'isInited': lock.isInited,
          'rssi': lock.rssi,
        });
      }
    });
  }

  void stopScan() {
    if (!_scanning) return;
    _scanning = false;
    TTLock.stopScanLock();
  }

  Future<Map<String, dynamic>> execute(
    String action,
    Map<String, dynamic> data,
    void Function(String) progress,
  ) async {
    await ready();
    if (_active) throw Exception('Wait for the current Bluetooth operation.');
    stopScan();
    _active = true;
    final result = Completer<Map<String, dynamic>>();
    void done([Map<String, dynamic> value = const {}]) {
      _active = false;
      if (!result.isCompleted) result.complete(value);
    }

    void fail(TTLockError code, String message) {
      _active = false;
      if (!result.isCompleted) {
        result.completeError(
          Exception(
            'Bluetooth operation failed (${code.name}). Move near the lock and check its state before trying again.',
          ),
        );
      }
    }

    final lockData = data['lock_data'] as String? ?? '';
    var timedOut = false;
    try {
      switch (action) {
        case 'passcode_add':
          TTLock.createCustomPasscode(
            data['passcode'],
            data['start'],
            data['end'],
            lockData,
            done,
            fail,
          );
        case 'passcode_delete':
          TTLock.deletePasscode(data['card_number'], lockData, done, fail);
        case 'passcode_period':
          TTLock.modifyPasscode(
            data['card_number'],
            null,
            data['start'],
            data['end'],
            lockData,
            done,
            fail,
          );
        case 'fingerprint_add':
          TTLock.addFingerprint(
            null,
            data['start'],
            data['end'],
            lockData,
            (count, total) => progress(
              'Touch the lock’s fingerprint sensor: $count of $total scans.',
            ),
            (number) => done({'fingerprint_number': number}),
            fail,
          );
        case 'fingerprint_delete':
          TTLock.deleteFingerprint(data['card_number'], lockData, done, fail);
        case 'fingerprint_period':
          TTLock.modifyFingerprintValidityPeriod(
            data['card_number'],
            null,
            data['start'],
            data['end'],
            lockData,
            done,
            fail,
          );
        case 'card_add':
          TTLock.addCard(
            null,
            data['start'],
            data['end'],
            lockData,
            () => progress('Present the access card to the lock reader now.'),
            (number) => done({'card_number': number}),
            fail,
          );
        case 'card_delete':
          TTLock.deleteCard(data['card_number'], lockData, done, fail);
        case 'card_period':
          TTLock.modifyCardValidityPeriod(
            data['card_number'],
            null,
            data['start'],
            data['end'],
            lockData,
            done,
            fail,
          );
        case 'lock_init':
          TTLock.initLock(
            Map<String, dynamic>.from(data['scan']),
            (value) => done({'lock_data': value}),
            fail,
          );
        case 'lock_reset':
          TTLock.resetLock(lockData, done, fail);
        case 'lock':
        case 'unlock':
          TTLock.controlLock(
            lockData,
            action == 'lock' ? TTControlAction.lock : TTControlAction.unlock,
            (time, battery, id, value) =>
                done({'battery': battery, 'time': time}),
            fail,
          );
        case 'status':
          TTLock.getLockSwitchState(
            lockData,
            (state) => done({'state': state.name}),
            fail,
          );
        case 'battery':
          TTLock.getLockPower(
            lockData,
            (value) => done({'battery': value}),
            fail,
          );
        case 'time':
          TTLock.setLockTime(
            DateTime.now().millisecondsSinceEpoch,
            lockData,
            done,
            fail,
          );
        case 'records':
          TTLock.getLockOperateRecord(
            TTOperateRecordType.total,
            lockData,
            (value) => done({'records': value}),
            fail,
          );
        case 'auto_lock':
          TTLock.setLockAutomaticLockingPeriodicTime(
            data['seconds'],
            lockData,
            done,
            fail,
          );
        default:
          throw Exception('Unsupported Bluetooth operation.');
      }
      return await result.future.timeout(
        const Duration(seconds: 90),
        onTimeout: () {
          timedOut = true;
          // Do not allow another command while an SDK command may still be active.
          throw Exception(
            'Bluetooth result is unknown. Check the physical lock. Wait for the SDK to finish or restart the app before another operation.',
          );
        },
      );
    } catch (e) {
      if (!timedOut) _active = false;
      rethrow;
    }
  }
}
