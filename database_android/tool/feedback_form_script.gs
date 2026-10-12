// 共有ページを使う人向けのアンケート（Googleフォーム）を作るスクリプト（2026-10-12 利用者「2で作ってもらおうかな」）。
// 回答はフォームとつないだスプレッドシートにたまり、Claude がGoogleドライブの接続でそのシートを読んで整理する。
//
// 使い方：
//   1. https://script.google.com で「新しいプロジェクト」を作る（自分用・読み取り専用のスクリプトとは別）。
//   2. このファイルの中身を全部貼って保存し、関数 createFeedbackForm を選んで「実行」。
//   3. 許可を求められたら許可する（フォームとスプレッドシートを作るため）。
//   4. 実行ログに出る「回答用URL」を使う人に渡す。「編集用URL」「回答のシート」は自分用。
// 質問はすべて任意（空欄のまま送れる。2026-10-12 利用者「めんどくさいところは空欄にしても送れるように」）。
// 何度も実行すると、そのたびに新しいフォームができる（前のものは残る）。

const SKIP = '空欄のままで次へ進めます（このページを全部とばしてもOK）。';

function asQuestion(item) {
  switch (item.getType()) {
    case FormApp.ItemType.MULTIPLE_CHOICE: return item.asMultipleChoiceItem();
    case FormApp.ItemType.CHECKBOX: return item.asCheckboxItem();
    case FormApp.ItemType.PARAGRAPH_TEXT: return item.asParagraphTextItem();
    default: return null;
  }
}

function createFeedbackForm() {
  const form = FormApp.create('database 共有ページ アンケート');
  form.setDescription('★ どの質問も空欄のままで送れます。答えやすいところだけで大丈夫です（1問だけでも助かります）。\n'
    + 'スクリーンショットがあれば、回答の最後の欄にその旨を書いて、別に送ってください。');
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setProgressBar(true);

  form.addSectionHeaderItem().setTitle('あなたについて').setHelpText(SKIP);
  form.addMultipleChoiceItem().setTitle('Q1. 主に使う端末は？')
    .setChoiceValues(['iPhone', 'Android', 'PC']).showOtherOption(true);
  form.addMultipleChoiceItem().setTitle('Q2. どのくらい見ていますか？')
    .setChoiceValues(['毎日', '週に数回', 'たまに']);
  form.addParagraphTextItem().setTitle('Q3. 主に何を見るために開いていますか？')
    .setHelpText('例：明日行く台を決める、昨日の結果を見る、🌈の付いた台を探す');

  form.addPageBreakItem().setTitle('困ったこと・見づらかったこと')
    .setHelpText('いくつかある場合は、Q5〜Q7に「1.」「2.」と番号を付けて書いてください。\n' + SKIP);
  form.addCheckboxItem().setTitle('Q4. どの画面ですか？（いくつでも）')
    .setChoiceValues(['カレンダー', '日のランキング', '機種の台一覧', '台のデータ', '回っていない台',
      'バラエティ🌈の表', 'バラエティ🌈の空き順']).showOtherOption(true);
  form.addParagraphTextItem().setTitle('Q5. そのとき何をしようとしていましたか？');
  form.addCheckboxItem().setTitle('Q6. 実際どうでしたか？（いくつでも）')
    .setChoiceValues(['見づらい', '探すのに時間がかかる', '押し間違えた', '意味が分からなかった',
      '表示がおかしい・数字が合わない']).showOtherOption(true);
  form.addParagraphTextItem().setTitle('Q6補足. 具体的にどうなりましたか？');
  form.addParagraphTextItem().setTitle('Q7. どうなっていたら嬉しいですか？（思いつけば）');
  form.addMultipleChoiceItem().setTitle('Q8. どのくらい困っていますか？')
    .setChoiceValues(['毎回困る', 'ときどき困る', '少し気になる程度']);

  form.addPageBreakItem().setTitle('🌈（確定が出た台の印）について').setHelpText(SKIP);
  form.addMultipleChoiceItem().setTitle('Q9. 🌈は付けていますか？')
    .setChoiceValues(['よく付ける', 'たまに', '付けていない']);
  form.addParagraphTextItem().setTitle('Q10. 付けにくい・付け間違えたことはありますか？あればどの画面で？');
  form.addParagraphTextItem().setTitle('Q11. 🌈の情報で、ほかに見たいものはありますか？')
    .setHelpText('例：機種ごとの回数、曜日ごとの傾向、前回からの日数');

  form.addPageBreakItem().setTitle('その他').setHelpText(SKIP);
  form.addParagraphTextItem().setTitle('Q12. よく使う機能・気に入っているところは？');
  form.addParagraphTextItem().setTitle('Q13. あったら便利な機能は？');
  form.addParagraphTextItem().setTitle('Q14. 自由に一言');

  // 念のため、全部の質問を任意にそろえる（FormAppの既定も任意）。
  form.getItems().forEach(item => {
    const typed = asQuestion(item);
    if (typed) typed.setRequired(false);
  });

  const sheet = SpreadsheetApp.create('database 共有ページ アンケート（回答）');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());

  console.log('回答用URL（使う人に渡す）：' + form.getPublishedUrl());
  console.log('編集用URL（自分用）：' + form.getEditUrl());
  console.log('回答のシート（自分用）：' + sheet.getUrl());
}
