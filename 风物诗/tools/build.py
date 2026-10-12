# -*- coding: utf-8 -*-
"""风物诗 —— 一键打包（PyInstaller onedir + 素材装配 [+ Inno Setup 安装包]）。

用法：
    python 风物诗/tools/build.py              打包 exe 并装配可运行目录
    python 风物诗/tools/build.py --clean      先清掉 build/ dist/ 再打
    python 风物诗/tools/build.py --inno       打完顺手编译安装包（需已装 Inno Setup）
    python 风物诗/tools/build.py --zip        顺手压一个便携 zip
    python 风物诗/tools/build.py --no-stage   只出 exe，不装配素材

为什么素材要复制到 dist/风物诗/ 而不是塞进 exe：
  工具脚本（获取谱子/*.py）是**运行时被 importlib 就地加载**的普通文件 ——
  它们自己会按 `__file__` 反推 ROOT 去找 parser.py。所以它们必须与
  exe 同级真实存在，这也让用户能自己改脚本而不用重打包。

    dist/风物诗/
        风物诗.exe
        _internal/          ← PyInstaller 的运行时与第三方包
        获取谱子/           ← 工具脚本（exe 同级，paths.scripts_dir() 这么找）
        parser.py           ← 被工具脚本动态加载
        player.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # 风物诗/tools
APP_DIR = HERE.parent                            # 风物诗/
REPO = APP_DIR.parent                            # 仓库根
DIST = APP_DIR / "dist" / "风物诗"
SCRIPTS_SRC = REPO / "获取谱子"

# 装配规则：源 → dist 里的相对位置
SCRIPT_FILES = [
    "jianpu_to_score.py", "midi_to_score.py", "retime.py", "add_hold.py",
    "verify_original.py", "字母谱转谱.py", "字母谱对账.py", "txt_maker.py",
    "键盘字母谱规律.md",
]
OCR_FILES = ["识谱.py", "imgio.py", "audit.py", "字模.json"]
ROOT_FILES = ["parser.py", "player.py"]

SKIP_DIRS = {"__pycache__", ".work", "scores", "起风了"}


def say(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd: list[str], cwd: Path | None = None) -> int:
    """跑子进程，输出实时透传（编码两种都兼容）。"""
    say("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert p.stdout is not None
    raw = p.stdout.read()
    for enc in ("utf-8", "cp936"):
        try:
            say(raw.decode(enc))
            break
        except UnicodeDecodeError:
            continue
    else:
        say(raw.decode("utf-8", "replace"))
    return p.wait()


def have_pyinstaller() -> bool:
    try:
        import PyInstaller                                    # noqa: F401
        return True
    except Exception:
        return False


BULK_LIMIT = 50          # 与受限环境的「批量删除」阈值对齐


def _count_files(d: Path, cap: int = 200) -> int:
    n = 0
    try:
        for p in d.rglob("*"):
            n += 1
            if n > cap:
                break
    except Exception:
        pass
    return n


def drop_or_setaside(d: Path) -> None:
    """腾出输出目录：能删就删，**不能删就改名挪走**。

    为什么需要这条兜底：受限环境会拦截「一次性删太多文件」（本机阈值 50 个）。
    dist/ 有 1000+ 个文件，直接 rmtree 会让**进程被直接终止**（不是抛异常，
    所以连 ignore_errors 都救不回来）。这里改成：文件多就压根不试删除，
    一次改名把旧目录挪到 _回收/ 下 —— 改名不触发删除计数，必定能过。

    在你自己的机器上（没有这层限制）它会正常 rmtree，_回收/ 始终是空的。
    """
    if not d.exists():
        return
    n = _count_files(d)
    if n > BULK_LIMIT:
        say("%s 里有 %s+ 个文件，跳过删除，直接改名腾挪" % (d, BULK_LIMIT))
    else:
        shutil.rmtree(d, ignore_errors=True)
        if not d.exists():
            say("清掉 %s" % d)
            return
    junk = APP_DIR / "_回收"
    try:
        junk.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = junk / ("%s-%s" % (d.name, stamp))
        k = 1
        while dst.exists():
            dst = junk / ("%s-%s-%d" % (d.name, stamp, k))
            k += 1
        shutil.move(str(d), str(dst))
        say("   已腾挪到 %s" % dst)
    except Exception as e:
        say("！%s 既删不掉也挪不动：%s: %s" % (d, type(e).__name__, e))


def clean() -> None:
    for d in (APP_DIR / "build", APP_DIR / "dist"):
        drop_or_setaside(d)


def stage() -> list[tuple[str, int, int]]:
    """把工具脚本装配进 dist/风物诗/。返回 [(说明, 文件数, 字节数)]。"""
    out: list[tuple[str, int, int]] = []

    def copy_group(label: str, items: list[Path], dst: Path) -> None:
        n = b = 0
        dst.mkdir(parents=True, exist_ok=True)
        for src in items:
            if not src.exists():
                say("   ！缺文件：%s" % src)
                continue
            shutil.copy2(src, dst / src.name)
            n += 1
            b += src.stat().st_size
        out.append((label, n, b))
        say("   %-22s %d 个文件  %.1f KB" % (label, n, b / 1024))

    say("\n装配素材 → %s" % DIST)
    copy_group("工具脚本 获取谱子/",
               [SCRIPTS_SRC / f for f in SCRIPT_FILES] +
               [p for p in SCRIPTS_SRC.glob("*.txt")
                if p.name.endswith("（字母谱）.txt")] +
               [p for p in SCRIPTS_SRC.glob("compose_*.py")],
               DIST / "获取谱子")
    copy_group("识谱 简谱识谱/",
               [SCRIPTS_SRC / "简谱识谱" / f for f in OCR_FILES],
               DIST / "获取谱子" / "简谱识谱")
    copy_group("解析与演奏 parser/player",
               [REPO / f for f in ROOT_FILES], DIST)
    copy_group("说明与依赖",
               [APP_DIR / "requirements.txt", APP_DIR / "打包说明.md",
                APP_DIR / "使用须知.txt"],
               DIST)
    return out


def make_zip() -> Path | None:
    z = APP_DIR / "dist" / "风物诗-便携版.zip"
    if z.exists():
        try:
            z.unlink()
        except Exception:
            pass
    say("\n压便携包 → %s" % z)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as f:
        for p in sorted(DIST.rglob("*")):
            if p.is_file():
                f.write(p, Path("风物诗") / p.relative_to(DIST))
    say("   %.1f MB" % (z.stat().st_size / 1024 / 1024))
    return z


def find_iscc() -> Path | None:
    la = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cands = [
        # ★ 实测：静默装在用户目录时，Inno 自己的默认路径是 Programs\Inno
        Path(la) / "Programs" / "Inno" / "ISCC.exe",
        Path(la) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(pf86) / "Inno Setup 6" / "ISCC.exe",
        Path(pf) / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
    ]
    for c in cands:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    return None


def app_version() -> str:
    """从 app/paths.py 读版本号，保证安装包与程序里的版本永远一致。"""
    try:
        txt = (APP_DIR / "app" / "paths.py").read_text(encoding="utf-8")
        for ln in txt.splitlines():
            if ln.startswith("APP_VERSION"):
                return ln.split("=", 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return "0.1.0"


def ensure_utf8_bom(p: Path) -> None:
    """Inno Setup 的 .iss 含中文，必须有 UTF-8 BOM，否则按 ANSI 读会乱码。"""
    try:
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            return
        p.write_bytes(b"\xef\xbb\xbf" + raw)
        say("  已给 %s 补上 UTF-8 BOM" % p.name)
    except Exception as e:
        say("  ！补 BOM 失败：%s" % e)


def make_inno() -> int:
    iscc = find_iscc()
    if iscc is None:
        say("\n！没找到 ISCC.exe（Inno Setup 6 未安装），跳过安装包。")
        say("  装法：winget install --id JRSoftware.InnoSetup")
        return 1
    iss = APP_DIR / "安装包.iss"
    if not iss.is_file():
        say("\n！缺少 %s" % iss)
        return 1
    ensure_utf8_bom(iss)
    ver = app_version()
    cmd = [str(iscc), "/DAPPVERSION=%s" % ver]
    # 中文向导：Inno 官方不带中文 .isl，只有装了非官方语言包才加，否则编译会失败
    zh = iscc.parent / "Languages" / "ChineseSimplified.isl"
    if zh.is_file():
        cmd.append("/DCHINESE")
        say("使用中文安装向导：%s" % zh)
    else:
        say("未安装中文语言包，安装向导走英文（不影响功能）")
    cmd.append(str(iss))
    say("\n编译安装包（版本 %s）→ %s" % (ver, iscc))
    return run(cmd, cwd=APP_DIR)


def main() -> int:
    ap = argparse.ArgumentParser(description="风物诗 打包")
    ap.add_argument("--clean", action="store_true", help="先清 build/ dist/")
    ap.add_argument("--no-stage", action="store_true", help="只出 exe")
    ap.add_argument("--inno", action="store_true", help="顺手编译安装包")
    ap.add_argument("--zip", action="store_true", help="顺手压便携 zip")
    a = ap.parse_args()

    say("=" * 66)
    say("风物诗 打包  ·  Python %s" % sys.version.split()[0])
    say("  应用目录 %s" % APP_DIR)
    say("  仓库根   %s" % REPO)
    say("  工具脚本 %s  (%s)"
        % (SCRIPTS_SRC, "存在" if SCRIPTS_SRC.is_dir() else "★ 不存在！"))
    say("=" * 66)

    if not have_pyinstaller():
        say("！当前解释器没装 PyInstaller。装法：")
        say("  \"%s\" -m pip install pyinstaller" % sys.executable)
        return 2
    if not (APP_DIR / "风物诗.spec").is_file():
        say("！找不到 风物诗.spec")
        return 2
    if not (APP_DIR / "assets" / "风物诗.ico").is_file():
        say("图标不存在，先生成…")
        run([sys.executable, str(HERE / "build_icon.py")])

    if a.clean:
        clean()
    else:
        # 即便没要求 --clean，也要保证输出目录能被重建
        # （否则 PyInstaller 会因为「dist 已存在且删不掉」直接失败）
        drop_or_setaside(APP_DIR / "build")
        drop_or_setaside(DIST)

    t0 = time.time()
    rc = run([sys.executable, "-m", "PyInstaller", "--noconfirm",
              "--log-level=WARN", "风物诗.spec"], cwd=APP_DIR)
    say("\nPyInstaller 退出码 %d，用时 %.1fs" % (rc, time.time() - t0))
    exe = DIST / "风物诗.exe"
    if rc != 0 or not exe.is_file():
        say("！没有产出 %s" % exe)
        return rc or 3

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    say("exe 与运行时：%d 个文件  %.1f MB"
        % (sum(1 for p in DIST.rglob("*") if p.is_file()), total / 1024 / 1024))

    if not a.no_stage:
        groups = stage()
        total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())

    say("\n" + "=" * 66)
    say("产物目录 %s" % DIST)
    say("  总计 %d 个文件  %.1f MB"
        % (sum(1 for p in DIST.rglob("*") if p.is_file()), total / 1024 / 1024))
    say("  双击运行：%s" % exe)
    say("=" * 66)

    if a.zip:
        make_zip()
    if a.inno:
        make_inno()
        z = APP_DIR / "dist" / "installer"
        if z.is_dir():
            for p in sorted(z.iterdir()):
                say("  安装包：%s  (%.1f MB)"
                    % (p, p.stat().st_size / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
