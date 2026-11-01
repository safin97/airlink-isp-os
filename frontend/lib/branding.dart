import 'package:flutter/material.dart';

/// The supplied artwork stays unmodified; its light backing preserves contrast.
class AirLinkLogo extends StatelessWidget {
  final double width;
  final bool stacked;
  const AirLinkLogo({super.key, this.width = 196, this.stacked = false});

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(12),
    child: ColoredBox(
      color: Colors.white,
      child: Image.asset(
        'assets/branding/airlink-${stacked ? 'stacked' : 'horizontal'}.png',
        width: width,
        height: width * (stacked ? 1131 / 1126 : 1168 / 2908),
        fit: BoxFit.contain,
        semanticLabel: 'AirLink — Telecommunication company',
        filterQuality: FilterQuality.high,
      ),
    ),
  );
}
