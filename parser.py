from collections import namedtuple

# 一个音符：time = 距离开始演奏的毫秒数，keys = 需要同时按下的键，line = 曲谱中的真实行号
Note = namedtuple("Note", ["time", "keys", "line"])


def parse(file_path, start_line=1):
    """
    解析乐谱文件，返回 Note(time, keys, line) 的列表

    file_path: 乐谱文件路径
    start_line: 从第几行开始演奏（1 为第一行，行号与文本编辑器显示的一致）

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
                    f"{file_path} 第 {line_no} 行格式错误，应为「间隔毫秒 按键」: {line!r}"
                )

            keys = list(parts[1]) if len(parts) >= 2 else []

            current_time += interval
            notes.append(Note(current_time, keys, line_no))

    return notes
