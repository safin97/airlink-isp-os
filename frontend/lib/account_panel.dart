import 'telegram_settings.dart';
import 'app_language.dart';

import 'package:flutter/material.dart';

import 'api.dart';
import 'payment_settings.dart';
import 'customer_device_access.dart';

Map<String, IconData> accountPagesFor(Map<String, dynamic> user) => {
  if (user['role'] == 'owner') 'Account profile': Icons.person_outline,
  'Change password': Icons.lock_outline,
  if (user['role'] == 'owner' || user['role'] == 'manager')
    'Telegram notifications': Icons.send_outlined,
  if (user['role'] == 'owner') ...{
    'Customer device access': Icons.router_outlined,
    'Payment setup': Icons.payments_outlined,
  },
};

class AccountPanel extends StatefulWidget {
  final Api api;
  final String page;
  const AccountPanel({
    super.key,
    required this.api,
    this.page = 'Account profile',
  });
  @override
  State<AccountPanel> createState() => _AccountPanelState();
}

class _AccountPanelState extends State<AccountPanel> with LanguageRebuild {
  final current = TextEditingController();
  final next = TextEditingController();
  final confirm = TextEditingController();
  final form = GlobalKey<FormState>();
  bool busy = false;
  String? error;
  String? message;
  Map<String, dynamic> get user => widget.api.user ?? {};

  @override
  void dispose() {
    current.dispose();
    next.dispose();
    confirm.dispose();
    super.dispose();
  }

  Future<void> changePassword() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await widget.api.request(
        '/auth/password',
        method: 'PUT',
        body: {
          'current_password': current.text,
          'new_password': next.text,
          'confirm_password': confirm.text,
        },
      );
      if (!mounted) return;
      current.clear();
      next.clear();
      confirm.clear();
      setState(
        () => message =
            'Password changed. Your other sessions have been signed out.',
      );
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final selectedPage = accountPagesFor(user).containsKey(widget.page)
        ? widget.page
        : accountPagesFor(user).keys.first;
    return Card(
      key: const ValueKey('account-page'),
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            AppText(
              selectedPage,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 20),
            switch (selectedPage) {
              'Telegram notifications' => TelegramSettings(api: widget.api),
              'Change password' => passwordSettings(),
              'Customer device access' => CustomerDeviceAccess(
                api: widget.api,
                embedded: true,
              ),
              'Payment setup' => PaymentSettings(
                api: widget.api,
                embedded: true,
              ),
              _ => profile(),
            },
          ],
        ),
      ),
    );
  }

  Widget profile() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const CircleAvatar(child: Icon(Icons.person_outline)),
        title: SelectableText(
          '${user['username'] ?? ''}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          'Role: ${user['access_role_name'] ?? user['manager_role_name'] ?? user['role'] ?? ''}',
        ),
      ),
      if (user['created_at'] != null)
        Text(
          'Account created: ${user['created_at'].toString().split('T').first}',
        ),
    ],
  );

  Widget passwordSettings() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Form(
        key: form,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextFormField(
              controller: current,
              obscureText: true,
              enabled: !busy,
              decoration: InputDecoration(labelText: tr('Current password')),
              validator: (v) => v == null || v.isEmpty ? 'Required' : null,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: next,
              obscureText: true,
              enabled: !busy,
              decoration: InputDecoration(
                labelText: tr('New password'),
                helperText:
                    '14–128 characters, with at least 8 different characters.',
              ),
              validator: (v) =>
                  v == null ||
                      v.length < 14 ||
                      v.length > 128 ||
                      v.runes.toSet().length < 8
                  ? 'Use 14–128 characters with at least 8 different characters'
                  : null,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: confirm,
              obscureText: true,
              enabled: !busy,
              decoration: InputDecoration(
                labelText: tr('Confirm new password'),
              ),
              validator: (v) =>
                  v != next.text ? 'Passwords do not match' : null,
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: busy ? null : changePassword,
              child: AppText(busy ? 'Saving…' : 'Change password'),
            ),
          ],
        ),
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
        Padding(padding: const EdgeInsets.only(top: 12), child: Text(message!)),
    ],
  );
}
