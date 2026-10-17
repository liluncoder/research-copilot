"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { askQuestion, type QAResult } from "@/lib/api";

/** 示例问题：一键复现 J4 三连问，评审不用自己编问题。 */
const EXAMPLES = [
  "这篇论文里 Adam 优化器的 β1、β2 和 ε 分别设成多少？",
  "训练用了多少块 GPU？什么型号？",
  "在 WMT 2014 英德翻译任务上，BLEU 分数是多少？",
];

const NODE_LABEL: Record<string, string> = {
  plan: "理解问题 · 改写检索词",
  retrieve: "混合检索 · 召回片段",
  answer: "依据片段作答",
  verify: "核对出处 · 剔除编造",
};

/** 把 [来源: 文件名·p7·5.3 Optimizer] 渲染成小标签，正文保持简洁。 */
function renderAnswer(text: string) {
  const re = /\[来源[:：]\s*([^·\]]+?)\s*·\s*([^·\]]+?)\s*·\s*([^\]]+?)\s*\]/g;
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<span key={`t${last}`}>{text.slice(last, m.index)}</span>);
    out.push(
      <span
        key={`c${m.index}`}
        title={`来源：${m[1]} · ${m[2]} · ${m[3]}`}
        className="mx-0.5 inline-flex translate-y-[-1px] items-center rounded border border-primary/25 bg-primary/10 px-1.5 py-[1px] align-baseline font-mono text-[11px] text-primary"
      >
        {m[2]} · {m[3].trim()}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key="tail">{text.slice(last)}</span>);
  return out;
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<QAResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const totalMs = useMemo(
    () => (res?.steps ?? []).reduce((s, x) => s + x.ms, 0),
    [res],
  );

  async function submit(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      setRes(await askQuestion(q, { topK: 5 }));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen">
      <div className="mx-auto w-full max-w-3xl px-6 py-12">
        <header className="mb-10">
          <h1 className="text-2xl font-semibold tracking-tight">抗幻觉问答</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            只依据库内文献作答，每个论断都挂出处；查不到就明确拒答。
          </p>
          <nav className="mt-5 flex gap-5 text-sm text-muted-foreground">
            <Link href="/" className="hover:text-foreground">
              首页
            </Link>
            <Link href="/library" className="hover:text-foreground">
              文献库
            </Link>
            <Link href="/ask" className="font-medium text-foreground">
              问答
            </Link>
            <Link href="/reader" className="hover:text-foreground">
              阅读器
            </Link>
          </nav>
        </header>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit(question);
          }}
          className="flex items-center gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="问点什么，例如：训练用了多少块 GPU？"
            className="h-11 flex-1 rounded-lg border border-border/70 bg-transparent px-3.5 text-sm outline-none transition placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="h-11 shrink-0 rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "思考中" : "提问"}
          </button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                void submit(ex);
              }}
              className="rounded-full border border-border/60 px-3 py-1 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              {ex}
            </button>
          ))}
        </div>

        {err && (
          <p className="mt-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
            请求失败：{err}
          </p>
        )}

        {busy && (
          <ol className="mt-10 space-y-4 border-l border-border/60 pl-5">
            {["plan", "retrieve", "answer", "verify"].map((n, i) => (
              <li key={n} className="relative">
                <span className="absolute -left-[23px] top-2 h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                  {n}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground/70">
                  {NODE_LABEL[n]}
                  <span className="ml-1 animate-pulse">…</span>
                </p>
                {i === 0 && <span className="sr-only">正在处理</span>}
              </li>
            ))}
          </ol>
        )}

        {res && !busy && (
          <div className="mt-10 space-y-8">
            {/* 结论 */}
            <section>
              <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
                {res.refused ? (
                  <span className="rounded-full border border-border/70 px-2 py-0.5">
                    未找到依据 · 已拒答
                  </span>
                ) : (
                  <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-primary">
                    已作答 · {res.citations.length} 处出处
                  </span>
                )}
                <span>编排 {res.orchestrator}</span>
                <span>·</span>
                <span>{Math.round(totalMs)} ms</span>
              </div>

              <div className="rounded-xl border border-border/60 px-5 py-4">
                <p className="whitespace-pre-wrap text-[15px] leading-7">
                  {renderAnswer(res.answer)}
                </p>
              </div>

              {res.invalid_citations.length > 0 && (
                <p className="mt-2 text-xs text-destructive">
                  已剔除 {res.invalid_citations.length} 条无法核实的出处：
                  {res.invalid_citations.join(" ")}
                </p>
              )}
            </section>

            {/* 思考过程 */}
            <section>
              <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-muted-foreground">
                思考过程
              </h2>
              <ol className="space-y-4 border-l border-border/60 pl-5">
                {res.steps.map((s, i) => (
                  <li key={`${s.node}-${i}`} className="relative">
                    <span className="absolute -left-[23px] top-2 h-1.5 w-1.5 rounded-full bg-primary/70" />
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                        {s.node}
                        <span className="ml-2 normal-case tracking-normal text-muted-foreground/60">
                          {NODE_LABEL[s.node] ?? ""}
                        </span>
                      </p>
                      <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/60">
                        {s.ms >= 1000 ? `${(s.ms / 1000).toFixed(1)}s` : `${Math.round(s.ms)}ms`}
                      </span>
                    </div>
                    <p className="mt-1 break-words text-[13px] leading-6 text-muted-foreground">
                      {s.detail}
                    </p>
                  </li>
                ))}
              </ol>
            </section>

            {/* 命中片段 */}
            {res.hits.length > 0 && (
              <section>
                <details className="group">
                  <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-widest text-muted-foreground transition hover:text-foreground">
                    依据片段（{res.hits.length}）
                    <span className="ml-1 inline-block transition group-open:rotate-90">›</span>
                  </summary>
                  <ul className="mt-4 space-y-3">
                    {res.hits.map((h) => (
                      <li key={h.chunk_id} className="rounded-lg border border-border/50 px-4 py-3">
                        <div className="mb-1.5 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
                          <span className="text-foreground/80">{h.page}</span>
                          <span>·</span>
                          <span>{h.section}</span>
                          <span className="ml-auto text-muted-foreground/60">
                            {h.dense_rank !== null ? `dense#${h.dense_rank}` : ""}
                            {h.sparse_rank !== null ? ` sparse#${h.sparse_rank}` : ""}
                          </span>
                        </div>
                        <p className="line-clamp-4 text-[13px] leading-6 text-muted-foreground">
                          {h.text}
                        </p>
                      </li>
                    ))}
                  </ul>
                </details>
              </section>
            )}
          </div>
        )}

        <footer className="mt-16 text-[11px] text-muted-foreground/70">
          检索为空时不会调用大模型；回答里的出处会逐条核对，对不上即剔除。
        </footer>
      </div>
    </main>
  );
}
