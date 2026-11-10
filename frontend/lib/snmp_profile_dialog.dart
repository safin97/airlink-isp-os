import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class SnmpProfileDialog extends StatefulWidget {
  const SnmpProfileDialog({super.key, required this.api});
  final Api api;

  @override
  State<SnmpProfileDialog> createState() => _SnmpProfileDialogState();
}

class _SnmpProfileDialogState extends State<SnmpProfileDialog>
    with LanguageRebuild {
  final form = GlobalKey<FormState>();
  final fields = {
    for (final key in ['name', 'community', 'username', 'auth_key', 'priv_key'])
      key: TextEditingController(),
  };
  String version = '2c';
  String authProtocol = 'SHA1', privProtocol = 'AES128';
  bool busy = false;
  String? error;

  @override
  void dispose() {
    for (final controller in fields.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/snmp-profiles',
        method: 'POST',
        body: {
          'name': fields['name']!.text.trim(),
          'version': version,
          if (version == '3') ...{
            'username': fields['username']!.text.trim(),
            'auth_protocol': authProtocol,
            'priv_protocol': privProtocol,
            'auth_key': fields['auth_key']!.text,
            'priv_key': fields['priv_key']!.text,
          } else
            'community': fields['community']!.text,
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

  Widget field(
    String key,
    String label, {
    bool secret = false,
    int min = 1,
    int max = 255,
  }) => Padding(
    padding: const EdgeInsets.only(top: 14),
    child: TextFormField(
      key: ValueKey(key),
      controller: fields[key],
      enabled: !busy,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: false,
      decoration: InputDecoration(labelText: tr(label)),
      validator: (value) {
        if (value == null || value.trim().isEmpty) return tr('Required');
        if (value.length < min || value.length > max) {
          return '${tr('Length')}: $min–$max';
        }
        return null;
      },
    ),
  );

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: AlertDialog(
      title: const AppText('Add SNMP profile'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: version,
                  decoration: InputDecoration(labelText: tr('SNMP version')),
                  items: const [
                    DropdownMenuItem(value: '1', child: Text('SNMP v1')),
                    DropdownMenuItem(value: '2', child: Text('SNMP v2')),
                    DropdownMenuItem(value: '3', child: Text('SNMP v3')),
                    DropdownMenuItem(value: '2c', child: Text('SNMP v2c')),
                  ],
                  onChanged: busy
                      ? null
                      : (value) => setState(() => version = value!),
                ),
                field('name', 'Profile name', max: 120),
                if (version == '3') ...[
                  field('username', 'SNMPv3 username', max: 32),
                  DropdownButtonFormField<String>(
                    initialValue: authProtocol,
                    decoration: const InputDecoration(
                      labelText: 'Authentication protocol',
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: 'SHA1',
                        child: Text('SHA-1 (MikroTik)'),
                      ),
                      DropdownMenuItem(value: 'SHA256', child: Text('SHA-256')),
                      DropdownMenuItem(value: 'MD5', child: Text('MD5')),
                    ],
                    onChanged: busy
                        ? null
                        : (value) => setState(() => authProtocol = value!),
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: privProtocol,
                    decoration: const InputDecoration(
                      labelText: 'Privacy protocol',
                    ),
                    items: const [
                      DropdownMenuItem(value: 'AES128', child: Text('AES-128')),
                      DropdownMenuItem(value: 'DES', child: Text('DES')),
                    ],
                    onChanged: busy
                        ? null
                        : (value) => setState(() => privProtocol = value!),
                  ),
                  field(
                    'auth_key',
                    'Authentication key (8+ characters)',
                    secret: true,
                    min: 8,
                    max: 128,
                  ),
                  field(
                    'priv_key',
                    'Privacy key (8+ characters)',
                    secret: true,
                    min: 8,
                    max: 128,
                  ),
                ] else ...[
                  field('community', 'Read-only community', secret: true),
                  const SizedBox(height: 14),
                  const AppText(
                    'Enable SNMP on the device and allow UDP 161 from your AirLink server. Use a read-only community.',
                  ),
                ],
                if (error != null) ...[
                  const SizedBox(height: 14),
                  Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ],
              ],
            ),
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
          child: AppText(busy ? 'Saving…' : 'Save'),
        ),
      ],
    ),
  );
}
