"""检查 .env 里的密钥是否齐全。

★只打印变量名和长度，**绝不打印密钥内容** —— 这样你随手截图/贴日志也不会泄露。

用法：
    python tools/check_env.py

退出码：0 = 齐全；1 = 有缺失或文件可疑。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

# G2 判据要求的两个 provider
REQUIRED = ["DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not ENV.exists():
        print("✗ 根目录没有 .env")
        print("  建一个：Copy-Item .env.example .env")
        return 1

    raw = ENV.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    vals: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()

    print(f"检查：{ENV}")
    print(f"  大小 {len(raw)} 字节，{len(text.splitlines())} 行")

    # ★头号事故：跟空模板一模一样 ⇒ 说明又被 Copy-Item 覆盖过一次
    clobbered = EXAMPLE.exists() and raw == EXAMPLE.read_bytes()
    if clobbered:
        print("\n⚠ 严重：.env 与 .env.example 内容完全相同 ⇒ 你的密钥已被覆盖成空模板。")
        print("   常见原因：又跑了一次 `Copy-Item .env.example .env` ——")
        print("   它是**覆盖**不是新建，而且会继承源文件的修改时间，所以看不出被改过。")
        print("   修法：把 key 重新粘回 .env，然后 `Copy-Item .env .env.bak` 备份（.env.* 已屏蔽）。")

    print()
    empty: list[str] = []
    for k in REQUIRED:
        v = vals.get(k, "")
        if v:
            print(f"  ✓ {k} 已填（{len(v)} 字符）")
        else:
            print(f"  ✗ {k} 是空的")
            empty.append(k)

    # 顺带查几个容易写错的形式（加引号 / 等号旁空格）
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        k, v = (p.strip() for p in s.split("=", 1))
        if k in REQUIRED:
            if v[:1] in {'"', "'"}:
                print(f"  ⚠ {k} 的值带了引号 —— 去掉引号，写裸值")
            if " = " in s:
                print(f"  ⚠ {k} 的等号旁有空格 —— 改成 NAME=value")

    if clobbered or empty:
        print("\n✗ 需要处理")
        return 1
    print("\n✓ 密钥齐全")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
