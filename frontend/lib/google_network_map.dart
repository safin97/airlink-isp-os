import 'package:flutter/material.dart';
import 'google_map_frame.dart';
import 'tower_map_view.dart';

class GoogleNetworkMap extends StatefulWidget {
  final List<dynamic> towers;
  final bool expanded;
  final VoidCallback toggleExpanded;
  final VoidCallback openTopology;
  final ValueChanged<String> openDevices;
  const GoogleNetworkMap({
    super.key,
    required this.towers,
    required this.expanded,
    required this.toggleExpanded,
    required this.openTopology,
    required this.openDevices,
  });

  @override
  State<GoogleNetworkMap> createState() => _GoogleNetworkMapState();
}

class _GoogleNetworkMapState extends State<GoogleNetworkMap> {
  int fitRevision = 0;

  @override
  Widget build(BuildContext context) {
    final located = widget.towers
        .where((t) => t['latitude'] != null && t['longitude'] != null)
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (located.isNotEmpty)
                TextButton.icon(
                  onPressed: () => setState(() => fitRevision++),
                  icon: const Icon(Icons.fit_screen),
                  label: const Text('Fit all towers'),
                ),
              TextButton.icon(
                onPressed: widget.toggleExpanded,
                icon: Icon(
                  widget.expanded ? Icons.fullscreen_exit : Icons.fullscreen,
                ),
                label: Text(widget.expanded ? 'Show sidebar' : 'Expand map'),
              ),
            ],
          ),
        ),
        Expanded(
          child: KeyedSubtree(
            key: ValueKey(fitRevision),
            child: LayoutBuilder(
              builder: (context, constraints) => googleMapFrame(
                towerMapUrl(
                  located,
                  null,
                  constraints.maxWidth,
                  constraints.maxHeight,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
