package com.keyan.database_android

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "database/share"

    /**
     * 自動取り込みがONの間、このアプリの画面だけ消さずに暗くする（端末の設定は変えない）。
     * 画面が消えるとアプリ内のブラウザがページの読み込みを終えず「ON・読み込み待ち」で止まる
     * （2026-10-06 実機で確認：充電中でも同じ。画面をつけると読み込みが再開した）。
     * FLAG_KEEP_SCREEN_ON はこの画面が見えている間だけ効き、端末の「画面消灯までの時間」とは別に働く。
     * 明るさもこの画面だけの値で、OFFや画面を閉じたときに端末の明るさへ戻る。
     */
    private fun keepScreenOnDimmed(on: Boolean) {
        val attributes = window.attributes
        if (on) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            attributes.screenBrightness = 0.05f
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            attributes.screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        }
        window.attributes = attributes
    }
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
                            keepScreenOnDimmed(true)
                            result.success(null)
                        }
                        "stop" -> {
                            stopService(Intent(this, AutoCaptureService::class.java))
                            keepScreenOnDimmed(false)
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
