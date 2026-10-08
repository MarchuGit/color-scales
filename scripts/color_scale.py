#!/usr/bin/env python3
"""Motor de m-color-scales.

Genera escalas de color en OKLCH ubicando cada HEX en el nivel que le
corresponde por luminosidad, y las exporta como SVG con los templates
originales embebidos.

Uso:
  color_scale.py --lines "4E2159\\ncaso b C9E1D3 166534 fijo oscuro" --out DIR
  color_scale.py --spec spec.json --out DIR
Opciones: --no-drift  --names HEX=Nombre ...  --table  --pairs  --preview  --name archivo
Salida: SVG (+ PNG con --preview) en DIR y un reporte JSON por stdout.
"""
import argparse
import datetime
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

# ─── Niveles ──────────────────────────────────────────────────────────────
LEVELS21 = list(range(0, 1001, 50))
FINAL13 = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 1000]
# 0 y 1000 son blanco y negro puros: un HEX del usuario nunca los reemplaza.
ANCHOR_LEVELS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

ACHROMATIC_C = 0.005      # por debajo, el tono es ruido numérico: gris real
CHROMATIC_C = 0.02        # por encima, el tono es confiable para comparar
SAME_FAMILY_DH = 15.0     # grados de tono para considerar dos colores de una familia
DE_REUSE = 0.02           # ΔE OKLab: indistinguible a efectos prácticos
DE_ACCEPT = 0.05          # ΔE OKLab: parecido, decisión visual

# ─── Conversión de color ──────────────────────────────────────────────────
def _s2l(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _l2s(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

def _cbrt(x):
    return math.copysign(abs(x) ** (1 / 3), x)

def norm_hex(h):
    h = h.strip().lstrip('#').upper()
    if not re.fullmatch(r'[0-9A-F]{6}', h):
        raise ValueError('HEX inválido: ' + h)
    return h

def hex_to_linear(h):
    return [_s2l(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)]

def linear_to_oklab(r, g, b):
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)

def oklch_to_linear(L, C, H):
    h = math.radians(H)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)

def hex_to_oklab(h):
    return linear_to_oklab(*hex_to_linear(h))

def hex_to_oklch(h):
    L, a, b = hex_to_oklab(h)
    return L, math.hypot(a, b), (math.degrees(math.atan2(b, a)) + 360) % 360

def in_gamut(L, C, H, eps=0.0005):
    return all(-eps <= c <= 1 + eps for c in oklch_to_linear(L, C, H))

def max_chroma(L, H):
    """Croma más alto que existe en pantalla (sRGB) para ese L y ese tono."""
    if L <= 0 or L >= 1:
        return 0.0
    lo, hi = 0.0, 0.5
    for _ in range(30):
        mid = (lo + hi) / 2
        if in_gamut(L, mid, H):
            lo = mid
        else:
            hi = mid
    return lo

def oklch_to_hex(L, C, H):
    """Mapeo de gamut: si el color no existe en pantalla, se baja el croma
    (búsqueda binaria) conservando L y tono; nunca se recortan canales."""
    L = min(max(L, 0.0), 1.0)
    if C > 0 and not in_gamut(L, C, H):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            if in_gamut(L, mid, H):
                lo = mid
            else:
                hi = mid
        C = lo
    rgb = oklch_to_linear(L, C, H)
    return ''.join('%02X' % round(min(max(_l2s(max(c, 0.0)), 0.0), 1.0) * 255) for c in rgb)

def wcag_lum(h):
    r, g, b = hex_to_linear(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(h1, h2):
    a, b = wcag_lum(h1), wcag_lum(h2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)

def delta_e(h1, h2):
    return math.dist(hex_to_oklab(h1), hex_to_oklab(h2))

def hue_diff(h1, h2):
    d = (h2 - h1) % 360
    return d - 360 if d > 180 else d

# ─── Curvas nivel → luminosidad (L de OKLCH) ──────────────────────────────
def _pchip(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    def f(x):
        for i in range(n - 1):
            if xs[i] <= x <= xs[i + 1]:
                t = (x - xs[i]) / h[i]
                h00 = 2 * t ** 3 - 3 * t ** 2 + 1
                h10 = t ** 3 - 2 * t ** 2 + t
                h01 = -2 * t ** 3 + 3 * t ** 2
                h11 = t ** 3 - t ** 2
                return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]
        return ys[-1]
    return f

# "tailwind": L promedio por nivel de las 17 familias cromáticas de Tailwind v4.3.
TAILWIND_POINTS = [(0, 1.0), (50, 0.977), (100, 0.950), (200, 0.905), (300, 0.840),
                   (400, 0.754), (500, 0.683), (600, 0.598), (700, 0.515), (800, 0.446),
                   (900, 0.395), (950, 0.278), (1000, 0.0)]
CURVES = {'tailwind': _pchip(TAILWIND_POINTS)}

def place(L, curve):
    """Nivel permitido cuya luminosidad de curva está más cerca del color."""
    f = CURVES[curve]
    return min(ANCHOR_LEVELS, key=lambda lv: abs(L - f(lv)))

# ─── Tono y croma ─────────────────────────────────────────────────────────
# Giro de tono medido en Tailwind v4.3: (tono del 500, giro al 50, giro al 950).
# Los cálidos giran mucho (amarillo -32° al oscurecer); el resto, 14° o menos.
DRIFT_TABLE = [(16, -4, -4), (25, -8, 1), (48, 26, -11), (70, 25, -24), (86, 16, -32),
               (131, -10, 1), (150, 6, 3), (162, 4, 10), (183, -2, 10), (215, -14, 14),
               (237, -1, 6), (260, -5, 8), (277, -5, 4), (293, 1, -2), (304, 4, -1),
               (322, -2, 4), (354, -11, 10)]
DRIFT_L50, DRIFT_L950 = 0.977, 0.278


def _drift_for(H):
    """Giro al 50 y al 950 para un tono, interpolando la tabla en el círculo."""
    pts = DRIFT_TABLE + [(DRIFT_TABLE[0][0] + 360,) + DRIFT_TABLE[0][1:]]
    h = H if H >= pts[0][0] else H + 360
    for (h1, l1, d1), (h2, l2, d2) in zip(pts, pts[1:]):
        if h1 <= h <= h2:
            t = (h - h1) / (h2 - h1)
            return l1 + (l2 - l1) * t, d1 + (d2 - d1) * t
    return 0.0, 0.0


def drifted_hue(H0, L0, L):
    """Al aclarar u oscurecer desde el ancla, el tono gira como en Tailwind v4."""
    g50, g950 = _drift_for(H0)
    if L < L0:
        t = min((L0 - L) / max(L0 - DRIFT_L950, 1e-6), 1.0)
        return (H0 + g950 * t) % 360
    if L > L0:
        t = min((L - L0) / max(DRIFT_L50 - L0, 1e-6), 1.0)
        return (H0 + g50 * t) % 360
    return H0

# Croma relativo promedio por nivel en Tailwind v4.3 (1 = máximo en pantalla),
# normalizado al pico: los extremos bajan levemente la saturación.
CHROMA_TAPER = _pchip([(0, 0.84), (50, 0.84), (100, 0.86), (200, 0.86), (300, 0.92),
                       (400, 1.0), (500, 1.0), (600, 1.0), (700, 0.98), (800, 0.92),
                       (900, 0.84), (950, 0.82), (1000, 0.82)])


def tapered(r, level, anchor_level):
    return min(r * CHROMA_TAPER(level) / CHROMA_TAPER(anchor_level), 1.0)


def relative_chroma(L, C, H):
    cm = max_chroma(L, H)
    return 0.0 if cm <= 0 else min(C / cm, 1.0)

# ─── Construcción de escalas ──────────────────────────────────────────────
class Anchor:
    def __init__(self, hx, name=''):
        self.hex = norm_hex(hx)
        self.name = name
        self.L, self.C, self.H = hex_to_oklch(self.hex)
        self.achromatic = self.C < ACHROMATIC_C
        self.r = 0.0 if self.achromatic else relative_chroma(self.L, self.C, self.H)
        self.level = None
        self.forced = None


def place_anchor(a, curve):
    """Nivel del ancla: el forzado por el usuario (HEX@400) o el de su luminosidad."""
    if a.forced in ANCHOR_LEVELS:
        return a.forced
    return place(a.L, curve)


def _step(level, L, H, r):
    if r <= 0:
        return oklch_to_hex(L, 0.0, 0.0)
    return oklch_to_hex(L, r * max_chroma(L, H), H)


def scale_anchored(anchors, curve='tailwind', drift=False):
    """Casos A y B: uno o dos HEX fijos en su nivel; el resto sigue la curva."""
    f = CURVES[curve]
    anchors = sorted(anchors, key=lambda a: a.level)
    for a in anchors:
        a.d = a.L - f(a.level)
    # Un color casi neutro no tiene tono confiable: toma el del otro ancla, si lo hay.
    chromatic = [a for a in anchors if a.C >= CHROMATIC_C]
    for a in anchors:
        if a.C < CHROMATIC_C and chromatic and chromatic[0] is not a:
            a.Hu = chromatic[0].H
        elif a.achromatic:
            a.Hu = 0.0
        else:
            a.Hu = a.H
    by_level = {a.level: a for a in anchors}
    first, last = anchors[0], anchors[-1]
    steps = []
    for lv in LEVELS21:
        if lv == 0:
            steps.append({'level': 0, 'hex': 'FFFFFF', 'fixed': False})
            continue
        if lv == 1000:
            steps.append({'level': 1000, 'hex': '000000', 'fixed': False})
            continue
        if lv in by_level:
            a = by_level[lv]
            steps.append({'level': lv, 'hex': a.hex, 'fixed': True, 'name': a.name})
            continue
        if lv < first.level:
            w = lv / first.level
            L = f(lv) + first.d * w
            H = drifted_hue(first.Hu, first.L, L) if drift else first.Hu
            r = tapered(first.r, lv, first.level)
        elif lv > last.level:
            w = (1000 - lv) / (1000 - last.level)
            L = f(lv) + last.d * w
            H = drifted_hue(last.Hu, last.L, L) if drift else last.Hu
            r = tapered(last.r, lv, last.level)
        else:
            a, b = anchors[0], anchors[1]
            t = (lv - a.level) / (b.level - a.level)
            L = f(lv) + a.d * (1 - t) + b.d * t
            H = (a.Hu + hue_diff(a.Hu, b.Hu) * t) % 360
            r = a.r + (b.r - a.r) * t
        steps.append({'level': lv, 'hex': _step(lv, L, H, r), 'fixed': False})
    return steps


def scale_neutral(curve):
    """Escala de grises sobre la curva, sin color fijo."""
    f = CURVES[curve]
    return [{'level': lv, 'hex': 'FFFFFF' if lv == 0 else '000000' if lv == 1000 else oklch_to_hex(f(lv), 0.0, 0.0),
             'fixed': False} for lv in LEVELS21]


def is_pure_bw(a):
    return a.hex in ('FFFFFF', '000000')


def scale_edges(a, b):
    """Caso C: HEX1 en el nivel 0, HEX2 en el 1000; interpolación L, C y tono."""
    Ha = a.H if not a.achromatic else b.H
    Hb = b.H if not b.achromatic else a.H
    dH = hue_diff(Ha, Hb)
    steps = []
    for lv in LEVELS21:
        if lv == 0:
            steps.append({'level': 0, 'hex': a.hex, 'fixed': True, 'name': a.name})
        elif lv == 1000:
            steps.append({'level': 1000, 'hex': b.hex, 'fixed': True, 'name': b.name})
        else:
            t = lv / 1000
            L = a.L + (b.L - a.L) * t
            C = a.C + (b.C - a.C) * t
            H = (Ha + dH * t) % 360
            steps.append({'level': lv, 'hex': oklch_to_hex(L, C, H), 'fixed': False})
    return steps


def resolve_collision(a1, a2):
    if a1.level != a2.level:
        return None
    light, dark = sorted([a1, a2], key=lambda a: -a.L)
    i = ANCHOR_LEVELS.index(dark.level)
    if i + 1 < len(ANCHOR_LEVELS):
        dark.level = ANCHOR_LEVELS[i + 1]
    else:
        light.level = ANCHOR_LEVELS[i - 1]
    return 'ambos caían en el mismo nivel; se separaron a %d y %d' % (light.level, dark.level)


def fit_analysis(fixed, other, curve, drift):
    """Escala del color fijo + paso sugerido en el nivel donde cae el otro."""
    fx = Anchor(fixed.hex, fixed.name)
    fx.forced = fixed.forced
    fx.level = place_anchor(fx, curve)
    steps = scale_anchored([fx], curve, drift)
    lv = place_anchor(other, curve)
    if lv == fx.level:
        i = ANCHOR_LEVELS.index(lv)
        lv = ANCHOR_LEVELS[i + 1] if other.L < fx.L and i + 1 < len(ANCHOR_LEVELS) else ANCHOR_LEVELS[max(i - 1, 0)]
    step = next(s for s in steps if s['level'] == lv)
    de = delta_e(other.hex, step['hex'])
    step.update({'suggested': True, 'original': other.hex, 'delta_e': de})
    if de <= DE_REUSE:
        verdict = 'reutilizar el paso: indistinguible del original'
    elif de <= DE_ACCEPT:
        verdict = 'aceptable: parecido, decidir mirando'
    else:
        verdict = 'conviene escala aparte: la diferencia se nota'
    return steps, {'fixed': fixed.hex, 'other': other.hex, 'other_level': lv,
                   'suggested': step['hex'], 'delta_e': round(de, 4), 'verdict': verdict}

# ─── Validación y reportes ────────────────────────────────────────────────
def validate(steps, anchors, monotone=True):
    issues = []
    hexes = [s['hex'] for s in steps]
    for a in anchors:
        if a.hex not in hexes:
            issues.append('el HEX %s no quedó intacto en la escala' % a.hex)
    for x, y in zip(steps, steps[1:]):
        if x['hex'] == y['hex']:
            issues.append('niveles %d y %d tienen el mismo HEX' % (x['level'], y['level']))
        if monotone and hex_to_oklch(y['hex'])[0] >= hex_to_oklch(x['hex'])[0]:
            issues.append('la luminosidad no baja entre %d y %d' % (x['level'], y['level']))
    return issues


def pair_report(steps):
    def first(pred):
        return next((s['level'] for s in steps if pred(s)), None)
    s50 = next(s['hex'] for s in steps if s['level'] == 50)
    return {
        'texto_sobre_blanco_4.5': first(lambda s: contrast(s['hex'], 'FFFFFF') >= 4.5),
        'texto_grande_o_borde_sobre_blanco_3': first(lambda s: contrast(s['hex'], 'FFFFFF') >= 3),
        'texto_sobre_50_4.5': first(lambda s: contrast(s['hex'], s50) >= 4.5),
    }


def table_rows(steps, levels):
    rows = []
    for s in steps:
        if s['level'] not in levels:
            continue
        L, C, H = hex_to_oklch(s['hex'])
        cw, cb = contrast(s['hex'], 'FFFFFF'), contrast(s['hex'], '000000')
        rows.append('| %d | #%s | (%.3f, %.3f, %.1f) | %.2f / %.2f | %s |' % (
            s['level'], s['hex'], L, C, H, cw, cb, 'WHITE' if cw >= cb else 'BLACK'))
    return '| Level | HEX | OKLCH | Contrast Ratio (W/B) | Text Color |\n|---|---|---|---|---|\n' + '\n'.join(rows)

# ─── SVG (templates originales embebidos) ─────────────────────────────────
SCALE_SVG = '''<svg width="327" height="285" viewBox="0 0 327 285" fill="none" xmlns="http://www.w3.org/2000/svg">
<g id="SCALE">
<rect width="327" height="285" fill="white"/>
<g id="Scale-name">
<text id="Color Name" fill="#09090B" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="24" font-weight="700" letter-spacing="0px"><tspan x="30" y="52.92">Color Name</tspan></text>
<text id="Notes..." fill="#71717A" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="12" letter-spacing="0px"><tspan x="30" y="77.26">Notes...</tspan></text>
</g>
<g id="Scale-items-container">
<rect width="267" height="154" transform="translate(30 101)" fill="white"/>
<path id="item" d="M297 101H30V255H297V101Z" fill="#D9D9D9"/>
</g>
</g>
</svg>
'''

ITEM_DEFAULT_SVG = '''<svg width="92" height="154" viewBox="0 0 92 154" fill="none" xmlns="http://www.w3.org/2000/svg">
<g id="Item-Default">
<g id="swatch-style">
<rect x="1" y="1" width="90" height="70" rx="6" fill="white"/>
<rect x="1" y="1" width="90" height="70" rx="6" stroke="white" stroke-width="2"/>
<rect id="[SWATCH]" width="80" height="60" rx="4" transform="matrix(-1 0 0 1 86 6)" fill="#4E2159"/>
</g>
<g id="labels">
<text id="[TOKEN]" fill="#6B7280" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="12" letter-spacing="0px"><tspan x="38" y="96.26">00</tspan></text>
<g id="hex">
<text id="hash" fill="#111827" style="white-space: pre" xml:space="preserve" font-family="Andale Mono" font-size="13" letter-spacing="0px"><tspan x="17" y="115.481">#</tspan></text>
<text id="[HEX]" fill="#111827" style="white-space: pre" xml:space="preserve" font-family="Andale Mono" font-size="13" letter-spacing="0px"><tspan x="28" y="115.481">O0O0O0</tspan></text>
</g>
</g>
</g>
</svg>
'''

ITEM_FIJO_SVG = '''<svg width="92" height="154" viewBox="0 0 92 154" fill="none" xmlns="http://www.w3.org/2000/svg">
<g id="Item-Fijo">
<g id="swatch-style">
<rect x="1" y="1" width="90" height="70" rx="7" fill="white"/>
<rect x="1" y="1" width="90" height="70" rx="7" stroke="#F43F5E" stroke-width="2"/>
<rect id="[SWATCH]" width="80" height="60" rx="4" transform="matrix(-1 0 0 1 86 6)" fill="#4E2159"/>
</g>
<g id="labels">
<text id="[TOKEN]" fill="#F43F5E" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="12" letter-spacing="0px"><tspan x="38" y="96.26">00</tspan></text>
<g id="hex">
<text id="hash" fill="#F43F5E" style="white-space: pre" xml:space="preserve" font-family="Andale Mono" font-size="13" letter-spacing="0px"><tspan x="17" y="115.481">#</tspan></text>
<text id="[HEX]" fill="#F43F5E" style="white-space: pre" xml:space="preserve" font-family="Andale Mono" font-size="13" letter-spacing="0px"><tspan x="28" y="115.481">O0O0O0</tspan></text>
</g>
<path id="arrow" d="M41.646 126.032L46.014 130.386L50.354 126.046V127.6L46 131.94L41.646 127.586L41.646 126.032ZM46.574 122L46.574 131.24H45.426L45.426 122L46.574 122Z" fill="#09090B"/>
<text id="[NAME]" fill="#09090B" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="14" font-weight="700" letter-spacing="0px"><tspan x="15.3066" y="149.91">[nombre]</tspan></text>
</g>
</g>
</svg>
'''

# Variante para el paso sugerido (derivada de Item-Fijo, en azul): la mitad derecha
# del swatch muestra el HEX original para comparar a simple vista.
ITEM_SUGERIDO_SVG = (ITEM_FIJO_SVG
    .replace('id="Item-Fijo"', 'id="Item-Sugerido"')
    .replace('#F43F5E', '#3B82F6')
    .replace('fill="#09090B"/>\n<text id="[NAME]" fill="#09090B"', 'fill="#3B82F6"/>\n<text id="[NAME]" fill="#3B82F6"')
    .replace('transform="matrix(-1 0 0 1 86 6)" fill="#4E2159"/>',
             'transform="matrix(-1 0 0 1 86 6)" fill="#4E2159"/>\n'
             '<path id="[ORIGINAL]" d="M46 6H82C84.2091 6 86 7.79086 86 10V62C86 64.2091 84.2091 66 82 66H46V6Z" fill="#0R1G1N"/>\n'
             '<rect id="divisor" x="45.5" y="6" width="1" height="60" fill="white"/>\n'
             '<text id="original-label" fill="#0L4B3L" style="white-space: pre" xml:space="preserve" font-family="Geist" font-size="8" letter-spacing="0px"><tspan x="50" y="62">tuyo</tspan></text>'))

ITEM_W, SCALE_H, MARGIN = 92, 285, 30
FIXED_BLACK = '#000000'
EDGE_GRAY = '#F2F2F2'
ALERT_RED = '#F43F5E'
NAME_MAX = 10


def _inner(svg):
    return svg[svg.index('>') + 1:svg.rindex('</svg>')].strip('\n')


def svg_item(step):
    if step.get('suggested'):
        tpl = ITEM_SUGERIDO_SVG
    else:
        tpl = ITEM_FIJO_SVG if step['fixed'] else ITEM_DEFAULT_SVG
    s = _inner(tpl)
    if step.get('suggested'):
        orig = step['original']
        label = 'FFFFFF' if contrast(orig, 'FFFFFF') >= contrast(orig, '000000') else '000000'
        s = s.replace('#0R1G1N', '#' + orig).replace('#0L4B3L', '#' + label)
        step = dict(step, name=('ΔE %.3f' % step['delta_e']).replace('.', ','))
    # Colores fijos: borde y textos en negro; en rojo cuando la escala es no recomendada.
    # (La variante sugerida ya viene en azul desde su definición.)
    if step['fixed'] and not step.get('suggested'):
        s = s.replace('#F43F5E', ALERT_RED if step.get('alert') else FIXED_BLACK)
    s = s.replace('fill="#4E2159"', 'fill="#%s"' % step['hex'], 1)
    if step['hex'] == 'FFFFFF':
        # cuadro blanco: borde interno gris muy suave (1 px, #F2F2F2) para que no se pierda sobre el fondo
        s = s.replace('fill="#FFFFFF"/>', 'fill="#FFFFFF"/>\n<rect id="edge" x="6.5" y="6.5" width="79" '
                      'height="59" rx="3.5" stroke="%s" stroke-width="1" fill="none"/>' % EDGE_GRAY, 1)
    # [AA]: contraste WCAG del color contra el texto que mejor se lee encima (blanco o negro),
    # dentro del cuadro, abajo a la izquierda, con la posición medida en el layer [AA] de Figma.
    cw, cb = contrast(step['hex'], 'FFFFFF'), contrast(step['hex'], '000000')
    # El producto de los dos contrastes (contra blanco y contra negro) es siempre 21: el mejor
    # texto da como mínimo 4,58:1 y el otro color sirve solo si el mejor queda bajo 7.
    def nivel(r):
        return 'AAA' if r >= 7 else 'AA' if r >= 4.5 else 'AA Lg/UI'

    # El contraste es simétrico: la línea blanca vale también para el color usado como texto
    # sobre fondo blanco, y la negra, para el color como texto sobre fondo negro. Solo se escribe
    # lo que sirve (3:1 o más), cada línea en su propio color de texto. Blanco arriba, negro abajo.
    filas = [(c, '%.2f:1 %s' % (r, nivel(r))) for c, r in (('#FFFFFF', cw), ('#000000', cb)) if r >= 3]
    ys = [60] if len(filas) == 1 else [49, 60]
    aa = ('<text id="[AA]" style="white-space: pre" xml:space="preserve" font-family="Inter" '
          'font-size="8.546" letter-spacing="0px">%s</text>'
          % ''.join('<tspan x="10" y="%d" fill="%s">%s</tspan>' % (y, c, t) for y, (c, t) in zip(ys, filas)))
    s = s.replace('</g>\n<g id="labels">', aa + '\n</g>\n<g id="labels">', 1)
    # El número de nivel se centra sobre el eje del ítem (x=46); el template lo ancla a
    # la izquierda en x=38 y los niveles de 3 y 4 cifras quedan corridos.
    s = s.replace('letter-spacing="0px"><tspan x="38" y="96.26">00</tspan>',
                  'letter-spacing="0px" text-anchor="middle"><tspan x="46" y="96.26">00</tspan>', 1)
    s = s.replace('>00</tspan>', '>%d</tspan>' % step['level'], 1)
    s = s.replace('>O0O0O0</tspan>', '>%s</tspan>' % step['hex'], 1)
    # El nombre se centra bajo la flecha (x=46 es el eje del ítem); en el template va
    # alineado a la izquierda en x=15,3 y los nombres largos quedan corridos.
    s = s.replace('letter-spacing="0px"><tspan x="15.3066" y="149.91">[nombre]</tspan>',
                  'letter-spacing="0px" text-anchor="middle"><tspan x="46" y="149.91">[nombre]</tspan>', 1)
    s = s.replace('>[nombre]</tspan>', '>%s</tspan>' % escape(step.get('name', '')), 1)
    return s


CODE_GRAY = '#A1A1AA'


def svg_scale(steps, title, notes, alert=False, code=None):
    n = len(steps)
    width = n * ITEM_W + 2 * MARGIN
    s = SCALE_SVG
    s = s.replace('width="327" height="285" viewBox="0 0 327 285"',
                  'width="%d" height="%d" viewBox="0 0 %d %d"' % (width, SCALE_H, width, SCALE_H), 1)
    s = s.replace('<rect width="327" height="285" fill="white"/>',
                  '<rect width="%d" height="%d" fill="white"/>' % (width, SCALE_H), 1)
    s = s.replace('<rect width="267" height="154"', '<rect width="%d" height="154"' % (n * ITEM_W), 1)
    s = s.replace('>Color Name</tspan>', '>%s</tspan>' % escape(title), 1)
    s = s.replace('>Notes...</tspan>', '>%s</tspan>' % escape(notes), 1)
    if alert:
        s = s.replace('<text id="Notes..." fill="#71717A"', '<text id="Notes..." fill="%s"' % ALERT_RED, 1)
    if code:
        # código corto de la escala en la conversación, para elegirla al exportar
        s = s.replace('<g id="Scale-name">\n', '<g id="Scale-name">\n<text id="code" fill="%s" style="white-space: pre" '
                      'xml:space="preserve" font-family="Geist" font-size="11" letter-spacing="0px">'
                      '<tspan x="30" y="24">%s</tspan></text>\n' % (CODE_GRAY, escape(code)), 1)
    items = '\n'.join('<g id="item-%d" transform="translate(%d 101)">\n%s\n</g>' % (
        st['level'], MARGIN - 1 + i * ITEM_W, svg_item(st)) for i, st in enumerate(steps))
    s = s.replace('<path id="item" d="M297 101H30V255H297V101Z" fill="#D9D9D9"/>', items, 1)
    return s, width


# Exportación: cada escala queda solo con su nombre, sin código de sesión, nota ni ↳, y con el
# padding del layout de Figma: 20 arriba, 10 entre el nombre y los ítems, 20 abajo (234 de alto).
EXPORT_H, EXPORT_ITEMS_Y, EXPORT_TITLE_Y = 234, 61, 45.7


def clean_svg(svg):
    """Versión de exportación de una escala ya renderizada: solo el nombre, sin código, nota ni ↳."""
    def sub(pattern, repl, text, flags=0):
        out, n = re.subn(pattern, repl, text, count=1, flags=flags)
        if n != 1:
            raise ValueError('clean_svg: no se encontró %r' % pattern)
        return out

    s = sub(r'<text id="code".*?</text>\n', '', svg, re.S)
    s = sub(r'<text id="Notes\.\.\.".*?</text>\n?', '', s, re.S)
    s = sub(r'(<text id="Color Name"[^>]*><tspan x="30" y=")[\d.]+(">)(?:↳ )?', r'\g<1>%s\g<2>' % EXPORT_TITLE_Y, s)
    s = s.replace(ALERT_RED, FIXED_BLACK)
    s = s.replace('height="%d"' % SCALE_H, 'height="%d"' % EXPORT_H, 2)
    s = s.replace(' %d"' % SCALE_H, ' %d"' % EXPORT_H, 1)
    s = s.replace('translate(30 101)', 'translate(30 %d)' % EXPORT_ITEMS_Y)
    s = re.sub(r'(<g id="item-\d+" transform="translate\(\d+ )101\)', r'\g<1>%d)' % EXPORT_ITEMS_Y, s)
    s = s.replace('M297 101H30V255H297V101Z', 'M297 %dH30V%dH297V%dZ' % ((EXPORT_ITEMS_Y,) * 3)) if 'id="item"' in s else s
    return s


def svg_stack(scales, height=None):
    if len(scales) == 1:
        return scales[0][0]
    width = max(w for _, w in scales)
    h = height or SCALE_H
    height = h * len(scales)
    body = '\n'.join('<g id="escala-%d" transform="translate(0 %d)">\n%s\n</g>' % (
        i + 1, i * h, _inner(svg)) for i, (svg, _) in enumerate(scales))
    return ('<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">\n%s\n</svg>\n') % (width, height, width, height, body)

# ─── Entrada ──────────────────────────────────────────────────────────────
HEX_RE = re.compile(r'(?<![0-9A-Fa-f])#?([0-9A-Fa-f]{6})(?![0-9A-Fa-f])')


def parse_lines(text):
    """Una línea = una escala. Devuelve (specs, líneas sin HEX válido)."""
    specs, ignored = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        hexes = [h.upper() for h in HEX_RE.findall(line)]
        levels = {h.upper(): int(lv) for h, lv in re.findall(r'#?([0-9A-Fa-f]{6})\s*@\s*(\d{2,3})', line)}
        if not hexes:
            ignored.append(line)
            continue
        m = re.search(r'caso\s*([abc])', low)
        case = m.group(1).upper() if m else ('A' if len(hexes) == 1 else 'B')
        fm = re.search(r'fij[oa]s?\s*(claro|oscuro|1|2|primero|segundo|ambos)', low)
        fixed = None
        if fm:
            fixed = {'1': 'first', 'primero': 'first', '2': 'second', 'segundo': 'second'}.get(fm.group(1), fm.group(1))
        elif re.search(r'\bambos\b', low):
            fixed = 'ambos'
        if case == 'A' or len(hexes) == 1:
            for h in hexes:
                specs.append({'case': 'A', 'colors': [h], 'levels': levels, 'requested': case})
        else:
            if len(hexes) > 2:
                ignored.append('%s (solo se usan los dos primeros HEX)' % line)
            specs.append({'case': case, 'colors': hexes[:2], 'fixed': fixed, 'levels': levels})
    return specs, ignored


def build(spec, defaults, names):
    curve = spec.get('curve', defaults['curve'])
    drift = spec.get('drift', defaults['drift'])
    case = spec['case']
    anchors = [Anchor(h, names.get(norm_hex(h), '')) for h in spec['colors']]
    forced = {norm_hex(k): v for k, v in (spec.get('levels') or {}).items()}
    for a in anchors:
        a.forced = forced.get(a.hex)
        if a.forced is not None and a.forced not in ANCHOR_LEVELS:
            warnings_pre = 'el nivel %d no es un nivel final permitido; se ignora' % a.forced
            a.forced = None
            spec.setdefault('_warnings', []).append(warnings_pre)
    rep = {'case': case, 'input': [a.hex for a in anchors], 'curve': curve, 'drift': drift}
    warnings = list(spec.pop('_warnings', []))
    for a in anchors:
        if len(a.name) > NAME_MAX:
            warnings.append('el nombre "%s" supera %d caracteres y puede no entrar en el ítem' % (a.name, NAME_MAX))
    if spec.get('requested') in ('B', 'C'):
        warnings.append('el caso %s necesita dos HEX; se generó como caso A' % spec['requested'])
    if case in ('B', 'C') and len(anchors) < 2:
        warnings.append('el caso %s necesita dos HEX; se generó como caso A' % case)
        case = rep['case'] = 'A'
    if case in ('B', 'C') and delta_e(anchors[0].hex, anchors[1].hex) <= DE_REUSE:
        keep = max(anchors, key=lambda a: a.C)
        warnings.append('los dos HEX son prácticamente iguales (ΔE %s); se generó como caso A con #%s'
                        % (('%.3f' % delta_e(anchors[0].hex, anchors[1].hex)).replace('.', ','), keep.hex))
        anchors = [keep]
        case = rep['case'] = 'A'
    if case == 'C' and {a.hex for a in anchors} == {'FFFFFF', '000000'}:
        warnings.append('blanco a negro: se generó la escala de neutros sobre la curva')
        anchors = [anchors[0]]
        case = rep['case'] = 'A'
    if case == 'B' and any(is_pure_bw(a) for a in anchors):
        bw = next(a for a in anchors if is_pure_bw(a))
        warnings.append('#%s ya es el extremo de toda escala (nivel %d); se generó como caso A con el otro color'
                        % (bw.hex, 0 if bw.hex == 'FFFFFF' else 1000))
        anchors = [a for a in anchors if not is_pure_bw(a)]
        case = rep['case'] = 'A'
    if case == 'A' and is_pure_bw(anchors[0]):
        steps = scale_neutral(curve)
        issues = validate(steps, [], monotone=True)
        rep['anchors'] = {}
        warnings.append('#%s es blanco o negro puro: no define un color; se generó una escala de neutros sin fijo'
                        % anchors[0].hex)
        title = spec.get('title') or 'Neutros'
        notes = spec.get('notes') or 'Caso A · #%s no define tono · escala de grises' % anchors[0].hex
    elif case == 'C':
        steps = scale_edges(*anchors)
        issues = validate(steps, anchors, monotone=False)
        title = spec.get('title') or 'Gradiente %s → %s' % (anchors[0].hex, anchors[1].hex)
        notes = spec.get('notes') or 'Caso C · extremos'
    elif case == 'A' or len(anchors) == 1:
        a = anchors[0]
        a.level = place_anchor(a, curve)
        steps = scale_anchored([a], curve, drift)
        issues = validate(steps, anchors)
        rep['anchors'] = {a.hex: a.level}
        title = spec.get('title') or (a.name or '#' + a.hex)
        notes = spec.get('notes') or 'Caso A · #%s en %d' % (a.hex, a.level)
    else:
        a1, a2 = anchors
        a1.level, a2.level = place_anchor(a1, curve), place_anchor(a2, curve)
        col = resolve_collision(a1, a2)
        if col:
            warnings.append(col)
        if a1.C >= CHROMATIC_C and a2.C >= CHROMATIC_C:
            rep['hue_difference'] = round(abs(hue_diff(a1.H, a2.H)), 1)
        light, dark = sorted(anchors, key=lambda a: -a.L)
        saturated = max(anchors, key=lambda a: (a.C, -a.L))
        muted = min(anchors, key=lambda a: a.C)
        if muted.C < CHROMATIC_C and saturated.C > 0.08:
            warnings.append('#%s es casi neutro y #%s tiene color: la escala une un neutro con un color'
                            % (muted.hex, saturated.hex))
        fixed = spec.get('fixed')
        # compatibilidad: ΔE del otro color contra su paso en la escala del más saturado
        other = a2 if saturated is a1 else a1
        probe = fit_analysis(saturated, other, curve, drift)[1]
        rep['compatibility'] = {k: probe[k] for k in ('fixed', 'other', 'other_level', 'suggested', 'delta_e', 'verdict')}
        rep['approved'] = probe['delta_e'] <= DE_ACCEPT
        if not fixed:
            fixed = 'ambos'
            if not rep['approved']:
                rep['split'] = True
                warnings.append('CASO B NO RECOMENDADO: los dos colores son muy distintos para una misma escala '
                                '(ΔE %s, el límite es %s). Se entregan la escala unida y, debajo, dos escalas '
                                'separadas (caso A).' % (('%.3f' % probe['delta_e']).replace('.', ','),
                                                         ('%.2f' % DE_ACCEPT).replace('.', ',')))
        if fixed == 'ambos':
            steps = scale_anchored(anchors, curve, drift)
            issues = validate(steps, anchors)
            rep['anchors'] = {a.hex: a.level for a in anchors}
            rep['mode'] = 'ambos fijos'
            if rep.get('hue_difference', 0) > SAME_FAMILY_DH:
                warnings.append('tonos a %.0f° de distancia: la escala hace de puente entre dos familias'
                                % rep['hue_difference'])
            if not rep['approved']:
                rep['alert'] = True
                for st in steps:
                    st['alert'] = st['fixed']
            title = spec.get('title') or ' + '.join((a.name or '#' + a.hex) for a in anchors)
            notes = spec.get('notes') or 'Caso B · ambos fijos · #%s en %d · #%s en %d%s' % (
                a1.hex, a1.level, a2.hex, a2.level,
                '' if rep['approved'] else ' · NO RECOMENDADA: se aconsejan dos escalas separadas')
        else:
            fx = {'claro': light, 'oscuro': dark, 'first': a1, 'second': a2, 'saturado': saturated}[fixed]
            ot = a2 if fx is a1 else a1
            steps, fit = fit_analysis(fx, ot, curve, drift)
            rep['fit'] = fit
            rep['mode'] = 'fijo #%s' % fx.hex
            issues = validate(steps, [fx])
            rep['anchors'] = {fx.hex: place_anchor(fx, curve)}
            title = spec.get('title') or (fx.name or '#' + fx.hex)
            notes = spec.get('notes') or ('Caso B · fijo #%s · en azul, el paso más parecido a #%s '
                                          '(mitad derecha = tu color) · ΔE %s · %s') % (
                fx.hex, ot.hex, ('%.3f' % fit['delta_e']).replace('.', ','), fit['verdict'])
    rep['steps'] = [{'level': s['level'], 'hex': s['hex'], 'fixed': s['fixed'],
                     'suggested': bool(s.get('suggested'))} for s in steps]
    rep['issues'] = issues
    rep['warnings'] = warnings
    return steps, rep, title, notes


def render_preview(rendered, out, name):
    """PNG de vista previa con Quick Look de macOS y PIL. Quick Look hace miniaturas cuadradas,
    así que se agrupan hasta 4 escalas por lienzo cuadrado (una sola apertura de qlmanage por
    grupo) y después se recorta el blanco. Usa fuentes de reemplazo: no tiene Geist ni Andale Mono."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    tmp = tempfile.mkdtemp(prefix='color-scales-preview-')
    width = max(w for _, w in rendered)
    per = max(1, width // SCALE_H)
    parts = []
    for g in range(0, len(rendered), per):
        group = rendered[g:g + per]
        body = ''.join('<g transform="translate(0 %d)">%s</g>' % (i * SCALE_H, _inner(svg))
                       for i, (svg, _) in enumerate(group))
        square = ('<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" '
                  'xmlns="http://www.w3.org/2000/svg"><rect width="%d" height="%d" fill="white"/>%s</svg>'
                  % (width, width, width, width, width, width, body))
        path = os.path.join(tmp, 'grupo-%d.svg' % g)
        with open(path, 'w') as fh:
            fh.write(square)
        subprocess.run(['qlmanage', '-t', '-s', '2400', '-o', tmp, path], capture_output=True)
        png = path + '.png'
        if not os.path.exists(png):
            return None
        im = Image.open(png).convert('RGB')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        box = ImageChops.difference(im, bg).getbbox()
        if box:
            im = im.crop((0, max(box[1] - 40, 0), im.width, min(box[3] + 40, im.height)))
        parts.append(im)
    W = max(p.width for p in parts)
    sheet = Image.new('RGB', (W, sum(p.height for p in parts)), (255, 255, 255))
    y = 0
    for p in parts:
        sheet.paste(p, (0, y))
        y += p.height
    dest = os.path.join(out, name + '.png')
    sheet.save(dest)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    return dest


# ─── Sesión, carpetas y exportación ───────────────────────────────────────
# Cada conversación tiene un identificador de sesión (lo crea la skill en la primera corrida).
# Cada escala generada en esa sesión recibe un código corto (01, 02…) que va en su título y se
# guarda en un registro, para elegir después cuáles exportar sin copiar HEX.
# Cada conversación tiene su carpeta en Descargas, con solo lo de esa conversación:
# ~/Downloads/colorscales_AAAA-MM-DD_HHMM/ (registro, hoja de candidatas, corridas y exportaciones).
BASE_DIR = os.path.expanduser('~/Downloads')
EXPORT_FORMATS = ('svg', 'css', 'tokens', 'config')


def slugify(text):
    import unicodedata
    t = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')


def clean_title(title):
    return title.replace('↳ ', '').strip()


def run_slug(project, titles):
    if project:
        return slugify(project) or 'escalas'
    parts = []
    for t in titles:
        for piece in clean_title(t).split(' + '):
            s = slugify(piece)
            if s and s not in parts:
                parts.append(s)
    if not parts:
        return 'escalas'
    if len(parts) > 3:
        return '-'.join(parts[:3]) + '-y-%d' % (len(parts) - 3)
    return '-'.join(parts)


def unique_dir(base, stem):
    path, n = os.path.join(base, stem), 2
    while os.path.exists(path):
        path, n = os.path.join(base, '%s-%d' % (stem, n)), n + 1
    os.makedirs(path)
    return path


def session_dir(base, session):
    path = os.path.join(base, 'colorscales_' + re.sub(r'[^0-9A-Za-z_-]+', '-', session))
    os.makedirs(path, exist_ok=True)
    return path


def stamp_hm():
    return datetime.datetime.now().strftime('%H%M')


def registry_path(base, session):
    # oculto: Finder no lo muestra; es lo que permite exportar después
    return os.path.join(session_dir(base, session), '.sesion.json')


def load_registry(base, session):
    path = registry_path(base, session)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    return {'session': session, 'scales': []}


def save_registry(base, session, reg):
    path = registry_path(base, session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2)


def scale_kind(rep, spec):
    if spec.get('derived'):
        return 'derivada'
    if rep.get('alert'):
        return 'no recomendada'
    if rep.get('case') == 'C':
        return 'degradé'
    if rep.get('fit'):
        return 'fijo y paso sugerido'
    return 'escala'


def config_spec(spec, rep, names):
    """Spec que reproduce exactamente esta escala con --spec."""
    out = {k: spec[k] for k in ('case', 'colors', 'fixed', 'levels', 'curve', 'drift', 'derived', 'notes')
           if spec.get(k) not in (None, {}, [])}
    if rep.get('alert'):
        out['fixed'] = 'ambos'  # la unida no recomendada, sin volver a generar sus derivadas
        out['comment'] = ('fixed=ambos lo pone el script para reproducir la escala unida sin volver a generar '
                          'sus separadas; no es un pedido del usuario')
    out['names'] = {h: names[norm_hex(h)] for h in spec['colors'] if names.get(norm_hex(h))}
    return out


def versions(scales):
    """Número de versión por título: dos 'Mist' con HEX distintos son versión 1 y 2."""
    seen, out = {}, {}
    for s in scales:
        t = clean_title(s['title']).lower()
        seen[t] = seen.get(t, 0) + 1
        out[s['code']] = seen[t]
    return out


def suggested_codes(scales):
    """Selección propuesta: la última versión de cada título; de una no recomendada, sus derivadas."""
    latest = {}
    for s in scales:
        latest[clean_title(s['title']).lower()] = s['code']
    keep = set(latest.values())
    for s in scales:
        if s['kind'] == 'no recomendada' and any(d.get('derived_from') == s['code'] for d in scales):
            keep.discard(s['code'])
            keep.update(d['code'] for d in scales if d.get('derived_from') == s['code'])
    return [s['code'] for s in scales if s['code'] in keep]


def color_value(hexv, fmt):
    if fmt == 'oklch':
        L, C, H = hex_to_oklch(hexv)
        return 'oklch(%.3f %.3f %.1f)' % (L, C, H if C > 0.0005 else 0)
    return '#' + hexv.lower()


def token_value(hexv, fmt):
    if fmt == 'oklch':
        L, C, H = hex_to_oklch(hexv)
        comps, space = [round(L, 4), round(C, 4), round(H if C > 0.0005 else 0, 2)], 'oklch'
    else:
        comps, space = [round(int(hexv[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)], 'srgb'
    return {'colorSpace': space, 'components': comps, 'hex': '#' + hexv.lower()}


def var_names(scales):
    """Nombre de variable por escala: el título en minúsculas; sin nombre, color-1, color-2…"""
    used, out, unnamed = {}, {}, 0
    for s in scales:
        t = clean_title(s['title'])
        base = '' if t.startswith('#') or t.startswith('Gradiente') else slugify(t)
        if not base:
            unnamed += 1
            base = 'color-%d' % unnamed
        n = used.get(base, 0) + 1
        used[base] = n
        out[s['code']] = base if n == 1 else '%s-%d' % (base, n)
    return out


def export_css(scales, fmt):
    names = var_names(scales)
    lines = [':root {']
    for i, s in enumerate(scales):
        if i:
            lines.append('')
        lines.append('  /* %s · %s */' % (clean_title(s['title']), s['code']))
        for st in s['steps']:
            if st['level'] in FINAL13:
                lines.append('  --color-%s-%d: %s;' % (names[s['code']], st['level'], color_value(st['hex'], fmt)))
    lines.append('}')
    return '\n'.join(lines) + '\n'


def export_tokens(scales, fmt):
    """Tokens en el formato estándar DTCG 2025.10 (grupo 'color' con $type heredado)."""
    names = var_names(scales)
    group = {'$type': 'color'}
    for s in scales:
        scale = {}
        for st in s['steps']:
            if st['level'] in FINAL13:
                tok = {'$value': token_value(st['hex'], fmt)}
                if st['fixed']:
                    tok['$description'] = 'color de marca: %s' % (s['names'].get(st['hex']) or '#' + st['hex'])
                scale[str(st['level'])] = tok
        group[names[s['code']]] = scale
    return json.dumps({'color': group}, ensure_ascii=False, indent=2) + '\n'


def copy_clipboard(svg_code):
    try:
        # pbcopy/pbpaste dependen de la configuración regional: sin UTF-8 los caracteres
        # como Á, · o ↳ pueden salir mal. Se fuerza UTF-8 en ambos.
        env = dict(os.environ, LC_ALL='en_US.UTF-8')
        subprocess.run(['pbcopy'], input=svg_code.encode(), check=True, env=env)
        back = subprocess.run(['pbpaste'], capture_output=True, env=env).stdout
        return {'copied': back == svg_code.encode(), 'bytes': len(back)}
    except (OSError, subprocess.CalledProcessError) as exc:
        return {'copied': False, 'error': str(exc)}


def run_candidates(args, base):
    reg = load_registry(base, args.session)
    scales = reg['scales']
    if not scales:
        return {'error': 'La sesión %s no tiene escalas registradas.' % args.session}
    ver = versions(scales)
    sug = suggested_codes(scales)
    result = {'session': args.session, 'suggested': sug, 'candidates': [
        {'code': s['code'], 'title': clean_title(s['title']), 'kind': s['kind'],
         'colors': ['#%s@%s' % (h, s['anchors'].get(h, '-')) for h in s['colors']],
         'version': ver[s['code']], 'derived_from': s.get('derived_from'),
         'suggested': s['code'] in sug} for s in scales]}
    if args.preview:
        result['preview'] = render_preview([(s['svg'], s['width']) for s in scales],
                                           tempfile.mkdtemp(prefix='color-scales-'), 'candidatas')
    return result


def run_export(args, base):
    reg = load_registry(base, args.session)
    by_code = {s['code']: s for s in reg['scales']}
    codes = ['%02d' % int(c) for c in re.findall(r'\d+', args.export)]
    missing = [c for c in codes if c not in by_code]
    if not codes or missing:
        return {'error': 'Códigos que no existen en la sesión %s: %s' % (args.session, ', '.join(missing) or args.export),
                'available': sorted(by_code)}
    chosen = [by_code[c] for c in dict.fromkeys(codes)]
    formats = [f.strip() for f in args.formats.split(',') if f.strip()]
    bad = [f for f in formats if f not in EXPORT_FORMATS]
    if bad:
        return {'error': 'Formatos desconocidos: %s (válidos: %s)' % (', '.join(bad), ', '.join(EXPORT_FORMATS))}
    slug = run_slug(args.project, [s['title'] for s in chosen])
    folder = unique_dir(session_dir(base, args.session), stamp_hm() + '_export_' + slug)
    files = {}
    if 'svg' in formats:
        svg_code = svg_stack([(clean_svg(s['svg']), s['width']) for s in chosen], EXPORT_H)
        files['svg'] = os.path.join(folder, slug + '.svg')
        with open(files['svg'], 'w') as fh:
            fh.write(svg_code)
    if 'css' in formats:
        files['css'] = os.path.join(folder, slug + '.css')
        with open(files['css'], 'w') as fh:
            fh.write(export_css(chosen, args.color_format))
    if 'tokens' in formats:
        files['tokens'] = os.path.join(folder, slug + '.tokens.json')
        with open(files['tokens'], 'w') as fh:
            fh.write(export_tokens(chosen, args.color_format))
    if 'config' in formats:
        files['config'] = os.path.join(folder, slug + '.config.json')
        with open(files['config'], 'w', encoding='utf-8') as fh:
            json.dump({'version': 1, 'scales': [s['spec'] for s in chosen]}, fh, ensure_ascii=False, indent=2)
    result = {'session': args.session, 'exported': codes, 'format': args.color_format, 'folder': folder,
              'files': files, 'variables': var_names(chosen)}
    if args.copy and 'svg' in formats:
        result['clipboard'] = copy_clipboard(svg_code)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--lines')
    p.add_argument('--spec')
    p.add_argument('--out', default=None,
                   help='carpeta donde se guarda el SVG de respaldo (por defecto ~/Downloads)')
    p.add_argument('--copy', action='store_true',
                   help='copia el SVG completo al portapapeles (se verifica leyéndolo de vuelta)')
    p.add_argument('--name', default=None, help='nombre del archivo, sin extensión (por defecto escalas-AAAA-MM-DD-HHMM)')
    p.add_argument('--no-drift', dest='drift', action='store_false',
                   help='tono constante (sin la deriva medida en Tailwind)')
    p.add_argument('--names', nargs='*', default=[])
    p.add_argument('--table', action='store_true')
    p.add_argument('--pairs', action='store_true')
    p.add_argument('--preview', action='store_true')
    p.add_argument('--session', default=None,
                   help='identificador de la conversación: numera cada escala (01, 02…) y la registra para exportar')
    p.add_argument('--project', default=None, help='nombre del proyecto para la carpeta y los archivos')
    p.add_argument('--base', default=None, help='carpeta raíz de las corridas (por defecto ~/Downloads)')
    p.add_argument('--candidates', action='store_true',
                   help='lista las escalas de la sesión con su código y la selección propuesta (con --preview, hoja visual)')
    p.add_argument('--export', default=None, help='códigos de la sesión a exportar, por ejemplo "03 05 06"')
    p.add_argument('--formats', default='svg,css,tokens,config', help='svg, css, tokens y/o config, separados por coma')
    p.add_argument('--color-format', choices=['hex', 'oklch'], default='hex')
    args = p.parse_args()
    base = os.path.expanduser(args.base) if args.base else BASE_DIR
    if not args.session and not args.out and not (args.candidates or args.export):
        # sin sesión indicada, la corrida abre una nueva (la skill la reusa en las siguientes)
        args.session = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')

    if args.candidates or args.export:
        if not args.session:
            print(json.dumps({'error': 'Para listar o exportar hace falta --session.'}, ensure_ascii=False))
            sys.exit(1)
        result = run_candidates(args, base) if args.candidates else run_export(args, base)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1 if 'error' in result else 0)

    ignored = []
    if args.spec:
        with open(args.spec) as fh:
            specs = json.load(fh)['scales']
    elif args.lines is not None:
        specs, ignored = parse_lines(args.lines.replace('\\n', '\n'))
    else:
        specs, ignored = parse_lines(sys.stdin.read())
    if not specs:
        print(json.dumps({'error': 'No se encontró ningún HEX válido (6 dígitos) en la entrada.',
                          'ignored_lines': ignored}, ensure_ascii=False, indent=2))
        sys.exit(1)

    names = {}
    for item in args.names:
        k, _, v = item.partition('=')
        names[norm_hex(k)] = v.strip()
    defaults = {'curve': 'tailwind', 'drift': args.drift}
    levels = FINAL13

    rendered, reports, entries, run_specs, titles = [], [], [], [], []
    reg = load_registry(base, args.session) if args.session else None

    def emit(spec, parent=None):
        try:
            steps, rep, title, notes = build(dict(spec), defaults, names)
        except Exception as exc:  # una línea rota no frena las demás
            reports.append({'input': spec.get('colors'), 'error': str(exc)})
            return None
        shown = [s for s in steps if s['level'] in levels]
        if spec.get('derived'):
            title = '↳ ' + title
            notes = '↳ ' + notes
            rep['derived'] = True
        code = None
        if reg is not None:
            code = '%02d' % (len(reg['scales']) + len(entries) + 1)
            rep['code'] = code
        svg, width = svg_scale(shown, title, notes, alert=bool(rep.get('alert')), code=code)
        rendered.append((svg, width))
        titles.append(title)
        if code:
            entries.append({'code': code, 'title': title, 'kind': scale_kind(rep, spec), 'case': rep['case'],
                            'colors': rep['input'], 'anchors': rep.get('anchors', {}),
                            'names': {h: names.get(h, '') for h in rep['input']},
                            'approved': rep.get('approved'), 'derived_from': parent,
                            'steps': [{'level': s['level'], 'hex': s['hex'], 'fixed': s['fixed']} for s in steps],
                            'spec': config_spec(spec, rep, names), 'svg': svg, 'width': width})
        if args.table:
            rep['table'] = table_rows(steps, levels)
        if args.pairs and rep['case'] != 'C':
            rep['pairs'] = pair_report([s for s in steps if s['level'] in FINAL13])
        reports.append(rep)
        return rep

    groups = []
    for spec in specs:
        start = len(rendered)
        for h, n in (spec.get('names') or {}).items():
            names[norm_hex(h)] = n
        run_specs.append({k: v for k, v in spec.items() if v not in (None, {}, [])})
        run_specs[-1]['names'] = {h: names[norm_hex(h)] for h in spec['colors'] if names.get(norm_hex(h))}
        rep = emit(spec)
        if rep and rep.get('split'):
            for h in rep['input']:
                emit({'case': 'A', 'colors': [h], 'levels': spec.get('levels'), 'derived': True,
                      'curve': spec.get('curve', 'tailwind'), 'drift': spec.get('drift', args.drift),
                      'notes': 'Caso A · escala separada derivada de la no recomendada · #%s (el caso B con #%s no se recomienda)'
                               % (h, ' y #'.join(x for x in rep['input'] if x != h))}, parent=rep.get('code'))
        if len(rendered) > start:
            groups.append(list(range(start, len(rendered))))

    # Entrega: el SVG completo (todas las escalas apiladas) se copia al portapapeles y se
    # guarda, con la vista previa y la config de la corrida, en la carpeta de la conversación:
    # ~/Downloads/colorscales_<sesión>/HHMM_<nombres o proyecto>.svg. Con --out, todo va
    # directo a esa carpeta (como lo usan las pruebas internas).
    if not rendered:
        print(json.dumps({'error': 'No se pudo generar ninguna escala.', 'scales': reports,
                          'ignored_lines': ignored}, ensure_ascii=False, indent=2))
        sys.exit(1)
    if args.out:
        out = args.out
        os.makedirs(out, exist_ok=True)
        name = args.name or 'escalas-' + datetime.datetime.now().strftime('%Y-%m-%d-%H%M')
    else:
        out = session_dir(base, args.session)
        stem = stamp_hm() + '_' + (args.name or run_slug(args.project, [t for t in titles if not t.startswith('↳ ')]))
        name, n = stem, 2
        while os.path.exists(os.path.join(out, name + '.svg')):
            name, n = '%s-%d' % (stem, n), n + 1
    svg_path = os.path.join(out, name + '.svg')
    svg_code = svg_stack(rendered)
    with open(svg_path, 'w') as fh:
        fh.write(svg_code)
    # Al explorar solo queda el SVG de respaldo; la config de cada escala va al registro y se
    # entrega recién al exportar. Con --out se guarda también la config de la corrida.
    result = {'folder': out, 'svg': svg_path, 'svg_bytes': len(svg_code.encode()), 'scales': reports}
    if args.out:
        result['config'] = os.path.join(out, name + '.config.json')
        with open(result['config'], 'w', encoding='utf-8') as fh:
            json.dump({'version': 1, 'scales': run_specs}, fh, ensure_ascii=False, indent=2)
    if reg is not None:
        for e in entries:
            e['run'] = out
        reg['scales'].extend(entries)
        save_registry(base, args.session, reg)
        result['session'] = args.session
        result['codes'] = [e['code'] for e in entries]
    if args.copy:
        result['clipboard'] = copy_clipboard(svg_code)
    if ignored:
        result['ignored_lines'] = ignored
    if args.preview:
        # la vista previa es para mostrarla en el chat: va a una carpeta temporal, no a Descargas
        result['preview'] = render_preview(rendered, out if args.out else tempfile.mkdtemp(prefix='color-scales-'), name)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
