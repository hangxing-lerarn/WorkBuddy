# -*- coding: utf-8 -*-
"""
给曲谱补上「按住时长」第三列 —— 把已有的无按住谱子升级成带按住的版本。

用法（在项目根目录）:
    python 获取谱子/add_hold.py                     # 试运行：只打印计划，不写文件
    python 获取谱子/add_hold.py --write             # 真正写回
    python 获取谱子/add_hold.py scores/unravel.txt --write
    python 获取谱子/add_hold.py scores/ --write --gap 10 --min 50 --round 10

不传路径时默认处理 scores/ 下所有 .txt。已经带了一部分第三列的文件会被**跳过**
（视为人工维护过，例如 scores/琴行为探针.txt 只有第 6 段是按住 A/B 对照），
要强制处理加 --force。

规则（保住原有断句）:
    发声行的按住时长 = (本行的起点 → 下一个更晚的行的起点) - gap
    也就是「这一行的音符弹满自己这一格」:
      · 下一行是音符 → 两音之间只隔 gap，连起来
      · 下一行是休止 → 在休止开始前 gap 松开，休止依旧是静默（断句一字不改）
    下限 min（默认 50ms —— 太短的按键游戏可能收不到）。默认不做取整：
    手工谱的间隔本来就是整齐数，取整只会把 158-10=148 抬成 150、白吃 2ms 余量。
    最后一行后面没有行了，用本文件出现次数最多的间隔。

边界:
    · 只动「有键」的行。注释行、休止行、行数、顺序、行尾风格、末尾换行状态一律保持。
    · 已经有第三列的行原样保留 → 可重复运行（幂等），不会越改越长。
    · 时长为 0 的行（同刻和弦的续行）按「下一个更晚的行」算，与前一音同组。

为什么按住时长必须 ≤ 格子时长: 播放器是顺序阻塞的（按下 → sleep → 松开），
时间轴用绝对时间自我校正，一旦某行超时就**永远补不回来**。留 gap 是给
「松开旧键 + 按下新键」的开销。详见 README「按住时长（长音）」一节。
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# 与 parser.HOLD_GAP_MS / parser.DEFAULT_HOLD_MS 保持一致
DEFAULT_GAP_MS = 10
DEFAULT_MIN_MS = 50
# 手工谱的间隔本来就是人工定的整齐数（158 / 472 / 100…），取整没有收益，
# 反而会把 158-10=148 抬成 150，吃掉 2ms 余量。所以默认不取整。
DEFAULT_ROUND_MS = 0

# 由 __file__ 推出项目根，任何 cwd 都能跑
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "scores"

_TERMINATOR = re.compile(r"(\r\n|\n|\r)$")


def split_terminator(s):
    """把行尾换行符（\\r\\n / \\n / \\r / 无）切出来。"""
    m = _TERMINATOR.search(s)
    if m:
        return s[: m.start()], m.group(1)
    return s, ""


def shape_hold(cell_ms, gap, hold_min, hold_round, hold_max):
    """格子时长 → 写入文件里的按住时长。与 midi_to_score.shape_hold 同序。"""
    h = cell_ms - gap
    if hold_max > 0:
        h = min(h, hold_max)
    if hold_round > 0:
        h = int(round(h / hold_round)) * hold_round
    h = max(h, hold_min)
    return max(1, int(h))


def read_rows(text):
    """解析成 data 列表: [行下标, 间隔, 键串或 None, 已有的第三列或 None]。"""
    data = []
    for i, raw in enumerate(text.splitlines(keepends=True)):
        body, _term = split_terminator(raw)
        s = body.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        try:
            interval = int(parts[0])
        except ValueError:
            raise ValueError(f"第 {i + 1} 行不是以整数开头: {body!r}")
        keys = parts[1] if len(parts) >= 2 else None
        hold = None
        if len(parts) >= 3:
            try:
                hold = int(parts[2])
            except ValueError:
                raise ValueError(f"第 {i + 1} 行第三列不是整数: {body!r}")
        data.append([i, interval, keys, hold])
    return data


def plan_text(text, gap=DEFAULT_GAP_MS, hold_min=DEFAULT_MIN_MS,
              hold_round=DEFAULT_ROUND_MS, hold_max=0):
    """
    返回 (新文本, 统计 dict 或 None)。统计为 None 表示这份谱子不需要改。
    """
    raw_lines = text.splitlines(keepends=True)
    data = read_rows(text)
    if not data:
        return text, None

    # 每行的起点（parser 是 current_time += interval，所以第一行的起点就是它的间隔）
    times = []
    t = 0
    for _idx, interval, _keys, _hold in data:
        t += interval
        times.append(t)

    # 本行的「格子时长」= 到下一个更晚的行的起点；没有则为 None
    cell = [None] * len(data)
    for a in range(len(data)):
        for b in range(a + 1, len(data)):
            if times[b] > times[a]:
                cell[a] = times[b] - times[a]
                break

    # 最后一行没有「下一个更晚的行」，用本文件最常见的**正**间隔
    # （取正的：同刻续行那种 0 间隔不代表时值，拿它兜底会算出下限）
    positives = Counter(iv for _i, iv, _k, _h in data if iv > 0)
    modal = positives.most_common(1)[0][0] if positives else hold_min

    holds = []
    written = 0
    kept = 0
    short = 0
    for n, (idx, _interval, keys, old_hold) in enumerate(data):
        if not keys:
            continue  # 休止行不加第三列
        if old_hold is not None:
            holds.append(old_hold)
            kept += 1
            continue
        c = cell[n] if cell[n] is not None else modal
        if c - gap < hold_min:
            short += 1
        h = shape_hold(c, gap, hold_min, hold_round, hold_max)
        holds.append(h)
        body, term = split_terminator(raw_lines[idx])
        raw_lines[idx] = f"{body} {h}{term}"
        written += 1

    new_text = "".join(raw_lines)
    holds_sorted = sorted(holds)
    stats = {
        "rows": len(data),
        "sound_rows": len(holds),
        "written": written,
        "kept": kept,
        "short": short,
        "min": holds_sorted[0] if holds_sorted else 0,
        "max": holds_sorted[-1] if holds_sorted else 0,
        "median": holds_sorted[len(holds_sorted) // 2] if holds_sorted else 0,
        "holds": Counter(holds),
    }
    return new_text, stats


def collect(paths):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(x for x in p.glob("*.txt")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"跳过（不存在）: {p}")
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="给曲谱补上按住时长第三列（保住原有断句）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="*", help=f"谱子文件或目录（默认 {DEFAULT_DIR}）")
    ap.add_argument("--write", action="store_true", help="真正写回文件（默认只试运行）")
    ap.add_argument("--force", action="store_true",
                    help="连「已经有一部分第三列」的文件也处理（默认视为人工维护过，跳过）")
    ap.add_argument("--gap", type=int, default=DEFAULT_GAP_MS,
                    help=f"松开旧键+按下新键的余量，毫秒（默认 {DEFAULT_GAP_MS}）")
    ap.add_argument("--min", dest="hold_min", type=int, default=DEFAULT_MIN_MS,
                    help=f"按住时长下限，毫秒（默认 {DEFAULT_MIN_MS}）")
    ap.add_argument("--round", dest="hold_round", type=int, default=DEFAULT_ROUND_MS,
                    help=f"取整粒度，毫秒；0 = 不取整（默认 {DEFAULT_ROUND_MS}）")
    ap.add_argument("--max", dest="hold_max", type=int, default=0,
                    help="按住时长上限，毫秒；0 = 不限（默认 0）")
    args = ap.parse_args(argv)

    paths = args.paths or [str(DEFAULT_DIR)]
    files = collect(paths)
    if not files:
        print("没有找到可处理的 .txt")
        return 1

    header = (f"{'文件':<34}{'数据行':>7}{'发声行':>7}{'写入':>6}{'保留':>6}"
              f"{'中位':>7}{'范围':>16}{'格子<下限':>10}")
    table, errors, skipped = [], [], []
    changed = 0
    for f in files:
        raw = f.read_bytes()
        text = raw.decode("utf-8")
        try:
            rows = read_rows(text)
        except ValueError as e:
            errors.append(f"{f.name:<34}  解析失败: {e}")
            continue
        # 已经有部分第三列 → 认为是人工维护过的（例如探针谱的对照组），
        # 整体跑目录时默认不碰它，免得把有意为之的写法填平
        n_have = sum(1 for r in rows if r[3] is not None)
        if n_have and not args.force:
            skipped.append((f.name, n_have))
            continue
        try:
            new_text, stats = plan_text(text, args.gap, args.hold_min,
                                        args.hold_round, args.hold_max)
        except ValueError as e:
            errors.append(f"{f.name:<34}  解析失败: {e}")
            continue
        if stats is None:
            table.append(f"{f.name:<34}  （没有数据行，跳过）")
            continue
        rng = f"{stats['min']}~{stats['max']}ms"
        table.append(f"{f.name:<34}{stats['rows']:>7}{stats['sound_rows']:>7}"
                     f"{stats['written']:>6}{stats['kept']:>6}{stats['median']:>6}ms"
                     f"{rng:>16}{stats['short']:>10}")
        if stats["written"] == 0:
            continue
        changed += 1
        if args.write:
            f.write_bytes(new_text.encode("utf-8"))
            table.append(f"    → 已写入 {f}")

    if table:
        print(header)
        print("\n".join(table))
    for e in errors:
        print(e)
    for name, n_have in skipped:
        print(f"跳过 {name}：已经有 {n_have} 行带第三列（人工维护过，加 --force 才处理）")

    if changed and not args.write:
        print(f"\n试运行结束：{changed} 份谱子会被修改。加 --write 才会真正写回。")
    elif changed:
        print(f"\n完成：{changed} 份谱子已更新。")
    elif skipped:
        print(f"\n{len(skipped)} 份谱子已带第三列，其余无需改动。")
    else:
        print("\n所有谱子都已有第三列，无需改动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
