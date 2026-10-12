"""任务执行引擎：**进程内**加载并调用工具脚本的 main()，把 stdout 实时喂给日志视图。

为什么不用子进程：
  · 打包成 exe 后 sys.executable 就是 exe 自己，跑不了 .py 脚本；
  · 进程内调用对开发期和打包后是同一套代码，行为一致；
  · 拿到的异常栈也是完整的，便于定位。

代价：脚本的 stdout 是**进程级**重定向，所以同一时刻只允许跑一个任务（单飞锁）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from . import paths

# 行 → 日志级别的启发式判定
_ERR_MARKS = ("Traceback (most recent call last)", "Error:", "error:", "Exception",
              "!! ", "失败", "找不到")
_WARN_MARKS = ("⚠", "警告", "可疑", "待确认", "无法", "超出", "保留在")
_OK_MARKS = ("已写出", "完成", "成功", "OK", "就绪", "已移入", "产物")


def guess_level(line: str) -> str:
    s = line.strip()
    if not s:
        return "dim"
    for m in _ERR_MARKS:
        if m in s:
            return "err"
    for m in _WARN_MARKS:
        if m in s:
            return "warn"
    for m in _OK_MARKS:
        if m in s:
            return "ok"
    if s.startswith("===") or s.startswith("---"):
        return "info"
    return "dim"


class _LineWriter(io.TextIOBase):
    """把 print 的碎片拼成整行再 emit。"""

    def __init__(self, emit: Callable[[str, str], None]):
        super().__init__()
        self._emit = emit
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line.rstrip("\r"), guess_level(line))
        return len(s)

    def flush(self):
        if self._buf:
            self._emit(self._buf.rstrip("\r"), guess_level(self._buf))
            self._buf = ""


class Runner:
    """单飞任务执行器。emit 会被切回 UI 线程，页面可以放心直接改控件。"""

    def __init__(self, ui, log, on_state: Callable[[bool], None] | None = None):
        self.ui = ui
        self.log = log
        self.on_state = on_state
        self._busy = threading.Event()
        self._title = ""
        self._started = 0.0

    # ---- 状态 ----
    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    @property
    def title(self) -> str:
        return self._title

    # ---- 输出 ----
    def emit(self, line: str, level: str = "dim") -> None:
        """线程安全：切到 UI 线程再写控件。"""
        try:
            self.ui.after(0, lambda: self.log.append(line, level))
        except Exception:
            try:
                self.log.append(line, level)
            except Exception:
                pass

    def emit_now(self, line: str, level: str = "dim") -> None:
        self.log.append(line, level)

    # ---- 执行 ----
    def run(self, title: str, fn: Callable[[], object]) -> bool:
        if self.busy:
            self.emit(f"[忙] 已有任务在跑：{self._title}，请等它结束。", "warn")
            return False
        self._busy.set()
        self._title = title
        self._started = time.time()
        if self.on_state:
            try:
                self.on_state(True)
            except Exception:
                pass
        threading.Thread(target=self._worker, args=(title, fn), daemon=True).start()
        return True

    def _worker(self, title: str, fn: Callable[[], object]) -> None:
        self.emit("", "dim")
        self.emit(f"=== {title} ===", "info")
        writer = _LineWriter(self.emit)
        result = None
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                result = fn()
        except SystemExit as e:
            result = getattr(e, "code", 0)
        except Exception:
            for ln in traceback.format_exc().rstrip().splitlines():
                self.emit(ln, "err")
            result = -1
        finally:
            writer.flush()
        dt = time.time() - self._started
        if result in (0, None) and result is not False:
            self.emit(f"完成，用时 {dt:.1f} 秒", "ok")
        elif result is False:
            self.emit(f"未完成，用时 {dt:.1f} 秒", "warn")
        else:
            self.emit(f"结束（返回 {result!r}），用时 {dt:.1f} 秒", "warn")
        self._save_log(title)
        self._busy.clear()
        if self.on_state:
            try:
                self.ui.after(0, lambda: self.on_state(False))
            except Exception:
                pass

    def _save_log(self, title: str) -> None:
        """把本次运行日志落盘。文件名带秒级时间戳，正常不会撞已有文件；
        仍走 paths.write_text，以免受限环境下覆盖写被拒。"""
        try:
            p = Path(paths.LOG_DIR)
            p.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in title)[:40]
            paths.write_text(p / f"{stamp}-{safe}.log", self.log.get_text())
        except Exception:
            pass


# --------------------------------------------------------------------------
# 脚本加载与调用
# --------------------------------------------------------------------------

_module_cache: dict[str, object] = {}


def load_module(path: Path):
    """就地加载一个 .py 为模块（不复制、不改动它）。"""
    key = str(Path(path).resolve())
    if key in _module_cache:
        return _module_cache[key]
    name = f"_fw_{Path(path).stem}_{abs(hash(key)) % 100000}"
    spec = importlib.util.spec_from_file_location(name, key)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载脚本：{key}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # ★ 必须先注册：否则 @dataclass 解析注解会崩
    added = str(Path(path).parent) not in sys.path
    if added:
        sys.path.insert(0, str(Path(path).parent))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    finally:
        if added:
            try:
                sys.path.remove(str(Path(path).parent))
            except ValueError:
                pass
    _module_cache[key] = mod
    return mod


def call_main(mod, argv: list[str]):
    """调用脚本的 main()：能收 argv 就传，不能收就临时改 sys.argv。"""
    fn = getattr(mod, "main", None)
    if fn is None:
        raise AttributeError(f"{getattr(mod, '__file__', mod)} 里没有 main()")
    old_argv = sys.argv
    sys.argv = [str(getattr(mod, "__file__", "script"))] + [str(a) for a in argv]
    try:
        try:
            params = list(inspect.signature(fn).parameters.values())
            positional = [p for p in params
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            required = [p for p in positional if p.default is p.empty]
        except (TypeError, ValueError):
            positional, required = [], []
        if required:
            return fn([str(a) for a in argv])
        if positional:
            return fn([str(a) for a in argv])
        return fn()
    finally:
        sys.argv = old_argv


def run_script(script_path: Path, argv: list[str]) -> int:
    """加载 + 调用，返回退出码（0 视为成功）。"""
    mod = load_module(script_path)
    rc = call_main(mod, argv)
    if rc is None:
        return 0
    try:
        return int(rc)
    except Exception:
        return 0 if rc is False else 1


def preflight(script_path: Path | None) -> str:
    """跑之前的自检：脚本在不在、能不能加载。返回空串表示没问题。"""
    if script_path is None:
        return "找不到工具脚本。请在「设置」里指定 获取谱子 目录。"
    if not Path(script_path).is_file():
        return f"脚本不存在：{script_path}"
    return ""
