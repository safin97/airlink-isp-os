import 'package:flutter/material.dart';
import 'branding.dart';

/// Connection UI only: passwords stay in the server-side saved profile.
class TowerApiLogin extends StatelessWidget {
  final Map<String, dynamic> device;
  final List<dynamic> profiles;
  final String profileId;
  final bool busy, loadingProfiles, profilesLoaded, owner, canEdit;
  final String? error;
  final int? errorStatus;
  final ValueChanged<String> onSelect;
  final VoidCallback onConnect, onReload, onClose;
  final VoidCallback? onAddProfile;
  const TowerApiLogin({
    super.key,
    required this.device,
    required this.profiles,
    required this.profileId,
    required this.busy,
    required this.loadingProfiles,
    required this.profilesLoaded,
    required this.owner,
    required this.canEdit,
    this.error,
    this.errorStatus,
    required this.onSelect,
    required this.onConnect,
    required this.onReload,
    required this.onClose,
    this.onAddProfile,
  });

  Map? get selected =>
      profiles.whereType<Map>().where((p) => p['id'] == profileId).firstOrNull;
  String connectionType(Map p) => switch (p['transport']) {
    'routeros' => 'MikroTik API',
    'routeros_tls' => 'MikroTik API-SSL',
    _ => 'Web / REST',
  };
  String port(Map p) {
    if (p['port'] != null) return '${p['port']}';
    return switch (p['transport']) {
      'routeros' => '8728',
      'routeros_tls' => '8729',
      _ =>
        p['protocol'] == 'http'
            ? '80'
            : p['protocol'] == 'https'
            ? '443'
            : '443 / 80',
    };
  }

  String encryption(Map p) => switch (p['transport']) {
    'routeros' => 'Standard API connection',
    'routeros_tls' =>
      p['verify_tls'] == false
          ? 'TLS · certificate verification off'
          : 'TLS · certificate verification on',
    _ =>
      p['protocol'] == 'http'
          ? 'HTTP connection'
          : p['protocol'] == 'https'
          ? p['verify_tls'] == false
                ? 'HTTPS · certificate verification off'
                : 'HTTPS · certificate verification on'
          : 'HTTPS first, HTTP fallback',
  };
  String get failureTitle {
    if (!profilesLoaded) return 'Saved logins could not be loaded';
    if (errorStatus == 403 || errorStatus == 404) {
      return 'Access needs attention';
    }
    if (errorStatus == 504) return 'Connection timed out';
    if ((error ?? '').toLowerCase().contains('rejected')) {
      return 'Login was rejected';
    }
    return 'Unable to connect';
  }

  Widget detail(
    BuildContext context,
    IconData icon,
    String label,
    String value,
  ) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          icon,
          size: 18,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 3),
              Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
            ],
          ),
        ),
      ],
    ),
  );

  Widget identity(BuildContext context, bool compact) => Container(
    padding: EdgeInsets.all(compact ? 22 : 32),
    decoration: const BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xff102e41), Color(0xff0b5660)],
      ),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: AirLinkLogo(width: 196),
              ),
            ),
            if (compact)
              IconButton(
                tooltip: 'Close',
                onPressed: busy ? null : onClose,
                icon: const Icon(Icons.close, color: Colors.white),
              ),
          ],
        ),
        SizedBox(height: compact ? 14 : 38),
        if (!compact) ...[
          Container(
            padding: const EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .10),
              borderRadius: BorderRadius.circular(18),
            ),
            child: Icon(
              device['vendor'] == 'mikrotik_switch'
                  ? Icons.settings_ethernet
                  : Icons.router_outlined,
              color: const Color(0xff9aece3),
              size: 32,
            ),
          ),
          const SizedBox(height: 22),
        ],
        Text(
          '${device['username'] ?? device['name'] ?? 'Device'}',
          style: TextStyle(
            color: Colors.white,
            fontSize: compact ? 22 : 28,
            fontWeight: FontWeight.w700,
            height: 1.2,
          ),
        ),
        const SizedBox(height: 10),
        SelectableText(
          '${device['ip_address'] ?? ''}',
          style: const TextStyle(color: Color(0xffc1dce3), fontSize: 15),
        ),
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: .10),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            device['vendor'] == 'mikrotik_switch'
                ? 'MikroTik switch'
                : 'MikroTik RouterOS',
            style: const TextStyle(color: Color(0xffc5e8e9), fontSize: 12),
          ),
        ),
        if (!compact) ...[
          const SizedBox(height: 38),
          const Divider(color: Color(0xff3e6b78)),
          const SizedBox(height: 18),
          const Text(
            'YOUR DEVICE WORKSPACE',
            style: TextStyle(
              color: Color(0xff91bdc8),
              fontSize: 10,
              letterSpacing: 1.2,
            ),
          ),
          const SizedBox(height: 16),
          for (final item in [
            (Icons.settings_ethernet, 'Ports & live traffic'),
            (Icons.wifi, 'Wireless & clients'),
            (Icons.tune, 'Device configuration'),
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Row(
                children: [
                  Icon(item.$1, size: 17, color: const Color(0xff8ae0d9)),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      item.$2,
                      style: const TextStyle(
                        color: Color(0xffd4e8ec),
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ],
    ),
  );

  Widget form(BuildContext context, bool compact) {
    final scheme = Theme.of(context).colorScheme;
    final profile = selected;
    final ready = !busy && profilesLoaded && profile != null;
    return Padding(
      padding: EdgeInsets.all(compact ? 22 : 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Connect to device',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: -.5,
                          ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Select a saved login to open the device manager.',
                      style: TextStyle(
                        color: scheme.onSurfaceVariant,
                        height: 1.5,
                      ),
                    ),
                  ],
                ),
              ),
              if (!compact)
                IconButton(
                  tooltip: 'Close',
                  onPressed: busy ? null : onClose,
                  icon: const Icon(Icons.close),
                ),
            ],
          ),
          const SizedBox(height: 26),
          if (loadingProfiles) ...[
            const LinearProgressIndicator(),
            const SizedBox(height: 12),
            const Text('Loading saved logins…'),
          ] else if (profiles.isEmpty && profilesLoaded)
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: scheme.surfaceContainerLow,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Column(
                children: [
                  Icon(Icons.key_outlined, size: 32, color: scheme.primary),
                  const SizedBox(height: 12),
                  const Text(
                    'No saved logins available',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    owner
                        ? 'Add a login for this device to get started.'
                        : 'Ask the owner to share a Towers API login with your account.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: scheme.onSurfaceVariant),
                  ),
                ],
              ),
            )
          else if (profilesLoaded) ...[
            DropdownButtonFormField<String>(
              key: ValueKey('tower-login-profile-$profileId'),
              initialValue: profileId,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: 'Device login profile',
                prefixIcon: Icon(Icons.key_outlined),
                border: OutlineInputBorder(),
              ),
              items: [
                const DropdownMenuItem(
                  value: '',
                  child: Text('Choose a saved login'),
                ),
                for (final p in profiles)
                  DropdownMenuItem(
                    value: '${p['id']}',
                    child: Text(
                      '${p['name']} — ${p['username']}',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: busy
                  ? null
                  : (v) {
                      if (v != null) onSelect(v);
                    },
            ),
            if (profile != null) ...[
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  color: scheme.primary.withValues(alpha: .045),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: scheme.outlineVariant),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    detail(
                      context,
                      Icons.person_outline,
                      'Device username',
                      '${profile['username'] ?? ''}',
                    ),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: detail(
                            context,
                            Icons.cable,
                            'Connection',
                            connectionType(profile),
                          ),
                        ),
                        Expanded(
                          child: detail(
                            context,
                            Icons.tag,
                            'Port',
                            port(profile),
                          ),
                        ),
                      ],
                    ),
                    const Divider(height: 18),
                    Text(
                      encryption(profile),
                      style: TextStyle(
                        color: scheme.onSurfaceVariant,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
            ] else
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  'Choose the account you want to use on this device.',
                  style: TextStyle(
                    color: scheme.onSurfaceVariant,
                    fontSize: 12,
                  ),
                ),
              ),
          ],
          if (error != null && !busy) ...[
            const SizedBox(height: 18),
            Semantics(
              liveRegion: true,
              child: Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: scheme.errorContainer.withValues(alpha: .5),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.error_outline, color: scheme.error, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            failureTitle,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: scheme.onErrorContainer,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            error!,
                            style: TextStyle(
                              color: scheme.onErrorContainer,
                              fontSize: 13,
                              height: 1.4,
                            ),
                          ),
                          if (profilesLoaded && owner)
                            const Padding(
                              padding: EdgeInsets.only(top: 8),
                              child: Text(
                                'You can review saved credentials and connection settings in Towers API.',
                                style: TextStyle(fontSize: 12),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          if (busy && !loadingProfiles) ...[
            const SizedBox(height: 22),
            const LinearProgressIndicator(),
            const SizedBox(height: 12),
            Semantics(
              liveRegion: true,
              child: const Text(
                'Connecting and reading device details…',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'This may take up to a minute. The workspace opens when the device responds.',
              style: TextStyle(
                color: scheme.onSurfaceVariant,
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: ready ? onConnect : null,
            icon: busy && !loadingProfiles
                ? const SizedBox(
                    width: 17,
                    height: 17,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.arrow_forward, size: 19),
            label: Text(
              busy && !loadingProfiles
                  ? 'Connecting…'
                  : error != null && profilesLoaded
                  ? 'Retry connection'
                  : 'Connect',
            ),
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 18),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Icon(
                canEdit ? Icons.tune : Icons.visibility_outlined,
                size: 16,
                color: scheme.onSurfaceVariant,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  canEdit
                      ? 'View readings and edit settings with review before saving.'
                      : 'Your AirLink account has read-only device access.',
                  style: TextStyle(
                    fontSize: 12,
                    color: scheme.onSurfaceVariant,
                    height: 1.4,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              TextButton.icon(
                onPressed: busy ? null : onReload,
                icon: const Icon(Icons.refresh, size: 17),
                label: const Text('Reload logins'),
              ),
              if (owner && onAddProfile != null)
                TextButton.icon(
                  onPressed: busy ? null : onAddProfile,
                  icon: const Icon(Icons.add, size: 17),
                  label: const Text('Add saved login'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Theme.of(context).colorScheme.surface,
    insetPadding: EdgeInsets.all(
      MediaQuery.sizeOf(context).width < 600 ? 12 : 32,
    ),
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 940),
      child: SingleChildScrollView(
        child: LayoutBuilder(
          builder: (context, box) {
            final compact = box.maxWidth < 720;
            return compact
                ? Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [identity(context, true), form(context, true)],
                  )
                : IntrinsicHeight(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SizedBox(width: 310, child: identity(context, false)),
                        Expanded(child: form(context, false)),
                      ],
                    ),
                  );
          },
        ),
      ),
    ),
  );
}
