"""工具链适配：给四个脚本 + 五个辅助工具生成正确的命令行。

这一层只做「界面输入 → argv」和「文件 → 界面显示」的翻译，不碰脚本内部。

⚠️ 两条重要事实（都已实测确认，别照直觉改）：
  1. `jianpu_to_score.py` **没有 --head**：调号/拍号/BPM 来自简谱 txt 的**首行**，
     唯一的覆盖口是 `--bpm`。所以「手动填页眉」= 在缓存目录写一份**改过首行的副本**
     再喂给它 —— 原简谱文件一个字都不动。
  2. `midi_to_score.py` 的**批量模式目录写死在仓库**（change_base/no|yes、scores/）。
     应用侧因此自己遍历队列，用**单文件模式 + 显式 -o** 落到应用数据目录。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import paths

# --------------------------------------------------------------------------
# 页眉（简谱首行）
# --------------------------------------------------------------------------

HEADER_RE = re.compile(
    r"^\s*(\d)\s*=\s*([A-Ga-g])\s*([#b]?)\s+(\d+)\s*/\s*(\d+)\s+(\d{1,3})\s*$")

TEMPO_LO, TEMPO_HI = 20, 320


def _norm(line: str) -> str:
    return (line.replace("＝", "=").replace("／", "/")
            .replace("　", " ").strip())


def parse_header(text: str) -> dict:
    """解析 `1=C 4/4 80`。可解析则 ok=True。"""
    m = HEADER_RE.match(_norm(text))
    if not m:
        return {"ok": False, "raw": text.strip()}
    key = m.group(2).upper() + m.group(3)
    bpm = int(m.group(6))
    return {
        "ok": True,
        "diatonic": int(m.group(1)),
        "key": key,
        "beats": int(m.group(4)),
        "beat_unit": int(m.group(5)),
        "bpm": bpm,
        "tempo_ok": TEMPO_LO <= bpm <= TEMPO_HI,
        "raw": text.strip(),
    }


def format_header(key: str, beats: int, bpm: int, beat_unit: int = 4) -> str:
    return f"1={key} {beats}/{beat_unit} {bpm}"


def read_jianpu_header(path: Path) -> dict:
    """读简谱文件首行 → 页眉字典。读不到就返回 ok=False（调用方给默认值）。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for _ in range(6):
                line = f.readline()
                if not line:
                    break
                if _norm(line):
                    got = parse_header(line)
                    if got["ok"]:
                        return got
                    break
    except Exception as e:
        return {"ok": False, "raw": "", "error": str(e)}
    return {"ok": False, "raw": ""}


def header_path_for(src: Path, header_line: str) -> Path:
    """把改过首行的副本写到缓存目录，返回副本路径。原文件绝不改动。"""
    work = Path(paths.WORK_DIR)
    work.mkdir(parents=True, exist_ok=True)
    dst = work / f"{src.stem}.head-override.txt"
    raw = src.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    body = raw[1:] if raw else []
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(header_line.rstrip("\n") + "\n")
        for ln in body:
            f.write(ln if ln.endswith("\n") else ln + "\n")
    return dst


def sibling_overlay(path: Path) -> Path | None:
    """找同名对声部：`X（旋律）.txt` ↔ `X（伴奏）.txt`。"""
    name = path.name
    for a, b in (("（旋律）", "（伴奏）"), ("（伴奏）", "（旋律）"),
                 ("(旋律)", "(伴奏)"), ("(伴奏)", "(旋律)")):
        if a in name:
            cand = path.with_name(name.replace(a, b))
            if cand.is_file():
                return cand
    return None


# --------------------------------------------------------------------------
# 目录列举
# --------------------------------------------------------------------------


def list_files(folder: Path, exts: tuple[str, ...]) -> list[Path]:
    try:
        return sorted(
            p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in exts
            and not p.name.startswith("~"))
    except Exception:
        return []


def list_scores() -> list[Path]:
    return list_files(paths.data_dirs()["scores"], (".txt",))


def list_jianpu() -> list[Path]:
    return list_files(paths.data_dirs()["jianpu"], (".txt",))


def list_midis() -> list[Path]:
    return list_files(paths.data_dirs()["no"], (".mid", ".midi"))


# --------------------------------------------------------------------------
# 1) 简谱转机器谱
# --------------------------------------------------------------------------


def build_jianpu_argv(jianpu: Path, *, overlays: list[Path], out: Path,
                      bpm: int | None = None, hold: str = "own",
                      speed: float = 1.0, max_fold: int = 1,
                      force: bool = False, dry_run: bool = False) -> list[str]:
    argv = [str(jianpu)]
    for o in overlays:
        argv += ["--overlay", str(o)]
    argv += ["-o", str(out)]
    if bpm:
        argv += ["--bpm", str(bpm)]
    if hold and hold != "own":
        argv += ["--hold", hold]
    if speed and abs(speed - 1.0) > 1e-9:
        argv += ["--speed", f"{speed:g}"]
    if max_fold and max_fold != 1:
        argv += ["--max-fold", str(max_fold)]
    if force:
        argv.append("--force")
    if dry_run:
        argv.append("--dry-run")
    return argv


# --------------------------------------------------------------------------
# 2) MIDI 直接转（单文件模式 + 显式 -o）
# --------------------------------------------------------------------------


def build_midi_argv(midi: Path, out: Path, *, mode: str = "voicing",
                    hold: str = "none", hold_max: int | None = None,
                    max_voices: str = "auto", tonic: str = "auto",
                    max_octave_shift: int = 1,
                    extra: list[str] | None = None) -> list[str]:
    argv = [str(midi), "-o", str(out)]
    if mode and mode != "voicing":
        argv += ["--mode", mode]
    if hold and hold != "none":
        argv += ["--hold", hold]
        if hold_max:
            argv += ["--hold-max", str(hold_max)]
    if max_voices and max_voices != "auto":
        argv += ["--max-voices", str(max_voices)]
    if tonic and tonic != "auto":
        argv += ["--tonic", str(tonic)]
    if max_octave_shift and max_octave_shift != 1:
        argv += ["--max-octave-shift", str(max_octave_shift)]
    argv += list(extra or [])
    return argv


# --------------------------------------------------------------------------
# 3) 谱图识谱
# --------------------------------------------------------------------------


def build_ocr_argv(images: list[Path], *, out: Path, bass: Path | None = None,
                   head: str = "", score: Path | None = None,
                   extra: list[str] | None = None) -> list[str]:
    argv = [str(p) for p in images]
    argv += ["-o", str(out)]
    if bass:
        argv += ["--bass", str(bass)]
    if head.strip():
        argv += ["--head", head.strip()]
    if score:
        argv += ["--score", str(score)]
    argv += list(extra or [])
    return argv


def sort_pages(files: list[Path]) -> list[Path]:
    """按页序排：优先取文件名里的数字，取不到就按名字排。"""
    def key(p: Path):
        nums = re.findall(r"\d+", p.stem)
        return (int(nums[-1]) if nums else 10**9, p.name.lower())
    return sorted(files, key=key)


# --------------------------------------------------------------------------
# 4) 辅助工具（统一「工具」页驱动）
# --------------------------------------------------------------------------

TOOL_SPECS: dict[str, dict] = {
    "retime": {
        "label": "改时值 retime",
        "script": "retime.py",
        "hint": "把机器谱换一套速度/格长。--base 是「当初生成这首谱时的 BPM」，"
                "脚本会拿它跟头部注释里的 `N BPM` 核对，对不上直接报错。默认只试运行。",
        "fields": [
            {"key": "score", "arg": "", "label": "机器谱文件", "kind": "file",
             "root": "scores", "ext": (".txt",), "hint": "scores/ 下挑一个"},
            {"key": "base", "arg": "--base", "label": "--base 原速（BPM）",
             "kind": "text", "default": "", "required": True,
             "hint": "填当初生成时的 BPM，如 138；会与头部 `N BPM` 核对"},
            {"key": "tempo", "arg": "--tempo", "label": "--tempo 目标速度",
             "kind": "text", "default": "", "required": True,
             "hint": "单段写 `138`；分段写 `1=100,25=112,101=90`（小节号=BPM）"},
            {"key": "write", "arg": "--write", "label": "真正写回文件",
             "kind": "bool", "default": False},
        ],
    },
    "add_hold": {
        "label": "加按住 add_hold",
        "script": "add_hold.py",
        "hint": "按「到下一个发声行的间隔」给曲谱补上第三列按住时长。默认只试运行；"
                "已经人工维护过第三列的谱子会被跳过，要覆盖得勾 --force。",
        "fields": [
            {"key": "paths", "arg": "", "label": "谱子文件或目录", "kind": "file",
             "root": "scores", "ext": (".txt",), "hint": "留空 = 默认整个 scores/"},
            {"key": "gap", "arg": "--gap", "label": "--gap 松开余量(ms)", "kind": "text",
             "default": "10"},
            {"key": "hold_min", "arg": "--min", "label": "--min 按住下限(ms)",
             "kind": "text", "default": "50"},
            {"key": "hold_round", "arg": "--round", "label": "--round 取整(ms)",
             "kind": "text", "default": "", "hint": "留空 = 脚本默认"},
            {"key": "hold_max", "arg": "--max", "label": "--max 按住上限(ms)",
             "kind": "text", "default": "", "hint": "0 或留空 = 不设上限"},
            {"key": "force", "arg": "--force", "label": "覆盖已带第三列的谱子（--force）",
             "kind": "bool", "default": False},
            {"key": "write", "arg": "--write", "label": "真正写回文件",
             "kind": "bool", "default": False},
        ],
    },
    "letters": {
        "label": "字母谱转谱",
        "script": "字母谱转谱.py",
        "hint": "把键盘字母谱（zxcvbnm / asdfghj / qwertyu）转成机器谱。",
        "fields": [
            {"key": "src", "arg": "", "label": "字母谱源文件", "kind": "file",
             "root": "jianpu", "ext": (".txt",)},
            {"key": "dst", "arg": "", "label": "输出机器谱路径", "kind": "save",
             "root": "scores", "default_name": "字母谱转出.txt"},
            {"key": "bpm", "arg": "--bpm", "label": "--bpm", "kind": "text",
             "default": "110"},
            {"key": "title", "arg": "--title", "label": "--title 曲名",
             "kind": "text", "default": ""},
        ],
    },
    "letters_audit": {
        "label": "字母谱对账",
        "script": "字母谱对账.py",
        "hint": "用独立解码器逐事件比对「字母谱原文」与「产物曲谱」，两边一致才放行。",
        "fields": [
            {"key": "src", "arg": "", "label": "字母谱原文", "kind": "file",
             "root": "jianpu", "ext": (".txt",)},
            {"key": "dst", "arg": "", "label": "产物曲谱", "kind": "file",
             "root": "scores", "ext": (".txt",)},
        ],
    },
    "verify": {
        "label": "原谱独立复核",
        "script": "verify_original.py",
        "hint": "只读产物字节、独立推一遍约束（行语法/键位/按住/编码…）。留空则复核 scores/*-原创.txt。",
        "fields": [
            {"key": "paths", "arg": "", "label": "要复核的曲谱（可多选）",
             "kind": "multi", "root": "scores", "ext": (".txt",),
             "hint": "留空 = 全部 *-原创.txt"},
        ],
    },
}
TOOL_ORDER = list(TOOL_SPECS)


def build_tool_argv(spec: dict, values: dict, extra_text: str = "") -> list[str]:
    argv: list[str] = []
    for f in spec["fields"]:
        v = values.get(f["key"])
        if f["kind"] == "bool":
            if v:
                argv.append(f["arg"])
            continue
        if f["kind"] == "multi":
            for item in (v or []):
                if str(item).strip():
                    argv.append(str(item).strip())
            continue
        s = ("" if v is None else str(v)).strip()
        if not s:
            continue
        if f["arg"]:
            argv += [f["arg"], s]
        else:
            argv.append(s)
    if extra_text.strip():
        argv += extra_text.split()
    return argv


# --------------------------------------------------------------------------
# 输出与落盘
# --------------------------------------------------------------------------


def preview_out(stem: str, tag: str, ext: str = ".txt") -> Path:
    """转换产物的预览路径（先给用户看，点了保存才进数据目录）。"""
    d = Path(paths.PREVIEW_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stem}{tag}{ext}"


def ensure_parent(p: Path) -> Path:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    return Path(p)


def save_product(src: Path, dst_dir: Path, overwrite: bool = False) -> Path:
    """把预览产物存进数据目录。已有同名文件时**绝不覆盖**，改存 (2)。"""
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / Path(src).name
    if dst.exists() and not overwrite:
        i = 2
        while (dst_dir / f"{Path(src).stem}({i}){Path(src).suffix}").exists():
            i += 1
        dst = dst_dir / f"{Path(src).stem}({i}){Path(src).suffix}"
    shutil.copy2(src, dst)
    return dst


# --------------------------------------------------------------------------
# 列表里显示的摘要（只读头几行，够快）
# --------------------------------------------------------------------------


def _head_text(path: Path, n: int = 12) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            out = []
            for i, ln in enumerate(f):
                out.append(ln)
                if i >= n:
                    break
            return "".join(out)
    except Exception:
        return ""


def score_summary(path: Path) -> str:
    """机器谱摘要：速度 / BPM / 每格毫秒。读不到就返回空串。"""
    txt = _head_text(path, 12)
    if not txt:
        return ""
    bits = []
    m = re.search(r"^#\s*(\d+(?:\.\d+)?)\s*倍速", txt, re.M)
    if m and m.group(1) not in ("1", "1.0"):
        bits.append(f"{m.group(1)}× 倍速")
    m = re.search(r"(\d+)\s*BPM", txt)
    if m:
        bits.append(f"{m.group(1)} BPM")
    m = re.search(r"=\s*(\d+)\s*毫秒", txt)
    if m:
        bits.append(f"{m.group(1)}ms/格")
    m = re.search(r"每小节\s*(\d+)\s*格", txt)
    if m:
        bits.append(f"{m.group(1)} 格/小节")
    return " · ".join(bits)


def jianpu_summary(path: Path) -> str:
    got = read_head_line(path)
    if not got:
        return ""
    h = parse_header(got)
    if not h["ok"]:
        return got
    extra = "" if h.get("tempo_ok", True) else "  ⚠ 超出合理范围"
    return f"{h['key']} 调 · {h['beats']}/4 · {h['bpm']} BPM{extra}"


def read_head_line(path: Path) -> str:
    """取简谱文件第一行非空内容（原样，不解析）。"""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for _ in range(6):
                ln = f.readline()
                if not ln:
                    break
                if ln.strip():
                    return ln.strip()
    except Exception:
        pass
    return ""


def midi_summary(path: Path) -> str:
    try:
        return f"{path.stat().st_size / 1024:.0f} KB"
    except Exception:
        return ""
