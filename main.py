import os
import re
from parser import parse
from player import play, FINISHED

# 无论从哪个目录启动，都基于本文件所在位置找 scores/，不再依赖当前工作目录
SCORES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores")


def choose_song():
    """
    列出 scores/ 目录下的曲谱供用户选择，返回曲谱的完整路径。
    """
    if not os.path.isdir(SCORES_DIR):
        raise SystemExit(f"未找到曲谱目录：{SCORES_DIR}")

    files = sorted(
        f for f in os.listdir(SCORES_DIR)
        if f.lower().endswith(".txt") and os.path.isfile(os.path.join(SCORES_DIR, f))
    )

    if not files:
        raise SystemExit(f"曲谱目录下没有 .txt 曲谱：{SCORES_DIR}")

    print("可用乐谱：")
    for i, f in enumerate(files, start=1):
        print(f"  {i}. {os.path.splitext(f)[0]}")

    while True:
        raw = input(f"选择编号 (1-{len(files)}，q 退出): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            raise SystemExit("已退出")
        if raw.isdigit() and 1 <= int(raw) <= len(files):
            return os.path.join(SCORES_DIR, files[int(raw) - 1])
        print(f"  无效输入，请输入 1-{len(files)} 之间的编号。")


def _prompt_int(prompt, default, min_value=1):
    """读取整数，直接回车用默认值，非法输入重新询问。"""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("  请输入整数。")
            continue
        if value < min_value:
            print(f"  不能小于 {min_value}。")
            continue
        return value


def _prompt_float(prompt, default, min_value=0.01):
    """读取浮点数（倍速），直接回车用默认值，非法输入重新询问。"""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("  请输入数字，例如 1.5。")
            continue
        if value < min_value:
            print(f"  倍速必须大于 {min_value}，否则会越弹越慢。")
            continue
        return value


def parse_default_speed(filepath):
    """
    从乐谱文件第一行解析默认倍速。
    格式: #1.9倍速
    如果读不到文件或解析失败，返回默认值 1.0
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            # 匹配格式 #1.9倍速 或 #2.0倍速 等
            match = re.match(r'#(\d+\.?\d*)倍速', first_line)
            if match:
                return float(match.group(1))
            else:
                return 1.0
    except (FileNotFoundError, IOError):
        return 1.0
    except ValueError:
        return 1.0


def main():
    # 循环的意义：暂停时按 P 中止演奏后会回到这里，重新选曲
    while True:
        song = choose_song()
        start_line = _prompt_int("输入起始行号 (默认为1): ", 1)
        notes = parse(song, start_line)

        if not notes:
            print(f"从第 {start_line} 行起没有可演奏的音符，请换一个起始行号。\n")
            continue

        # 获取第一个音符的时间作为起始时间
        start_time = notes[0][0]

        # 读取乐谱中默认的倍速
        default_speed = parse_default_speed(song)
        speed = _prompt_float(f"输入倍速 (默认为{default_speed}): ", default_speed)

        print(f"共 {len(notes)} 个音符，起始于第 {notes[0].line} 行，倍速 {speed}")

        # 提示必须在开始演奏之前给出：play() 会阻塞等待 F8
        input("打开原神并装备琴，按回车准备开始（F8 开始，空格暂停）")

        if play(notes, speed, start_time, start_line) == FINISHED:
            break

        # 用户暂停后按 P：回到选曲界面
        print("\n已返回选曲界面。\n")


if __name__ == "__main__":
    main()
