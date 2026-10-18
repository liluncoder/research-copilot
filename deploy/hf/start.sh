#!/usr/bin/env bash
# HF Spaces 单容器入口：uvicorn（内网 8000）+ Next standalone（对外 7860）。
set -euo pipefail

cd /app

echo "[start] uvicorn 127.0.0.1:8000"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers &
API_PID=$!

# 预热：BGE-M3 首次加载 20~60s，先让首问不必等；失败不影响服务启动
if [ "${EMBEDDING_BACKEND:-hash}" != "hash" ]; then
  python - <<'PY' &
import json, time, urllib.request

for _ in range(90):
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2).read()
        break
    except Exception:
        time.sleep(1)

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/search",
    data=json.dumps({"query": "warm up", "top_k": 1}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(req, timeout=300).read()
    print("[start] embedder warm-up done", flush=True)
except Exception as e:  # noqa: BLE001
    print(f"[start] embedder warm-up skipped: {e}", flush=True)
PY
fi

echo "[start] next standalone 0.0.0.0:7860"
cd /app/web
HOSTNAME=0.0.0.0 PORT="${PORT:-7860}" node server.js &
WEB_PID=$!

trap 'kill "${API_PID}" "${WEB_PID}" 2>/dev/null || true' INT TERM

# 任一进程退出就整体退出，让 Space 重启（而不是半死不活）
wait -n "${API_PID}" "${WEB_PID}"
STATUS=$?
kill "${API_PID}" "${WEB_PID}" 2>/dev/null || true
exit "${STATUS}"
