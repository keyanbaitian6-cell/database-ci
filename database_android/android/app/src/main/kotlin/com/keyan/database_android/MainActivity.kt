package com.keyan.database_android

import android.content.Intent
import android.net.Uri
import android.content.ComponentName
import android.os.Build
import android.provider.Settings
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "database/share"
    private val backupSaver by lazy { BackupDocumentSaver(this) }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (!backupSaver.onActivityResult(requestCode, resultCode, data)) {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }

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
        // 取り込み画面の内部ブラウザで YouTube への要求を外へ出さない（YouTubeRequestBlocker.kt）。
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "database/web_requests")
            .setMethodCallHandler(YouTubeRequestBlocker(flutterEngine)::handle)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "database/backup_destination")
            .setMethodCallHandler(backupSaver::handle)
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
        // ジャグラーオンラインの取込（お試し、JUGGLER_ONLINE.md）：撮った画面の一覧・削除・設定画面を開く。
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "database/juggler").setMethodCallHandler { call, result ->
            when (call.method) {
                "status" -> {
                    val component = ComponentName(this, JugglerCaptureService::class.java).flattenToString()
                    val enabled = (Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
                        .split(':').any { it.equals(component, ignoreCase = true) }
                    result.success(mapOf(
                        "enabled" to enabled,
                        "sdk" to Build.VERSION.SDK_INT,
                        "captures" to JugglerCaptureService.captures(this).map { it.absolutePath },
                    ))
                }
                "openSettings" -> {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    result.success(null)
                }
                "delete" -> {
                    val folder = JugglerCaptureService.folder(this).canonicalFile
                    val paths = (call.arguments as? List<*>)?.filterIsInstance<String>() ?: emptyList()
                    var deleted = 0
                    for (path in paths) {
                        val file = java.io.File(path).canonicalFile
                        // 撮った画面のフォルダの中だけ消す。
                        if (file.parentFile == folder && file.name.endsWith(".png") && file.delete()) deleted++
                    }
                    result.success(deleted)
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
                        // 0時の自動取り込みの予約を待つ間（P’s CUBE、2026-10-26）。常駐サービスは起こさず、
                        // 画面だけ消さずに暗くする（Android 15以降の常駐の1日6時間を待ち時間で使わない）。
                        "keepScreen" -> {
                            keepScreenOnDimmed(call.argument<Boolean>("on") == true)
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
