#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""识谱审计器 —— 把识谱器的「**静默失败**」显式化（诊断层）。

## 为什么需要它

本项目累计 23 条已知缺陷，**绝大多数**的共同症状是同一个：

> 产物写错了，但日志一声不吭，`self_check` 的拍数自检还报 **全绿**。

根因是一句判据：**「往某一格里塞一颗音、或给某格加一个 `*`，都不改变那一格的时值」**
—— 而 `self_check` 的拍数校验只查「每小节拍数和」。于是：

| 曲目 | 实际错 | 自检报 |
|---|---|---|
| 雨爱 | 旋律上声部整行 12 颗静默丢失 | `✓ 每小节拍数 = 4（90 个小节·声部，0 错）` |
| 龙卷风 | 上声部整行 32 颗静默丢失 | `✓ 每小节拍数 = 4（112 个小节·声部，0 错）` |
| 悬潮 | 真三连音一个都没打标 `*` | 只在「某小节凭空多 0.50 拍」时才露头 |
| Zoo | 页眉假括号把正文 `0` 标成 `0/*` | 同上 |

也就是说：**拍数自检是一张漏网很大的网**。本模块用**独立于拍数的观测量**把这些
漏掉的错查出来，输出一份可读清单。

## 定位

* **只读**：不修改任何产物、不干预任何识别结果，随时可开 → **零回归风险**。
* **独立**：不复用 `self_check` 的拍数口径（那正是失灵的那张网），另立判据。
* **口径对齐识别器**：「系统内 / 系统外」一律按识别器自己用的 `sy ± 3S` 切，
  不用额外的宽松 pad —— 否则会把识别器没收录的那一行误判成「已在系统内」。

## 判据一览（code → 对应缺陷）

| code | 查什么 | 对应缺陷 |
|---|---|---|
| `GHOST_ROW` | 满高数字行整行印在系统上沿之外、且与谱表内某行**逐一列对齐** | 20 / 23 |
| `ORPHAN_DIGIT` | 满高正文数字夹在首末系统之间却不属于任何系统（漏字） | 8 / 20 |
| `TRIPLET_ARC` | 谱表带内、「高瘦」的 `arc`（疑似漏检的三连音括号钩） | 22 |
| `CHORD_DESC` | 和弦各音 MIDI **非严格降序**（「音高由高到低」铁律） | 7 家族 |
| `TRIPLET_STAR` | `*` 总数 ≠ 已检出三连音括号数 × 3 | 21 / 22 |
| `BEAT_GREEN_BUT` | 上面任意一条报了 WARN → 提示「拍数全绿是假绿」 | — |

## 用法

由 `识谱.py --audit [报告路径]` 调用：

    findings = audit_all(sp, pages, rows, head, sections)
    print(format_report(findings))

`sp` 是 `识谱` 模块对象本身（借用 `bar_columns` 等纯函数），由调用方用
`sys.modules[__name__]` 传入 —— 这样 `audit.py` 不 import 识谱，避免循环依赖，
也让本模块可被单独测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 音级 → 相对半音（1=C 大调：1 2 3 4 5 6 7 = 0 2 4 5 7 9 11）
DEGREE_SEMI = {"1": 0, "2": 2, "3": 4, "4": 5, "5": 7, "6": 9, "7": 11}

# 与 识谱.py 的 TRI_PAD_F 同一口径（谱表有效区上下各放宽多少 × 字高），
# 仅供 `TRIPLET_ARC` 使用 —— 三连音括号可以略高于系统上沿。
TRI_PAD_F = 1.2
# 识别器把数字收进系统的真实纵向容差（= 识谱.py 的 `sy0 - 3*S`）
SYS_CUT_S = 3.0
# 「行聚类」的纵向容差（× S），与识谱器内部一致
ROW_CLUSTER_S = 12.0
# 列对齐容差（px）
COL_ALIGN_PX = 4.0
# 幽灵行判据：带外行里至少这么多比例的数字要与谱表内某行同列
GHOST_ALIGN_F = 0.60
GHOST_MIN_DIGITS = 2

_DIGIT_RE = re.compile(r"\d[',]*")


@dataclass
class Finding:
    level: str        # "WARN" | "INFO"
    code: str
    where: str
    msg: str


# ---------------------------------------------------------------------------
# token 解析（独立于识谱器：不复用它的任何内部量）
# ---------------------------------------------------------------------------
def parse_token(tok: str) -> list[tuple[int, int]]:
    """简谱 token → `[(音级, 八度位移)]`；休止（`0`）自动跳过。

    例：`~1'//` → `[(1, +1)]`；`(3 6, 2,)` → `[(3, 0), (6, -1), (2, -1)]`；
    `0/` → `[]`。和弦与单音走同一条正则，`~` / 时值后缀（`/` `.` `-` `*`）不影响取音。
    """
    t = tok.lstrip("~")
    body = t
    if body.startswith("("):
        i = body.find(")")
        body = body[1:i] if i > 0 else body[1:]
    out: list[tuple[int, int]] = []
    for m in _DIGIT_RE.finditer(body):
        s = m.group(0)
        deg = int(s[0])
        if deg == 0:
            continue
        tail = s[1:]
        out.append((deg, tail.count("'") - tail.count(",")))
    return out


def token_midi(tok: str) -> list[int]:
    """音级 + 八度位移 → 相对 MIDI（1=C，中音区 `1` = 60 的**相对值**）。"""
    return [60 + DEGREE_SEMI[str(d)] + 12 * o for d, o in parse_token(tok)]


# ---------------------------------------------------------------------------
# 版面级判据
# ---------------------------------------------------------------------------
def _cluster_rows(digs: list, tol: float) -> list[list]:
    """把一组数字按 cy 聚成「行」（同 识谱器 `_row_bands` 的口径，独立实现）。"""
    digs = sorted(digs, key=lambda d: d["cy"])
    rows: list[list] = []
    for d in digs:
        if rows and d["cy"] - rows[-1][-1]["cy"] <= tol:
            rows[-1].append(d)
        else:
            rows.append([d])
    return rows


def _bar_of_x(cols: list, x: float):
    """x 落在哪一小节（1 起）；落在所有小节线之外返回 None（与识谱器同口径）。"""
    for k in range(len(cols) - 1):
        if cols[k] < x < cols[k + 1]:
            return k + 1
    return None


def _staff_geometry(sp: Any, pg: Any):
    """每个系统的 `(si, cols, x_lo, x_hi, a, b)`。

    ⚠️ `a / b` 是**系统上下沿原值**，不加任何 pad —— 识别器收录数字的真实纵向
    容差是 `sy ± 3S`（≈0.14 字高），消费方各自按需再 pad（三连音用 `TRI_PAD_F`）。
    这里若提前加宽，会把「识别器根本没收录的那一行」误判成「已在系统内」，
    幽灵行判据就直接失灵（《龙卷风》实测：宽 1.2 字高恰好把 ghost 行包进去）。
    """
    S = pg.S
    vb = [c for c in pg.items if c["kind"] == "vbar"]
    out = []
    for si, (a, b) in enumerate(pg.spans, 1):
        cols = sp.bar_columns(vb, a, b, S)
        if len(cols) < 2:
            continue
        out.append((si, cols, cols[0], cols[-1], a, b))
    return out


def _box_cells(pg: Any) -> set:
    """`pg.box` 里所有已收录数字的 `(cx, cy)`（用来判断一行是否**真的丢了**）。"""
    cells = set()
    for v in pg.box.values():
        for d in v.get("dig", []):
            cells.add((d["cx"], d["cy"]))
    return cells


def ghost_rows(sp: Any, pg: Any) -> list[Finding]:
    """缺陷 20 / 23：满高数字行整行印在系统上沿之外、与谱表内某行同列。

    ⚠️ 判据不能用「页眉区」或「数字行数」（《雨爱》12 个系统里只有 3 个带幽灵行、
    本谱页眉还是纯文字）。可靠判据 = **带外行与谱表内某行的数字 cx 逐一列对齐**
    （《雨爱》12/12、偏差 ≤4px；《龙卷风》21/21）→ 同列即「应属同一和弦/同一拍」。

    ⚠️ 带外窗口的**下界必须钳在上一系统下沿之后**，否则会把上一系统自己的数字
    当成「本系统的幽灵行」（《悬潮》实测 10 个系统全部误报）。

    ⚠️ **还要区分「真丢」与「已被上沿救援」**：《悬潮》p2s7 的整行确实在花括号
    之上，但被 `_rescue_top` 完整捞回（进了 `box`）—— 那不算缺陷。判据 = 该行数字
    是否出现在 `pg.box` 里：在 → 只是 INFO（已救），不在 → WARN（真丢）。
    """
    S, med_h = pg.S, pg.med_h
    cut = SYS_CUT_S * S
    cells = _box_cells(pg)
    out: list[Finding] = []
    prev_bot = None
    for si, cols, lo, hi, a, b in _staff_geometry(sp, pg):
        inside = [c for c in pg.items
                  if c["kind"] == "glyph" and c["h"] >= 0.8 * med_h
                  and lo <= c["cx"] <= hi and a - cut <= c["cy"] <= b + cut]
        if not inside:
            prev_bot = b
            continue
        rows_in = _cluster_rows(inside, ROW_CLUSTER_S * S)
        # 带外：上沿（识别器口径）之上、且不得跨入上一系统
        band_lo = a - 3.0 * med_h if prev_bot is None else prev_bot
        above = [c for c in pg.items
                 if c["kind"] == "glyph" and c["h"] >= 0.8 * med_h
                 and lo <= c["cx"] <= hi and band_lo <= c["cy"] < a - cut
                 and _bar_of_x(cols, c["cx"]) is not None]
        for r in _cluster_rows(above, ROW_CLUSTER_S * S):
            if len(r) < GHOST_MIN_DIGITS:
                continue
            xs = sorted(d["cx"] for d in r)
            best_hit = 0
            for rin in rows_in:
                xin = sorted(d["cx"] for d in rin)
                n = sum(1 for x in xs if any(abs(x - y) <= COL_ALIGN_PX for y in xin))
                best_hit = max(best_hit, n)
            if best_hit < GHOST_ALIGN_F * len(xs):
                continue
            cy = round(sum(d["cy"] for d in r) / len(r))
            n_in_box = sum(1 for d in r if (d["cx"], d["cy"]) in cells)
            if n_in_box >= 0.5 * len(r):
                out.append(Finding(
                    "INFO", "GHOST_ROW", f"第{pg.sh.page}页 系统{si}",
                    f"上沿之外有 {len(r)} 颗满高数字（cy≈{cy}）与谱表内某行同列，"
                    f"但其中 {n_in_box} 颗**已被上沿救援收进 box** ⇒ 未丢失"))
            else:
                out.append(Finding(
                    "WARN", "GHOST_ROW", f"第{pg.sh.page}页 系统{si}",
                    f"上沿之外有 {len(r)} 颗满高数字（cy≈{cy}），其中 {best_hit} 颗"
                    f"与谱表内某行逐一列对齐（差 ≤{COL_ALIGN_PX:g}px），"
                    f"且仅 {n_in_box}/{len(r)} 颗进了 box ⇒ "
                    f"疑似「整行印在花括号之上」而静默丢失（缺陷 20/23）"))
        prev_bot = b
    return out


def orphan_digits(sp: Any, pg: Any) -> list[Finding]:
    """满高正文数字落在**任何系统之外**、但仍夹在首末系统之间 → 疑似漏字。

    ⚠️ 必须**限定在首末系统的纵向范围之内**：页眉的曲名/署名是**大号文字**，
    笔画常被 OCR 认成数字（《Zoo》实测标题「疯狂动物城2主题曲」里 41 颗被读成
    `1`）。它们在谱表之上、从不进 `box`，报出来只会淹没有用的信号。

    ⚠️ 还必须是**成行且与谱表内某行同列**的：《悬潮》左边栏的段落号 `(N)` 也是
    满高数字、也夹在系统之间（实测每页 10~40 颗单颗散落），加"成行 + 列对齐"
    这条后它们自然出局。
    """
    S, med_h = pg.S, pg.med_h
    cut = SYS_CUT_S * S
    geo = _staff_geometry(sp, pg)
    if not geo:
        return []
    x_lo = min(g[2] for g in geo)
    x_hi = max(g[3] for g in geo)
    y_top = min(g[4] for g in geo) - cut
    y_bot = max(g[5] for g in geo) + cut
    inside = [c for c in pg.items
              if c["kind"] == "glyph" and c["h"] >= 0.8 * med_h
              and any(g[4] - cut <= c["cy"] <= g[5] + cut for g in geo)]
    strays = [c for c in pg.items
              if c["kind"] == "glyph" and c["h"] >= 0.8 * med_h
              and x_lo <= c["cx"] <= x_hi and y_top <= c["cy"] <= y_bot
              and not any(g[4] - cut <= c["cy"] <= g[5] + cut for g in geo)]
    out: list[Finding] = []
    for r in _cluster_rows(strays, ROW_CLUSTER_S * S):
        if len(r) < GHOST_MIN_DIGITS:
            continue
        xs = sorted(d["cx"] for d in r)
        aligned = sum(1 for x in xs
                      if any(abs(x - d["cx"]) <= COL_ALIGN_PX for d in inside))
        if aligned < GHOST_ALIGN_F * len(xs):
            continue
        cy = round(sum(d["cy"] for d in r) / len(r))
        sample = ", ".join(f"{d['label']}@x{d['cx']}" for d in r[:8])
        out.append(Finding(
            "INFO", "ORPHAN_DIGIT", f"第{pg.sh.page}页",
            f"系统外有一行 {len(r)} 颗满高数字（cy≈{cy}，{aligned} 颗与谱表内同列）："
            f"{sample}（需人工确认是否真漏字）"))
    return out


def triplet_arc_suspects(sp: Any, pg: Any) -> list[Finding]:
    """缺陷 22：三连音括号的 `3` 与括号钩合并成 `arc` ⇒ 整组静默漏检。

    `_find_triplets()` 的候选池只有 `kind=="glyph"` 的小号数字与 `kind=="hline"`
    的细横线；`3`/臂一旦与钩粘连成 `arc`，两条通道同时落空、**日志一声不吭**。

    ⚠️ **区分「括号钩」与「连音弧」靠长宽比**：括号钩是 `⌒` 的半边、**高瘦**
    （《悬潮》实测 w15 h30 → h/w = 2.0）；连音弧（slur）**矮胖**
    （《Zoo》实测 w17 h17、w19 h17 → h/w ≈ 1.0）。取 1.3 为界。
    若只看尺寸不看比例，Zoo 的 29 条连音弧会全部报成假告警。
    """
    S, med_h = pg.S, pg.med_h
    pad = TRI_PAD_F * med_h
    out: list[Finding] = []
    sus = []
    for si, cols, lo, hi, a, b in _staff_geometry(sp, pg):
        for c in pg.items:
            if c["kind"] != "arc":
                continue
            if not (lo <= c["cx"] <= hi and a - pad <= c["cy"] <= b + pad):
                continue
            if 0.30 * med_h <= c["w"] <= 1.10 * med_h \
                    and 0.80 * med_h <= c["h"] <= 2.60 * med_h \
                    and c["h"] >= 1.30 * c["w"]:
                sus.append((si, c))
    if sus:
        seen = ", ".join(f"s{si}:x{c['cx']}/y{c['cy']}"
                         f"(w{c['w']}h{c['h']})" for si, c in sus[:10])
        out.append(Finding(
            "WARN", "TRIPLET_ARC", f"第{pg.sh.page}页",
            f"谱表带内有 {len(sus)} 个「高瘦」弧（h ≥ 1.3w）：{seen}"
            f"⇒ 疑似三连音括号钩漏检（缺陷 22），请裁图核对"))
    return out


# ---------------------------------------------------------------------------
# 谱面级判据（吃 rows）
# ---------------------------------------------------------------------------
def chord_descending(rows: dict) -> list[Finding]:
    """缺陷 7 家族：和弦各音必须**音高由高到低**（本谱系版面铁律，已用逐列量测确立）。

    ⚠️ 竖排和弦的八度点被「就近法」判给**下方**数字时，就会产出
    `(3 6 2',)` 这种先升后降的串。全量扫一遍即可一眼查出。
    """
    bad = []
    for (pi, si, st), bars in rows.items():
        for bar, toks in sorted(bars.items()):
            for _x, tok, _dur in toks:
                t = tok.lstrip("~")
                if not t.startswith("("):
                    continue
                midi = token_midi(t)
                if len(midi) >= 2 and any(midi[i] <= midi[i + 1]
                                          for i in range(len(midi) - 1)):
                    bad.append((pi + 1, si, bar, st, tok, midi))
    out: list[Finding] = []
    for pi, si, bar, st, tok, midi in bad:
        out.append(Finding(
            "WARN", "CHORD_DESC", f"第{pi}页 系统{si} 第{bar}小节 {st}",
            f"和弦 `{tok}` 各音 MIDI {midi} 并非严格降序"
            f"⇒ 疑似竖排八度点归属错（缺陷 7 家族）"))
    return out


def triplet_star(rows: dict, pages: list) -> list[Finding]:
    """不变量：`*` 总数 == **已检出**三连音括号数 × 3（仅在「每个括号辖 3 个单音」时成立）。

    ⚠️ 和弦列只打一个 `*`（`eval_bar` 对整个和弦 token 加后缀），所以**含和弦的
    三连音组**会让这个式子偏小。它因此只是个**提示**，不是硬性判据。
    另：括号整个没被检出时两边同为 0，本式不报警 —— 那种情形交给 `TRIPLET_ARC`。
    """
    stars = 0
    for bars in rows.values():
        for toks in bars.values():
            for _x, tok, _dur in toks:
                stars += tok.count("*")
    brackets = sum(len(getattr(pg, "triplets", []) or []) for pg in pages)
    if stars == 3 * brackets:
        return [Finding("INFO", "TRIPLET_STAR", "全曲",
                        f"`*` 总数 {stars} = 已检出三连音括号 {brackets} × 3 ✓"
                        f"（括号认对即打满标）")]
    return [Finding("INFO", "TRIPLET_STAR", "全曲",
                    f"`*` 总数 {stars} vs 已检出括号 {brackets} × 3 = {3 * brackets}"
                    f"（差 {stars - 3 * brackets}）—— 若括号辖的是和弦（一列只打一个"
                    f"`*`）属正常；否则提示打标不全（缺陷 21/22）")]


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def audit_all(sp: Any, pages: list, rows: dict, head: str = "",
              sections: dict | None = None) -> list[Finding]:
    """跑全部判据，返回发现清单（WARN 在前）。"""
    found: list[Finding] = []
    for pg in pages:
        found += ghost_rows(sp, pg)
        found += orphan_digits(sp, pg)
        found += triplet_arc_suspects(sp, pg)
    found += chord_descending(rows)
    found += triplet_star(rows, pages)

    n_warn = sum(1 for f in found if f.level == "WARN")
    if n_warn:
        found.append(Finding(
            "WARN", "BEAT_GREEN_BUT", "全曲",
            f"本条清单有 {n_warn} 条 WARN —— 其中多数是**拍数自检查不出**的错"
            f"（塞音/丢 `*` 不改时值）。若自检显示「每小节拍数 0 错」，那是**假绿**"))
    found.sort(key=lambda f: (f.level != "WARN", f.code, f.where))
    return found


def format_report(findings: list[Finding], head: str = "", n_pages: int = 0) -> str:
    lines = ["=" * 68,
             "识谱审计报告（诊断层 · 只读）",
             "=" * 68]
    if head or n_pages:
        lines.append(f"  首行 {head}  共 {n_pages} 页")
    warns = [f for f in findings if f.level == "WARN"]
    infos = [f for f in findings if f.level == "INFO"]
    lines.append(f"  WARN {len(warns)} 条 / INFO {len(infos)} 条")
    lines.append("-" * 68)
    for f in warns:
        lines.append(f"[WARN] {f.code:<14} {f.where}")
        lines.append(f"        {f.msg}")
    for f in infos:
        lines.append(f"[INFO] {f.code:<14} {f.where}")
        lines.append(f"        {f.msg}")
    if not warns:
        lines.append("  没有 WARN —— 但请注意：拍数全绿也不能证明没错（本层只覆盖")
        lines.append("  已归纳出的 6 类判据；未知形态仍需人工裁图核对）。")
    lines.append("=" * 68)
    return "\n".join(lines) + "\n"
