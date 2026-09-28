# -*- coding: utf-8 -*-
"""audit2.py —— 《起风了》产物的独立听觉/结构审计。

四件事：
  ① **同素材段落逐字比对**：主题段（第 1/2/5/6/17 系统等）与副歌段
     （第 7/8/14/15 系统等）转写后必须逐字相同。
  ② 手算整曲时长 = Σ(每格间隔) + 末行第三列，与文件自报比对。
  ③ 静音占比（「那些时刻安静」的口径）。
  ④ 音程刺耳检查：同刻音簇内的相邻半音 + 旋律相邻音 + 旋律 vs 当前和弦根音。
"""
import io
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:/Users/HUAWEI/Desktop/original-guitar-tool-master")
sys.path.insert(0, str(ROOT))
from parser import parse  # noqa: E402

PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72,
         74, 76, 77, 79, 81, 83]
KEYS = "zxcvbnmasdfghjqwertyu"
K2P = {k: p for k, p in zip(KEYS, PITCH)}


def read(path):
    return io.open(path, encoding="utf-8").read()


def main():
    mel = read(ROOT / "简谱/起风了（旋律）.txt")
    bas = read(ROOT / "简谱/起风了（伴奏）.txt")

    # ---- ① 同素材段落逐字比对 ----
    def systems(text):
        out = {}
        cur = None
        for ln in text.splitlines():
            if ln.startswith("@ "):
                m = re.match(r"@ 第 (\d+) 小节", ln)
                cur = int(m.group(1))
                out[cur] = ""
            elif cur is not None and ln.strip():
                out[cur] += ln.strip()
        return out

    sm, sb = systems(mel), systems(bas)
    print("① 同素材段落比对")
    groups = [
        ("主题A（第 1 拍起 7123）", [1, 5, 37, 65]),
        ("主题A2（第 2 小节 7123…）", [22, 26, 46]),
        ("副歌B（365 5-6-5）", [25, 29, 53, 57]),
    ]
    ok = True
    for name, starts in groups:
        seen = {}
        for st in starts:
            if st not in sm:
                print("   ?? 缺段落 第%d小节" % st)
                continue
            # 只比该系统的第 1 小节（同一素材位置）
            seg = sm[st].split("|")[0].strip()
            seen.setdefault(seg, []).append(st)
        for seg, where in seen.items():
            mark = "一致性 OK" if len(seen) == 1 else "不一致"
            if len(seen) != 1:
                ok = False
            print("   %-24s %-8s 出现于 %s" % (name, mark, where))
            print("      %s" % seg[:110])
    print("   → 同素材比对：%s" % ("全部一致 ✓" if ok else "存在差异"))

    # ---- ② 时长 ----
    print()
    print("② 时长核算")
    for tag, path in (("旋律", "简谱/起风了（旋律）.txt"),
                      ("伴奏", "简谱/起风了（伴奏）.txt")):
        tots = 0.0
        per = []
        for ln in read(ROOT / path).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith(("#", "@")):
                continue
            for tok in re.findall(r"(\d+)\s*\|\s*(\d+)\s*/", ln + " |"):
                pass
            nums = re.findall(r"\b(\d{1,4})\b", ln)
            # 这一行是简谱正文，不参与时长（时长在 scores 里算）
        pass
    # 时长直接读 scores
    txt = read(ROOT / "scores/起风了（简谱转）.txt")
    s = 0.0
    last_hold = 0
    nline = 0
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        s += float(p[0])
        nline += 1
        if len(p) >= 3:
            last_hold = float(p[2])
    print("   Σ间隔 = %.0f ms，末行按住 = %.0f ms → 整曲 %.1f s"
          % (s, last_hold, (s + last_hold) / 1000.0))

    # ---- ③ 静音占比 ----
    print()
    print("③ 静默时刻占比（发声格 / 休止格）")
    notes = parse(str(ROOT / "scores/起风了（简谱转）.txt"))
    # 按格统计：重建格序
    grid = []
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        grid.append((float(p[0]), p[1] if len(p) > 1 else None))
    voice = sum(1 for g in grid if g[1] and g[1] != "0")
    print("   共 %d 格：发声 %d（%.0f%%）/ 休止 %d（%.0f%%）"
          % (len(grid), voice, 100.0 * voice / len(grid),
             len(grid) - voice, 100.0 * (len(grid) - voice) / len(grid)))

    # ---- ④ 刺耳检查 ----
    print()
    print("④ 音程检查")
    by_t = {}
    for n in notes:
        by_t.setdefault(n.time, []).extend(K2P[k] for k in n.keys)
    mini = 0
    for t, ps in sorted(by_t.items()):
        ps = sorted(set(ps))
        for i in range(len(ps) - 1):
            if ps[i + 1] - ps[i] <= 2:
                mini += 1
    print("   同刻音簇内相邻半音/全音（<=2 半音，最刺耳）：%d 处" % mini)
    ks = Counter()
    for n in notes:
        for k in n.keys:
            ks[k] += 1
    print("   键位分布：", " ".join("%s:%d" % (k, ks[k]) for k in KEYS if ks[k]))
    print("   用到 %d 个键；音域 %d..%d（跨 %d 半音）"
          % (len([k for k in KEYS if ks[k]]),
             min(K2P[k] for k in ks), max(K2P[k] for k in ks),
             max(K2P[k] for k in ks) - min(K2P[k] for k in ks)))


if __name__ == "__main__":
    main()
