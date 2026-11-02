import 'app_theme.dart';
import 'app_language.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';

class Sas4Connection extends StatefulWidget {
  final Api api;
  const Sas4Connection({super.key, required this.api});
  @override
  State<Sas4Connection> createState() => _Sas4ConnectionState();
}

class _Sas4ConnectionState extends State<Sas4Connection> with LanguageRebuild {
  bool get canEdit =>
      canEditSection(widget.api.user ?? {}, 'isp_card') ||
      canEditSection(widget.api.user ?? {}, 'noc');
  final username = TextEditingController();
  final password = TextEditingController();
  final form = GlobalKey<FormState>();
  bool busy = true;
  bool configured = false;
  String? error;
  String? message;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('/integrations/sas4');
      if (!mounted) return;
      setState(() {
        username.text = data['username'];
        configured = data['configured'] == true;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save() async {
    if (!canEdit) return;
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await widget.api.request(
        '/integrations/sas4',
        method: 'PUT',
        body: {
          'username': username.text.trim(),
          'password': password.text.isEmpty ? null : password.text,
        },
      );
      if (!mounted) return;
      setState(() {
        configured = true;
        password.clear();
        message = 'Connection saved. Checking SAS4…';
      });
      final clientsAllowed = hasSection(widget.api.user!, 'isp_card');
      final data = await widget.api.request(
        clientsAllowed
            ? '/integrations/sas4/clients?page=1'
            : '/integrations/sas4/online-count',
      );
      if (mounted) {
        setState(
          () => message = clientsAllowed
              ? 'Connected. ${data['total']} clients available in ISP Card.'
              : 'Connected. Online users: ${data['online_users'] ?? 'Unavailable'}.',
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          message = null;
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
    key: form,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const AppText(
          'SAS4 connection',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        AppText(
          'airlinkcom.online • Private to your AirLink account.',
          style: TextStyle(color: themeColor(0xff99acc6, 0xff52627a)),
        ),
        const SizedBox(height: 16),
        TextFormField(
          controller: username,
          enabled: !busy && canEdit,
          decoration: InputDecoration(labelText: tr('SAS4 manager username')),
          validator: (value) =>
              value == null || value.trim().isEmpty ? 'Required' : null,
        ),
        const SizedBox(height: 16),
        TextFormField(
          controller: password,
          enabled: !busy && canEdit,
          obscureText: true,
          decoration: InputDecoration(
            labelText: tr('SAS4 manager password'),
            helperText: configured
                ? 'Leave blank to keep the saved password for this username.'
                : 'Stored encrypted on the AirLink server.',
          ),
          validator: (value) => !configured && (value == null || value.isEmpty)
              ? 'Required'
              : null,
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: busy || !canEdit ? null : save,
          icon: const Icon(Icons.link),
          label: const AppText('Save SAS4 connection'),
        ),
        if (busy)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: LinearProgressIndicator(),
          ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (message != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(message!),
          ),
      ],
    ),
  );
}
