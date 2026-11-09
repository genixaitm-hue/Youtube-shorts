#!/usr/bin/env python3
"""Falklands War geopolitical Short renderer.
Usage: python3 render_video.py [--test t1 t2 ...] [--out final_video.mp4]
Data: Natural Earth 10m admin-0 countries (project_assets/maps). Flags: flag-icons (MIT).
"""
import os, sys, re, math, io, pickle, subprocess
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import geopandas as gpd, shapely
from shapely.geometry import box
from pyproj import Geod
import cairosvg
import content as C

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "project_assets")
W, H, FPS = 1080, 1920, 30
DUR = C.DURATION
NF = int(round(DUR * FPS))
SY = 900  # screen y of camera centre (a bit above middle: keeps map clear of captions)
R = 6378137.0

# ---------- palette (RGB) ----------
def bgr(rgb): return (rgb[2], rgb[1], rgb[0])
OCEAN_T, OCEAN_B = (4, 10, 26), (9, 26, 56)
GRAY, GRAY_EDGE = (36, 42, 54), (66, 76, 96)
EMERALD, EMERALD_E = (14, 138, 100), (70, 228, 170)
CRIMSON, CRIMSON_E = (190, 32, 56), (255, 96, 116)
GOLD, WHITE = (255, 198, 64), (246, 248, 252)

def lerp(a, b, u): return tuple(a[i] + (b[i] - a[i]) * u for i in range(3))
def sstep(u): u = min(max(u, 0.0), 1.0); return u * u * u * (u * (u * 6 - 15) + 10)
def ramp(t, t0, t1): return sstep((t - t0) / (t1 - t0))
def win(t, a, b, fi=0.3, fo=0.3):
    """alpha window: fade in at a, fade out ending at b"""
    return ramp(t, a, a + fi) * (1 - ramp(t, b - fo, b))

def merc(lon, lat):
    lon = np.asarray(lon, float); lat = np.asarray(lat, float)
    return R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))

# ---------- geography ----------
LODS = [4000, 1200, 400, 0]
def prep_geo():
    cache = os.path.join(HERE, ".geo_cache.pkl")
    if os.path.exists(cache):
        return pickle.load(open(cache, "rb"))
    g = gpd.read_file(os.path.join(A, "maps", "ne_10m_admin_0_countries.geojson"))
    clip = box(-180, -78, 180, 84)
    fn = lambda c: np.column_stack(merc(c[:, 0], c[:, 1]))
    groups = {}
    for _, r in g.iterrows():
        geom = r.geometry.intersection(clip)
        if geom.is_empty: continue
        a3 = r.ADM0_A3
        grp = a3 if a3 in ("ARG", "GBR", "FLK", "SGS") else "OTHER"
        groups.setdefault(grp, []).append(shapely.transform(geom, fn))
    out = {}
    for grp, geoms in groups.items():
        u = shapely.union_all(geoms) if grp != "OTHER" else shapely.GeometryCollection(geoms)
        per = {}
        for tol in LODS:
            gg = u.simplify(tol, preserve_topology=True) if tol else u
            polys = []
            for p in shapely.get_parts(shapely.get_parts(gg)) if gg.geom_type == "GeometryCollection" else (gg.geoms if hasattr(gg, "geoms") else [gg]):
                for q in (p.geoms if hasattr(p, "geoms") else [p]):
                    if q.geom_type != "Polygon" or q.is_empty: continue
                    rings = [np.asarray(q.exterior.coords)] + [np.asarray(i.coords) for i in q.interiors]
                    polys.append((q.bounds, rings))
            per[tol] = polys
        out[grp] = per
    pickle.dump(out, open(cache, "wb"))
    return out

GEO = prep_geo()

# ---------- camera ----------
KEYS = [  # t, lon, lat, metres-per-pixel (Mercator)
    (0.0, -31, 6.3, 19500), (5.4, -31, 6.3, 18600), (8.4, -62, -50.8, 3000), (12.4, -62, -51.0, 2850),
    (14.0, -62.0, -53.3, 1650), (15.2, -62.0, -53.3, 1650), (16.9, -47.5, -53.8, 3900),
    (17.6, -47.5, -53.8, 3900), (19.2, -31, 6.3, 19000), (21.7, -31, 6.3, 18400),
    (23.2, -45, -52.5, 4300), (24.2, -45, -52.5, 4300), (26.2, -58.8, -51.75, 340),
    (30.0, -58.5, -51.72, 310), (35.0, -58.0, -51.7, 280), (38.0, -60.5, -51.5, 2800),
    (46.0, -60.5, -51.5, 2600), (49.8, -31, 3.3, 20500), (54.0, -31, 3.3, 19800)]
KX = [(k[0], *merc(k[1], k[2]), math.log(k[3])) for k in KEYS]

def camera(t):
    for i in range(len(KX) - 1):
        a, b = KX[i], KX[i + 1]
        if a[0] <= t <= b[0]:
            u = sstep((t - a[0]) / (b[0] - a[0]))
            m = math.exp(a[3] + (b[3] - a[3]) * u); ma, mb = math.exp(a[3]), math.exp(b[3])
            # big zooms: keep one world point fixed on screen (zoom-about-a-point) so the target never leaves frame
            s_ = (ma - m) / (ma - mb) if abs(a[3] - b[3]) > 0.12 else u
            x = a[1] + (b[1] - a[1]) * s_; y = a[2] + (b[2] - a[2]) * s_
            return x + 5 * m * math.sin(t * .45), y + 4 * m * math.cos(t * .37), m
    k = KX[-1]; return k[1], k[2], math.exp(k[3])

# ---------- drawing primitives ----------
class Layer:
    """premultiplied-alpha vector layer (img = colour*alpha, m = alpha)"""
    def __init__(self, scale=1.0):
        self.s = scale; h, w = int(H * scale), int(W * scale)
        self.img = np.zeros((h, w, 3), np.uint8); self.m = np.zeros((h, w), np.uint8)
    def _p(self, pts):
        return np.round(np.asarray(pts, float) * self.s * 16).astype(np.int64).clip(-2**30, 2**30).astype(np.int32)
    def poly(self, pts, color, alpha=1.0, th=2, closed=False):
        if alpha <= 0.003: return
        p = self._p(pts).reshape(-1, 1, 2); c = tuple(float(x) * alpha for x in bgr(color)); a = (255 * alpha,)
        t = max(1, int(round(th * self.s)))
        cv2.polylines(self.img, [p], closed, c, t, cv2.LINE_AA, 4); cv2.polylines(self.m, [p], closed, a, t, cv2.LINE_AA, 4)
    def fill(self, rings, color, alpha=1.0):
        if alpha <= 0.003: return
        ps = [self._p(r).reshape(-1, 1, 2) for r in rings]; c = tuple(float(x) * alpha for x in bgr(color))
        cv2.fillPoly(self.img, ps, c, cv2.LINE_AA, 4); cv2.fillPoly(self.m, ps, (255 * alpha,), cv2.LINE_AA, 4)
    def circle(self, c, r, color, alpha=1.0, th=-1):
        if alpha <= 0.003: return
        ctr = (int(round(c[0] * self.s * 16)), int(round(c[1] * self.s * 16))); rr = int(round(r * self.s * 16))
        t = th if th < 0 else max(1, int(round(th * self.s)))
        col = tuple(float(x) * alpha for x in bgr(color))
        cv2.circle(self.img, ctr, rr, col, t, cv2.LINE_AA, 4); cv2.circle(self.m, ctr, rr, (255 * alpha,), t, cv2.LINE_AA, 4)
    def arc(self, c, r, a0, a1, color, alpha, th):
        ctr = (int(round(c[0] * self.s * 16)), int(round(c[1] * self.s * 16))); rr = int(round(r * self.s * 16))
        col = tuple(float(x) * alpha for x in bgr(color)); t = max(1, int(round(th * self.s)))
        cv2.ellipse(self.img, ctr, (rr, rr), 0, a0, a1, col, t, cv2.LINE_AA, 4)
        cv2.ellipse(self.m, ctr, (rr, rr), 0, a0, a1, (255 * alpha,), t, cv2.LINE_AA, 4)

def composite(frame, lay, gain=1.0):
    img, m = lay.img, lay.m
    if lay.s != 1.0:
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_LINEAR); m = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR)
    f = frame.astype(np.uint16) * (255 - m[..., None].astype(np.uint16)) // 255 + img
    return np.clip(f, 0, 255).astype(np.uint8)

# ---------- text / sprites ----------
FONTS = {}
def font(sz, w="Bold"):
    k = (sz, w)
    if k not in FONTS: FONTS[k] = ImageFont.truetype(os.path.join(A, "fonts", f"Poppins-{w}.ttf"), sz)
    return FONTS[k]

CMAP = {"g": GOLD, "r": (255, 92, 110), "e": (64, 226, 164), "w": WHITE}
def parse(s):
    out, pos = [], 0
    for m in re.finditer(r"\{(\w):([^}]*)\}", s):
        if m.start() > pos: out.append((s[pos:m.start()], WHITE))
        out.append((m.group(2), CMAP[m.group(1)])); pos = m.end()
    if pos < len(s): out.append((s[pos:], WHITE))
    return out

class Sprite:
    def __init__(self, rgba):  # rgba PIL
        a = np.asarray(rgba); self.bgr = a[..., [2, 1, 0]].copy(); self.a = a[..., 3].astype(np.float32) / 255.0
        self.h, self.w = self.a.shape

def blit(frame, spr, x, y, alpha=1.0, scale=1.0, anchor="c"):
    if alpha <= 0.003: return
    b, a = spr.bgr, spr.a
    if abs(scale - 1) > 1e-3:
        nw, nh = max(1, int(spr.w * scale)), max(1, int(spr.h * scale))
        b = cv2.resize(b, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        a = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_LINEAR)
    h, w = a.shape
    x0 = int(x - (w / 2 if anchor == "c" else 0 if anchor == "l" else w)); y0 = int(y - h / 2)
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if X0 >= X1 or Y0 >= Y1: return
    sb = b[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0].astype(np.float32); sa = (a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * alpha)[..., None]
    roi = frame[Y0:Y1, X0:X1].astype(np.float32)
    frame[Y0:Y1, X0:X1] = (roi * (1 - sa) + sb * sa).astype(np.uint8)

_text_cache = {}
def text_sprite(text, size, color=WHITE, w="Bold", track=0, stroke=0, shadow=True):
    key = (text, size, color, w, track, stroke, shadow)
    if key in _text_cache: return _text_cache[key]
    f = font(size, w); pad = 24 + stroke
    if track:
        wd = sum(f.getlength(ch) + track for ch in text)
    else:
        wd = f.getlength(text)
    img = Image.new("RGBA", (int(wd) + pad * 2, int(size * 1.55) + pad * 2), (0, 0, 0, 0))
    def draw(layer, fill, st=0, off=(0, 0)):
        d = ImageDraw.Draw(layer); x = pad + off[0]
        if track:
            for ch in text:
                d.text((x, pad + off[1]), ch, font=f, fill=fill, stroke_width=st, stroke_fill=fill); x += f.getlength(ch) + track
        else:
            d.text((x, pad + off[1]), text, font=f, fill=fill, stroke_width=st, stroke_fill=fill)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); draw(sh, (0, 0, 0, 200), stroke + 2, (0, 4))
        sh = sh.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(6)); img = Image.alpha_composite(img, sh)
    if stroke: 
        st = Image.new("RGBA", img.size, (0, 0, 0, 0)); draw(st, (0, 0, 0, 235), stroke); img = Image.alpha_composite(img, st)
    top = Image.new("RGBA", img.size, (0, 0, 0, 0)); draw(top, tuple(color) + (255,)); img = Image.alpha_composite(img, top)
    s = Sprite(img); _text_cache[key] = s; return s

_line_cache = {}
def caption_line(markup):
    if markup in _line_cache: return _line_cache[markup]
    segs = parse(markup)
    for size in range(72, 44, -2):
        f = font(size); tw = sum(f.getlength(t) for t, _ in segs)
        if tw <= 930: break
    pad = 30
    img = Image.new("RGBA", (int(tw) + pad * 2, int(size * 1.6) + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); st = Image.new("RGBA", img.size, (0, 0, 0, 0)); top = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x = pad
    for t, c in segs:
        ImageDraw.Draw(sh).text((x, pad + 5), t, font=f, fill=(0, 0, 0, 220), stroke_width=8, stroke_fill=(0, 0, 0, 220))
        ImageDraw.Draw(st).text((x, pad), t, font=f, fill=(0, 0, 0, 240), stroke_width=7, stroke_fill=(0, 0, 0, 240))
        ImageDraw.Draw(top).text((x, pad), t, font=f, fill=tuple(c) + (255,)); x += f.getlength(t)
    from PIL import ImageFilter
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(7)))
    img = Image.alpha_composite(Image.alpha_composite(img, st), top)
    s = Sprite(img); _line_cache[markup] = s; return s

# ---------- flags ----------
def flag_img(code, wpx):
    png = cairosvg.svg2png(url=os.path.join(A, "flags", f"{code}.svg"), output_width=wpx * 2)
    im = Image.open(io.BytesIO(png)).convert("RGBA"); h = im.height
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, h - 1], radius=int(h * .14), fill=255)
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), m))
    ImageDraw.Draw(im).rounded_rectangle([1, 1, im.width - 2, h - 2], radius=int(h * .14), outline=(255, 255, 255, 235), width=4)
    return im.resize((wpx, int(h / 2)), Image.LANCZOS)

_flag_cache = {}
def flag_sprite(code, wpx):
    k = (code, wpx)
    if k not in _flag_cache:
        im = flag_img(code, wpx); pad = 26
        canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
        from PIL import ImageFilter
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); sh.paste((0, 0, 0, 190), (pad, pad + 6, pad + im.width, pad + im.height + 6))
        canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(9))); canvas.alpha_composite(im, (pad, pad))
        _flag_cache[k] = Sprite(canvas)
    return _flag_cache[k]

_label_cache = {}
def label_sprite(text, sub=None, flag=None, size=34, accent=GOLD):
    k = (text, sub, flag, size)
    if k in _label_cache: return _label_cache[k]
    S = 2; f = font(size * S); fs = font(int(size * .62) * S, "Medium")
    tw = f.getlength(text) + len(text) * 2 * S
    sw = (fs.getlength(sub) + len(sub) * 1.5 * S) if sub else 0
    fl = flag_img(flag, int(size * 1.9 * S)) if flag else None
    padx, pady = 22 * S, 14 * S
    inner_w = max(tw, sw); h = int(size * 1.25 * S) + (int(size * .9 * S) if sub else 0)
    wid = int(inner_w + padx * 2 + (fl.width + 16 * S if fl else 0)); hei = int(h + pady * 2)
    img = Image.new("RGBA", (wid + 40 * S, hei + 40 * S), (0, 0, 0, 0)); d = ImageDraw.Draw(img); o = 20 * S
    d.rounded_rectangle([o, o, o + wid, o + hei], radius=int(14 * S), fill=(6, 14, 32, 214), outline=tuple(accent) + (230,), width=2 * S)
    x = o + padx
    if fl:
        img.alpha_composite(fl, (x, o + (hei - fl.height) // 2)); x += fl.width + 16 * S
    def spaced(xx, yy, s, ff, fill, tr):
        for ch in s: d.text((xx, yy), ch, font=ff, fill=fill); xx += ff.getlength(ch) + tr
    ty = o + pady - 2 * S
    spaced(x, ty, text, f, (255, 255, 255, 255), 2 * S)
    if sub: spaced(x, ty + int(size * 1.28 * S), sub, fs, tuple(accent) + (255,), 1.5 * S)
    img = img.resize((img.width // S, img.height // S), Image.LANCZOS)
    s = Sprite(img); _label_cache[k] = s; return s

# ---------- places & routes ----------
P = dict(london=(-0.12, 51.5), stanley=(-57.85, -51.69), portsmouth=(-1.09, 50.80), ascension=(-14.36, -7.94),
         sgeorgia=(-36.5, -54.3), sancarlos=(-59.03, -51.50), uk=(-2.5, 54.3), arg=(-66.0, -27.0), fk=(-59.4, -51.8))
geod = Geod(ellps="WGS84")
ARC = np.array(geod.npts(*P["london"], *P["stanley"], 80)); ARC = np.vstack([P["london"], ARC, P["stanley"]])
ROUTE_WP = [(-1.09, 50.8), (-12, 44), (-20, 30), (-19, 10), (-14.36, -7.94), (-25, -22), (-42, -40), (-57.2, -51.2)]
def smooth_path(wps, n=300):
    p = np.array(wps, float); p = np.vstack([p[0], p, p[-1]]); out = []
    for i in range(1, len(p) - 2):
        for s in np.linspace(0, 1, n // (len(wps) - 1), endpoint=False):
            t = s; p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
            out.append(.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(p[-2]); return np.array(out)
ROUTE = smooth_path(ROUTE_WP)
LAND_ARROW = np.array([(-59.62, -51.12), (-59.03, -51.50)])
ADV = np.array([(-59.03, -51.50), (-58.6, -51.52), (-58.25, -51.62), (-57.92, -51.68)])
INV_FROM = (-63.9, -54.5)

CX = lambda lonlat: merc(lonlat[..., 0], lonlat[..., 1])

class View:
    def __init__(self, t):
        self.cx, self.cy, self.mpp = camera(t)
    def pt(self, lon, lat):
        x, y = merc(lon, lat); return float(W / 2 + (x - self.cx) / self.mpp), float(SY - (y - self.cy) / self.mpp)
    def pts(self, lonlats):
        a = np.asarray(lonlats, float); x, y = merc(a[:, 0], a[:, 1])
        return np.column_stack([W / 2 + (x - self.cx) / self.mpp, SY - (y - self.cy) / self.mpp])
    def rings(self, rings, bounds):
        x0 = W / 2 + (bounds[0] - self.cx) / self.mpp; x1 = W / 2 + (bounds[2] - self.cx) / self.mpp
        y1 = SY - (bounds[1] - self.cy) / self.mpp; y0 = SY - (bounds[3] - self.cy) / self.mpp
        if x1 < -40 or x0 > W + 40 or y1 < -40 or y0 > H + 40: return None
        return [np.column_stack([W / 2 + (r[:, 0] - self.cx) / self.mpp, SY - (r[:, 1] - self.cy) / self.mpp]) for r in rings]

# ---------- static backgrounds ----------
yy = np.linspace(0, 1, H)[:, None, None]
BG = (np.array(bgr(OCEAN_T), np.float32) * (1 - yy) + np.array(bgr(OCEAN_B), np.float32) * yy) * np.ones((1, W, 1), np.float32)
gx, gy = np.meshgrid(np.linspace(-1, 1, W), np.linspace(-1, 1, H))
VIG = np.clip(1.08 - 0.42 * (gx ** 2 * .9 + gy ** 2 * .6), 0.45, 1.0).astype(np.float32)[..., None]
GRAD = np.clip((np.arange(H) - 1100) / 520, 0, 1)[:, None] ** 1.3 * 0.62  # caption scrim
GRAD[1700:] = GRAD[1700]
TOPG = np.clip((300 - np.arange(H)) / 300, 0, 1)[:, None] ** 1.5 * 0.5
rng = np.random.default_rng(7)
PART = rng.random((70, 4))

def pick(grp, mpp):
    tol = [l for l in LODS if l <= 0.4 * mpp][-1] if mpp * .4 >= LODS[0] else 0
    tol = max([l for l in LODS if l <= 0.4 * mpp] or [0]) if mpp * .4 >= 4000 else ([l for l in LODS if l <= 0.4 * mpp] or [0])[-1]
    return GEO[grp][tol]

def lod_for(mpp):
    c = [l for l in LODS if l and l <= 0.4 * mpp]
    return max(c) if c else (0 if mpp * .4 < LODS[2] else LODS[2])

def occupation(t):
    fk = ramp(t, 12.9, 14.6) * (1 - ramp(t, 30.3, 32.0))
    sg = ramp(t, 15.3, 16.6) * (1 - ramp(t, 22.8, 23.8))
    return fk, sg

# ---------- frame ----------
def dashed(L, G, pts, prog, color, alpha, th, t, dash=26, gap=16, head=True, glow=0.5):
    if prog <= 0.001 or len(pts) < 2: return
    seg = np.hypot(*np.diff(pts, axis=0).T); cum = np.concatenate([[0], np.cumsum(seg)]); total = cum[-1]; end = total * prog
    if total < 4: return
    period = dash + gap; off = -(t * 70) % period; d = -off
    def at(s):
        i = min(np.searchsorted(cum, s, side="right") - 1, len(seg) - 1)
        u = (s - cum[i]) / max(seg[i], 1e-6); return pts[i] + (pts[i + 1] - pts[i]) * u
    while d < end:
        s0, s1 = max(d, 0), min(d + dash, end)
        if s1 > s0:
            sub = [at(s0)] + [pts[i] for i in range(len(pts)) if s0 < cum[i] < s1] + [at(s1)]
            L.poly(sub, color, alpha, th); G.poly(sub, color, glow * alpha, th * 3)
        d += period
    if head and prog > 0.02:
        tip = at(end); back = at(max(end - 30, 0)); v = tip - back; n = np.hypot(*v) or 1; v = v / n; nrm = np.array([-v[1], v[0]])
        tri = np.array([tip + v * 14, tip - v * 22 + nrm * 17, tip - v * 22 - nrm * 17])
        L.fill([tri], color, alpha); G.fill([tri], color, glow * alpha)

def pin(L, G, xy, color, t, alpha=1.0, r=11, pulse=True, ph=0.0):
    if alpha <= 0.01: return
    if pulse:
        for k in range(2):
            u = ((t * .8 + ph + k * .5) % 1.0)
            L.circle(xy, r + 6 + 46 * u, color, alpha * (1 - u) * .8, 3); G.circle(xy, r + 6 + 46 * u, color, alpha * (1 - u), 5)
    L.circle(xy, r + 4, (255, 255, 255), alpha); L.circle(xy, r, color, alpha); G.circle(xy, r + 8, color, alpha * .9)

def render(t):
    V = View(t); mpp = V.mpp; tol = lod_for(mpp)
    frame = BG.copy()
    # coastal glow (continental-shelf feel)
    gm = np.zeros((H // 4, W // 4), np.uint8)
    polys = {}
    for grp in GEO:
        L_ = []
        for b, rings in GEO[grp][tol]:
            r = V.rings(rings, b)
            if r is not None: L_.append(r)
        polys[grp] = L_
        for r in L_:
            cv2.fillPoly(gm, [np.round(x * 4).astype(np.int32).reshape(-1, 1, 2) for x in [q / 4 for q in r]] if False else [np.round(q / 4 * 16).astype(np.int64).clip(-2**30, 2**30).astype(np.int32).reshape(-1, 1, 2) for q in r], 255, cv2.LINE_AA, 4)
    sig = float(np.clip(30 / max(1, mpp / 3000 + 1) + 10, 10, 30)) / 4
    gl = cv2.GaussianBlur(gm, (0, 0), sig * 2.2).astype(np.float32) / 255.0
    gl = cv2.resize(gl, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
    frame = frame + gl * np.array(bgr((22, 74, 140)), np.float32) * .62
    frame = np.clip(frame, 0, 255).astype(np.uint8)

    # graticule
    Lg = Layer()
    step = [s for s in (20, 10, 5, 2, 1, .5, .25, .1) if s * 111320 * 0.6 / mpp > 230][-1] if any(s * 111320 * .6 / mpp > 230 for s in (20, 10, 5, 2, 1, .5, .25, .1)) else 20
    lon0 = (V.cx - W / 2 * mpp) / R * 57.29578; lon1 = (V.cx + W / 2 * mpp) / R * 57.29578
    for lo in np.arange(math.floor(lon0 / step) * step, lon1 + step, step):
        x = V.pt(lo, 0)[0]; Lg.poly([(x, 0), (x, H)], (110, 150, 210), .09, 1)
    for la in np.arange(-80, 81, step):
        y = V.pt(0, la)[1]
        if -5 < y < H + 5: Lg.poly([(0, y), (W, y)], (110, 150, 210), .09, 1)
    frame = composite(frame, Lg)

    # land
    fk_occ, sg_occ = occupation(t)
    col_fk = lerp(CRIMSON, EMERALD, fk_occ); col_sg = lerp(CRIMSON, EMERALD, sg_occ)
    Ll = Layer()
    for r in polys.get("OTHER", []): Ll.fill(r, GRAY, 1)
    for r in polys.get("OTHER", []):
        for q in r[:1]: Ll.poly(q, GRAY_EDGE, .9, 1, True)
    for grp, col, edge in (("ARG", EMERALD, EMERALD_E), ("GBR", CRIMSON, CRIMSON_E)):
        for r in polys.get(grp, []): Ll.fill(r, col, 1)
        for r in polys.get(grp, []): Ll.poly(r[0], edge, 1, 2 if mpp < 6000 else 1, True)
    for r in polys.get("SGS", []): Ll.fill(r, col_sg, 1)
    for r in polys.get("FLK", []): Ll.fill(r, col_fk, 1)
    frame = composite(frame, Ll)

    # glow + overlays
    L, G = Layer(), Layer(0.25)
    far = mpp > 1200
    gth = 3 if mpp < 1500 else 1
    ga, gw = (.35, 2) if far else (.6, 3)
    for r in polys.get("FLK", []):
        L.poly(r[0], GOLD, .85 if far else 1, gth, True); G.poly(r[0], GOLD, ga, gth * gw, True)
    for r in polys.get("SGS", []):
        L.poly(r[0], GOLD, .85 if far else .95, gth, True); G.poly(r[0], GOLD, ga * .8, gth * gw, True)
    for r in polys.get("ARG", []) + polys.get("GBR", []):
        G.poly(r[0], (200, 200, 200), .0, 1, True)

    stanley = V.pt(*P["stanley"]); london = V.pt(*P["london"]); fk = V.pt(*P["fk"])
    # --- Scene 1: distance arc London -> Stanley
    a_arc = win(t, 1.4, 9.0, .5, .8)
    if a_arc > 0:
        pr = ramp(t, 1.6, 4.4); arc = V.pts(ARC)
        dashed(L, G, arc, pr, GOLD, a_arc, 4, t, head=False)
        pin(L, G, london, WHITE, t, a_arc * ramp(t, 1.4, 2.0), 9, False)
        pin(L, G, stanley, GOLD, t, a_arc * ramp(t, 3.8, 4.4), 9, True)
    # --- Setup: Argentine-coast distance bracket
    a_set = win(t, 8.2, 12.4, .5, .4)
    # --- invasion arrow
    a_inv = win(t, 12.7, 16.3, .3, .5)
    if a_inv > 0:
        pts = V.pts([INV_FROM, (-60.6, -52.9), P["stanley"]]) if False else V.pts([INV_FROM, (-61.0, -53.2), (-58.4, -52.2), (-57.95, -51.78)])
        dashed(L, G, pts, ramp(t, 12.9, 14.6), (64, 226, 164), a_inv, 6, t)
    # --- South Georgia pin events
    sg = V.pt(*P["sgeorgia"])
    a_sg1 = win(t, 15.2, 17.8, .4, .5)
    if a_sg1 > 0:
        pin(L, G, sg, (64, 226, 164), t, a_sg1, 10, True)
        pts = V.pts([(-57.2, -52.0), (-48.0, -52.8), (-39.0, -53.9)]); dashed(L, G, pts, ramp(t, 15.4, 16.9), (64, 226, 164), a_sg1, 6, t)
    # --- task force route
    a_rt = win(t, 17.7, 22.8, .4, .7)
    if a_rt > 0:
        pr = ramp(t, 17.9, 21.6); pts = V.pts(ROUTE)
        dashed(L, G, pts, pr, (255, 110, 126), a_rt, 5, t)
        pin(L, G, V.pt(*P["portsmouth"]), WHITE, t, a_rt, 9, False)
        pin(L, G, V.pt(*P["ascension"]), GOLD, t, a_rt * ramp(t, 19.4, 20.0), 8, False)
    a_sg2 = win(t, 22.0, 24.2, .4, .5)
    if a_sg2 > 0: pin(L, G, sg, (255, 110, 126), t, a_sg2, 10, True)
    # --- local ops (San Carlos / Stanley)
    a_loc = win(t, 24.2, 35.3, .5, .6)
    if a_loc > 0:
        sc = V.pt(*P["sancarlos"])
        dashed(L, G, V.pts(LAND_ARROW), ramp(t, 24.9, 26.4), (255, 170, 180), a_loc, 8, t)
        pin(L, G, sc, GOLD, t, a_loc * ramp(t, 25.8, 26.4), 12, True)
        dashed(L, G, V.pts(ADV), ramp(t, 27.1, 29.9), (255, 235, 238), a_loc, 9, t, dash=30, gap=16)
        pin(L, G, stanley, GOLD, t, a_loc * ramp(t, 29.6, 30.2), 13, True, .3)
        # surrender: expanding ring
        if t >= 30.2:
            u = ramp(t, 30.2, 32.2); L.circle(stanley, 20 + 240 * u, (255, 255, 255), (1 - u) * .8, 4); G.circle(stanley, 20 + 240 * u, GOLD, (1 - u), 8)
    # --- stats-phase + final pins
    a_fin = win(t, 38.5, 54, 1.2, .1)
    if a_fin > 0:
        for k in range(3):
            u = ((t * .35 + k / 3) % 1.0); G.circle(fk, 14 + 70 * u, GOLD, a_fin * (1 - u) * .9, 6); L.circle(fk, 14 + 70 * u, GOLD, a_fin * (1 - u) * .7, 2)
    # particles
    for i, (px, py, ps, pa) in enumerate(PART):
        x = (px * W + t * (6 + 8 * ps)) % W; y = (py * H - t * (10 + 18 * ps)) % H
        L.circle((x, y), 1 + 2 * ps, (190, 215, 255), .12 + .25 * pa)

    frame = composite(frame, L)
    gl = cv2.GaussianBlur(G.img, (0, 0), 5); gl = cv2.resize(gl, (W, H), interpolation=cv2.INTER_LINEAR)
    frame = np.clip(frame.astype(np.int16) + (gl * 1.5).astype(np.int16), 0, 255).astype(np.uint8)
    # scrims + vignette
    sc_ = (GRAD + TOPG)[..., None]; frame = (frame * (1 - sc_)).astype(np.uint8)
    frame = (frame * VIG).astype(np.uint8)

    labels(frame, t, V, polys)
    hud(frame, t)
    stats(frame, t)
    # global fade in / out
    fade = ramp(t, 0.0, 0.5) * (1 - ramp(t, DUR - 0.9, DUR))
    return (frame.astype(np.float32) * fade).astype(np.uint8)

# ---------- labels ----------
def labels(frame, t, V, polys):
    def put(spr, lonlat, dx, dy, a, anchor="c", rise=14):
        if a <= 0.01: return
        x, y = V.pt(*lonlat); blit(frame, spr, x + dx, y + dy + rise * (1 - a), a, 1.0, anchor)
    # flags header (scene 1)
    af = win(t, 0.4, 5.6, .6, .6)
    if af > 0:
        u = ramp(t, 0.4, 1.2); ur = ramp(t, .7, 1.5)
        blit(frame, flag_sprite("gb", 250), 300 - 80 * (1 - u), 320, af * u)
        blit(frame, flag_sprite("ar", 250), 780 + 80 * (1 - ur), 320, af * ur)
        blit(frame, text_sprite("VS", 54, GOLD), 540, 320, af * ramp(t, 1.0, 1.6))
    # world labels
    mapa = ramp(t, 1.0, 1.8) * (1 - ramp(t, 5.0, 5.6)) 
    put(label_sprite("UNITED KINGDOM", flag="gb", size=30, accent=CRIMSON_E), P["uk"], -75, 45, ramp(t, 3.0, 3.8) * (1 - ramp(t, 5.0, 5.6)), "r")
    put(label_sprite("ARGENTINA", flag="ar", size=30, accent=EMERALD_E), P["arg"], 0, 0, ramp(t, 3.4, 4.2) * (1 - ramp(t, 5.0, 5.6)), "l")
    # distance badge on arc
    ad = win(t, 3.6, 7.8, .6, .8)
    if ad > 0:
        mid = V.pt(*ARC[len(ARC) // 2]); blit(frame, label_sprite("12,700 KM", sub="LONDON TO STANLEY", size=36), mid[0] + 150, mid[1] + 10, ad)
    # setup labels
    a1 = win(t, 7.4, 12.6, .7, .5)
    put(label_sprite("FALKLAND ISLANDS", sub="ISLAS MALVINAS", size=34, accent=GOLD), (-57.8, -51.0), 0, -135, a1)
    put(label_sprite("ARGENTINA", flag="ar", size=34, accent=EMERALD_E), (-69.2, -45.0), 0, 0, a1, "c")
    ab = win(t, 8.8, 12.4, .6, .5)
    if ab > 0:
        a_, b_ = V.pt(-66.2, -53.0), V.pt(-61.4, -52.0)
        x, y = V.pt(-62.0, -54.2); blit(frame, label_sprite("ABOUT 480 KM", sub="FROM ARGENTINA'S COAST", size=30, accent=GOLD), x, y, ab)
    ab2 = win(t, 10.5, 12.6, .5, .4)
    if ab2 > 0:
        x, y = V.pt(-57.8, -51.0); blit(frame, flag_sprite("gb", 150), x, y - 300, ab2)
    # invasion
    put(label_sprite("FALKLAND ISLANDS", sub="BRITISH-ADMINISTERED", size=30), (-60.0, -50.9), 0, -110, win(t, 12.4, 13.2, .3, .3) * 0 + (1 - ramp(t, 13.0, 13.6)) * ramp(t, 12.3, 12.8) * (1 - ramp(t, 13, 13.6)))
    put(label_sprite("ARGENTINE FORCES", flag="ar", size=30, accent=EMERALD_E), (-65.2, -53.2), -10, -120, win(t, 13.6, 16.0, .4, .4), "c")
    # south georgia
    put(label_sprite("SOUTH GEORGIA", size=30), P["sgeorgia"], 0, -90, max(win(t, 15.5, 17.7, .5, .4), win(t, 22.2, 24.0, .5, .5)))
    # task force
    put(label_sprite("PORTSMOUTH", flag="gb", size=26, accent=CRIMSON_E), P["portsmouth"], -20, 70, win(t, 17.9, 22.2, .5, .5), "r")
    put(label_sprite("ASCENSION IS.", size=26), P["ascension"], 40, 0, win(t, 19.8, 22.2, .4, .5), "l")
    ar = win(t, 19.6, 22.0, .6, .6)
    if ar > 0:
        x, y = V.pt(-30, -30); blit(frame, text_sprite("ILLUSTRATIVE ROUTE", 24, (200, 215, 240), "Medium", track=3), x, y, ar * .85)
    # local
    put(label_sprite("SAN CARLOS", sub="21 MAY", size=30, accent=CRIMSON_E), P["sancarlos"], -30, -105, win(t, 25.6, 35, .5, .6), "c")
    put(label_sprite("STANLEY", sub="CAPITAL", size=34, accent=GOLD), P["stanley"], 40, 100, win(t, 29.4, 35.0, .5, .6), "c")
    put(label_sprite("EAST FALKLAND", size=26), (-58.9, -52.05), 0, 0, win(t, 25.3, 30.5, .6, .6) * .9)
    # stats-phase / final labels
    put(label_sprite("FALKLAND ISLANDS", sub="BRITISH OVERSEAS TERRITORY", size=30, flag=None, accent=CRIMSON_E), (-56.0, -51.8), 40, -55, win(t, 49.4, 53.6, .8, .5), "l")
    put(label_sprite("LAS MALVINAS", sub="CLAIMED BY ARGENTINA", size=30, accent=EMERALD_E), (-58.5, -51.8), -40, -55, win(t, 49.6, 53.6, .8, .5), "r")

# ---------- HUD ----------
EV_DAYS_T = [12.4, 15.2, 17.6, 22.0, 24.2, 30.2]; EV_DAYS_D = [0, 1, 3, 24, 49, 73]
def hud(frame, t):
    for (a, b, date, lab) in C.EVENTS:
        al = win(t, a, b, .35, .35)
        if al <= 0: continue
        u = ramp(t, a, a + .45)
        blit(frame, text_sprite(date, 78, WHITE, stroke=0), 540, 262 + 24 * (1 - u), al)
        blit(frame, text_sprite(lab, 28, GOLD, "Medium", track=3), 540, 346 + 24 * (1 - u), al)
    tl = win(t, 12.4, 35.2, .5, .6)
    if tl > 0:
        d = float(np.interp(t, EV_DAYS_T, EV_DAYS_D)); L = Layer(); x0, x1, y = 110, 970, 412
        L.poly([(x0, y), (x1, y)], (120, 140, 170), tl * .5, 4)
        L.poly([(x0, y), (x0 + (x1 - x0) * d / 73, y)], GOLD, tl, 5)
        for dd, tt in zip(EV_DAYS_D, EV_DAYS_T):
            xx = x0 + (x1 - x0) * dd / 73; on = t >= tt
            L.circle((xx, y), 9, GOLD if on else (120, 140, 170), tl, -1); L.circle((xx, y), 9, (255, 255, 255), tl * (.9 if on else .3), 2)
        L.circle((x0 + (x1 - x0) * d / 73, y), 14, (255, 255, 255), tl * .9, 3)
        fr = composite(frame, L); frame[:] = fr
        blit(frame, text_sprite("DAY " + str(int(d) + 1), 24, WHITE, "Medium", track=3), x1 - 40, y + 44, tl * .9)
    # 74 days badge
    ba = win(t, 32.6, 35.2, .5, .5)
    if ba > 0:
        u = ramp(t, 32.6, 33.3); blit(frame, label_sprite("74 DAYS", sub="OF WAR", size=64, accent=GOLD), 540, 560, ba, .8 + .2 * u)

# ---------- stats panels ----------
def rrect(L, x0, y0, x1, y1, alpha):
    L.fill([np.array([(x0 + 18, y0), (x1 - 18, y0), (x1, y0 + 18), (x1, y1 - 18), (x1 - 18, y1), (x0 + 18, y1), (x0, y1 - 18), (x0, y0 + 18)])], (6, 14, 34), alpha * .84)
    L.poly([(x0 + 18, y0), (x1 - 18, y0), (x1, y0 + 18), (x1, y1 - 18), (x1 - 18, y1), (x0 + 18, y1), (x0, y1 - 18), (x0, y0 + 18)], GOLD, alpha * .85, 2, True)

def stats(frame, t):
    a = win(t, 35.0, 41.5, .6, .6)
    if a > 0:
        L = Layer(); rrect(L, 60, 540, 1020, 1210, a)
        rows = [("ARGENTINE SERVICEMEN", 649, EMERALD_E, 36.0, "ar"), ("BRITISH SERVICEMEN", 255, CRIMSON_E, 36.6, "gb"), ("FALKLAND ISLANDERS", 3, GOLD, 37.2, None)]
        for i, (lab, val, col, ts, fl) in enumerate(rows):
            y = 720 + i * 170; u = ramp(t, ts, ts + 1.6); bw = 760 * (val / 700) * u
            L.poly([(160, y + 62), (920, y + 62)], (80, 100, 130), a * .5, 10); L.poly([(160, y + 62), (160 + max(bw, 4 if u > 0 else 0), y + 62)], col, a, 10)
        frame[:] = composite(frame, L)
        blit(frame, text_sprite("WAR DEAD", 30, GOLD, "Medium", track=6), 540, 598, a)
        for i, (lab, val, col, ts, fl) in enumerate(rows):
            y = 720 + i * 170; u = ramp(t, ts, ts + 1.6); n = int(round(val * u))
            blit(frame, text_sprite(str(n), 74, col), 160, y - 6, a * ramp(t, ts - .1, ts + .3), 1.0, "l")
            blit(frame, text_sprite(lab, 26, WHITE, "Medium", track=2), 920, y + 20, a * ramp(t, ts, ts + .4), 1.0, "r")
        blit(frame, text_sprite("Figures vary slightly by source", 22, (170, 185, 210), "Regular", shadow=False), 540, 1182, a * .8)
    b = win(t, 41.4, 46.0, .6, .6)
    if b > 0:
        L = Layer(); rrect(L, 60, 560, 1020, 1190, b)
        u = ramp(t, 42.0, 43.9); c = (540, 850)
        L.arc(c, 200, 0, 360, (80, 100, 130), b * .5, 38); L.arc(c, 200, -90, -90 + 359.3 * .998 * u, GOLD, b, 38)
        frame[:] = composite(frame, L)
        blit(frame, text_sprite("2013 REFERENDUM", 30, GOLD, "Medium", track=6), 540, 618, b)
        blit(frame, text_sprite(f"{99.8 * u:.1f}%", 96, WHITE), 540, 840, b)
        blit(frame, text_sprite("VOTED TO STAY A BRITISH", 26, WHITE, "Medium", track=2), 540, 1090, b * ramp(t, 43, 43.6))
        blit(frame, text_sprite("OVERSEAS TERRITORY  ·  92% TURNOUT", 26, WHITE, "Medium", track=2), 540, 1130, b * ramp(t, 43.2, 43.8))
    f = win(t, 47.0, 53.6, .8, .5)
    if f > 0:
        blit(frame, text_sprite("STILL DISPUTED", 92, WHITE), 540, 300, f * ramp(t, 47.0, 47.8))
        blit(frame, text_sprite("SOVEREIGNTY OF THE FALKLAND ISLANDS · ISLAS MALVINAS", 22, GOLD, "Medium", track=2), 540, 392, f * ramp(t, 47.6, 48.4))
        blit(frame, flag_sprite("gb", 150), 250, 480, f * ramp(t, 48, 48.8)); blit(frame, flag_sprite("ar", 150), 530, 480, f * ramp(t, 48.2, 49))
        blit(frame, text_sprite("vs", 40, GOLD), 390, 480, f * ramp(t, 48.4, 49))

# ---------- captions ----------
def captions(frame, t):
    for (a, b, l1, l2) in C.CAPTIONS:
        if not (a - .01 <= t <= b + .01): continue
        for i, ln in enumerate([l1, l2]):
            if not ln: continue
            d = .09 * i; u = ramp(t, a + d, a + d + .28); o = 1 - ramp(t, b - .2, b)
            blit(frame, caption_line(ln), 540, (1385 if l2 else 1420) + i * 98 + 30 * (1 - u), u * o, .94 + .06 * u)

# ---------- main ----------
def encode(out, frames_iter):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
           "-r", str(FPS), "-movflags", "+faststart", "-an", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i, fr in frames_iter:
        p.stdin.write(fr.tobytes())
        if i % 60 == 0: print("frame", i, "/", NF, flush=True)
    p.stdin.close(); p.wait()

if __name__ == "__main__":
    if "--test" in sys.argv:
        ts = [float(x) for x in sys.argv[sys.argv.index("--test") + 1:]]
        os.makedirs("/tmp/test", exist_ok=True)
        for t in ts:
            cv2.imwrite(f"/tmp/test/t{t:05.1f}.png", render(t)); print("ok", t)
    else:
        out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(HERE, "final_video.mp4")
        encode(out, ((i, render(i / FPS)) for i in range(NF)))
        print("done", out)
