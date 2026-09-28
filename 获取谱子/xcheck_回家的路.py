# -*- coding: utf-8 -*-
"""xcheck.py —— 独立对账：另一套解码逻辑回读产物，与字母谱逐事件比对。

与 字母谱转谱.py 的差异：不复用其代码，直接按拍平铺，
和弦按「集合」比（转换器会把和弦按琴键高低排序，字母序≠键序）。
"""
import sys
from pathlib import Path

KEYS = "zxcvbnmasdfghjqwertyu"
PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
         72, 74, 76, 77, 79, 81, 83]
K2P = dict(zip(KEYS.upper(), PITCH))
BPM = 110.0
BEAT = 60000.0 / BPM

# ---- 独立解码字母谱 ----
want = []          # (is_chord, frozenset(midi))
t = BEAT           # 起手一拍
times = []         # 每个发声事件的起始时刻
with open(Path(__file__).parent / "回家的路（字母谱）.txt", encoding="utf-8") as f:
    for raw in f:
        line = raw.strip()
        if not line or "/" not in line:
            continue
        fields = line.split("/")
        if line.endswith("/"):
            fields.pop()
        for fld in fields:
            toks = []
            i = 0
            while i < len(fld):          # 手写括号感知（不复用正则）
                if fld[i] == "(":
                    j = fld.index(")", i)
                    toks.append(fld[i + 1:j])
                    i = j + 1
                elif fld[i].isalpha():
                    toks.append(fld[i])
                    i += 1
                else:
                    i += 1
            if not toks:
                t += BEAT
                continue
            step = BEAT / len(toks)
            for tk in toks:
                mids = frozenset(K2P[c] for c in tk)
                want.append((len(tk) > 1, mids))
                times.append(t)
                t += step

# ---- parser 回读产物 ----
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parser as P
notes = [n for n in P.parse(
    Path(__file__).parent.parent / "scores" / "回家的路（直接转）.txt") if n.keys]

errs = []
if len(want) != len(notes):
    errs.append(f"事件数不等: 字母谱 {len(want)} vs 产物 {len(notes)}")
for k, ((wc, wm), n) in enumerate(zip(want, notes)):
    got = frozenset(PITCH[KEYS.index(s)] for s in n.keys)
    if (len(n.keys) > 1) != wc:
        errs.append(f"事件 {k}: 单/和弦不符 {n.keys} vs chord={wc}")
    if got != wm:
        errs.append(f"事件 {k}: 音集不符 {sorted(got)} vs {sorted(wm)}")
    if abs(n.time - times[k]) > 1.5:   # 取整允许 ±1.5ms
        errs.append(f"事件 {k}: 时刻漂移 {n.time} vs {times[k]:.1f}")

print(f"字母谱发声事件 {len(want)} / 产物发声事件 {len(notes)}")
print(f"对账差异 {len(errs)} 处")
for e in errs[:10]:
    print(" ", e)
sys.exit(1 if errs else 0)
