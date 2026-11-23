import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/app_language.dart';
import 'package:airlink_isp_os/app_theme.dart';
import 'package:airlink_isp_os/client_portal.dart';
import 'package:airlink_isp_os/client_dashboard_style.dart';
import 'package:airlink_isp_os/client_slide_to_pay.dart';

void main() {
  tearDown(() {
    setAppLanguage(AppLanguage.english);
    setAppTheme(ThemeMode.dark);
  });
  for (final width in [320.0, 390.0, 1280.0]) {
    testWidgets(
      'client language and day/night controls preserve session at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var accountReads = 0;
        final api = Api(
          client: MockClient((request) async {
            if (request.url.path == '/api/client/account') {
              accountReads++;
              return http.Response(
                jsonEncode({
                  'username': 'subscriber-123',
                  'profile': 'AirLink Plus',
                  'profile_id': 98,
                  'expiration': '2027-12-01',
                  'recharge_cost': '25000',
                  'currency': 'IQD',
                  'payments': [],
                  'can_recharge': true,
                  'fib_configured': true,
                }),
                200,
              );
            }
            expect(request.url.path, '/api/client/cards');
            return http.Response(
              jsonEncode({
                'items': [
                  {
                    'profile_id': 98,
                    'name': 'AirLink Plus',
                    'price_iqd': '25000',
                  },
                ],
              }),
              200,
            );
          }),
        );
        await tester.pumpWidget(AirLinkApp(home: ClientPortal(api: api)));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byType(TextField));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField), 'DRAFT-PIN');
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.tap(find.byKey(const ValueKey('language-selector')));
        await tester.pumpAndSettle();
        await tester.tap(
          find.widgetWithText(
            CheckedPopupMenuItem<AppLanguage>,
            AppLanguage.badini.label,
          ),
        );
        await tester.pumpAndSettle();
        expect(appLanguage.value, AppLanguage.badini);
        expect(find.text('ب خێر هاتیەڤە'), findsOneWidget);
        expect(find.text('subscriber-123'), findsWidgets);
        expect(
          Directionality.of(tester.element(find.byType(TextField))),
          TextDirection.rtl,
        );
        expect(
          tester.widget<TextField>(find.byType(TextField)).controller!.text,
          'DRAFT-PIN',
        );
        await tester.tap(find.byKey(const ValueKey('theme-toggle')));
        await tester.pumpAndSettle();
        expect(appThemeMode.value, ThemeMode.light);
        expect(
          Theme.of(tester.element(find.byType(ClientGlass).first)).brightness,
          Brightness.light,
        );
        expect(
          tester.widget<TextField>(find.byType(TextField)).controller!.text,
          'DRAFT-PIN',
        );
        expect(accountReads, 1);
        await tester.tap(find.byType(NavigationDestination).at(2));
        await tester.pumpAndSettle();
        expect(find.text(tr('Slide to the right to pay')), findsOneWidget);
        expect(
          Directionality.of(
            tester.element(
              find.descendant(
                of: find.byType(ClientSlideToPay),
                matching: find.byType(Slider),
              ),
            ),
          ),
          TextDirection.ltr,
        );
        expect(find.text('AirLink Plus'), findsOneWidget);
        await tester.tap(find.byType(NavigationDestination).at(3));
        await tester.pumpAndSettle();
        expect(find.text(tr('NOC Center')), findsOneWidget);
        expect(find.text('07501033002'), findsOneWidget);
        expect(
          Theme.of(tester.element(find.byType(ClientGlass).first)).brightness,
          Brightness.light,
        );
        await tester.tap(find.byKey(const ValueKey('theme-toggle')));
        await tester.pumpAndSettle();
        expect(
          Theme.of(tester.element(find.byType(ClientGlass).first)).brightness,
          Brightness.dark,
        );
        expect(accountReads, 2); // Opening Packages refreshes the account.
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
}
