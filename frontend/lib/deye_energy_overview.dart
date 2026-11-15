import 'dart:math' as math;
import 'package:flutter/material.dart';

/// Station measurements only: missing values are never treated as zero.
class DeyeEnergyOverview extends StatelessWidget {
  const DeyeEnergyOverview({
    super.key,
    required this.reading,
    this.compact = false,
  });
  final Map<String, dynamic>? reading;
  final bool compact;

  String power(String key) {
    final value = reading?[key];
    if (value is! num || !value.isFinite) return 'Unavailable';
    return value.abs() >= 1000
        ? '${(value / 1000).toStringAsFixed(2)} kW'
        : '${value.toStringAsFixed(0)} W';
  }

  num? measure(String key) =>
      reading?[key] is num && (reading![key] as num).isFinite
      ? reading![key] as num
      : null;

  String get gridState {
    final availability = reading?['grid_availability'];
    final state = availability is Map ? availability['state'] : null;
    return state == 'up' || state == 'down' ? state as String : 'unknown';
  }

  int direction(String inbound, String outbound) {
    final a = measure(inbound), b = measure(outbound);
    if (a != null && a > 0 && b == 0) return 1;
    if (b != null && b > 0 && a == 0) return -1;
    return 0;
  }

  String get batteryMode {
    final charge = measure('charge_w'), discharge = measure('discharge_w');
    if (charge != null && charge > 0 && discharge != null && discharge > 0) {
      return 'Charging and discharging';
    }
    if (charge != null && charge > 0) return 'Charging · ${power('charge_w')}';
    if (discharge != null && discharge > 0) {
      return 'Discharging · ${power('discharge_w')}';
    }
    if (charge == 0 && discharge == 0) return 'Idle';
    return 'Charge/discharge unavailable';
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final rawSoc = reading?['battery_soc'];
    final soc = rawSoc is num && rawSoc.isFinite && rawSoc >= 0 && rawSoc <= 100
        ? rawSoc.toDouble()
        : null;
    final solar = dark ? const Color(0xffffc568) : const Color(0xffa55d00);
    final battery = dark ? const Color(0xff6ce0b5) : const Color(0xff087955);
    final grid = gridState == 'up'
        ? (dark ? const Color(0xff83bcff) : const Color(0xff2165af))
        : Theme.of(context).colorScheme.onSurfaceVariant;
    final load = dark ? const Color(0xffc7afff) : const Color(0xff7943b4);
    if (compact) {
      final recent = reading?['freshness'] == 'recent';
      return _CompactEnergyBridge(
        gridState: gridState,
        directions: recent
            ? [
                (measure('solar_w') ?? 0) > 0 ? 1 : 0,
                direction('discharge_w', 'charge_w'),
                gridState == 'up' ? direction('import_w', 'export_w') : 0,
                (measure('load_w') ?? 0) > 0 ? -1 : 0,
              ]
            : [0, 0, 0, 0],
        colors: [solar, battery, grid, load],
        nodes: [
          _BridgeNode(
            title: 'Solar panels',
            icon: Icons.solar_power_outlined,
            color: solar,
            value: power('solar_w'),
          ),
          _BridgeNode(
            title: 'Battery',
            icon: Icons.battery_charging_full,
            color: battery,
            value: soc == null ? 'Unavailable' : '${soc.toStringAsFixed(0)}%',
            charge: soc,
            details: [
              'Power: ${power('battery_w')}',
              recent ? batteryMode : 'Last: $batteryMode',
            ],
          ),
          _BridgeNode(
            title: 'Grid',
            status: _GridMode(reading?['grid_availability']),
            icon: gridState == 'down'
                ? Icons.power_off_outlined
                : Icons.electrical_services_outlined,
            color: grid,
            value: power('grid_w'),
            details: [
              'Import: ${power('import_w')}',
              'Export: ${power('export_w')}',
            ],
          ),
          _BridgeNode(
            title: 'Load',
            icon: Icons.home_outlined,
            color: load,
            value: power('load_w'),
          ),
        ],
      );
    }
    final cards = [
      _EnergyCard(
        title: 'Solar panels',
        subtitle: 'SOLAR PRODUCTION',
        icon: Icons.solar_power_outlined,
        color: solar,
        value: power('solar_w'),
        details: const ['Current generation'],
      ),
      _EnergyCard(
        title: 'Battery',
        subtitle: 'STORED ENERGY',
        icon: Icons.battery_charging_full,
        color: battery,
        value: soc == null ? 'Unavailable' : '${soc.toStringAsFixed(0)}%',
        charge: soc,
        details: [
          batteryMode,
          'Power: ${power('battery_w')}',
          'Charging: ${power('charge_w')}',
          'Discharging: ${power('discharge_w')}',
        ],
      ),
      _EnergyCard(
        title: 'Grid',
        subtitle: 'GRID EXCHANGE',
        status: _GridMode(reading?['grid_availability']),
        icon: gridState == 'down'
            ? Icons.power_off_outlined
            : Icons.electrical_services_outlined,
        color: grid,
        value: power('grid_w'),
        details: [
          'Import: ${power('import_w')}',
          'Export: ${power('export_w')}',
        ],
      ),
      _EnergyCard(
        title: 'Load',
        subtitle: 'SITE CONSUMPTION',
        icon: Icons.home_outlined,
        color: load,
        value: power('load_w'),
        details: const ['Current consumption'],
      ),
    ];
    final overview = LayoutBuilder(
      builder: (context, constraints) {
        // The diagram needs room for readable cards and large accessibility text.
        final diagram =
            !compact &&
            constraints.maxWidth >= 900 &&
            MediaQuery.textScalerOf(context).scale(14) <= 18;
        if (!diagram) {
          final columns = constraints.maxWidth >= 1000
              ? 4
              : constraints.maxWidth >= 560
              ? 2
              : 1;
          final width = (constraints.maxWidth - (columns - 1) * 16) / columns;
          return Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final card in cards) SizedBox(width: width, child: card),
            ],
          );
        }
        final hub = Container(
          width: 180,
          height: 180,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: LinearGradient(
              colors: [
                Color.alphaBlend(
                  battery.withValues(alpha: .16),
                  Theme.of(context).colorScheme.surface,
                ),
                Color.alphaBlend(
                  grid.withValues(alpha: .12),
                  Theme.of(context).colorScheme.surface,
                ),
              ],
            ),
            border: Border.all(color: battery.withValues(alpha: .3)),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.bolt_rounded, color: battery, size: 44),
              const SizedBox(height: 6),
              const Text(
                'Deye inverter',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
              ),
              const SizedBox(height: 4),
              Text(
                'Energy overview',
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        );
        return Stack(
          children: [
            Positioned.fill(
              child: CustomPaint(
                painter: _EnergyLinks(
                  Theme.of(context).colorScheme.outlineVariant,
                  gridState,
                ),
              ),
            ),
            Column(
              children: [
                SizedBox(width: 250, child: cards[0]),
                const SizedBox(height: 36),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    SizedBox(width: 250, child: cards[1]),
                    hub,
                    SizedBox(width: 250, child: cards[2]),
                  ],
                ),
                const SizedBox(height: 36),
                SizedBox(width: 250, child: cards[3]),
              ],
            ),
          ],
        );
      },
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        overview,
        const SizedBox(height: 12),
        _GridAvailability(reading?['grid_availability']),
      ],
    );
  }
}

class _CompactEnergyBridge extends StatefulWidget {
  const _CompactEnergyBridge({
    required this.nodes,
    required this.directions,
    required this.colors,
    required this.gridState,
  });
  final List<Widget> nodes;
  final List<int> directions;
  final List<Color> colors;
  final String gridState;

  @override
  State<_CompactEnergyBridge> createState() => _CompactEnergyBridgeState();
}

class _CompactEnergyBridgeState extends State<_CompactEnergyBridge>
    with SingleTickerProviderStateMixin {
  late final AnimationController animation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 2),
    value: 1,
  );
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    syncMotion();
  }

  @override
  void didUpdateWidget(_CompactEnergyBridge oldWidget) {
    super.didUpdateWidget(oldWidget);
    syncMotion();
  }

  void syncMotion() {
    final moving =
        widget.directions.any((d) => d != 0) &&
        !MediaQuery.disableAnimationsOf(context) &&
        TickerMode.valuesOf(context).enabled;
    if (moving) {
      if (!animation.isAnimating) animation.repeat();
    } else {
      animation.stop();
      animation.value = 1;
    }
  }

  @override
  void dispose() {
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Semantics(
    label: widget.directions.every((direction) => direction == 0)
        ? 'No confirmed energy flow'
        : 'Energy flow: ${[if (widget.directions[0] == 1) 'Solar to inverter', if (widget.directions[1] == 1) 'Battery to inverter', if (widget.directions[1] == -1) 'Inverter to battery', if (widget.directions[2] == 1) 'Grid to inverter', if (widget.directions[2] == -1) 'Inverter to grid', if (widget.directions[3] == -1) 'Inverter to load'].join('; ')}',
    child: LayoutBuilder(
      builder: (context, bounds) {
        final nodes = widget.nodes;
        final vertical =
            bounds.maxWidth < 600 ||
            MediaQuery.textScalerOf(context).scale(14) > 20;
        final scheme = Theme.of(context).colorScheme;
        final hub = Container(
          key: const ValueKey('dashboard-deye-inverter'),
          width: 112,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
          decoration: BoxDecoration(
            color: scheme.surface,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: scheme.primary.withValues(alpha: .4),
              width: 1.5,
            ),
            boxShadow: [
              BoxShadow(
                color: scheme.primary.withValues(alpha: .1),
                blurRadius: 16,
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.developer_board_outlined,
                color: scheme.primary,
                size: 30,
              ),
              const SizedBox(height: 6),
              const Text(
                'Inverter',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
              ),
              Text(
                'DEYE',
                style: TextStyle(
                  color: scheme.onSurfaceVariant,
                  fontSize: 9,
                  letterSpacing: 1.6,
                ),
              ),
            ],
          ),
        );
        Widget pair(Widget a, Widget b) => IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(child: a),
              const SizedBox(width: 16),
              Expanded(child: b),
            ],
          ),
        );
        return Align(
          alignment: Alignment.center,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 860),
            child: Stack(
              children: [
                Positioned.fill(
                  child: AnimatedBuilder(
                    animation: animation,
                    builder: (_, _) => CustomPaint(
                      painter: _BridgeLinks(
                        scheme.outlineVariant,
                        vertical,
                        widget.directions,
                        widget.colors,
                        animation.value,
                        widget.gridState,
                      ),
                    ),
                  ),
                ),
                if (vertical)
                  Column(
                    children: [
                      pair(nodes[0], nodes[2]),
                      const SizedBox(height: 18),
                      hub,
                      const SizedBox(height: 18),
                      pair(nodes[1], nodes[3]),
                    ],
                  )
                else
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          children: [
                            nodes[0],
                            const SizedBox(height: 16),
                            nodes[1],
                          ],
                        ),
                      ),
                      const SizedBox(width: 32),
                      hub,
                      const SizedBox(width: 32),
                      Expanded(
                        child: Column(
                          children: [
                            nodes[2],
                            const SizedBox(height: 16),
                            nodes[3],
                          ],
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        );
      },
    ),
  );
}

class _BridgeNode extends StatelessWidget {
  const _BridgeNode({
    required this.title,
    required this.icon,
    required this.color,
    required this.value,
    this.charge,
    this.status,
    this.details = const [],
  });
  final String title, value;
  final IconData icon;
  final Color color;
  final double? charge;
  final Widget? status;
  final List<String> details;
  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 88),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    decoration: BoxDecoration(
      color: Color.alphaBlend(
        color.withValues(alpha: .07),
        Theme.of(context).colorScheme.surface,
      ),
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: color.withValues(alpha: .25)),
    ),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: color),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          value,
          style: TextStyle(
            color: color,
            fontSize: value == 'Unavailable' ? 15 : 21,
            fontWeight: FontWeight.w700,
          ),
        ),
        if (status != null) ...[const SizedBox(height: 8), status!],
        if (charge != null) ...[
          const SizedBox(height: 6),
          Semantics(
            label: 'Battery charge',
            value: '${charge!.round()} percent',
            child: LinearProgressIndicator(
              value: charge! / 100,
              minHeight: 4,
              color: color,
              backgroundColor: color.withValues(alpha: .12),
              borderRadius: BorderRadius.circular(4),
            ),
          ),
        ],
        for (final detail in details)
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: Text(
              detail,
              style: TextStyle(
                fontSize: 11,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
      ],
    ),
  );
}

class _BridgeLinks extends CustomPainter {
  const _BridgeLinks(
    this.color,
    this.vertical,
    this.directions,
    this.colors,
    this.progress,
    this.gridState,
  );
  final Color color;
  final bool vertical;
  final List<int> directions;
  final List<Color> colors;
  final double progress;
  final String gridState;
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round;
    final x = size.width / 2, y = size.height / 2;
    final paths = <Path>[];
    if (vertical) {
      for (final p in [
        Offset(size.width / 4, 0),
        Offset(size.width / 4, size.height),
        Offset(size.width * 3 / 4, 0),
        Offset(size.width * 3 / 4, size.height),
      ]) {
        final bend = p.dy == 0 ? y - 62 : y + 62;
        paths.add(
          Path()
            ..moveTo(p.dx, p.dy)
            ..lineTo(p.dx, bend)
            ..lineTo(x, bend)
            ..lineTo(x, y),
        );
      }
    } else {
      final top = (size.height - 16) / 4,
          bottom = size.height - (size.height - 16) / 4;
      for (final p in [
        Offset(0, top),
        Offset(0, bottom),
        Offset(size.width, top),
        Offset(size.width, bottom),
      ]) {
        final bend = p.dx == 0 ? x - 72 : x + 72;
        paths.add(
          Path()
            ..moveTo(p.dx, p.dy)
            ..lineTo(bend, p.dy)
            ..lineTo(bend, y)
            ..lineTo(x, y),
        );
      }
    }
    for (var i = 0; i < paths.length; i++) {
      if (i == 2 && gridState != 'up') {
        _drawDashed(canvas, paths[i], paint);
        continue;
      }
      canvas.drawPath(paths[i], paint);
      if (directions[i] == 0) continue;
      final active = Paint()
        ..color = colors[i]
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke;
      final metric = paths[i].computeMetrics().first;
      // Place the direction arrow in the exposed bridge near the inverter.
      final t = metric.getTangentForOffset(
        math.max(0, metric.length - (vertical ? 70 : 80)),
      )!;
      final vector = t.vector * directions[i].toDouble();
      final normal = Offset(-vector.dy, vector.dx);
      canvas.drawPath(
        Path()
          ..moveTo(
            (t.position - vector * 5 + normal * 4).dx,
            (t.position - vector * 5 + normal * 4).dy,
          )
          ..lineTo((t.position + vector * 3).dx, (t.position + vector * 3).dy)
          ..lineTo(
            (t.position - vector * 5 - normal * 4).dx,
            (t.position - vector * 5 - normal * 4).dy,
          ),
        active,
      );
      if (progress < 1) {
        for (var marker = 0; marker < 3; marker++) {
          final phase = (progress + marker / 3) % 1;
          final position = directions[i] > 0 ? phase : 1 - phase;
          final dot = metric
              .getTangentForOffset(metric.length * position)!
              .position;
          canvas.drawCircle(dot, 3, Paint()..color = colors[i]);
        }
      }
    }
  }

  @override
  bool shouldRepaint(_BridgeLinks oldDelegate) =>
      oldDelegate.color != color ||
      oldDelegate.vertical != vertical ||
      oldDelegate.progress != progress ||
      oldDelegate.gridState != gridState ||
      oldDelegate.directions != directions ||
      oldDelegate.colors != colors;
}

class _GridMode extends StatelessWidget {
  const _GridMode(this.data);
  final dynamic data;

  @override
  Widget build(BuildContext context) {
    final values = data is Map ? data as Map : const {};
    final up = values['state'] == 'up', down = values['state'] == 'down';
    final label = up
        ? 'On-grid'
        : down
        ? 'Off-grid'
        : 'Unknown';
    final dark = Theme.of(context).brightness == Brightness.dark;
    final color = up
        ? (dark ? Colors.tealAccent.shade100 : Colors.teal.shade800)
        : down
        ? (dark ? Colors.amber.shade200 : Colors.brown.shade800)
        : Theme.of(context).colorScheme.onSurfaceVariant;
    final explanation = up
        ? 'Grid voltage is present. This estimate does not confirm the inverter’s operating mode or grid relay position.'
        : down
        ? 'Grid voltage is absent. This estimate does not confirm the inverter’s operating mode or grid relay position.'
        : 'The grid connection cannot be determined from the available cloud measurements.';
    return Tooltip(
      message:
          '$explanation\n${values['reason'] ?? 'Grid measurements are unavailable.'}',
      child: Container(
        key: const ValueKey('deye-grid-mode'),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .1),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Wrap(
              spacing: 5,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Icon(
                  up
                      ? Icons.power_outlined
                      : down
                      ? Icons.power_off_outlined
                      : Icons.help_outline,
                  size: 15,
                  color: color,
                ),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
              ],
            ),
            if (up || down)
              Text(
                'Voltage estimate',
                style: TextStyle(fontSize: 10, color: color),
              ),
          ],
        ),
      ),
    );
  }
}

class _GridAvailability extends StatelessWidget {
  const _GridAvailability(this.data);
  final dynamic data;
  String duration(dynamic value) {
    if (value is! num || !value.isFinite || value < 0) return 'Unavailable';
    final seconds = value.floor();
    return '${seconds ~/ 3600}h ${(seconds % 3600) ~/ 60}m ${seconds % 60}s';
  }

  @override
  Widget build(BuildContext context) {
    final values = data is Map ? data as Map : const {};
    final state = values['state'];
    final known = values['started_at'] != null;
    final label = state == 'up'
        ? 'Grid available · voltage estimate'
        : state == 'down'
        ? 'Grid unavailable · voltage estimate'
        : 'Grid status unknown';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                label,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Tooltip(
                message:
                    '${values['reason'] ?? 'Grid voltage is not available from this reading.'}\nEstimates from distinct cloud voltage samples. The dashboard station is monitored while AirLink runs. Gaps, stale readings and state changes are unknown time.',
                child: const Icon(Icons.info_outline, size: 16),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 16,
            runSpacing: 5,
            children: [
              Text(
                'Observed uptime: ${known ? duration(values['uptime_seconds']) : 'Unavailable'}',
                style: const TextStyle(fontSize: 11),
              ),
              Text(
                'Observed downtime: ${known ? duration(values['downtime_seconds']) : 'Unavailable'}',
                style: const TextStyle(fontSize: 11),
              ),
              Text(
                'Unknown time: ${known ? duration(values['unknown_seconds']) : 'Unavailable'}',
                style: const TextStyle(fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 5),
          const Text(
            'Cloud estimates · dashboard station monitored in background',
            style: TextStyle(fontSize: 10),
          ),
        ],
      ),
    );
  }
}

class _EnergyCard extends StatelessWidget {
  const _EnergyCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.color,
    required this.value,
    required this.details,
    this.charge,
    this.status,
  });
  final String title, subtitle, value;
  final IconData icon;
  final Color color;
  final List<String> details;
  final double? charge;
  final Widget? status;

  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 190),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(22),
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          Color.alphaBlend(
            color.withValues(alpha: .09),
            Theme.of(context).colorScheme.surface,
          ),
          Theme.of(context).colorScheme.surface,
        ],
      ),
      border: Border.all(color: color.withValues(alpha: .24)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          children: [
            Container(
              padding: const EdgeInsets.all(9),
              decoration: BoxDecoration(
                color: color.withValues(alpha: .12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: color, size: 23),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Text(
          subtitle,
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w600,
            letterSpacing: 1.1,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          value,
          style: TextStyle(
            fontSize: value == 'Unavailable' ? 23 : 32,
            fontWeight: FontWeight.w700,
            letterSpacing: -.8,
            color: color,
          ),
        ),
        if (status != null) ...[const SizedBox(height: 8), status!],
        if (charge != null) ...[
          const SizedBox(height: 10),
          Semantics(
            label: 'Battery charge',
            value: '${charge!.round()} percent',
            child: LinearProgressIndicator(
              value: charge! / 100,
              minHeight: 7,
              borderRadius: BorderRadius.circular(10),
              color: color,
              backgroundColor: color.withValues(alpha: .12),
            ),
          ),
        ],
        const SizedBox(height: 10),
        for (final detail in details)
          Padding(
            padding: const EdgeInsets.only(top: 3),
            child: Text(
              detail,
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
      ],
    ),
  );
}

class _EnergyLinks extends CustomPainter {
  const _EnergyLinks(this.color, this.gridState);
  final Color color;
  final String gridState;
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    final x = size.width / 2;
    // Neutral connections: direction is reported in the measurement labels.
    final y = size.height / 2;
    canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    canvas.drawLine(Offset(250, y), Offset(x, y), paint);
    final gridLink = Path()
      ..moveTo(x, y)
      ..lineTo(size.width - 250, y);
    if (gridState == 'up') {
      canvas.drawPath(gridLink, paint..style = PaintingStyle.stroke);
    } else {
      _drawDashed(canvas, gridLink, paint..style = PaintingStyle.stroke);
    }
    paint.style = PaintingStyle.fill;
    for (final point in [
      Offset(x, y - 115),
      Offset(x, y + 115),
      Offset(x - 115, y),
      Offset(x + 115, y),
    ]) {
      canvas.drawCircle(point, 4, paint);
    }
  }

  @override
  bool shouldRepaint(_EnergyLinks oldDelegate) =>
      oldDelegate.color != color || oldDelegate.gridState != gridState;
}

void _drawDashed(Canvas canvas, Path path, Paint paint) {
  for (final metric in path.computeMetrics()) {
    for (double offset = 0; offset < metric.length; offset += 12) {
      canvas.drawPath(
        metric.extractPath(offset, math.min(offset + 6, metric.length)),
        paint,
      );
    }
  }
}
