package com.keyan.database_android

import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Message
import android.view.KeyEvent
import android.webkit.ClientCertRequest
import android.webkit.HttpAuthHandler
import android.webkit.RenderProcessGoneDetail
import android.webkit.SafeBrowsingResponse
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.annotation.RequiresApi
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugins.webviewflutter.WebViewFlutterAndroidExternalApi
import java.io.ByteArrayInputStream

/**
 * 取り込み画面の内部ブラウザで、YouTube（動画・サムネイル・再生）への要求を端末の中で
 * 空の応答（204）にして、外へ通信しない（2026-10-25 利用者「開こうとすらしない処理」）。
 * PCは WebView2 の WebResourceRequested で同じことをしている（database/pscube_connection.py）。
 *
 * webview_flutter には要求を断る機能が無いので、プラグインが設定した WebViewClient を
 * [Client] で包み、shouldInterceptRequest だけを足す。ほかのコールバックはすべて元の
 * WebViewClient へそのまま渡す（onNavigationRequest・読み込みの開始/完了・エラー処理を壊さない）。
 * Dart の setNavigationDelegate は WebViewClient を置き換えるので、その後に毎回呼ばれる。
 */
class YouTubeRequestBlocker(private val engine: FlutterEngine) {
    fun handle(call: MethodCall, result: MethodChannel.Result) {
        if (call.method != "blockYouTube") {
            result.notImplemented()
            return
        }
        val id = (call.argument<Number>("webView"))?.toLong()
        val hosts = call.argument<List<String>>("hosts")?.map { it.lowercase() }.orEmpty()
        // WebView.getWebViewClient は Android 8 から。それより前は止めない（枠はJSで隠す）。
        if (id == null || hosts.isEmpty() || Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            result.success(false)
            return
        }
        @Suppress("DEPRECATION")
        val webView = WebViewFlutterAndroidExternalApi.getWebView(engine, id)
        if (webView == null) {
            result.success(false)
            return
        }
        val current = webView.webViewClient
        if (current is Client) {
            current.hosts = hosts
        } else {
            webView.webViewClient = Client(current, hosts)
        }
        result.success(true)
    }

    @RequiresApi(Build.VERSION_CODES.O)
    class Client(private val inner: WebViewClient, @Volatile var hosts: List<String>) : WebViewClient() {
        override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? =
            if (isBlocked(request?.url, hosts)) emptyResponse() else inner.shouldInterceptRequest(view, request)

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun shouldInterceptRequest(view: WebView?, url: String?): WebResourceResponse? =
            if (isBlocked(url?.let(Uri::parse), hosts)) emptyResponse() else inner.shouldInterceptRequest(view, url)

        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
            inner.shouldOverrideUrlLoading(view, request)

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean =
            inner.shouldOverrideUrlLoading(view, url)

        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) =
            inner.onPageStarted(view, url, favicon)

        override fun onPageFinished(view: WebView?, url: String?) = inner.onPageFinished(view, url)

        override fun onLoadResource(view: WebView?, url: String?) = inner.onLoadResource(view, url)

        override fun onPageCommitVisible(view: WebView?, url: String?) = inner.onPageCommitVisible(view, url)

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun onTooManyRedirects(view: WebView?, cancelMsg: Message?, continueMsg: Message?) =
            inner.onTooManyRedirects(view, cancelMsg, continueMsg)

        @Deprecated("Deprecated in Java")
        @Suppress("DEPRECATION")
        override fun onReceivedError(view: WebView?, errorCode: Int, description: String?, failingUrl: String?) =
            inner.onReceivedError(view, errorCode, description, failingUrl)

        override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) =
            inner.onReceivedError(view, request, error)

        override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) =
            inner.onReceivedHttpError(view, request, errorResponse)

        override fun onFormResubmission(view: WebView?, dontResend: Message?, resend: Message?) =
            inner.onFormResubmission(view, dontResend, resend)

        override fun doUpdateVisitedHistory(view: WebView?, url: String?, isReload: Boolean) =
            inner.doUpdateVisitedHistory(view, url, isReload)

        override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) =
            inner.onReceivedSslError(view, handler, error)

        override fun onReceivedClientCertRequest(view: WebView?, request: ClientCertRequest?) =
            inner.onReceivedClientCertRequest(view, request)

        override fun onReceivedHttpAuthRequest(view: WebView?, handler: HttpAuthHandler?, host: String?, realm: String?) =
            inner.onReceivedHttpAuthRequest(view, handler, host, realm)

        override fun shouldOverrideKeyEvent(view: WebView?, event: KeyEvent?): Boolean =
            inner.shouldOverrideKeyEvent(view, event)

        override fun onUnhandledKeyEvent(view: WebView?, event: KeyEvent?) = inner.onUnhandledKeyEvent(view, event)

        override fun onScaleChanged(view: WebView?, oldScale: Float, newScale: Float) =
            inner.onScaleChanged(view, oldScale, newScale)

        override fun onReceivedLoginRequest(view: WebView?, realm: String?, account: String?, args: String?) =
            inner.onReceivedLoginRequest(view, realm, account, args)

        override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean =
            inner.onRenderProcessGone(view, detail)

        @RequiresApi(Build.VERSION_CODES.O_MR1)
        override fun onSafeBrowsingHit(
            view: WebView?,
            request: WebResourceRequest?,
            threatType: Int,
            callback: SafeBrowsingResponse?,
        ) = inner.onSafeBrowsingHit(view, request, threatType, callback)
    }

    companion object {
        /** ホスト名だけで判定する（Dart の isYouTubeRequestUrl・PC の is_youtube_request と同じ規則）。 */
        fun isBlocked(url: Uri?, hosts: List<String>): Boolean {
            val host = url?.host?.lowercase() ?: return false
            return hosts.any { host == it || host.endsWith(".$it") }
        }

        private fun emptyResponse() =
            WebResourceResponse("text/plain", "utf-8", 204, "No Content", emptyMap(), ByteArrayInputStream(ByteArray(0)))
    }
}
