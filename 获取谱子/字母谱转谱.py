# -*- coding: utf-8 -*-
"""字母谱转谱 —— 把「键盘字母谱」（评论区扒谱格式）转成 scores/ 可直接弹奏的曲谱。

字母谱编码规律（2026-09-28 与《起风了》图像转写互证确认，详见 获取谱子/键盘字母谱规律.md）：

    字母 = 物理按键，不是音名：
        Z X C V B N M = 低音区 1,~7,    （MIDI 48~59）
        A S D F G H J = 中音区 1~7      （MIDI 60~71）
        Q W E R T Y U = 高音区 1'~7'    （MIDI 72~83）
    ( ) 内字母 = 同时按（和弦）；括号外字母 = 按出现顺序先后弹。
    特殊音符（对应印刷简谱的两类记号）：
        Q.  (VAT).   附点音符「·」—— 时值 ×1.5（点后缀，与简谱惯例一致）
        ~Q  ~(AD)    延音线「⌒」—— 接音不重弹，时值并入前一个同音事件，
                     并给前一个音写按住第三列（时值 −10ms）
    音符不带特殊记号时按普通处理；拍内按权重分拍（普通 1 / 附点 1.5），
    全普通音的拍与「平分」完全一致 —— 老谱面零影响。
    字母谱本身不带时值，节奏靠本文约定的分隔符表达：

    每行 = 一小节，`/` 分隔拍；拍内字母/括号按出现顺序平分该拍时值；
    空格只是视觉分组；空字段 = 休止一拍；行尾多余的 `/` 忽略。
    不含 `/` 的纯和弦行（如结尾 `(CBAGQ)`）= 整小节和弦：第 1 拍起音、按住整小节。
    （个别小节拍数不是 4 —— 按每行实际字段数处理，不强制 4 拍。）

用法：
    python 字母谱转谱.py <字母谱.txt> <输出.txt> [--bpm 110]

产物格式 = parser.py 直读的「间隔毫秒 按键 [按住毫秒]」。
和弦成员按琴键从低到高排（低音组→高音组，非字母序），同仓库交付口径。
时间轴在浮点域累加、按整数毫秒取边界差，累计零漂移；
结尾和弦的按住时长 = 它到所在小节末尾的剩余时值（末个发声行不被钳制）。
"""
import argparse
import re
import sys
from pathlib import Path

KEYS = "zxcvbnmasdfghjqwertyu"
PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
         72, 74, 76, 77, 79, 81, 83]
K2P = dict(zip(KEYS.upper(), PITCH))

# 一个事件 = 「可选延音线 ~」+ 和弦括号或单字母或 0 或 - + 「可选附点 .」
#   Q.   = 附点音符（时值 ×1.5）；(VAT). 和弦附点同理（括号内 (VAT.) 也认）
#   ~Q   = 延音线接音：不重弹，时值并入前一个同音事件（并给前音写按住第三列）
#   -    = 延时线（简谱减时线同形）：前一个发声事件延长本槽时值（同拍内按权重分）
#   0    = 显式休止（0. = 附点休止）——空字段只能整拍休止，拍内休止用 0
EVENT = re.compile(r"~?\([^()]*\)\.?|~?[A-Z]\.?|0\.?|-")

# 时值权重：普通 1，附点 1.5。拍内按权重分拍 —— 全普通音时与「平分」一致。
WEIGHT_PLAIN, WEIGHT_DOT = 1.0, 1.5

LEAD_IN_BEATS = 1.0   # 起手空一拍，给玩家反应时间


def parse_letter_score(path):
    """读字母谱。返回 [(段落名或 None, [小节...]) ...]；小节 = [拍...]，拍 = [事件...]。

    事件 = 按键字母串（如 'ZBDT'）。空拍 = []。
    判定音乐行的标准：含 `/`。段落标签（第一段：/副歌：等）与空行跳过。
    """
    sections, cur_name, cur_bars = [], None, []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            has_slash = "/" in line
            has_letter = re.search(r"[A-Z]", line) is not None
            if not has_slash and not has_letter:
                # 段落标签（第一段：/副歌：等）：先把上一段（带段落名）收进结果
                if cur_bars:
                    sections.append((cur_name, cur_bars))
                    cur_bars = []
                cur_name = line.rstrip("：:")
                continue
            if has_slash:
                fields = line.split("/")
                if line.endswith("/"):
                    fields.pop()      # 行尾 `/` 只是小节收口
            else:
                # 无 `/` 的纯字母/和弦行 = 整小节和弦收尾：
                # 第 1 拍起音，后 3 拍延音（结尾长音，按住到小节末尾）
                fields = [line, "", "", ""]
            bar = []
            for fld in fields:
                evs = []
                for m in EVENT.finditer(fld):
                    tok = m.group(0)
                    tie = tok.startswith("~")
                    dot = tok.endswith(".")
                    body = tok[1:] if tie else tok
                    body = body[:-1] if dot else body
                    letters = body[1:-1] if body.startswith("(") else body
                    letters = letters.replace(" ", "")   # 和弦内允许空格 (C H W)
                    if letters.endswith("."):   # 和弦附点点在括号内 (XS.) 也认
                        dot = True
                        letters = letters[:-1]
                    evs.append((letters, dot, tie))
                bar.append(evs)       # 空字段 → 空拍（休止）
            cur_bars.append(bar)
    if cur_bars:
        sections.append((cur_name, cur_bars))
    return sections


def chord_keys(letters):
    """和弦字母串 → 排好序的小写键串（低音组→高音组 = 按 MIDI 升序）。"""
    mids = [K2P[ch] for ch in letters]
    if len(set(mids)) != len(mids):
        raise ValueError(f"和弦内有重复的键: {letters}")
    order = sorted(zip(mids, letters))
    return "".join(k.lower() for _, k in order)


def convert(path, bpm):
    """字母谱 → 时隙表 [起始ms, 键串或None, 小节末ms, 本音时值ms, 延音并入ms]。"""
    sections = parse_letter_score(path)
    beat_ms = 60000.0 / bpm
    slots = []
    t = LEAD_IN_BEATS * beat_ms
    n_bars = n_beats = n_rest = n_dots = n_ties = n_ext = 0
    for name, bars in sections:
        for bar in bars:
            n_bars += 1
            for evs in bar:
                n_beats += 1
                if not evs:
                    slots.append([t, None, None, beat_ms, 0.0])
                    n_rest += 1
                    t += beat_ms
                    continue
                # 按权重分拍：普通 1 / 附点 1.5。全普通音时 = 旧的「平分」。
                total_w = sum(WEIGHT_DOT if dot else WEIGHT_PLAIN
                              for _, dot, _ in evs)
                base = beat_ms / total_w
                for letters, dot, tie in evs:
                    dur = base * (WEIGHT_DOT if dot else WEIGHT_PLAIN)
                    if dot:
                        n_dots += 1
                    if letters == "-":
                        # 延时线：并入前一个发声事件（同延音的按住机制）
                        j = next((k for k in range(len(slots) - 1, -1, -1)
                                  if slots[k][1]), None)
                        if j is None:
                            raise ValueError("延时线 - 前面没有任何音")
                        slots[j][4] += dur
                        n_ext += 1
                    elif tie:
                        j = next((k for k in range(len(slots) - 1, -1, -1)
                                  if slots[k][1]), None)
                        if j is None:
                            raise ValueError(f"延音线 ~{letters} 前面没有任何音")
                        prev = {PITCH[KEYS.index(k)] for k in slots[j][1]}
                        miss = [ch for ch in letters.upper()
                                if K2P[ch] not in prev]
                        if miss:
                            raise ValueError(
                                f"延音线 ~{letters} 与前一个音 {slots[j][1]} "
                                f"不接（缺 {''.join(miss)}）")
                        slots[j][4] += dur      # 并入前一个音：多按住这么久
                        n_ties += 1
                    elif letters == "0":
                        slots.append([t, None, None, dur, 0.0])
                    else:
                        slots.append([t, chord_keys(letters), None, dur, 0.0])
                    t += dur
            bar_end = t
            for s in slots:
                if s[2] is None:
                    s[2] = bar_end   # 记录所属小节的末尾
    return slots, dict(beat_ms=beat_ms, bars=n_bars, beats=n_beats,
                       rests=n_rest, dots=n_dots, ties=n_ties, exts=n_ext,
                       sections=sections)


def build_text(slots, meta, bpm, title, src_name):
    """时隙表 → 曲谱文本。浮点累加、整数取边界差 → 累计零漂移。"""
    # 掐掉结尾的休止时隙；最后一个发声行按住到所属小节末尾
    while slots and slots[-1][1] is None:
        slots.pop()
    last = slots[-1]
    final_hold = int(round(last[2] - last[0]))

    out = ["#1倍速", "#" + "=" * 62]
    out.append(f"#  {title} —— 键盘字母谱直转（{bpm} BPM）")
    out.append(f"#  一拍 = {meta['beat_ms']:.1f} 毫秒；每行 = 一个字母谱事件；空行 = 休止")
    out.append(f"#  字母 = 物理按键（低 zxcvbnm / 中 asdfghj / 高 qwertyu），( ) 同按")
    out.append(f"#  由 获取谱子/字母谱转谱.py 从 {src_name} 生成，改谱请改字母谱原文")
    out.append("#" + "=" * 62)

    prev_r, body = 0, []
    for (t, keys, _, dur, extra) in slots:
        r = int(round(t))
        body.append((r - prev_r, keys, dur, extra))
        prev_r = r

    # 每个发声槽之后最近的一个发声槽（用于按取整时间轴预钳按住时长）
    starts = [int(round(s[0])) for s in slots]
    nxt_snd = [None] * len(slots)
    seen = None
    for k in range(len(slots) - 1, -1, -1):
        nxt_snd[k] = seen
        if slots[k][1]:
            seen = k

    # 每小节 = (段落名, 时隙数)。注意：拍内多事件时 **时隙数 > 拍数**，
    # 必须按 len(evs) 数时隙，不能用拍数当下标步长（那会从小节 1 就错位）。
    bar_info = []   # (段落名, n_slots)
    for name, bars in meta["sections"]:
        for bar in bars:
            # 休止拍没有任何事件，但也占一个时隙 → max(1, ...)
            bar_info.append((name, sum(max(1, len(evs)) for evs in bar)))

    text, slot_i, last_label = [], 0, object()
    for bar_no, (name, n_slots) in enumerate(bar_info, start=1):
        if slot_i >= len(slots):
            break   # 整小节都是结尾休止，已掐掉
        if name != last_label:
            if name:
                text.append(f"#――― {name} ―――")
            last_label = name
        text.append(f"#第 {bar_no} 小节")
        take = min(n_slots, len(slots) - slot_i)   # 末小节被掐掉部分休止
        for _ in range(take):
            interval, keys, dur, extra = body[slot_i]
            if keys:
                # 延音/延时线并入时值的前音：写按住第三列（时值 − HOLD_GAP 10ms），
                # 并按取整时间轴预钳到「下一个发声行 − 10」—— 与 parser 的钳制
                # 完全一致，避免 verify_original 报「按住值被解析器改动」。
                is_last = slot_i == len(slots) - 1
                hold_ms = int(round(dur + extra)) - 10
                if is_last:
                    hold_ms = max(final_hold, hold_ms)
                else:
                    j = nxt_snd[slot_i]
                    if j is not None:
                        hold_ms = min(hold_ms, starts[j] - starts[slot_i] - 10)
                hold = f" {hold_ms}" if (extra > 0 or is_last) else ""
                text.append(f"{interval} {keys}{hold}")
            else:
                text.append(f"{interval}")
            slot_i += 1
    assert slot_i == len(slots), f"还有 {len(slots) - slot_i} 个时隙没写进谱子"
    return out + text


def self_check(score_path):
    """回读产物：键域、同按上限、时长、事件数。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import parser as P
    notes = P.parse(score_path)
    bad = [n for n in notes if any(k not in KEYS for k in n.keys)]
    assert not bad, f"越界键: {bad[:3]}"
    wide = [n for n in notes if len(n.keys) > 5]
    assert not wide, f"同按超过 5 键: {wide[:3]}"
    total = notes[-1].time + notes[-1].hold
    sounding = sum(1 for n in notes if n.keys)
    return dict(notes=len(notes), sounding=sounding, total_ms=total,
                max_chord=max(len(n.keys) for n in notes))


def main():
    ap = argparse.ArgumentParser(description="键盘字母谱 → 可弹奏曲谱")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--bpm", type=float, default=110.0)
    ap.add_argument("--title", default="回家的路")
    args = ap.parse_args()

    src = Path(args.src)
    slots, meta = convert(src, args.bpm)
    text = build_text(slots, meta, int(args.bpm), args.title, src.name)

    dst = Path(args.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(text) + "\n")

    st = self_check(dst)
    print(f"已生成 {dst}")
    print(f"  小节 {meta['bars']} / 拍 {meta['beats']}（含休止拍 {meta['rests']}）"
          f" / 附点 {meta['dots']} / 延音 {meta['ties']} / 延时线 {meta['exts']}")
    print(f"  事件 {st['notes']}（发声 {st['sounding']}）/ 最多同按 {st['max_chord']}")
    print(f"  整曲时长 {st['total_ms'] / 1000:.1f}s @ {args.bpm:g} BPM")


if __name__ == "__main__":
    main()
