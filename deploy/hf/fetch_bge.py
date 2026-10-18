"""构建期下载 BGE-M3：优先魔搭（国内快），失败再走 Hugging Face。

为什么要两条路：
  · ModelScope 创空间的构建机在国内，直连 huggingface.co 可能很慢或不可达；
  · HF Spaces 的构建机在海外，魔搭反而可能慢。
所以 auto 模式先试魔搭、再试 HF，任一成功即可（权重约 2.2GB）。
"""

from __future__ import annotations

import sys
from pathlib import Path

DEST = Path("/app/models/bge-m3")
PATTERNS = ["*.json", "*.txt", "*.model", "pytorch_model.bin", "model.safetensors"]


def has_weights() -> bool:
    return any(DEST.glob("*.safetensors")) or (DEST / "pytorch_model.bin").exists()


def from_modelscope() -> None:
    from modelscope import snapshot_download

    print("[bge] downloading from ModelScope ...", flush=True)
    snapshot_download(
        "BAAI/bge-m3",
        local_dir=str(DEST),
        allow_patterns=PATTERNS,
        max_workers=4,
    )


def from_huggingface() -> None:
    from huggingface_hub import snapshot_download

    print("[bge] downloading from Hugging Face ...", flush=True)
    snapshot_download(
        "BAAI/bge-m3",
        local_dir=str(DEST),
        allow_patterns=PATTERNS,
        max_workers=4,
    )


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for name, fn in (("modelscope", from_modelscope), ("huggingface", from_huggingface)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {e}")
            print(f"[bge] {name} failed: {e}", flush=True)
        if has_weights():
            print(f"[bge] weights ready at {DEST}", flush=True)
            return 0
    print("[bge] no weights downloaded\n" + "\n".join(errors), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
