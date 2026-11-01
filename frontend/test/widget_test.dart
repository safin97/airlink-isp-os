import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets('Login uses actual API and shows authentication failures', (tester) async {
    final api=Api(client:MockClient((r) async=>http.Response('{"detail":"Invalid username or password"}',401,headers:{'content-type':'application/json'})));
    await tester.pumpWidget(MaterialApp(home:LoginView(api:api,initialized:true,done:(){})));
    await tester.enterText(find.byType(TextField).at(0),'owner');
    await tester.enterText(find.byType(TextField).at(1),'bad-password');
    await tester.tap(find.widgetWithText(FilledButton,'Sign in'));
    await tester.pumpAndSettle();
    expect(find.text('Invalid username or password'),findsOneWidget);
    expect(api.token,isNull);
  });
  testWidgets('Setup requires confirmation and local initialization token', (tester) async {
    await tester.pumpWidget(MaterialApp(home:LoginView(api:Api(),initialized:false,done:(){})));
    expect(find.text('Local setup token'),findsOneWidget);
    expect(find.text('Confirm password'),findsOneWidget);
  });
  test('API preserves explicit unavailable telemetry', () async {
    final api=Api(client:MockClient((r) async=>http.Response('{"availability_24h":null,"connected_clients":null}',200,headers:{'content-type':'application/json'})));
    final data=await api.request('/dashboard');
    expect(data['availability_24h'],isNull);
    expect(data['connected_clients'],isNull);
  });
}
