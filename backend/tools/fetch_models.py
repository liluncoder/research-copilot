"""下载 S2 需要的本地模型（BGE-M3）。★在你自己终端跑，比自动化会话快得多。

用法（PowerShell，仓库根目录）：
    $py = "C:\\Users\\23810\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe"
    & $py backend\\tools\\fetch_models.py

它会做三件事：
  1. 走 hf-mirror.com 镜像（国内可达，不用梯子）
  2. 关掉 Xet 传输（那是需要登录的新协议，匿名会 401）
  3. 断点续传：中断了重跑即可，已下好的分片不会重下

下完后 `python tests\\verify_s2_retrieval.py --backend bge-m3` 就能用真向量复跑判据。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # ★否则匿名 401
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

    target = Path(os.environ.get("BGE_M3_PATH", Path.home() / ".cache" / "bge-m3"))
    print(f"镜像     : {os.environ['HF_ENDPOINT']}")
    print(f"目标目录 : {target}")
    print(f"已有大小 : {human(dir_size(target))}")
    print("（BGE-M3 约 2.2GB，中断后重跑本脚本会自动续传）\n")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("缺 huggingface_hub：先执行 pip install huggingface_hub", file=sys.stderr)
        return 2

    t0 = time.time()
    try:
        path = snapshot_download(
            "BAAI/bge-m3",
            allow_patterns=["*.json", "*.txt", "*.model", "model.safetensors"],
            local_dir=str(target),
            resume_download=True,
            max_workers=4,
        )
    except KeyboardInterrupt:
        print("\n已中断，重跑本脚本可续传。")
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"\n下载失败：{type(e).__name__}: {e}", file=sys.stderr)
        print("重跑本脚本会自动续传；若持续失败，可在 .env 里设 EMBEDDING_BACKEND=hash 先用离线兜底。")
        return 1

    size = dir_size(Path(path))
    print(f"\n完成：{path}")
    print(f"大小：{human(size)}  耗时：{time.time() - t0:.0f}s")
    print("\n下一步（验证真向量检索）：")
    print("  python tests\\verify_s2_retrieval.py --backend bge-m3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
