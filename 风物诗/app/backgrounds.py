"""预设背景：用 PIL/numpy 现场渲染，不往仓库里塞图片二进制。

首次运行生成 6 张 1280×800 的背景图到 %LOCALAPPDATA%\\风物诗\\backgrounds\\，
以后直接读缓存。用户也可以选自己的图片（会连同模糊/压暗参数一起用）。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from . import paths

SIZE = (1280, 800)


# --------------------------------------------------------------------------
# 渲染工具
# --------------------------------------------------------------------------


def _hex2rgb(c: str) -> tuple[float, float, float]:
    c = c.lstrip("#")
    return int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0


def _ramp(t: np.ndarray, stops: list[tuple[float, tuple[str, ...]]]) -> np.ndarray:
    """按 t∈[0,1] 在多段颜色之间插值，返回 (h,w,3) 的 0~1 数组。"""
    stops = sorted(stops, key=lambda s: s[0])
    out = np.zeros(t.shape + (3,), dtype=np.float64)
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        m = (t >= t0) & (t <= t1)
        if not m.any():
            continue
        k = np.clip((t[m] - t0) / max(1e-9, t1 - t0), 0, 1)[:, None]
        a = np.array(_hex2rgb(c0[0]))
        b = np.array(_hex2rgb(c1[0]))
        out[m] = a + (b - a) * k
    out[t < stops[0][0]] = _hex2rgb(stops[0][1][0])
    out[t > stops[-1][0]] = _hex2rgb(stops[-1][1][0])
    return out


def _grid():
    h, w = SIZE[1], SIZE[0]
    yy, xx = np.mgrid[0:h, 0:w]
    return yy, xx, xx / (w - 1), yy / (h - 1)


def _radial(cx: float, cy: float) -> np.ndarray:
    yy, xx, u, v = _grid()
    d = np.sqrt(((u - cx) * 1.35) ** 2 + (v - cy) ** 2)
    return np.clip(d / d.max(), 0, 1)


def _diag(angle_deg: float) -> np.ndarray:
    yy, xx, u, v = _grid()
    a = math.radians(angle_deg)
    t = u * math.cos(a) + v * math.sin(a)
    return (t - t.min()) / (t.max() - t.min() + 1e-9)


def _vignette(strength: float = 0.55) -> np.ndarray:
    yy, xx, u, v = _grid()
    d = np.sqrt(((u - 0.5) * 1.25) ** 2 + ((v - 0.5) * 1.25) ** 2)
    d = np.clip(d / d.max(), 0, 1)
    return 1.0 - strength * (d ** 2)


def _stars(rgb: np.ndarray, count: int, seed: int, tint=(1.0, 1.0, 1.0)) -> np.ndarray:
    rnd = random.Random(seed)
    h, w = rgb.shape[0], rgb.shape[1]
    for _ in range(count):
        x = rnd.randrange(w)
        y = rnd.randrange(h)
        r = rnd.choice((1, 1, 1, 2))
        b = rnd.uniform(0.18, 0.85)
        ys = slice(max(0, y - r), min(h, y + r + 1))
        xs = slice(max(0, x - r), min(w, x + r + 1))
        add = np.array([b * tint[0], b * tint[1], b * tint[2]])
        rgb[ys, xs] = np.clip(rgb[ys, xs] + add, 0, 1)
    return rgb


def _finish(rgb: np.ndarray, blur: float = 0.0) -> Image.Image:
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


# --------------------------------------------------------------------------
# 六个预设
# --------------------------------------------------------------------------


def _preset_深空紫() -> Image.Image:
    rgb = _ramp(_radial(0.30, 0.24), [
        (0.00, ("#3A2E6E",)), (0.35, ("#1E1840",)), (0.70, ("#100C24",)),
        (1.00, ("#08060F",))])
    rgb *= _vignette(0.45)[..., None]
    rgb = _stars(rgb, 420, seed=11, tint=(0.85, 0.85, 1.0))
    return _finish(rgb, 0.4)


def _preset_极光青() -> Image.Image:
    yy, xx, u, v = _grid()
    rgb = _ramp(_diag(105), [
        (0.00, ("#06231F",)), (0.45, ("#0B3A34",)), (0.75, ("#071C22",)),
        (1.00, ("#040D12",))])
    band = np.sin((u * 2.4 + v * 3.1) * math.pi) * 0.5 + 0.5
    glow = np.clip(band, 0, 1) ** 2 * np.clip(1.35 - v * 1.5, 0, 1)
    teal = np.array(_hex2rgb("#2FD3A6"))
    rgb = np.clip(rgb + glow[..., None] * teal * 0.42, 0, 1)
    rgb *= _vignette(0.5)[..., None]
    return _finish(rgb, 1.2)


def _preset_午夜蓝() -> Image.Image:
    yy, xx, u, v = _grid()
    rgb = _ramp(v, [(0.00, ("#101E3C",)), (0.55, ("#0A1228",)),
                    (1.00, ("#05070F",))])
    rgb = np.clip(rgb + np.clip(0.35 - u, 0, 1)[..., None]
                  * np.array(_hex2rgb("#1B3A6B")) * 0.5, 0, 1)
    rgb *= _vignette(0.5)[..., None]
    rgb = _stars(rgb, 260, seed=7, tint=(0.8, 0.9, 1.0))
    return _finish(rgb, 0.6)


def _preset_霓虹网格() -> Image.Image:
    yy, xx, u, v = _grid()
    rgb = _ramp(_radial(0.5, 0.42), [
        (0.00, ("#1A1030",)), (0.55, ("#100A20",)), (1.00, ("#07060E",))])
    step = 40
    grid = ((xx % step) < 1) | ((yy % step) < 1)
    fade = np.clip(1.0 - _radial(0.5, 0.42) * 1.5, 0, 1)
    line = np.array(_hex2rgb("#8A6CFF"))
    rgb = np.clip(rgb + (grid * fade)[..., None] * line * 0.28, 0, 1)
    glare = np.clip(1.0 - _radial(0.5, 0.42) * 3.0, 0, 1) ** 2
    rgb = np.clip(rgb + glare[..., None] * np.array(_hex2rgb("#D46CFF")) * 0.22, 0, 1)
    rgb *= _vignette(0.4)[..., None]
    return _finish(rgb, 0.5)


def _preset_暖夜橙() -> Image.Image:
    rgb = _ramp(_radial(0.82, 0.88), [
        (0.00, ("#6B3618",)), (0.30, ("#3A1E12",)), (0.65, ("#1E1210",)),
        (1.00, ("#0C0808",))])
    rgb *= _vignette(0.42)[..., None]
    return _finish(rgb, 1.0)


def _preset_墨绿() -> Image.Image:
    rgb = _ramp(_diag(60), [
        (0.00, ("#0C2C24",)), (0.5, ("#08201C",)), (1.00, ("#040D0C",))])
    rgb = np.clip(rgb + np.clip(1.0 - _radial(0.22, 0.18) * 2.2, 0, 1)[..., None]
                  * np.array(_hex2rgb("#1E7A5E")) * 0.35, 0, 1)
    rgb *= _vignette(0.5)[..., None]
    return _finish(rgb, 1.4)


PRESETS: dict[str, callable] = {
    "深空紫": _preset_深空紫,
    "极光青": _preset_极光青,
    "午夜蓝": _preset_午夜蓝,
    "霓虹网格": _preset_霓虹网格,
    "暖夜橙": _preset_暖夜橙,
    "墨绿": _preset_墨绿,
}
PRESET_ORDER = list(PRESETS)


def preset_path(name: str) -> Path:
    return Path(paths.BG_DIR) / f"{name}.png"


def ensure_presets(force: bool = False, on_step=None,
                   only: str | None = None) -> list[str]:
    """补齐缺失的预设图，返回本次生成的名称。

    only 给了就只处理那一张（启动时只保证在用的那张就绪，其余后台慢慢来）。
    """
    Path(paths.BG_DIR).mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    names = [only] if only and only in PRESETS else list(PRESETS)
    for name in names:
        fn = PRESETS[name]
        p = preset_path(name)
        if p.exists() and not force:
            continue
        try:
            if on_step:
                on_step(f"生成预设背景：{name}")
            fn().save(p, "PNG")
            made.append(name)
        except Exception:
            continue
    return made


# --------------------------------------------------------------------------
# 读图 / 平均色（做「假透明」面板用）
# --------------------------------------------------------------------------

_avg_cache: dict[str, str] = {}


def load_image(kind: str, value: str, preset_name: str = "") -> Image.Image | None:
    """按设置取一张背景图；solid 模式返回 None（调用方用纯色）。"""
    try:
        if kind == "image" and value:
            p = Path(value)
            if p.is_file():
                return Image.open(p).convert("RGB")
        if kind == "preset":
            p = preset_path(preset_name or value or PRESET_ORDER[0])
            if p.is_file():
                return Image.open(p).convert("RGB")
            ensure_presets()
            if p.is_file():
                return Image.open(p).convert("RGB")
    except Exception:
        return None
    return None


def average_color(img: Image.Image | None) -> str:
    if img is None:
        return "#0E0E16"
    key = f"{img.width}x{img.height}:{hash(img.tobytes()[:4096])}"
    if key in _avg_cache:
        return _avg_cache[key]
    try:
        small = img.resize((48, 30), Image.BILINEAR)
        a = np.asarray(small, dtype=np.float64).reshape(-1, 3).mean(axis=0)
        hexc = "#%02X%02X%02X" % tuple(int(v) for v in a)
    except Exception:
        hexc = "#0E0E16"
    _avg_cache[key] = hexc
    return hexc


def prepare(kind: str, value: str, preset_name: str = "",
            dim: float = 0.0, blur: float = 0.0) -> tuple[Image.Image | None, str]:
    """返回 (处理后的背景图, 平均色)。solid 模式图为 None。"""
    img = load_image(kind, value, preset_name)
    if img is None:
        return None, "#0E0E16"
    if blur and blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if dim and dim > 0:
        arr = np.asarray(img, dtype=np.float64) * (1.0 - max(0.0, min(0.8, dim)))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img, average_color(img)
