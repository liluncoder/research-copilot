"""把 staging 推到 ModelScope 创空间（Docker 构建，端口固定 7860）。

前置：
  1. modelscope.cn 注册并登录
  2. 网页创建一个公开创空间，SDK 选 Docker，名称 research-copilot
  3. 账号设置 → 访问令牌，复制 ms-...；不要写进仓库

用法：
    $env:MODELSCOPE_TOKEN='ms-...'
    python tools\\deploy_modelscope.py --repo luniy/research-copilot

脚本只做 git push；push 后到创空间页面点"上线/重启"触发构建。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_hf import ROOT, stage  # noqa: E402


def run(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(cmd[:3] + (["..."] if len(cmd) > 3 else [])))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="<用户名>/research-copilot")
    ap.add_argument("--out", default=str(ROOT / "build" / "ms-space"))
    ap.add_argument("--token", default=os.environ.get("MODELSCOPE_TOKEN"))
    ap.add_argument("--message", default="deploy: research copilot demo")
    args = ap.parse_args()

    token = args.token
    if not token:
        f = ROOT / ".ms_token"
        if f.exists():
            token = f.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(
            "未找到 ModelScope 访问令牌。二选一：\n"
            "  1) $env:MODELSCOPE_TOKEN='ms-...'\n"
            "  2) 写入 .ms_token（已在 .gitignore）"
        )

    out = Path(args.out)
    stage(out)
    # 每次 staging 都重建 git，避免把上次的历史/密钥带进去
    run(["git", "init", "-b", "master"], out)
    run(["git", "config", "user.name", "research-copilot"], out)
    run(["git", "config", "user.email", "deploy@local"], out)
    run(["git", "add", "-A"], out)
    run(["git", "commit", "-m", args.message], out)

    url = f"https://oauth2:{token}@www.modelscope.cn/studios/{args.repo}.git"
    try:
        run(["git", "ls-remote", url, "HEAD"], out)
    except subprocess.CalledProcessError:
        print("! 仓库不可达：确认创空间已创建、token 有写权限、repo 名拼写正确", file=sys.stderr)
        return 1
    run(["git", "push", "--force", url, "master"], out)

    print(f"\nSpace: https://modelscope.cn/studios/{args.repo}")
    print("下一步：到创空间页面点『上线 / 重启』触发 Docker 构建；")
    print("并在设置里加环境变量 DEEPSEEK_API_KEY（值不要提交进仓库）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
