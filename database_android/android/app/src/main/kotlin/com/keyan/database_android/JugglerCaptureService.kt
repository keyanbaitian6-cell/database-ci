package com.keyan.database_android

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Display
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

/**
 * ジャグラーオンライン（お試し、2026-10-09から最長2週間。JUGGLER_ONLINE.md）。
 * ジャグラーオンラインの画面が前にある間だけ、小さな「取込」ボタンを重ねる。押すとその画面を撮って
 * アプリの中（filesDir/juggler_captures）に置くだけで、読み取り・保存はdatabaseアプリの画面で行う。
 * ジャグラーオンラインは画面をUnityで描くため、文字はアクセシビリティから読めない（画像から読む）。
 * ボタンは指でずらせる（位置は覚える）。長押しでdatabaseアプリを開く。
 */
class JugglerCaptureService : AccessibilityService() {
    companion object {
        const val TARGET = "jp.co.kitadenshi.juggleronline"
        fun folder(context: Context): File = File(context.filesDir, "juggler_captures").apply { mkdirs() }
        fun captures(context: Context): List<File> =
            folder(context).listFiles { f -> f.isFile && f.name.endsWith(".png") }?.sortedBy { it.name } ?: emptyList()
    }

    private val handler = Handler(Looper.getMainLooper())
    private var button: TextView? = null
    private var params: WindowManager.LayoutParams? = null
    private var busy = false

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val pkg = event.packageName?.toString() ?: return
        when (pkg) {
            TARGET -> showButton()
            // 自分の知らせ・通知の引き出しなどでは消さない。
            packageName, "com.android.systemui" -> Unit
            else -> hideButton()
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        hideButton()
        super.onDestroy()
    }

    private fun prefs() = getSharedPreferences("juggler_capture", Context.MODE_PRIVATE)

    private fun label() = "取込\n${captures(this).size}枚"

    private fun showButton() {
        if (button != null) {
            button?.text = label()
            return
        }
        val density = resources.displayMetrics.density
        val size = (64 * density).toInt()
        val view = TextView(this).apply {
            text = label()
            setTextColor(Color.WHITE)
            textSize = 12f
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.parseColor("#E6007A"))
                setStroke((2 * density).toInt(), Color.WHITE)
            }
            alpha = 0.92f
        }
        val lp = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs().getInt("x", (8 * density).toInt())
            y = prefs().getInt("y", (resources.displayMetrics.heightPixels * 0.62).toInt())
        }
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var moved = false
        val longPress = Runnable {
            moved = true
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        view.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; startX = lp.x; startY = lp.y; moved = false
                    handler.postDelayed(longPress, 700)
                }
                MotionEvent.ACTION_MOVE -> {
                    if (abs(e.rawX - downX) > 12 || abs(e.rawY - downY) > 12) {
                        handler.removeCallbacks(longPress)
                        moved = true
                        lp.x = startX + (e.rawX - downX).toInt()
                        lp.y = startY + (e.rawY - downY).toInt()
                        windowManager().updateViewLayout(view, lp)
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    handler.removeCallbacks(longPress)
                    if (moved) {
                        prefs().edit().putInt("x", lp.x).putInt("y", lp.y).apply()
                    } else if (e.action == MotionEvent.ACTION_UP) {
                        capture()
                    }
                }
            }
            true
        }
        windowManager().addView(view, lp)
        button = view
        params = lp
    }

    private fun hideButton() {
        button?.let { runCatching { windowManager().removeView(it) } }
        button = null
        params = null
    }

    private fun windowManager() = getSystemService(Context.WINDOW_SERVICE) as WindowManager

    private fun say(text: String) = Toast.makeText(this, text, Toast.LENGTH_SHORT).show()

    /** ボタンを隠してから画面を撮る（ボタンが写らないように）。 */
    private fun capture() {
        if (busy) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            say("この機能はAndroid 11以降で使えます。")
            return
        }
        busy = true
        button?.visibility = View.INVISIBLE
        handler.postDelayed({
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    val bitmap = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                        ?.copy(Bitmap.Config.ARGB_8888, false)
                    result.hardwareBuffer.close()
                    button?.visibility = View.VISIBLE
                    if (bitmap == null) {
                        busy = false
                        say("画面を撮れませんでした。")
                        return
                    }
                    Thread {
                        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss-SSS", Locale.US).format(Date())
                        val file = File(folder(this@JugglerCaptureService), "jo-$stamp.png")
                        val ok = runCatching {
                            FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                        }.isSuccess
                        bitmap.recycle()
                        handler.post {
                            busy = false
                            button?.text = label()
                            say(if (ok) "取り込みました（${captures(this@JugglerCaptureService).size}枚）。databaseで読み取ります。" else "保存できませんでした。")
                        }
                    }.start()
                }

                override fun onFailure(errorCode: Int) {
                    busy = false
                    button?.visibility = View.VISIBLE
                    say("画面を撮れませんでした（$errorCode）。少し待ってからもう一度押してください。")
                }
            })
        }, 150)
    }
}
