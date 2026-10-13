package com.keyan.database_android

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File

/** 保存場所は利用者が選ぶ。Driveのアカウント・フォルダIDはAPKへ埋め込まない。 */
class BackupDocumentSaver(private val activity: Activity) {
    companion object {
        const val REQUEST_SAVE = 4718
        private val backupName = Regex("^(database|pscube)-backup-android-\\d{8}-\\d{6}\\.json$")
    }

    private val prefs = activity.getSharedPreferences("backup_destination", Activity.MODE_PRIVATE)
    private var pending: Pair<File, MethodChannel.Result>? = null

    fun handle(call: MethodCall, result: MethodChannel.Result) {
        if (call.method != "save") {
            result.notImplemented()
            return
        }
        if (pending != null) {
            result.error("backup_save_busy", "別のバックアップを保存中です。", null)
            return
        }
        try {
            val path = call.argument<String>("path") ?: error("バックアップがありません。")
            val source = File(path).canonicalFile
            val roots = listOf(activity.cacheDir, activity.filesDir,
                File(activity.applicationInfo.dataDir, "app_flutter")).map { it.canonicalFile }
            require(source.parentFile in roots && source.isFile && backupName.matches(source.name)) {
                "アプリが書き出したバックアップだけ保存できます。"
            }
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/json"
                putExtra(Intent.EXTRA_TITLE, source.name)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    prefs.getString("last_uri", null)?.let {
                        // 保存した文書の親を開くヒント。対応状況は保存先のプロバイダによる。
                        putExtra(DocumentsContract.EXTRA_INITIAL_URI, Uri.parse(it))
                    }
                }
            }
            pending = source to result
            activity.startActivityForResult(intent, REQUEST_SAVE)
        } catch (error: Exception) {
            pending = null
            result.error("backup_save_open", error.message, null)
        }
    }

    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != REQUEST_SAVE) return false
        val request = pending ?: return true // OSがアプリを作り直した場合は保存済みにしない。
        if (resultCode != Activity.RESULT_OK) {
            pending = null
            request.second.success(false)
            return true
        }
        val uri = data?.data
        if (uri == null || uri.scheme != "content") {
            pending = null
            request.second.error("backup_save_uri", "保存先を取得できませんでした。", null)
            return true
        }
        val flags = data?.flags ?: 0
        // 数十MiB以上のファイルも丸ごとメモリに載せず、UIスレッドを止めずに書く。
        Thread({
            try {
                val resolver = activity.contentResolver
                request.first.inputStream().use { input ->
                    val output = resolver.openOutputStream(uri, "w")
                        ?: error("保存先に書き込めませんでした。")
                    output.use { input.copyTo(it) }
                }
                if (flags and Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION != 0) {
                    try {
                        resolver.takePersistableUriPermission(uri, flags and
                            (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION))
                        prefs.getString("last_uri", null)?.let { previous ->
                            if (previous != uri.toString()) {
                                // 初期表示に必要な直近1件だけ保持し、権限の上限に達しないようにする。
                                val old = resolver.persistedUriPermissions.firstOrNull {
                                    it.uri.toString() == previous
                                }
                                if (old != null) {
                                    resolver.releasePersistableUriPermission(old.uri,
                                        (if (old.isReadPermission) Intent.FLAG_GRANT_READ_URI_PERMISSION else 0) or
                                        (if (old.isWritePermission) Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0))
                                }
                            }
                        }
                    } catch (_: SecurityException) {
                        // 永続権限非対応でも保存そのものは完了している。
                    }
                }
                // 書き込み・closeが成功した場合だけ次回の場所を更新する。
                prefs.edit().putString("last_uri", uri.toString()).apply()
                activity.runOnUiThread {
                    pending = null
                    request.second.success(true)
                }
            } catch (error: Exception) {
                // 元の端末バックアップは残す。失敗した保存をバックアップ済みにしない。
                activity.runOnUiThread {
                    pending = null
                    request.second.error("backup_save_write", error.message, null)
                }
            }
        }, "backup-save").start()
        return true
    }
}
