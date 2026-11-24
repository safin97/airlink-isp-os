import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'ttlock_bluetooth.dart';
import 'ttlock_style.dart';

class TTLockBluetoothPermissionCard extends StatefulWidget {
  final TTLockBluetooth bluetooth;
  const TTLockBluetoothPermissionCard({super.key, required this.bluetooth});

  @override
  State<TTLockBluetoothPermissionCard> createState() =>
      _BluetoothPermissionState();
}

class _BluetoothPermissionState extends State<TTLockBluetoothPermissionCard>
    with
        WidgetsBindingObserver,
        AutomaticKeepAliveClientMixin<TTLockBluetoothPermissionCard> {
  TTLockBluetoothPermission? access;
  bool busy = false;
  String? error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (!widget.bluetooth.available) {
      access = TTLockBluetoothPermission.unsupported;
    }
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => refresh(prompt: true));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) refresh();
  }

  Future<void> refresh({bool prompt = false}) async {
    if (!mounted || busy) return;
    setState(() => busy = true);
    try {
      final value = await widget.bluetooth.permissionStatus();
      if (!mounted) return;
      setState(() {
        access = value;
        error = null;
      });
    } catch (_) {
      if (mounted) {
        setState(
          () => error = 'Could not check Bluetooth permission. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
    if (mounted &&
        prompt &&
        widget.bluetooth.available &&
        access != null &&
        access != TTLockBluetoothPermission.granted &&
        access != TTLockBluetoothPermission.unsupported &&
        ModalRoute.of(context)?.isCurrent != false) {
      final allow = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          scrollable: true,
          icon: const Icon(LucideIcons.bluetooth, color: ttBlue, size: 32),
          title: const Text('Allow Bluetooth for TTLock?'),
          content: Text(description),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Not now'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(actionLabel),
            ),
          ],
        ),
      );
      if (allow == true && mounted) await allowAccess();
    }
  }

  bool get needsSettings =>
      access == TTLockBluetoothPermission.settings ||
      access == TTLockBluetoothPermission.restricted;
  String get actionLabel =>
      needsSettings ? 'Open app settings' : 'Allow Bluetooth';
  String get description => switch (access) {
    TTLockBluetoothPermission.granted =>
      'Permission is allowed. Turn on Bluetooth and stay near the lock. Permission alone does not mean a lock is connected.',
    TTLockBluetoothPermission.settings =>
      'Bluetooth access was blocked. Open the AirLink app settings and allow Bluetooth / Nearby devices and any requested location access.',
    TTLockBluetoothPermission.restricted =>
      'Bluetooth access is restricted by this device. Check its app settings or ask the device administrator to allow access.',
    TTLockBluetoothPermission.unsupported =>
      'Nearby locks connect through the AirLink Android or iPhone app. Use phone Bluetooth on a lock to connect from this website.',
    _ =>
      'Allow AirLink to discover and manage nearby TTLock locks. Android also requests location access for lock discovery. You can continue without Bluetooth.',
  };

  Future<void> allowAccess() async {
    if (!mounted || busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (needsSettings) {
        if (!await widget.bluetooth.openSettings() && mounted) {
          setState(
            () => error =
                'Open your phone Settings → AirLink to allow Bluetooth access.',
          );
        }
        if (mounted) {
          final value = await widget.bluetooth.permissionStatus();
          if (mounted) setState(() => access = value);
        }
      } else {
        final value = await widget.bluetooth.requestPermission();
        if (mounted) {
          setState(() {
            access = value;
            if (value == TTLockBluetoothPermission.needed) {
              error =
                  'Bluetooth permission was not allowed. Retry or continue without Bluetooth.';
            }
          });
        }
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Could not request Bluetooth permission. Check your phone settings and try again.',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> browserHelp() => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      scrollable: true,
      title: const Text('Connect Bluetooth through your phone'),
      content: const Text(
        'This website uses the AirLink phone app for TTLock Bluetooth.\n\n1. Open TTLock in the AirLink Android or iPhone app and allow Bluetooth.\n\n2. Sign in to the same AirLink owner and TTLock accounts. Open Share Bluetooth with website and start sharing near the lock.\n\n3. Here, choose Use phone Bluetooth on your lock, select the phone and approve requests on it.\n\nKeep the phone app open. No lock is paired or unlocked by allowing permission.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Got it'),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final native = widget.bluetooth.available;
    final granted = access == TTLockBluetoothPermission.granted;
    return TTPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(LucideIcons.bluetooth, color: granted ? ttGreen : ttBlue),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  granted ? 'Bluetooth permission allowed' : 'Bluetooth access',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(description, style: TextStyle(color: ttMuted(context))),
          if (error != null) ...[
            const SizedBox(height: 8),
            Text(error!, style: const TextStyle(color: ttRed)),
          ],
          const SizedBox(height: 12),
          if (busy) const LinearProgressIndicator(),
          if (!busy)
            native
                ? granted
                      ? TextButton.icon(
                          onPressed: refresh,
                          icon: const Icon(LucideIcons.refreshCw, size: 16),
                          label: const Text('Check permission'),
                        )
                      : FilledButton.icon(
                          onPressed: allowAccess,
                          icon: const Icon(LucideIcons.bluetooth, size: 16),
                          label: Text(actionLabel),
                        )
                : OutlinedButton.icon(
                    onPressed: browserHelp,
                    icon: const Icon(LucideIcons.smartphone, size: 16),
                    label: const Text('Bluetooth setup'),
                  ),
        ],
      ),
    );
  }
}
