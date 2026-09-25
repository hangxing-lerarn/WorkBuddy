import re

#用于将有特定规律的人类简体乐谱转化成机器谱
def process_file(input_filename='正规化后', output_filename='机器谱的阶段性成果.txt'):
    try:
        with open(input_filename, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"错误：未在同目录下找到文件《{input_filename}》")
        return
    except Exception as e:
        print(f"读取文件时出错: {e}")
        return

    # 去除换行符，将所有内容合并为一行连续文本
    content = content.replace('\n', '').replace('\r', '')

    # 定义正则模式：匹配括号内的字母（如(CD)）或单个字母（如G）或中点（·）
    pattern = r'\([A-Z]+\)|[A-Z]|·'
    units = re.findall(pattern, content)

    # 用于收集所有输出行
    output_lines = []

    for unit in units:
        if unit == '·':
            # 空白单位，仅输出 90
            output_lines.append("90")
        elif unit.startswith('('):
            # 括号单位，去掉括号并转小写
            letters = unit[1:-1].lower()
            if len(letters) == 1:
                output_lines.append(f"90 {letters}")
            elif len(letters) == 2:
                output_lines.append(f"90 {letters}")
            else:  # 三个或更多字母
                output_lines.append(f"90 {letters}")
        else:
            # 单个字母，转小写
            letter = unit.lower()
            output_lines.append(f"90 {letter}")

    # 将所有行写入文件（覆盖模式）
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        print(f"转换完成，结果已保存到《{output_filename}》")
    except Exception as e:
        print(f"写入文件时出错: {e}")


if __name__ == "__main__":
    process_file()