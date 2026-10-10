"""Rydorgo's mark - an italic R with three speed lines - in every format the app needs.

One geometry on Android's 108-unit adaptive-icon grid (the visible part is the
middle 72, the safe circle radius 33 around 54,54). The italic is a skew baked
into the points, because a VectorDrawable <group> cannot skew.

Regenerate (from rider/scripts/brand):
    python make_icon.py          # vectors, brandMarkPaths.ts, jobs.json
    npm i --no-save @resvg/resvg-js@2 && node render.js   # the PNGs
`node preview_scenes.js` draws every illustration, light and dark, to PNG
sheets here for a look before they reach a phone. resvg is a tool for these
scripts only - never an app dependency.
"""

import json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RES = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'res')
HERE = os.path.dirname(os.path.abspath(__file__))

K = 0.15          # italic: x' = x - K*y
SCALE = 0.9       # breathing room inside the safe circle
CX = CY = 54.0
SHIFT_X = 1.5     # optical centring of R + lines


def tf(x, y):
    x = x + SHIFT_X
    x = x - K * (y - CY)          # skew about the centre line
    x = CX + (x - CX) * SCALE
    y = CY + (y - CY) * SCALE
    return round(x, 2), round(y, 2)


def path(cmds):
    """[('M', x, y), ('L', x, y), ('C', x1, y1, x2, y2, x, y), ('Z',)] -> d, transformed."""
    out = []
    for c in cmds:
        op, nums = c[0], c[1:]
        pts = []
        for i in range(0, len(nums), 2):
            pts.extend(tf(nums[i], nums[i + 1]))
        out.append(op + (' ' + ' '.join(f'{n:g}' for n in pts) if pts else ''))
    return ' '.join(out)


R_OUTER = [
    ('M', 47, 33), ('L', 65, 33), ('C', 73.5, 33, 78.5, 38.2, 78.5, 46.2),
    ('C', 78.5, 52.2, 75.4, 56.6, 70.2, 58.4), ('L', 80, 75), ('L', 69, 75),
    ('L', 60.6, 59.4), ('L', 57, 59.4), ('L', 57, 75), ('L', 47, 75), ('Z',),
]
R_HOLE = [
    ('M', 57, 41.6), ('L', 64.3, 41.6), ('C', 67.4, 41.6, 69, 43.4, 69, 46.4),
    ('C', 69, 49.4, 67.4, 51.2, 64.3, 51.2), ('L', 57, 51.2), ('Z',),
]


def capsule(x1, x2, y, r):
    k = 0.5523 * r
    return [
        ('M', x1, y - r), ('L', x2, y - r),
        ('C', x2 + k, y - r, x2 + r, y - k, x2 + r, y),
        ('C', x2 + r, y + k, x2 + k, y + r, x2, y + r),
        ('L', x1, y + r),
        ('C', x1 - k, y + r, x1 - r, y + k, x1 - r, y),
        ('C', x1 - r, y - k, x1 - k, y - r, x1, y - r), ('Z',),
    ]


R_D = path(R_OUTER) + ' ' + path(R_HOLE)
LINES_D = ' '.join(path(capsule(a, b, y, 2.6)) for a, b, y in ((33, 40, 44), (27, 40, 54), (33, 40, 64)))

GRAD = [('0', '#FF7A3D'), ('0.55', '#FF5200'), ('1', '#E84A00')]


def svg(view, *, shape, size, fg_only=False):
    x0, y0, w, h = view
    stops = ''.join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in GRAD)
    bg = ''
    if not fg_only:
        if shape == 'square':
            bg = f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="url(#g)"/>'
        elif shape == 'rounded':
            bg = f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="{w * 0.22}" fill="url(#g)"/>'
        else:
            bg = f'<circle cx="{x0 + w / 2}" cy="{y0 + h / 2}" r="{w / 2}" fill="url(#g)"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="{x0} {y0} {w} {h}">'
        f'<defs><linearGradient id="g" x1="{x0}" y1="{y0}" x2="{x0 + w}" y2="{y0 + h}" gradientUnits="userSpaceOnUse">{stops}</linearGradient></defs>'
        f'{bg}<path d="{LINES_D}" fill="#FFFFFF" fill-opacity="0.85"/>'
        f'<path d="{R_D}" fill="#FFFFFF" fill-rule="evenodd"/></svg>'
    )


jobs = []  # (svg, out png path)
DENS = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
VISIBLE = (18, 18, 72, 72)  # the part of the 108 grid a launcher shows
for d, px in DENS.items():
    jobs.append((svg(VISIBLE, shape='rounded', size=px), os.path.join(RES, f'mipmap-{d}', 'ic_launcher.png')))
    jobs.append((svg(VISIBLE, shape='round', size=px), os.path.join(RES, f'mipmap-{d}', 'ic_launcher_round.png')))
jobs.append((svg(VISIBLE, shape='square', size=512), os.path.join(ROOT, 'assets', 'brand', 'play-store-icon-512.png')))
jobs.append((svg((0, 0, 108, 108), shape='square', size=1024), os.path.join(ROOT, 'assets', 'brand', 'icon-1024.png')))
os.makedirs(os.path.join(ROOT, 'assets', 'brand'), exist_ok=True)
open(os.path.join(ROOT, 'assets', 'brand', 'mark.svg'), 'w', encoding='utf-8').write(svg(VISIBLE, shape='rounded', size=512))
json.dump([{'svg': s, 'out': o} for s, o in jobs], open(os.path.join(HERE, 'jobs.json'), 'w'))

# --- Android vector drawables ------------------------------------------------
os.makedirs(os.path.join(RES, 'drawable'), exist_ok=True)
os.makedirs(os.path.join(RES, 'mipmap-anydpi-v26'), exist_ok=True)
items = ''.join(f'\n          <item android:offset="{o}" android:color="{c}" />' for o, c in GRAD)
open(os.path.join(RES, 'drawable', 'ic_launcher_background.xml'), 'w', encoding='utf-8', newline='\n').write(f'''<?xml version="1.0" encoding="utf-8"?>
<!-- Generated with the mark (scratch make_icon.py); the brand gradient on the 108 grid. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:aapt="http://schemas.android.com/aapt"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
  <path android:pathData="M0,0h108v108h-108z">
    <aapt:attr name="android:fillColor">
      <gradient
          android:type="linear"
          android:startX="0"
          android:startY="0"
          android:endX="108"
          android:endY="108">{items}
      </gradient>
    </aapt:attr>
  </path>
</vector>
''')


def fg_vector(name, comment, color='#FFFFFF', size=108):
    open(os.path.join(RES, 'drawable', name), 'w', encoding='utf-8', newline='\n').write(f'''<?xml version="1.0" encoding="utf-8"?>
<!-- {comment} -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="{size}dp"
    android:height="{size}dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
  <path
      android:fillColor="{color}"
      android:fillAlpha="0.85"
      android:pathData="{LINES_D}" />
  <path
      android:fillColor="{color}"
      android:fillType="evenOdd"
      android:pathData="{R_D}" />
</vector>
''')


fg_vector('ic_launcher_foreground.xml', 'Rydorgo mark: an italic R and three speed lines, inside the adaptive safe zone.')
fg_vector('splash_mark.xml', 'The mark alone, for the launch screen (white on the brand orange).', size=160)

for name in ('ic_launcher.xml', 'ic_launcher_round.xml'):
    open(os.path.join(RES, 'mipmap-anydpi-v26', name), 'w', encoding='utf-8', newline='\n').write('''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
  <background android:drawable="@drawable/ic_launcher_background" />
  <foreground android:drawable="@drawable/ic_launcher_foreground" />
  <monochrome android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
''')

# --- the same mark for the app's own screens (BrandMark) ---------------------
open(os.path.join(ROOT, 'src', 'components', 'ui', 'brandMarkPaths.ts'), 'w', encoding='utf-8', newline='\n').write(f'''/**
 * Rydorgo's mark, the same geometry as the launcher icon
 * (`android/app/src/main/res/drawable/ic_launcher_foreground.xml`): Android's
 * 108-unit adaptive grid, of which a launcher shows the middle 72 - hence
 * MARK_VIEWBOX. Generated; change the icon and this together.
 */

export const MARK_VIEWBOX = '18 18 72 72';
export const MARK_LINES = '{LINES_D}';
export const MARK_R = '{R_D}';
''')
print('ok', len(jobs), 'pngs queued')
