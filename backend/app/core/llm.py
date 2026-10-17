"""LLM 调用（OpenAI 兼容端点，DeepSeek 主 / 通义、智谱备）。

★只用标准库 urllib：少一个依赖，Docker 也小。
★密钥只从 settings 读（→ .env），绝不写进日志/异常信息。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = 60


class LLMNotConfigured(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _endpoint() -> tuple[str, str, str]:
    s = get_settings()
    presets = {
        "deepseek": (s.deepseek_base_url, s.deepseek_api_key, s.deepseek_model),
        "dashscope": (s.dashscope_base_url, s.dashscope_api_key, s.dashscope_model),
        "zhipu": (s.zhipu_base_url, s.zhipu_api_key, s.zhipu_model),
    }
    base, key, model = presets.get(s.llm_provider, presets["deepseek"])
    if not key:
        # 主 provider 没 key ⇒ 找一个有 key 的备用
        for name, (b, k, m) in presets.items():
            if k:
                logger.warning("主 provider %s 无 key，改用 %s", s.llm_provider, name)
                return b, k, m
        raise LLMNotConfigured("没有任何可用的 LLM key（见 .env.example 的 LLM_PROVIDER 一组）")
    return base, key, model


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 1200,
) -> LLMReply:
    base, key, model = _endpoint()
    url = base.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # ★不能把 key 打进日志：只留状态码 + 响应体前 200 字
        detail = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 连接失败（{e.reason}）——检查网络或代理") from e

    usage = body.get("usage") or {}
    return LLMReply(
        text=(body["choices"][0]["message"]["content"] or "").strip(),
        model=body.get("model", model),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


def is_configured() -> bool:
    try:
        _endpoint()
        return True
    except LLMNotConfigured:
        return False
