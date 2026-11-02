import 'dart:js_interop';
import 'package:web/web.dart' as web;

Future<void> enterFullscreen() async {
  try {
    if (web.document.fullscreenElement == null &&
        web.document.fullscreenEnabled) {
      await web.document.documentElement?.requestFullscreen().toDart;
    }
  } catch (_) {
    // Keep the NOC-only layout when the browser denies fullscreen.
  }
}

Future<void> leaveFullscreen() async {
  try {
    if (web.document.fullscreenElement != null) {
      await web.document.exitFullscreen().toDart;
    }
  } catch (_) {
    // The browser may have already exited with Escape.
  }
}

void Function() watchFullscreen({
  required void Function(bool) changed,
  required bool Function() nocActive,
  required void Function() toggle,
}) {
  final onChange = ((web.Event event) {
    changed(web.document.fullscreenElement != null);
  }).toJS;
  final onKey = ((web.Event event) {
    final key = event as web.KeyboardEvent;
    if (nocActive() && key.code == 'F12') {
      key.preventDefault();
      key.stopImmediatePropagation();
      if (!key.repeat) toggle();
    }
  }).toJS;
  web.document.addEventListener('fullscreenchange', onChange);
  web.window.addEventListener('keydown', onKey, true.toJS);
  return () {
    web.document.removeEventListener('fullscreenchange', onChange);
    web.window.removeEventListener('keydown', onKey, true.toJS);
  };
}
