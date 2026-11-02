import 'dart:async';
import 'package:flutter/material.dart';

class DashboardClock extends StatefulWidget {
  final bool compact;
  const DashboardClock({super.key, this.compact = false});

  @override
  State<DashboardClock> createState() => _DashboardClockState();
}

class _DashboardClockState extends State<DashboardClock> {
  DateTime current = DateTime.now();
  Timer? timer;

  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => current = DateTime.now());
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    String two(int value) => value.toString().padLeft(2, '0');
    final time =
        '${two(current.hour)}:${two(current.minute)}:${two(current.second)}';
    final date = MaterialLocalizations.of(context).formatMediumDate(current);
    return Tooltip(
      message: '$date · ${current.timeZoneName} · Local time',
      child: Column(
        crossAxisAlignment: widget.compact
            ? CrossAxisAlignment.start
            : CrossAxisAlignment.end,
        children: [
          Text(
            time,
            textDirection: TextDirection.ltr,
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: widget.compact ? 14 : 18,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (!widget.compact)
            Text(date, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
