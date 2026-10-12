# -*- coding: utf-8 -*-
"""字母谱对账 —— 独立解码器逐事件比对字母谱原文与产物曲谱。

与 字母谱转谱.py 刻意不复用代码（手写括号扫描 vs 正则、独立时间轴），
两边算出的结果必须完全一致才放行。用法：

    python 字母谱对账.py <字母谱.txt> <产物.txt>

比对项：发声事件数、每个事件的「单音/和弦 + 音集（集合比，和弦序不比）」、
起始时刻（±1.5ms 取整容差）、延音事件的按住第三列、
以及「普通事件不得带按住第三列」（收尾和弦除外）。速度从产物头「（NNN BPM）」注释自动读。
"""
import re
import sys
from pathlib import Path

KEYS = "zxcvbnmasdfghjqwertyu"
PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
         72, 74, 76, 77, 79, 81, 83]
K2P = dict(zip(KEYS.upper(), PITCH))
LEAD_IN_BEATS = 1.0          # 必须与 字母谱转谱.py 的约定一致


def decode_letter(path, bpm):
    """独立解码字母谱 → ([(is_chord, frozenset(midi), hold期望或None)], [起始时刻ms])。

    与转谱器同一套格式约定，但实现独立（手写扫描、独立时间轴）：
    附点「.」= 时值 ×1.5；延音「~」= 不发声、时值并入前一个事件
    （前一个事件的期望按住 = 本音时值 + 并入时值 − 10ms）。
    """
    beat = 60000.0 / bpm
    want, times = [], []
    durs, exts = [], []          # 每个已发声事件：自身时值 / 被延音并入的时值
    t = LEAD_IN_BEATS * beat
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            has_slash = "/" in line
            has_letter = re.search(r"[A-Z]", line) is not None
            if not has_slash and not has_letter:
                continue                      # 段落标签
            fields = line.split("/") if has_slash else [line, "", "", ""]
            if has_slash and line.endswith("/"):
                fields.pop()
            for fld in fields:
                # 手写扫描：~ 前缀 / ( ) 和弦 / . 附点 / - 延时线 / 0 显式休止
                toks, i = [], 0
                while i < len(fld):
                    tie = fld[i] == "~"
                    if tie:
                        i += 1
                    if i < len(fld) and fld[i] == "(":
                        j = fld.index(")", i)
                        body, i = fld[i + 1:j], j + 1
                    elif i < len(fld) and fld[i] == "-":
                        toks.append(("-", False, tie))
                        i += 1
                        continue
                    elif i < len(fld) and fld[i] == "0":
                        body, i = "0", i + 1
                    elif i < len(fld) and fld[i] in KEYS.upper():
                        body, i = fld[i], i + 1
                    else:
                        if tie:
                            raise ValueError(f"孤立的 ~：{fld!r}")
                        i += 1
                        continue
                    dot = i < len(fld) and fld[i] == "."
                    if dot:
                        i += 1
                    if body.endswith("."):      # 点在括号内 (XS.) 也认
                        dot = True
                        body = body[:-1]
                    body = body.replace(" ", "")   # 和弦内允许空格 (C H W)
                    toks.append((body, dot, tie))
                if not toks:
                    t += beat
                    continue
                total_w = sum(1.5 if dot else 1.0 for _, dot, _ in toks)
                base = beat / total_w
                for body, dot, tie in toks:
                    dur = base * (1.5 if dot else 1.0)
                    if body == "-":
                        if not want:
                            raise ValueError("延时线 - 前面没有任何音")
                        exts[-1] += dur     # 并入前一个音
                        t += dur
                        continue
                    if tie:
                        if not want:
                            raise ValueError(f"延音线 ~{body} 前面没有任何音")
                        miss = [c for c in body if K2P[c] not in want[-1][1]]
                        if miss:
                            raise ValueError(f"延音线 ~{body} 与前一音不接")
                        exts[-1] += dur     # 并入前一个音
                    elif body == "0":
                        pass                # 显式休止：只推时间，不发声
                    else:
                        want.append((len(body) > 1,
                                     frozenset(K2P[c] for c in body), None))
                        durs.append(dur)
                        exts.append(0.0)
                        times.append(t)
                    t += dur
    # 期望按住 = 本音时值 + 被并入时值（延音/延时线）− 10ms 余量，
    # 再按取整时间轴预钳到「下一个发声事件 − 10」—— 与转谱器/解析器一致
    exp_hold = []
    for k in range(len(want)):
        h = round(durs[k] + exts[k]) - 10 if exts[k] > 0 else None
        if h is not None and k + 1 < len(want):
            h = min(h, round(times[k + 1]) - round(times[k]) - 10)
        exp_hold.append(h)
    want = [(w, m, exp_hold[k]) for k, (w, m, _) in enumerate(want)]
    return want, times


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    head = dst.read_text(encoding="utf-8")[:600]
    bpm = float(re.search(r"（(\d+(?:\.\d+)?) BPM）", head).group(1))
    want, times = decode_letter(src, bpm)

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import parser as P
    notes = [n for n in P.parse(dst) if n.keys]

    errs = []
    if len(want) != len(notes):
        errs.append(f"事件数不等: 字母谱 {len(want)} vs 产物 {len(notes)}")
    for k in range(min(len(want), len(notes))):
        (wc, wm, wh), n = want[k], notes[k]
        got = frozenset(PITCH[KEYS.index(s)] for s in n.keys)
        if (len(n.keys) > 1) != wc:
            errs.append(f"事件 {k}: 单/和弦不符 {n.keys} vs chord={wc}")
        if got != wm:
            errs.append(f"事件 {k}: 音集不符 {sorted(got)} vs {sorted(wm)}")
        if abs(n.time - times[k]) > 1.5:
            errs.append(f"事件 {k}: 时刻漂移 {n.time} vs {times[k]:.1f}")
        if wh is not None and k != len(notes) - 1 and n.hold != wh:
            # 末事件按「到所属小节末尾」收尾，另算
            errs.append(f"事件 {k}: 延音按住不符 {n.hold} vs 期望 {wh}")
        if wh is None and n.hold != 0 and k != len(notes) - 1:
            # 无延音的普通事件不该有第三列（收尾和弦除外，另算）
            errs.append(f"事件 {k}: 意外的按住第三列 {n.hold}")

    print(f"BPM {bps_str(bpm)}｜字母谱发声事件 {len(want)} / 产物 {len(notes)}")
    print(f"对账差异 {len(errs)} 处")
    for e in errs[:10]:
        print(" ", e)
    sys.exit(1 if errs else 0)


def bps_str(bpm):
    return str(int(bpm)) if bpm == int(bpm) else str(bpm)


if __name__ == "__main__":
    main()
