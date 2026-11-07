"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Plus, Search, Send, Sparkles, Trash2 } from "lucide-react";
import { askQuestion, type QAResult } from "@/lib/api";
import { SiteHeader } from "@/components/site-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * 问答页（对话式）。
 *
 * ★改造要点（按使用反馈）：
 *   1. 原来一刷新/切页历史就没了 ⇒ 对话存 localStorage，左侧栏列出历史、可点开、可删除；
 *   2. 原来结果铺满整页、输入框在最上面 ⇒ 改成聊天式：空态时输入框居中，问答后落到底部；
 *   3. 原来"思考中"只是四行静止文字 ⇒ 换成转圈 + 逐条点亮的步骤提示。
 *   4. 每个回答的出处/思考过程仍然保留（这是本作品的核心卖点，不能为了好看删掉）。
 */

type Msg = { id: string; role: "user" | "assistant"; text: string; res?: QAResult; error?: string };
type Conv = { id: string; title: string; updatedAt: number; messages: Msg[] };

const STORE_KEY = "rc_chat_v1";

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

/** 素材出处渲染成小标签，正文保持简洁。 */
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
        className="mx-0.5 inline-flex items-center rounded border border-primary/25 bg-primary/10 px-1.5 py-[1px] align-baseline font-mono text-[11px] text-primary"
      >
        {m[2]} · {m[3].trim()}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key="tail">{text.slice(last)}</span>);
  return out;
}

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export default function AskPage() {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const active = useMemo(() => convs.find((c) => c.id === activeId) ?? null, [convs, activeId]);
  const messages = active?.messages ?? [];

  // 读本地历史
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Conv[];
        if (Array.isArray(parsed) && parsed.length) {
          setConvs(parsed);
          setActiveId(parsed[0].id);
        }
      }
    } catch {
      /* 坏数据就当他没有 */
    }
    setHydrated(true);
  }, []);

  // 写本地历史
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(convs.slice(0, 30)));
    } catch {
      /* 配额满了就别存，不影响使用 */
    }
  }, [convs, hydrated]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const newConv = useCallback(() => {
    const c: Conv = { id: uid(), title: "新对话", updatedAt: Date.now(), messages: [] };
    setConvs((prev) => [c, ...prev]);
    setActiveId(c.id);
    setQuestion("");
    setErr(null);
  }, []);

  function removeConv(id: string) {
    setConvs((prev) => {
      const next = prev.filter((c) => c.id !== id);
      if (id === activeId) setActiveId(next[0]?.id ?? null);
      return next;
    });
  }

  async function submit(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setErr(null);

    let convId = activeId;
    if (!convId) {
      convId = uid();
      setConvs((prev) => [{ id: convId!, title: q.slice(0, 24), updatedAt: Date.now(), messages: [] }, ...prev]);
      setActiveId(convId);
    }
    const userMsg: Msg = { id: uid(), role: "user", text: q };
    setConvs((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              title: c.messages.length === 0 ? q.slice(0, 24) : c.title,
              updatedAt: Date.now(),
              messages: [...c.messages, userMsg],
            }
          : c,
      ),
    );
    setQuestion("");

    try {
      const res = await askQuestion(q, { topK: 5 });
      const botMsg: Msg = { id: uid(), role: "assistant", text: res.answer, res };
      setConvs((prev) =>
        prev.map((c) =>
          c.id === convId ? { ...c, updatedAt: Date.now(), messages: [...c.messages, botMsg] } : c,
        ),
      );
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e);
      setErr(msg);
      setConvs((prev) =>
        prev.map((c) =>
          c.id === convId
            ? { ...c, messages: [...c.messages, { id: uid(), role: "assistant", text: "", error: msg }] }
            : c,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  const empty = messages.length === 0;

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <div className="flex min-h-0 flex-1">
        {/* 左：对话历史 */}
        <aside className="hidden w-60 shrink-0 flex-col border-r border-border/70 lg:flex">
          <div className="flex items-center justify-between px-3 py-3">
            <span className="section-label">对话历史</span>
            <Button variant="subtle" size="sm" onClick={newConv} title="新建对话">
              <Plus className="h-3.5 w-3.5" />
              新建
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-2 pb-4">
            {convs.length === 0 && (
              <p className="px-2 py-6 text-[12px] leading-6 text-muted-foreground/70">
                还没有对话。问第一个问题就会出现在这里，刷新或切页面都不会丢。
              </p>
            )}
            <ul className="space-y-1">
              {convs.map((c) => (
                <li key={c.id}>
                  <div
                    className={cn(
                      "group flex items-center gap-1 rounded-lg px-2 py-1.5 text-[12.5px] transition-colors",
                      c.id === activeId
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-muted/50",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => setActiveId(c.id)}
                      className="min-w-0 flex-1 truncate text-left"
                      title={c.title}
                    >
                      {c.title || "新对话"}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeConv(c.id)}
                      className="shrink-0 rounded p-1 text-muted-foreground/50 opacity-0 transition hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                      title="删除这个对话"
                      aria-label="删除对话"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        {/* 右：对话区 */}
        <main className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 overflow-auto">
            <div className="mx-auto w-full max-w-3xl px-5 pb-6 pt-8">
              {/* ★busy 时一定走对话视图：否则首问在消息落库前仍显示空态，
                  "思考中"动画就永远出不来（后端秒失败时尤其明显） */}
              {empty && !busy ? (
                <div className="flex min-h-[46vh] flex-col items-center justify-center text-center">
                  <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/10">
                    <Sparkles className="h-5 w-5 text-primary" />
                  </div>
                  <h1 className="text-[20px] font-semibold tracking-tight">问点什么</h1>
                  <p className="mt-2 max-w-md text-[13px] leading-6 text-muted-foreground">
                    只依据库内文献作答，每个论断都挂出处；查不到就明确拒答，不猜。
                  </p>
                  <div className="mt-6 flex flex-wrap justify-center gap-2">
                    {EXAMPLES.map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        disabled={busy}
                        onClick={() => void submit(ex)}
                        className="flex items-center gap-1.5 rounded-full border border-border/80 bg-card px-3 py-1.5 text-[12px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                      >
                        <Search className="h-3 w-3 opacity-60" />
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-7">
                  {messages.map((m) =>
                    m.role === "user" ? (
                      <div key={m.id} className="flex justify-end">
                        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14px] leading-6 text-primary-foreground shadow-sm">
                          {m.text}
                        </div>
                      </div>
                    ) : m.error ? (
                      <Alert key={m.id} variant="destructive">
                        请求失败：{m.error}
                      </Alert>
                    ) : (
                      <AssistantBubble key={m.id} res={m.res!} />
                    ),
                  )}
                  {busy && <Thinking />}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>
          </div>

          {/* 输入区：空态在中间，有对话后落到底部 */}
          <div className={cn("border-t border-border/60 bg-background/80 backdrop-blur", empty && "border-t-0")}>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void submit(question);
              }}
              className="mx-auto flex w-full max-w-3xl items-center gap-2 px-5 py-4"
            >
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="问点什么，例如：训练用了多少块 GPU？"
                aria-label="问题"
                className="h-11"
              />
              <Button type="submit" size="lg" disabled={busy || !question.trim()} className="shrink-0">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {busy ? "思考中" : "发送"}
              </Button>
            </form>
            {err && (
              <p className="mx-auto w-full max-w-3xl px-5 pb-3 text-[11px] text-destructive/80">{err}</p>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

/** 思考中：转圈 + 逐条点亮的步骤，替代原来四行静止文字 */
function Thinking() {
  const [step, setStep] = useState(0);
  const names = ["plan", "retrieve", "answer", "verify"];
  useEffect(() => {
    const t = setInterval(() => setStep((s) => Math.min(s + 1, names.length - 1)), 1100);
    return () => clearInterval(t);
  }, [names.length]);

  return (
    <div className="animate-fade-up flex gap-3">
      <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
      </span>
      <div className="flex-1">
        <p className="text-[13px] text-muted-foreground">
          {NODE_LABEL[names[step]]}
          <span className="ml-1 inline-flex gap-0.5 align-baseline">
            <span className="thinking-dot" />
            <span className="thinking-dot" style={{ animationDelay: "160ms" }} />
            <span className="thinking-dot" style={{ animationDelay: "320ms" }} />
          </span>
        </p>
        <div className="mt-2 flex gap-1">
          {names.map((n, i) => (
            <span
              key={n}
              className={cn(
                "h-1 w-8 rounded-full transition-colors duration-500",
                i <= step ? "bg-primary/60" : "bg-border",
              )}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function AssistantBubble({ res }: { res: QAResult }) {
  const totalMs = res.steps.reduce((s, x) => s + x.ms, 0);
  return (
    <div className="animate-fade-up flex gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <Sparkles className="h-3.5 w-3.5 text-primary" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
          {res.refused ? (
            <Badge variant="secondary">未找到依据 · 已拒答</Badge>
          ) : (
            <Badge variant="success">已作答 · {res.citations.length} 处出处</Badge>
          )}
          <span>{res.orchestrator}</span>
          <span className="text-border">·</span>
          <span className="tabular">{Math.round(totalMs)} ms</span>
        </div>

        <Card className="px-4 py-3">
          <p className="whitespace-pre-wrap text-[14.5px] leading-7">{renderAnswer(res.answer)}</p>
        </Card>

        {res.invalid_citations.length > 0 && (
          <Alert variant="warning" className="mt-2">
            已剔除 {res.invalid_citations.length} 条无法核实的出处
          </Alert>
        )}

        <details className="group mt-2">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-[11px] uppercase tracking-widest text-muted-foreground/80 transition hover:text-foreground">
            思考过程
            <span className="inline-block transition group-open:rotate-90">›</span>
          </summary>
          <ol className="mt-3 space-y-3 border-l border-border pl-4">
            {res.steps.map((s, i) => (
              <li key={`${s.node}-${i}`} className="relative">
                <span className="absolute -left-[19px] top-1.5 h-1.5 w-1.5 rounded-full bg-primary/60" />
                <div className="flex items-baseline justify-between gap-3">
                  <p className="font-mono text-[10.5px] uppercase tracking-widest text-muted-foreground">
                    {s.node}
                    <span className="ml-2 normal-case tracking-normal text-muted-foreground/60">
                      {NODE_LABEL[s.node] ?? ""}
                    </span>
                  </p>
                  <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-muted-foreground/60">
                    {s.ms >= 1000 ? `${(s.ms / 1000).toFixed(1)}s` : `${Math.round(s.ms)}ms`}
                  </span>
                </div>
                <p className="mt-0.5 break-words text-[12px] leading-6 text-muted-foreground">{s.detail}</p>
              </li>
            ))}
          </ol>
        </details>

        {res.hits.length > 0 && (
          <details className="group mt-1.5">
            <summary className="flex cursor-pointer list-none items-center gap-1 text-[11px] uppercase tracking-widest text-muted-foreground/80 transition hover:text-foreground">
              依据片段（{res.hits.length}）
              <span className="inline-block transition group-open:rotate-90">›</span>
            </summary>
            <ul className="mt-3 space-y-2">
              {res.hits.map((h) => (
                <li key={h.chunk_id} className="rounded-lg border border-border/60 bg-card px-3 py-2">
                  <div className="mb-1 flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-muted-foreground">
                    <span className="text-foreground/80">{h.page}</span>
                    <span className="text-border">·</span>
                    <span>{h.section}</span>
                  </div>
                  <p className="line-clamp-3 text-[12px] leading-6 text-muted-foreground">{h.text}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
