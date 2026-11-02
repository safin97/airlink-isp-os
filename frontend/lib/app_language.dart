import 'package:flutter/material.dart';
import 'language_storage.dart';
import 'translations.dart';
import 'app_theme.dart';

enum AppLanguage {
  english('en', 'English'),
  badini('ku', 'کوردی (بادینی)'),
  arabic('ar', 'العربية');

  const AppLanguage(this.code, this.label);
  final String code;
  final String label;
  bool get rtl => this != english;
}

final appLanguage = ValueNotifier<AppLanguage>(
  AppLanguage.values.firstWhere(
    (language) => language.code == readLanguage(),
    orElse: () => AppLanguage.english,
  ),
);

void setAppLanguage(AppLanguage language) {
  writeLanguage(language.code);
  appLanguage.value = language;
}

/// Only use for UI copy. Names, credentials and API values stay untouched.
String tr(String text) {
  final language = appLanguage.value;
  if (language == AppLanguage.english) return text;
  return translations[text]?[language == AppLanguage.badini ? 0 : 1] ?? text;
}

/// Rebuild language and style without recreating controllers or loading data.
mixin LanguageRebuild<T extends StatefulWidget> on State<T> {
  @override
  void initState() {
    super.initState();
    appLanguage.addListener(_languageChanged);
    appThemeMode.addListener(_languageChanged);
  }

  void _languageChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    appLanguage.removeListener(_languageChanged);
    appThemeMode.removeListener(_languageChanged);
    super.dispose();
  }
}

class AppText extends StatelessWidget {
  const AppText(
    this.data, {
    super.key,
    this.style,
    this.textAlign,
    this.maxLines,
    this.overflow,
    this.softWrap,
    this.textDirection,
  });
  final String data;
  final TextStyle? style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;
  final bool? softWrap;
  final TextDirection? textDirection;

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<AppLanguage>(
    valueListenable: appLanguage,
    builder: (context, language, child) => Text(
      tr(data),
      style: style,
      textAlign: textAlign,
      maxLines: maxLines,
      overflow: overflow,
      softWrap: softWrap,
      textDirection: textDirection,
    ),
  );
}

class LanguageSelector extends StatelessWidget {
  const LanguageSelector({super.key});

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<AppLanguage>(
    valueListenable: appLanguage,
    builder: (context, language, child) => PopupMenuButton<AppLanguage>(
      key: const ValueKey('language-selector'),
      tooltip: tr('Language'),
      initialValue: language,
      onSelected: setAppLanguage,
      itemBuilder: (context) => AppLanguage.values
          .map(
            (item) => CheckedPopupMenuItem<AppLanguage>(
              value: item,
              checked: item == language,
              child: Text(
                item.label,
                textDirection: item.rtl ? TextDirection.rtl : TextDirection.ltr,
              ),
            ),
          )
          .toList(),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.language, size: 20),
            const SizedBox(width: 6),
            Text(
              MediaQuery.sizeOf(context).width < 600
                  ? switch (language) {
                      AppLanguage.english => 'EN',
                      AppLanguage.badini => 'کوردی',
                      AppLanguage.arabic => 'العربية',
                    }
                  : language.label,
              style: const TextStyle(fontSize: 13),
            ),
            const Icon(Icons.arrow_drop_down, size: 18),
          ],
        ),
      ),
    ),
  );
}

class ThemeToggle extends StatelessWidget {
  const ThemeToggle({super.key});

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([appThemeMode, appLanguage]),
    builder: (context, child) {
      final mode = appThemeMode.value;
      return IconButton(
        key: const ValueKey('theme-toggle'),
        tooltip: tr(mode == ThemeMode.dark ? 'Day style' : 'Night style'),
        icon: Icon(
          mode == ThemeMode.dark
              ? Icons.light_mode_outlined
              : Icons.dark_mode_outlined,
        ),
        onPressed: () => setAppTheme(
          mode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark,
        ),
      );
    },
  );
}
