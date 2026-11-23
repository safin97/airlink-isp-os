import 'package:flutter/material.dart';
import 'main.dart' show AirLinkApp;
import 'mobile_session.dart';
import 'package:http/http.dart' as http;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  const configured = String.fromEnvironment('API_BASE');
  final saved = configured.isNotEmpty
      ? configured
      : await mobileSecrets.read(key: 'airlink.server');
  if (saved != null) {
    try {
      mobileServer = validateMobileServer(saved);
    } on FormatException {
      /* Show setup. */
    }
  }
  runApp(const MobileAirLink());
}

class MobileAirLink extends StatefulWidget {
  const MobileAirLink({super.key});
  @override
  State<MobileAirLink> createState() => _MobileAirLinkState();
}

class _MobileAirLinkState extends State<MobileAirLink> {
  final server = TextEditingController();
  String? error;
  bool saving = false;
  @override
  void dispose() {
    server.dispose();
    super.dispose();
  }

  Future<void> connect() async {
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final value = validateMobileServer(server.text);
      final response = await http
          .get(Uri.parse('$value/api/health'))
          .timeout(const Duration(seconds: 12));
      if (response.statusCode != 200) {
        throw Exception(
          'AirLink health check failed. Check the server address.',
        );
      }
      await mobileSecrets.write(key: 'airlink.server', value: value);
      if (mounted) setState(() => mobileServer = value);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (mobileServer != null) return const AirLinkApp();
    return AirLinkApp(
      home: Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 480),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.router_outlined, size: 64),
                    const SizedBox(height: 16),
                    const Text(
                      'Connect to AirLink',
                      style: TextStyle(fontSize: 26),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'Use the HTTPS address of your AirLink server. Sign in with your existing AirLink owner account to manage TTLock.',
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: server,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'AirLink server',
                        hintText: 'https://airlink.example.com',
                      ),
                    ),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text(error!),
                      ),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: saving ? null : connect,
                      child: const Text('Continue'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
