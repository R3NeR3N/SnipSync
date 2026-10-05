"""XML の安全な読み込み。

読む XML は auto-editor が書いた FCPXML / Premiere XML だけ（DOCTYPE を持たない）。標準ライブラリの
パーサーは外部エンティティ展開や entity 爆発（XXE / billion laughs）に対して既定で無防備なので、
defusedxml で読み、DOCTYPE があるファイルは拒否する。書き出しや要素の組み立ては標準の
``xml.etree.ElementTree`` を使う。
"""
from defusedxml import ElementTree as _SafeET


def parse(path):
    """ElementTree を返す。DOCTYPE・エンティティ・外部参照を含む XML は例外にする。"""
    return _SafeET.parse(path, forbid_dtd=True)
