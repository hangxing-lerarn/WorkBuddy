from collections import namedtuple

# 曲谱没写第三列（或写了 0）时，按键按住多久。
# 这个值也是「按住时长」的下限：极密的段落里宁可稍微晚一点，
# 也不要短到游戏收不到按键 —— 与加入第三列之前的行为一致。
DEFAULT_HOLD_MS = 50

# 钳制按住时长时，给「松开旧键 + 按下新键」留的余量（毫秒）。
# 不留余量的话，按住时长正好等于间隔时每一行都会晚一点点，
# 而播放器是顺序阻塞的，这点误差会**逐行累积**，整首越弹越拖。
HOLD_GAP_MS = 10

# 一个音符：
#   time = 距离开始演奏的毫秒数
#   keys = 需要同时按下的键（空列表 = 休止）
#   line = 曲谱中的真实行号
#   hold = 建议按住毫秒（已钳制过；0 表示「用 DEFAULT_HOLD_MS」）
# 新字段加在**末尾**，旧的 Note(t, keys, line) 三元组写法仍然可用。
Note = namedtuple("Note", ["time", "keys", "line", "hold"], defaults=(0,))


def _clamp_holds(notes):
    """
    把每个发声行的按住时长钳制到「离下一个发声行还有多久」。

    为什么必须钳：播放器是顺序阻塞的（按下 -> sleep -> 松开），每一行实际占用的
    时间是「按住时长」，而它只在**还没到目标时刻**时才补睡。于是每一行能**还掉**
    的迟到上限就是「到下一行的间隔 − 按住时长」：

      · 按住 < 间隔（有余量）→ 这点余量会把上一行攒下的迟到一次性还清，
        顺便吸收「按下 / 松开」本身的耗时抖动。
      · 按住 >= 间隔（没有余量）→ 余量为零甚至为负，迟到**逐行累积**，
        整首越来越慢，密集段落里再也追不回来。

    所以按住时长必须留在「到下一个发声行之前」，并留出 HOLD_GAP_MS 的余量。

    注意钳的是「下一个**发声**行」，不是「下一行」：
    中间夹着的休止行什么都不做，按住跨过去完全无害（`128 a` 后面跟 5 行休止，
    按住可以一直延续到下一个音）；按「下一行」钳制会把它误砍成 118ms。
    不过「跨不跨休止」同时也是个**音乐**取舍 —— 想保住休止做出的断音，
    就该在休止前松手（见 获取谱子/add_hold.py 的做法）。

    下限：钳完比 DEFAULT_HOLD_MS 还短（极密的段落）就退回 DEFAULT_HOLD_MS。
    最后一个发声行没有下一个，不钳。
    """
    n = len(notes)
    if not n:
        return
    # nxt[i] = 下一个「真的有键」的行号，没有则为 None
    nxt = [None] * n
    seen = None
    for i in range(n - 1, -1, -1):
        nxt[i] = seen
        if notes[i].keys:
            seen = i

    for i in range(n):
        if notes[i].hold <= 0:
            continue
        j = nxt[i]
        if j is None:
            # 最后一个发声行：没有下一个，按标称时值，但仍要托住下限
            hold = max(DEFAULT_HOLD_MS, notes[i].hold)
        else:
            cap = notes[j].time - notes[i].time - HOLD_GAP_MS
            # 上限压到 cap，下限托到 DEFAULT_HOLD_MS。
            # 注意下限不只在 cap 过小时生效 —— 标称时值本身短于下限（MIDI 里
            # 十几毫秒的装饰音）也要抬起来，否则游戏可能根本收不到那次按键。
            # 只有当 cap 连下限都容不下（极密的段落）时，下限才压过上限，
            # 此时会稍微迟到一点，但仍与加入第三列之前的行为一致。
            hold = max(DEFAULT_HOLD_MS, min(notes[i].hold, cap))
        if hold != notes[i].hold:
            notes[i] = notes[i]._replace(hold=hold)


def parse(file_path, start_line=1):
    """
    解析乐谱文件，返回 Note(time, keys, line, hold) 的列表

    file_path: 乐谱文件路径
    start_line: 从第几行开始演奏（1 为第一行，行号与文本编辑器显示的一致）

    行格式（第三列可选）：
        158                   休止 158 毫秒
        158 a                 按键 a，按住时长用播放器默认值
        158 vj                和弦（连写即同时按下），同上
        320 a 700             按键 a，按住 700 毫秒 —— 用来模拟长音 / 重音

    说明：空行与注释行（以 # 开头）不参与计时，但会占用真实行号。
    这里直接记录每个音符所在的行号，播放时打印的「第 N 行」才与文件对得上。
    """
    notes = []
    current_time = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line_no < start_line:
                continue

            parts = line.split()
            try:
                interval = int(parts[0])
            except ValueError:
                raise ValueError(
                    f"{file_path} 第 {line_no} 行格式错误，"
                    f"应为「间隔毫秒 按键 [按住毫秒]」: {line!r}"
                )

            keys = list(parts[1]) if len(parts) >= 2 else []

            hold = 0
            if len(parts) >= 3:
                try:
                    hold = int(parts[2])
                except ValueError:
                    raise ValueError(
                        f"{file_path} 第 {line_no} 行第三列（按住毫秒）不是整数: {line!r}"
                    )
                if hold < 0:
                    raise ValueError(
                        f"{file_path} 第 {line_no} 行第三列（按住毫秒）不能为负: {line!r}"
                    )
            if len(parts) > 3:
                raise ValueError(
                    f"{file_path} 第 {line_no} 行多于三列，"
                    f"应为「间隔毫秒 按键 [按住毫秒]」: {line!r}"
                )

            current_time += interval
            notes.append(Note(current_time, keys, line_no, hold))

    _clamp_holds(notes)
    return notes
