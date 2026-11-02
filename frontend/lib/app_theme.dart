import 'package:flutter/material.dart';
import 'language_storage.dart';

final appThemeMode = ValueNotifier<ThemeMode>(
  readTheme() == 'light' ? ThemeMode.light : ThemeMode.dark,
);

void setAppTheme(ThemeMode mode) {
  writeTheme(mode == ThemeMode.light ? 'light' : 'dark');
  appThemeMode.value = mode;
}

Color themeColor(int dark, int light) =>
    Color(appThemeMode.value == ThemeMode.light ? light : dark);

ThemeData airLinkTheme(Brightness brightness) {
  final light = brightness == Brightness.light;
  final background = Color(light ? 0xfff2f5fa : 0xff071426);
  final surface = Color(light ? 0xffffffff : 0xff10233d);
  final scheme =
      ColorScheme.fromSeed(
        seedColor: const Color(0xff3454ff),
        brightness: brightness,
      ).copyWith(
        primary: Color(light ? 0xff2455ca : 0xff438fff),
        surface: surface,
        secondary: Color(light ? 0xff087f5b : 0xff34d399),
      );
  return ThemeData(
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    useMaterial3: true,
    fontFamily: 'sans-serif',
    dividerColor: Color(light ? 0xffd6dfeb : 0xff20334e),
    appBarTheme: AppBarTheme(
      backgroundColor: background,
      surfaceTintColor: Colors.transparent,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: background,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      contentPadding: const EdgeInsets.all(16),
    ),
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
      ),
    ),
  );
}
