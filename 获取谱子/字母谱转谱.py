# -*- coding: utf-8 -*-
"""字母谱转谱 —— 把「键盘字母谱」（评论区扒谱格式）转成 scores/ 可直接弹奏的曲谱。

字母谱编码规律（2026-09-28 与《起风了》图像转写互证确认，详见 获取谱子/键盘字母谱规律.md）：

    字母 = 物理按键，不是音名：
        Z X C V B N M = 低音区 1,~7,    （MIDI 48~59）
        A S D F G H J = 中音区 1~7      （MIDI 60~71）
        Q W E R T Y U = 高音区 1'~7'    （MIDI 72~83）
    ( ) 内字母 = 同时按（和弦）；括号外字母 = 按出现顺序先后弹。
    字母谱本身不带时值，节奏靠本文约定的分隔符表达：

    每行 = 一小节，`/` 分隔拍；拍内字母/括号按出现顺序平分该拍时值；
    空格只是视觉分组；空字段 = 休止一拍；行尾多余的 `/` 忽略。
    （个别小节拍数不是 4 —— 第一段第 1 行确实 5 拍、(XGJ) 行确实 2 拍，
      已与谱主逐条确认，本脚本按每行实际字段数处理，不强制 4 拍。）

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

# 一个事件 = 一个和弦括号，或一个单字母
TOKEN = re.compile(r"\(([A-Z]*)\)|([A-Z])")

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
            if "/" not in line:
                # 新段落标签：先把上一段（带它的段落名）收进结果
                if cur_bars:
                    sections.append((cur_name, cur_bars))
                    cur_bars = []
                cur_name = line.rstrip("：:")
                continue
            fields = line.split("/")
            if line.endswith("/"):
                fields.pop()          # 行尾 `/` 只是小节收口
            bar = []
            for fld in fields:
                evs = []
                for m in TOKEN.finditer(fld):
                    letters = m.group(1) if m.group(1) is not None else m.group(2)
                    evs.append(letters)
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
    """字母谱 → [(start_ms, keys_or_None, measure_end_ms)] 时隙表。"""
    sections = parse_letter_score(path)
    beat_ms = 60000.0 / bpm
    slots = []          # (start, keys or None, measure_end)
    t = LEAD_IN_BEATS * beat_ms
    n_bars = n_beats = n_rest = 0
    for name, bars in sections:
        for bar in bars:
            n_bars += 1
            bar_start = t
            for evs in bar:
                n_beats += 1
                if not evs:
                    slots.append([t, None, None])
                    n_rest += 1
                    t += beat_ms
                    continue
                step = beat_ms / len(evs)
                for letters in evs:
                    slots.append([t, chord_keys(letters), None])
                    t += step
            bar_end = t
            for s in slots:
                if s[2] is None:
                    s[2] = bar_end   # 记录所属小节的末尾
    return slots, dict(beat_ms=beat_ms, bars=n_bars, beats=n_beats,
                       rests=n_rest, sections=sections)


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
    for (t, keys, _) in slots:
        r = int(round(t))
        body.append((r - prev_r, keys))
        prev_r = r

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
            interval, keys = body[slot_i]
            if keys:
                hold = f" {final_hold}" if slot_i == len(slots) - 1 else ""
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
    print(f"  小节 {meta['bars']} / 拍 {meta['beats']}（含休止拍 {meta['rests']}）")
    print(f"  事件 {st['notes']}（发声 {st['sounding']}）/ 最多同按 {st['max_chord']}")
    print(f"  整曲时长 {st['total_ms'] / 1000:.1f}s @ {args.bpm:g} BPM")


if __name__ == "__main__":
    main()
