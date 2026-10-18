"""把仓库里"演示必需"的文件整理成 HF Space 的构建上下文，并可选上传。

为什么不在仓库根目录直接建 Space：
  · 根目录有 108MB 的判据 PDF、各种日志、.env —— 上传既慢又可能泄密；
  · HF Space 的 Docker 构建上下文就是仓库根，必须先把无关文件剔掉。

用法：
    python tools\\deploy_hf.py                    # 只生成 build/hf-space（默认）
    python tools\\deploy_hf.py --upload           # 生成后上传（需要 HF_TOKEN）
    python tools\\deploy_hf.py --upload --repo-id liluncoder/research-copilot

上传前请确认环境变量 HF_TOKEN（Settings → Access Tokens，勾选 write）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HF_DIR = ROOT / "deploy" / "hf"

FRONTEND_FILES = [
    "package.json",
    "package-lock.json",
    "next.config.mjs",
    "next-env.d.ts",
    "postcss.config.mjs",
    "tailwind.config.ts",
    "tsconfig.json",
]
FRONTEND_DIRS = ["app", "components", "lib", "public"]
BACKEND_DIRS = ["app", "tools", "data", "chroma_data"]

COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".DS_Store",
    "Thumbs.db",
)


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=COPY_IGNORE)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def stage(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ("Dockerfile", "start.sh", "README.md", ".dockerignore", "docker.yaml", "fetch_bge.py"):
        _copy(HF_DIR / name, out / name)

    for name in BACKEND_DIRS:
        _copy(ROOT / "backend" / name, out / "backend" / name)
    _copy(ROOT / "backend" / "pyproject.toml", out / "backend" / "pyproject.toml")

    for name in FRONTEND_DIRS:
        _copy(ROOT / "frontend" / name, out / "frontend" / name)
    for name in FRONTEND_FILES:
        _copy(ROOT / "frontend" / name, out / "frontend" / name)

    # 构建期没有 node_modules；上面的白名单已排除 .next / node_modules
    docs = sorted((out / "backend" / "data" / "uploads").glob("*/parsed.json"))
    vectors = sorted((out / "backend" / "chroma_data").glob("*/vectors.npy"))
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"staged: {out}")
    print(f"  文献 {len(docs)} 篇（parsed.json） / 索引 {len(vectors)} 份（vectors.npy）")
    print(f"  体积 {total / 1024 / 1024:.1f} MB")
    if len(docs) != len(vectors):
        print("  ! 文献数与索引数不一致：容器里会有文献检索不到", file=sys.stderr)
    if len(docs) < 5:
        print("  ! 演示语料少于 5 篇，确认 UPLOAD_DIR 是否指对了", file=sys.stderr)


def _token() -> str:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        # hf auth login 会把 token 存进 ~/.cache/huggingface/token；
        # get_token() 会读它（也包括 HF_TOKEN 环境变量）。
        try:
            from huggingface_hub import get_token

            token = get_token()
        except Exception:  # noqa: BLE001
            token = None
    if not token:
        f = ROOT / ".hf_token"
        if f.exists():
            token = f.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(
            "未找到 HF token。二选一：\n"
            "  1) hf auth login\n"
            "  2) 把 write token 写进 .hf_token（已在 .gitignore）\n"
            "然后：python tools\\deploy_hf.py --upload"
        )
    return token


def _env_value(name: str) -> str | None:
    """先环境变量，再仓库根的 .env；只返回值，不打印。"""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def upload(
    out: Path,
    repo_id: str | None,
    private: bool,
    message: str,
    *,
    set_secret: bool = False,
    wait: bool = False,
) -> str:
    from huggingface_hub import HfApi

    api = HfApi(token=_token())
    user = api.whoami()["name"]
    repo_id = repo_id or f"{user}/research-copilot"
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        private=private,
        exist_ok=True,
    )
    print(f"uploading {out} → https://huggingface.co/spaces/{repo_id}")
    api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=str(out),
        commit_message=message,
        ignore_patterns=[".git*", "**/__pycache__/**", "**/*.pyc"],
    )

    if set_secret:
        key = _env_value("DEEPSEEK_API_KEY")
        if key:
            api.add_space_secret(repo_id=repo_id, key="DEEPSEEK_API_KEY", value=key)
            print("secret DEEPSEEK_API_KEY: set（值未打印）")
        else:
            print("! .env / 环境变量里没有 DEEPSEEK_API_KEY，跳过 Space Secret")

    subdomain = repo_id.replace("/", "-").replace("_", "-").lower()
    print(f"Space: https://huggingface.co/spaces/{repo_id}")
    print(f"Demo : https://{subdomain}.hf.space")

    if wait:
        _wait_running(api, repo_id)
    return repo_id


def _wait_running(api, repo_id: str, timeout_min: int = 45) -> None:
    import time

    deadline = time.time() + timeout_min * 60
    last = None
    while time.time() < deadline:
        try:
            stage = api.get_space_runtime(repo_id).stage
        except Exception as e:  # noqa: BLE001
            stage = f"unknown: {e}"
        if stage != last:
            print(f"[build] {stage}", flush=True)
            last = stage
        if stage == "RUNNING":
            print("[build] RUNNING — 可以开始验公网访问")
            return
        if stage in {"BUILD_ERROR", "CONFIG_ERROR", "RUNTIME_ERROR"}:
            print(f"[build] 失败：{stage}")
            print(f"日志：https://huggingface.co/spaces/{repo_id}/logs")
            raise SystemExit(1)
        time.sleep(15)
    print("[build] 等待超时；去 Space 页面看构建日志")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "hf-space"))
    ap.add_argument("--upload", action="store_true", help="上传到 HF Space（需要 HF token）")
    ap.add_argument("--repo-id", default=None, help="默认 <你的用户名>/research-copilot")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--message", default="deploy: research copilot demo")
    ap.add_argument("--set-secret", action="store_true", help="把 .env 的 DEEPSEEK_API_KEY 写成 Space Secret")
    ap.add_argument("--wait", action="store_true", help="轮询构建状态直到 RUNNING")
    args = ap.parse_args()

    out = Path(args.out)
    stage(out)
    if args.upload:
        upload(
            out,
            args.repo_id,
            args.private,
            args.message,
            set_secret=args.set_secret,
            wait=args.wait,
        )
    else:
        print("\n只生成了 staging；上传：python tools\\deploy_hf.py --upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
