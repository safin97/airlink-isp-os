import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;

Widget googleMapFrame(String url) => HtmlElementView.fromTagName(
  key: ValueKey(url),
  tagName: 'iframe',
  onElementCreated: (element) {
    final frame = element as web.HTMLIFrameElement;
    frame
      ..src = url
      ..title = 'AirLink tower location on Google Maps'
      ..allowFullscreen = true
      ..referrerPolicy = 'strict-origin-when-cross-origin';
    frame.style
      ..width = '100%'
      ..height = '100%'
      ..border = '0';
  },
);
