import 'package:web/web.dart' as web;

String? readTheme() {
  try {
    return web.window.localStorage.getItem('airlink.theme');
  } catch (_) {
    return null;
  }
}

void writeTheme(String theme) {
  try {
    web.window.localStorage.setItem('airlink.theme', theme);
  } catch (_) {
    // Theme switching still works when browser storage is unavailable.
  }
}

String? readLanguage() {
  try {
    return web.window.localStorage.getItem('airlink.language');
  } catch (_) {
    return null;
  }
}

void writeLanguage(String code) {
  try {
    web.window.localStorage.setItem('airlink.language', code);
  } catch (_) {
    // Language switching still works when browser storage is disabled.
  }
}
