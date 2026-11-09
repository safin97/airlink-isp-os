import 'package:flutter/material.dart';

/// Responsive presentation of device-reported readings. Missing values stay
/// unavailable; the dashboard never fills gaps with sample telemetry.
class OnlineDeviceDashboard extends StatelessWidget {
  final Map<String, dynamic> data, row;
  final bool busy, stale, showDetails;
  final bool showSubscription;
  final VoidCallback? onRefresh, onClose;
  final VoidCallback onSettings;
  final Widget details;
  final String? error, message;

  const OnlineDeviceDashboard({
    super.key,
    required this.data,
    required this.row,
    required this.busy,
    required this.stale,
    required this.showDetails,
    required this.onRefresh,
    required this.onClose,
    required this.onSettings,
    required this.details,
    this.showSubscription = true,
    this.error,
    this.message,
  });

  List<Map> records(String key) =>
      (data[key] as List? ?? []).whereType<Map>().toList();

  Map? firstGroup(String name) =>
      ((data['groups'] as Map? ?? {})[name] as List? ?? [])
          .whereType<Map>()
          .firstOrNull;

  String text(dynamic value) =>
      value == null || '$value'.isEmpty ? 'Unavailable' : '$value';

  num? number(dynamic value) {
    if (value is num) return value;
    return num.tryParse(
      RegExp(r'-?\d+(?:\.\d+)?').firstMatch('$value')?.group(0) ?? '',
    );
  }

  String rate(dynamic value) {
    final amount = number(value);
    return amount == null
        ? 'Unavailable'
        : '${amount.toStringAsFixed(amount == amount.roundToDouble() ? 0 : 1)} Mbps';
  }

  String traffic(dynamic value) {
    final bps = number(value);
    return bps == null || bps < 0
        ? 'Unavailable'
        : '${(bps / 1000000).toStringAsFixed(1)} Mbps';
  }

  @override
  Widget build(BuildContext context) {
    const blue = Color(0xff087bf5);
    const green = Color(0xff08a84e);
    const canvas = Color(0xfff5f8fc);
    const border = Color(0xffd9e1ec);

    final radios = records('wireless');
    final radio = radios.length == 1 ? radios.single : <dynamic, dynamic>{};
    final ports = records('ethernet');
    final ether =
        ports.where((p) => p['name'] == 'ether1').firstOrNull ??
        ports.where((p) => p['name'] == 'eth0').firstOrNull ??
        (ports.length == 1 ? ports.single : <dynamic, dynamic>{});
    final peers = records('registrations')
        .where((p) => radio['name'] == null || p['interface'] == radio['name'])
        .toList();
    final peer = peers.length == 1 ? peers.single : <dynamic, dynamic>{};
    final pppoe = records('pppoe').firstOrNull;
    final identity = firstGroup('Identity');
    final system = firstGroup('System');
    final family = '${data['detected_vendor'] ?? data['vendor']}'.toLowerCase();
    final isUbiquiti = family.contains('ubiquiti');
    final vendor = isUbiquiti ? 'Ubiquiti' : 'MikroTik';
    final name =
        identity?['name'] ??
        system?['device_model'] ??
        system?['board-name'] ??
        data['device_type'] ??
        data['vendor'] ??
        row['username'];
    final signal = number(radio['signal_dbm']);
    final speed = number(ether['speed_mbps']);
    final tx = radio['tx_rate_mbps'] ?? peer['tx-rate'] ?? peer['tx_rate_mbps'];
    final rx = radio['rx_rate_mbps'] ?? peer['rx-rate'] ?? peer['rx_rate_mbps'];
    final fullDuplex = ether['full_duplex'];
    final duplex = fullDuplex == true || fullDuplex == 'true'
        ? 'Full duplex'
        : fullDuplex == false || fullDuplex == 'false'
        ? 'Half duplex'
        : null;
    final quality = signal == null
        ? null
        : signal >= -60
        ? 'Excellent'
        : signal >= -70
        ? 'Good'
        : signal >= -80
        ? 'Fair'
        : 'Weak';
    final accountStatus = '${row['status'] ?? pppoe?['status'] ?? ''}'
        .split(' •')
        .first;

    final theme = ThemeData.light(useMaterial3: true).copyWith(
      scaffoldBackgroundColor: canvas,
      colorScheme: ColorScheme.fromSeed(
        seedColor: blue,
        brightness: Brightness.light,
      ),
      cardTheme: const CardThemeData(color: Colors.white),
    );

    return Theme(
      data: theme,
      child: Dialog(
        insetPadding: const EdgeInsets.all(12),
        backgroundColor: canvas,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1040),
          child: SizedBox(
            width: MediaQuery.sizeOf(context).width,
            height: MediaQuery.sizeOf(context).height - 24,
            child: Column(
              children: [
                _Header(
                  stale: stale,
                  onClose: onClose,
                  onRefresh: onRefresh,
                  onSettings: onSettings,
                  showDetails: showDetails,
                ),
                if (busy) const LinearProgressIndicator(minHeight: 3),
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 28),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (error != null)
                          _Notice(error!, const Color(0xffb42318)),
                        if (stale)
                          const _Notice(
                            'Showing the previous readings.',
                            Color(0xff9a6700),
                          ),
                        if (message != null) _Notice(message!, blue),
                        _DeviceCard(
                          name: '$name',
                          ip: '${row['ip_address']}',
                          vendor: vendor,
                          icon: isUbiquiti
                              ? Icons.router_outlined
                              : Icons.cell_tower_outlined,
                        ),
                        const SizedBox(height: 12),
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final wide = constraints.maxWidth >= 720;
                            final width = wide
                                ? (constraints.maxWidth - 12) / 2
                                : constraints.maxWidth;
                            return Wrap(
                              spacing: 12,
                              runSpacing: 12,
                              children: [
                                SizedBox(
                                  width: width,
                                  child: _InfoCard(
                                    title: 'Wireless (Radio)',
                                    icon: Icons.wifi,
                                    color: blue,
                                    headline: signal == null
                                        ? 'Unavailable'
                                        : '${signal.toStringAsFixed(0)} dBm',
                                    badge: quality,
                                    rows: [
                                      _Reading(
                                        Icons.wifi_tethering,
                                        'SSID',
                                        text(radio['ssid']),
                                      ),
                                      _Reading(
                                        Icons.swap_vert,
                                        'Wireless TX / RX',
                                        '${rate(tx)} / ${rate(rx)}',
                                      ),
                                    ],
                                  ),
                                ),
                                SizedBox(
                                  width: width,
                                  child: _InfoCard(
                                    title: 'Ethernet (LAN)',
                                    icon: Icons.settings_ethernet,
                                    color: const Color(0xff145dcc),
                                    headline: speed == null
                                        ? 'Unavailable'
                                        : speed >= 1000
                                        ? '${(speed / 1000).toStringAsFixed(speed % 1000 == 0 ? 0 : 1)} Gbps'
                                        : '${speed.toStringAsFixed(0)} Mbps',
                                    badge: duplex,
                                    rows: [
                                      _Reading(
                                        Icons.arrow_downward,
                                        'Download',
                                        traffic(ether['rx_bps']),
                                        color: blue,
                                      ),
                                      _Reading(
                                        Icons.arrow_upward,
                                        'Upload',
                                        traffic(ether['tx_bps']),
                                        color: green,
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            );
                          },
                        ),
                        const SizedBox(height: 12),
                        if (showSubscription)
                          _AccountCard(
                            username: text(
                              pppoe?['username'] ?? row['username'],
                            ),
                            status: accountStatus.isEmpty
                                ? 'Unavailable'
                                : accountStatus,
                            expiry: text(row['expiration']),
                            source: pppoe == null
                                ? 'ISP Card / RADIUS'
                                : 'Device PPPoE',
                          ),
                        if (showSubscription && data['pppoe_note'] != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                              '${data['pppoe_note']}',
                              style: const TextStyle(
                                color: Color(0xff65758b),
                                fontSize: 12,
                              ),
                            ),
                          ),
                        if (showDetails) ...[
                          const SizedBox(height: 16),
                          Card(
                            margin: EdgeInsets.zero,
                            clipBehavior: Clip.antiAlias,
                            shape: RoundedRectangleBorder(
                              side: const BorderSide(color: border),
                              borderRadius: BorderRadius.circular(18),
                            ),
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: details,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  final bool stale, showDetails;
  final VoidCallback? onClose, onRefresh;
  final VoidCallback onSettings;
  const _Header({
    required this.stale,
    required this.onClose,
    required this.onRefresh,
    required this.onSettings,
    required this.showDetails,
  });

  @override
  Widget build(BuildContext context) => Container(
    color: Colors.white,
    padding: const EdgeInsets.fromLTRB(10, 10, 10, 12),
    child: SafeArea(
      bottom: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) => Row(
              children: [
                IconButton(
                  onPressed: onClose,
                  tooltip: 'Close',
                  icon: const Icon(Icons.arrow_back_ios_new),
                ),
                if (constraints.maxWidth >= 390)
                  Image.asset(
                    'assets/branding/airlink-horizontal.png',
                    width: 128,
                    height: 38,
                    fit: BoxFit.contain,
                  )
                else
                  const Text(
                    'AirLink',
                    style: TextStyle(
                      color: Color(0xff081b42),
                      fontSize: 21,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                const Spacer(),
                IconButton(
                  onPressed: onRefresh,
                  tooltip: 'Refresh',
                  icon: const Icon(Icons.refresh),
                ),
                IconButton(
                  onPressed: onSettings,
                  tooltip: 'Device settings and details',
                  isSelected: showDetails,
                  icon: const Icon(Icons.tune),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Device overview',
                        style: TextStyle(
                          color: Color(0xff081b42),
                          fontSize: 24,
                          fontWeight: FontWeight.w800,
                          height: 1,
                        ),
                      ),
                      SizedBox(height: 5),
                      Text(
                        'Live readings from the connected device.',
                        style: TextStyle(color: Color(0xff65758b)),
                      ),
                    ],
                  ),
                ),
                _StatusPill(
                  stale ? 'Previous readings' : 'Online',
                  stale ? const Color(0xffd97706) : const Color(0xff08a84e),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _DeviceCard extends StatelessWidget {
  final String name, ip, vendor;
  final IconData icon;
  const _DeviceCard({
    required this.name,
    required this.ip,
    required this.vendor,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) => _Shell(
    child: Row(
      children: [
        _IconTile(icon: icon),
        const SizedBox(width: 14),
        Container(width: 1, height: 58, color: const Color(0xffd9e1ec)),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                vendor,
                style: const TextStyle(color: Color(0xff65758b), fontSize: 12),
              ),
              Text(
                name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Color(0xff081b42),
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
              Text('IP: $ip', style: const TextStyle(color: Color(0xff46566d))),
            ],
          ),
        ),
      ],
    ),
  );
}

class _InfoCard extends StatelessWidget {
  final String title, headline;
  final String? badge;
  final IconData icon;
  final Color color;
  final List<_Reading> rows;
  const _InfoCard({
    required this.title,
    required this.icon,
    required this.color,
    required this.headline,
    required this.rows,
    this.badge,
  });

  @override
  Widget build(BuildContext context) => _Shell(
    child: LayoutBuilder(
      builder: (context, constraints) {
        final content = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(
                color: Color(0xff081b42),
                fontWeight: FontWeight.w800,
                fontSize: 17,
              ),
            ),
            const SizedBox(height: 3),
            Wrap(
              spacing: 10,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  headline,
                  style: const TextStyle(
                    color: Color(0xff081b42),
                    fontSize: 25,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (badge != null && badge != 'Unavailable')
                  _StatusPill(badge!, const Color(0xff08a84e), compact: true),
              ],
            ),
            const SizedBox(height: 9),
            for (final row in rows) row,
          ],
        );
        if (constraints.maxWidth < 300) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IconTile(icon: icon, color: color),
              const SizedBox(height: 10),
              content,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _IconTile(icon: icon, color: color),
            const SizedBox(width: 14),
            Expanded(child: content),
          ],
        );
      },
    ),
  );
}

class _AccountCard extends StatelessWidget {
  final String username, status, expiry, source;
  const _AccountCard({
    required this.username,
    required this.status,
    required this.expiry,
    required this.source,
  });

  @override
  Widget build(BuildContext context) => _Shell(
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _IconTile(icon: Icons.person_outline),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'PPPoE Subscription',
                style: TextStyle(
                  color: Color(0xff081b42),
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 24,
                runSpacing: 10,
                children: [
                  _Value(label: 'Username', value: username),
                  _Value(label: 'Status', value: status, good: true),
                  _Value(label: 'Expiry', value: expiry),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                'Source: $source',
                style: const TextStyle(color: Color(0xff46566d), fontSize: 12),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _Value extends StatelessWidget {
  final String label, value;
  final bool good;
  const _Value({required this.label, required this.value, this.good = false});
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: const TextStyle(color: Color(0xff65758b), fontSize: 11),
      ),
      const SizedBox(height: 2),
      good && value.toLowerCase().contains('active')
          ? _StatusPill(value, const Color(0xff08a84e), compact: true)
          : Text(
              value,
              style: const TextStyle(
                color: Color(0xff081b42),
                fontWeight: FontWeight.w700,
              ),
            ),
    ],
  );
}

class _Reading extends StatelessWidget {
  final IconData icon;
  final String label, value;
  final Color? color;
  const _Reading(this.icon, this.label, this.value, {this.color});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 5),
    child: Row(
      children: [
        Icon(icon, size: 16, color: color ?? const Color(0xff46566d)),
        const SizedBox(width: 7),
        Text('$label: ', style: const TextStyle(color: Color(0xff46566d))),
        Expanded(
          child: Text(
            value,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: Color(0xff081b42),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ],
    ),
  );
}

class _Shell extends StatelessWidget {
  final Widget child;
  const _Shell({required this.child});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      border: Border.all(color: const Color(0xffd9e1ec)),
      boxShadow: const [
        BoxShadow(
          color: Color(0x0a081b42),
          blurRadius: 12,
          offset: Offset(0, 4),
        ),
      ],
    ),
    child: child,
  );
}

class _IconTile extends StatelessWidget {
  final IconData icon;
  final Color color;
  const _IconTile({required this.icon, this.color = const Color(0xff081b42)});
  @override
  Widget build(BuildContext context) => Container(
    width: 58,
    height: 58,
    decoration: BoxDecoration(
      color: const Color(0xffeaf4ff),
      borderRadius: BorderRadius.circular(14),
    ),
    child: Icon(icon, color: color, size: 31),
  );
}

class _StatusPill extends StatelessWidget {
  final String text;
  final Color color;
  final bool compact;
  const _StatusPill(this.text, this.color, {this.compact = false});
  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.symmetric(
      horizontal: compact ? 9 : 12,
      vertical: compact ? 4 : 7,
    ),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .12),
      borderRadius: BorderRadius.circular(24),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (!compact) ...[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
        ],
        Text(
          text,
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w800,
            fontSize: compact ? 12 : 13,
          ),
        ),
      ],
    ),
  );
}

class _Notice extends StatelessWidget {
  final String text;
  final Color color;
  const _Notice(this.text, this.color);
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .08),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Text(text, style: TextStyle(color: color)),
  );
}
