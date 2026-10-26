/// P’s CUBEの当日分をGoogleのスクリプト（Apps Script）へ送る（2026-10-26、database/PSCUBE_SYNC.md
/// 「当日分の自動送信」）。自動取り込みが「すべて取り込みました」で止まったときに、その日の記録だけを送る。
/// スクリプトは「database共有」に pscube-day-android-YYYY-MM-DD.json を書き、PC版が起動中に読み込む。
/// 台の記録を書くので合言葉が要る（スクリプトの PSCUBE_UPLOAD_KEY と同じもの）。
library;

import 'dart:convert';
import 'dart:io';

import 'models.dart' show timestampWithOffset;
import 'pscube_store.dart';

/// スクリプトへ本文を送り、返事の本文を返す。試験では差し替える。
typedef ScriptPoster = Future<String> Function(Uri url, String body);

/// 当日分の自動送信の設定。URLはスクリプトの「ウェブアプリのURL」（…/exec）。
class PscubeDayUploadSetting {
  const PscubeDayUploadSetting({
    required this.url,
    required this.key,
    this.enabled = true,
  });

  final String url, key;
  final bool enabled;

  static PscubeDayUploadSetting? fromJson(Map<String, dynamic>? raw) {
    if (raw == null) return null;
    final url = raw['url'], key = raw['key'], enabled = raw['enabled'];
    if (url is! String || key is! String) return null;
    return PscubeDayUploadSetting(
      url: url,
      key: key,
      enabled: enabled != false,
    );
  }

  Map<String, Object?> toJson() => {'url': url, 'key': key, 'enabled': enabled};

  /// 入れた値の誤り（無ければ null）。
  static String? problem(String url, String key) {
    if (scriptUri(url) == null) {
      return 'スクリプトのURL（https://script.google.com/macros/s/…/exec）を入れてください。';
    }
    if (key.trim().length < 8) return '合言葉は8文字以上にしてください。';
    return null;
  }

  static Uri? scriptUri(String value) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host != 'script.google.com' ||
        !uri.path.startsWith('/macros/s/') ||
        !uri.path.endsWith('/exec')) {
      return null;
    }
    return uri;
  }
}

/// [day] の記録を送る。成功・失敗の文を返し、結果を端末に残す（取り込み画面に表示する）。
/// 失敗しても記録は端末に残っているので、取り込みのやり直しは要らない（手で送り直せる）。
Future<({bool ok, String message})> uploadPscubeDay(
  PscubeStore store,
  String day,
  PscubeDayUploadSetting setting, {
  ScriptPoster poster = postToScript,
  DateTime? now,
}) async {
  final at = now ?? DateTime.now();
  final label =
      '${int.parse(day.substring(5, 7))}/${int.parse(day.substring(8))}';
  Future<({bool ok, String message})> finish(bool ok, String message) async {
    await store.markDayUpload({
      'day': day,
      'at': timestampWithOffset(at),
      'ok': ok,
      'message': message,
    });
    return (ok: ok, message: message);
  }

  final uri = PscubeDayUploadSetting.scriptUri(setting.url);
  if (uri == null) return finish(false, '$labelの分を送れません：スクリプトのURLが不正です。');
  final backup = await store.dayBackup(day, now: at);
  if (backup == null) return finish(false, '$labelの分を送れません：その日の記録がありません。');
  final count = (backup['records'] as List).length;
  Object? reply;
  try {
    reply = jsonDecode(
      await poster(
        uri,
        jsonEncode({
          'file': 'pscube-day',
          'key': setting.key,
          'day': day,
          'backup': backup,
        }),
      ),
    );
  } catch (error) {
    return finish(false, '$labelの分を送れませんでした：$error');
  }
  if (reply is Map &&
      reply['ok'] == true &&
      reply['day'] == day &&
      reply['records'] == count &&
      reply['exported_at'] == backup['exported_at']) {
    return finish(true, '$labelの分（$count台）をDriveへ送りました。');
  }
  final error = reply is Map
      ? reply['error'] ??
            (reply['ok'] == true ? '保存の確認情報が一致しません。閲覧用スクリプトを更新してください。' : null)
      : null;
  return finish(false, '$labelの分を送れませんでした：${error ?? 'スクリプトの返事が読めません'}');
}

/// Apps Script のウェブアプリへPOSTする。スクリプトは実行後、返事の場所へ転送（302）するので、
/// 転送先を読む（POSTのままでは転送されない）。
Future<String> postToScript(Uri url, String body) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
  try {
    final request = await client.postUrl(url);
    request.followRedirects = false;
    request.headers.contentType = ContentType(
      'text',
      'plain',
      charset: 'utf-8',
    );
    request.add(utf8.encode(body));
    var response = await request.close().timeout(const Duration(seconds: 90));
    for (
      var hops = 0;
      response.isRedirect || _redirect(response.statusCode);
      hops++
    ) {
      final location = response.headers.value(HttpHeaders.locationHeader);
      await response.drain<void>();
      if (location == null || hops >= 5) {
        throw const HttpException('スクリプトの転送先が読めません。');
      }
      final next = await client.getUrl(url.resolve(location));
      response = await next.close().timeout(const Duration(seconds: 60));
    }
    final text = await response
        .transform(utf8.decoder)
        .join()
        .timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) {
      throw HttpException('スクリプトの返事が ${response.statusCode} でした。');
    }
    return text;
  } finally {
    client.close(force: true);
  }
}

bool _redirect(int status) =>
    status == 301 ||
    status == 302 ||
    status == 303 ||
    status == 307 ||
    status == 308;
