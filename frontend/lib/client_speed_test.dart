import 'dart:async';
import 'dart:math';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

/// Browser-to-Internet checks, deliberately separate from the authenticated API.
/// Public endpoints: https://github.com/cloudflare/speedtest
class ClientSpeedTest {
  final http.Client client;
  bool stopped = false;
  void Function(String, double)? onMeasurement;
  ClientSpeedTest({http.Client? client}) : client = client ?? http.Client();

  void close() {
    stopped = true;
    client.close();
  }

  Uri endpoint(String path, [int? bytes]) =>
      Uri.https('speed.cloudflare.com', path, {
        'airlink_test': DateTime.now().microsecondsSinceEpoch.toString(),
        if (bytes != null) 'bytes': '$bytes',
      });

  Future<double> transfer(
    int bytes, {
    bool upload = false,
    void Function(double)? onProgress,
  }) async {
    if (stopped) throw StateError('Test stopped');
    final request = http.Request(
      upload ? 'POST' : 'GET',
      endpoint(upload ? '/__up' : '/__down', upload ? null : bytes),
    );
    request.followRedirects = false;
    if (upload) {
      final random = Random();
      final payload = Uint8List(bytes);
      for (var i = 0; i < bytes; i++) {
        payload[i] = random.nextInt(256);
      }
      request.bodyBytes = payload;
      request.headers['Content-Type'] = 'text/plain';
    }
    final clock = Stopwatch()..start();
    Future<void> perform() async {
      final response = await client.send(request);
      if (response.statusCode != 200) {
        throw StateError('Test server unavailable');
      }
      int received = 0;
      await for (final chunk in response.stream) {
        received += chunk.length;
        if (!upload && bytes > 0 && clock.elapsedMilliseconds >= 100) {
          onProgress?.call(received * 8 / clock.elapsedMicroseconds);
        }
        if (received > (upload ? 65536 : bytes)) {
          throw StateError('Unexpected test response');
        }
      }
      if (!upload && received != bytes) {
        throw StateError('Incomplete test response');
      }
    }

    try {
      await perform().timeout(const Duration(seconds: 12));
      if (stopped) throw StateError('Test stopped');
      return max(clock.elapsedMicroseconds / 1000000, 0.000001);
    } catch (_) {
      close();
      rethrow;
    }
  }

  Future<double> checkInternet() async => await transfer(0) * 1000;

  Future<Map<String, double>> run(void Function(String) progress) async {
    progress('Checking internet…');
    await checkInternet(); // Warm up the connection before measuring latency.
    final latency = <double>[];
    for (var i = 0; i < 6; i++) {
      latency.add(await checkInternet());
    }
    final jitter =
        [
          for (var i = 1; i < latency.length; i++)
            (latency[i] - latency[i - 1]).abs(),
        ].reduce((a, b) => a + b) /
        (latency.length - 1);
    latency.sort();
    final ping = (latency[2] + latency[3]) / 2;
    onMeasurement?.call('latency_ms', ping);
    onMeasurement?.call('jitter_ms', jitter);
    Future<double> bandwidth(bool upload) async {
      progress(upload ? 'Testing upload…' : 'Testing download…');
      final sampleBytes = upload ? 250000 : 1000000;
      final sampleSeconds = await transfer(sampleBytes, upload: upload);
      final bytes = (sampleBytes / sampleSeconds * 2).round().clamp(
        sampleBytes,
        upload ? 8000000 : 16000000,
      );
      final seconds = await transfer(
        bytes,
        upload: upload,
        onProgress: (speed) => onMeasurement?.call('download_mbps', speed),
      );
      final speed = bytes * 8 / seconds / 1000000;
      onMeasurement?.call(upload ? 'upload_mbps' : 'download_mbps', speed);
      return speed;
    }

    final download = await bandwidth(false);
    final upload = await bandwidth(true);
    return {
      'latency_ms': ping,
      'jitter_ms': jitter,
      'download_mbps': download,
      'upload_mbps': upload,
    };
  }
}
