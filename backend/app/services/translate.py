"""S3 · 段落级翻译（中英对照的右栏）。

★三条设计约束：
1. **按段落翻译，不按整节**：右栏要和左栏逐段对齐，整节翻译会丢段落边界。
2. **磁盘缓存按原文哈希**：同一段第二次打开不再花钱；原文改了哈希就变，自动失效。
3. **批量 + JSON 契约**：一次最多 6 段，要求返回 `{"translations": ["...", ...]}` 按序对齐；
   解析失败就退回逐段翻译（慢但不会错位）。

★缓存目录跟着 upload_dir 走（`data/translate/`），已在 .gitignore 的 `backend/data/` 里。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.core import llm
from app.core.config import get_settings

PROMPT = """把下面的英文学术段落逐段翻译成**简体中文**。

要求：
- 只输出 JSON：{"translations": ["第一段译文", "第二段译文", ...]}
- 段数与输入完全一致，顺序不变
- 保留专业术语的英文原词（如 Transformer、attention、BLEU），数字与公式原样保留
- 不要加解释、不要合并段落、不要省略

段落：
{items}
"""

BATCH = 6


def _cache_dir() -> Path:
    uploads = Path(get_settings().upload_dir)
    return uploads.parent / "translate"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load(doc_id: str, text: str) -> str | None:
    p = _cache_dir() / doc_id / f"{_key(text)}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _save(doc_id: str, text: str, zh: str) -> None:
    d = _cache_dir() / doc_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_key(text)}.txt").write_text(zh, encoding="utf-8")


def _parse(reply: str, expect: int) -> list[str] | None:
    s = reply.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s)
        items = data.get("translations")
        if isinstance(items, list) and len(items) == expect:
            return [str(x) for x in items]
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            items = json.loads(m.group(0)).get("translations")
            if isinstance(items, list) and len(items) == expect:
                return [str(x) for x in items]
        except Exception:  # noqa: BLE001
            return None
    return None


def translate_items(
    doc_id: str, items: list[dict[str, Any]], *, target: str = "zh"
) -> dict[str, Any]:
    """items: [{"para_id": "...", "text": "..."}]，返回 {para_id: zh} 与统计。"""
    if not llm.is_configured():
        return {"error": "未配置 LLM key，无法翻译", "items": {}, "cached": 0, "translated": 0}

    result: dict[str, str] = {}
    pending: list[dict[str, Any]] = []
    for it in items:
        pid, text = str(it["para_id"]), str(it["text"])
        hit = _load(doc_id, text)
        if hit:
            result[pid] = hit
        else:
            pending.append({"para_id": pid, "text": text})

    translated = 0
    errors: list[str] = []
    for i in range(0, len(pending), BATCH):
        chunk = pending[i : i + BATCH]
        numbered = "\n\n".join(f"[{k + 1}] {c['text']}" for k, c in enumerate(chunk))
        try:
            reply = llm.chat(
                [{"role": "user", "content": PROMPT.replace("{items}", numbered)}],
                temperature=0.2,
                max_tokens=2000,
            ).text
            outs = _parse(reply, len(chunk))
        except Exception as e:  # noqa: BLE001
            outs = None
            errors.append(f"batch {i // BATCH}: {e}")

        if outs:
            for c, zh in zip(chunk, outs):
                result[c["para_id"]] = zh
                _save(doc_id, c["text"], zh)
                translated += 1
        else:
            # 兜底：逐段翻译（慢，但保证不错位）
            for c in chunk:
                try:
                    zh = llm.chat(
                        [
                            {
                                "role": "user",
                                "content": "把下面这段英文学术文本译成简体中文，只输出译文：\n\n" + c["text"],
                            }
                        ],
                        temperature=0.2,
                        max_tokens=900,
                    ).text.strip()
                    result[c["para_id"]] = zh
                    _save(doc_id, c["text"], zh)
                    translated += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{c['para_id']}: {e}")

    return {
        "items": result,
        "cached": len(items) - len(pending),
        "translated": translated,
        "failed": len(items) - len(result),
        "errors": errors[:3],
    }
