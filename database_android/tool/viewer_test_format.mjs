// 画面試験で使う、閲覧ページと同じ差枚の書き方（models.dart の signedMedals：符号と3桁区切り）。
export function signedMedalsForTest(value) {
  const digits = Math.abs(value).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (value > 0 ? '+' : value < 0 ? '-' : '') + digits;
}
