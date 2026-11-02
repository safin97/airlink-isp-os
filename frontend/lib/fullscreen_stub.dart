Future<void> enterFullscreen() async {}
Future<void> leaveFullscreen() async {}
void Function() watchFullscreen({
  required void Function(bool) changed,
  required bool Function() nocActive,
  required void Function() toggle,
}) => () {};
