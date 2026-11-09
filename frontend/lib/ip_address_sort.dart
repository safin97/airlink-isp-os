List<int>? _addressBytes(String? address) {
  if (address == null || address.isEmpty) return null;
  try {
    return address.contains(':')
        ? Uri.parseIPv6Address(address)
        : Uri.parseIPv4Address(address);
  } on FormatException {
    return null;
  }
}

int compareIpAddresses(String? left, String? right) {
  final a = _addressBytes(left), b = _addressBytes(right);
  if (a == null || b == null) {
    if (a != null) return -1;
    if (b != null) return 1;
    return (left ?? '').compareTo(right ?? '');
  }
  if (a.length != b.length) return a.length.compareTo(b.length);
  for (var i = 0; i < a.length; i++) {
    final order = a[i].compareTo(b[i]);
    if (order != 0) return order;
  }
  return 0;
}
