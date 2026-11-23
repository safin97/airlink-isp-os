import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'ttlock_style.dart';

class TTLockDashboard extends StatefulWidget {
  final List<Map<String, dynamic>> locks;
  final Map<int, Map<String, dynamic>> states;
  final int total, page, pages;
  final bool busy, loading, native;
  final String account;
  final String? synced;
  final VoidCallback refresh,
      add,
      gateways,
      reconnect,
      disconnect,
      previous,
      next;
  final VoidCallback? share;
  final void Function(Map<String, dynamic>, String) open, operate;
  final void Function(Map<String, dynamic>) check, edit, remove, phone;
  const TTLockDashboard({
    super.key,
    required this.locks,
    required this.states,
    required this.total,
    required this.page,
    required this.pages,
    required this.busy,
    required this.loading,
    required this.native,
    required this.account,
    required this.synced,
    required this.refresh,
    required this.add,
    required this.gateways,
    required this.reconnect,
    required this.disconnect,
    required this.previous,
    required this.next,
    this.share,
    required this.open,
    required this.operate,
    required this.check,
    required this.edit,
    required this.remove,
    required this.phone,
  });
  @override
  State<TTLockDashboard> createState() => _TTLockDashboardState();
}

class _TTLockDashboardState extends State<TTLockDashboard> {
  String query = '', filter = 'All connections';
  bool grid = true;
  bool get disabled => widget.busy || widget.loading;
  String connection(Map<String, dynamic> lock) =>
      widget.states[lock['id']]?['connection'] ?? 'unknown';
  @override
  Widget build(BuildContext context) {
    final visible = widget.locks
        .where(
          (l) =>
              ('${l['name']} ${l['id']}').toLowerCase().contains(
                query.toLowerCase(),
              ) &&
              (filter == 'All connections' ||
                  filter == 'Verified online' && connection(l) == 'online' ||
                  filter == 'Unreachable / check failed' &&
                      connection(l) == 'failed' ||
                  filter == 'Not verified' && connection(l) == 'unknown' ||
                  filter == 'Gateway linked' && l['has_gateway'] == true ||
                  filter == 'Low battery' &&
                      l['battery'] is int &&
                      l['battery'] <= 20),
        )
        .toList();
    final metrics = [
      (
        'Total Smart Locks',
        '${widget.total}',
        'In your TTLock account',
        LucideIcons.lockKeyhole,
        ttBlue,
      ),
      (
        'Online Locks',
        '${widget.locks.where((l) => connection(l) == 'online').length}',
        'Verified on this page',
        LucideIcons.wifi,
        ttGreen,
      ),
      (
        'Offline / Unreachable Locks',
        '${widget.locks.where((l) => connection(l) == 'failed').length}',
        'Failed checks on this page',
        LucideIcons.wifiOff,
        ttRed,
      ),
      (
        'Low Battery Locks',
        '${widget.locks.where((l) => l['battery'] is int && l['battery'] <= 20).length}',
        '20% or lower · this page',
        LucideIcons.batteryLow,
        ttAmber,
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LayoutBuilder(
          builder: (context, c) {
            final columns = c.maxWidth < 310
                ? 1
                : c.maxWidth < 1050
                ? 2
                : 4;
            final compact = c.maxWidth < 560;
            return Wrap(
              spacing: 16,
              runSpacing: 16,
              children: [
                for (final m in metrics)
                  SizedBox(
                    width: (c.maxWidth - 16 * (columns - 1)) / columns,
                    child: TTPanel(
                      padding: EdgeInsets.all(compact ? 16 : 20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: compact
                                    ? Text(
                                        m.$2,
                                        style: const TextStyle(
                                          fontSize: 30,
                                          fontWeight: FontWeight.w700,
                                        ),
                                      )
                                    : Text(
                                        m.$1,
                                        style: TextStyle(
                                          color: ttMuted(context),
                                          fontSize: 13,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                              ),
                              Container(
                                padding: EdgeInsets.all(compact ? 8 : 10),
                                decoration: BoxDecoration(
                                  color: m.$5.withValues(alpha: .09),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: Icon(
                                  m.$4,
                                  color: m.$5,
                                  size: compact ? 18 : 20,
                                ),
                              ),
                            ],
                          ),
                          if (compact) ...[
                            const SizedBox(height: 8),
                            ConstrainedBox(
                              constraints: const BoxConstraints(minHeight: 44),
                              child: Text(
                                m.$1,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  height: 1.4,
                                ),
                              ),
                            ),
                          ] else
                            Text(
                              m.$2,
                              style: const TextStyle(
                                fontSize: 34,
                                fontWeight: FontWeight.w700,
                                letterSpacing: -1,
                              ),
                            ),
                          const SizedBox(height: 4),
                          Text(
                            m.$3,
                            style: TextStyle(
                              color: ttMuted(context),
                              fontSize: compact ? 11 : 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            );
          },
        ),
        const SizedBox(height: 12),
        Text(
          '${widget.locks.where((l) => connection(l) == 'unknown').length} locks on this page have not been checked. Gateway presence does not establish reachability.',
          style: TextStyle(color: ttMuted(context), fontSize: 12),
        ),
        const SizedBox(height: 28),
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 16,
          runSpacing: 16,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Your smart locks',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'One place for every door and every access.',
                  style: TextStyle(color: ttMuted(context)),
                ),
              ],
            ),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: disabled ? null : widget.gateways,
                  icon: const Icon(LucideIcons.router, size: 17),
                  label: const Text('Gateway Management'),
                ),
                FilledButton.icon(
                  onPressed: disabled ? null : widget.add,
                  icon: const Icon(LucideIcons.plus, size: 18),
                  label: const Text('Add Lock'),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 20),
        TTPanel(
          padding: const EdgeInsets.all(14),
          child: LayoutBuilder(
            builder: (context, c) => Wrap(
              spacing: 12,
              runSpacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SizedBox(
                  width: c.maxWidth < 600
                      ? c.maxWidth
                      : ((c.maxWidth - 490).clamp(200, 600)).toDouble(),
                  child: TextField(
                    onChanged: (s) => setState(() => query = s),
                    decoration: const InputDecoration(
                      hintText: 'Search this page by name or ID',
                      prefixIcon: Icon(LucideIcons.search, size: 18),
                    ),
                  ),
                ),
                SizedBox(
                  width: c.maxWidth < 600 ? c.maxWidth : 225,
                  child: DropdownButtonFormField<String>(
                    initialValue: filter,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: 'Connection filter',
                    ),
                    items: [
                      for (final f in [
                        'All connections',
                        'Verified online',
                        'Unreachable / check failed',
                        'Not verified',
                        'Gateway linked',
                        'Low battery',
                      ])
                        DropdownMenuItem(
                          value: f,
                          child: Text(f, style: const TextStyle(fontSize: 13)),
                        ),
                    ],
                    onChanged: (s) => setState(() => filter = s!),
                  ),
                ),
                OutlinedButton.icon(
                  onPressed: disabled ? null : widget.refresh,
                  icon: const Icon(LucideIcons.refreshCw, size: 17),
                  label: const Text('Refresh All'),
                ),
                SegmentedButton<bool>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(
                      value: true,
                      icon: Icon(LucideIcons.layoutGrid, size: 18),
                      tooltip: 'Grid view',
                    ),
                    ButtonSegment(
                      value: false,
                      icon: Icon(LucideIcons.list, size: 18),
                      tooltip: 'List view',
                    ),
                  ],
                  selected: {grid},
                  onSelectionChanged: (s) => setState(() => grid = s.first),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        if (widget.loading && widget.locks.isEmpty)
          const TTSkeleton()
        else if (visible.isEmpty)
          TTEmpty(
            title: widget.locks.isEmpty
                ? 'No locks to display'
                : 'No matching locks',
            message: widget.locks.isEmpty
                ? 'No administrator-owned locks are listed on this page. Add a lock with the phone app, then refresh your account.'
                : 'Try another name, ID or connection filter. Search and filters apply to the current page.',
            icon: LucideIcons.lockKeyhole,
          )
        else
          LayoutBuilder(
            builder: (context, c) {
              final columns = !grid || c.maxWidth < 740
                  ? 1
                  : c.maxWidth < 1160
                  ? 2
                  : 3;
              return Wrap(
                spacing: 20,
                runSpacing: 20,
                children: [
                  for (final lock in visible)
                    SizedBox(
                      width: (c.maxWidth - 20 * (columns - 1)) / columns,
                      child: TTLockTile(
                        lock: lock,
                        state: widget.states[lock['id']],
                        synced: widget.synced,
                        compact: !grid,
                        disabled: disabled,
                        native: widget.native,
                        onOpen: (tab) => widget.open(lock, tab),
                        onCheck: () => widget.check(lock),
                        onOperate: (action) => widget.operate(lock, action),
                        onPhone: () => widget.phone(lock),
                        onEdit: () => widget.edit(lock),
                        onRemove: () => widget.remove(lock),
                      ),
                    ),
                ],
              );
            },
          ),
        const SizedBox(height: 20),
        Wrap(
          spacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            TextButton(
              onPressed: disabled || widget.page <= 1 ? null : widget.previous,
              child: const Text('Previous'),
            ),
            Text(
              'Page ${widget.page} / ${widget.pages == 0 ? 1 : widget.pages}',
            ),
            TextButton(
              onPressed: disabled || widget.page >= widget.pages
                  ? null
                  : widget.next,
              child: const Text('Next'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        TTPanel(
          padding: const EdgeInsets.all(16),
          child: Wrap(
            spacing: 16,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Icon(LucideIcons.shieldCheck, color: ttGreen, size: 20),
              Text(
                widget.account,
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              Text(
                'Synced ${ttDate(widget.synced)}',
                style: TextStyle(color: ttMuted(context), fontSize: 12),
              ),
              TextButton(
                onPressed: disabled ? null : widget.reconnect,
                child: const Text('Reconnect'),
              ),
              TextButton(
                onPressed: disabled ? null : widget.disconnect,
                child: const Text('Disconnect'),
              ),
              if (widget.share != null)
                TextButton.icon(
                  onPressed: disabled ? null : widget.share,
                  icon: const Icon(LucideIcons.smartphone, size: 16),
                  label: const Text('Share Bluetooth with website'),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class TTLockTile extends StatelessWidget {
  final Map<String, dynamic> lock;
  final Map<String, dynamic>? state;
  final String? synced;
  final bool compact, disabled, native;
  final void Function(String) onOpen, onOperate;
  final VoidCallback onCheck, onPhone, onEdit, onRemove;
  const TTLockTile({
    super.key,
    required this.lock,
    this.state,
    this.synced,
    this.compact = false,
    required this.disabled,
    required this.native,
    required this.onOpen,
    required this.onOperate,
    required this.onCheck,
    required this.onPhone,
    required this.onEdit,
    required this.onRemove,
  });
  @override
  Widget build(BuildContext context) {
    final canControl = native || lock['has_gateway'] == true;
    final locked = state?['state'] == 'locked',
        unlocked = state?['state'] == 'unlocked';
    final label = locked
        ? 'Locked'
        : unlocked
        ? 'Unlocked'
        : 'State Unknown';
    final connection = state?['connection'];
    final reason = canControl
        ? 'Commands are authorized by TTLock when sent.'
        : 'No direct Bluetooth or compatible gateway is available. Use phone Bluetooth to connect a nearby app.';
    return TTPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: InkWell(
                  onTap: disabled ? null : () => onOpen('overview'),
                  borderRadius: BorderRadius.circular(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        lock['name'],
                        style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Lock ID: ${lock['id']}',
                        style: TextStyle(fontSize: 12, color: ttMuted(context)),
                      ),
                    ],
                  ),
                ),
              ),
              PopupMenuButton<String>(
                tooltip: 'Device options',
                enabled: !disabled,
                icon: Icon(
                  LucideIcons.ellipsis,
                  size: 20,
                  color: ttMuted(context),
                ),
                onSelected: (s) {
                  if (s == 'edit') {
                    onEdit();
                  } else {
                    onRemove();
                  }
                },
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'edit', child: Text('Edit name')),
                  PopupMenuItem(value: 'remove', child: Text('Remove in app')),
                ],
              ),
            ],
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              TTBadge(
                connection == 'online'
                    ? 'Verified online'
                    : connection == 'failed'
                    ? 'Check failed'
                    : 'Not verified',
                color: connection == 'online'
                    ? ttGreen
                    : connection == 'failed'
                    ? ttAmber
                    : ttMuted(context),
              ),
              if (lock['group'] is String &&
                  (lock['group'] as String).isNotEmpty)
                TTBadge(lock['group'], icon: LucideIcons.layers),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            padding: EdgeInsets.all(compact ? 12 : 22),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(18),
              gradient: LinearGradient(
                colors: [
                  ttBlue.withValues(alpha: .07),
                  ttBlue.withValues(alpha: .015),
                ],
              ),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                TTLockIllustration(size: compact ? 54 : 70),
                Column(
                  children: [
                    Tooltip(
                      message: !canControl
                          ? reason
                          : locked
                          ? 'Unlock'
                          : unlocked
                          ? 'Lock'
                          : 'Check status before choosing an action',
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 250),
                        padding: const EdgeInsets.all(7),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          border: Border.all(
                            color:
                                (locked
                                        ? ttBlue
                                        : unlocked
                                        ? ttGreen
                                        : ttMuted(context))
                                    .withValues(alpha: .15),
                            width: 5,
                          ),
                        ),
                        child: IconButton.filled(
                          onPressed: disabled || !canControl
                              ? null
                              : locked
                              ? () => onOperate('unlock')
                              : unlocked
                              ? () => onOperate('lock')
                              : onCheck,
                          tooltip: locked
                              ? 'Unlock control'
                              : unlocked
                              ? 'Lock control'
                              : 'Verify lock state',
                          style: IconButton.styleFrom(
                            backgroundColor: locked
                                ? ttBlue
                                : unlocked
                                ? ttGreen
                                : ttMuted(context).withValues(alpha: .12),
                            foregroundColor: locked || unlocked
                                ? Colors.white
                                : ttMuted(context),
                            padding: const EdgeInsets.all(20),
                          ),
                          icon: Icon(
                            locked
                                ? LucideIcons.lockKeyhole
                                : unlocked
                                ? LucideIcons.lockKeyholeOpen
                                : LucideIcons.circleHelp,
                            size: 28,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      label,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: locked
                            ? Theme.of(context).colorScheme.primary
                            : unlocked
                            ? ttGreen
                            : ttMuted(context),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          TTBattery(lock['battery']),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 6,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    LucideIcons.bluetooth,
                    size: 14,
                    color: ttMuted(context),
                  ),
                  const SizedBox(width: 5),
                  Text(
                    native
                        ? 'Bluetooth: check nearby'
                        : 'Bluetooth: phone bridge',
                    style: TextStyle(fontSize: 11, color: ttMuted(context)),
                  ),
                ],
              ),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(LucideIcons.router, size: 14, color: ttMuted(context)),
                  const SizedBox(width: 5),
                  Text(
                    lock['has_gateway'] == true
                        ? 'Gateway linked'
                        : 'No gateway reported',
                    style: TextStyle(fontSize: 11, color: ttMuted(context)),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            'Last sync · ${ttDate(synced)}',
            style: TextStyle(fontSize: 11, color: ttMuted(context)),
          ),
          if (state?['observed_at'] != null)
            Text(
              'State checked · ${ttDate(state!['observed_at'])}',
              style: TextStyle(fontSize: 11, color: ttMuted(context)),
            ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Tooltip(
                  message: reason,
                  child: OutlinedButton.icon(
                    onPressed: disabled || !canControl
                        ? null
                        : () => onOperate('lock'),
                    icon: const Icon(LucideIcons.lockKeyhole, size: 16),
                    label: const Text('Lock'),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Tooltip(
                  message: reason,
                  child: FilledButton.icon(
                    onPressed: disabled || !canControl
                        ? null
                        : () => onOperate('unlock'),
                    icon: const Icon(LucideIcons.lockKeyholeOpen, size: 16),
                    label: const Text('Unlock'),
                  ),
                ),
              ),
            ],
          ),
          if (!canControl)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                reason,
                style: TextStyle(
                  fontSize: 11,
                  height: 1.5,
                  color: ttMuted(context),
                ),
              ),
            ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final item in [
                ('eKeys', 'ekeys', LucideIcons.keyRound),
                ('Passcodes', 'passcode', LucideIcons.grid2x2),
                ('Cards', 'card', LucideIcons.creditCard),
                ('Fingerprints', 'fingerprint', LucideIcons.fingerprint),
                ('Access History', 'records', LucideIcons.history),
                ('Device Settings', 'settings', LucideIcons.settings2),
              ])
                TextButton.icon(
                  onPressed: disabled ? null : () => onOpen(item.$2),
                  icon: Icon(item.$3, size: 15),
                  label: Text(item.$1, style: const TextStyle(fontSize: 12)),
                ),
            ],
          ),
          const Divider(height: 24),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              TextButton.icon(
                onPressed: disabled || !canControl ? null : onCheck,
                icon: const Icon(LucideIcons.refreshCw, size: 15),
                label: const Text('Check status'),
              ),
              if (!native)
                TextButton.icon(
                  onPressed: disabled ? null : onPhone,
                  icon: const Icon(LucideIcons.smartphone, size: 15),
                  label: const Text('Use phone Bluetooth'),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
