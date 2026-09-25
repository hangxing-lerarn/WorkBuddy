# -*- coding: utf-8 -*-
"""
midi_to_score.py —— 把 MIDI 文件转换成原神「风物之诗琴」机器谱 txt

只依赖 Python 标准库，不需要 pip 安装任何东西。

用法（批量模式，最常用）:
    python midi_to_score.py
    # 自动读取 change_base/no 下所有 .mid/.midi -> 依次转成 scores/<同名>.txt
    # 转换完成后把源 .mid 移动到 change_base/yes

用法（单文件模式）:
    python midi_to_score.py 你的歌.mid
    python midi_to_score.py 你的歌.mid --melody-track 1  # 手动指定主旋律轨
    python midi_to_score.py 你的歌.mid --max-voices 2    # 最多同时弹 2 个音
    python midi_to_score.py 你的歌.mid --mode highest    # 回退到旧的单音线行为
    python midi_to_score.py 你的歌.mid --step exact      # 不量化，节奏最还原
    python midi_to_score.py 你的歌.mid -o ../scores/我的歌.txt

核心约束（原神琴）：21 键 = 三组八度的自然音阶，没有升降号。
所以本工具会先把音高「吸附」到最合适的调性上，落不到琴键上的音再做处置。

最影响听感的参数（都在下面有详细说明）:
    --mode voicing        默认。每个时刻编一个小和弦（旋律 + 低音 + 填充），
                          不再像旧版那样把复音压成单音线
    --melody-track N      声部编织靠它判断「谁是主旋律」，判错了用这个覆盖
    --step exact          不套十六分网格，按原始 MIDI 的真实 onset 间隔逐行写
    --speed               默认 1.0（与原曲等长）；auto = 按时长比对反推
    --max-octave-shift    超出琴域的音最多挪几个八度，默认 1，更远的不弹
"""

import argparse
import os
import shutil
import sys

# 音区：低音区 ZXCVBNM -> 中音区 ASDFGHJ -> 高音区 QWERTYU
ORDER = "zxcvbnm" + "asdfghj" + "qwertyu"
DEGREES = (0, 2, 4, 5, 7, 9, 11)          # 自然音阶的半音位置
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# 轨名关键词 -> 角色。用于 --mode voicing 自动挑主旋律轨。
# 轨名是最可靠的信号（花之舞写着 Melody/HigherAcc，但"取最高音"会把旋律让给伴奏轨）。
MELODY_KW = ("melody", "mel", "vocal", "vo", "lead", "solo",
             "主旋律", "主音", "弦律", "zhu")
BASS_KW = ("bass", "低音", "contra")
ACCOMP_KW = ("accomp", "acc", "chord", "harmony", "string", "pad", "ban", "伴")
# 鼓轨不能只靠通道 9 判断 —— 实测有的 MIDI 把鼓写在普通通道上，
# 只是轨名写着 drum，音高全是 100+，会污染"最高音"和声部候选。
DRUM_KW = ("drum", "perc", "click", "鼓", "打击", "节奏")

# 声部编织的 onset 分组宽度（毫秒）= 播放器按键按住时长。
# 比这更近的两个音在游戏里本来就分不开，强行排成两行只会被拉平。
VOICE_BUCKET = 50

# 目录约定：全部相对本文件定位，换电脑/换路径都不用改
PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.join(PROJ_DIR, "change_base")
NO_DIR = os.path.join(BASE_DIR, "no")          # 待转换的 .mid 放这里
YES_DIR = os.path.join(BASE_DIR, "yes")        # 转换成功的 .mid 移到这里
SCORES_DIR = os.path.join(PROJ_DIR, "scores")  # 生成的机器谱 txt


# --------------------------------------------------------------------------
# 1. 纯标准库 MIDI 解析
# --------------------------------------------------------------------------

def read_varlen(data, i):
    """读取 MIDI 变长数值，返回 (值, 新下标)"""
    val = 0
    while i < len(data):
        b = data[i]
        i += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, i
    return val, i


def parse_midi(path):
    """解析 MIDI，返回 (division, tracks)，tracks 为 [(轨名, [(tick, kind, payload)])]"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise ValueError("不是合法的 MIDI 文件（缺少 MThd）")

    fmt = int.from_bytes(data[8:10], "big")
    ntrks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")

    tracks = []
    i = 14
    while i + 8 <= len(data):
        chunk_id = data[i:i + 4]
        length = int.from_bytes(data[i + 4:i + 8], "big")
        body_start = i + 8
        body_end = body_start + length
        if chunk_id != b"MTrk":
            i = body_end
            continue

        events = []
        tick = 0
        status = None
        run_status = None                 # 最近一个「通道消息」状态字节，供 running status 复用
        p = body_start
        while p < body_end:
            delta, p = read_varlen(data, p)
            tick += delta
            if p >= body_end:
                break
            b = data[p]
            if b & 0x80:                      # 新状态字节
                status = b
                p += 1
                if b < 0xF0:
                    run_status = b
            else:
                # running status：复用最近的通道状态字节。
                # 元事件/SysEx 之后也允许复用 —— SMF 规范明文禁止，但实测
                # mido 与不少真实文件都这么做，硬按规范会静默截断整条轨。
                status = run_status
            if status is None:
                break
            hi = status & 0xF0

            if status == 0xFF:                # 元事件
                mtype = data[p]
                p += 1
                ln, p = read_varlen(data, p)
                payload = data[p:p + ln]
                p += ln
                events.append((tick, "meta", (mtype, payload)))
            elif status in (0xF0, 0xF7):      # SysEx
                ln, p = read_varlen(data, p)
                p += ln
            elif hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                events.append((tick, "midi", (status, data[p], data[p + 1])))
                p += 2
            elif hi in (0xC0, 0xD0):
                events.append((tick, "midi", (status, data[p], 0)))
                p += 1
            elif status in (0xF1, 0xF3):      # 系统公共消息：各带 1 个数据字节
                p += 1
            elif status == 0xF2:              # 歌曲位置指针：2 个数据字节
                p += 2
            elif status == 0xF6:              # 调音请求：无数据字节
                pass
            else:
                break
        tracks.append(events)
        i = body_end

    return fmt, ntrks, division, tracks


def track_name(events):
    for tick, kind, payload in events:
        if kind == "meta" and payload[0] == 0x03:
            return payload[1].decode("utf-8", "replace").strip()
    return ""


def tempo_events(tracks):
    out = []
    for events in tracks:
        for tick, kind, payload in events:
            if kind == "meta" and payload[0] == 0x51 and len(payload[1]) == 3:
                us = int.from_bytes(payload[1], "big")
                if us > 0:
                    out.append((tick, us))
    return sorted(out)


def make_tick_converter(division, tempos):
    """返回 tick -> 毫秒 的函数。支持多个变速点。"""
    if division == 0:
        raise ValueError("division（每四分音符的 tick 数）为 0，文件非法")
    if division & 0x8000:                     # SMPTE 时间码
        fps = 256 - (division >> 8)
        tpf = division & 0xFF
        ms_per_tick = 1000.0 / (fps * tpf)
        return lambda t: t * ms_per_tick

    tm = []
    for tick, us in tempos:
        if not tm or tm[-1][0] != tick:
            tm.append((tick, us))
    if not tm or tm[0][0] != 0:
        tm.insert(0, (0, 500000))

    cum = [0.0]                              # cum[i] = 到 tm[i] 为止累计秒
    for idx in range(1, len(tm)):
        span = tm[idx][0] - tm[idx - 1][0]
        cum.append(cum[-1] + span * tm[idx - 1][1] / division / 1e6)

    def conv(tick):
        for idx in range(len(tm) - 1, -1, -1):
            if tick >= tm[idx][0]:
                return (cum[idx] + (tick - tm[idx][0]) * tm[idx][1] / division / 1e6) * 1000.0
        return 0.0

    return conv


def extract_notes(events):
    """从轨道事件中提取音符，返回 [(start_tick, dur_tick, pitch, channel)]"""
    active, notes = {}, []
    for tick, kind, payload in events:
        if kind != "midi":
            continue
        status, d1, d2 = payload
        hi, ch = status & 0xF0, status & 0x0F
        if hi == 0x90 and d2 > 0:
            active[(ch, d1)] = tick
        elif hi == 0x80 or (hi == 0x90 and d2 == 0):
            k = (ch, d1)
            if k in active:
                st = active.pop(k)
                notes.append((st, tick - st, d1, ch))
    for (ch, pitch), st in active.items():   # 没有配对的 note off
        notes.append((st, 0, pitch, ch))
    return sorted(notes)


# --------------------------------------------------------------------------
# 2. 音高映射
# --------------------------------------------------------------------------

def allowed_pitches(tonic_pc, base):
    """21 键对应的 MIDI 音高：低音区 -> 高音区"""
    return [base + DEGREES[i % 7] + 12 * (i // 7) for i in range(21)]


# 21 键真实覆盖 base .. base + POOL_SPAN（三组八度自然音阶），由 allowed_pitches 实测推导。
# 注意：这里曾经手写成 base + 23（少算一整个八度），会让选出的基准整体抬高 12~24 个半音，
# 后果是约四分之一的音被塞进错误的八度（旋律忽高忽低）。别再手写这个常数。
POOL_SPAN = allowed_pitches(0, 0)[-1]


def snap(pitch, pool):
    """把音高吸附到最接近的合法音高"""
    return min(pool, key=lambda a: (abs(a - pitch), a))


def choose_tonic_and_base(pitches):
    """
    两阶段选调：
      1) 选音级（12 个调）使吸附误差最小 —— 决定「调性」是否正确
      2) 选八度基准（base = 音级 + 12k）使「落不到琴键上」的音最少 —— 决定「音域」够不够用

    第 2 步的窗口宽度必须用 POOL_SPAN，用错宽度会把基准整体抬高一个八度。
    窗口同分时再比总吸附位移，避免随便取一个。
    """
    pitches = list(pitches)
    best_pc, best_err = 0, None
    for pc in range(12):
        pool = allowed_pitches(pc, pc + 48)          # 八度无关，只看音级
        err = sum(abs(p - snap(p, pool)) for p in pitches)
        if best_err is None or err < best_err:
            best_pc, best_err = pc, err

    best_base, best_key = None, None
    for octave in range(-2, 11):
        base = best_pc + 12 * octave
        out = sum(1 for p in pitches if p < base or p > base + POOL_SPAN)
        pool = allowed_pitches(best_pc, base)
        key = (out, sum(abs(p - snap(p, pool)) for p in pitches))
        if best_key is None or key < best_key:
            best_base, best_key = base, key
    if best_base < 0:                                # MIDI 音高不从负数起，兜一下
        best_base = best_pc
    return best_pc, best_base, best_err


def map_pitch(pitch, pool, max_octave_shift):
    """
    把一个音高放进 21 键池子，返回 (池内音高, 挪了几个八度, 是否保留)。

    落在琴域外的音按 max_octave_shift 处置：
      0          -> 一律不弹（音区绝对干净，但丢音最多）
      1（默认）  -> 只挪 1 个八度，更远的直接不弹
      N          -> 最多挪 N 个八度；给个大数就等于「一个音都不丢」

    注意：不能直接把域外音吸附到琴域边界（那是错的），那会把音级也改掉。
    """
    lo, hi = pool[0], pool[-1]
    shifted = 0
    p = pitch
    while p < lo:
        p += 12
        shifted += 1
    while p > hi:
        p -= 12
        shifted += 1
    if shifted > max_octave_shift:
        return pitch, shifted, False
    return snap(p, pool), shifted, True


def track_roles(tracks, all_notes):
    """给每条轨打角色标签：旋律 / 低音 / 伴奏 / 其他 / 空轨"""
    roles = {}
    for i, ev in enumerate(tracks):
        ns = all_notes[i]
        nm = track_name(ev).lower()
        if not ns:
            roles[i] = "空轨"
        elif any(k in nm for k in DRUM_KW):
            roles[i] = "鼓"
        elif any(k in nm for k in MELODY_KW):
            roles[i] = "旋律"
        elif any(k in nm for k in BASS_KW):
            roles[i] = "低音"
        elif any(k in nm for k in ACCOMP_KW):
            roles[i] = "伴奏"
        else:
            mean_p = sum(p for _, _, p, _ in ns) / len(ns)
            roles[i] = "低音" if mean_p < 45 else "其他"
    return roles


def pick_melody_track(roles, all_notes, want):
    """
    挑主旋律轨，返回 (轨号, 判定依据)；挑不出来返回 (None, 原因)。

    优先级：手动指定 > 轨名标注 > 统计兜底。
    统计兜底必须先踢掉「稀疏装饰轨」（音数不到最密轨 20% 的，如钟琴、刮奏），
    否则会出现「只有 53 个音的 Glockenspiel 因为音最高而被当成主旋律」这种事，
    也会让整首曲子的音区基准被带偏。
    """
    if want is not None:
        if 0 <= want < len(all_notes) and all_notes[want]:
            return want, "手动 --melody-track"
        return None, f"--melody-track {want} 超出范围或是空轨"

    hit = [i for i, r in roles.items() if r == "旋律"]
    if hit:
        return hit[0], "轨名标注"

    live = [i for i, r in roles.items() if r in ("其他", "伴奏") and all_notes[i]]
    if not live:
        live = [i for i in all_notes if all_notes[i]]
    if not live:
        return None, "没有可用轨"
    densest = max(len(all_notes[i]) for i in live)
    live = [i for i in live if len(all_notes[i]) >= 0.2 * densest]
    if not live:
        return None, "没有可用轨"
    means = {i: sum(p for _, _, p, _ in all_notes[i]) / len(all_notes[i]) for i in live}
    best = max(means, key=means.get)
    return best, f"音高均值最高（{means[best]:.0f}）"


def resolve_voicing(args, notes3):
    """
    把 --max-voices / --min-interval 的 auto 解析成具体数字，并把依据带回日志。

    自适应口径（都跟「这首曲子本身有多密」挂钩）：
      max-voices   <- 原曲平均同时发声数 × 0.6，钳到 2~5。
                      含义是「挑骨架」：原曲再满也不该一键按满，只留最能说明和声的那几个。
      min-interval <- 原曲 onset 内相邻音程的中位数 × 0.6，钳到 3~6。
                      下限锁 3，是因为 1~2 半音同时响在 21 键琴上必然糊成一片。
    """
    by_onset = {}
    for t, p, _ in notes3:
        by_onset.setdefault(round(t / VOICE_BUCKET), set()).add(p)
    poly = [len(v) for v in by_onset.values()]
    avg_poly = (sum(poly) / len(poly)) if poly else 1.0

    ivs = []
    for v in by_onset.values():
        s = sorted(v)
        for a, b in zip(s, s[1:]):
            ivs.append(b - a)
    ivs.sort()
    med_iv = ivs[len(ivs) // 2] if ivs else 4

    if str(args.max_voices).strip().lower() == "auto":
        k = max(2, min(5, int(round(avg_poly * 0.6))))
        k_src = f"auto，原曲平均 {avg_poly:.1f} 音/时刻"
    else:
        k = max(1, min(5, int(args.max_voices)))
        k_src = "手动"
    if str(args.min_interval).strip().lower() == "auto":
        g = max(3, min(6, int(round(med_iv * 0.6))))
        g_src = f"auto，原曲音程中位 {med_iv} 半音"
    else:
        g = max(1, int(args.min_interval))
        g_src = "手动"
    return k, k_src, g, g_src, avg_poly, med_iv


def build_voicing(notes3, mel_idx, max_voices, min_interval, bass_gap, merge_ms,
                  pool=None, max_shift=1):
    """
    声部编织：把「每个时刻只留最高音」换成「每个时刻编一个小和弦」。

    notes3 = [(毫秒, 音高, 轨号)]，按 merge_ms 分组成「同时响的音」，每组取：
      1. 旋律声部 = 旋律轨在本组内的最高音（该组没有旋律轨的音时退回全组最高音）
      2. 低音声部 = 本组最低音，且必须与旋律拉开 bass_gap 半音以上才值得占一根手指
      3. 填充声部 = 从高到低补，任何两音至少差 min_interval 半音（避开相邻半音的音簇）

    传了 pool 就一边选一边用琴域筛：弹不出来的候选直接跳过，而且「低音与旋律的
    间隔」「填充与已有声部的间隔」都按落到琴上之后的实际音高算 —— 否则会出现
    「低音选中了却一映射就被丢」或者「两个音映射到相邻键」的假复音。

    返回 ([(毫秒, 音高)], 组数, 旋律数, 低音数, 填充数, 整组跳过的时刻数)。
    音高返回的是**原始音高**，由调用方统一走 map_pitch 落到琴键上。
    """
    def fit(p):
        if pool is None:
            return p
        s, _sh, keep = map_pitch(p, pool, max_shift)
        return s if keep else None

    groups = []
    for t, p, i in notes3:
        if groups and t - groups[-1][-1][0] <= merge_ms:
            groups[-1].append((t, p, i))
        else:
            groups.append([(t, p, i)])

    out = []
    n_mel = n_bass = n_fill = n_skip = 0
    for g in groups:
        t0 = g[0][0]
        # 旋律：从旋律轨的音里由高到低试，取第一个弹得出来的
        mel = [p for _, p, i in g if i == mel_idx] or [p for _, p, _ in g]
        sel = []
        for p in sorted(set(mel), reverse=True):
            s = fit(p)
            if s is not None:
                sel.append((p, s))
                n_mel += 1
                break
        if not sel:
            n_skip += 1                    # 连主旋律都落不到琴上，这一时刻只能放弃
            continue
        top = sel[0][1]
        # 低音：从最低音往上找第一个「弹得出来且与旋律拉开足够远」的
        for p in sorted({p for _, p, _ in g}):
            if len(sel) >= max_voices:
                break
            s = fit(p)
            if s is not None and top - s >= bass_gap:
                sel.append((p, s))
                n_bass += 1
                break
        # 填充：从高到低补，按琴上音高保证两两间隔
        for p in sorted({p for _, p, _ in g}, reverse=True):
            if len(sel) >= max_voices:
                break
            s = fit(p)
            if s is None or any(s == x[1] for x in sel):
                continue
            if all(abs(s - x[1]) >= min_interval for x in sel):
                sel.append((p, s))
                n_fill += 1
        for src, _s in sel:
            out.append((t0, src))
    return out, len(groups), n_mel, n_bass, n_fill, n_skip


def assemble_exact(mapped, args):
    """
    不量化模式：按真实 onset 间隔逐行写。

    mapped = [(毫秒, 按键字符)]。相邻间隔小于 args.merge_ms 的音并成和弦
    ——播放器按键只按住 50ms，更近的音本来就分不开。
    返回 ([(间隔毫秒, 按键串)], 因和弦上限丢掉的音数)
    """
    groups = []
    for t, c in mapped:
        if groups and t - groups[-1][-1][0] <= args.merge_ms:
            groups[-1].append((t, c))
        else:
            groups.append([(t, c)])

    items, dropped = [], 0
    prev_t = None
    for g in groups:
        keys = sorted({c for _, c in g}, key=ORDER.index)
        if len(keys) > args.max_chord:
            dropped += len(keys) - args.max_chord
            keys = keys[-args.max_chord:]
        t0 = g[0][0]
        # 第一行的间隔保留前奏留白，之后用真实差值（合并阈值保证差值 > merge_ms）
        delta = int(round(t0)) if prev_t is None else max(1, int(round(t0 - prev_t)))
        prev_t = t0
        items.append((delta, "".join(keys)))
    return items, dropped


# --------------------------------------------------------------------------
# 3. 主流程
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        description="把 MIDI 转成原神「风物之诗琴」机器谱 txt（纯标准库）")
    ap.add_argument("midi", nargs="?",
                    help="输入 MIDI 文件路径；省略则进入批量模式，"
                         "读取 change_base/no 下的全部 MIDI")
    ap.add_argument("-o", "--out", help="输出 txt 路径（默认 scores/<midi名>.txt，批量模式忽略）")
    ap.add_argument("--mode", choices=("voicing", "highest", "track", "merge"),
                    default="voicing",
                    help="voicing=声部编织，每个时刻编一个小和弦(默认)；"
                         "highest=每个时刻只保留最高音(旧行为，会把复音压成单音线)；"
                         "track=只取指定轨；merge=合并所有非打击轨")
    ap.add_argument("--track", type=int, default=0, help="--mode track 时的轨号(0开始)")
    ap.add_argument("--melody-track", type=int, default=None,
                    help="--mode voicing 时手动指定主旋律轨号(0开始)；"
                         "省略=自动判断（先看轨名关键词，再按统计兜底）")
    ap.add_argument("--max-voices", default="auto",
                    help="--mode voicing 时每个时刻最多同时弹几个音；"
                         "auto(默认，按原曲密度取 2~5) 或 1~5 的数字")
    ap.add_argument("--min-interval", default="auto",
                    help="--mode voicing 时和弦内任意两音的最小半音间隔；"
                         "auto(默认，按原曲和声密度取 3~6) 或数字。"
                         "设成 1~2 会允许相邻半音同时响（音簇，很刺耳）")
    ap.add_argument("--bass-gap", type=int, default=12,
                    help="--mode voicing 时低音声部与旋律至少要拉开多少半音才保留，"
                         "默认 12（一个八度）；给个大数等于不要低音声部")
    ap.add_argument("--step", default="auto",
                    help="网格步长毫秒(整数) / auto(=十六分音符，默认) / "
                         "exact(=不量化，按真实 onset 间隔逐行写，节奏最还原)")
    ap.add_argument("--merge-ms", type=int, default=50,
                    help="间隔小于该值算「同时响」：--step exact 按它并成和弦，"
                         "--mode voicing 按它分组挑声部。默认 50"
                         "（= 播放器按键按住时长，更近的音本来就分不开）")
    ap.add_argument("--speed", default=None,
                    help="写入首行的倍速：省略=1.0（与原曲等长）；auto=按谱子时长与原曲"
                         "时长之比反推；也可直接给数字。小于 1 会变慢")
    ap.add_argument("--max-octave-shift", type=int, default=1,
                    help="超出琴域的音最多挪几个八度，默认 1（更远的不弹）；"
                         "0=绝不挪八度、超域直接不弹；给个大数=全都挪回来")
    ap.add_argument("--tonic", default="auto",
                    help="调性: auto(默认) 或 C/D/E/F/G/A/B 等")
    ap.add_argument("--max-chord", type=int, default=6, help="和弦上限，默认 6")
    ap.add_argument("--section-cells", type=int, default=256,
                    help="每多少格插一个分节注释，exact 模式按等效时长换算，0=不插，默认 256")
    ap.add_argument("--section-seconds", type=float, default=None,
                    help="每多少秒插一个分节注释；给了就覆盖 --section-cells")
    ap.add_argument("--no-pad", action="store_true",
                    help="不补齐到 8 格的倍数（仅网格模式）")
    ap.add_argument("--overwrite", action="store_true",
                    help="输出 txt 已存在时直接覆盖（默认先备份成 .bak）")
    return ap


def convert(midi_path, out_path, args):
    """把单个 MIDI 转成机器谱写到 out_path，返回统计 dict；失败返回 None"""
    try:
        fmt, ntrks, division, tracks = parse_midi(midi_path)
        conv = make_tick_converter(division, tempo_events(tracks))
    except (ValueError, OSError, IndexError) as e:
        print(f"解析 MIDI 失败：{e}")
        print("  请确认这是未被截断的标准 MIDI 文件（.mid/.midi）")
        return None
    print(f"MIDI: format={fmt} 轨数={ntrks} division={division}")

    all_notes = []
    for idx, events in enumerate(tracks):
        nm = track_name(events)
        notes = [n for n in extract_notes(events) if n[3] != 9]   # 丢掉鼓轨
        print(f"  轨{idx} {nm!r}: {len(notes)} 个音符")
        all_notes.append(notes)

    melody_idx = None
    notes3 = []
    vp = None
    if args.mode == "track":
        picked = all_notes[args.track] if args.track < len(all_notes) else []
        chosen = [(conv(s), p) for s, d, p, c in picked]
        print(f"使用 轨{args.track}，{len(chosen)} 个音符")
    elif args.mode == "merge":
        chosen = []
        for notes in all_notes:
            chosen += [(conv(s), p) for s, d, p, c in notes]
        print(f"合并全部非打击轨，{len(chosen)} 个音符")
    elif args.mode == "voicing":
        roles = track_roles(tracks, all_notes)
        live = "  ".join(f"轨{i}={r}" for i, r in sorted(roles.items()) if r != "空轨")
        print(f"  轨角色：{live}")
        melody_idx, how = pick_melody_track(roles, all_notes, args.melody_track)
        if melody_idx is None:
            print(f"  !! 挑不出主旋律轨（{how}），本次退回「全轨取最高音」")
        else:
            print(f"  主旋律轨：轨{melody_idx}（{how}）")
        notes3 = sorted((conv(s), p, i)
                        for i, notes in enumerate(all_notes)
                        for s, d, p, c in notes
                        if roles.get(i) != "鼓")
        if not notes3:
            print("没有可用音符")
            return None
        vp = resolve_voicing(args, notes3)
        print(f"  声部编织参数：最多 {vp[0]} 音/时刻（{vp[1]}），"
              f"音程下限 {vp[2]} 半音（{vp[3]}）")
    else:  # highest
        bucket = {}
        for notes in all_notes:
            for s, d, p, c in notes:
                bucket.setdefault(round(conv(s), 1), []).append(p)
        chosen = [(t, max(ps)) for t, ps in bucket.items()]
        print(f"提取最高音旋律，{len(chosen)} 个音符")

    # 选调基准：声部编织时只看「主旋律轨的音」，不能把全部声部一起喂进来。
    # 低音声部大量落在琴域外，一起喂会把窗口整体拉低，旋律反而被挤出琴域
    # （花之舞就是这么把旋律轨 52~70 段全丢掉的）。
    if args.mode == "voicing":
        if melody_idx is not None:
            key_pitches = [p for i, notes in enumerate(all_notes) if i == melody_idx
                           for s, d, p, c in notes]
        else:
            key_pitches = [p for _, p, _ in notes3]
        if not key_pitches:
            key_pitches = [p for _, p, _ in notes3]
    else:
        if not chosen:
            print("没有可用音符，请换 --mode 或 --track")
            return None
        chosen.sort()
        key_pitches = [p for _, p in chosen]

    # --- 网格：auto / 指定毫秒 / exact（不量化） ---
    exact = args.step.strip().lower() == "exact"
    tempos = tempo_events(tracks)
    init_us = tempos[0][1] if tempos else 500000
    est_step = max(20, int(round(init_us / 4000.0)))       # 十六分音符；分节换算也用
    bpm = 60_000_000 / init_us
    if exact:
        step = None
        print(f"速度 {bpm:.1f} BPM；--step exact：不套网格，按真实 onset 间隔逐行写")
    elif args.step == "auto":
        step = est_step
        print(f"速度 {bpm:.1f} BPM -> 自动步长 {step}ms（十六分音符）")
    else:
        step = int(args.step)

    # --- 调性与八度基准（用 key_pitches：声部编织时只看主旋律轨）---
    if args.tonic != "auto":
        pc = NOTE_NAMES.index(args.tonic.upper().replace("B#", "C"))
        _, base, err = choose_tonic_and_base(key_pitches)
        base = max(0, pc + 12 * round((base - pc) / 12))
        tonic_pc, snap_err = pc, err
    else:
        tonic_pc, base, snap_err = choose_tonic_and_base(key_pitches)

    pool = allowed_pitches(tonic_pc, base)
    print(f"调性 {NOTE_NAMES[tonic_pc]}（最接近的调），最低键 z = {base} "
          f"({NOTE_NAMES[base % 12]}{base // 12 - 1})，"
          f"琴域 {pool[0]}~{pool[-1]} 共 {POOL_SPAN + 1} 个半音")

    # 声部编织：等琴域定下来之后再挑音。
    # 低音必须挑「弹得出来」的，否则选中了也会被 --max-octave-shift 丢掉，白忙一场。
    if args.mode == "voicing":
        chosen, n_grp, n_mel, n_bass, n_fill, n_skip = build_voicing(
            notes3, melody_idx, vp[0], vp[2], args.bass_gap,
            args.merge_ms, pool, args.max_octave_shift)
        if not chosen:
            print("声部编织后没有可弹的音，请调大 --max-octave-shift 或改用 --mode highest")
            return None
        chosen.sort()
        extra = f"，另有 {n_skip} 个时刻所有音都弹不出来已跳过" if n_skip else ""
        print(f"  声部编织：{n_grp} 个时刻 -> {len(chosen)} 个音"
              f"（旋律 {n_mel} + 低音 {n_bass} + 填充 {n_fill}），"
              f"平均 {len(chosen) / max(n_grp, 1):.2f} 音/时刻{extra}")

    onsets = [t for t, _ in chosen]
    pitches = [p for _, p in chosen]

    # --- 落键：吸附 + 琴域外处置 ---
    mapped = []                       # [(毫秒, 按键字符)]
    out_range = 0
    n_altered = folds = 0
    for t, p in chosen:
        s, shifted, keep = map_pitch(p, pool, args.max_octave_shift)
        if not keep:
            out_range += 1
            continue
        if shifted:
            folds += 1
        if s != p:
            n_altered += 1
        mapped.append((t, ORDER[pool.index(s)]))

    print(f"音域 {min(pitches)}..{max(pitches)}（跨 {max(pitches) - min(pitches)} 半音）"
          f" -> 吸附改动 {n_altered}/{len(pitches)} 个音，挪八度 {folds} 个")
    if out_range:
        print(f"  !! 超出琴域、按 --max-octave-shift {args.max_octave_shift} 不弹 "
              f"{out_range} 个音（占 {100 * out_range / len(pitches):.0f}%）"
              f"；要少丢音就调大该参数，要绝对不挪八度就设 0")
    if not mapped:
        print("所有音都落在琴域外，请手动指定 --tonic 重试")
        return None

    # --- 组装成 (间隔毫秒, 按键串) ---
    chord_dropped = 0
    if exact:
        items, chord_dropped = assemble_exact(mapped, args)
        note_lines = len(items)
        body_ms = sum(d for d, _ in items)
        q_err = None
        print(f"不套网格：{note_lines} 个音符行，最后一个音落在 {body_ms / 1000:.1f}s")
    else:
        cells = {}
        for t, c in mapped:
            ci = int(round(t / step))
            prev = cells.get(ci)
            if prev is None:
                cells[ci] = [c]
            elif c not in prev:
                prev.append(c)
        # 和弦按低音区->高音区排序（项目的硬性约定），超出上限保留最高音
        for ci, keys in cells.items():
            keys.sort(key=ORDER.index)
            if len(keys) > args.max_chord:
                chord_dropped += len(keys) - args.max_chord
                cells[ci] = keys[-args.max_chord:]
        max_cell = max(cells) if cells else 0
        q_err = sum(abs(t - round(t / step) * step) for t in onsets) / len(onsets)
        print(f"量化到 {step}ms 网格：平均误差 {q_err:.1f}ms = 格子的 "
              f"{100 * q_err / step:.0f}%"
              f"（原曲触键没落在网格上时误差就会大，想彻底不偏用 --step exact）")
        note_lines = max_cell + 1
        if not args.no_pad:
            pad = (-note_lines) % 8
            if pad:
                print(f"为对齐 8 格小节，末尾补 {pad} 格休止")
            note_lines += pad
        items = [(step, "".join(cells.get(ci, []))) for ci in range(note_lines)]
        body_ms = note_lines * step

    if chord_dropped:
        print(f"  !! 因和弦上限 {args.max_chord} 丢弃 {chord_dropped} 个音")

    # --- 倍速：默认 1.0（与原曲等长）/ auto / 手写数字 ---
    span_ms = onsets[-1]                       # 原曲从第一个音到最后一个音
    if args.speed is None:
        speed = 1.0
    elif str(args.speed).strip().lower() == "auto":
        speed = (body_ms / span_ms) if span_ms > 0 else 1.0
        print(f"--speed auto：谱子 {body_ms / 1000:.1f}s ÷ 原曲 {span_ms / 1000:.1f}s"
              f" -> 倍速 {speed:.3f}")
    else:
        speed = float(args.speed)
    if speed <= 0:
        print(f"倍速必须大于 0（收到 {speed}），改用 1.0")
        speed = 1.0

    # --- 分节注释：按时间插，网格与 exact 两种模式通用 ---
    if args.section_seconds is None:
        mark_gap = args.section_cells * est_step           # 毫秒
    else:
        mark_gap = int(args.section_seconds * 1000)
    lines = [f"#{speed:g}倍速"]
    if mark_gap > 0:
        lines.append("#开头：")
    elapsed = 0
    seg = 1
    next_mark = mark_gap
    for delta, keys in items:
        elapsed += delta
        if mark_gap > 0 and elapsed >= next_mark:
            seg += 1
            lines.append(f"#第{seg}段：")
            next_mark += mark_gap
        lines.append(f"{delta} {keys}" if keys else str(delta))

    # --- 写出 ---
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    backup = None
    if os.path.exists(out_path) and not args.overwrite:
        backup = unique_path(out_path + ".bak")
        shutil.copy2(out_path, backup)
        print(f"同名谱子已存在，原件已备份为 {os.path.basename(backup)}")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n已写出 {out_path}")
    sec_count = sum(1 for l in lines if l.startswith("#")) - 1
    print(f"  {len(lines)} 行（首行倍速 + {sec_count} 个分节注释 + {note_lines} "
          f"{'个音符行' if exact else '个格子'}），{os.path.getsize(out_path)} 字节")
    print(f"  谱子 {body_ms / 1000:.1f}s ÷ {speed:g} 倍速 = 实际演奏 "
          f"{body_ms / speed / 1000:.1f}s"
          f"（原曲 {span_ms / 1000:.1f}s，"
          f"差 {100 * (body_ms / speed / max(span_ms, 1) - 1):+.0f}%）")

    # --- 自检 ---
    print("\n规范自检:")
    note_rows = [l for l in lines if not l.startswith("#")]
    bad = [l for l in note_rows
           if not (l.split(" ", 1)[0].isdigit()
                   and (len(l.split()) == 1
                        or all(c in ORDER for c in l.split()[1])))]
    print(f"  行语法违规        : {len(bad)}  {bad[:3]}")
    oc = 0
    for l in note_rows:
        p = l.split(" ", 1)
        if len(p) == 2:
            ks = list(p[1])
            if ks != sorted(ks, key=ORDER.index):
                oc += 1
    print(f"  和弦排序违规      : {oc}")
    if exact:
        ivs = sorted({int(l.split()[0]) for l in note_rows})
        print(f"  间隔取值          : {len(ivs)} 种，{ivs[0]}~{ivs[-1]}ms"
              f"（不均匀是正常的，播放器逐行累加）")
    else:
        print(f"  段长 %8           : {note_lines % 8}  ({note_lines} 格)")
        rests = sum(1 for l in note_rows if " " not in l)
        runs = []
        run = 0
        for l in note_rows:
            if " " not in l:
                run += 1
            else:
                if run:
                    runs.append(run)
                run = 0
        if run:
            runs.append(run)
        if runs:
            single = sum(1 for r in runs if r == 1)
            print(f"  休止段 {len(runs)} 个，其中单格 {single} "
                  f"({100 * single / len(runs):.0f}%)")
    return {"notes": len(mapped), "cells": note_lines, "out": out_path,
            "backup": backup, "altered": n_altered, "folds": folds,
            "dropped": chord_dropped + out_range, "out_range": out_range,
            "speed": speed, "step": step}


# --------------------------------------------------------------------------
# 4. 批量模式：change_base/no -> scores/<同名>.txt，源 .mid 移到 change_base/yes
# --------------------------------------------------------------------------

def unique_path(path):
    """若 path 已被占用，返回加 _1/_2 … 后的新路径"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{stem}_{i}{ext}"):
        i += 1
    return f"{stem}_{i}{ext}"


def batch(args):
    for d in (NO_DIR, YES_DIR, SCORES_DIR):
        os.makedirs(d, exist_ok=True)

    files = sorted(f for f in os.listdir(NO_DIR)
                   if f.lower().endswith((".mid", ".midi"))
                   and os.path.isfile(os.path.join(NO_DIR, f)))

    print(f"批量模式：{NO_DIR}")
    if not files:
        print("no 文件夹里没有 .mid / .midi 文件。放进去之后重新运行即可。")
        return 0

    print(f"发现 {len(files)} 个 MIDI，开始依次转换\n")
    ok, failed = [], []
    for idx, name in enumerate(files, 1):
        src = os.path.join(NO_DIR, name)
        stem = os.path.splitext(name)[0]
        out_path = os.path.join(SCORES_DIR, stem + ".txt")
        print(f"=== [{idx}/{len(files)}] {name} ===")
        try:
            stat = convert(src, out_path, args)
        except Exception as e:                    # 单个文件出错不中断整批
            print(f"  !! 转换异常：{type(e).__name__}: {e}")
            stat = None
        if not stat:
            failed.append(name)
            print("  -> 失败，文件保留在 no 文件夹，继续下一个\n")
            continue
        dest = unique_path(os.path.join(YES_DIR, name))
        shutil.move(src, dest)
        ok.append(name)
        extra = f"，丢弃 {stat['dropped']}" if stat["dropped"] else ""
        print(f"  -> 谱子：{os.path.relpath(out_path, PROJ_DIR)}"
              f"（{stat['notes']} 音 / {stat['cells']} "
              f"{'行' if stat['step'] is None else '格'}"
              f" / 倍速 {stat['speed']:g}{extra}）")
        print(f"  -> 源文件已移入：{os.path.relpath(dest, PROJ_DIR)}\n")

    print("=" * 56)
    print(f"完成：成功 {len(ok)} 个，失败 {len(failed)} 个")
    if failed:
        print("失败清单：" + "、".join(failed))
    return 0 if not failed else 1


def main():
    args = build_parser().parse_args()

    if args.midi:                                  # 单文件模式
        if not os.path.isfile(args.midi):
            print(f"找不到文件：{args.midi}")
            return 1
        out_path = args.out or os.path.join(
            SCORES_DIR, os.path.splitext(os.path.basename(args.midi))[0] + ".txt")
        return 0 if convert(args.midi, out_path, args) else 1

    if args.out:
        print("提示：批量模式下 -o 被忽略，输出固定为 scores/<MIDI同名>.txt\n")
    return batch(args)                             # 批量模式


if __name__ == "__main__":
    sys.exit(main())
