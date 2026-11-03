package com.keyan.database_android

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
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
    private fun keepScreenOnDimmed(on: Boolean, dim: Boolean = on) {
        val attributes = window.attributes
        if (on) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        attributes.screenBrightness =
            if (on && dim) 0.05f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        window.attributes = attributes
    }
    /** 通知の許可（Android 13以降）。自動取り込み・0時の予約をONにしたとき（利用者の操作のとき）だけ聞く。 */
    private fun requestResultNotices() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2103)
        }
    }

    /**
     * 自動取り込みの結果（完了・止まった理由）を通知で知らせる（2026-11-04、利用者が選んだ「朝の取り込み結果通知」）。
     * 常駐の通知（AutoCaptureService）とは別の通知で、常駐を止めた後も残る。同じ番号で出すので、最新の結果だけが残る。
     * 許可が無ければ出さずに false を返す（取り込みは止めない）。
     */
    private fun postResultNotice(title: String, text: String): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }
        val manager = getSystemService(NotificationManager::class.java)
        val channelId = "database_capture_result"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(channelId, "取り込みの結果", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        val open = PendingIntent.getActivity(
            this, 1, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, channelId)
        } else {
            Notification.Builder(this)
        }.setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        manager.notify(2102, notification)
        return true
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
        // ホーム画面のウィジェットへ、前回の取り込みの結果と翌日候補を渡す（2026-11-04）。
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "database/widget").setMethodCallHandler { call, result ->
            when (call.method) {
                "update" -> {
                    val values = (call.arguments as? Map<*, *>)
                        ?.entries
                        ?.mapNotNull { (k, v) -> if (k is String && v is String) k to v else null }
                        ?.toMap()
                        ?: emptyMap()
                    CaptureWidgetProvider.save(this, values)
                    result.success(null)
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
                        "requestNotices" -> {
                            requestResultNotices()
                            result.success(null)
                        }
                        "notify" -> result.success(
                            postResultNotice(
                                call.argument<String>("title") ?: "database",
                                call.argument<String>("text") ?: "",
                            )
                        )
                        // 0時の自動取り込みの予約を待つ間（P’s CUBE、2026-10-26）。常駐サービスは起こさず、
                        // 画面を消さないだけ（23時以降は暗くする）。Android 15以降の常駐の1日6時間を待ち時間で使わない。
                        "keepScreen" -> {
                            keepScreenOnDimmed(
                                call.argument<Boolean>("on") == true,
                                call.argument<Boolean>("dim") == true,
                            )
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
