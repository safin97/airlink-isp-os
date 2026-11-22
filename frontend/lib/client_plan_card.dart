import 'package:flutter/material.dart';
import 'app_language.dart';
import 'branding.dart';

class ClientPlanCard extends StatelessWidget {
  final Map<String, dynamic> plan;
  final bool current;
  final VoidCallback? onRecharge;
  const ClientPlanCard({
    super.key,
    required this.plan,
    required this.current,
    this.onRecharge,
  });

  String amount(dynamic value) {
    final number = double.tryParse('$value');
    if (number == null || !number.isFinite) return '—';
    final text = number == number.roundToDouble()
        ? number.toStringAsFixed(0)
        : number.toStringAsFixed(2);
    final parts = text.split('.');
    parts[0] = parts[0].replaceAllMapped(
      RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
      (m) => '${m[1]},',
    );
    return parts.join('.');
  }

  @override
  Widget build(BuildContext context) {
    const colors = {
      'AirLink Basic': [Color(0xff163456), Color(0xff235a82)],
      'AirLink Plus': [Color(0xff11434c), Color(0xff167a79)],
      'AirLink Pro': [Color(0xff292b66), Color(0xff5251a2)],
      'AirLink Ultra': [Color(0xff432651), Color(0xff7d3d7f)],
      'AirLink Max': [Color(0xff423621), Color(0xff786039)],
    };
    final price = plan['price_iqd'];
    final maximum = plan['max_price_iqd'];
    final priceText = price == null
        ? tr('Price unavailable')
        : '${amount(price)}${maximum != null && double.tryParse('$maximum') != double.tryParse('$price') ? ' – ${amount(maximum)}' : ''} IQD';
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            constraints: const BoxConstraints(minHeight: 190),
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: colors[plan['name']] ?? colors['AirLink Basic']!,
              ),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Colors.white24),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const AirLinkLogo(width: 112),
                    const Spacer(),
                    const Icon(Icons.wifi, color: Colors.white70, size: 26),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  '${plan['name']}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  priceText,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 24,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  tr('Card price'),
                  style: const TextStyle(color: Colors.white70, fontSize: 14),
                ),
                if (current) ...[
                  const SizedBox(height: 12),
                  Text(
                    tr('Your current plan'),
                    style: const TextStyle(color: Colors.white, fontSize: 14),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 8),
          AppText(switch (plan['stock_status']) {
            'sold_out' => 'Currently out of stock',
            'no_cards' => 'No recharge cards listed yet',
            _ => 'Availability confirmed at checkout',
          }),
          ...[
            const SizedBox(height: 8),
            OutlinedButton(onPressed: onRecharge, child: const AppText('Pay')),
          ],
        ],
      ),
    );
  }
}
