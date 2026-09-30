package com.keyan.database_android

import android.content.Intent
import android.net.Uri
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "database/share"
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "openUrl" -> {
                    val raw = call.arguments as? String
                    val uri = raw?.let(Uri::parse)
                    val allowed = uri?.scheme == "https" &&
                        uri.host == "meruhenworld.pt.teramoba2.com" &&
                        (uri.path?.startsWith("/nagamachiminami/") == true ||
                            uri.path?.startsWith("/saiwaichou/") == true)
                    if (!allowed) {
                        result.error("outside_scope", "対象外のページです。", null)
                    } else {
                        startActivity(Intent(Intent.ACTION_VIEW, uri))
                        result.success(null)
                    }
                }
                else -> result.notImplemented()
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "database/auto_capture")
            .setMethodCallHandler { call, result ->
                try {
                    when (call.method) {
                        "start" -> {
                            val service = Intent(this, AutoCaptureService::class.java)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                                startForegroundService(service)
                            } else {
                                startService(service)
                            }
                            result.success(null)
                        }
                        "stop" -> {
                            stopService(Intent(this, AutoCaptureService::class.java))
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (error: Exception) {
                    result.error("auto_capture_service", error.message ?: error.javaClass.simpleName, null)
                }
            }
    }
}
