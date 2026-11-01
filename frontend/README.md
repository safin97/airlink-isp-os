# AirLink dashboard

Flutter web client for the AirLink API. See the repository README for build and deployment instructions.

Run `flutter pub get`, `flutter analyze`, `flutter test`, then `flutter build web --release --no-web-resources-cdn`. The dependency resolution is recorded in `pubspec.lock`.

Production serves the client and `/api` from the same HTTPS origin. Access tokens stay in memory. Secure HttpOnly refresh cookies are managed by the server. `API_BASE` is a compile-time development override; it is empty for the appliance build.

Metrics and inventory come from the backend. Empty or unsupported metrics are explicitly unavailable. The only external dashboard resource is the OpenStreetMap tile service, which requires internet access and displays attribution. The dashboard itself and its renderer assets are included in the OS image.
