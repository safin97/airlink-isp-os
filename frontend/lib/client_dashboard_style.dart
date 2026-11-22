import 'dart:ui';
import 'package:flutter/material.dart';

const clientNavy = Color(0xff061322);
const clientBlue = Color(0xff3478ff);
const clientCyan = Color(0xff56e5ff);
const clientMuted = Color(0xffa9bdd3);

ThemeData clientDashboardTheme() {
  final scheme =
      ColorScheme.fromSeed(
        seedColor: clientBlue,
        brightness: Brightness.dark,
      ).copyWith(
        primary: clientCyan,
        onPrimary: const Color(0xff052237),
        secondary: clientBlue,
        surface: const Color(0xff10243a),
        onSurface: const Color(0xffedf5ff),
        outline: const Color(0xff48637e),
      );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    fontFamily: 'sans-serif',
    scaffoldBackgroundColor: clientNavy,
    textTheme: const TextTheme(
      headlineMedium: TextStyle(
        fontSize: 28,
        fontWeight: FontWeight.w700,
        letterSpacing: -.7,
      ),
      headlineSmall: TextStyle(
        fontSize: 24,
        fontWeight: FontWeight.w700,
        letterSpacing: -.4,
      ),
      titleLarge: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
      titleMedium: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      bodyLarge: TextStyle(fontSize: 16, height: 1.4),
      bodyMedium: TextStyle(fontSize: 14, height: 1.45),
      labelLarge: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
    ).apply(bodyColor: scheme.onSurface, displayColor: scheme.onSurface),
    cardTheme: CardThemeData(
      color: const Color(0xff10243a),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: const BorderSide(color: Color(0xff29435f)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xff081b2e),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
      contentPadding: const EdgeInsets.all(18),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    dividerColor: const Color(0xff29435f),
  );
}

class ClientGlass extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  const ClientGlass({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(22),
  });
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(26),
    child: BackdropFilter(
      filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
      child: Container(
        padding: padding,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(26),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xe51a3551), Color(0xe50b2035)],
          ),
          border: Border.all(color: const Color(0xff294b68)),
        ),
        child: child,
      ),
    ),
  );
}
