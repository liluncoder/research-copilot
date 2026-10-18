"use client";

import { useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { askQuestion, type QAResult } from "@/lib/api";
import { PageHeader, SiteShell } from "@/components/site-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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

  const totalMs = useMemo(() => (res?.steps ?? []).reduce((s, x) => s + x.ms, 0), [res]);

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
    <SiteShell width="narrow">
      <PageHeader
        title="抗幻觉问答"
        desc="只依据库内文献作答，每个论断都挂出处；查不到就明确拒答。"
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(question);
        }}
        className="flex items-center gap-2"
      >
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="问点什么，例如：训练用了多少块 GPU？"
          aria-label="问题"
          className="h-11"
        />
        <Button type="submit" size="lg" disabled={busy || !question.trim()} className="shrink-0">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {busy ? "思考中" : "提问"}
        </Button>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <Button
            key={ex}
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => {
              setQuestion(ex);
              void submit(ex);
            }}
            className="rounded-full font-normal text-muted-foreground hover:text-foreground"
          >
            <Search className="h-3 w-3 opacity-60" />
            {ex}
          </Button>
        ))}
      </div>

      {err && (
        <Alert variant="destructive" className="mt-6">
          请求失败：{err}
        </Alert>
      )}

      {busy && (
        <Card className="mt-8 p-5">
          <ol className="space-y-4 border-l border-border pl-5">
            {["plan", "retrieve", "answer", "verify"].map((n) => (
              <li key={n} className="relative">
                <span className="absolute -left-[23px] top-2 h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                  {n}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground/70">
                  {NODE_LABEL[n]}
                  <span className="ml-1 animate-pulse">…</span>
                </p>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {res && !busy && (
        <div className="mt-9 space-y-8">
          {/* 结论 */}
          <section>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {res.refused ? (
                <Badge variant="secondary">未找到依据 · 已拒答</Badge>
              ) : (
                <Badge variant="success">已作答 · {res.citations.length} 处出处</Badge>
              )}
              <span>编排 {res.orchestrator}</span>
              <span className="text-border">·</span>
              <span className="tabular">{Math.round(totalMs)} ms</span>
            </div>

            <Card className="px-5 py-4">
              <p className="whitespace-pre-wrap text-[15px] leading-7">{renderAnswer(res.answer)}</p>
            </Card>

            {res.invalid_citations.length > 0 && (
              <Alert variant="warning" className="mt-2">
                已剔除 {res.invalid_citations.length} 条无法核实的出处：{res.invalid_citations.join(" ")}
              </Alert>
            )}
          </section>

          {/* 思考过程 */}
          <section>
            <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-muted-foreground">
              思考过程
            </h2>
            <ol className="space-y-4 border-l border-border pl-5">
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
                <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium uppercase tracking-widest text-muted-foreground transition hover:text-foreground">
                  依据片段（{res.hits.length}）
                  <span className="inline-block transition group-open:rotate-90">›</span>
                </summary>
                <ul className="mt-4 space-y-3">
                  {res.hits.map((h) => (
                    <li key={h.chunk_id}>
                      <Card className="px-4 py-3">
                        <div className="mb-1.5 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
                          <span className="text-foreground/80">{h.page}</span>
                          <span className="text-border">·</span>
                          <span>{h.section}</span>
                          <span className="ml-auto text-muted-foreground/60">
                            {h.dense_rank !== null ? `dense#${h.dense_rank}` : ""}
                            {h.sparse_rank !== null ? ` sparse#${h.sparse_rank}` : ""}
                          </span>
                        </div>
                        <p className="line-clamp-4 text-[13px] leading-6 text-muted-foreground">
                          {h.text}
                        </p>
                      </Card>
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
    </SiteShell>
  );
}
