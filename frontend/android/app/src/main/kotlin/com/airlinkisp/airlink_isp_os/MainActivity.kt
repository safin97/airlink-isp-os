package com.airlinkisp.airlink_isp_os

import io.flutter.embedding.android.FlutterActivity
import com.ttlock.ttlock_flutter.TtlockFlutterPlugin

class MainActivity : FlutterActivity() {
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        (flutterEngine?.plugins?.get(TtlockFlutterPlugin::class.java) as? TtlockFlutterPlugin)
            ?.onRequestPermissionsResult(requestCode, permissions, grantResults)
    }
}
