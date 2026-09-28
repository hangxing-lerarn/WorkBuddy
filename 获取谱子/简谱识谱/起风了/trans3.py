# -*- coding: utf-8 -*-
"""glyphs3.json → 简谱文本（拍数自检 + dump）

时值 = (1/2^减时线数) × (附点 ? 1.5 : 1)；1 小节 = 4 拍。

⚠️ **减时线的「条数」不能直接数横线块，要先按 x 切开**：
   谱面上 `7123`（四个音）共用一条长减时线（w51），`53`（两个音）共用一条（w25），
   单音 `3` 各有一条（w7~11）。同一条线上每个音的减时线**条数相同**，
   所以做法是：把每个 beam 块按它覆盖到的数字列切开，让每列各得一份。

八度点判据：点相对**减时线**在谱表外侧 = 该手常态八度；在内侧 = 换八度。
  上方手：点在数字**上**方（y 更小）= 常态
  下方手：点在数字**下**方（y 更大）= 常态
实测反例：`4 1` 的点在数字下方且更靠外 → 若按「点在数字下=低八度」会读成 `4, 1,`，
与下一小节的 `3 7 3`（无点）自相矛盾（同一只手不会在相邻小节换记谱八度区）。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
IMG = {p: np.array(Image.open(HERE / f"p{p}.png").convert("L"))
       for p in (1, 2, 3)}
DIGIT = {int(k): v for k, v in json.loads(
    (HERE / "labels.json").read_text(encoding="utf-8")).items()}
BEAMSTR = {0: "", 1: "/", 2: "//", 3: "///", 4: "////"}
TOL = 1e-6
NCB = 4


def ov(a0, a1, b0, b1, tol=1):
    return min(a1, b1) - max(a0, b0) >= tol


def build():
    data = json.loads((HERE / "glyphs3.json").read_text(encoding="utf-8"))
    systems = data["systems"]
    box = defaultdict(lambda: {"dig": [], "beam": [], "dot": [], "junk": []})
    for g in data["glyphs"]:
        if g["kind"] == "bar":
            continue
        s = next(t for t in systems
                 if t["page"] == g["page"] and t["sys"] == g["sys"])
        bars = s["bars"]
        b = 1
        for i in range(len(bars) - 1):
            if bars[i] <= g["cx"] < bars[i + 1]:
                b = i + 1
                break
        else:
            if g["cx"] >= bars[-1]:
                b = len(bars)
        # ⚠️ junk 也要收：拍号 `2/4` `4/4` 的上下两个小数字（h7 / h12）
        #    会被 `kind_of` 判成 junk，它们是**识别拍号的唯一线索**。
        box[(g["page"], g["sys"], b, g["staff"])][
            {"glyph": "dig", "beam": "beam", "dot": "dot",
             "junk": "junk"}[g["kind"]]].append(g)
    return box, systems


def read_tsig_num(img, B):
    """读变拍号的**分子**（拍号分数线上方的小数字）。

    ⚠️ 本谱出现的变拍号只有 `2/4` 与 `4/4` 两种，分子 `2` 与 `4` 的形状差别很大：
      `2`：上半是圆弧，**最下面一行是一条满宽横杠**（实测 y321-322 连续 7 个 `#`）
      `4`：主体是一撇 + 一竖，**中间偏下有一条满宽横杠**（实测 y318-319）
    判据：取上方小数字的外接框，逐行数最长连续 `#`；
      **最后一行**接近满宽 → `2`；**中间某行**接近满宽（且末行不满）→ `4`。
    这样就不必依赖必须看得清字形的 OCR，只需数一条横杠的位置。
    """
    x0, x1 = int(B["x0"]) - 4, int(B["x1"]) + 5
    y1 = int(B["y0"]) - 1
    y0 = max(0, y1 - 20)
    sub = (img[y0:y1, x0:x1] < 160)
    if sub.size == 0:
        return 4
    rows = []
    for r in range(sub.shape[0]):
        best = cur = 0
        for c in range(sub.shape[1]):
            cur = cur + 1 if sub[r, c] else 0
            best = max(best, cur)
        rows.append(best)
    # ⚠️ **必须先裁掉上下空白行**（这一条实踩过）。裁剪带固定 20px 高，而小数字
    #    只占 11~12px → `rows[-1]` 取到的是**底部空白行**（恒 0），「末行满宽」
    #    判据永远不成立，于是**所有拍号都被读成 4/4**（p2s2 x=371 的真 2/4 受害）。
    while rows and rows[0] == 0:
        rows.pop(0)
    while rows and rows[-1] == 0:
        rows.pop()
    if not rows:
        return 4
    # ⚠️ 「满宽」必须相对**该数字自身的最长横杠**，不能相对裁剪带宽度。
    #    裁剪带宽 23px，而真正的数字只有 9px 宽 → 用 0.55×W=12 当阈值，
    #    连 `4` 的 9px 横杠都够不着，还是会全读成 4。
    mx = max(rows)
    full = max(3, int(mx * 0.85))
    n = len(rows)
    # `2`：最底一行是满宽横杠（y321-322 两条 7px）→ 命中末两行
    # `4`：横杠在中间（y318-319 两条 9px），末端仍是细竖笔 → 不命中末两行
    if rows[n - 1] >= full or (n >= 2 and rows[n - 2] >= full):
        return 2
    return 4


def time_sig_list(img, box, pg, sy):
    """返回 [(x, 分子)]，分子 ∈ {2,4}。"""
    out = []
    for b in range(1, NCB + 3):
        for st in ("mel", "bas"):
            it = box.get((pg, sy, b, st))
            if not it:
                continue
            for B in it["beam"]:
                if not (12 <= B["w"] <= 20 and B["h"] <= 3):
                    continue
                up = [j for j in it["junk"]
                      if ov(j["x0"], j["x1"], B["x0"], B["x1"], 2)
                      and j["y1"] < B["y0"] and B["y0"] - j["y1"] <= 8]
                dn = [j for j in it["junk"]
                      if ov(j["x0"], j["x1"], B["x0"], B["x1"], 2)
                      and j["y0"] > B["y1"] and j["y0"] - B["y1"] <= 8]
                if up and dn:
                    out.append((B["cx"], read_tsig_num(img, B)))
    # 同一 x 的 mel/bas 两根分数线合并
    out.sort()
    mg = []
    for x, n in out:
        if mg and abs(x - mg[-1][0]) <= 4:
            continue
        mg.append((x, n))
    return mg


def global_tsig(box, systems):
    """把全谱所有变拍号按**阅读顺序**排成 [(seq, x, 分子)]。

    seq = 该系统在 `systems` 里的下标。阅读顺序假设 `systems` 已按 p1s1→p3s2 排好。
    ⚠️ 拍号**跨系统延续**：p1 某处写了 `2/4`，后面每一个系统都是 2/4，直到出现 `4/4`
       才恢复。所以必须全局串起来，不能只看本系统。
    """
    out = []
    for i, s in enumerate(systems):
        for x, n in time_sig_list(IMG[s["page"]], box, s["page"], s["sys"]):
            out.append((i, x, n))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def want_beats(ts, seq, xa, xb):
    """本小节的期望拍数 = **最后一个对本小节生效**的拍号的分子。

    生效判据：
      · 该系统 seq 更靠前 → 已生效（延续）
      · 同一系统内 x <= xb（本小节右边界）→ 已生效（拍号就写在本小节开头）
        ⚠️ 故 x 落在**本小节之内**也算；落在更后面的小节里才算「尚未生效」。
      · 一个都没有 → 曲首默认的 `4/4` = 4 拍
    """
    cur = 4
    for (j, x, n) in ts:
        if j < seq or (j == seq and x <= xb):
            cur = n
    return float(cur)


def time_sig_bars(box, pg, sy):
    """扫出本系统里「拍号分数线」的 x 列表。

    ⚠️ **被实拍砸出来的坑**：本谱会在**小节中间**插入变拍号（`2/4` / `4/4`），
    写法是「小数字 2 / 短横 / 小数字 4」竖排。那条短横 w15、h1、画在数字行中线
    （与增时线 `-` 完全同高同宽），于是被当成 `-` 吞掉 →
    一小节凭空多 1 拍，`p2s2b2 = - 1 -`（3.00）就是这么来的。
    判据：**中线高度的横线，且它的上下各有一块小尺寸 junk**（上下两个数字）。
    真增时线 `-` 上下不会有这种成对小碎块。
    """
    out = []
    for b in range(1, NCB + 3):
        for st in ("mel", "bas"):
            it = box.get((pg, sy, b, st))
            if not it:
                continue
            for B in it["beam"]:
                if not (12 <= B["w"] <= 20 and B["h"] <= 3):
                    continue
                up = [j for j in it["junk"]
                      if ov(j["x0"], j["x1"], B["x0"], B["x1"], 2)
                      and j["y1"] < B["y0"] and B["y0"] - j["y1"] <= 8]
                dn = [j for j in it["junk"]
                      if ov(j["x0"], j["x1"], B["x0"], B["x1"], 2)
                      and j["y0"] > B["y1"] and j["y0"] - B["y1"] <= 8]
                if up and dn:
                    out.append(B["cx"])
    return out


def cols_of(digs):
    ds = sorted(digs, key=lambda d: (d["x0"], d["cy"]))
    cols = []
    for d in ds:
        if cols and ov(cols[-1]["x0"], cols[-1]["x1"], d["x0"], d["x1"], 2):
            c = cols[-1]
            c["x0"] = min(c["x0"], d["x0"])
            c["x1"] = max(c["x1"], d["x1"])
            c["mem"].append(d)
        else:
            cols.append({"x0": d["x0"], "x1": d["x1"], "mem": [d]})
    return cols


# 八度点与数字本体的**垂直间隙上限**。
#
# ⚠️ **这是本轮最隐蔽的一个 bug**（症状：连音线两端音高不一致，解析器报
#    `连音线两端的音不一样`）。
#    旧代码 `dns = [p for p in dots if abs(p.cx - d.cx) <= 12 and p.cy > d.y1 + 1]`
#    —— **没有任何距离上限**。后果：数字下方 ~25px 处的**下一行/歌词行的
#    减时线与汉字笔画碎块**被原样当成低八度点：
#    · p1s5b1 mel 的 `6 5 6`（数字 y1029-1046）正下方 y1070-1072 是**歌词
#      「这世间」的笔画碎块** → 被读成下加点 → 整行错成 `6, 5, 6,`；
#    · 而末尾的灰 tie 音 `6`(gray) 的 y1=1046，歌词碎块在 y1070 **恰好差 24px**，
#      凑不上 → 灰音仍是 `6` → `~6` 接不上前一个 `6,`。
#
#    修法：间隙必须落在 **[2, 21]**。这个区间是**实测双峰**分出来的（846 个候选）：
#      · gap 2~20.5 → 真八度点（537 个，含实测最大 20.5 的 bas 上加点）
#      · gap 21.5~44 → 全是假点（309 个），来源见上表
#    中间 21.0~21.5 之间**一个样本都没有**，分界干净。
OCT_DOT_MAXGAP = 21


def abs_bar(tok, dur):
    """把 token 换算成实际拍数。附点 = ×1.5。

    ⚠️ **附点必须写成「点后缀」**（`2/.`、`(6, 2)//.`），不能写成 `·` 前缀。
       实踩：`jianpu_to_score.py` 第 249 行有 `.replace("·", "0")` —— `·` 是
       **休止符**的等价写法，于是 `·2/` 会被折成 `02/` →
       `无法识别的记谱 token：'02/'`。项目约定（见 `Cry For Me（旋律）.txt` 头部）：
       `#   · 附点写在音后面（如 7/. = 附点八分）`。
       ⚠️ 附点在**减时线之后**（`2/.`：先八分再附点），不是 `2./`。
    """
    n = tok.count(".")
    return dur * (1.5 ** n)


def beam_counts(cols, realbeam):
    """每列实际挂几条减时线。

    ⚠️ **不能「逐列数覆盖它的横线块条数」**（这条实踩过，是整谱 3.50 的主因）。
       原写法 `nb = len({B["y0"]//3 for B in hit})`，对 `6 5 6 6̸` 会算出
       `6→2, 5→2, 6→2` —— 因为**上线覆盖了三列、下线覆盖了两列**，逐列都能看到
       两条横线。可原谱实际是 **`6` 八分 + `5 6` 十六分**（打印证据：
       上线 y1050-1051 覆盖 x128-178 = `6 5 6` 三列；下线 y1054-1056 覆盖
       x154-178 = 只有 `5 6`）→ 真实时值 0.5+0.25+0.25 = 1.0，原写法读成
       0.25+0.25+0.25 = 0.75，**每小节凭空少 0.25 拍**。

    正确模型：把 `realbeam` 里的横线块按 `(x0,x1)` 归组 —— **同一组减时线的多条线
       x 范围会完全一致**（如 `(154,178)` 出现两次 = 同一根「双横线」），
       所以 `grp[(x0,x1)] = 该 x 范围上有几条线`。某列的减时线条数 =
       **覆盖该列的所有组的条数之和**（`sum`，不是 `max`！）。

    ⚠️ **必须 `sum` 而不是 `max`**（实踩）：p1s3b1 mel = `2· 1 2· 1 2 3 5 3`，
       线组有 `(128,178)` 与 `(167,178)` 两组；对 `1`(x167-178) 这一列，
       **两组都覆盖它、各 1 条 → 共 2 条（十六分）**。用 `max` 只得 1 条
       → 每小节少 0.25 拍，全谱大面积 4.50/5.00。
    """
    grp = {}
    for B in realbeam:
        k = (B["x0"], B["x1"])
        grp[k] = grp.get(k, 0) + 1
    out = {}
    for i, c in enumerate(cols):
        n = 0
        for (gx0, gx1), k in grp.items():
            if ov(gx0, gx1, c["x0"], c["x1"], 1):
                n += k
        out[i] = min(n, 4)
    return out


def eval_bar(box, key, xa=None, xb=None, tsig=None):
    it = box.get(key)
    if not it:
        return 0.0, []
    if xa is None:
        xa, xb = -1e9, 1e9
    cols = cols_of(it["dig"])
    beams, dots = it["beam"], it["dot"]
    out = []
    # 数字行的中线 y = 数字本体的 y 中点（增时线画在这个高度）
    #
    # ⚠️ **必须用中位数，不能用平均数**。和弦的上方成员会画在本行上方的
    #    加线位置（实见 p2s2b1 bas：`(1 4)` 的 `1` 在 y378、`4` 在 y403），
    #    mean 被拽到 398.5，而增时线在 411 → `abs(411-398.5)=12.5 > 3`，
    #    **两条 `-` 全被当成减时线丢掉** → 该小节读出 2.00 拍。
    #    median 落在正常行 403~419 的中点 411，与增时线严丝合缝。
    if it["dig"]:
        ys = sorted((d["y0"] + d["y1"]) / 2 for d in it["dig"])
        midy = ys[len(ys) // 2]
    else:
        midy = None
    # ⚠️ beam 块里混着两种东西：**减时线**（贴数字下方，y≈340/344）与
    #    **增时线 `-`**（画在数字行中线，y≈327）。
    #    ⚠️ 而且**增时线的 y 在跨手时不一样**：上方手数字 y319..335（中线 327），
    #       下方手数字 y403..419（中线 411）。所以不能写死，要按本手的中线判。
    # ⚠️ **减时线必须在数字本体的下方**（`B.y0 > 数字 y1`）。
    #    实拍反例：p1s3b1 bas 的 `1 3 5 2 3`（数字 y757-773）上方 y724-730 有一批
    #    **w8~12 的短横线**（低音谱表的八度/装饰记号），它们与数字列 x 重叠，
    #    若不加这一条，`1` 会同时吃到「下方 y777-778 的减时线」+「上方 y729-730 的短横线」
    #    → 被判成**十六分**（`1,//`），整小节读出 3.75 拍。
    #
    # ⚠️⚠️ **还要限制「不能太远」**：本谱的**下加点**（低八度记号）是并列的两个小点，
    #    会被连通成一条 `w13 h2` 的横线（外观看就是一条减时线！）。
    #    实见 p1s4b4 mel 的 `1 - 1 2 3 1`：第一个 `1`(y851-867) 当然没有减时线，
    #    但 y892-893 出现 `BEM x873-885 w13`（两个下加点连成的横线，距数字 25px），
    #    被当减时线 → `1` 读成八分、末尾 `1` 读成 `1,/` → 该小节 3.25 拍。
    #    → **有效减时线距数字下缘 <= 20px**（实测真减时线 +5~6px，下加点 +25px）。
    dig_y1 = max((d["y1"] for d in it["dig"]), default=0)
    dash, realbeam = [], []
    for B in beams:
        # 只保留落在本小节 x 范围内的 beam（否则会串到别的小节去）
        if not ov(B["x0"], B["x1"], xa, xb, 1):
            continue
        # ⚠️ 变拍号 `2/4` `4/4` 的**分数线**与增时线同高同宽，必须先剔掉
        if tsig and any(abs(B["cx"] - t) <= 4 for t in tsig):
            continue
        if midy is not None and abs(B["cy"] - midy) <= 3 and B["w"] >= 8:
            dash.append(B)
        elif dig_y1 < B["y0"] <= dig_y1 + 20:      # 数字下方且不太远
            realbeam.append(B)
    # ⚠️ **过滤掉「落在数字外接框内部」的点**。
    #    灰 tie 音只被 `<128` 抓到最深的笔画，剩余的抗锯齿碎块会独立成小 dot
    #    （实见灰 `3` 内部散出 6 个点），灰 pass 又整块补上了这个数字
    #    → 同位置出现「数字 + 一堆字内碎点」。真符号（八度点/附点）**不可能在字内**。
    def inside(p, d):
        return (p["x0"] >= d["x0"] and p["x1"] <= d["x1"]
                and p["y0"] >= d["y0"] - 1 and p["y1"] <= d["y1"] + 1)
    # 上谱手的**八度点**本来就在数字上方，不会 in-box；
    # 下谱手的**附点**可能落在数字外接框内部（见下），所以不能一律删。
    dots = [p for p in dots if not any(inside(p, d) for d in it["dig"])]
    bc = beam_counts(cols, realbeam)
    for ci, c in enumerate(cols):
        nb = bc.get(ci, 0)
        # ⚠️ **灰 tie 音的时值由「它自己的减时线条数」决定，不要向前继承**
        #    （这一条被两组实拍同时钉死）：
        #    · p1s1b1 mel `7̸1̸2̸3̸ | 3̸ | 5̸3̸ | 3̸(gray) | —`
        #      末尾灰 `3` **无减时线** → 四分 1.0 拍；
        #      总 = 1.0 + 0.5 + 0.5 + 1.0 + 1.0(`-`) = **4.00** ✓
        #    · p1s5b1 mel `6̸ | 5̸6̸ | 6̸(gray) ‖ 7̸ | 6̸7̸ | 7̸(gray)`
        #      两个灰音都无减时线 → 各 1.0 拍；
        #      总 = (0.5+0.25+0.25+1.0) × 2 = **4.00** ✓
        #    ⚠️ 若改成「继承前一个音的时值」，前者得 3.00、后者得 2.50，全谱大面积塌。
        #      灰音只是**不重弹**（记谱写作 `~`），时值完全按自己的减时线读。
        is_gray = all(d.get("gray") for d in c["mem"])
        # 八度点 / 附点：挂到本列的音上
        #
        # ⚠️ **两种点必须分开判**：
        #    · **八度点**：`cy` 落在数字 y 区间**之外**（在正上/正下）→ 改音高
        #    · **附点**：`cy` 落在数字 y 区间**之内**（正对中线）→ 时值 ×1.5
        # ⚠️ 判附点还有两个必须同时满足的条件（否则会被灰字的**字内碎块**刷爆 ——
        #    实见 p1s1b1 的灰 `3` 内部散出 6 个 w1~2 的小点，全被误当附点 →
        #    一拍变 8.00）：
        #    ① **必须严格在数字右缘之外或紧贴右缘**（`p.x0 >= d["x1"] - 3`）。
        #       真附点排版在数字右侧（实见 bas 的 `4.`：数字 x128-140，点在 x132-135，
        #       是「紧贴右缘内」的极端情形，所以容差给到 3px）。
        #    ② **必须是「孤立的小圆点」**：面积 >= 4 且接近正方（`|w-h| <= 2`）。
        #       碎块多为 w1 h5 / w2 h2 的细长条，会被这一条挡掉。
        #    ③ **必须紧贴本数字的右缘**（`d.x1 - 3 <= p.x0 <= d.x1 + 10`）。
        #       上限别放到 +16：实见 p2s1b4 mel 的 `6 3·`，`6` 的右缘是 x1056、
        #       点却在 x1072（那是 `3` 的附点）→ 上限 +16 时 `6` 也被加上附点，
        #       该小节读成 4.12 而不是 4.00。真附点实测距右缘 4~8px。
        toks = []
        any_dot = False
        staff = c["mem"][0]["staff"]
        for d in sorted(c["mem"], key=lambda d: d["cy"]):
            t = DIGIT.get(d.get("cl", -1), "?")
            # ⚠️ **一个点只能归给它「最近的那个数字」，不能是「±12px 内都算」**
            #    （实踩）：p1s1b2 mel 的 `3`(x504-514) 与 `1`(x518-523) 相距仅 9px，
            #    `3` 的点在 x507；用 ±12 阈值时 `1` 也被判「有点」→ 读出 `1'`。
            #    致命的是这会让**同一素材的重复段落读法不一致**：
            #    bar1 第 1 拍是 `7`（真无点）、bar2 第 1 拍是 `7'`（真有点），
            #    而 bar2 的第 10 个音被多挂一个点 → 「同素材段落必须逐字相同」
            #    这条核验口径当场报警。
            #    修法：按 cx 距离排序取最近者，且横向差距必须 <= 9px
            #    （实测真点都画在数字正上方，|Δcx| 最大约 3px；9 留足余量）。
            def nearest(ps, up):
                best, bd = None, 1e9
                for p in ps:
                    if up:
                        g = d["y0"] - p["cy"]
                        if not (2 <= g <= OCT_DOT_MAXGAP):
                            continue
                    else:
                        g = p["cy"] - d["y1"]
                        if not (2 <= g <= OCT_DOT_MAXGAP):
                            continue
                    dx = abs(p["cx"] - d["cx"])
                    if dx < bd:
                        best, bd = p, dx
                return [best] if (best is not None and bd <= 9) else []
            ups = nearest(dots, True)
            dns = nearest(dots, False)
            augd = []
            for p in dots:
                if not (d["y0"] - 1 <= p["cy"] <= d["y1"] + 1):
                    continue
                w, h = p["w"], p["h"]
                if w * h < 4 or abs(w - h) > 2:
                    continue
                if p["x0"] < d["x1"] - 3 or p["x0"] > d["x1"] + 10:
                    continue
                augd.append(p)
            if augd[:1]:                 # 一个附点 = 1.5 倍（同音位最多一个）
                any_dot = True
            # ⚠️⚠️ **八度点的判定与「在哪一行谱表」完全无关**（这条是整轮里
            #      纠正得最晚、影响最大的一处 —— 249 个音曾全部漏掉高音记号）。
            #
            #   旧代码写的是「上谱手点上=常态不加、点下=`,`；下谱手点下=常态不加、
            #   点上=`'`」—— 那是把**五线谱的加线思维**错搬到了简谱上：
            #   五线谱里音符画在哪条线已含八度信息，加线只是补充；而简谱的
            #   **数字本身不带任何八度信息**，八度**只能靠上下点表达**。
            #   所以「点上 → `'`、点下 → `,`、无点 → 中音」是唯一正确的读法。
            #
            #   代价与实证：改前 mel 轨 249 个带点数字**全部读成中音**，
            #   整首曲子塌在 `a~j`（中音）一段里 —— 与交付产物
            #   「只用到 13 个键、音域仅 22 半音」完全吻合（此即马脚）。
            #   改后 mel 才能真正写出 `'`。
            if dns and not ups:
                t += ","
            elif ups and not dns:
                t += "'"
            elif ups and dns:
                # 上下都有点：简谱里表示「跨两个八度」，极罕见。
                # 本谱实测没有；保守取**上方点**（与旧 mel 分支一致）。
                t += "'"
            if is_gray:
                t = "~" + t                  # tie 音：不重弹，时值继承
            toks.append(t)
        tok = toks[0] if len(toks) == 1 else "(" + " ".join(toks) + ")"
        tok += BEAMSTR[nb]
        # ⚠️ 附点挂在**整个 token 的最后**（减时线之后）：`2/.`、`(6, 2)//.`
        if any_dot:
            tok += "."
        dur = 1.0 / 2 ** nb
        out.append((c["x0"], tok, dur))
    for B in dash:
        out.append((B["x0"], "-", 1.0))
    out.sort(key=lambda t: t[0])
    return sum(abs_bar(t[1], t[2]) for t in out), out


def barx(systems, pg, sy, b):
    s = next(t for t in systems if t["page"] == pg and t["sys"] == sy)
    return s["bars"][b - 1], s["bars"][b]


def expect_beats(box, systems, pg, sy, b):
    """本小节期望拍数：默认 4/4=4 拍；若小节内**起始处**插入了变拍号则按拍号算。

    ⚠️ 本谱有 `2/4` 小节（实见 p2s2 第 2 小节 = `1 —`，共 2 拍），
    以及恢复用的 `4/4`。拍号位置 = 小节起点 + 一小段（紧随左侧小节线）。
    判据：小节 x 范围内存在「分数线」式的 tsig 标记，且它落在小节**前 1/3**，
    则取该拍号的分子。
    """
    xa, xb = barx(systems, pg, sy, b)
    out = 4.0
    for t in time_sig_bars(box, pg, sy):
        if xa - 2 <= t <= xa + (xb - xa) * 0.34:
            # 拍号分数线的上方小数字 = 分子；用两条横线的高度差推不出，
            # 这里直接由**该小节实测总拍数**兜底：先用 4，若实测明显偏小再降
            out = 2.0
    return out


def main():
    box, systems = build()
    ts = global_tsig(box, systems)
    if len(sys.argv) > 2 and sys.argv[1] == "dump":
        pg, sy = int(sys.argv[2]), int(sys.argv[3])
        tgs = time_sig_bars(box, pg, sy)
        seq = next(i for i, s in enumerate(systems)
                   if s["page"] == pg and s["sys"] == sy)
        print("# tsig x:", [round(t, 1) for t in tgs])
        print("# tsig global:", [(i, round(x, 1), n) for (i, x, n) in ts])
        for st in ("mel", "bas"):
            for b in range(1, NCB + 1):
                xa, xb = barx(systems, pg, sy, b)
                tt, out = eval_bar(box, (pg, sy, b, st), xa, xb,
                                   tgs)
                want = want_beats(ts, seq, xa, xb)
                flag = "" if abs(tt - want) <= TOL else "  <<< want %.0f" % want
                print("p%ds%db%d %s %5.2f | %s%s"
                      % (pg, sy, b, st, tt, " ".join(t[1] for t in out), flag))
        return 0
    bad = []
    for seq, s in enumerate(systems):
        tgs = time_sig_bars(box, s["page"], s["sys"])
        for st in ("mel", "bas"):
            for b in range(1, NCB + 1):
                xa, xb = barx(systems, s["page"], s["sys"], b)
                tt, out = eval_bar(box, (s["page"], s["sys"], b, st), xa, xb,
                                   tgs)
                want = want_beats(ts, seq, xa, xb)
                if abs(tt - want) > TOL:
                    bad.append((s["page"], s["sys"], b, st, round(tt, 3),
                                want, " ".join(t[1] for t in out)))
    print("拍数有别的小节 %d / %d" % (len(bad), len(systems) * 2 * NCB))
    for i, x in enumerate(ts):
        print("   # tsig systems[%d] x=%.1f  %d/4" % (x[0], x[1], x[2]))
    for x in bad[:40]:
        print("   p%ds%db%d %s %5.2f (want %.0f) | %s" % x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
