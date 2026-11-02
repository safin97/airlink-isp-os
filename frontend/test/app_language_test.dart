import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/app_language.dart';
import 'package:airlink_isp_os/app_theme.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/translations.dart';

void main() {
  tearDown(() {
    setAppLanguage(AppLanguage.english);
    setAppTheme(ThemeMode.dark);
  });

  test('Both languages have nonempty translations for every UI key', () {
    for (final entry in translations.entries) {
      expect(entry.value.length, 2, reason: entry.key);
      expect(entry.value.every((value) => value.trim().isNotEmpty), isTrue);
    }
  });

  for (final width in [390.0, 1280.0]) {
    testWidgets('Dashboard changes language without reloading data at $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var requests = 0;
      final api = Api(
        client: MockClient((request) async {
          requests++;
          return http.Response(
            jsonEncode(
              request.url.path == '/api/dashboard' ? <String, dynamic>{} : [],
            ),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      )..user = {'username': 'viewer', 'role': 'viewer'};
      await tester.pumpWidget(
        AirLinkApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      final initialRequests = requests;
      for (final language in [AppLanguage.badini, AppLanguage.arabic]) {
        setAppLanguage(language);
        await tester.pumpAndSettle();
        expect(find.text(tr('Dashboard')), findsWidgets);
        expect(find.text(tr('PC performance')), findsOneWidget);
        await tester.tap(find.byKey(const ValueKey('theme-toggle')));
        await tester.pumpAndSettle();
        expect(
          Theme.of(
            tester.element(find.byKey(const ValueKey('theme-toggle'))),
          ).brightness,
          appThemeMode.value == ThemeMode.light
              ? Brightness.light
              : Brightness.dark,
        );
        expect(requests, initialRequests);
        expect(
          tester.getCenter(find.byKey(const ValueKey('language-selector'))).dx,
          greaterThan(width / 2),
        );
        expect(tester.takeException(), isNull);
      }
      await tester.pumpWidget(const SizedBox());
    });
    testWidgets(
      'Language menu preserves login drafts and stays right at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          AirLinkApp(
            home: LoginView(api: Api(), initialized: true, done: () {}),
          ),
        );
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField).first, 'owner-123');
        await tester.enterText(find.byType(TextField).last, 'draft-password');

        for (final language in [
          AppLanguage.arabic,
          AppLanguage.badini,
          AppLanguage.english,
        ]) {
          await tester.tap(find.byKey(const ValueKey('language-selector')));
          await tester.pumpAndSettle();
          await tester.tap(
            find.widgetWithText(
              CheckedPopupMenuItem<AppLanguage>,
              language.label,
            ),
          );
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const ValueKey('theme-toggle')));
          await tester.pumpAndSettle();
          expect(
            Theme.of(tester.element(find.byType(TextField).first)).brightness,
            appThemeMode.value == ThemeMode.light
                ? Brightness.light
                : Brightness.dark,
          );
          expect(appLanguage.value, language);
          expect(find.text(tr('Sign in')), findsOneWidget);
          expect(find.text(tr('Username')), findsOneWidget);
          expect(
            Directionality.of(tester.element(find.byType(TextField).first)),
            language.rtl ? TextDirection.rtl : TextDirection.ltr,
          );
          expect(
            tester
                .widget<TextField>(find.byType(TextField).first)
                .controller!
                .text,
            'owner-123',
          );
          expect(
            tester
                .widget<TextField>(find.byType(TextField).last)
                .controller!
                .text,
            'draft-password',
          );
          expect(
            tester
                .getCenter(find.byKey(const ValueKey('language-selector')))
                .dx,
            greaterThan(width / 2),
          );
          expect(tester.takeException(), isNull);
        }
      },
    );
  }
}
