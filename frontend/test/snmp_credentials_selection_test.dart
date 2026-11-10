import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  Future<void> mount(
    WidgetTester tester, {
    String? existing,
    List<Option> profiles = const [],
    required Future<void> Function(Map<String, dynamic>) save,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ResourceDialog(
            title: 'Edit device',
            fields: [
              FieldSpec(
                'snmp_profile_id',
                'SNMP profile',
                kind: 'snmp_profile',
                options: profiles,
              ),
            ],
            initial: {'snmp_profile_id': existing},
            save: save,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('existing custom v2c credentials survive selecting v2 alias', (
    tester,
  ) async {
    Map<String, dynamic>? saved;
    await mount(
      tester,
      existing: 'private',
      profiles: const [
        Option('private', 'Private community', snmpVersion: '2c'),
      ],
      save: (data) async => saved = data,
    );
    expect(find.text('Private community'), findsOneWidget);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('SNMP v2').last);
    await tester.pumpAndSettle();
    expect(find.text('Private community'), findsOneWidget);
    expect(find.text('SNMP Community String'), findsNothing);
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved!['snmp_profile_id'], 'private');
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('v3 cannot save without matching credentials', (tester) async {
    var writes = 0;
    await mount(
      tester,
      profiles: const [Option('v1', 'Old v1', snmpVersion: '1')],
      save: (_) async {
        writes++;
      },
    );
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('SNMP v3').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('Add an SNMP v3 profile'), findsOneWidget);
    expect(find.text('Old v1'), findsNothing);
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(writes, 0);
    expect(find.text('Choose matching SNMP credentials'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('clear control can remove an existing profile', (tester) async {
    Map<String, dynamic>? saved;
    await mount(
      tester,
      existing: 'private',
      profiles: const [Option('private', 'Private v3', snmpVersion: '3')],
      save: (data) async => saved = data,
    );
    await tester.tap(find.byTooltip('Remove SNMP profile'));
    await tester.pumpAndSettle();
    expect(find.text('SNMP credentials'), findsNothing);
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved!['snmp_profile_id'], isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
