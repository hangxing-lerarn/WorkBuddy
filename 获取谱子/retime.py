#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把机器谱的**间隔列**按谱面分段速度重算 —— 原谱中途变速时补的最后一步。

为什么需要它
------------
`jianpu_to_score.py` 只有**一个**全局速度（写进首行 `#N倍速`，播放器把间隔 ÷ N）。
可印刷谱常在中途另写速度记号（《诀别书》实测：`(25)♩=112`、`(101)♩=100`、
`(105)♩=90` —— 段落号旁边那一小串，识谱器只认页眉那一行）。于是全曲都被按
页眉速度算成间隔，占 70% 的中段会偏慢 10.7%、结尾 4 小节偏快 11%。
本工具在**产物层**补这一步：按小节把间隔乘 `基准速度 ÷ 该小节速度`。

用法
----
    python 获取谱子/retime.py "scores/诀别书（简谱转）.txt" \
        --base 100 --tempo "1=100,25=112,101=100,105=90" --write

`--tempo` 是「起始小节=速度」列表，按小节号升序，**第一条必须是第 1 小节**。
`--base` 是当初跑 `jianpu_to_score.py` 时 `--head` 里写的速度，工具会拿它核对
首行注释里的 `N BPM`，对不上直接报错（防呆）。默认**试运行**，只打印结果；
落盘要显式 `--write`，落盘前把原文件备份成 `<名字>.bak`（幂等，重跑安全）。

关键语义（改之前先读）
----------------------
* **第 i 行的间隔属于第 i−1 格所在的小节** —— `parser` 是「先累加间隔再记音」，
  速度在第 i 格**开始**时才切换，所以从上一格到这一格的那段空档仍算旧速度。
  首行的间隔是「起手延迟」，按第 1 小节的速度缩放。
* **逐行乘系数、逐行取整会累积漂移**：112 BPM 的十六分格是 133.93ms，取整成 134
  每格多 0.07ms，一个小节 16 格就是 1.1ms，76 个小节漂到 80ms。所以这里维护一个
  **浮点理想时刻**，对**累计时刻**取整再作差 —— 累计误差恒 ≤0.5ms，且各段总时长
  精确到 ms。
* **按住时长同乘系数**（保住「本音自身时值 − 10ms」的口径），再按新间隔把
  `cap_holds` 的钳制重做一遍（上限 = 到下一个发声格 − 10ms、下限 50ms、末个发声
  格不钳上限）—— 否则 112 BPM 段里会有按住比到下一音的空档还长的行。

产物会多两行注释说明分段速度；其余字节只动「间隔」与「按住」两列。
"""

import argparse
import importlib.util
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAP = 10            # 与 parser.HOLD_GAP_MS 一致
HOLD_MIN = 50       # 与 parser.DEFAULT_HOLD_MS 一致


def load_parser():
    spec = importlib.util.spec_from_file_location("parser_mod", ROOT / "parser.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_converter():
    spec = importlib.util.spec_from_file_location("j2s", Path(__file__).resolve().parent
                                                  / "jianpu_to_score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def half_up(x):
    return int(math.floor(x + 0.5))


def parse_tempo(spec, log):
    """`"1=100,25=112,101=100,105=90"` → [(1, 100.0), (25, 112.0), …]"""
    out = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(f"✗ --tempo 片段看不懂：{item!r}（要写 小节=速度）")
        a, b = item.split("=", 1)
        try:
            bar, bpm = int(a.strip()), float(b.strip())
        except ValueError:
            raise SystemExit(f"✗ --tempo 片段看不懂：{item!r}（要写 小节=速度）")
        if bar < 1 or bpm <= 0:
            raise SystemExit(f"✗ --tempo 片段越界：{item!r}")
        out.append((bar, bpm))
    if not out:
        raise SystemExit("✗ --tempo 是空的")
    out.sort()
    if out[0][0] != 1:
        raise SystemExit(f"✗ --tempo 的第一条必须是第 1 小节，现在是第 {out[0][0]} 小节")
    for i in range(1, len(out)):
        if out[i][0] == out[i - 1][0]:
            raise SystemExit(f"✗ --tempo 里第 {out[i][0]} 小节写了两遍")
    log("  分段速度：" + " ｜ ".join(
        "第%d-%s小节 ♩=%g" % (b, (out[i + 1][0] - 1) if i + 1 < len(out) else "末",
                              t) for i, (b, t) in enumerate(out)))
    return out


def tempo_of(bar, segs):
    t = segs[0][1]
    for b, v in segs:
        if bar >= b:
            t = v
        else:
            break
    return t


def bar_map(lines, log):
    """每一格（= 一个音符行）属于第几小节。靠正文里的 `#<整数>` 小节标记推。

    标记只落在**段落起点**（每 4 小节一个），所以先算「一段几格、几小节」，
    再按格号外推。全部格数在正文里是连续的（均匀网格），因此只需按顺序数。
    """
    marks = []          # [(第几格, 第几小节)]
    cells = 0
    for ln in lines:
        s = ln.strip()
        if s.startswith("#"):
            body = s[1:].strip()
            if body.isdigit():
                marks.append((cells, int(body)))
            continue
        if s:
            cells += 1
    if not marks:
        raise SystemExit("✗ 产物里没有 `#<小节号>` 标记，没法定位小节")
    if len(marks) == 1:
        raise SystemExit("✗ 只有一个 `#<小节号>` 标记，推不出「一段几格几小节」")
    step_cells = marks[1][0] - marks[0][0]
    step_bars = marks[1][1] - marks[0][1]
    if step_cells <= 0 or step_bars <= 0 or step_cells % step_bars:
        raise SystemExit("✗ 小节标记间距推不出整数格子/小节")
    per_bar = step_cells // step_bars
    for i in range(1, len(marks) - 1):          # 顺带核一遍后面的标记同伦
        dc = marks[i + 1][0] - marks[i][0]
        db = marks[i + 1][1] - marks[i][1]
        if db <= 0 or dc % db or dc // db != per_bar:
            raise SystemExit("✗ 小节标记间距不一致（第 %d 个标记处）" % (i + 1))
    out = []
    mi = 0
    for c in range(cells):
        while mi + 1 < len(marks) and marks[mi + 1][0] <= c:
            mi += 1
        out.append(marks[mi][1] + (c - marks[mi][0]) // per_bar)
    log("  小节映射：每小节 %d 格 ｜ 共 %d 格 → 第 %d…%d 小节"
        % (per_bar, cells, out[0], out[-1]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="按谱面分段速度重算机器谱的间隔列（原谱中途变速时用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("score", help="机器谱文件（scores/*.txt）")
    ap.add_argument("--base", type=float, required=True,
                    help="当初转换用的速度（--head 里那个），用于核对与换算系数")
    ap.add_argument("--tempo", required=True,
                    help='分段速度，如 "1=100,25=112,101=100,105=90"')
    ap.add_argument("--write", action="store_true",
                    help="真的写回（默认只试运行；写前备份 <名字>.bak）")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    def log(m):
        if not a.quiet:
            print(m, flush=True)

    path = Path(a.score)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit("✗ 输入带 UTF-8 BOM")
    if b"\r" in raw:
        raise SystemExit("✗ 输入含 CR，不是纯 LF")
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    tail_nl = text.endswith("\n")

    m = re.search(r"\b(\d+(?:\.\d+)?) BPM\b", text[:600])
    if not m:
        raise SystemExit("✗ 头部注释里找不到 `N BPM`，核对不了 --base")
    if abs(float(m.group(1)) - a.base) > 1e-6:
        raise SystemExit("✗ 头部写的是 %s BPM，与 --base %g 不符"
                         % (m.group(1), a.base))

    segs = parse_tempo(a.tempo, log)
    bars = bar_map(lines, log)
    log("  基准速度 ♩=%g（%s）" % (a.base, "全段同速，无需改动"
                                  if len(segs) == 1 else "按分段重算"))

    body = []                       # [(行号, 原行, 间隔, keys, 按住 or None)]
    ci = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#") or not s:
            continue
        parts = ln.split()
        if len(parts) > 3:
            raise SystemExit("✗ 第 %d 行字段多于 3 个：%r" % (i + 1, ln))
        body.append((i, parts, float(parts[0]), parts[1] if len(parts) > 1 else "",
                     int(parts[2]) if len(parts) > 2 else None))
        ci += 1

    if ci != len(bars):
        raise SystemExit("✗ 音符行 %d 行，与推出的小节格数 %d 不符" % (ci, len(bars)))

    # ---- 间隔：浮点理想时刻 → 累计取整 → 作差
    out_iv = []
    ideal = 0.0
    prev = 0
    for k, (_i, _p, iv, _keys, _h) in enumerate(body):
        # 第 k 行的间隔属于**上一格**所在的小节；首行（起手延迟）按第 0 格算
        bar = bars[k - 1] if k else bars[0]
        ideal += iv * a.base / tempo_of(bar, segs)
        now = half_up(ideal)
        out_iv.append(now - prev)
        prev = now
    total = prev

    # ---- 按住：同乘系数，再按新间隔重做一次 cap_holds 的钳制
    onset = []
    t = 0
    for iv in out_iv:
        t += iv
        onset.append(t)
    out_h = []
    for k, (_i, _p, _iv, keys, h) in enumerate(body):
        if not keys:
            out_h.append(h)                      # 休止格：原样（本来就是空列）
            continue
        bar = bars[k - 1] if k else bars[0]
        if h is None:
            out_h.append(None)                   # 本来就没写第三列 → 别给它加上
            continue
        nh = half_up((h + GAP) * a.base / tempo_of(bar, segs)) - GAP
        j = next((x for x in range(k + 1, len(body)) if body[x][3]), None)
        if j is None:
            out_h.append(max(HOLD_MIN, nh))       # 末个发声行不钳上限
        else:
            cap = onset[j] - onset[k] - GAP
            out_h.append(max(HOLD_MIN, min(nh, cap)))

    # ---- 回写
    newlines = list(lines)
    note = ("#  ⚠ 原谱中途变速，间隔已按分段重算："
            + " ｜ ".join("第%d-%s小节 ♩=%g"
                          % (b, (segs[i + 1][0] - 1) if i + 1 < len(segs) else "末", v)
                          for i, (b, v) in enumerate(segs)))
    note2 = ("#     （上面「一行 = … 毫秒」是 ♩=%g 的基准格；本次由 获取谱子/retime.py"
             " 重算，改谱请重跑）" % a.base)
    for k, (i, parts, _iv, _keys, _h) in enumerate(body):
        parts = list(parts)
        parts[0] = str(out_iv[k])
        if len(parts) >= 3:
            parts[2] = str(out_h[k])
        newlines[i] = " ".join(parts)
    at = next((i for i, ln in enumerate(newlines) if "一行 =" in ln), None)
    if at is None:
        at = max(i for i, ln in enumerate(newlines) if ln.startswith("#")) + 1
        newlines[at:at] = [note, note2]
    else:
        newlines[at + 1:at + 1] = [note, note2]
    out = "\n".join(newlines) + ("\n" if tail_nl else "")

    # ---- 自检
    problems = []
    if len(out_iv) != len(body):
        problems.append("行数变了")
    if any(v <= 0 for v in out_iv):
        problems.append("有非正的间隔")
    if any(v < HOLD_MIN for v in out_h if v):
        problems.append("有低于下限 %dms 的按住" % HOLD_MIN)

    tmp = (path.parent / (path.name + ".retime.tmp")).resolve()
    tmp.write_text(out, encoding="utf-8", newline="\n")
    mod = load_parser()
    notes = mod.parse(str(tmp))
    j2s = load_converter()
    worst, wl = j2s.simulate(notes, 1.0)
    if worst > 1e-6:
        problems.append("模拟播放出现 %.1fms 迟到（第 %s 行）" % (worst, wl))
    if len(notes) != len(body):
        problems.append("parser 回读行数 %d ≠ %d" % (len(notes), len(body)))
    keys_old = [sorted(p[1]) if len(p) > 1 else [] for (_i, p, _v, _k, _h) in body]
    keys_new = [sorted("".join(n.keys) if not isinstance(n.keys, str) else n.keys)
                for n in notes]
    if keys_old != keys_new:
        bad = next(i for i, (x, y) in enumerate(zip(keys_old, keys_new)) if x != y)
        problems.append("按键列第 %d 行变了：%s → %s" % (bad + 1, keys_old[bad],
                                                        keys_new[bad]))
    dur = sum(out_iv) + (out_h[-1] or 0)

    log("  时长 %.1fs（Σ间隔 %dms + 末行按住 %dms）｜ 模拟播放最大迟到 %.1fms"
        % (dur / 1000.0, sum(out_iv), out_h[-1] or 0, worst))
    if problems:
        for p in problems:
            log("  ✗ " + p)
        tmp.unlink(missing_ok=True)
        return 1
    log("  ✓ 自检通过：行数 / 按键列 / 间隔正数 / 按住上下限 / parser 回读 / "
        "模拟播放零迟到 / 编码")
    if not a.write:
        log("  （试运行，未写盘；要落盘加 --write）")
        tmp.unlink(missing_ok=True)
        return 0
    bak = Path(str(path) + ".bak")
    if bak.exists():
        log("  ⚠ 备份已存在，先删旧的 %s" % bak.name)
        bak.unlink()
    path.replace(bak)
    tmp.replace(path)
    log("  ✓ 已写出 %s（原文件备份为 %s）" % (path, bak.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
