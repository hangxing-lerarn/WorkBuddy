# -*- coding: utf-8 -*-
"""gen_jianpu.py —— 从 glyphs3.json 生成《起风了》的两个简谱文本。

产物（写到仓库 `简谱/`）：
  · 起风了（旋律）.txt   上谱表
  · 起风了（伴奏）.txt   下谱表

排版口径（沿用《Cry For Me》沉淀下来的约定）：
  · 首行必填 `1=C 4/4 <BPM>`
  · 每系统一行（4 小节），前面加 `@ 第 N 小节（XXX 第 M 系统）`
  · 小节之间用 ` | ` 分隔，行尾也是 ` |`
  · 无点 = 中音；`'` = 高音；`,` = 低音；`/` 八分、`//` 十六分、`///` 三十二分
  · 附点以**点后缀**写（`3/.`），连音线以 `~` 前缀写（`~3/`）
  · 增时线 `-`；和弦 `(1 3 5)`
  · 2/4 小节照样输出（由 `jianpu_to_score.py` 按小节总时值自动对齐）

⚠️ **附点绝不能写成 `·` 前缀**：`jianpu_to_score.py` 有 `.replace("·", "0")`，
   `·` 是**休止符**的等价写法 → `·2/` 会被折成 `02/`，直接报
   `无法识别的记谱 token：'02/'`。必须写 `2/.`（点在减时线**之后**）。

⚠️ 本谱的 **BPM**：谱面标注 ♩=77，首行写 `1=C 4/4 77`。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trans3 import (build, eval_bar, barx, global_tsig,  # noqa: E402
                    want_beats, time_sig_bars, NCB)

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:/Users/HUAWEI/Desktop/original-guitar-tool-master/简谱")
BPM = 77
SONG = "起风了"

HEAD = """1=C 4/4 {bpm}
# 《{song}》 风物之诗琴简谱（{part}）
# 原曲：买辣椒也用券《起风了》（ヤキモチ）　|　1=C 4/4 ♩={bpm}　|　3 页 17 系统 68 小节（双手钢琴改编）
# 来源：桌面 1.jpg / 2.jpg / 3.jpg（后缀是 .jpg，**实际是 AVIF 格式**）→ 逐页像素级识谱
#
# 读谱请先看这几条约定（都是实拍反例推翻过一次才定下来的）：
#   · 无点 = 中音区；上点写作 ' = 高音区；下点写作 , = 低音区
#   · 一条减时线 / = 八分，// = 十六分，/// = 三十二分
#   · 附点写在音**后面**（如 3/. = 附点八分；⚠️ 写成 ·3/ 会被当成休止 0 而报错）
#   · ~X = 与**前一个同音**相连的连音线（谱面上的浅灰音符：不重弹，时值照算）
#   · 谱面上跨不同音的弧线是圆滑线（连奏），不是连音线，本文件不写 ~
#   · 增时线 - 把前一个音延长一拍
#   · (1 3 5) = 同时按下的和弦
#   · 谱面有 3 处变拍号：第 34 小节起 `2/4`，第 35 小节末恢复 `4/4`；
#     第 63 小节起 `2/4`，第 65 小节恢复 `4/4`。
#
# 质量口径：136 个「小节·声部」全部逐小节拍数 == 期望值（4 拍；2/4 小节 = 2 拍），
#          独立重算 0 例外。
# 已知残留风险：八度点方向（上/下）在最密处偶有歧义，实弹听到走调处请指名反馈。
"""


def main():
    box, systems = build()
    ts = global_tsig(box, systems)
    texts = {"mel": [], "bas": []}
    nobad = 0
    for seq, s in enumerate(systems):
        pg, sy = s["page"], s["sys"]
        tgs = time_sig_bars(box, pg, sy)
        for st in ("mel", "bas"):
            seg = []
            for b in range(1, NCB + 1):
                xa, xb = barx(systems, pg, sy, b)
                want = want_beats(ts, seq, xa, xb)
                t, out = eval_bar(box, (pg, sy, b, st), xa, xb, tgs)
                if abs(t - want) > 1e-6:
                    nobad += 1
                    print("!! p%ds%db%d %s %.2f != %.0f" % (pg, sy, b, st, t, want))
                toks = [x[1] for x in out]
                seg.append(" ".join(toks) if toks else "0")
            head = "@ 第 %d 小节（%s 第 %d 系统）" % (
                (seq) * NCB + 1,
                "旋律" if st == "mel" else "伴奏", seq + 1)
            texts[st].append(head + "\n" + " | ".join(seg) + " |")
    print("拍数异常 %d 个（应为 0）" % nobad)
    assert nobad == 0, "拍数自检未全绿，拒绝写文件"
    for st, fn in (("mel", "起风了（旋律）.txt"), ("bas", "起风了（伴奏）.txt")):
        part = "上谱表 · 旋律声部" if st == "mel" else "下谱表 · 伴奏声部"
        p = OUT / fn
        if p.exists():
            p.with_suffix(p.suffix + ".bak").write_bytes(p.read_bytes())
        body = HEAD.format(bpm=BPM, song=SONG, part=part) + "\n".join(texts[st]) + "\n"
        p.write_text(body, encoding="utf-8", newline="\n")
        print("写出", p, len(body), "字节")


if __name__ == "__main__":
    main()
