#!/usr/bin/env python3
"""Build the Calibre plugin, dist/audiblez_audiobook.zip. Install it with:
    calibre-customize -a dist/audiblez_audiobook.zip
The plugin bundles colab_audiblez.py and a payload zip of our audiblez package and voices, which it uploads to the VM."""
import zipfile
from pathlib import Path

from colab_audiblez import make_payload

ROOT = Path(__file__).parent


def main():
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    payload = make_payload(ROOT, dist / 'audiblez_payload.zip')
    plugin = dist / 'audiblez_audiobook.zip'
    with zipfile.ZipFile(plugin, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / 'calibre_plugin').iterdir()):
            if f.is_file():
                z.write(f, f.name)
        for f in sorted((ROOT / 'calibre_plugin' / 'images').glob('*.png')):  # from icons/render_icons.py
            z.write(f, f'images/{f.name}')
        z.write(ROOT / 'colab_audiblez.py', 'colab_audiblez.py')
        z.write(ROOT / 'LICENSE', 'LICENSE')  # both licenses require their text to travel with copies
        z.write(ROOT / 'audiblez' / 'LICENSE', 'LICENSE-audiblez')
        z.write(payload, 'audiblez_payload.zip', compress_type=zipfile.ZIP_STORED)  # already compressed
    print(f'Built {plugin}')


if __name__ == '__main__':
    main()
