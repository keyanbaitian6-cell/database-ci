"""PC の Python のファイルに、どこにも定義の無い名前（読み込み忘れ）が無いこと（2026-11-23）。

`009dc55` で `app.py` の日次学習の裏の処理（QuietDailyWorker.start）と5分ごとの確認が `threading` を使い始めたが、
`import threading` が無かった。立ち上げるたびに NameError になり、しかも「実行中」の印を立てたあとだったので、
11/23 の夜は日次学習が一度も始まらなかった。その関数を通る試験が無く、ふつうの試験では気づけなかった。
ここでは実行せずに、Python の symtable で関数の中から参照している大域の名前がモジュールに定義されているかを見る。"""
import builtins
from pathlib import Path
import symtable
import unittest

FOLDER = Path(__file__).resolve().parents[1]
# symtable がモジュールの直下に作る内部の名前（実行時には存在する）
INTERNAL = {'__conditional_annotations__', '__annotations__', '__file__', '__name__', '__spec__', '__doc__',
            '__builtins__', '__loader__', '__package__', '__path__'}


def undefined_names(source, name='<source>'):
    top = symtable.symtable(source, name, 'exec')
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    defined |= set(dir(builtins)) | INTERNAL
    found = set()

    def walk(table):
        for symbol in table.get_symbols():
            if (symbol.is_referenced() and symbol.is_global() and not symbol.is_declared_global()
                    and symbol.get_name() not in defined):
                found.add((symbol.get_name(), table.get_name(), table.get_lineno()))
        for child in table.get_children():
            walk(child)

    walk(top)
    return sorted(found)


class UndefinedNamesTest(unittest.TestCase):
    def test_every_pc_module_defines_or_imports_the_names_it_uses(self):
        problems = []
        for path in sorted(FOLDER.glob('*.py')):
            for name, scope, line in undefined_names(path.read_text(encoding='utf-8'), str(path)):
                problems.append(f'{path.name}:{line} {scope}() で {name} が未定義')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_the_check_catches_the_missing_threading_import_of_11_23(self):
        source = ('def main():\n'
                  '    class Worker:\n'
                  '        def start(self):\n'
                  '            self.thread = threading.Thread(target=print)\n'
                  '    return Worker\n')
        self.assertEqual([n for n, _, _ in undefined_names(source)], ['threading'])
        self.assertEqual(undefined_names('import threading\n' + source), [])


if __name__ == '__main__':
    unittest.main()
