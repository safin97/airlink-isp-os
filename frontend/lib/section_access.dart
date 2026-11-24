import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

const operationalSections = <String, String>{
  'dashboard': 'Dashboard',
  'noc': 'NOC Screen',
  'towers': 'Towers',
  'isp_card': 'ISP Card',
  'monitoring': 'Monitoring',
  'network_map': 'Network Map',
  'alerts': 'Alerts',
  'reports': 'Reports',
};
const administrativeSections = <String, String>{
  'fib_recharge': 'FIB Bank recharge',
  'managers': 'Managers',
  'inventory_admin': 'Inventory administration',
  'device_login': 'Device login',
  'towers_api': 'Towers API',
  'card_system': 'Card System',
  'ttlock': 'TTLock',
  'deye_management': 'Deye configuration and sharing',
  'backups': 'Backups and restore',
  'vpn': 'VPN',
  'payment_gateways': 'Payment setup',
  'client_portal': 'Client portal settings',
  'customer_device_access': 'Customer device access',
  'device_api_access': 'Device API access',
  'telegram_bot': 'Customer Telegram bot',
  'telegram_account': 'Telegram account lookup',
  'telegram_notifications': 'Telegram notifications',
  'whatsapp': 'WhatsApp notifications',
  'pc_updates': 'PC and GPU updates',
  'snmp_sharing': 'SNMP visibility sharing',
};
const assignableSections = <String, String>{
  ...operationalSections,
  'software_updates': 'Software Updates',
  'settings': 'Settings',
  'access_roles': 'Access Roles',
  ...administrativeSections,
};
const pageSections = <String, String>{
  ...operationalSections,
  'software_updates': 'Software Updates',
  'settings': 'Settings',
  'access_roles': 'Access Roles',
  'deye': 'Deye Solar',
  'managers': 'Managers',
  'ttlock': 'TTLock',
  'device_login': 'Device login',
  'towers_api': 'Towers API',
};
const ownerSections = <String, String>{
  ...pageSections,
  'diagnostics': 'Diagnostics',
  'my_account': 'My account',
  'card_system': 'Card System',
};
const pinnedOwnerSections = {'access_roles', 'my_account'};

bool usesSectionPermissions(Map<String, dynamic> user) =>
    user['role'] == 'manager' || user['access_policy_configured'] == true;

bool canViewSnmpProfiles(Map<String, dynamic> user) =>
    user['role'] == 'owner' ||
    (user['show_snmp_profiles'] as bool? ??
        (usesSectionPermissions(user) && hasSection(user, 'settings')));

bool hasSection(Map<String, dynamic> user, String key) {
  if (user['role'] == 'owner') {
    final visible = user['visible_sections'] as List?;
    return pinnedOwnerSections.contains(key) ||
        !ownerSections.containsKey(key) ||
        visible == null ||
        visible.contains(key);
  }
  if (key == 'deye') {
    return user['show_deye_solar'] as bool? ??
        (user['sections'] as List? ?? []).contains('deye');
  }
  if ((key == 'access_roles') && !usesSectionPermissions(user)) {
    return user['role'] == 'owner';
  }
  if (administrativeSections.containsKey(key) &&
      !usesSectionPermissions(user)) {
    return false;
  }
  if (!usesSectionPermissions(user)) return true;
  if (!assignableSections.containsKey(key)) return false;
  final sections = user['sections'] as List?;
  return sections == null
      ? operationalSections.containsKey(key)
      : sections.contains(key);
}

bool canEditSection(Map<String, dynamic> user, String key) {
  if (user['role'] == 'owner') return true;
  if (key == 'deye') return false;
  if (!usesSectionPermissions(user) || !hasSection(user, key)) return false;
  final editable = user['editable_sections'] as List?;
  return editable == null
      ? !administrativeSections.containsKey(key)
      : editable.contains(key);
}

bool canDeleteSection(Map<String, dynamic> user, String key) {
  if (user['role'] == 'owner') return true;
  if (key == 'deye') return false;
  if (!usesSectionPermissions(user) || !hasSection(user, key)) return false;
  final deletable = user['deletable_sections'] as List?;
  return deletable == null
      ? !administrativeSections.containsKey(key) && canEditSection(user, key)
      : deletable.contains(key);
}

bool canReadResource(Map<String, dynamic> user, String resource) {
  if (resource == 'snmp-profiles') return canViewSnmpProfiles(user);
  if (!usesSectionPermissions(user)) return true;
  const readers = <String, List<String>>{
    'dashboard': ['dashboard', 'noc'],
    'users': ['managers'],
    'access-roles': ['access_roles'],
    'towers': ['towers', 'noc', 'network_map', 'monitoring'],
    'places': ['towers'],
    'devices': ['towers', 'noc', 'network_map', 'monitoring'],
    'sectors': ['towers', 'network_map', 'monitoring'],
    'alerts': ['dashboard', 'noc', 'alerts'],
    'links': ['network_map'],
    'snmp-profiles': ['settings'],
  };
  return (readers[resource] ?? []).any((key) => hasSection(user, key));
}

class SectionAccessDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> account;
  const SectionAccessDialog({
    super.key,
    required this.api,
    required this.account,
  });
  @override
  State<SectionAccessDialog> createState() => _SectionAccessDialogState();
}

class _SectionAccessDialogState extends State<SectionAccessDialog> {
  late final Set<String> selected = Set<String>.from(
    widget.account['sections'] as List? ?? operationalSections.keys,
  );
  late final Set<String> editable = Set<String>.from(
    widget.account['editable_sections'] as List? ?? selected,
  );
  late final Set<String> deletable = Set<String>.from(
    widget.account['deletable_sections'] as List? ?? editable,
  );
  bool busy = false;
  String? error;

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/users/${widget.account['id']}/sections',
        method: 'PUT',
        body: {
          'sections': assignableSections.keys.where(selected.contains).toList(),
          'deletable_sections': assignableSections.keys
              .where((key) => selected.contains(key) && deletable.contains(key))
              .toList(),
          'editable_sections': assignableSections.keys
              .where((key) => selected.contains(key) && editable.contains(key))
              .toList(),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text('Section access · ${widget.account['username']}'),
    content: SizedBox(
      width: 680,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const AppText(
              'Show allows reading. Allow edits and Allow delete are separate permissions.',
            ),
            Row(
              children: [
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(
                          () => selected.addAll(assignableSections.keys),
                        ),
                  child: const AppText('Select all'),
                ),
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(() {
                          selected.clear();
                          editable.clear();
                          deletable.clear();
                        }),
                  child: const AppText('Clear all'),
                ),
              ],
            ),
            for (final section in assignableSections.entries)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: AppText(section.value),
                subtitle: AppText(
                  !selected.contains(section.key)
                      ? 'Hidden'
                      : editable.contains(section.key) &&
                            deletable.contains(section.key)
                      ? 'Edit and delete'
                      : editable.contains(section.key)
                      ? 'Can edit'
                      : deletable.contains(section.key)
                      ? 'Can delete'
                      : 'Read-only',
                ),
                secondary: Tooltip(
                  message: 'Allow edits: ${section.value}',
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const AppText('Allow delete'),
                      Checkbox(
                        key: ValueKey('delete-${section.key}'),
                        value:
                            selected.contains(section.key) &&
                            deletable.contains(section.key),
                        onChanged: busy || !selected.contains(section.key)
                            ? null
                            : (value) => setState(() {
                                if (value == true) {
                                  deletable.add(section.key);
                                } else {
                                  deletable.remove(section.key);
                                }
                              }),
                      ),
                      const AppText('Allow edits'),
                      Checkbox(
                        key: ValueKey('edit-${section.key}'),
                        value:
                            selected.contains(section.key) &&
                            editable.contains(section.key),
                        onChanged: busy || !selected.contains(section.key)
                            ? null
                            : (value) => setState(() {
                                if (value == true) {
                                  editable.add(section.key);
                                } else {
                                  editable.remove(section.key);
                                }
                              }),
                      ),
                    ],
                  ),
                ),
                value: selected.contains(section.key),
                onChanged: busy
                    ? null
                    : (value) => setState(() {
                        if (value == true) {
                          selected.add(section.key);
                        } else {
                          selected.remove(section.key);
                          editable.remove(section.key);
                          deletable.remove(section.key);
                        }
                      }),
              ),
            const SizedBox(height: 8),
            const AppText(
              'Administrative features require explicit permissions. Managers can delegate only their own permissions. Owner accounts stay protected.',
            ),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy ? null : () => Navigator.pop(context),
        child: const AppText('Cancel'),
      ),
      FilledButton(
        onPressed: busy ? null : save,
        child: AppText(busy ? 'Saving…' : 'Save access'),
      ),
    ],
  );
}

// Mirror the server's administrative route registry for immediate UI feedback.
const featureRoutes = <String, String>{
  '/integrations/ttlock': 'ttlock',
  '/card-system': 'card_system',
  '/vpn': 'vpn',
  '/backups': 'backups',
  '/towers-api-profiles': 'towers_api',
  '/integrations/sas4/device-login-profiles': 'device_login',
  '/integrations/sas4/device-access': 'customer_device_access',
  '/device-api-access': 'device_api_access',
  '/payments/gateways': 'payment_gateways',
  '/client-portal': 'client_portal',
  '/integrations/telegram-account': 'telegram_account',
  '/integrations/whatsapp': 'whatsapp',
  '/system/pc-updates': 'pc_updates',
  '/users': 'managers',
  '/snmp-profile-visibility': 'snmp_sharing',
  '/integrations/telegram': 'telegram_notifications',
};
String? featureForRequest(String path) {
  path = Uri.parse(path).path.replaceFirst(RegExp(r'/$'), '');
  for (final route in featureRoutes.entries) {
    if (path == route.key || path.startsWith('${route.key}/')) {
      return route.value;
    }
  }
  return null;
}

String featureRequestAction(String method, String path, Object? body) {
  if (method == 'DELETE') return 'delete';
  if (['GET', 'HEAD', 'OPTIONS'].contains(method)) {
    return path.startsWith('/integrations/ttlock/') &&
            path.endsWith('/bluetooth')
        ? 'edit'
        : 'view';
  }
  final values = body is Map ? body : const {};
  final action =
      path == '/integrations/ttlock/bridge/jobs' && values['parameters'] is Map
      ? values['parameters']['action']
      : [
          '/card-system/radius/action',
          '/integrations/ttlock/mobile/prepare',
        ].contains(path)
      ? values['action']
      : null;
  if (action is String &&
      (action == 'delete' ||
          action.endsWith('_delete') ||
          action == 'lock_reset')) {
    return 'delete';
  }
  if (path.startsWith('/integrations/ttlock/mobile/') &&
      (path.endsWith('/complete') || path.endsWith('/sync'))) {
    return 'view';
  }
  if (path.startsWith('/integrations/ttlock/bridge/jobs/') &&
      path.endsWith('/claim')) {
    return 'view';
  }
  if (path.endsWith('/delete') ||
      (path.endsWith('/disconnect') && !path.startsWith('/vpn/'))) {
    return 'delete';
  }
  if (path.startsWith('/card-system/') && path.endsWith('/pin')) return 'view';
  return 'edit';
}

bool canFeatureRequest(
  Map<String, dynamic> user,
  String path,
  String method,
  Object? body,
) {
  if (user['role'] == 'owner') return true;
  final feature = featureForRequest(path);
  if (feature == null) return true;
  return switch (featureRequestAction(method, Uri.parse(path).path, body)) {
    'view' => hasSection(user, feature),
    'delete' => canDeleteSection(user, feature),
    _ => canEditSection(user, feature),
  };
}
