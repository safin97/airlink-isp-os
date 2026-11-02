import 'app_language.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';
import 'tower_marker.dart';

const zakhoCenter = LatLng(37.1436, 42.6819);

class NetworkMap extends StatefulWidget {
  final List<dynamic> towers;
  final bool expanded;
  final VoidCallback toggleExpanded;
  final ValueChanged<String> openDevices;
  final TileProvider? tileProvider;
  const NetworkMap({
    super.key,
    required this.towers,
    required this.expanded,
    required this.toggleExpanded,
    required this.openDevices,
    this.tileProvider,
  });

  @override
  State<NetworkMap> createState() => _NetworkMapState();
}

class _NetworkMapState extends State<NetworkMap> with LanguageRebuild {
  final controller = MapController();
  bool ready = false;

  List<dynamic> located(List<dynamic> towers) => towers.where((t) {
    final lat = t['latitude'];
    final lon = t['longitude'];
    return lat is num &&
        lon is num &&
        lat.isFinite &&
        lon.isFinite &&
        lat >= -85.0511 &&
        lat <= 85.0511 &&
        lon >= -180 &&
        lon <= 180;
  }).toList();

  LatLng point(dynamic tower) => LatLng(
    (tower['latitude'] as num).toDouble(),
    (tower['longitude'] as num).toDouble(),
  );

  CameraFit? fit(List<dynamic> towers) => towers.isEmpty
      ? null
      : CameraFit.coordinates(
          coordinates: towers.map(point).toList(),
          padding: const EdgeInsets.fromLTRB(90, 110, 90, 65),
          maxZoom: 15,
        );

  void fitAll() {
    if (!ready) return;
    controller.rotate(0);
    final cameraFit = fit(located(widget.towers));
    if (cameraFit == null) {
      controller.move(zakhoCenter, 13);
    } else {
      controller.fitCamera(cameraFit);
    }
  }

  String positions(List<dynamic> towers) => located(
    towers,
  ).map((t) => '${t['id']}:${t['latitude']}:${t['longitude']}').join('|');

  @override
  void didUpdateWidget(NetworkMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (positions(oldWidget.towers) != positions(widget.towers) ||
        oldWidget.expanded != widget.expanded) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) fitAll();
      });
    }
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Color statusColor(dynamic status) => switch (status) {
    'online' => const Color(0xff34d399),
    'offline' => const Color(0xffff7385),
    'warning' => const Color(0xffffb454),
    _ => const Color(0xff99acc6),
  };

  @override
  Widget build(BuildContext context) {
    final towers = located(widget.towers);
    final missing = widget.towers.length - towers.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Wrap(
            spacing: 12,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Chip(
                avatar: Icon(Icons.layers_outlined, size: 18),
                label: AppText('Map type: Default'),
              ),
              Text(
                '${towers.length} ${towers.length == 1 ? 'tower' : 'towers'} on map',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              if (missing > 0)
                Text(
                  '$missing without GPS',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              TextButton.icon(
                onPressed: fitAll,
                icon: const Icon(Icons.fit_screen),
                label: const AppText('Fit all towers'),
              ),
              TextButton.icon(
                onPressed: () {
                  if (ready) controller.move(zakhoCenter, 13);
                },
                icon: const Icon(Icons.location_city_outlined),
                label: const AppText('Zakho'),
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
          child: Stack(
            children: [
              FlutterMap(
                mapController: controller,
                options: MapOptions(
                  initialCenter: zakhoCenter,
                  initialZoom: 13,
                  initialCameraFit: fit(towers),
                  minZoom: 2,
                  maxZoom: 19,
                  backgroundColor: const Color(0xffe8edf2),
                  onMapReady: () => ready = true,
                  interactionOptions: const InteractionOptions(
                    flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
                  ),
                ),
                children: [
                  TileLayer(
                    urlTemplate:
                        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                    userAgentPackageName: 'com.airlink.isp_os',
                    tileProvider: widget.tileProvider,
                    maxNativeZoom: 19,
                  ),
                  MarkerLayer(
                    markers: towers
                        .map(
                          (tower) => Marker(
                            key: ValueKey('map-tower-${tower['id']}'),
                            point: point(tower),
                            width: 156,
                            height: 96,
                            alignment: Alignment.topCenter,
                            child: Semantics(
                              button: true,
                              label:
                                  '${tower['name']}, ${tower['status'] ?? 'unknown'}. Open tower devices',
                              child: Tooltip(
                                message:
                                    '${tower['name']} • ${tower['status'] ?? 'unknown'}',
                                child: GestureDetector(
                                  behavior: HitTestBehavior.opaque,
                                  onTap: () => widget.openDevices(tower['id']),
                                  child: MouseRegion(
                                    cursor: SystemMouseCursors.click,
                                    child: Column(
                                      mainAxisAlignment: MainAxisAlignment.end,
                                      children: [
                                        Container(
                                          constraints: const BoxConstraints(
                                            maxWidth: 150,
                                          ),
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 10,
                                            vertical: 4,
                                          ),
                                          decoration: BoxDecoration(
                                            color: const Color(0xff10233d),
                                            borderRadius: BorderRadius.circular(
                                              6,
                                            ),
                                            border: Border.all(
                                              color: Colors.white.withValues(
                                                alpha: .8,
                                              ),
                                            ),
                                          ),
                                          child: Text(
                                            tower['name'],
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(
                                              color: Colors.white,
                                              fontSize: 12,
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(height: 2),
                                        TowerMarker(
                                          statusColor: statusColor(
                                            tower['status'],
                                          ),
                                          size: 48,
                                          mapPin: true,
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        )
                        .toList(),
                  ),
                  Align(
                    alignment: Alignment.bottomRight,
                    child: SafeArea(
                      child: Material(
                        color: Theme.of(context).colorScheme.surface,
                        child: InkWell(
                          onTap: () => launchUrl(
                            Uri.parse(
                              'https://www.openstreetmap.org/copyright',
                            ),
                          ),
                          child: const Padding(
                            padding: EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 3,
                            ),
                            child: AppText(
                              '© OpenStreetMap contributors',
                              style: TextStyle(fontSize: 11),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              Positioned(
                right: 16,
                top: 16,
                child: Material(
                  elevation: 4,
                  color: Theme.of(context).colorScheme.surface,
                  borderRadius: BorderRadius.circular(12),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: 'Zoom in',
                        icon: const Icon(Icons.add),
                        onPressed: () {
                          if (ready) {
                            controller.move(
                              controller.camera.center,
                              (controller.camera.zoom + 1).clamp(2, 19),
                            );
                          }
                        },
                      ),
                      IconButton(
                        tooltip: 'Zoom out',
                        icon: const Icon(Icons.remove),
                        onPressed: () {
                          if (ready) {
                            controller.move(
                              controller.camera.center,
                              (controller.camera.zoom - 1).clamp(2, 19),
                            );
                          }
                        },
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
