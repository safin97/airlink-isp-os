import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/client_slide_to_pay.dart';

void main() {
  testWidgets('only a completed thumb swipe confirms, once', (tester) async {
    var confirmations = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 244,
              child: ClientSlideToPay(onConfirmed: () => confirmations++),
            ),
          ),
        ),
      ),
    );
    final control = find.byType(ClientSlideToPay);
    final start = tester.getTopLeft(control) + const Offset(26, 30);
    await tester.tapAt(start + const Offset(190, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 0);
    await tester.dragFrom(start, const Offset(80, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 0);
    expect(tester.widget<Slider>(find.byType(Slider)).value, 0);
    final gesture = await tester.startGesture(start);
    await gesture.moveBy(const Offset(60, 0));
    await gesture.cancel();
    await tester.pumpAndSettle();
    expect(confirmations, 0);
    expect(tester.widget<Slider>(find.byType(Slider)).value, 0);
    await tester.dragFrom(start, const Offset(192, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 1);
    await tester.dragFrom(start, const Offset(192, 0));
    await tester.pumpAndSettle();
    expect(confirmations, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('disabled control cannot confirm', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Center(child: SizedBox(width: 244, child: ClientSlideToPay())),
        ),
      ),
    );
    final control = find.byType(ClientSlideToPay);
    await tester.dragFrom(
      tester.getTopLeft(control) + const Offset(26, 30),
      const Offset(192, 0),
    );
    await tester.pumpAndSettle();
    expect(tester.widget<Slider>(find.byType(Slider)).onChanged, isNull);
    expect(tester.widget<Slider>(find.byType(Slider)).value, 0);
  });

  testWidgets('keyboard users can progress right to confirmation in RTL too', (
    tester,
  ) async {
    var confirmations = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(
            body: Center(
              child: SizedBox(
                width: 244,
                child: ClientSlideToPay(onConfirmed: () => confirmations++),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.pump();
    for (var i = 0; i < 20; i++) {
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
      await tester.pump();
    }
    expect(confirmations, 1);
  });
}
