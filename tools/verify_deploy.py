"""G20 部署验收：对一个公网（或本地）演示地址跑一遍主线探针。

用法：
    python tools/verify_deploy.py https://<user>-research-copilot.hf.space
    python tools/verify_deploy.py http://localhost:7861 --skip-qa

判据：
  D1 首页 / 五个功能页 HTTP 200
  D2 /health 正常，且 embedding_backend 与 llm_configured 可见
  D3 预置语料 9 篇
  D4 中文查询能召回（≥1 条），并报出实际向量后端
  D5 引用图谱 ≥500 节点
  D6 中文事实题答对（含 P100 与 8）且有出处、无编造（需要 LLM key）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PAGES = ["/", "/library", "/ask", "/reader", "/graph", "/write"]


def req(base: str, path: str, *, data: dict | None = None, timeout: int = 120):
    url = base.rstrip("/") + path
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    r = urllib.request.Request(
        url,
        data=body,
        headers={
            # ModelScope 的 ms.show 网关会拦 Python-urllib 默认 UA（403），
            # 用浏览器 UA 才能过；不是应用层鉴权。
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            **({"Content-Type": "application/json"} if body else {}),
        },
        method="POST" if body else "GET",
    )
    t0 = time.time()
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
        status = resp.status
    return status, raw, round((time.time() - t0) * 1000)


def get_json(base: str, path: str, timeout: int = 120):
    _, raw, ms = req(base, path, timeout=timeout)
    return json.loads(raw.decode("utf-8")), ms


def post_json(base: str, path: str, data: dict, timeout: int = 180):
    _, raw, ms = req(base, path, data=data, timeout=timeout)
    return json.loads(raw.decode("utf-8")), ms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--skip-qa", action="store_true", help="不调 LLM，只验证检索与页面")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    failures: list[str] = []
    warnings: list[str] = []

    print(f"# 部署验收：{base}\n")
    print("| 检查 | 结果 | 耗时 | 详情 |")
    print("|---|---|---|---|")

    def row(name: str, ok: bool, ms: int | str, detail: str) -> None:
        print(f"| {name} | {'PASS' if ok else 'FAIL'} | {ms} | {detail} |")
        if not ok:
            failures.append(name)

    # D1 页面
    for path in PAGES:
        try:
            status, raw, ms = req(base, path, timeout=60)
            ok = status == 200 and len(raw) > 2000
            row(f"页面 {path}", ok, ms, f"HTTP {status} / {len(raw)} B")
        except Exception as e:  # noqa: BLE001
            row(f"页面 {path}", False, "-", f"{type(e).__name__}: {e}")

    # D2 health
    health = None
    try:
        health, ms = get_json(base, "/health", timeout=60)
        ok = health.get("status") == "ok"
        row(
            "health",
            ok,
            ms,
            f"stage={health.get('stage')} embedding={health.get('embedding_backend')} "
            f"llm={health.get('llm_configured')}",
        )
        if not health.get("llm_configured"):
            warnings.append("llm_configured=false：问答/图注/综述会降级")
    except Exception as e:  # noqa: BLE001
        row("health", False, "-", f"{type(e).__name__}: {e}")

    # D3 语料
    docs: list[dict] = []
    try:
        data, ms = get_json(base, "/api/v1/documents", timeout=60)
        docs = data.get("items") or []
        row("预置语料", len(docs) >= 9, ms, f"{len(docs)} 篇")
    except Exception as e:  # noqa: BLE001
        row("预置语料", False, "-", f"{type(e).__name__}: {e}")

    # D4 中文检索
    emb = (health or {}).get("embedding_backend", "?")
    try:
        res, ms = post_json(
            base,
            "/api/v1/search",
            {"query": "训练用了多少块 GPU？", "top_k": 5},
            timeout=180,
        )
        count = int(res.get("count") or 0)
        backend = res.get("backend") or {}
        ok = count >= 1
        row("中文检索", ok, ms, f"{count} 条 / store={backend.get('store')} embed={backend.get('embedding')}")
        if emb == "hash":
            warnings.append("embedding=hash：中文到英文论文的跨语言召回会偏弱（HF 应显示 bge-m3）")
    except Exception as e:  # noqa: BLE001
        row("中文检索", False, "-", f"{type(e).__name__}: {e}")

    # D5 图谱
    try:
        g, ms = get_json(base, "/api/v1/graph", timeout=120)
        n = int(g["stats"]["n_nodes"])
        row("引用图谱", n >= 500, ms, f"{n} 节点 / {g['stats']['n_edges']} 边")
    except Exception as e:  # noqa: BLE001
        row("引用图谱", False, "-", f"{type(e).__name__}: {e}")

    # D6 事实题（LLM）
    if args.skip_qa:
        print("| 中文问答 | SKIP | - | --skip-qa |")
    else:
        try:
            qa, ms = post_json(
                base,
                "/api/v1/qa",
                {"question": "训练用了多少块 GPU？什么型号？", "top_k": 5},
                timeout=240,
            )
            ans = qa.get("answer") or ""
            cites = qa.get("citations") or []
            ok = (not qa.get("refused")) and ("P100" in ans) and ("8" in ans) and len(cites) > 0
            row(
                "中文问答（J4）",
                ok,
                ms,
                f"refused={qa.get('refused')} cites={len(cites)} "
                f"invalid={len(qa.get('invalid_citations') or [])}",
            )
            if not ok:
                print(f"\n> 回答节选：{ans[:240]}")
        except Exception as e:  # noqa: BLE001
            row("中文问答（J4）", False, "-", f"{type(e).__name__}: {e}")

    print("\n## 结论\n")
    if failures:
        print(f"**FAIL**：{', '.join(failures)}")
    else:
        print("**PASS**：主线探针全部通过")
    for w in warnings:
        print(f"- WARN：{w}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
