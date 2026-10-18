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


def _redact(text: str) -> str:
    import re

    return re.sub(r"//oauth2:[^@]+@", "//oauth2:***@", text)


def run(cmd: list[str], cwd: Path) -> None:
    shown = [ _redact(x) for x in cmd[:3] ]
    print("$", " ".join(shown + (["..."] if len(cmd) > 3 else [])))
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

    # ★创空间的 master 是受保护分支，不允许 force push。
    # 先把远端历史取下来，mixed reset 到远端 HEAD（保留工作区文件），
    # 再把我们的文件作为一次正常提交接在后面 → fast-forward push。
    run(["git", "fetch", url, "master"], out)
    run(["git", "reset", "--mixed", "FETCH_HEAD"], out)
    run(["git", "add", "-A"], out)
    commit = subprocess.run(
        ["git", "commit", "-m", args.message],
        cwd=out,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        print(commit.stdout, commit.stderr, file=sys.stderr)
        return 1
    run(["git", "push", url, "master"], out)

    print(f"\nSpace: https://modelscope.cn/studios/{args.repo}")
    print("下一步：到创空间页面点『上线 / 重启』触发 Docker 构建；")
    print("并在设置里加环境变量 DEEPSEEK_API_KEY（值不要提交进仓库）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
