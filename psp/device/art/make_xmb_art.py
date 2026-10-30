"""Draws RemotePilot PSP's XMB art (ICON0.PNG 144x80, PIC1.PNG 480x272).

    python psp/device/art/make_xmb_art.py remotepilot <out folder>

Everything is drawn here from shapes and text: no game art, no captures, no
one's logos. The lettering
is Audiowide (fonts/ beside this file, SIL Open Font License, with OFL.txt).
Colours: a night-blue palette with a cyan accent. The output is plain 8-bit
RGB PNG, non-interlaced, without metadata, as the XMB wants.

"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE / 'fonts' / 'Audiowide-Regular.ttf'
SCALE = 4  # drawn at 4x, then reduced: smooth edges

BG = (8, 17, 31)
DEEP = (11, 42, 74)
BLUE = (21, 93, 158)
ACCENT = (103, 220, 255)
TEXT = (241, 247, 255)
MUTED = (180, 200, 223)
GOLD = (255, 214, 120)


def font(size):
    return ImageFont.truetype(str(FONT), size * SCALE)


def backdrop(width, height, seed):
    """Night-blue gradient, a faint hexagon lattice, stars and a horizon glow."""
    w, h = width * SCALE, height * SCALE
    image = Image.new('RGB', (w, h), BG)
    pixels = image.load()
    for y in range(h):
        t = y / (h - 1)
        row = tuple(int(BG[i] + (DEEP[i] - BG[i]) * t ** 1.4) for i in range(3))
        for x in range(w):
            pixels[x, y] = row
    lattice = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(lattice)
    side = 18 * SCALE
    step_x, step_y = side * 1.5, side * math.sqrt(3)
    for column in range(int(w / step_x) + 2):
        for row in range(int(h / step_y) + 2):
            cx = column * step_x
            cy = row * step_y + (step_y / 2 if column % 2 else 0)
            points = [(cx + side * math.cos(math.pi / 3 * k), cy + side * math.sin(math.pi / 3 * k)) for k in range(7)]
            fade = int(34 * (cy / h))
            draw.line(points, fill=BLUE + (fade,), width=SCALE)
    image.paste(lattice, (0, 0), lattice)
    stars = ImageDraw.Draw(image)
    rng = random.Random(seed)
    for _ in range(int(width * height / 900)):
        x, y = rng.randrange(w), rng.randrange(int(h * 0.62))
        r = rng.choice((1, 1, 1, 2)) * SCALE // 2
        level = rng.randrange(120, 255)
        stars.ellipse((x - r, y - r, x + r, y + r), fill=(level, level, min(255, level + 20)))
    glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-w * 0.4, h * 0.70, w * 1.4, h * 2.2), outline=ACCENT + (200,), width=3 * SCALE)
    glow = glow.filter(ImageFilter.GaussianBlur(6 * SCALE))
    image.paste(glow, (0, 0), glow)
    ImageDraw.Draw(image).ellipse((-w * 0.4, h * 0.70, w * 1.4, h * 2.2), outline=ACCENT, width=SCALE)
    return image


def text(draw, xy, words, size, fill, anchor='la'):
    draw.text((xy[0] * SCALE, xy[1] * SCALE), words, font=font(size), fill=fill, anchor=anchor)


def finish(image, width, height, path):
    image = image.resize((width, height), Image.LANCZOS).convert('RGB')
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, 'PNG', optimize=True)
    print('wrote %s (%dx%d)' % (path, width, height))


def tile(seed):
    """A 144x80 tile: the backdrop, a rounded frame."""
    image = backdrop(144, 80, seed)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2 * SCALE, 2 * SCALE, 142 * SCALE, 78 * SCALE), radius=8 * SCALE, outline=ACCENT, width=SCALE)
    return image, draw


def waves(draw, cx, cy, r):
    """Wi-Fi arcs over a dot: RemotePilot's link."""
    s = SCALE
    for k, radius in enumerate((r * 0.35, r * 0.68, r)):
        draw.arc(((cx - radius) * s, (cy - radius) * s, (cx + radius) * s, (cy + radius) * s), 225, 315,
                 fill=ACCENT if k < 2 else TEXT, width=int(2.4 * s))
    draw.ellipse(((cx - 2.6) * s, (cy - 2.6) * s, (cx + 2.6) * s, (cy + 2.6) * s), fill=TEXT)


def remotepilot(out):
    image, draw = tile(7)
    waves(draw, 25, 46, 20)
    text(draw, (48, 18), 'Remote', 13, TEXT)
    text(draw, (48, 36), 'Pilot', 13, ACCENT)
    text(draw, (72, 66), 'PSP companion', 7, MUTED, 'mm')
    finish(image, 144, 80, out / 'ICON0.PNG')

    image = backdrop(480, 272, 2026)
    draw = ImageDraw.Draw(image)
    waves(draw, 420, 80, 44)
    text(draw, (464, 170), 'RemotePilot PSP', 24, TEXT, 'ra')
    text(draw, (464, 202), 'logs, screen, folders and controls', 11, ACCENT, 'ra')
    text(draw, (464, 220), 'over your own Wi-Fi', 11, ACCENT, 'ra')
    text(draw, (240, 262), 'Not affiliated with Sony', 6, MUTED, 'mm')
    finish(image, 480, 272, out / 'PIC1.PNG')


if __name__ == '__main__':
    sets = {'remotepilot': remotepilot}
    if len(sys.argv) != 3 or sys.argv[1] not in sets:
        sys.exit('usage: make_xmb_art.py remotepilot <out folder>')
    sets[sys.argv[1]](Path(sys.argv[2]))
