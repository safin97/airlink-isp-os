import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

/// Displays server-directed waits without retrying Telegram actions automatically.
mixin TelegramCooldown<T extends StatefulWidget> on State<T> {
  Timer? _cooldownTimer;
  int cooldownSeconds = 0;
  bool cooldownNotice = false;
  bool get coolingDown => cooldownSeconds > 0;

  void acceptCooldown(dynamic seconds) {
    if (seconds is! int || seconds <= 0) return;
    _cooldownTimer?.cancel();
    setState(() {
      cooldownSeconds = seconds;
      cooldownNotice = true;
    });
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(
        () => cooldownSeconds = (seconds - timer.tick).clamp(0, seconds),
      );
      if (!coolingDown) timer.cancel();
    });
  }

  bool acceptCooldownError(Object error) {
    if (error is! ApiException ||
        error.status != 429 ||
        error.retryAfterSeconds == null) {
      return false;
    }
    acceptCooldown(error.retryAfterSeconds);
    return true;
  }

  Widget get cooldownMessage {
    final seconds = cooldownSeconds;
    final duration =
        '${seconds ~/ 3600}h ${(seconds % 3600) ~/ 60}m ${seconds % 60}s';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Text(
        coolingDown
            ? 'Telegram actions are paused. Try again in $duration. AirLink will not retry automatically.'
            : 'The cooldown has ended. You can try again now.',
      ),
    );
  }

  @override
  void dispose() {
    _cooldownTimer?.cancel();
    super.dispose();
  }
}
