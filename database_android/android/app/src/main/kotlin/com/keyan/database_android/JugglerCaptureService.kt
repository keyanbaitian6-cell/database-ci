package com.keyan.database_android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Display
import android.view.Gravity
import android.view.MotionEvent
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
 * ジャグラーオンラインの画面が前にある間だけ、小さな「取込」ボタンを重ねる。1回押すと「データ一覧」の表を
 * 自動でスクロールしながら撮る（2026-10-10 利用者「取り込みボタンで開いてる機種の台番したまで取り込めたら」）：
 * 1ページ目（BB〜総回転数）をいちばん上から下まで撮り、横にずらして差枚のページを下から上まで撮る。
 * 撮った画面はアプリの中（filesDir/juggler_captures）に置くだけで、読み取り・保存はdatabaseアプリの画面で行う。
 * ジャグラーオンラインは画面をUnityで描くため、文字はアクセシビリティから読めない（画像から読む）。
 * ボタンは指でずらせる（位置は覚える）。長押しでdatabaseアプリを開く。撮影中にほかのアプリへ移ると止まる。
 */
class JugglerCaptureService : AccessibilityService() {
    companion object {
        const val TARGET = "jp.co.kitadenshi.juggleronline"
        fun folder(context: Context): File = File(context.filesDir, "juggler_captures").apply { mkdirs() }
        fun captures(context: Context): List<File> =
            folder(context).listFiles { f -> f.isFile && f.name.endsWith(".png") }?.sortedBy { it.name } ?: emptyList()

        // 位置は画面の割合（お手本を作った端末は横1080×縦2340）。2026-10-10 に実機で確かめた：表は見出しごと
        // スクロールし、ゆっくり550px動かすと勢いで約790px進む（見えている表は約1340px）。横は3ページで、
        // 1ページ目（BB〜総回転数）は印「»」だけ、2ページ目（確率など）は両方、3ページ目（差枚）は「«」だけ。
        // 「全機種表示」では全機種が1つの表に並ぶ（数百台）ので、1ページあたりの枚数の上限は多めにする。
        const val MAX_SHOTS_PER_PAGE = 150
        const val MAX_STEPS = 3000
    }

    private val handler = Handler(Looper.getMainLooper())
    private var button: TextView? = null
    private var params: WindowManager.LayoutParams? = null
    private var busy = false

    /** 自動で撮っている最中の1回分。ほかのアプリへ移ったら cancelled にして止める。 */
    private class AutoRun(val group: String) {
        var saved = 0
        var steps = 0
        var lastSaved: IntArray? = null
        var cancelled = false
    }

    private var auto: AutoRun? = null

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val pkg = event.packageName?.toString() ?: return
        val cls = event.className?.toString() ?: ""
        // 出し消しの原因を追えるよう、前に来たアプリと画面の種類の名前だけを残す（画面の文字は読まない）。
        Log.d("JugglerCapture", "window $pkg $cls")
        // キーボードは、ジャグラーオンラインの上に出ても前のアプリは変わらないので消さない。
        if (cls.startsWith("android.inputmethodservice.")) return
        when (pkg) {
            // 撮影中はボタンを出さない（写らないように・スワイプを受け止めないように）。
            TARGET -> if (auto == null) showButton()
            // databaseの画面（MainActivity）が前に来たときだけ消す（読み取りの画面に重ならないように）。
            // このボタン自身や知らせ（Toast）も同じパッケージ名で届くので、パッケージ名だけで消すと、
            // 出した直後に自分で消してしまう（2026-10-10、0.5.36+2026100903 でボタンが出なくなった）。
            packageName -> if (cls == MainActivity::class.java.name) hideButton()
            // 通知の引き出しなどでは消さない。
            "com.android.systemui" -> Unit
            else -> hideButton()
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        hideButton()
        super.onDestroy()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        auto?.cancelled = true
        return super.onUnbind(intent)
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
                        startAuto()
                    }
                }
            }
            true
        }
        windowManager().addView(view, lp)
        button = view
        params = lp
    }

    /** ほかのアプリへ移ったとき：ボタンを消し、撮影中なら止める。 */
    private fun hideButton() {
        auto?.cancelled = true
        removeButton()
    }

    private fun removeButton() {
        button?.let { runCatching { windowManager().removeView(it) } }
        button = null
        params = null
    }

    private fun windowManager() = getSystemService(Context.WINDOW_SERVICE) as WindowManager

    private fun say(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()

    // ---- 自動で撮る ----

    private fun startAuto() {
        if (busy) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            say("この機能はAndroid 11以降で使えます。")
            return
        }
        busy = true
        val run = AutoRun(SimpleDateFormat("yyyyMMddHHmmss", Locale.US).format(Date()))
        auto = run
        // ボタンは撮影の間は消す（写らないように・スワイプを受け止めないように）。知らせ（Toast）も写るので出さない。
        removeButton()
        handler.postDelayed({ alignToFirstPage(run, 0) }, 300)
    }

    /** まだ続けてよいか。止められていたら終わりの処理をする。 */
    private fun alive(run: AutoRun): Boolean {
        if (auto !== run) return false
        if (run.cancelled) {
            finish(run, "止めました（${run.saved}枚撮りました）。")
            return false
        }
        if (++run.steps > MAX_STEPS) {
            finish(run, "長くかかりすぎたので止めました（${run.saved}枚撮りました）。")
            return false
        }
        return true
    }

    private fun finish(run: AutoRun, message: String) {
        if (auto !== run) return
        auto = null
        busy = false
        // ほかのアプリへ移って止まったときは出さない（ジャグラーオンラインに戻れば出る）。
        if (!run.cancelled) showButton()
        say(message)
    }

    /** 1ページ目（BB〜総回転数、印は「»」だけ）へ戻す。 */
    private fun alignToFirstPage(run: AutoRun, tries: Int) {
        if (!alive(run)) return
        settled(run) { bitmap, sig ->
            val (left, right) = pageArrows(bitmap)
            bitmap.recycle()
            when {
                !left && !right -> finish(run, "「データ一覧」の表で押してください（表のページの印が見つかりません）。")
                left && tries < 4 -> swipeHorizontal(run, toNext = false) { alignToFirstPage(run, tries + 1) }
                left -> finish(run, "表の1ページ目に戻れませんでした。")
                else -> scrollToTop(run, sig, 0)
            }
        }
    }

    /** 表のいちばん上へ（画面が動かなくなるまで、指を下へ速く動かす）。 */
    private fun scrollToTop(run: AutoRun, previous: IntArray, tries: Int) {
        if (!alive(run)) return
        swipeVertical(run, towardTop = true, fast = true) {
            settled(run) { bitmap, sig ->
                bitmap.recycle()
                if (same(sig, previous) || tries >= 20) captureDown(run) else scrollToTop(run, sig, tries + 1)
            }
        }
    }

    /** 1ページ目を上から下へ撮る。前に撮った画面と同じ（もう動かない）なら、いちばん下まで撮った。 */
    private fun captureDown(run: AutoRun) {
        if (!alive(run)) return
        settled(run) { bitmap, sig ->
            if (run.lastSaved?.let { same(sig, it) } == true || run.saved >= MAX_SHOTS_PER_PAGE) {
                bitmap.recycle()
                run.lastSaved = null
                toNetPage(run, 0)
            } else {
                save(run, bitmap, sig)
                swipeVertical(run, towardTop = false, fast = false) { captureDown(run) }
            }
        }
    }

    /** 差枚のページ（印は「«」だけ）へ。2ページ目（確率など）は撮らずに通り過ぎる。 */
    private fun toNetPage(run: AutoRun, tries: Int) {
        if (!alive(run)) return
        swipeHorizontal(run, toNext = true) {
            settled(run) { bitmap, _ ->
                val (left, right) = pageArrows(bitmap)
                bitmap.recycle()
                when {
                    left && !right -> captureUp(run, run.saved)
                    tries < 3 -> toNetPage(run, tries + 1)
                    else -> finish(run, "差枚のページに移れませんでした（${run.saved}枚撮りました）。")
                }
            }
        }
    }

    /** 差枚のページを下から上へ撮る（横にずらしても縦の位置はそのまま）。 */
    private fun captureUp(run: AutoRun, firstPageShots: Int) {
        if (!alive(run)) return
        settled(run) { bitmap, sig ->
            if (run.lastSaved?.let { same(sig, it) } == true || run.saved - firstPageShots >= MAX_SHOTS_PER_PAGE) {
                bitmap.recycle()
                finish(run, "${run.saved}枚撮りました。databaseの「ジャグラーオンラインの取り込み」で読み取ってください。")
            } else {
                save(run, bitmap, sig)
                swipeVertical(run, towardTop = true, fast = false) { captureUp(run, firstPageShots) }
            }
        }
    }

    /** 画面が止まる（続けて撮った2枚が同じ）まで撮り直す。スクロールの勢いが残っている間は使わない。 */
    private fun settled(run: AutoRun, previous: IntArray? = null, tries: Int = 0, then: (Bitmap, IntArray) -> Unit) {
        if (!alive(run)) return
        shot(run, 0) { bitmap ->
            val sig = signature(bitmap)
            if ((previous != null && same(sig, previous)) || tries >= 10) {
                then(bitmap, sig)
            } else {
                bitmap.recycle()
                handler.postDelayed({ settled(run, sig, tries + 1, then) }, 450)
            }
        }
    }

    private fun shot(run: AutoRun, retries: Int, then: (Bitmap) -> Unit) {
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(result: ScreenshotResult) {
                val bitmap = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                    ?.copy(Bitmap.Config.ARGB_8888, false)
                result.hardwareBuffer.close()
                when {
                    bitmap == null -> finish(run, "画面を撮れませんでした（${run.saved}枚撮りました）。")
                    auto === run && !run.cancelled -> then(bitmap)
                    else -> {
                        bitmap.recycle()
                        alive(run)
                    }
                }
            }

            override fun onFailure(errorCode: Int) {
                // 続けて撮りすぎ（間隔が短い）などは、少し待って撮り直す。
                if (retries < 3) {
                    handler.postDelayed({ if (alive(run)) shot(run, retries + 1, then) }, 600)
                } else {
                    finish(run, "画面を撮れませんでした（$errorCode、${run.saved}枚撮りました）。")
                }
            }
        })
    }

    private fun save(run: AutoRun, bitmap: Bitmap, sig: IntArray) {
        run.lastSaved = sig
        run.saved++
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss-SSS", Locale.US).format(Date())
        // -g<組>：1回押して撮った画面の組。読み取りで、画面の外に出た店名・機種名を組の中で補う。
        val file = File(folder(this), "jo-$stamp-g${run.group}.png")
        Thread {
            runCatching { FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) } }
            bitmap.recycle()
        }.start()
    }

    /**
     * 縦のスクロール。[towardTop]：表の上の方へ（指を下へ動かす）。[fast]：いちばん上へ戻すときの速い動き。
     * 横はスタートの列のあたり（左端の台番号の枠、右端のページの印と「^」ボタンを避ける）。
     */
    private fun swipeVertical(run: AutoRun, towardTop: Boolean, fast: Boolean, then: () -> Unit) {
        val m = resources.displayMetrics
        val x = m.widthPixels * 0.65f
        val (from, to) = when {
            fast -> 0.45f to 0.85f
            towardTop -> 0.575f to 0.81f
            else -> 0.81f to 0.575f
        }
        swipe(run, x, m.heightPixels * from, x, m.heightPixels * to, if (fast) 250L else 900L, then)
    }

    /** 横のページ送り。[toNext]：右のページへ（指を左へ動かす）。 */
    private fun swipeHorizontal(run: AutoRun, toNext: Boolean, then: () -> Unit) {
        val m = resources.displayMetrics
        val y = m.heightPixels * 0.70f
        val (from, to) = if (toNext) 0.83f to 0.14f else 0.14f to 0.83f
        swipe(run, m.widthPixels * from, y, m.widthPixels * to, y, 500L, then)
    }

    private fun swipe(run: AutoRun, x1: Float, y1: Float, x2: Float, y2: Float, ms: Long, then: () -> Unit) {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, ms))
            .build()
        val ok = dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                handler.postDelayed({ if (alive(run)) then() }, 300)
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                finish(run, "スクロールが止められました（${run.saved}枚撮りました）。")
            }
        }, handler)
        if (!ok) {
            finish(run, "スクロールできませんでした（${run.saved}枚撮りました）。設定でこのサービスを一度オフにしてオンにし直してください。")
        }
    }

    /** 表のあたりの明るさを粗く並べたもの（動いたかどうかを比べる）。上の帯・下のメニューは入れない。 */
    private fun signature(bitmap: Bitmap): IntArray {
        val y0 = (bitmap.height * 0.40).toInt()
        val y1 = (bitmap.height * 0.86).toInt()
        val values = ArrayList<Int>()
        var y = y0
        while (y < y1) {
            var x = 0
            while (x < bitmap.width) {
                val c = bitmap.getPixel(x, y)
                values.add((Color.red(c) + Color.green(c) + Color.blue(c)) / 3)
                x += 12
            }
            y += 12
        }
        return values.toIntArray()
    }

    private fun same(a: IntArray, b: IntArray): Boolean {
        if (a.size != b.size || a.isEmpty()) return false
        var sum = 0L
        for (i in a.indices) sum += abs(a[i] - b[i])
        return sum.toDouble() / a.size < 2.5
    }

    /** 横のページの印（左「«」・右「»」、灰色）。lib/juggler_online.dart の joPageArrows と同じ決まり。 */
    private fun pageArrows(bitmap: Bitmap): Pair<Boolean, Boolean> {
        val y0 = (bitmap.height * 0.58).toInt()
        val y1 = (bitmap.height * 0.66).toInt()
        fun count(x0: Int, x1: Int): Int {
            var n = 0
            var y = y0
            while (y < y1 && y < bitmap.height) {
                var x = maxOf(x0, 0)
                while (x < x1 && x < bitmap.width) {
                    val c = bitmap.getPixel(x, y)
                    val r = Color.red(c)
                    if (r in 0x68..0x90 && abs(r - Color.green(c)) < 8 && abs(r - Color.blue(c)) < 8) n++
                    x += 2
                }
                y += 2
            }
            return n
        }
        return (count(0, 86) >= 25) to (count(bitmap.width - 80, bitmap.width) >= 25)
    }
}
