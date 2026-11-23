import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

const ttBlue = Color(0xff0866f5),
    ttNavy = Color(0xff101828),
    ttGreen = Color(0xff12b76a),
    ttAmber = Color(0xfff79009),
    ttRed = Color(0xfff04438);
Color ttSurface(BuildContext c) => Theme.of(c).brightness == Brightness.dark
    ? const Color(0xff172235)
    : Colors.white;
Color ttMuted(BuildContext c) => Theme.of(c).brightness == Brightness.dark
    ? const Color(0xffa0afc3)
    : const Color(0xff667085);
String ttDate(dynamic value) {
  DateTime? date;
  if (value is int && value > 0) {
    date = DateTime.fromMillisecondsSinceEpoch(
      value < 100000000000 ? value * 1000 : value,
    );
  }
  if (value is String) date = DateTime.tryParse(value);
  if (date == null) return 'Not reported';
  final d = date.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)} · ${two(d.hour)}:${two(d.minute)}';
}

class TTTheme extends StatelessWidget {
  final Widget child;
  const TTTheme({super.key, required this.child});
  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context), dark = base.brightness == Brightness.dark;
    final scheme =
        ColorScheme.fromSeed(
          seedColor: ttBlue,
          brightness: base.brightness,
        ).copyWith(
          primary: dark ? const Color(0xff73aaff) : ttBlue,
          surface: dark ? const Color(0xff172235) : Colors.white,
          error: ttRed,
        );
    return Theme(
      data: base.copyWith(
        colorScheme: scheme,
        scaffoldBackgroundColor: dark
            ? const Color(0xff0c1423)
            : const Color(0xfff5f8fe),
        textTheme: base.textTheme.apply(
          bodyColor: dark ? const Color(0xffedf2fa) : ttNavy,
          displayColor: dark ? const Color(0xffedf2fa) : ttNavy,
        ),
        appBarTheme: AppBarTheme(
          backgroundColor: scheme.surface,
          foregroundColor: scheme.onSurface,
          elevation: 0,
        ),
        cardTheme: CardThemeData(
          color: scheme.surface,
          elevation: 0,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: scheme.surface,
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 16,
          ),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide(color: scheme.outlineVariant),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide(color: scheme.outlineVariant),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide(color: scheme.primary, width: 2),
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            backgroundColor: ttBlue,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
        ),
      ),
      child: child,
    );
  }
}

class TTPanel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const TTPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(22),
  });
  @override
  Widget build(BuildContext context) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: ttSurface(context),
      borderRadius: BorderRadius.circular(22),
      border: Border.all(
        color: Theme.of(
          context,
        ).colorScheme.outlineVariant.withValues(alpha: .5),
      ),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: .025),
          blurRadius: 24,
          offset: const Offset(0, 8),
        ),
      ],
    ),
    child: child,
  );
}

class TTBadge extends StatelessWidget {
  final String text;
  final Color color;
  final IconData? icon;
  const TTBadge(this.text, {super.key, this.color = ttBlue, this.icon});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon ?? LucideIcons.circle, size: 12, color: color),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            text,
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );
}

class TTEmpty extends StatelessWidget {
  final String title, message;
  final IconData icon;
  final Widget? action;
  const TTEmpty({
    super.key,
    required this.title,
    required this.message,
    this.icon = LucideIcons.shieldCheck,
    this.action,
  });
  @override
  Widget build(BuildContext context) => TTPanel(
    child: Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: ttBlue.withValues(alpha: .07),
                shape: BoxShape.circle,
              ),
              child: Icon(
                icon,
                size: 32,
                color: Theme.of(context).colorScheme.primary,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Text(
                message,
                textAlign: TextAlign.center,
                style: TextStyle(color: ttMuted(context), height: 1.6),
              ),
            ),
            if (action != null) ...[const SizedBox(height: 20), action!],
          ],
        ),
      ),
    ),
  );
}

class TTLockIllustration extends StatelessWidget {
  final double size;
  const TTLockIllustration({super.key, this.size = 96});
  @override
  Widget build(BuildContext context) => SizedBox(
    width: size,
    height: size * 1.35,
    child: CustomPaint(painter: _LockPainter()),
  );
}

class _LockPainter extends CustomPainter {
  @override
  void paint(Canvas c, Size s) {
    final body = RRect.fromRectAndRadius(
      Rect.fromLTWH(s.width * .24, 0, s.width * .52, s.height),
      Radius.circular(s.width * .15),
    );
    c.drawShadow(
      Path()..addRRect(body),
      Colors.black.withValues(alpha: .25),
      8,
      false,
    );
    c.drawRRect(
      body,
      Paint()
        ..shader = const LinearGradient(
          colors: [Color(0xff43526a), Color(0xff101828)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ).createShader(body.outerRect),
    );
    c.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(
          s.width * .3,
          s.height * .06,
          s.width * .4,
          s.height * .37,
        ),
        const Radius.circular(8),
      ),
      Paint()..color = const Color(0xff081321),
    );
    for (var r = 0; r < 3; r++) {
      for (var col = 0; col < 3; col++) {
        c.drawCircle(
          Offset(s.width * (.39 + col * .11), s.height * (.15 + r * .09)),
          sizeDot(s),
          Paint()..color = const Color(0xffb1c9ec),
        );
      }
    }
    c.drawCircle(
      Offset(s.width * .5, s.height * .58),
      s.width * .13,
      Paint()..color = const Color(0xff60738f),
    );
    c.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(
          s.width * .43,
          s.height * .54,
          s.width * .54,
          s.height * .08,
        ),
        const Radius.circular(8),
      ),
      Paint()
        ..shader = const LinearGradient(
          colors: [Color(0xff91a5c1), Color(0xff4c607d)],
        ).createShader(body.outerRect),
    );
    c.drawCircle(
      Offset(s.width * .5, s.height * .83),
      s.width * .055,
      Paint()..color = ttBlue,
    );
  }

  double sizeDot(Size s) => s.width * .018;
  @override
  bool shouldRepaint(_LockPainter old) => false;
}

class TTBattery extends StatelessWidget {
  final int? value;
  const TTBattery(this.value, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = value == null
        ? ttMuted(context)
        : value! <= 20
        ? ttAmber
        : ttGreen;
    return Row(
      children: [
        Icon(
          value != null && value! <= 20
              ? LucideIcons.batteryLow
              : LucideIcons.battery,
          size: 18,
          color: color,
        ),
        const SizedBox(width: 8),
        Text(
          'Battery: ${value == null ? '—' : '$value%'}',
          style: TextStyle(fontSize: 12, color: ttMuted(context)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(5),
            child: LinearProgressIndicator(
              value: value == null ? 0 : value! / 100,
              minHeight: 5,
              color: color,
              backgroundColor: color.withValues(alpha: .12),
            ),
          ),
        ),
      ],
    );
  }
}

class TTSkeleton extends StatelessWidget {
  const TTSkeleton({super.key});
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Loading locks',
    child: TTPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final width in [130.0, 220.0, 180.0])
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: Container(
                width: width,
                height: 18,
                decoration: BoxDecoration(
                  color: ttMuted(context).withValues(alpha: .1),
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
            ),
          const LinearProgressIndicator(minHeight: 2),
        ],
      ),
    ),
  );
}
