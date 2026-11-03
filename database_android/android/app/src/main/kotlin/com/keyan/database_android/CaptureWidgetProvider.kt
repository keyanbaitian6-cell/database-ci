package com.keyan.database_android

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/**
 * ホーム画面のウィジェット（2026-11-04、利用者が選んだ「ホーム画面のウィジェット」。通常版・P’s CUBE版の両方）。
 * 前回の取り込みの結果（通知と同じ文）と翌日候補を出す。中身はアプリが書いた値をそのまま出すだけで、
 * ウィジェットが自分でサイトへ行ったり計算したりはしない。押すとアプリを開く。
 */
class CaptureWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) manager.updateAppWidget(id, views(context))
    }

    companion object {
        private const val PREFS = "database_widget"

        /** アプリから受け取った値を残し、置いてあるウィジェットをすべて書き換える。 */
        fun save(context: Context, values: Map<String, String>) {
            val editor = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            for ((key, value) in values) editor.putString(key, value)
            editor.apply()
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, CaptureWidgetProvider::class.java))
            for (id in ids) manager.updateAppWidget(id, views(context))
        }

        private fun views(context: Context): RemoteViews {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val views = RemoteViews(context.packageName, R.layout.capture_widget)
            views.setTextViewText(
                R.id.widget_title,
                context.applicationInfo.loadLabel(context.packageManager),
            )
            views.setTextViewText(
                R.id.widget_status,
                prefs.getString("status", null) ?: "まだ取り込みの結果はありません",
            )
            views.setTextViewText(R.id.widget_candidates, prefs.getString("candidates", null) ?: "")
            views.setTextViewText(R.id.widget_updated, prefs.getString("updated", null) ?: "")
            val open = PendingIntent.getActivity(
                context, 2, Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            views.setOnClickPendingIntent(R.id.widget_root, open)
            return views
        }
    }
}
