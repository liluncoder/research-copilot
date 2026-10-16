"""连通性自检：拿 .env 里的 key 各调一次 DeepSeek 和通义（= 判据 G2 的通过条件）。

★密钥全程不出现在命令行、不出现在输出里 —— 只打印 HTTP 状态码和模型回的极简内容。
   （把 key 写进 curl 命令会进 shell 历史，也容易被截图/贴日志时带出去。）

用法：
    python tools/check_llm.py

退出码：0 = 两家都通；1 = 有不通的。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 40


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()
    return vals


def probe(name: str, base_url: str, key: str, model: str) -> bool:
    """打一次最小的 chat/completions，只看能不能通。"""
    if not key:
        print(f"  ✗ {name}：.env 里没填 key，跳过")
        return False

    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "回复两个字：收到"}], "max_tokens": 8}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        print(f"  ✓ {name}（{model}）HTTP {resp.status} —— 模型回：{text[:20]!r}")
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  ✗ {name}（{model}）HTTP {e.code}：{detail}")
        if e.code == 401:
            print(f"     ⇒ key 无效或格式不对（当前长度 {len(key)} 字符；通常 30-40 字符左右）")
        return False
    except Exception as e:  # 网络/DNS/超时
        print(f"  ✗ {name}（{model}）连不上：{type(e).__name__}: {e}")
        return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    env = read_env()
    print("两家各调一次（判据 G2 的通过条件）：")
    ok_ds = probe(
        "DeepSeek",
        env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        env.get("DEEPSEEK_API_KEY", ""),
        env.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
    ok_qwen = probe(
        "通义千问",
        env.get("DASHSCOPE_BASE_URL", ""),
        env.get("DASHSCOPE_API_KEY", ""),
        env.get("DASHSCOPE_MODEL", "qwen-plus"),
    )

    print()
    if ok_ds and ok_qwen:
        print("PASS —— 双 provider 可用，主备切换的前提成立（R6 风险已缓解）")
        return 0
    print("FAIL —— 至少一家不通")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
