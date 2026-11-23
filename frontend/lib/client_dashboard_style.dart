import 'dart:ui';
import 'package:flutter/material.dart';
import 'app_theme.dart';

Color get clientNavy => themeColor(0xff061322, 0xfff1f6fc);
const clientBlue = Color(0xff3478ff);
Color get clientCyan => themeColor(0xff56e5ff, 0xff006c9c);
Color get clientMuted => themeColor(0xffa9bdd3, 0xff52677c);

Color clientColor(int dark, int light) => themeColor(dark, light);

ThemeData clientDashboardTheme() {
  final brightness = appThemeMode.value == ThemeMode.light
      ? Brightness.light
      : Brightness.dark;
  final scheme =
      ColorScheme.fromSeed(
        seedColor: clientBlue,
        brightness: brightness,
      ).copyWith(
        primary: clientCyan,
        onPrimary: clientColor(0xff052237, 0xffffffff),
        secondary: clientBlue,
        surface: clientColor(0xff10243a, 0xffffffff),
        onSurface: clientColor(0xffedf5ff, 0xff102a43),
        outline: clientColor(0xff48637e, 0xff8298ae),
      );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
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
      color: clientColor(0xff10243a, 0xffffffff),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(color: Color(0xff29435f)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: clientColor(0xff081b2e, 0xfff3f7fc),
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
    dividerColor: clientColor(0xff29435f, 0xffcddce9),
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
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              clientColor(0xe51a3551, 0xfaffffff),
              clientColor(0xe50b2035, 0xf2eaf3fc),
            ],
          ),
          border: Border.all(color: clientColor(0xff294b68, 0xffcfdfed)),
        ),
        child: child,
      ),
    ),
  );
}
