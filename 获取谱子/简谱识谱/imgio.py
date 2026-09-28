# -*- coding: utf-8 -*-
"""图像读取 —— 纯标准库解码 PNG / PGM，其余格式走外部转换器兜底。

为什么不用 PIL：本仓库的 `获取谱子/` 下所有脚本都是**零第三方依赖**的，
用户环境里未必装得到 PIL。PNG 用 zlib（标准库）就能自己解，
足以覆盖"截图 / 修图软件另存为 PNG"这条最常见的路径。
webp / avif / jpg 这类需要外部解码器的，按 PIL → ffmpeg 顺序找，找不到时
给出明确的手工转换提示，而不是抛一个看不懂的 ImportError。

统一输出：8 位灰度，`bytes`，长度 = W*H，行优先。0 = 黑，255 = 白。
"""
import io
import os
import struct
import subprocess
import sys
import zlib

# 常见 ffmpeg 位置（本机 winget 装的版本优先）
_FF_CANDIDATES = [
    os.environ.get("FFMPEG", ""),
    r"C:\Users\HUAWEI\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe",
]


def _ffmpeg():
    for p in _FF_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    from shutil import which
    return which("ffmpeg")


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw, w, h, bpp, stride):
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 0:
            pass
        elif ft == 1:                       # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:                       # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:                       # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:                       # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        else:
            raise ValueError(f"PNG 行滤波类型 {ft} 不认识")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _png_gray(data):
    if data[:8] != _PNG_SIG:
        raise ValueError("不是 PNG 文件")
    pos, idat, plte, trns = 8, [], None, None
    ihdr = None
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            plte = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
    if ihdr is None:
        raise ValueError("PNG 缺少 IHDR")
    w, h, depth, ctype, comp, filt, inter = ihdr
    if inter:
        raise ValueError("暂不支持隔行（Adam7）PNG，请另存为普通 PNG")
    if comp != 0 or filt != 0:
        raise ValueError("PNG 压缩/滤波方式非标准")
    raw = zlib.decompress(b"".join(idat))

    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if depth == 16:
        bpp = ch * 2
    elif depth == 8:
        bpp = ch
    else:
        bpp = 1                             # 1/2/4 位：整行按字节对齐
    stride = (w * ch * depth + 7) // 8
    buf = _unfilter(raw, w, h, bpp, stride)

    # 解包成每像素 (r,g,b)
    out = bytearray(w * h)

    def expand_bits(row_bytes):
        vals = []
        for byte in row_bytes:
            for k in range(8 // depth):
                vals.append((byte >> (8 - depth * (k + 1))) & ((1 << depth) - 1))
                if len(vals) >= w:
                    return vals
        return vals

    for y in range(h):
        row = buf[y * stride:(y + 1) * stride]
        if depth < 8:
            idx = expand_bits(row)
            if ctype == 3:
                plte = plte or b""
                for x in range(w):
                    i = idx[x] * 3
                    r, g, b = plte[i], plte[i + 1], plte[i + 2]
                    out[y * w + x] = (r * 299 + g * 587 + b * 114) // 1000
            else:
                scale = 255 // ((1 << depth) - 1)
                for x in range(w):
                    out[y * w + x] = idx[x] * scale
            continue
        step = depth // 8
        for x in range(w):
            i = x * bpp
            if ctype == 0:
                out[y * w + x] = row[i]
            elif ctype == 4:
                out[y * w + x] = row[i]
            elif ctype == 2:
                r, g, b = row[i], row[i + step], row[i + 2 * step]
                out[y * w + x] = (r * 299 + g * 587 + b * 114) // 1000
            elif ctype == 6:
                r, g, b = row[i], row[i + step], row[i + 2 * step]
                out[y * w + x] = (r * 299 + g * 587 + b * 114) // 1000
            else:                           # 3 调色板 + 8/16 位索引
                j = row[i] * 3
                r, g, b = plte[j], plte[j + 1], plte[j + 2]
                out[y * w + x] = (r * 299 + g * 587 + b * 114) // 1000
    return bytes(out), w, h


# --------------------------------------------------------------------------
# PGM / 裸灰度
# --------------------------------------------------------------------------
def _pgm_gray(data):
    if not data.startswith(b"P5"):
        raise ValueError("不是 P5 二进制 PGM")
    pos = 2
    vals = []
    while len(vals) < 3:
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while pos < len(data) and data[pos] != 0x0A:
                pos += 1
            continue
        s = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        vals.append(int(data[s:pos]))
    pos += 1
    w, h, mx = vals
    body = data[pos:pos + w * h]
    if mx != 255:
        body = bytes((v * 255) // mx for v in body)
    return body, w, h


def _via_pil(path):
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(path).convert("L")
    return im.tobytes(), im.size[0], im.size[1]


def _via_ffmpeg(path, tmp_pgm):
    ff = _ffmpeg()
    if not ff:
        return None
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", path,
                    "-f", "image2", "-vcodec", "pgm", tmp_pgm],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(tmp_pgm, "rb") as fh:
        return _pgm_gray(fh.read())


def load_gray(path, raw_size=None):
    """读成 8 位灰度。raw_size 形如 '1400x1980' 时按裸字节读（.gray / .raw）。"""
    if raw_size:
        w, h = (int(t) for t in raw_size.lower().replace("*", "x").split("x"))
        with open(path, "rb") as fh:
            body = fh.read(w * h)
        return body, w, h
    with open(path, "rb") as fh:
        head = fh.read(8)
        fh.seek(0)
        data = fh.read()
    if head.startswith(_PNG_SIG):
        return _png_gray(data)
    if head.startswith(b"P5"):
        return _pgm_gray(data)
    tmp = os.path.join(os.environ.get("TEMP", "."), "_识谱_临时.pgm")
    for name, fn in (("PIL", lambda: _via_pil(path)),
                     ("ffmpeg", lambda: _via_ffmpeg(path, tmp))):
        try:
            r = fn()
        except Exception:                    # noqa: BLE001 —— 兜底链，失败就换下一个
            r = None
        if r:
            return r
    raise SystemExit(
        f"读不了 {path}：内置解码器只认 PNG / PGM。"
        f"请先另存为 PNG，或让 PIL / ffmpeg 可用。"
    )


def ink_threshold(buf, ratio=0.81):
    """自适应墨阈值。

    ⚠️ 不能取「纸白与墨黑的中点」：谱面里**浅灰音符**（跨小节连音线的接音，
    实测灰度 150~163）必须仍算墨，否则整条连音线的接音会凭空消失。
    所以阈值要贴近纸白一侧。取「纸白 × ratio」：

      · 纸白 = 亮度直方图的最亮主峰（本系列图是 **253**，不是 255）
      · ratio = 0.81 → 253×0.81 = 205，正好等于人工调参时用的那个值
    """
    hist = [0] * 256
    for v in buf:
        hist[v] += 1
    paper = max(range(200, 256), key=lambda v: hist[v]) if any(hist[200:]) else 255
    ink = int(round(paper * ratio))
    ink = max(16, min(250, ink))
    return ink, paper
