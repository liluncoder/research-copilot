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

    for name in ("Dockerfile", "start.sh", "README.md", ".dockerignore"):
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


def upload(out: Path, repo_id: str | None, private: bool, message: str) -> str:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit(
            "未找到 HF_TOKEN。先创建 write token：https://huggingface.co/settings/tokens\n"
            "然后：$env:HF_TOKEN='hf_...'; python tools\\deploy_hf.py --upload"
        )
    from huggingface_hub import HfApi

    api = HfApi(token=token)
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
    subdomain = repo_id.replace("/", "-").replace("_", "-").lower()
    print(f"Space: https://huggingface.co/spaces/{repo_id}")
    print(f"Demo : https://{subdomain}.hf.space")
    return repo_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "hf-space"))
    ap.add_argument("--upload", action="store_true", help="上传到 HF Space（需要 HF_TOKEN）")
    ap.add_argument("--repo-id", default=None, help="默认 <你的用户名>/research-copilot")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--message", default="deploy: research copilot demo")
    args = ap.parse_args()

    out = Path(args.out)
    stage(out)
    if args.upload:
        upload(out, args.repo_id, args.private, args.message)
    else:
        print("\n只生成了 staging；上传：python tools\\deploy_hf.py --upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
