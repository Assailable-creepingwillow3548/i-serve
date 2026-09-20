"""The frames of record-page.mjs, assembled into docs/page.gif.

Pillow is the one dependency in the tree and a contributor's tool only; what
the recording costs, and why, is in site/README.md. The palette is shared and
undithered because dithering scatters this page's flat fills and doubles the
file.
"""

import pathlib
import sys

from PIL import Image

FRAMES = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/page-frames")
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "docs/page.gif")
COLORS = 64
MS_PER_FRAME = 250


def main() -> None:
    files = sorted(FRAMES.glob("f*.png"))
    if not files:
        raise SystemExit(f"no frames in {FRAMES}")
    frames = [Image.open(f).convert("RGB") for f in files]
    shared = frames[0].quantize(colors=COLORS, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    paletted = [f.quantize(colors=COLORS, palette=shared, dither=Image.Dither.NONE) for f in frames]
    paletted[0].save(OUT, save_all=True, append_images=paletted[1:], loop=0,
                     duration=MS_PER_FRAME, optimize=True, disposal=1)
    kib = OUT.stat().st_size / 1024
    print(f"{OUT}: {len(frames)} frames, {kib:.0f} KiB, {len(frames) * MS_PER_FRAME / 1000:.0f} s")


if __name__ == "__main__":
    main()
