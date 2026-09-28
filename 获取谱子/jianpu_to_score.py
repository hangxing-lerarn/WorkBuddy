#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简谱 → 机器谱（scores/*.txt）

把人类简谱（阿拉伯数字谱）直接转成 `main.py` / `parser.py` 能读取并演奏的曲谱。
纯标准库，零依赖。

为什么另写一个而不用 `txt_maker.py`
------------------------------------
`txt_maker.py` 只认**已经手工转成 A~G 字母**的文本，而且间隔写死 90ms ——
等于没有节奏、没有八度、没有调号、没有休止时值。它是个「字母搬运工」，
不是简谱解析器。本工具直接吃简谱。

输入格式
--------
UTF-8 文本。以 `#` 开头的行是注释（`#` 后面紧跟数字时不算，那是升号）。

**首行（可选）写调号 / 拍号 / 速度**：

    1=C 4/4 100        ← 主音 / 每小节拍数 / 每分钟拍数（BPM）

省略时按 `1=C 4/4 90`。`1=G` `1=D` `1=F` 等非 C 调**无需手工移调** ——
工具会自动把整首曲子挪到能全用白键弹的调上（见下「调号与升降号」）。

**音符 token**（空格分隔，`|` 是小节线，只用来校验拍数、不计入时间）：

    1 2 3 4 5 6 7      音级（= do re mi fa sol la si）
    0                  休止（`·` 也接受）
    5'      /  5,      高八度 / 低八度（可叠：`5''` 高两个八度）
    5/      /  5//     减时线：八分音符 / 十六分音符（每多一个 `/` 再减半）
    5.      /  5/.     附点：时值 ×1.5（可与减时线叠加）
    -                  增时线：把**前一个音**延长一拍（可连写 `- -`）
    #4      /  b7      临时升号 / 降号
    (135)   / (1 3 5)  和弦（同时按下；时值写法跟在括号后面，如 `(135)/`）
    ~                  连音线（tie）：把**同音**并进当前音（时值相加），如 `1 ~ 1`
                       —— 两端音不同会报错；想表达「连奏」用 --hold next

    例：  1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -        ← 《小星星》前两句

段落标记：以 `@` 开头的行，会作为注释**原样**写进产物（如 `@前奏：`，
中文标点不会被折成半角）。以 `#` 开头的是注释，直接丢弃。

不支持的写法
------------
· **三连音等非二进制时值**。减时线 `／` 只能二等分，所以时值永远是
  十六分 / 三十二分 / 六十四分的整数倍；`1/ 1/ 1/` 是**三个八分音符**，
  不是三连音。真遇到三连音，工具会明确报错而不是糊过去。
· 一行里同时写多个小节而不加 `|`（拍数校验会因此失灵）。
· 带升降号的**调号**（`1=#F`）—— 换成它的等音调写，或整体移调后再写。

调号与升降号
------------
琴只有 **21 个白键**（C3~B5），弹不出任何黑键。所以：

1. 整首曲子按调号算出绝对音高后，**自动选一个移调量**，让尽量多的音落在白键上
   （`1=G` 会整体下移纯五度变成 C 调，`1=D` 下移大二度，`1=F` 下移纯四度 —— 都是全白键）；
2. 仍落在黑键上的音（临时升降号、或本来就写错的）**吸附到最近的白键**，
   并在自检里报出「走音」处数 —— 这是琴的物理限制，不是 bug；
3. 超出琴域（C3~B5）的音先尝试整体/逐个折八度，实在放不下的**丢弃**并计数
   （`--max-fold` 控制最多挪几个八度）。

输出
----
默认写 `scores/<输入文件名>.txt`，与项目既有曲谱同构：**一行 = 一个最小格**
（按需要取十六分 / 三十二分 / 六十四分音符），每行 `间隔毫秒 按键 [按住毫秒]`，
首行 `#1.0倍速`。按住时长 = 本音自己的时值 − 10ms，所以休止格是**真静默**。

⚠️ 间隔语义别写反：`parser.py` 是**先累加间隔、再把这个音符记在累加后的时刻**，
所以 note i 的时刻 = interval₁+…+interval_i，也就是
**第 i 行的间隔 = 从第 i−1 行到第 i 行的时间**（第 1 行的间隔是起手延迟）；
「从这一行到下一行的时间」写在**下一**行上。本工具每行都写同一个「格」值，
并把末尾补满整小节，所以每一行（含最后一行）都有值 —— 最后一行缺值的话，
parser 会直接把那个音漏掉。

用法
----
    python 获取谱子/jianpu_to_score.py 我的简谱.txt
    python 获取谱子/jianpu_to_score.py 我的简谱.txt --bpm 120 --out scores/我的曲子.txt
    python 获取谱子/jianpu_to_score.py 我的简谱.txt --dry-run     # 只自检不落盘
    python 获取谱子/jianpu_to_score.py 我的简谱.txt --hold next   # 连奏（键按到下一个音）

可参考 `简谱示例/欢乐颂.txt`（真实旋律）与 `简谱示例/语法示例.txt`（每种记号一条）。
"""

import argparse
import importlib.util
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "scores"

# ---------------------------------------------------------------- 琴的物理事实
ORDER = "zxcvbnm" + "asdfghj" + "qwertyu"      # 21 个键，低音组 → 中音组 → 高音组
PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
         72, 74, 76, 77, 79, 81, 83]           # C3 … B5
KEY_OF = dict(zip(PITCH, ORDER))
WHITE = {0, 2, 4, 5, 7, 9, 11}                 # 白键的音级
LOW, HIGH = PITCH[0], PITCH[-1]                # 48 … 83
SPAN = HIGH - LOW                              # 35（36 个半音位，只有白键可弹）

MAJOR = (0, 2, 4, 5, 7, 9, 11)                 # 大调音阶：级数 1~7 的半音偏移
KEY_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# ---------------------------------------------------------------- 时值
GRID_CANDIDATES = (0.25, 0.125, 0.0625)        # 十六分 / 三十二分 / 六十四分（以拍为单位）
GAP = 10                                       # 与 parser.HOLD_GAP_MS 一致
HOLD_MIN = 50                                  # 与 parser.DEFAULT_HOLD_MS 一致
EPS = 1e-9

HEAD_RE = re.compile(r"^1\s*=\s*([A-Ga-g])([#b]?)\s*(?:(\d+)\s*/\s*(\d+))?\s*(\d+)?")
TOKEN_RE = re.compile(r"^([#b]?)([0-7])([',]*)((?:[-/.])*)$")
DEG_RE = re.compile(r"([#b]?)([0-7])([',]*)")


def fullwidth_to_half(s):
    """把全角数字 / 符号折成半角 —— 中文输入法下打出来的简谱常常是全角。"""
    out = []
    for ch in s:
        o = ord(ch)
        if o == 0x3000:
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


class JianpuError(Exception):
    pass


def parse_meta(line):
    """解析 `1=C 4/4 100` → (key, beats_per_bar, bpm)。返回 None 表示这行不是调号行。"""
    m = HEAD_RE.match(line.strip())
    if not m:
        return None
    key = m.group(1).upper()
    if m.group(2):
        raise JianpuError(f"暂不支持带升降号的调号：1={key}{m.group(2)}")
    beats = int(m.group(3)) if m.group(3) else 4
    unit = int(m.group(4)) if m.group(4) else 4
    bpm = int(m.group(5)) if m.group(5) else 90
    return key, beats * 4 / unit, bpm        # beats_per_bar 以「四分音符 = 1 拍」计


def parse_degree_tok(tok, lineno):
    m = TOKEN_RE.match(tok)
    if not m:
        raise JianpuError(f"第 {lineno} 行无法识别的记谱 token：{tok!r}")
    acc, deg, octs, durs = m.groups()
    beats = 1.0
    for c in durs:
        if c == "-":
            beats += 1.0
        elif c == "/":
            beats /= 2
        elif c == ".":
            beats *= 1.5
    return int(deg), acc, octs.count("'") - octs.count(","), beats


def split_chord(inner, lineno):
    """`135` / `1 3 5` / `1'3'5'` → [(deg, acc, oct), ...]"""
    parts = inner.split() if " " in inner.strip() else None
    if parts is None:
        parts = [d.group(0) for d in DEG_RE.finditer(inner)]
        if "".join(parts) != inner:
            raise JianpuError(f"第 {lineno} 行和弦写法无法解析：({inner})")
    out = []
    for p in parts:
        m = DEG_RE.fullmatch(p)
        if not m:
            raise JianpuError(f"第 {lineno} 行和弦里的 {p!r} 不像音级")
        if int(m.group(2)) == 0:
            raise JianpuError(f"第 {lineno} 行和弦里出现了休止（0 / ·）—— "
                              f"休止没有「同时按下」可言，请拆成普通音符")
        out.append((int(m.group(2)), m.group(1), m.group(3).count("'") - m.group(3).count(",")))
    return out


def tokenize(line, lineno):
    """
    按空白切 token，但**括号内的空白不算分隔** —— 和弦 `(1 3 5)` 里可以有空格。
    返回 token 列表；括号不配对就直接报错（比让它漏到后面报「无法识别的记谱」清楚）。
    """
    toks, buf, depth = [], [], 0
    for ch in line:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            if depth == 0:
                raise JianpuError(f"第 {lineno} 行出现多余的右括号")
            depth -= 1
            buf.append(ch)
        elif ch.isspace() and depth == 0:
            if buf:
                toks.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if depth:
        raise JianpuError(f"第 {lineno} 行有没闭合的左括号")
    if buf:
        toks.append("".join(buf))
    return toks


def parse_jianpu(text):
    """
    简谱文本 → (meta, events, markers)

      events  每个元素 {'beats', 'degs'（休止为 []）, 'bar'}
      markers [(事件下标, 段落名)]
    """
    meta = {"key": "C", "beats_per_bar": 4.0, "bpm": 90}
    events, markers, bar = [], [], 0
    tie_spans = []                    # [(原小节, 新小节, 接过去的拍数)]，见下
    got_meta = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        raw = unicodedata.normalize("NFC", raw).strip()
        if not raw:
            continue
        # ⚠️ 段落标记 / 注释是**自由文本**，先按原样收下再谈记谱。
        # 全角音标必须折成半角（中文输入法下 `１ １ ５ ５`、`（１３５）` 很常见），
        # 但这个折叠会把中文标点一起改掉 —— `@A 段：` 会变成 `@A 段:`。
        # 所以只对「记谱行」做折叠。
        if raw[:1] in ("@", "＠"):
            markers.append((len(events), raw[1:].strip()))
            continue
        if raw[:1] in ("#", "＃") and not (len(raw) > 1 and raw[1].isdigit()):
            continue                                    # 注释（`#4` 这类升号不算）
        if not got_meta:
            got_meta = True
            m = parse_meta(fullwidth_to_half(raw))
            if m:
                meta["key"], meta["beats_per_bar"], meta["bpm"] = m
                continue                                # 调号行本身不产生音符

        # `·` 只是「0（休止）」的另一种写法，折成 0 —— 免得它一路漏到和弦里，
        # 在 MAJOR[-1] 上算出个莫名其妙的音高（split_chord 会另有一道拦截）。
        line = fullwidth_to_half(raw).replace("~", " ~ ").replace("·", "0").replace("•", "0").strip()

        for tok in tokenize(line, lineno):
            if tok in ("|", "||", "‖"):
                bar += 1
                continue
            if tok == "~":
                if not events:
                    raise JianpuError(f"第 {lineno} 行的连音线前面没有音")
                events[-1]["tie"] = True
                continue
            if tok == "-":                              # 增时线：延长前一个音
                if not events:
                    raise JianpuError(f"第 {lineno} 行的增时线前面没有音")
                # ⚠️ 连音线跨小节后，增时线会跟在**上一小节**的那个事件屁股后面
                # （`… 1'// | ~1' - - - |`）。直接 `+= 1.0` 会把整整 3 拍记到
                # 旧小节头上 —— 校验于是报「第 82 小节 7 拍、第 83 小节 1 拍」。
                # 增时线长在哪个小节，那 1 拍就属于哪个小节。
                if bar != events[-1]["bar"]:
                    tie_spans.append((events[-1]["bar"], bar, 1.0))
                events[-1]["beats"] += 1.0
                continue
            if tok.startswith("("):
                close = tok.find(")")
                if close < 0:
                    raise JianpuError(f"第 {lineno} 行和弦缺少右括号：{tok!r}")
                inner, tail = tok[1:close], tok[close + 1:]
                beats = 1.0
                for c in tail:
                    if c == "-":
                        beats += 1.0
                    elif c == "/":
                        beats /= 2
                    elif c == ".":
                        beats *= 1.5
                degs = split_chord(inner, lineno)
                if not degs:
                    raise JianpuError(f"第 {lineno} 行和弦是空的")
                if events and events[-1].get("tie"):
                    # 连音线接在**和弦**上（写法 `… (5 1) | ~(5 1) …`）。
                    # 与单音同一条规则：只有两端音**完全一样**才合并，时值相加，
                    # 跨小节时那部分时值归新小节（靠 tie_spans 在校验时挪回去）。
                    prev = events[-1]
                    if prev["degs"] != degs:
                        raise JianpuError(
                            f"第 {lineno} 行连音线两端的和弦不一样 —— `~` 只把"
                            f"**同一组音**接起来")
                    prev.pop("tie")
                    if bar != prev["bar"]:
                        tie_spans.append((prev["bar"], bar, beats))
                    prev["beats"] += beats
                    continue
                events.append({"degs": degs, "beats": beats, "bar": bar})
                continue

            deg, acc, oct_shift, beats = parse_degree_tok(tok, lineno)
            if events and events[-1].get("tie"):
                # `~` 在本工具里是**连音线（tie）**：只把同一个音接起来、时值相加。
                # 两端音不同就报错 —— 不然会静默把后一个音吞掉，很难查。
                # （要是想表达「连奏 / 圆滑线」，那是全曲性的，请用 --hold next。）
                events[-1].pop("tie")
                prev = events[-1]
                if not deg:
                    raise JianpuError(f"第 {lineno} 行连音线后面接的是休止，无法合并")
                if len(prev["degs"]) == 1 and prev["degs"][0] == (deg, acc, oct_shift):
                    # ⚠️ 连音线**跨小节**时（写法是 `… 3/ | ~3 2 …`，小节线写在
                    # 接音之前），接过来的那部分时值其实属于**新小节**。合并后
                    # 它挂在旧小节的那个事件上，会让「每小节拍数」校验把旧小节
                    # 算多、新小节算少 —— 所以单独记一笔，校验时挪回去。
                    if bar != prev["bar"]:
                        tie_spans.append((prev["bar"], bar, beats))
                    prev["beats"] += beats
                    continue
                raise JianpuError(
                    f"第 {lineno} 行连音线两端的音不一样 —— `~` 只把**同一个音**接起来"
                    f"（想表达连奏请改用 --hold next）")
            events.append({"degs": [(deg, acc, oct_shift)] if deg else [],
                           "beats": beats, "bar": bar})

    if events and events[-1].get("tie"):
        events[-1].pop("tie")

    # ---- 拍数校验：每小节相加应等于拍号 ----
    problems = []
    if events:
        total_bars = max(e["bar"] for e in events) + 1
        per = [0.0] * total_bars
        for e in events:
            per[e["bar"]] += e["beats"]
        for b_from, b_to, beats in tie_spans:            # 连音线跨小节：时值归新小节
            per[b_from] -= beats
            if b_to < total_bars:
                per[b_to] += beats
        for i, got in enumerate(per[:-1]):               # 最后一小节允许不完整
            if abs(got - meta["beats_per_bar"]) > EPS:
                problems.append(f"第 {i + 1} 小节是 {got:g} 拍，拍号要求 {meta['beats_per_bar']:g} 拍")

    # ---- 选格：最小音符时值必须是格的整数倍 ----
    unit = None
    smallest = min((e["beats"] for e in events), default=1.0)
    for cand in GRID_CANDIDATES:
        if all(abs(e["beats"] / cand - round(e["beats"] / cand)) < 1e-6 for e in events):
            unit = cand
            break
    if unit is None:
        raise JianpuError(
            "音符时值不是十六分 / 三十二分 / 六十四分音符的整数倍"
            f"（最小 {smallest:g} 拍）—— 请检查是否写了三连音等非二进制时值")

    return meta, events, markers, unit, problems


# ---------------------------------------------------------------- 音高求解

def raw_pitch(deg, acc, oct_shift, tonic_pc):
    """
    简谱级数 → 绝对音高（MIDI 号），**未移调**。

    基准：`base = 60`，也就是「1=C 时不带点的 1 = C4（中央 C）」。
    级数 1~7 按大调音阶取半音偏移（简谱的 1 2 3 4 5 6 7 天然就是大调音阶），
    `oct_shift` 是 `'` / `,` 的净个数（每层 ±12）。

    注意 base 只决定「写下来的相对位置」，真正的八度由 choose_transpose()
    的第 2 阶段挑 —— 所以 1=G 的曲子不需要手工挪。
    """
    semi = MAJOR[deg - 1] + 12 * oct_shift
    if acc == "#":
        semi += 1
    elif acc == "b":
        semi -= 1
    return 60 + tonic_pc + semi


def snap_to_white(p):
    """
    把音高吸附到最近的白键。等距时**往下**取 —— 对简谱里常见的
    `#4`（→ 落回 4）、`b7`（→ 6）、`b3`（→ 2）、`#5`（→ 5）都更温和，
    比往上顶一个全音听感上更像「原来的那个音」。
    """
    for d in (0, -1, 1, -2, 2):
        if (p + d) % 12 in WHITE:
            return p + d
    return p                                  # 到不了（白键间隔最多 2 半音）


def fold_into(p, max_fold):
    """
    把 p 折进琴域 [48, 83]，最多挪 max_fold 个八度。

    返回 (折后音高, 挪了几个八度)；折不进来返回 (None, None)。
    优先挪得少的方案 —— 挪八度会改音区，是听感上的「错位」。
    """
    if LOW <= p <= HIGH:
        return p, 0
    for k in sorted(range(-max_fold, max_fold + 1), key=abs):
        q = p + 12 * k
        if LOW <= q <= HIGH:
            return q, k
    return None, None


def choose_transpose(pitches, max_fold):
    """
    两阶段选移调量 —— 与 midi_to_score.choose_tonic_and_base 同构：

      阶段 1（音级，12 个）：最小化「落到黑键上、必须吸附」的音数 —— 这一步
        决定**调性是否正确**。全音阶调式（大调 / 自然小调）永远有且只有一个
        音级能让整首全落白键：1=C → 0，1=G → +5（≡ −7，即下移纯五度/上移纯四度
        都行，八度由阶段 2 定），1=D → +10（≡ −2），1=F → +7（≡ −5）。
        同分时再比「吸附总位移」，避免随便取一个。

      阶段 2（八度，−4…+4）：在「音级已经定死」（只能整体挪 ±12k）的前提下
        挑八度。判据按优先级：
          ① 丢音数最少 —— 折八度都放不下的才丢，这个最不能忍；
          ② 折八度数最少 —— **整首挪一个八度不改任何音程**（只是音区变），
             而只把个别音折八度会**打断旋律轮廓**，所以宁可整首挪；
          ③ 整首中心离琴域中点最近 —— 36 个半音位，摆中间才不浪费两头的键；
          ④ |T 折到 ±6 内| —— 纯粹为了在不同八度彻底打平时定个序。

    别用「最小化总音高位移」当目标（那是错的）：它会把整首往音域中间拽，
    牺牲调性正确性。也别用「|T| 最小」当第二判据 —— 那等于假设「1 永远在中
    央 C」，对 1=G 这种调号会把整首顶高一个八度（do 被定在 G4），白吃一次折
    八度；要用「折它到 ±6 内」的 T 才对调号不敏感。
    """
    best_pc, best_key = 0, None
    for pc in range(12):
        black = sum(1 for p in pitches if (p + pc) % 12 not in WHITE)
        shift = sum(abs(snap_to_white(p + pc) - (p + pc)) for p in pitches)
        key = (black, shift)
        if best_key is None or key < best_key:
            best_pc, best_key = pc, key

    middle = (LOW + HIGH) / 2.0
    center = (min(pitches) + max(pitches)) / 2.0
    best_T, best_key2 = best_pc, None
    for octv in range(-4, 5):
        T = best_pc + 12 * octv
        lost = folds = 0
        for p in pitches:
            q, k = fold_into(p + T, max_fold)
            if q is None:
                lost += 1
            else:
                folds += abs(k)
        t_rel = abs((T + 6) % 12 - 6)                 # T 折到 −6…+5 的绝对值
        key = (lost, folds, abs(center + T - middle), t_rel)
        if best_key2 is None or key < best_key2:
            best_T, best_key2 = T, key

    return best_T, best_pc, best_key


# ---------------------------------------------------------------- 落键

class Placement:
    """一次落键的统计。字段都是**计数**，报告里直接读。"""

    def __init__(self):
        self.total = 0          # 一共多少「音」（和弦按单个音算）
        self.lost = 0           # 折八度也放不下，丢弃
        self.folded = 0         # 挪了八度
        self.off_key = 0        # 落在黑键上、被吸附（走音）
        self.black = 0          # 阶段 1 意义下的黑键数（吸附前）
        self.lost_examples = []  # 丢掉的音，给几条样例

    def as_dict(self):
        return {"总音数": self.total, "吸附走音": self.off_key,
                "挪八度": self.folded, "丢弃": self.lost}


def place(p, T, max_fold, st):
    """绝对音高（未移调）→ 按键字符；放不下返回 None。"""
    st.total += 1
    q, k = fold_into(p + T, max_fold)
    if q is None:
        st.lost += 1
        if len(st.lost_examples) < 8:
            st.lost_examples.append(p + T)
        return None
    if k:
        st.folded += 1
    if q % 12 not in WHITE:
        st.black += 1
    s = snap_to_white(q)
    if s != q:
        st.off_key += 1
    return KEY_OF[s]


def solve_keys(events, tonic_pc, T, max_fold):
    """
    给每个事件解出按键串。返回 (按键串列表, Placement)。

    按键串按**低音组 → 中音组 → 高音组**排序（项目的硬性约定，不是字母序）；
    事件里丢掉的音直接不出现在串里，全丢则这个事件整格变成休止。
    """
    st = Placement()
    out = []
    for e in events:
        keys = []
        for deg, acc, oct_shift in e["degs"]:
            c = place(raw_pitch(deg, acc, oct_shift, tonic_pc), T, max_fold, st)
            if c is not None and c not in keys:
                keys.append(c)
        keys.sort(key=ORDER.index)
        out.append("".join(keys))
    return out, st


# ---------------------------------------------------------------- 打格

def render(events, keys_per_event, markers, unit, unit_ms):
    """
    把事件铺到均匀网格上，**一行 = 一格**（与 midi_to_score 的网格模式同构）。

      cells    {格号: 按键串}
      holds    {格号: 标称按住毫秒}   = 本音自己的时值 − GAP
      total    总格数
      mark_at  [(格号, 段落名)]

    为什么按住取「自己的时值」而不是「到下一个音的间隔」：
      · 取自己的时值 → 休止格是**真静默**，听得出断句 / 换气；
      · 取到下一个音的间隔 → 键一路按到下一个音，休止格也不再安静（连奏）。
    两种写法都符合 parser 的钳制，选哪种是**音乐**取舍，由 --hold 决定。
    """
    cells, holds, mark_at = {}, {}, []
    mi = 0
    cursor = 0
    for i, e in enumerate(events):
        while mi < len(markers) and markers[mi][0] == i:
            mark_at.append((cursor, markers[mi][1]))
            mi += 1
        n = int(round(e["beats"] / unit))
        if n < 1:                                # 理论上到不了（unit 取的是公约格）
            n = 1
        ks = keys_per_event[i]
        if ks:
            cells[cursor] = ks
            holds[cursor] = n * unit_ms - GAP
        cursor += n
    while mi < len(markers):                     # 收尾的段落标记（挂在最后一个事件上）
        mark_at.append((cursor, markers[mi][1]))
        mi += 1
    return cells, holds, cursor, mark_at


def cap_holds(cells, holds, total, unit_ms, hold_mode):
    """
    按 parser._clamp_holds 的**同一口径**算出最终写进谱子的值。

    上限 cap = 到下一个**发声**格的间隔 − HOLD_GAP_MS；下限 HOLD_MIN。
    `hold = max(HOLD_MIN, min(nominal, cap))` —— **先 min 后 max**，
    顺序反了会漏掉「标称时值本身就短于下限」的情况，写出十几毫秒的按键。

    返回 (最终按住 {格号: 毫秒}, 上限容不下下限的格号列表)。
    最后一格没有下一个，不钳上限（与 parser 一致）。
    """
    sounding = sorted(cells)
    nxt = dict(zip(sounding, sounding[1:]))
    out, too_tight = {}, []
    for c in sounding:
        nominal = holds[c]
        if hold_mode == "next":                  # 连奏：一路按到下一个发声格
            b = nxt.get(c)
            nominal = (b - c) * unit_ms - GAP if b is not None else nominal
        b = nxt.get(c)
        if b is None:
            hold = max(HOLD_MIN, nominal)
        else:
            cap = (b - c) * unit_ms - GAP
            hold = max(HOLD_MIN, min(nominal, cap))
            if hold > cap:                       # 格子在 60ms 以下才会发生
                too_tight.append(c)
        out[c] = hold
    return out, too_tight


# ---------------------------------------------------------------- 多声部叠加

def merge_voices(voice_cells, voice_holds, voice_totals, voice_marks):
    """
    把若干条**独立声部**按格合并成一份谱面。

    为什么需要它：本工具的单文件格式是**严格顺序**的（一个事件占一段时值），
    表达不了「上谱表旋律 + 下谱表伴奏」这种两条独立节奏线。所以双谱表的谱子
    拆成两个文件各写各的，再用这里按格叠起来 —— 同格出现的音取**并集**
    （变成和弦，播放器会同时按下），按住时长取**最大值**（最长的那根说了算，
    之后还会被 cap_holds 按「到下一个发声格」钳一遍）。

    前提：所有声部的 `unit` 必须相同（同一张谱上取的最小格），移调量也必须
    是同一个（在 main 里对全部声部的音一起求解），否则两声部会落在不同音高体系。
    """
    total = max(voice_totals) if voice_totals else 0
    cells, holds, marks = {}, {}, {}
    for vc, vh, vm in zip(voice_cells, voice_holds, voice_marks):
        for c, ks in vc.items():
            if c in cells:
                merged = cells[c] + "".join(k for k in ks if k not in cells[c])
                cells[c] = "".join(sorted(merged, key=ORDER.index))
            else:
                cells[c] = ks
        for c, h in vh.items():
            if h > holds.get(c, -1):
                holds[c] = h
        for c, text in vm:
            marks.setdefault(c, [])
            if text not in marks[c]:
                marks[c].append(text)
    mark_at = [(c, t) for c in sorted(marks) for t in marks[c]]
    return cells, holds, total, mark_at


def max_voices(cells):
    """一格上最多同时按几个键（给报告用；用户实测 5 键都能出声）。"""
    return max((len(v) for v in cells.values()), default=0)


# ---------------------------------------------------------------- 组装成文本

def format_unit_ms(unit, bpm):
    """格子的毫秒数（整数，parser 只吃整数）。"""
    ms = int(round(unit * 60000.0 / bpm))
    return max(1, ms)


def build_text(name, meta, unit, unit_ms, cells, holds, total, mark_at,
               hold_mode, speed, source_name, st, T, pc_group, voices=None):
    """拼出最终文件内容（不含末尾换行，由调用方补）。

    voices = [(声部名, 该声部文件名, Placement), ...]；None 表示单声部。
    """
    per_bar = meta["beats_per_bar"] / unit
    note_names = ("十六分", "三十二分", "六十四分")
    idx = GRID_CANDIDATES.index(unit) if unit in GRID_CANDIDATES else 0
    sources = source_name if isinstance(source_name, str) else " + ".join(source_name)

    head = [
        f"#{speed:g}倍速",
        "#" + "=" * 62,
        f"#  {name} —— 简谱转谱（1={meta['key']}，"
        f"{meta['beats_per_bar']:g}/4 拍，{meta['bpm']} BPM）",
        f"#  一行 = 一个{note_names[idx]}音符 = {unit_ms} 毫秒；"
        f"每小节 {per_bar:g} 格",
        f"#  移调 {T:+d} 半音（阶段 1 选到的音级 {pc_group}）→ "
        f"全曲落白键；按住时长 = 本音自己的时值 − {GAP}ms",
        f"#  由 获取谱子/jianpu_to_score.py 从 {sources} 生成，改谱请改简谱",
    ]
    if voices and len(voices) > 1:
        head.append(f"#  {len(voices)} 个声部按格叠加（同格取并集 = 和弦）："
                    + " / ".join(f"{n}：音 {s.total} 走音 {s.off_key} "
                                 f"挪八度 {s.folded} 丢 {s.lost}"
                                 for n, _f, s in voices))
    else:
        head.append(f"#  音数 {st.total}｜吸附走音 {st.off_key}｜"
                    f"挪八度 {st.folded}｜丢弃 {st.lost}")
    head.append("#" + "=" * 62)
    if hold_mode == "none":
        head[4] = (f"#  移调 {T:+d} 半音（阶段 1 选到的音级 {pc_group}）→ 全曲落白键；"
                   f"不写按住时长，播放器用默认 {HOLD_MIN}ms")

    body = []
    marks = {}
    for c, text in mark_at:
        marks.setdefault(c, []).append(text)
    for c in range(total):
        for text in marks.get(c, ()):
            body.append(f"#{text}")
        if c in cells:
            if hold_mode == "none":
                body.append(f"{unit_ms} {cells[c]}")
            else:
                body.append(f"{unit_ms} {cells[c]} {holds[c]}")
        else:
            body.append(str(unit_ms))
    for c in sorted(k for k in marks if k >= total):     # 挂在曲末的段落标记
        for text in marks[c]:
            body.append(f"#{text}")
    return head + body


# ---------------------------------------------------------------- 自检

def load_parser():
    spec = importlib.util.spec_from_file_location("parser", ROOT / "parser.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def simulate(notes, speed=1.0, hold_default=HOLD_MIN):
    """
    用一个理想化的顺序阻塞播放器跑一遍，返回 (最大迟到毫秒, 所在行号)。

    模型与 player.play() 完全一致：每行先睡到绝对目标时刻（**只补不欠**），
    发声行再按住 hold 毫秒。

    ⚠️ 只对**发声行**判定迟到 —— 休止行不按键、不占时间（player.py 里
    `if keys:` 为假时连 sleep 都跳过），它「晚」了也没有声音会晚，只是把
    目标往后推，正好当还账缓冲。要是把休止行也算进来，会看到上千毫秒的
    假迟到（第一格按住 590ms 早就盖过了后面三格休止的时刻）。

    真正要守的不变量只有一条：**任一发声行的目标时刻 ≥ 上一次按住结束的时刻**。
    因为谱面是均匀网格、且 hold ≤ 到下一个发声格的间隔 − 10ms，迟到应当恒为 0。
    """
    now = 0.0
    worst, worst_line = 0.0, None
    for n in notes:
        target = n.time / speed
        if target > now:
            now = target
        if not n.keys:
            continue
        late = now - target
        if late > worst + 1e-9:
            worst, worst_line = late, n.line
        now += (n.hold if n.hold > 0 else hold_default) / speed
    return worst, worst_line


def self_check(text, path, cells, holds, total, unit_ms, hold_mode, speed):
    """把要落盘的内容原样喂给 parser 再读回来，逐项对账。返回问题列表。"""
    problems = []

    # 1) 字节层：UTF-8 无 BOM、纯 LF、末尾有换行
    raw = text.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("产物带 UTF-8 BOM")
    if b"\r" in raw:
        problems.append("产物含 CR，不是纯 LF")
    if not raw.endswith(b"\n"):
        problems.append("产物末尾缺换行")

    # 2) 首行必须是 `#数字倍速`
    first = text.splitlines()[0] if text else ""
    if not re.match(r"^#\d+(?:\.\d+)?倍速$", first):
        problems.append(f"首行不是 `#数字倍速`：{first!r}")

    # 3) 行语法 + 计时行数
    timed = 0
    for i, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        if not re.match(r"^\d+$|^\d+ [a-z]+$|^\d+ [a-z]+ \d+$", line):
            problems.append(f"第 {i} 行不符合 `间隔 按键 [按住]` 语法：{line!r}")
        timed += 1
    if timed != total:
        problems.append(f"计时行 {timed} 行，网格应 {total} 格")

    # 4) parser 回读
    parser = load_parser()
    tmp = Path(path)
    notes = parser.parse(tmp)
    if len(notes) != total:
        problems.append(f"parser 读出 {len(notes)} 行，网格 {total} 格")
    for c in range(min(len(notes), total)):
        if notes[c].time != (c + 1) * unit_ms:
            problems.append(f"第 {c + 1} 格落在 {notes[c].time}ms，"
                            f"均匀网格应为 {(c + 1) * unit_ms}ms")
            break
    sounding = sorted(cells)
    for c in sounding:
        if notes[c].keys != list(cells[c]):
            problems.append(f"第 {c + 1} 格按键不符：谱面 {cells[c]!r} / "
                            f"读回 {''.join(notes[c].keys)!r}")
            break
    if hold_mode != "none":
        for c in sounding:
            got = notes[c].hold
            if got != holds[c]:
                problems.append(f"第 {c + 1} 格按住不符：写 {holds[c]} / 读回 {got}")
                break
    for n in notes:                                   # 下限 / 上限（parse 已钳，复核口径一致）
        # ⚠️ hold == 0 是**合法**的：那是「没写第三列，用播放器默认值」，
        # parser._clamp_holds 会直接 continue 掉。只有 >0 才受下限约束。
        if n.keys and 0 < n.hold < HOLD_MIN:
            problems.append(f"第 {n.line} 行按住 {n.hold}ms 低于下限 {HOLD_MIN}ms")
            break

    # 5) 音域：按键必须都在 21 键内
    for n in notes:
        bad = [k for k in n.keys if k not in KEY_OF.values()]
        if bad:
            problems.append(f"第 {n.line} 行出现琴上没有的键 {bad}")
            break
    used = sorted({k for n in notes for k in n.keys}, key=ORDER.index)
    if used:
        semis = [PITCH[ORDER.index(k)] for k in used]
        if max(semis) - min(semis) > SPAN:
            problems.append(f"音域跨 {max(semis) - min(semis)} 半音，超过琴的 {SPAN}")

    # 6) 模拟播放：绝对时间轴上不该有任何迟到
    worst, worst_line = simulate(notes, speed)
    if worst > 1.0:
        problems.append(f"模拟播放最大迟到 {worst:.1f}ms（第 {worst_line} 行）—— "
                        f"按住时长吃掉了给后续音符留的余量")

    dur_ms = total * unit_ms if total else 0
    return problems, notes, used, dur_ms


# ---------------------------------------------------------------- 主流程

def build_parser():
    ap = argparse.ArgumentParser(
        description="把人类简谱（阿拉伯数字谱）转成原神「风物之诗琴」机器谱 txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：\n"
               "  python 获取谱子/jianpu_to_score.py 我的简谱.txt\n"
               "  python 获取谱子/jianpu_to_score.py 我的简谱.txt --bpm 120 --dry-run\n")
    ap.add_argument("jianpu", help="主声部简谱文本文件（UTF-8）")
    ap.add_argument("--overlay", action="append", metavar="另一声部.txt",
                    help="再叠一个声部（可重复）。各声部共用同一个移调量（对全部"
                         "声部的音一起求解），格不同会自动齐到最细的那套；"
                         "同格出现的音取并集变成和弦 —— 用来做「上谱表旋律 + 下谱表"
                         "伴奏」这种双声部简谱。")
    ap.add_argument("-o", "--out", help="输出路径（默认 scores/<主声部文件名>.txt）")
    ap.add_argument("--bpm", type=int, help="覆盖简谱首行写的 BPM（BPM 按四分音符计）")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="写进首行的倍速（默认 1.0；与曲谱生态一致，实际播放间隔 ÷ 倍速）")
    ap.add_argument("--hold", choices=("own", "next", "none"), default="own",
                    help="按住时长怎么给：own=本音自己的时值−10ms（默认，休止格真静默）；"
                         "next=一路按到下一个发声格−10ms（连奏）；none=不写第三列")
    ap.add_argument("--max-fold", type=int, default=1,
                    help="音域外的音最多挪几个八度找位置（默认 1；给个大数等于一个都不丢）")
    ap.add_argument("--no-pad", action="store_true", help="末尾不补齐整小节")
    ap.add_argument("--force", action="store_true", help="自检有问题也照样落盘")
    ap.add_argument("--dry-run", action="store_true", help="只转换 + 自检，不落盘")
    return ap


def load_voice(path):
    """读一个简谱文件 → (meta, events, markers, unit, problems)。"""
    text = Path(path).read_text(encoding="utf-8-sig")      # utf-8-sig：容忍记事本加的 BOM
    return parse_jianpu(text)


def main(argv=None):
    args = build_parser().parse_args(argv)

    spec = [Path(args.jianpu)] + [Path(p) for p in (args.overlay or [])]
    for p in spec:
        if not p.is_file():
            print(f"找不到简谱文件：{p}")
            return 2

    voices = []
    for p in spec:
        try:
            meta_v, events, markers, unit_v, problems = load_voice(p)
        except JianpuError as e:
            print(f"简谱解析失败（{p.name}）：{e}")
            return 2
        if not events:
            print(f"{p.name} 里没有解析到任何音符，请检查格式（见文件头 docstring）")
            return 2
        voices.append({"path": p, "meta": meta_v, "events": events,
                       "markers": markers, "unit": unit_v, "problems": problems})

    meta = voices[0]["meta"]
    # 各声部「自己最少需要多细的格」可以不同：旋律有 32 分音符就得 1/32 拍，
    # 伴奏全是 8 分就只要 1/4 拍。在同一张谱上它们本来就共用同一个最小格，
    # 记谱简省不是另一张谱 —— 所以叠加时统一齐到**最细**的那一套。
    unit = min(v["unit"] for v in voices)
    if args.bpm:
        meta["bpm"] = args.bpm

    # --- 声部之间共用同一个移调量；格不同就齐到最细的 ---
    for v in voices[1:]:
        if abs(v["unit"] - unit) > EPS:
            print(f"  注：{v['path'].name} 自己只需 {v['unit']:g} 拍的最小格，"
                  f"叠加时齐到最细的 {unit:g} 拍")
        if (v["meta"]["key"] != meta["key"]
                or abs(v["meta"]["beats_per_bar"] - meta["beats_per_bar"]) > EPS):
            print(f"  !! {v['path'].name} 的调号/拍号（{v['meta']['key']} "
                  f"{v['meta']['beats_per_bar']:g}/4）与主声部（{meta['key']} "
                  f"{meta['beats_per_bar']:g}/4）不同 —— 按主声部处理")
        if v["meta"]["bpm"] != meta["bpm"]:
            print(f"  !! {v['path'].name} 的 BPM（{v['meta']['bpm']}）"
                  f"与主声部（{meta['bpm']}）不同 —— 按主声部处理")

    speed = args.speed if args.speed > 0 else 1.0
    unit_ms = format_unit_ms(unit, meta["bpm"])

    # --- 移调：对**全部声部**的音一起求解，两声部才落在同一音高体系 ---
    all_raw = [raw_pitch(d, a, o, KEY_PC[v["meta"]["key"]])
               for v in voices for e in v["events"] for d, a, o in e["degs"]]
    T, pc_group, _ = choose_transpose(all_raw, args.max_fold)

    # --- 各声部分别落键、打格，再按格叠加 ---
    v_cells, v_holds, v_totals, v_marks, infos = [], [], [], [], []
    for v in voices:
        keys_per_event, st_v = solve_keys(v["events"], KEY_PC[v["meta"]["key"]],
                                         T, args.max_fold)
        cells_v, holds_v, total_v, mark_v = render(v["events"], keys_per_event,
                                                   v["markers"], unit, unit_ms)
        v_cells.append(cells_v)
        v_holds.append(holds_v)
        v_totals.append(total_v)
        v_marks.append(mark_v)
        infos.append(st_v)

    cells, holds, total, mark_at = merge_voices(v_cells, v_holds, v_totals, v_marks)
    if not args.no_pad:
        per_bar = int(round(meta["beats_per_bar"] / unit))
        pad = (-total) % per_bar
        if pad:
            total += pad

    final_holds, too_tight = cap_holds(cells, holds, total, unit_ms, args.hold)
    if args.hold == "none":
        final_holds = {}
        if unit_ms < HOLD_MIN:
            print(f"  !! --hold none 且格只有 {unit_ms}ms：播放器对每一行都用默认 "
                  f"{HOLD_MIN}ms 按住，比格子还长，密集处会逐行累积迟到"
                  f"（要精确按住就用默认的 --hold own）")

    # ⚠️ 汇总必须新建对象：st = infos[0] 再 += 会把第 1 声部自己的统计也改掉
    st = Placement()
    for s in infos:
        st.total += s.total
        st.off_key += s.off_key
        st.folded += s.folded
        st.lost += s.lost
        st.lost_examples.extend(s.lost_examples)
    st.lost_examples = st.lost_examples[:8]
    voice_info = [("主声部（第 1 个文件）", voices[0]["path"].name, infos[0])] + [
        (f"叠加声部 {i + 1}", voices[i + 1]["path"].name, infos[i + 1])
        for i in range(len(infos) - 1)
    ] if len(voices) > 1 else None

    body = build_text(voices[0]["path"].stem, meta, unit, unit_ms, cells,
                      final_holds, total, mark_at, args.hold, speed,
                      [str(v["path"].name) for v in voices] if len(voices) > 1
                      else voices[0]["path"].name,
                      st, T, pc_group, voice_info)
    out_text = "\n".join(body) + "\n"

    # --- 报告 ---
    note_names = ("十六分", "三十二分", "六十四分")
    for i, v in enumerate(voices):
        n_sing = sum(1 for e in v["events"] if e["degs"])
        n_rest = len(v["events"]) - n_sing
        print(f"声部 {i + 1} {v['path'].name}：{len(v['events'])} 个事件"
              f"（{n_sing} 发声 / {n_rest} 休止）"
              f"｜音数 {infos[i].total} 走音 {infos[i].off_key} "
              f"挪八度 {infos[i].folded} 丢 {infos[i].lost}")
    print(f"调号 1={meta['key']} {meta['beats_per_bar']:g}/4 {meta['bpm']} BPM"
          f" → 格 = {note_names[GRID_CANDIDATES.index(unit)]} = {unit_ms}ms"
          f"（约 {60000 / (unit_ms * (1 / unit)):.0f} BPM）")
    print(f"移调 {T:+d} 半音（音级 {pc_group}）｜合计 吸附走音 {st.off_key}/{st.total}"
          f"｜挪八度 {st.folded}｜丢弃 {st.lost}")
    if st.off_key:
        print(f"  走音是琴的物理限制（21 键无升降号）：临时升降号只能吸附到最近的白键")
    if st.lost:
        print(f"  !! 合计 {st.lost} 个音折 {args.max_fold} 个八度仍放不下、只能丢弃"
              f"（样例 {st.lost_examples[:4]}）——调大 --max-fold 可以少丢")
    if too_tight and args.hold != "none":
        print(f"  !! {len(too_tight)} 格的时值短于按住下限 {HOLD_MIN}ms，"
              f"按住会被下限顶到略超出格子（格 {unit_ms}ms 太密）")
    for v in voices:
        for p in v["problems"]:
            print(f"  !! 拍数（{v['path'].name}）：{p}")
    print(f"共 {total} 格 = {sum(1 for c in cells if c < total)} 个发声格 / "
          f"{total - len(cells)} 个休止格｜"
          f"时长 {total * unit_ms / 1000:.1f}s"
          f"｜单格最多同时按 {max_voices(cells)} 键")

    # --- 自检：先写临时文件让 parser 读回来对账 ---
    tmp = Path(tempfile.gettempdir()) / f"jianpu_check_{out_text.__hash__() & 0xFFFFFF}.txt"
    tmp.write_text(out_text, encoding="utf-8", newline="\n")
    try:
        chk, notes, used, dur_ms = self_check(out_text, tmp, cells, final_holds,
                                             total, unit_ms, args.hold, speed)
    finally:
        if tmp.exists():
            tmp.unlink()

    if used:
        print(f"用到的键：{''.join(used)}（{len(used)} 个）"
              f"｜音域 {PITCH[ORDER.index(used[0])]}..{PITCH[ORDER.index(used[-1])]}"
              f"（跨 {PITCH[ORDER.index(used[-1])] - PITCH[ORDER.index(used[0])]} 半音）")
    if chk:
        print("自检发现问题：")
        for p in chk:
            print(f"  !! {p}")
    else:
        print("自检通过：行语法 / parser 回读 / 均匀网格 / 按住上下限 / 音域 / "
              "模拟播放零迟到 / 编码（UTF-8 无 BOM + 纯 LF + 末尾换行）")

    if chk and not args.force:
        print("产物未落盘（自检有问题）。确认无误可加 --force 强制写出。")
        return 1

    if args.dry_run:
        print("--dry-run：产物未落盘。")
        return 0

    out = Path(args.out) if args.out else SCORES / f"{voices[0]['path'].stem}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        bak = out.with_suffix(out.suffix + ".bak")
        i = 1
        while bak.exists():
            bak = out.with_suffix(out.suffix + f".bak{i}")
            i += 1
        out.replace(bak)
        print(f"同名谱子已存在，原件备份为 {bak.name}")
    out.write_text(out_text, encoding="utf-8", newline="\n")
    print(f"已写出 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
