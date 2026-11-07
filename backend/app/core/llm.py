"""LLM 调用（OpenAI 兼容端点；主用模型由 LLM_PROVIDER 决定，当前默认通义千问）。

★只用标准库 urllib：少一个依赖，Docker 也小。
★密钥只从 settings 读（→ .env），绝不写进日志/异常信息。
★**必须带重试**：实测同一台机器、同一个 key，5 次调用里出现过 1 次
  `[Errno 10053] 你的主机中的软件中止了一个已建立的连接`（Qwen 官方端点在长连接上偶发）。
  不重试的后果不是"慢一点"，而是 plan 节点拿不到检索词 ⇒ 退回原始中文问题 ⇒ 检索零命中 ⇒ **误拒答**。
  这类抖动会让判据忽过忽不过，所以重试是判据可复现性的一部分，不是优化。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = 60
RETRIES = 2  # 首次 + 1 次重试
RETRY_BACKOFF = 1.5  # 秒，线性退避


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

    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            # 4xx 是请求本身的问题（余额/模型名/额度），重试没意义；5xx 与 429 值得重试
            if e.code < 500 and e.code != 429:
                detail = e.read().decode("utf-8", errors="replace")[:200]
                raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
            last_err = e
            logger.warning("LLM HTTP %s（第 %d/%d 次），准备重试", e.code, attempt, RETRIES)
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            logger.warning("LLM 连接异常（第 %d/%d 次）：%s", attempt, RETRIES, e)
        if attempt < RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)
    else:
        reason = getattr(last_err, "reason", None) or last_err
        raise RuntimeError(f"LLM 连接失败（重试 {RETRIES} 次）：{reason} ——检查网络或代理") from last_err

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
