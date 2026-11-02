import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  for (final edit in [false, true]) {
    testWidgets('${edit ? 'edit' : 'add'} manager selects multiple places', (
      tester,
    ) async {
      Map<String, dynamic>? saved;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => ResourceDialog(
                    title: 'Manager',
                    fields: [
                      FieldSpec(
                        'role',
                        'Role',
                        initial: 'manager',
                        options: const [
                          Option('manager', 'Manager'),
                          Option('viewer', 'Viewer'),
                        ],
                      ),
                      FieldSpec(
                        'place_ids',
                        'Assigned places',
                        kind: 'multiselect',
                        initial: const <String>[],
                        options: const [
                          Option('north', 'North'),
                          Option('south', 'South'),
                        ],
                      ),
                    ],
                    initial: edit
                        ? {
                            'place_ids': ['north'],
                          }
                        : {},
                    save: (data) async {
                      saved = data;
                    },
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<CheckboxListTile>(
              find.widgetWithText(CheckboxListTile, 'North'),
            )
            .value,
        edit,
      );
      if (!edit) await tester.tap(find.text('North'));
      await tester.tap(find.text('South'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(saved!['place_ids'], ['north', 'south']);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'untouched assignments omitted and deselection saves empty list',
    (tester) async {
      for (final clear in [false, true]) {
        Map<String, dynamic>? saved;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: ResourceDialog(
                key: ValueKey(clear),
                title: 'Manager',
                fields: [
                  FieldSpec('role', 'Role', initial: 'manager'),
                  FieldSpec(
                    'place_ids',
                    'Assigned places',
                    kind: 'multiselect',
                    options: const [Option('north', 'North')],
                  ),
                ],
                initial: {
                  'place_ids': ['north'],
                },
                save: (data) async {
                  saved = data;
                },
              ),
            ),
          ),
        );
        if (clear) {
          await tester.tap(find.text('North'));
          await tester.pumpAndSettle();
        }
        await tester.tap(find.text('Save'));
        await tester.pumpAndSettle();
        expect(saved!.containsKey('place_ids'), clear);
        if (clear) expect(saved!['place_ids'], isEmpty);
        await tester.pumpWidget(const SizedBox());
      }
    },
  );
}
