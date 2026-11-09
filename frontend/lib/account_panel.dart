import 'app_language.dart';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'api.dart';
import 'sas4_connection.dart';
import 'payment_settings.dart';
import 'section_access.dart';

class AccountPanel extends StatefulWidget {
  final Api api;
  const AccountPanel({super.key, required this.api});
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
    final media = MediaQuery.of(context);
    final side = math
        .min(
          640.0,
          math.min(
            media.size.width - 32,
            media.size.height -
                media.viewInsets.bottom -
                media.padding.vertical -
                32,
          ),
        )
        .clamp(160.0, 640.0)
        .toDouble();
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: SizedBox(
        key: const ValueKey('account-square'),
        width: side,
        height: side,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Padding(
              padding: EdgeInsets.all(20),
              child: AppText(
                'My account',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 12,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const CircleAvatar(
                        child: Icon(Icons.person_outline),
                      ),
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
                    const Divider(height: 32),
                    const AppText(
                      'Change password',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Form(
                      key: form,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TextFormField(
                            controller: current,
                            obscureText: true,
                            enabled: !busy,
                            decoration: InputDecoration(
                              labelText: tr('Current password'),
                            ),
                            validator: (v) =>
                                v == null || v.isEmpty ? 'Required' : null,
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
                            validator: (v) => v != next.text
                                ? 'Passwords do not match'
                                : null,
                          ),
                          const SizedBox(height: 16),
                          FilledButton(
                            onPressed: busy ? null : changePassword,
                            child: AppText(
                              busy ? 'Saving…' : 'Change password',
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(
                          error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                    if (message != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(message!),
                      ),
                    if ((user['role'] == 'owner' ||
                            usesSectionPermissions(user)) &&
                        (hasSection(user, 'isp_card') ||
                            hasSection(user, 'noc'))) ...[
                      const Divider(height: 40),
                      Sas4Connection(api: widget.api),
                      if (hasSection(user, 'isp_card')) ...[
                        const Divider(height: 32),
                        PaymentSettings(api: widget.api),
                      ],
                    ],
                  ],
                ),
              ),
            ),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: busy ? null : () => Navigator.pop(context),
                  child: const AppText('Done'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
