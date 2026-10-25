"""Render the plugin's icons into calibre_plugin/images/ with Calibre's own Qt:
    calibre-debug icons/render_icons.py
Two drawings (menu, toolbar) x two strokes (light/dark Calibre theme), each at several pixel sizes; ui.py packs one
drawing's sizes per place into a single QIcon, so Qt shows the menu drawing in menus and the toolbar one in the bar."""
from pathlib import Path

from calibre.gui2 import ensure_app
from qt.core import QByteArray, QImage, QPainter, QSvgRenderer, Qt

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'calibre_plugin' / 'images'
STROKES = {'light': '#434343', 'dark': '#DEDFDF'}  # the San Francisco theme's; its purple accent is the same in both
SIZES = {'menu': (16, 32), 'toolbar': (64, 96, 128, 192)}

ensure_app()
OUT.mkdir(exist_ok=True)
for kind, sizes in SIZES.items():
    svg = (HERE / f'audiobook-{kind}.svg').read_text()
    for theme, stroke in STROKES.items():
        renderer = QSvgRenderer(QByteArray(svg.replace('#434343', stroke).encode()))
        for size in sizes:
            image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
            image.save(str(OUT / f'{kind}-{theme}-{size}.png'))
print(f'Rendered {sum(map(len, SIZES.values())) * len(STROKES)} icons into {OUT}')
