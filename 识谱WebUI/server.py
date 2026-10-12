#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""识谱 WebUI —— 后端服务（前端交互 / 后端处理数据）

零第三方依赖：只用 Python 标准库。唯一例外是「尺度归一化」需要 PIL，
缺失时自动降级（前端会显示提示），其余功能不受影响。

它包装的是 `获取谱子/简谱识谱/识谱.py`：

    前端 POST 图片(raw body) ──► 后端落盘 .work/<uid>/
    前端 POST /api/run       ──► 后端组装命令行 → 起子进程 → stdout 逐行入队
    前端 GET  /api/poll      ──► 取增量日志（+ 结束后一次性返回自检结果与产物文本）
    前端 GET  /api/artifact  ──► 下载产物
    前端 POST /api/save      ──► 把产物写进仓库的 简谱/ 与 scores/（带覆盖检查）

不修改识谱.py、不修改既有 简谱/*.txt 与 scores/*.txt。
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote

# --------------------------------------------------------------------------
# 路径契约（与识谱.py 的相对结构保持一致，不硬编码用户目录）
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
REPO = HERE.parent                                   # original-guitar-tool-master
TOOL_DIR = REPO / "获取谱子" / "简谱识谱"
TOOL = TOOL_DIR / "识谱.py"
IMPORTABLE = (TOOL_DIR / "imgio.py", TOOL_DIR / "字模.json",
              REPO / "获取谱子" / "jianpu_to_score.py")
JIANPU_DIR = REPO / "简谱"
SCORES_DIR = REPO / "scores"

OUT_DIR = HERE / "out"                               # 每次转写的产物（历史）
WORK_DIR = HERE / ".work"                            # 上传的原图 + 缩放中间件
INDEX = HERE / "index.html"

HOST = os.environ.get("SHIPU_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHIPU_PORT", "8760"))
MAX_UPLOAD = 64 * 1024 * 1024
AUTO_WIDTH = 1479                                    # 目标宽度：3169 × (21/45) ≈ 1479
                                                     # ⇒ 缩放后数字行高回到标定的 21px
                                                     # 实测像素级敏感：1480 会得到字高 22px

# --------------------------------------------------------------------------
# 解释器选择
# ⚠️ Store 版的 App Execution Alias（%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe）
#    在子进程上下文里有概率起不来（0xC0000142 STATUS_DLL_INIT_FAILED），
#    而且 Popen 杀它只杀转发器、真身会残留并占住端口。
#    ⇒ 每个候选都必须**实测一次**才采用。
# --------------------------------------------------------------------------
_PY: str | None = None
_BAD: set[str] = set()                               # 已被证实会抽风的解释器


def _py_ok(exe: str) -> bool:
    try:
        r = subprocess.run([exe, "-c", "import sys"],
                           capture_output=True, timeout=25)
        return r.returncode == 0
    except Exception:                                # noqa: BLE001
        return False


def ensure_py() -> str:
    """拿到一个**此刻确实能启动**的解释器；刚抽风过的会被拉黑并换下一个。"""
    global _PY
    p = get_py()
    if _py_ok(p):
        return p
    _BAD.add(p.lower())
    _PY = None
    return get_py()


def get_py() -> str:
    global _PY
    if _PY and _PY.lower() not in _BAD:
        return _PY
    import shutil as _sh
    cands: list[str] = []
    if os.environ.get("SHIPU_PY"):
        cands.append(os.environ["SHIPU_PY"])
    cands.append(sys.executable)                     # 服务自己的解释器，通常最稳
    for n in ("python", "python3", "py"):
        w = _sh.which(n)
        if w:
            cands.append(w)
    la = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    for n in ("python.exe", "python3.exe"):
        if (la / n).exists():
            cands.append(str(la / n))
    seen: set[str] = set()
    for c in cands:
        if not c:
            continue
        k = str(c).lower()
        if k in seen or k in _BAD:
            continue
        seen.add(k)
        if _py_ok(c):
            _PY = c
            return c
    _PY = sys.executable
    return _PY


_ENV_CACHE: dict | None = None


def probe_env(force: bool = False) -> dict:
    """报告当前解释器能力 + 依赖文件是否齐备（前端顶栏会显示）。结果缓存。"""
    global _ENV_CACHE
    if _ENV_CACHE and not force:
        return _ENV_CACHE
    PY = get_py()
    code = ("import sys,json;"
            "import importlib.util as u;"
            "print(json.dumps({'v':'%d.%d.%d'%sys.version_info[:3],"
            "'pil':u.find_spec('PIL') is not None}))")
    ver, pil = "?", False
    try:
        r = subprocess.run([PY, "-c", code], capture_output=True, timeout=25)
        d = json.loads(r.stdout.decode("utf-8", "replace").strip() or "{}")
        ver, pil = d.get("v", "?"), bool(d.get("pil"))
    except Exception:                                # noqa: BLE001
        pass
    missing = [str(p.relative_to(REPO)) for p in (TOOL, *IMPORTABLE) if not p.exists()]
    # 尺度归一化跑在**本服务进程内**，所以要看服务自己有没有 PIL，
    # 而不是看跑识谱.py 的那个解释器（后者纯标准库，不需要 PIL）。
    try:
        import PIL                                   # noqa: F401
        server_pil = True
    except Exception:                                # noqa: BLE001
        server_pil = False
    _ENV_CACHE = {
        "python": PY,
        "python_version": ver,
        "pil": pil,
        "server_pil": server_pil,
        "repo": str(REPO),
        "tool": str(TOOL),
        "missing": missing,
        "ready": not missing,
        "auto_width": AUTO_WIDTH,
        "out_dir": str(OUT_DIR),
        "jianpu_dir": str(JIANPU_DIR),
        "scores_dir": str(SCORES_DIR),
    }
    return _ENV_CACHE


# --------------------------------------------------------------------------
# 工位
# --------------------------------------------------------------------------
LOCK = threading.Lock()
UPLOADS: dict[str, dict] = {}                        # uid -> {name, path, bytes, w, h}
JOBS: dict[str, dict] = {}                           # jid -> job


def new_job(**kw) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid,
        "status": "running",                         # running | done | error | cancelled
        "lines": [],
        "result": None,
        "proc": None,
        "t0": time.time(),
        "cmd": [],
        "jobdir": None,
        **kw,
    }
    with LOCK:
        JOBS[jid] = job
    return job


def jlog(job: dict, line: str) -> None:
    with LOCK:
        job["lines"].append(line.rstrip("\r\n"))


def safe_name(name: str) -> str:
    name = unquote(name or "image.png")
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip() or "image.png"
    return name[:120]


def png_size(data: bytes):
    """从 PNG 的 IHDR 直接读宽高（源图基本都是 PNG，免依赖、免解码）。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None


# --------------------------------------------------------------------------
# 尺度归一化：识谱.py 的几何常量标定在「数字行高 21px」
# 但工具内部只做 S = 行高/21 的等比缩放，并未把输入图归一化到标定尺度。
# 源扫描件常见 3169×4481（字高 45px，S≈2.14），缩到宽 ~1480 后更稳。
# --------------------------------------------------------------------------
def normalize_images(paths: list[Path], mode: str, width: int, dst: Path):
    """返回 (处理后的路径列表, 说明文字)。mode: off | auto | custom"""
    if mode == "off" or not paths:
        return paths, "未做尺度归一化（原图直出）"
    try:
        from PIL import Image                             # noqa: PLC0415
    except ImportError:
        return paths, "⚠ 当前解释器没有 PIL，尺度归一化被跳过（原图直出）"

    target = AUTO_WIDTH if mode == "auto" else max(400, int(width))
    out, notes = [], []
    dst.mkdir(parents=True, exist_ok=True)
    for p in paths:
        try:
            im = Image.open(p)
            w, h = im.size
            if w <= target:
                out.append(p)
                notes.append(f"{p.name}: {w}px 已达标，未缩")
                continue
            im = im.convert("RGB")                        # 保持彩色！tint 靠它清歌词
            k = target / w
            nw, nh = max(1, round(w * k)), max(1, round(h * k))
            q = dst / (p.stem + ".png")
            im.resize((nw, nh), Image.LANCZOS).save(q)
            out.append(q)
            notes.append(f"{p.name}: {w}×{h} → {nw}×{nh} (k={k:.4f})")
        except Exception as e:                            # noqa: BLE001
            out.append(p)
            notes.append(f"{p.name}: 归一化失败({e})，用原图")
    return out, "尺度归一化 " + "; ".join(notes)


# --------------------------------------------------------------------------
# 自检解析
# --------------------------------------------------------------------------
RE_OK = re.compile(r"每小节拍数 = (\d+)（(\d+) 个小节·声部，0 错）")
RE_BAD = re.compile(r"拍数不对的小节 (\d+)/(\d+)")
RE_HEAD = re.compile(r"首行 (.+?)；旋律 (\d+) 系统 / 伴奏 (\d+) 系统")
RE_TIME = re.compile(r"总用时 ([\d.]+)s")
RE_SCALE = re.compile(r"字高 (\d+)px → 尺度 S=([\d.]+)")
RE_SYS = re.compile(r"第(\d+)系统 y(\d+)-(\d+)\s+小节线 x=\[([^\]]*)\] → (\d+) 小节")

# --------------------------------------------------------------------------
# 产物级静态预检
# ⚠️ jianpu_to_score.py 是 **fail-fast** 的：转换失败时只报**最前面**那一处，
#    剩下的错误要改完才暴露（本次实测：改掉第 3 行的休止和弦后，才冒出第 33 行
#    的 `~` 不一致）。这里把两类硬错误一次列全，省掉「改一处、再跑一次」的循环。
# --------------------------------------------------------------------------
_TIE_TOK = re.compile(r"~?\([^)]*\)[/*.]*|[^\s|]+")
_TIE_SUF = re.compile(r"[/*.]+$")
_CHORD = re.compile(r"\(([^)]*)\)")
_CHORD_REST = re.compile(r"(?:^|\s)(?:0|·)(?:\s|$)")


def _tie_head(tok: str) -> str:
    """去掉 `~` 前缀与时值后缀，返回音组字符串（口径与 jianpu_to_score 一致）。"""
    t = tok.lstrip("~")
    if t.startswith("("):
        end = t.find(")")
        return t[1:end].strip() if end >= 0 else t
    return _TIE_SUF.sub("", t)


def scan_products(text: str, tag: str) -> list[str]:
    """扫描产物文本，列出会让 jianpu_to_score 直接失败的两类硬错误。

    ⚠️ `prev`（前件）必须**跨行延续**：一条系统 = 一行，而 `~` 连音线**允许跨系统**，
    换行处甚至可能夹着段落标记 `@N`。按行重置 prev 会把合法的跨行 tie 误报成
    「行首 ~ 缺少前件」—— 实测《如果可以》4 页被误报 3 处，而 jianpu_to_score
    全部接受、exit 0（真正的假警报）。段落标记行照旧跳过，但**不清空 prev**。
    """
    out: list[str] = []
    prev = None
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("1=") or s.startswith("@"):
            continue
        for m in _CHORD.finditer(s):
            inner = m.group(1).strip()
            if _CHORD_REST.search(inner):
                out.append(f"{tag} 第 {lineno} 行：和弦 ({inner}) 里含休止 —— "
                           f"休止没有「同时按下」可言，需拆成普通音符")
        for tok in _TIE_TOK.findall(s):
            if tok == "|":
                continue
            if tok.startswith("~"):
                if prev is None:
                    out.append(f"{tag} 第 {lineno} 行：{tok} 前面一个音都没有，"
                               f"`~` 没有可接的前件")
                elif _tie_head(prev) != _tie_head(tok):
                    out.append(f"{tag} 第 {lineno} 行：{tok} 与前一音 {prev} 音组不同"
                               f"（`~` 只把同一组音接起来）")
            prev = tok
    return out


def parse_selfcheck(text: str) -> dict:
    """把识谱.py 的自检输出解析成结构化结果（只读正则，不改工具行为）。"""
    r: dict = {"bars": None, "bad": None, "head": None, "seconds": None,
               "scale": None, "systems": None, "ok": None,
               "warns": 0, "pages": []}
    m = RE_OK.search(text)
    if m:
        r["bars"], r["bad"], r["ok"] = int(m.group(2)), 0, True
    m = RE_BAD.search(text)
    if m:
        r["bad"], r["bars"], r["ok"] = int(m.group(1)), int(m.group(2)), False
    m = RE_HEAD.search(text)
    if m:
        r["head"] = m.group(1)
        r["systems"] = {"mel": int(m.group(2)), "bas": int(m.group(3))}
    m = RE_TIME.search(text)
    if m:
        r["seconds"] = float(m.group(1))
    m = RE_SCALE.search(text)
    if m:
        r["scale"] = {"px": int(m.group(1)), "S": float(m.group(2))}
    for m in RE_SYS.finditer(text):
        r["pages"].append({"page": int(m.group(1)), "bars": int(m.group(5))})
    r["warns"] = len(re.findall(r"^\s*⚠", text, re.M))
    # 「需要人工核对的地方」—— 这是界面比裸跑命令行多出来的价值：
    # 拍数 ✗、连音线两端不一致（会让机器谱整链失败）、页眉没认出。
    issues: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("✗") or "解析失败" in s:
            issues.append(s)
        elif s.startswith("⚠") and ("页眉" in s or "连音" in s or "自相矛盾" in s):
            issues.append(s)
    seen: set[str] = set()
    r["issues"] = [x for x in issues if not (x in seen or seen.add(x))][:40]
    return r


# --------------------------------------------------------------------------
# 核心：跑识谱.py
# --------------------------------------------------------------------------
def run_job(job: dict, spec: dict) -> None:
    try:
        imgs = [UPLOADS[u]["path"] for u in spec["uploads"] if u in UPLOADS]
        if not imgs:
            raise RuntimeError("没有可用的图片")

        jobdir = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{job['id']}"
        jobdir.mkdir(parents=True, exist_ok=True)
        job["jobdir"] = jobdir
        mel = jobdir / "旋律.txt"
        bas = jobdir / "伴奏.txt"
        scr = jobdir / "机器谱.txt"

        srcs, note = normalize_images(imgs, spec.get("scaleMode", "off"),
                                      spec.get("scaleWidth", AUTO_WIDTH),
                                      WORK_DIR / job["id"])
        jlog(job, f"[前端] 曲名 {spec.get('title') or '(未填)'}")
        jlog(job, f"[前端] {note}")

        pyexe = ensure_py()
        cmd = [pyexe, str(TOOL), *[str(p) for p in srcs],
               "-o", str(mel), "--bass", str(bas)]
        if spec.get("head"):
            cmd += ["--head", spec["head"]]
        if spec.get("ghost", "off") != "off":
            cmd += ["--ghost-merge", spec["ghost"]]
        if spec.get("triplet"):
            cmd += ["--triplet-arc"]
        if spec.get("ink"):
            cmd += ["--ink", str(int(spec["ink"]))]
        if spec.get("genScore"):
            cmd += ["--score", str(scr)]

        job["cmd"] = cmd
        jlog(job, f"[后端] 解释器 {pyexe}")
        jlog(job, "[后端] " + subprocess.list2cmdline(cmd))
        jlog(job, "-" * 60)

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"            # 统一子进程输出编码，避免 cp936 混流
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            cmd, cwd=str(TOOL_DIR), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        job["proc"] = proc
        raw = []
        assert proc.stdout is not None
        for bline in proc.stdout:
            s = bline.decode("utf-8", "replace").rstrip("\r\n")
            raw.append(s)
            jlog(job, s)
        code = proc.wait()
        text = "\n".join(raw)
        try:                                          # 完整日志落盘，便于事后核对
            (jobdir / "运行日志.txt").write_text(text, encoding="utf-8")
        except Exception:                             # noqa: BLE001
            pass

        chk = parse_selfcheck(text)
        artifacts = {}
        for key, path in (("mel", mel), ("bas", bas), ("score", scr)):
            if path.exists():
                artifacts[key] = {"name": path.name, "text": path.read_text(encoding="utf-8")}

        # 产物级预检：把会让 jianpu_to_score 直接失败的两类硬错误一次列全
        issues = list(chk.get("issues") or [])
        for key, tag in (("mel", "旋律"), ("bas", "伴奏")):
            if key in artifacts:
                issues += scan_products(artifacts[key]["text"], tag)
        chk["issues"] = list(dict.fromkeys(issues))[:60]
        job["result"] = {
            "exit": code,
            "check": chk,
            "artifacts": artifacts,
            "jobdir": str(jobdir),
            "note": note,
            "cancelled": job["status"] == "cancelled",
        }
        if job["status"] != "cancelled":
            job["status"] = "done"
            jlog(job, f"[后端] 进程退出码 {code}"
                      f"（0 = 自检全绿；1 = 有 ✗ 或机器谱转换失败）")
    except Exception as e:                            # noqa: BLE001
        job["status"] = "error"
        job["result"] = {"exit": -1, "error": f"{type(e).__name__}: {e}",
                         "check": {}, "artifacts": {}, "jobdir": str(job.get("jobdir") or "")}
        jlog(job, f"[后端] ✗ 异常：{type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# 写回仓库（带覆盖检查 —— 绝不动别人已转好的谱）
# --------------------------------------------------------------------------
def save_to_repo(job: dict, title: str, force: bool = False) -> dict:
    res = job.get("result") or {}
    arts = res.get("artifacts") or {}
    if not arts:
        return {"ok": False, "error": "没有可写入的产物"}
    title = (title or "").strip() or "未命名"
    plan = []
    if "mel" in arts:
        plan.append((JIANPU_DIR / f"{title}（旋律）.txt", arts["mel"]["text"]))
    if "bas" in arts:
        plan.append((JIANPU_DIR / f"{title}（伴奏）.txt", arts["bas"]["text"]))
    if "score" in arts:
        plan.append((SCORES_DIR / f"{title}（简谱转）.txt", arts["score"]["text"]))

    clash = [str(p.name) for p, _ in plan if p.exists()] if not force else []
    if clash:
        return {"ok": False, "conflict": clash,
                "error": f"目标已存在：{'、'.join(clash)}（勾选「允许覆盖」后重试）"}
    written = []
    for p, text in plan:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(str(p.relative_to(REPO)))
    return {"ok": True, "written": written}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ShipuWebUI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                       # 静音默认访问日志
        pass

    # ---------- 帮手 ----------
    def _send(self, code: int, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self) -> dict:
        try:
            return json.loads(self.body().decode("utf-8")) or {}
        except Exception:                            # noqa: BLE001
            return {}

    # ---------- GET ----------
    def do_GET(self):                                # noqa: N802
        """⚠️ 一律包一层 try/except。

        处理函数里任何未捕获异常，socketserver 都会**直接关掉连接**、不回任何字节，
        浏览器只看得到 ERR_EMPTY_RESPONSE（「127.0.0.1 未发送任何数据」），
        用户完全无从判断哪里坏了。包住后至少回一个带正文的 500，
        并把 traceback 打到控制台（双击 .bat 的那个窗口里能直接看到）。
        """
        try:
            self._route_get()
        except Exception:                            # noqa: BLE001
            traceback.print_exc()
            self._fail_txt()

    def _fail_txt(self):
        try:
            self._send(500, "服务内部错误（详见控制台 traceback）".encode("utf-8"),
                       "text/plain; charset=utf-8")
        except Exception:                            # noqa: BLE001
            pass

    def _route_get(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            try:
                body = INDEX.read_bytes()
            except OSError as e:
                return self._send(500, f"读不到前端页面 {INDEX}：{e}".encode("utf-8"),
                                  "text/plain; charset=utf-8")
            return self._send(200, body, "text/html; charset=utf-8")

        if p == "/api/env":
            return self.send_json(probe_env())

        if p == "/api/poll":
            job = JOBS.get((q.get("job") or [""])[0])
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            start = int((q.get("from") or ["0"])[0])
            with LOCK:
                lines = job["lines"][start:]
                n = len(job["lines"])
                status = job["status"]
                result = job["result"] if status in ("done", "error", "cancelled") else None
            return self.send_json({"lines": lines, "from": n, "status": status,
                                   "result": result})

        if p == "/api/history":
            items = []
            if OUT_DIR.exists():
                for d in sorted(OUT_DIR.iterdir(), reverse=True):
                    if not d.is_dir():
                        continue
                    arts = sorted(f.name for f in d.glob("*.txt"))
                    items.append({"dir": d.name,
                                  "mtime": time.strftime("%Y-%m-%d %H:%M",
                                                         time.localtime(d.stat().st_mtime)),
                                  "artifacts": arts})
            return self.send_json({"items": items[:60]})

        if p == "/api/artifact":
            job = JOBS.get((q.get("job") or [""])[0])
            key = (q.get("key") or ["mel"])[0]
            if not job or not job.get("result"):
                return self.send_json({"error": "no such job"}, 404)
            a = (job["result"].get("artifacts") or {}).get(key)
            if not a:
                return self.send_json({"error": "no such artifact"}, 404)
            data = a["text"].encode("utf-8")
            # ⚠️ HTTP header 按 latin-1 编码，中文文件名必须 percent-encode，
            # 否则 send_header 抛 UnicodeEncodeError → 连接被静默掐断
            return self._send(200, data, "text/plain; charset=utf-8",
                              {"Content-Disposition":
                               f"attachment; filename*=UTF-8''{quote(a['name'])}"})

        if p == "/api/jobfile":
            job = JOBS.get((q.get("job") or [""])[0])
            key = (q.get("key") or ["mel"])[0]
            if not job or not job.get("result"):
                return self.send_json({"error": "no such job"}, 404)
            a = (job["result"].get("artifacts") or {}).get(key)
            if not a:
                return self.send_json({"error": "no such artifact"}, 404)
            return self.send_json({"path": str(Path(job["result"]["jobdir"]) / a["name"])})

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---------- POST ----------
    def do_POST(self):                               # noqa: N802
        try:                                         # 同上：别让异常变成静默断连
            self._route_post()
        except Exception:                            # noqa: BLE001
            traceback.print_exc()
            self._fail_txt()

    def _route_post(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p == "/api/upload":
            data = self.body()
            if not data:
                return self.send_json({"error": "空上传"}, 400)
            if len(data) > MAX_UPLOAD:
                return self.send_json({"error": "文件超过 64MB"}, 413)
            name = safe_name((q.get("name") or ["image.png"])[0])
            uid = uuid.uuid4().hex[:12]
            d = WORK_DIR / "uploads" / uid
            d.mkdir(parents=True, exist_ok=True)
            path = d / name
            path.write_bytes(data)
            w, h = png_size(data)
            UPLOADS[uid] = {"name": name, "path": path, "bytes": len(data), "w": w, "h": h}
            return self.send_json({"id": uid, "name": name, "bytes": len(data),
                                   "w": w, "h": h})

        if p == "/api/run":
            spec = self.json_body()
            if not spec.get("uploads"):
                return self.send_json({"error": "请先上传图片"}, 400)
            job = new_job(title=spec.get("title", ""), spec=spec)
            with LOCK:
                job["lines"].append("[后端] 任务已创建，正在启动…")
            t = threading.Thread(target=run_job, args=(job, spec), daemon=True)
            t.start()
            return self.send_json({"job": job["id"]})

        if p == "/api/cancel":
            job = JOBS.get((self.json_body().get("job") or ""))
            if not job:
                return self.send_json({"error": "no such job"}, 404)
            job["status"] = "cancelled"
            proc = job.get("proc")
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:                    # noqa: BLE001
                    pass
            jlog(job, "[后端] 已请求取消")
            return self.send_json({"ok": True})

        if p == "/api/save":
            b = self.json_body()
            job = JOBS.get(b.get("job") or "")
            if not job or not job.get("result"):
                return self.send_json({"ok": False, "error": "任务尚未完成"}, 400)
            r = save_to_repo(job, b.get("title") or job.get("title") or "",
                             bool(b.get("force")))
            return self.send_json(r)

        if p == "/api/open":
            b = self.json_body()
            target = b.get("path")
            if not target or not Path(target).exists():
                return self.send_json({"ok": False, "error": "路径不存在"}, 400)
            try:
                subprocess.Popen(["explorer", "/select,", str(Path(target))])
                return self.send_json({"ok": True})
            except Exception as e:                   # noqa: BLE001
                return self.send_json({"ok": False, "error": str(e)}, 500)

        return self._send(404, b"not found", "text/plain; charset=utf-8")


# --------------------------------------------------------------------------
# 端口占用自检 / 接管
#
# 为什么必须做：`ThreadingHTTPServer` 继承 `HTTPServer`，其 `allow_reuse_address = 1`
# （= SO_REUSEADDR）。Linux 上 SO_REUSEADDR **不允许**两个进程绑同一端口；Windows 上
# 却允许 —— 所以「上一次的 server.py 没退干净」时再双击一次 启动服务.bat，
# 新进程会**静默绑成功、一句错都不报**，而浏览器请求可能被那个旧实例应答。
# 旧实例若还在跑老代码或处于坏状态，页面就是 ERR_EMPTY_RESPONSE，用户完全无从判断。
# ⇒ 绑之前先探一次：
#     是我们自己的实例且健康 → 直接开页面、退出（不重复起服务）
#     是我们自己的实例但首页坏了 → 结束它、接管端口
#     是别的程序 → 报错让路，提示换端口
# --------------------------------------------------------------------------
def _probe(path: str, timeout: float = 1.5):
    """GET HOST:PORT 上的一个路径。返回 (status, body)；无人应答/非 HTTP → None。

    直接用 http.client，**不走环境变量里的 proxy** —— 本机回环没必要，
    而且沙箱/公司代理有可能把大响应掐断，导致误判「端口上没有服务」。
    """
    try:
        c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read(8192)
        c.close()
        return r.status, body
    except Exception:                                # noqa: BLE001
        return None


def _looks_like_shipu(body: bytes) -> bool:
    """`/api/env` 的 JSON 是否出自本工具（而不是恰好也占着这个端口的别的服务）。"""
    try:
        d = json.loads(body.decode("utf-8", "replace"))
        return isinstance(d, dict) and {"repo", "tool", "out_dir"} <= set(d)
    except Exception:                                # noqa: BLE001
        return False


def _port_pids() -> list[int]:
    """netstat 找出正在 LISTENING 本端口的全部 PID（Windows）。"""
    if os.name != "nt":
        return []
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                           capture_output=True, timeout=8)
        text = r.stdout.decode("utf-8", "replace")
    except Exception:                                # noqa: BLE001
        return []
    want = f":{PORT}"
    pids: set[int] = set()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 5 or not f[1].endswith(want):
            continue
        # 只看 LISTENING 行；state 列理论上恒为英文 LISTENING，
        # 保险起见再放一个「对端是 0.0.0.0:0 / *:*」的兜底判据
        if not (f[3].upper().startswith("LISTEN") or f[2] in ("0.0.0.0:0", "*:*")):
            continue
        try:
            pids.add(int(f[4]))
        except ValueError:
            pass
    return sorted(pids)


def _kill_pid(pid: int) -> bool:
    try:
        r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:                                # noqa: BLE001
        return False


def claim_port(url: str) -> int | None:
    """端口自检 + 接管。

    返回 0    → 已有一个**健康**实例在跑，本进程应直接退出（顺手把页面打开）；
    返回 1    → 端口被占且动不了，报错退出；
    返回 None → 端口确认可用，调用方继续 bind。
    """
    got = _probe("/api/env")
    if got is None:
        pids = _port_pids()
        if pids:
            print(f"  [错误] 端口 {PORT} 已被其它程序占用（PID "
                  f"{', '.join(map(str, pids))}），而且它不响应 HTTP。")
            print(f"         请先关掉它，或换端口：set SHIPU_PORT=8761 后重新双击 启动服务.bat")
            return 1
        return None                                  # 无人应答、也无人监听 → 放心绑

    status, body = got
    if not (isinstance(status, int) and 200 <= status < 300 and _looks_like_shipu(body)):
        pids = _port_pids()
        print(f"  [错误] 端口 {PORT} 已被别的程序占用（PID "
              f"{', '.join(map(str, pids)) or '未知'}），它不是识谱 WebUI。")
        print(f"         请换端口：set SHIPU_PORT=8761 后重新双击 启动服务.bat")
        return 1

    # —— 是我们自己的实例 ——
    root = _probe("/", timeout=5.0)
    if root and root[0] == 200 and root[1]:
        print(f"  [提示] 已经有一个识谱 WebUI 在 {url} 正常跑着，不需要再起一个。")
        print(f"         现在把浏览器打开到那个地址，本窗口可以直接关掉。")
        if os.environ.get("SHIPU_NO_BROWSER") != "1":
            webbrowser.open(url)
        return 0

    # 是我们的实例，但首页坏了（典型症状：老进程没退干净 → ERR_EMPTY_RESPONSE）
    pids = _port_pids()
    if not pids or os.environ.get("SHIPU_NO_CLEAN") == "1":
        print(f"  [错误] 端口 {PORT} 上有个**坏掉的**旧实例（首页读不出来）没退干净。")
        print(f"         请手动关掉那个窗口；或设 SHIPU_NO_CLEAN=0 让我自动清理；"
              f"或换端口 SHIPU_PORT=8761。")
        return 1

    print(f"  [修复] 端口 {PORT} 上有个坏掉的旧实例（首页无响应 / ERR_EMPTY_RESPONSE），")
    print(f"         正在结束 PID {', '.join(map(str, pids))} 并接管端口…")
    for pid in pids:
        _kill_pid(pid)
    for _ in range(50):                              # 最多等 5s，让端口真正释放
        if _probe("/api/env") is None and not _port_pids():
            break
        time.sleep(0.1)
    left = _port_pids()
    if left:
        print(f"  [错误] 结束失败，PID {', '.join(map(str, left))} 仍占着 {PORT}。"
              f"请手动结束它，或换端口 SHIPU_PORT=8761。")
        return 1
    print("  [修复] 旧实例已清理，端口接管完成。")
    return None


def main() -> int:
    try:
        # line_buffering：输出被重定向到文件/管道时 Python 默认块缓冲，
        # 关键提示（端口被占、自动接管…）会迟迟不落盘甚至丢失。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:                                # noqa: BLE001
        pass
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    env = probe_env()

    print("=" * 68)
    print("  识谱 WebUI —— 前端交互 / 后端处理")
    print("=" * 68)
    print(f"  仓库      {env['repo']}")
    print(f"  识谱.py   {'OK' if not env['missing'] else '缺文件: ' + ', '.join(env['missing'])}")
    print(f"  解释器    {env['python']}  (Python {env['python_version']}, "
          f"PIL {'有' if env['pil'] else '无 → 尺度归一化不可用'})")
    print(f"  产物目录  {env['out_dir']}")
    print("-" * 68)
    url = f"http://{HOST}:{PORT}/"
    print(f"  地址      {url}")
    print("  停止服务  Ctrl+C")
    print("=" * 68)

    rc = claim_port(url)                             # ← 先探端口，别静默双绑
    if rc is not None:
        return rc

    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"  [错误] 绑不上 {HOST}:{PORT} —— {e}")
        print(f"         换端口重开：set SHIPU_PORT=8761")
        return 1
    srv.daemon_threads = True
    if os.environ.get("SHIPU_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
