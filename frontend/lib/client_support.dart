import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/link.dart';
import 'app_language.dart';
import 'branding.dart';
import 'client_dashboard_style.dart';

class ClientSupport extends StatelessWidget {
  const ClientSupport({super.key});

  Widget contact(BuildContext context, String phone, String label) {
    final international = '964${phone.substring(1)}';
    return ClientGlass(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.headset_mic_outlined, color: clientCyan, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: AppText(
                  label,
                  style: TextStyle(
                    color: clientMuted,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              IconButton(
                tooltip: tr('Copy phone number'),
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: phone));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: AppText('Phone number copied')),
                    );
                  }
                },
                icon: Icon(Icons.copy_rounded, size: 18, color: clientMuted),
              ),
            ],
          ),
          const SizedBox(height: 8),
          SelectableText(
            phone,
            textDirection: TextDirection.ltr,
            style: TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w700,
              letterSpacing: .4,
            ),
          ),
          const SizedBox(height: 6),
          AppText(
            'Choose how to reach us',
            style: TextStyle(color: clientMuted),
          ),
          const SizedBox(height: 20),
          LayoutBuilder(
            builder: (context, constraints) => Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final action in [
                  (
                    'Call',
                    Icons.call_outlined,
                    clientCyan,
                    Uri.parse('tel:+$international'),
                  ),
                  (
                    'WhatsApp',
                    Icons.chat_outlined,
                    clientColor(0xff64e8a0, 0xff087848),
                    Uri.https('wa.me', '/$international'),
                  ),
                  (
                    'Viber',
                    Icons.phone_in_talk_outlined,
                    clientColor(0xffc1a4ff, 0xff6c3ab5),
                    Uri(
                      scheme: 'viber',
                      host: 'chat',
                      queryParameters: {'number': '+$international'},
                    ),
                  ),
                ])
                  SizedBox(
                    width: MediaQuery.textScalerOf(context).scale(14) > 18
                        ? constraints.maxWidth
                        : (constraints.maxWidth - 16) / 3,
                    child: Link(
                      uri: action.$4,
                      target: action.$1 == 'WhatsApp'
                          ? LinkTarget.blank
                          : LinkTarget.self,
                      builder: (context, followLink) => FilledButton(
                        style: FilledButton.styleFrom(
                          foregroundColor: action.$3,
                          backgroundColor: action.$3.withValues(alpha: .10),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 14,
                          ),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                            side: BorderSide(
                              color: action.$3.withValues(alpha: .25),
                            ),
                          ),
                        ),
                        onPressed: followLink,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(action.$2, size: 23),
                            const SizedBox(height: 8),
                            AppText(
                              action.$1,
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    key: const PageStorageKey('client-about'),
    physics: const AlwaysScrollableScrollPhysics(),
    padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 960),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.all(26),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(28),
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    clientColor(0xff164f7b, 0xffd5edff),
                    clientColor(0xff132a50, 0xffe5efff),
                    clientColor(0xff101f36, 0xfff1f6ff),
                  ],
                ),
                border: Border.all(color: clientColor(0xff30638a, 0xffb7d2ec)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: clientCyan.withValues(alpha: .12),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Icon(
                      Icons.support_agent_rounded,
                      color: clientCyan,
                      size: 32,
                    ),
                  ),
                  const SizedBox(height: 20),
                  AppText(
                    'AIRLINK SUPPORT',
                    style: TextStyle(
                      color: clientCyan,
                      fontSize: 11,
                      letterSpacing: 2,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 8),
                  AppText(
                    'NOC Center',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 10),
                  AppText(
                    'Let’s get you connected.',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 6),
                  AppText(
                    'Contact our team for internet, recharge, and account support.',
                    style: TextStyle(color: clientMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            LayoutBuilder(
              builder: (context, constraints) {
                final first = contact(
                  context,
                  '07501033002',
                  'Support line 01',
                );
                final second = contact(
                  context,
                  '07501033004',
                  'Support line 02',
                );
                return constraints.maxWidth >= 700
                    ? Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(child: first),
                          const SizedBox(width: 16),
                          Expanded(child: second),
                        ],
                      )
                    : Column(
                        children: [first, const SizedBox(height: 16), second],
                      );
              },
            ),
            const SizedBox(height: 30),
            const Center(child: AirLinkLogo(width: 140)),
            const SizedBox(height: 8),
            AppText(
              'Telecommunication company',
              textAlign: TextAlign.center,
              style: TextStyle(color: clientMuted, fontSize: 12),
            ),
          ],
        ),
      ),
    ),
  );
}
