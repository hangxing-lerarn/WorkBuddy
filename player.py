import keyboard
import time

# play() 的返回值
FINISHED = "finished"  # 整首弹完
ABORTED = "aborted"    # 暂停时按 P，中止演奏并返回选曲界面

# 曲谱没写第三列（或写了 0）时的按键按住时长，毫秒。
# 与 parser.DEFAULT_HOLD_MS 保持一致。
DEFAULT_HOLD_MS = 50


def play(notes, speed=1.0, start_time=0, start_line=1, start_delay=2.0):
    """
    播放音符序列，返回 FINISHED（弹完）或 ABORTED（暂停时按 P 中止）。

    notes:       parse() 返回的音符列表。每个音符的按住时长取 note.hold，
                 为 0 时回退到 DEFAULT_HOLD_MS；休止行（没有按键）不占时间，
                 只是把时间轴往后推。
    speed:       倍速，实际间隔 = 毫秒 / speed，按住时长同样 ÷ speed
    start_time:  起始时间基准（保留参数，当前由内部计时决定）
    start_line:  起始行号，仅在传入旧式 (时间, 按键) 二元组时用于推算行号
    start_delay: 按下 F8 之后的缓冲秒数，留出时间把焦点交给游戏窗口

    热键：F8 开始 / 继续，空格 暂停，暂停后按 P 中止并返回选曲界面
    """
    print(f"按 F8 开始演奏（按下后缓冲 {start_delay:g} 秒）")
    keyboard.wait('f8')

    # 起奏缓冲：等够时间再开始计时，缓冲区不计入音符间隔
    if start_delay > 0:
        print(f"缓冲中... {start_delay:g} 秒后开始演奏")
        time.sleep(start_delay)

    start = time.time()
    paused = False
    last_space_state = False  # 用于检测空格边缘触发

    for i, note in enumerate(notes):
        t, keys = note[0], note[1]
        # 用解析阶段记录的真实行号；兼容旧的 (时间, 按键) 二元组写法
        current_line = note[2] if len(note) >= 3 else start_line + i
        # 检测空格按下，触发暂停
        if keyboard.is_pressed('space') and not last_space_state:
            if not paused:  # 只有未暂停时才触发暂停
                paused = True
                print(f"第 {current_line} 行暂停中... 按 F8 继续，按 P 返回选曲")
            last_space_state = True
        if not keyboard.is_pressed('space'):
            last_space_state = False

        # 暂停循环：F8 继续播放，P 中止演奏返回选曲
        while paused:
            if keyboard.is_pressed('p'):
                print(f"已在第 {current_line} 行中止演奏，返回选曲界面")
                return ABORTED
            if keyboard.is_pressed('f8'):
                paused = False
                print(f"从第 {current_line} 行继续播放")
                start = time.time() - t / 1000 / speed
                break
            time.sleep(0.05)

        # 计算播放时间
        target_time = t / 1000 / speed
        wait_time = target_time - (time.time() - start)
        if wait_time > 0:
            time.sleep(wait_time)

        print(f"第 {current_line} 行正在弹奏: {keys}")
        # 只按实际存在的按键：休止行没有键，按 0 个键再白睡 DEFAULT_HOLD_MS
        # 纯粹是浪费时间（还会吃掉给后续音符留的余量）。时间轴本来由上面的
        # 绝对时间 target_time 决定，跳过它不会让曲子变快。
        if keys:
            for k in keys:
                keyboard.press(k)  # 按下按键
            # 按住时长：曲谱第三列给了就用它（parser 已按「到下一个发声行的间隔」
            # 钳制过，保证不会把后面的音符挤晚），没给就用默认值
            hold_ms = note[3] if len(note) >= 4 and note[3] > 0 else DEFAULT_HOLD_MS
            time.sleep(hold_ms / 1000 / speed)
            for k in keys:
                keyboard.release(k)  # 释放按键

    return FINISHED