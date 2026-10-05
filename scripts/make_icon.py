"""アプリアイコン（src/snipsync/assets/icon/）を作り直す。ロゴ（widgets.Logo）と同じ図形を、大きなタイルに置く。

    pip install pillow
    python scripts/make_icon.py

理由は DESIGN.md「アプリアイコン」。色は src/snipsync/ui/theme.py のトークンから取る。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from snipsync.ui import theme as T  # noqa: E402

OUT = ROOT / "src" / "snipsync" / "assets" / "icon"
BASE = 1024            # 描くときの大きさ。縮小して各サイズを作る（輪郭をなめらかにするため）
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rgb(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def draw_base() -> Image.Image:
    img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # タイル: 暗い面（画面の BENCH）に、明るい縁取り。暗いタスクバーの上でも輪郭が見える。
    d.rounded_rectangle((0, 0, BASE - 1, BASE - 1), radius=int(BASE * 0.22), fill=rgb(T.EDGE))
    inset = int(BASE * 0.022)
    d.rounded_rectangle((inset, inset, BASE - 1 - inset, BASE - 1 - inset), radius=int(BASE * 0.2), fill=rgb(T.BENCH))
    # 図形: ロゴと同じ 30 単位の座標。小さくしても潰れないよう、枠線ではなく塗りつぶす。
    s = BASE * 0.74 / 24
    ox, oy = BASE / 2 - 15 * s, BASE / 2 - 15 * s

    def pts(*xy):
        return [(ox + xy[i] * s, oy + xy[i + 1] * s) for i in range(0, len(xy), 2)]

    chalk = rgb(T.CHALK)
    d.polygon(pts(3, 9, 15, 9, 11, 21, 3, 21), fill=chalk)
    d.polygon(pts(19, 9, 27, 9, 27, 21, 15, 21), fill=chalk)
    a, b = pts(18, 5, 9, 25)
    d.line((a, b), fill=rgb(T.BENCH), width=int(s * 5.6))      # 切れ目の隙間（タイルの色で抜く）
    d.line((a, b), fill=rgb(T.PENCIL), width=int(s * 3.0))
    for p in (a, b):                                            # 線の端を丸める
        r = s * 1.5
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=rgb(T.PENCIL))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = draw_base()
    frames = [base.resize((n, n), Image.LANCZOS) for n in SIZES]
    frames[-1].save(OUT / "snipsync.ico", format="ICO", sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    base.resize((256, 256), Image.LANCZOS).save(OUT / "snipsync.png")
    print("wrote", OUT / "snipsync.ico", "and snipsync.png")


if __name__ == "__main__":
    main()
