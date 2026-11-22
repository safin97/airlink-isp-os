import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';
import 'api.dart';
import 'app_language.dart';

class ClientPortalSettings extends StatefulWidget {
  final Api api;
  const ClientPortalSettings({super.key, required this.api});
  @override
  State<ClientPortalSettings> createState() => _ClientPortalSettingsState();
}

class _ClientPortalSettingsState extends State<ClientPortalSettings> {
  final rangeInput = TextEditingController();
  List<String> networks = [];
  bool enabled = false, busy = true, loaded = false;
  String? message, error, rangeError;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    rangeInput.dispose();
    super.dispose();
  }

  void applySettings(dynamic data) {
    enabled = data['enabled'] == true;
    networks = List<String>.from(data['subscriber_networks']);
    loaded = true;
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await widget.api.request('/client-portal');
      if (mounted) setState(() => applySettings(data));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String? validateRange(String value) {
    final parts = value.split('/');
    if (parts.length != 2 || !RegExp(r'^\d+$').hasMatch(parts[1])) {
      return 'Enter an IP range in CIDR format, for example 172.16.0.0/12.';
    }
    try {
      final ipv6 = parts[0].contains(':');
      final bytes = ipv6
          ? Uri.parseIPv6Address(parts[0])
          : Uri.parseIPv4Address(parts[0]);
      if (!ipv6 && bytes.join('.') != parts[0]) throw const FormatException();
      final prefix = int.parse(parts[1]);
      if (prefix < 1 || prefix > bytes.length * 8) {
        return ipv6
            ? 'IPv6 prefix must be between 1 and 128.'
            : 'IPv4 prefix must be between 1 and 32.';
      }
      for (var bit = prefix; bit < bytes.length * 8; bit++) {
        if ((bytes[bit ~/ 8] & (1 << (7 - bit % 8))) != 0) {
          return 'Use the network address for this prefix, not a device address.';
        }
      }
    } on FormatException {
      return 'Enter a valid IPv4 or IPv6 network address.';
    }
    return null;
  }

  bool addRange() {
    final value = rangeInput.text.trim();
    final problem = validateRange(value);
    setState(() {
      rangeError =
          problem ??
          (networks.any((n) => n.toLowerCase() == value.toLowerCase())
              ? 'This IP range is already in the list.'
              : networks.length >= 32
              ? 'You can add up to 32 IP ranges.'
              : null);
      if (rangeError == null) {
        networks.add(value);
        rangeInput.clear();
        message = null;
        error = null;
      }
    });
    return rangeError == null;
  }

  Future<void> save() async {
    if (busy || !loaded) return;
    // Include an entered range even when Save is pressed before Add.
    if (rangeInput.text.trim().isNotEmpty && !addRange()) return;
    setState(() {
      busy = true;
      message = null;
      error = null;
    });
    try {
      final data = await widget.api.request(
        '/client-portal',
        method: 'PUT',
        body: {
          'enabled': enabled,
          'subscriber_networks': List<String>.from(networks),
        },
      );
      if (mounted) {
        setState(() {
          applySettings(data);
          message =
              'Client portal saved. Existing client sessions have been signed out.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const AppText(
        'Customers sign in with their SAS4 PPPoE account and recharge only their own service. Your saved SAS4 connection and FIB merchant settings are used.',
      ),
      if (busy)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: LinearProgressIndicator(),
        ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const AppText('Enable client recharge portal'),
        value: enabled,
        onChanged: busy || !loaded
            ? null
            : (value) => setState(() {
                enabled = value;
                message = null;
              }),
      ),
      const SizedBox(height: 12),
      Text(
        tr('Automatic login IP ranges'),
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 8),
      const AppText(
        'Add each PPPoE subscriber network below, then save the client portal.',
      ),
      const SizedBox(height: 16),
      TextField(
        controller: rangeInput,
        enabled: !busy && loaded,
        autocorrect: false,
        enableSuggestions: false,
        textInputAction: TextInputAction.done,
        onSubmitted: (_) {
          if (!busy && loaded) addRange();
        },
        onChanged: (_) {
          if (rangeError != null) setState(() => rangeError = null);
        },
        decoration: InputDecoration(
          labelText: tr('IP range (CIDR)'),
          hintText: '172.16.0.0/12',
          errorText: rangeError == null ? null : tr(rangeError!),
          errorMaxLines: 3,
          border: const OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: 10),
      OutlinedButton.icon(
        onPressed: busy || !loaded ? null : addRange,
        icon: const Icon(Icons.add),
        label: const AppText('Add IP range'),
      ),
      if (loaded) ...[
        const SizedBox(height: 16),
        if (networks.isEmpty)
          const AppText(
            'No IP ranges added. Automatic login is off; customers can sign in with their username and password.',
          )
        else ...[
          Text('${tr('Allowed IP ranges')}: ${networks.length}/32'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final network in networks)
                InputChip(
                  key: ValueKey(network),
                  label: Text(network),
                  deleteButtonTooltipMessage: '${tr('Remove')} $network',
                  onDeleted: busy
                      ? null
                      : () => setState(() {
                          networks.remove(network);
                          message = null;
                          rangeError = null;
                        }),
                ),
            ],
          ),
        ],
      ],
      const SizedBox(height: 16),
      const AppText(
        'Use subscriber IP ranges visible before shared NAT. Automatic login requires a unique RADIUS session updated within two minutes. Other connections use password login.',
      ),
      if (networks.contains('172.0.0.0/8')) ...[
        const SizedBox(height: 8),
        const AppText(
          '172.0.0.0/8 includes public addresses. Use only ranges assigned to your PPPoE subscribers.',
        ),
      ],
      const SizedBox(height: 12),
      const AppText(
        'Saving applies the listed ranges and signs out existing client sessions.',
      ),
      const SizedBox(height: 16),
      FilledButton(
        onPressed: busy || !loaded ? null : save,
        child: const AppText('Save client portal'),
      ),
      if (error != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ),
      if (!loaded && !busy)
        TextButton(onPressed: load, child: const AppText('Retry connection')),
      Link(
        uri: Uri.base.resolve('/client'),
        target: LinkTarget.blank,
        builder: (_, follow) => TextButton(
          onPressed: follow,
          child: const AppText('Open client portal'),
        ),
      ),
      if (message != null) Text(message!),
    ],
  );
}
