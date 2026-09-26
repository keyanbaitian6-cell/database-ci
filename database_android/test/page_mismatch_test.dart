import 'package:database_android/web_import_page.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const list =
      'https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info_kt/?kind_code=21&target_date=2026-09-25';
  const graph =
      'https://meruhenworld.pt.teramoba2.com/nagamachiminami/standgraph/?rack_no=507&target_date=2026-09-25';

  test('ページのURLと合っていれば通す', () {
    expect(pageMismatch(list, store: 'saiwaichou', day: '2026-09-25'), isNull);
    expect(
      pageMismatch(
        graph,
        store: 'nagamachiminami',
        day: '2026-09-25',
        rack: 507,
      ),
      isNull,
    );
  });

  test('店舗・日付・台番号がURLと違えば止める', () {
    expect(
      pageMismatch(list, store: 'nagamachiminami', day: '2026-09-25'),
      isNotNull,
    );
    expect(
      pageMismatch(list, store: 'saiwaichou', day: '2026-09-24'),
      isNotNull,
    );
    expect(
      pageMismatch(
        graph,
        store: 'nagamachiminami',
        day: '2026-09-25',
        rack: 508,
      ),
      isNotNull,
    );
  });

  test('アプリが付けた日付（#database_day）とも照らし合わせる', () {
    const url =
        'https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info_kt/?kind_code=21#database_next_machine=1&database_day=2026-09-25';
    expect(pageMismatch(url, store: 'saiwaichou', day: '2026-09-25'), isNull);
    expect(
      pageMismatch(url, store: 'saiwaichou', day: '2026-09-20'),
      isNotNull,
    );
  });

  test('対象店舗以外のURLなら止め、URLが取れないときは止めない', () {
    expect(
      pageMismatch('https://example.com/saiwaichou/x', store: 'saiwaichou'),
      isNull,
    );
    expect(
      pageMismatch('https://example.com/other/x', store: 'saiwaichou'),
      isNotNull,
    );
    expect(pageMismatch(null, store: 'saiwaichou'), isNull);
  });

  test('URLに日付が無いときは、日付では止めない（確かめられない）', () {
    const url =
        'https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info_kt/?kind_code=21';
    expect(pageMismatch(url, store: 'saiwaichou', day: '2026-09-25'), isNull);
  });
}
