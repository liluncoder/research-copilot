"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { PageHeader, SiteShell } from "@/components/site-shell";
import {
  buildFramework,
  makeFigure,
  translateAbstract,
  type FigureResult,
  type FrameworkResult,
} from "@/lib/api";

type Tab = "figure" | "framework";

export default function WritePage() {
  const [tab, setTab] = useState<Tab>("figure");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // ---- J7 ----
  const [fig, setFig] = useState<FigureResult | null>(null);
  const chartBox = useRef<HTMLDivElement>(null);
  const chartInst = useRef<{ setOption: (o: unknown, n?: boolean) => void; resize: () => void; dispose: () => void } | null>(null);

  // ---- J8 ----
  const [topic, setTopic] = useState("局部学习规则在脉冲神经网络中的信用分配");
  const [fw, setFw] = useState<FrameworkResult | null>(null);
  const [en, setEn] = useState<string | null>(null);

  async function runFigure(blob: Blob, name: string) {
    setBusy(true);
    setErr(null);
    setFig(null);
    try {
      const r = await makeFigure(blob, { metric: "correct", groupBy: "condition", kind: "line", filename: name });
      setFig(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!fig || !chartBox.current) return;
    let disposed = false;
    (async () => {
      const echarts = await import("echarts");
      if (disposed || !chartBox.current) return;
      const inst = chartInst.current ?? (echarts.init(chartBox.current) as never);
      chartInst.current = inst as never;
      (inst as { setOption: (o: unknown, n?: boolean) => void }).setOption(
        { ...fig.chart, backgroundColor: "transparent", textStyle: { color: "#d8d8d5" } },
        true,
      );
      (inst as { resize: () => void }).resize();
    })();
    return () => {
      disposed = true;
    };
  }, [fig]);

  useEffect(() => () => chartInst.current?.dispose(), []);

  async function runFramework() {
    setBusy(true);
    setErr(null);
    setFw(null);
    setEn(null);
    try {
      const r = await buildFramework(topic);
      if (r.error) setErr(r.error);
      setFw(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runTranslate() {
    const abstract = fw?.sections?.Abstract;
    if (!abstract) return;
    setBusy(true);
    try {
      const r = await translateAbstract(abstract);
      setEn(r.error ? `翻译失败：${r.error}` : r.text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SiteShell width="narrow">
      <PageHeader title="写作 Copilot" desc="数据出图，图注只依据统计量；论文框架的参考文献只从库内选，编造一条都算失败。" />

        <div className="mb-6 flex gap-1 rounded-lg border border-border/60 p-1 text-sm">
          {(
            [
              ["figure", "图表 + 图注（J7）"],
              ["framework", "论文框架（J8）"],
            ] as [Tab, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`flex-1 rounded-md px-3 py-2 transition ${
                tab === k ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {err && <p className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm">{err}</p>}

        {tab === "figure" && (
          <section className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void runFigure(f, f.name);
                }}
                className="text-xs file:mr-3 file:rounded-md file:border-0 file:bg-primary/15 file:px-3 file:py-1.5 file:text-primary"
              />
              <button
                type="button"
                onClick={async () => {
                  const r = await fetch("/sample_snn_trials.csv");
                  void runFigure(await r.blob(), "snn_trials.csv");
                }}
                className="rounded-md border border-border/70 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
              >
                用示例数据（SNN 仿真 640 次 trial）
              </button>
              {busy && <span className="text-xs text-muted-foreground">处理中…</span>}
            </div>

            {fig && (
              <>
                <div ref={chartBox} className="h-[320px] w-full rounded-xl border border-border/60" />
                <div className="rounded-xl border border-border/60 px-5 py-4">
                  <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    图注（仅依据统计量生成）
                  </p>
                  <p className="text-[14px] leading-7">{fig.caption || "（未配置 LLM，图注为空）"}</p>
                </div>
                <details className="rounded-xl border border-border/60 px-5 py-3">
                  <summary className="cursor-pointer text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    喂给模型的统计量（可核对）
                  </summary>
                  <pre className="mt-3 overflow-auto text-[11px] leading-5 text-muted-foreground">
                    {JSON.stringify(fig.stats, null, 2)}
                  </pre>
                </details>
              </>
            )}
            {!fig && !busy && (
              <p className="text-sm text-muted-foreground">
                上传一份 CSV（需要数值列），或点上面的示例数据。CSV 的每一行都会被统计，图注只能看到统计量。
              </p>
            )}
          </section>
        )}

        {tab === "framework" && (
          <section className="space-y-4">
            <div className="flex gap-2">
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                className="h-10 flex-1 rounded-lg border border-border/70 bg-transparent px-3 text-sm outline-none focus:border-primary/60"
                placeholder="论文主题"
              />
              <button
                type="button"
                onClick={() => void runFramework()}
                disabled={busy || topic.trim().length < 2}
                className="h-10 rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground disabled:opacity-40"
              >
                {busy ? "生成中" : "生成框架"}
              </button>
            </div>

            {fw && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="rounded-full border border-border/70 px-2 py-0.5">
                    候选 {fw.n_candidates} 篇
                  </span>
                  <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-primary">
                    引用 {fw.references.length} 条 · 全部来自库内
                  </span>
                  {fw.invalid_refs.length > 0 ? (
                    <span className="rounded-full border border-destructive/40 bg-destructive/10 px-2 py-0.5 text-destructive">
                      剔除编造引用 {fw.invalid_refs.length} 条
                    </span>
                  ) : (
                    <span className="rounded-full border border-border/70 px-2 py-0.5">零编造</span>
                  )}
                </div>

                {Object.entries(fw.sections).map(([name, text]) => (
                  <article key={name} className="rounded-xl border border-border/60 px-5 py-4">
                    <h2 className="mb-2 text-sm font-medium">{name}</h2>
                    <p className="whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">{text}</p>
                  </article>
                ))}

                <div className="rounded-xl border border-border/60 px-5 py-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h2 className="text-sm font-medium">References（由本地元数据渲染）</h2>
                    <button
                      type="button"
                      onClick={() => void runTranslate()}
                      disabled={busy}
                      className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1 text-[11px] text-primary disabled:opacity-40"
                    >
                      摘要译成英文
                    </button>
                  </div>
                  <ol className="space-y-1.5 text-[12px] text-muted-foreground">
                    {fw.references.map((r) => (
                      <li key={r.doc_id}>
                        <span className="mr-1.5 font-mono text-[11px] text-foreground/60">[{r.n}]</span>
                        {r.authors.slice(0, 3).join(", ")}
                        {r.authors.length > 3 ? " et al." : ""}. {r.title}. {r.year ?? "年份未知"}.
                      </li>
                    ))}
                  </ol>
                </div>

                {en && (
                  <article className="rounded-xl border border-primary/25 bg-primary/5 px-5 py-4">
                    <h2 className="mb-2 text-sm font-medium text-primary">Abstract (English)</h2>
                    <p className="whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">{en}</p>
                  </article>
                )}
              </div>
            )}
            {!fw && !busy && (
              <p className="text-sm text-muted-foreground">
                输入主题后生成 Abstract / Introduction / Related Work；正文里的引用编号只能来自库内文献，
                参考文献条目由系统按元数据渲染，模型无法自己写条目。
              </p>
            )}
          </section>
        )}
    </SiteShell>
  );
}
