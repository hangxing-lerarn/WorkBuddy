# -*- coding: utf-8 -*-
"""audit4.py —— 交付前最后一道交叉验证。

把 `scores/起风了（简谱转）.txt` 用**真实 parser** 回读成音符序列，
再独立地从两个简谱文件（旋律 + 伴奏）算出「每个音应该在什么时刻、
按哪些键」，两者逐音比对（时刻容差 1ms、键集合必须全等）。

这能抓到：丢音、错键、时刻漂移、--overlay 合并错误。
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(r"C:/Users/HUAWEI/Desktop/original-guitar-tool-master")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "获取谱子"))
from parser import parse  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "J", str(ROOT / "获取谱子/jianpu_to_score.py"))
J = importlib.util.module_from_spec(spec)
spec.loader.exec_module(J)

PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72,
         74, 76, 77, 79, 81, 83]
KEYS = "zxcvbnmasdfghjqwertyu"
P2K = {p: k for k, p in zip(KEYS, PITCH)}


def main():
    txt = io.open(ROOT / "scores/起风了（简谱转）.txt", encoding="utf-8").read()
    notes = parse(str(ROOT / "scores/起风了（简谱转）.txt"))
    got = {}
    for n in notes:
        got.setdefault(n.time, set()).update(n.keys)
    print("机器谱回读：%d 个音符事件，%d 个不同时刻"
          % (len(notes), len(got)))

    # ---- 基调：音符总数对账 ----
    #    `jianpu_to_score.py` 自报「合计 N 音」；机器谱回读的键数必须与之相等。
    #    这是**最直接的零丢失证据**（比逐时刻对账更抗模型差异）。
    tot = 0
    for fn in ("简谱/起风了（旋律）.txt", "简谱/起风了（伴奏）.txt"):
        m, ev, mk, u, pr = J.parse_jianpu(
            io.open(ROOT / fn, encoding="utf-8").read())
        n = sum(len([d for d in e["degs"] if d[0]]) for e in ev)
        print("  %-28s %d 个事件 / %d 个音" % (fn, len(ev), n))
        tot += n
    keys_read = sum(len(n.keys) for n in notes)
    print("  合计 %d 音；机器谱回读 %d 个键 → %s"
          % (tot, keys_read, "零丢失 ✓" if tot == keys_read else "有丢失 ✗"))

    # ---- 独立重算：从两个简谱各自 parse 出事件 + 键，合并 ----
    voices = []
    for fn in ("简谱/起风了（旋律）.txt", "简谱/起风了（伴奏）.txt"):
        meta, events, markers, unit, probs = J.parse_jianpu(
            io.open(ROOT / fn, encoding="utf-8").read())
        voices.append((fn, meta, events, unit))
    meta = voices[0][1]
    unit = voices[0][3]
    # ⚠️ 一格的毫秒数 = 四分音符时长 × 格占几拍。
    #    写 `60000/bpm/(4*unit)` 是错的（多除掉 4）：BPM=77 时四分音符 = 779.2ms，
    #    unit=0.25 拍 → 一格 = 194.8ms。写成除 `4*unit` 会得 779.2ms（差 4 倍）。
    unit_ms = (60000.0 / meta["bpm"]) * unit
    print("格 = %g 拍 = %.1f ms（1=%s %g/4 %d BPM）"
          % (unit, unit_ms, meta["key"], meta["beats_per_bar"], meta["bpm"]))

    # ⚠️ `render()` 的事件从 cursor=0 起排，但 `parser` 是**先累加间隔再记音符**
    #    → 机器谱里第 1 个音符的时刻 = 首行的间隔值（起手延迟）。所以重算时要
    #    加上这个偏移才能与 `parse()` 对齐。首行间隔 = 第一格的长度。
    OFFSET = unit_ms
    exp = {}
    for fn, m, events, u in voices:
        cursor = 0
        for e in events:
            n = int(round(e["beats"] / u))
            ks = set()
            for deg, acc, octs in e["degs"]:
                if deg == 0:
                    continue
                p = J.raw_pitch(deg, acc, octs, 0)
                ks.add(p)
            if ks:
                key = round(cursor * unit_ms + OFFSET, 1)
                exp.setdefault(key, set()).update(ks)
            cursor += n

    print("独立重算：%d 个不同时刻" % len(exp))

    # ---- 比对 ----
    gk = sorted(got)
    ek = sorted(exp)
    bad_t = 0
    for k in ek:
        if not any(abs(k - g) <= 1.0 for g in gk):
            bad_t += 1
            if bad_t <= 5:
                print("  !! 时刻 %.1f 在机器谱中找不到（键 %s）"
                      % (k, sorted(P2K.get(p, "?") for p in exp[k])))
    # 键集合比对
    bad_k = 0
    for k in ek:
        near = [g for g in gk if abs(k - g) <= 1.0]
        if not near:
            continue
        g = near[0]
        a = {P2K[p] for p in exp[k] if p in P2K}
        if a != got[g]:
            bad_k += 1
            if bad_k <= 8:
                print("  !! 时刻 %.1f 键不一致：简谱 %s / 机器谱 %s"
                      % (k, sorted(a), sorted(got[g])))
    print()
    print("时刻对账：%d 处不匹配（应 0）" % bad_t)
    print("键集合对账：%d 处不匹配（应 0）" % bad_k)
    print("结论：%s" % ("逐音一致 ✓" if bad_t == 0 and bad_k == 0
                     else "存在差异 ✗"))


if __name__ == "__main__":
    main()
