# -*- coding: utf-8 -*-
"""audit3.py —— 按「整系统」做同素材逐字比对（比按小节更贴合谱面结构）。

谱面素材重复关系（人工读谱得到，用于交叉验证转写忠实度）：
  主题A   : 第 1 系统 == 第 2 系统 == 第 10 系统（前半） == 第 17 系统
  副歌B   : 第 7 系统 == 第 8 系统 == 第 14 系统 == 第 15 系统
  副歌B'  : 第 7 系统第 2 小节 == 第 8 系统第 2 小节（同素材）
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(r"C:/Users/HUAWEI/Desktop/original-guitar-tool-master")


def systems(text):
    out = {}
    cur = None
    for ln in text.splitlines():
        if ln.startswith("@ 第 "):
            cur = int(re.match(r"@ 第 (\d+) 小节", ln).group(1))
            out[cur] = []
        elif cur is not None and ln.strip():
            out[cur].append(ln.strip())
    # 每个起点一行（4 小节），去掉行尾的 " |"
    return {k: " ".join(v).rstrip("|").strip() for k, v in out.items()}


def bars(text):
    """返回 {起始小节号: [小节串, ...]}"""
    s = systems(text)
    out = {}
    for k, v in s.items():
        out[k] = [b.strip() for b in v.split("|")]
    return out


def main():
    for tag, fn in (("旋律", "简谱/起风了（旋律）.txt"),
                    ("伴奏", "简谱/起风了（伴奏）.txt")):
        text = io.open(ROOT / fn, encoding="utf-8").read()
        B = bars(text)
        print("=" * 72)
        print("【%s】整系统同素材比对" % tag)
        for name, starts in (
                ("主题A", [1, 5, 37, 65]),
                ("副歌B", [25, 29, 53, 57]),
                ("连接句", [9, 13, 41]),
        ):
            got = {}
            for st in starts:
                if st in B:
                    got.setdefault(tuple(B[st]), []).append(st)
                else:
                    print("   ?? 缺 第%d小节" % st)
            if not got:
                continue
            print("   %s：" % name)
            for seg, where in got.items():
                print("      出现在 %-16s %s" % (where, " | ".join(seg)[:120]))
            print("      → %s" % ("全部一致 ✓" if len(got) == 1 else "有 %d 种形态" % len(got)))


if __name__ == "__main__":
    main()
