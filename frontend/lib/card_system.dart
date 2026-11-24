import 'section_access.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'app_language.dart';
import 'sas4_cards.dart';

class CardSystem extends StatefulWidget {
  final Api api;
  const CardSystem({super.key, required this.api});
  @override
  State<CardSystem> createState() => _CardSystemState();
}

class _CardSystemState extends State<CardSystem> with LanguageRebuild {
  bool saved = false;
  @override
  Widget build(BuildContext context) {
    if (!hasSection(widget.api.user ?? {}, 'card_system')) {
      return const AppText('Owner access required');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppText(
          'Card System',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          children: [
            ChoiceChip(
              label: const AppText('SAS4 Radius'),
              selected: !saved,
              onSelected: (_) => setState(() => saved = false),
            ),
            ChoiceChip(
              label: const AppText('Saved FIB PINs'),
              selected: saved,
              onSelected: (_) => setState(() => saved = true),
            ),
          ],
        ),
        const SizedBox(height: 20),
        if (saved)
          SavedCardInventory(api: widget.api)
        else
          Sas4Cards(api: widget.api),
      ],
    );
  }
}

class SavedCardInventory extends StatefulWidget {
  final Api api;
  const SavedCardInventory({super.key, required this.api});

  @override
  State<SavedCardInventory> createState() => _SavedCardInventoryState();
}

class _SavedCardInventoryState extends State<SavedCardInventory>
    with LanguageRebuild {
  final form = GlobalKey<FormState>();
  final label = TextEditingController();
  final pin = TextEditingController();
  final price = TextEditingController();
  int? profileId;
  List<dynamic> profiles = [];
  String? profilesError;
  List<dynamic> cards = [];
  int total = 0;
  int offset = 0;
  bool busy = false;
  bool showPin = false;
  String? error;
  bool get owner => hasSection(widget.api.user ?? {}, 'card_system');

  @override
  void initState() {
    super.initState();
    if (owner) load();
  }

  @override
  void dispose() {
    label.dispose();
    pin.dispose();
    price.dispose();
    super.dispose();
  }

  Future<void> fetch() async {
    final result = await widget.api.request('/card-system?offset=$offset');
    if (!mounted) return;
    setState(() {
      cards = result['items'] as List;
      total = result['total'] as int;
    });
    try {
      final result = await widget.api.request('/card-system/profiles');
      if (mounted) {
        setState(() {
          profiles = result as List;
          profilesError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => profilesError =
              'Profiles could not be loaded. Check your SAS4 connection and refresh.',
        );
      }
    }
  }

  Future<void> run(Future<void> Function() action) async {
    if (!owner || busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> load() => run(fetch);

  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    await run(() async {
      await widget.api.request(
        '/card-system',
        method: 'POST',
        body: {
          'label': label.text.trim(),
          'pin': pin.text.trim(),
          'profile_id': profileId,
          'price_iqd': profileId == null ? null : price.text.trim(),
        },
      );
      if (!mounted) return;
      label.clear();
      pin.clear();
      setState(() {
        showPin = false;
        offset = 0;
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: AppText('Card PIN saved')));
      await fetch();
    });
  }

  String? validatePrice(String? value) {
    final text = (value ?? '').trim();
    final amount = double.tryParse(text);
    return !RegExp(r'^[0-9]+(?:\.[0-9]{1,2})?$').hasMatch(text) ||
            amount == null ||
            !amount.isFinite ||
            amount <= 0 ||
            amount > 1000000000
        ? tr('Enter a positive card price in IQD (up to two decimal places).')
        : null;
  }

  Widget profilePicker(int? selected, ValueChanged<int?>? changed) =>
      DropdownButtonFormField<int>(
        key: ValueKey('card-profile-$selected'),
        initialValue: selected,
        isExpanded: true,
        decoration: InputDecoration(
          labelText: tr('SAS4 profile'),
          border: const OutlineInputBorder(),
        ),
        items: [
          const DropdownMenuItem<int>(
            value: null,
            child: AppText('Unassigned — manual PIN use only'),
          ),
          if (selected != null && !profiles.any((p) => p['id'] == selected))
            DropdownMenuItem(
              value: selected,
              child: Text('Profile #$selected'),
            ),
          for (final profile in profiles)
            DropdownMenuItem(
              value: profile['id'] as int,
              child: Text(profile['name'] as String),
            ),
        ],
        onChanged: changed,
      );

  Future<void> editProfile(Map card) async {
    final editPrice = TextEditingController(text: card['price_iqd'] ?? '');
    int? selected = card['profile_id'] as int?;
    final editForm = GlobalKey<FormState>();
    final route = DialogRoute<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const AppText('Card profile and price'),
          content: SizedBox(
            width: 440,
            child: Form(
              key: editForm,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (profilesError != null) Text(profilesError!),
                  profilePicker(
                    selected,
                    (value) => update(() => selected = value),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: editPrice,
                    enabled: selected != null,
                    decoration: InputDecoration(
                      labelText: tr('Card price (IQD)'),
                      border: const OutlineInputBorder(),
                    ),
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    validator: (value) =>
                        selected == null ? null : validatePrice(value),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const AppText('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                if (editForm.currentState!.validate()) {
                  Navigator.pop(context, <String, dynamic>{
                    'profile_id': selected,
                    'price_iqd': selected == null
                        ? null
                        : editPrice.text.trim(),
                  });
                }
              },
              child: const AppText('Save'),
            ),
          ],
        ),
      ),
    );
    final result = await Navigator.of(context).push(route);
    await route.completed;
    editPrice.dispose();
    if (result == null || !mounted) return;
    await run(() async {
      await widget.api.request(
        '/card-system/${card['id']}/profile',
        method: 'PUT',
        body: result,
      );
      await fetch();
    });
  }

  Future<void> copy(Map card) => run(() async {
    final path = card['state'] == 'issued'
        ? '/payments/orders/${card['payment_id']}/pin'
        : '/card-system/${card['id']}/pin';
    final result = await widget.api.request(path, method: 'POST');
    await Clipboard.setData(ClipboardData(text: result['pin'] as String));
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: AppText('PIN copied.')));
  });

  Future<void> remove(Map card) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppText('Remove saved card?'),
        content: const AppText('This removes the PIN from your saved cards.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await run(() async {
      await widget.api.request('/card-system/${card['id']}', method: 'DELETE');
      if (!mounted) return;
      if (cards.length == 1 && offset > 0) offset -= 50;
      await fetch();
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!owner) return const AppText('Owner access required');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppText(
          'Saved FIB PINs',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        const AppText('Save existing SAS4 recharge card PINs for later use.'),
        const SizedBox(height: 20),
        Card.outlined(
          margin: EdgeInsets.zero,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Form(
              key: form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  AppText(
                    'Add PIN code',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const ValueKey('saved-card-label'),
                    controller: label,
                    enabled: !busy,
                    maxLength: 120,
                    decoration: InputDecoration(
                      labelText: tr('Label (optional)'),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (profilesError != null) Text(profilesError!),
                  profilePicker(
                    profileId,
                    busy ? null : (value) => setState(() => profileId = value),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const ValueKey('saved-card-price'),
                    controller: price,
                    enabled: !busy && profileId != null,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(
                      labelText: tr('Card price (IQD)'),
                      helperText: tr(
                        'FIB customers pay this price for a card matching their profile.',
                      ),
                      border: const OutlineInputBorder(),
                    ),
                    validator: (value) =>
                        profileId == null ? null : validatePrice(value),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const ValueKey('saved-card-pin'),
                    controller: pin,
                    enabled: !busy,
                    obscureText: !showPin,
                    autocorrect: false,
                    enableSuggestions: false,
                    maxLength: 128,
                    textInputAction: TextInputAction.done,
                    decoration: InputDecoration(
                      labelText: tr('Card PIN'),
                      border: const OutlineInputBorder(),
                      suffixIcon: IconButton(
                        tooltip: tr(showPin ? 'Hide PIN' : 'Show PIN'),
                        onPressed: busy
                            ? null
                            : () => setState(() => showPin = !showPin),
                        icon: Icon(
                          showPin ? Icons.visibility_off : Icons.visibility,
                        ),
                      ),
                    ),
                    validator: (value) =>
                        value == null ||
                            value.trim().isEmpty ||
                            value.trim().runes.any((c) => c < 32)
                        ? tr('Enter the card PIN')
                        : null,
                    onFieldSubmitted: (_) => busy ? null : save(),
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed:
                        !canEditSection(widget.api.user ?? {}, 'card_system') ||
                            busy
                        ? null
                        : save,
                    icon: const Icon(Icons.add_card),
                    label: const AppText('Add PIN code'),
                  ),
                ],
              ),
            ),
          ),
        ),
        if (busy) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        const SizedBox(height: 24),
        Row(
          children: [
            Expanded(
              child: Text(
                '${tr('Saved cards')} ($total)',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            IconButton(
              tooltip: tr('Refresh'),
              onPressed: busy ? null : load,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        if (cards.isEmpty && !busy && error == null)
          const AppText('No saved cards yet. Add a PIN code above.'),
        for (final card in cards)
          Card.outlined(
            child: ListTile(
              leading: const Icon(Icons.credit_card_outlined),
              title: Text(
                (card['label'] as String).isEmpty
                    ? tr('Recharge card')
                    : card['label'],
              ),
              subtitle: Text(
                '•••••••• · ${card['state'] ?? 'available'}\n${card['profile_id'] == null ? tr('Profile and price not assigned') : '${profiles.where((p) => p['id'] == card['profile_id']).firstOrNull?['name'] ?? 'Profile #${card['profile_id']}'} · ${card['price_iqd']} IQD'}',
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    tooltip: tr('Card profile and price'),
                    onPressed: !canEditSection(widget.api.user ?? {}, 'card_system') || busy || card['state'] != 'available'
                        ? null
                        : () => editProfile(card),
                    icon: const Icon(Icons.edit_outlined),
                  ),
                  IconButton(
                    tooltip: tr('Copy PIN'),
                    onPressed:
                        busy || !['available', 'issued'].contains(card['state'])
                        ? null
                        : () => copy(card),
                    icon: const Icon(Icons.copy),
                  ),
                  IconButton(
                    tooltip: tr('Remove saved card'),
                    onPressed: !canDeleteSection(widget.api.user ?? {}, 'card_system') || busy || card['state'] != 'available'
                        ? null
                        : () => remove(card),
                    icon: const Icon(Icons.delete_outline),
                  ),
                ],
              ),
            ),
          ),
        if (total > 50)
          Wrap(
            spacing: 12,
            children: [
              TextButton(
                onPressed: busy || offset == 0
                    ? null
                    : () {
                        offset -= 50;
                        load();
                      },
                child: const AppText('Previous'),
              ),
              TextButton(
                onPressed: busy || offset + cards.length >= total
                    ? null
                    : () {
                        offset += 50;
                        load();
                      },
                child: const AppText('Next'),
              ),
            ],
          ),
      ],
    );
  }
}
