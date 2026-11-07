"use client";

import { useEffect, useRef, useState } from "react";
import { BarChart3, FileUp, Languages, Loader2 } from "lucide-react";
import { PageHeader, SiteShell } from "@/components/site-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import {
  buildFramework,
  futureWork,
  listDocuments,
  makeDiagram,
  makeFigure,
  translateAbstract,
  type DiagramResult,
  type DocumentMeta,
  type FigureResult,
  type FrameworkResult,
  type FutureWorkResult,
} from "@/lib/api";

type Tab = "figure" | "framework" | "diagram" | "future";

export default function WritePage() {
  const [tab, setTab] = useState<Tab>("figure");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // ---- J7 ----
  const [fig, setFig] = useState<FigureResult | null>(null);
  const chartBox = useRef<HTMLDivElement>(null);
  const chartInst = useRef<{
    setOption: (o: unknown, n?: boolean) => void;
    resize: () => void;
    dispose: () => void;
  } | null>(null);

  // ---- J8 ----
  const [topic, setTopic] = useState("局部学习规则在脉冲神经网络中的信用分配");
  const [fw, setFw] = useState<FrameworkResult | null>(null);
  const [en, setEn] = useState<string | null>(null);

  // ---- J9 架构拓扑图（官方 1.6.2）----
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [docId, setDocId] = useState("");
  const [diagram, setDiagram] = useState<DiagramResult | null>(null);

  useEffect(() => {
    if (docs.length) return;
    void listDocuments()
      .then((r) => {
        setDocs(r.items);
        if (!docId && r.items[0]) setDocId(r.items[0].doc_id);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- J10 未来工作探索（官方 1.5.4）----
  const [fut, setFut] = useState<FutureWorkResult | null>(null);

  async function runFuture() {
    setBusy(true);
    setErr(null);
    setFut(null);
    try {
      setFut(await futureWork());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runDiagram() {
    if (!docId) return;
    setBusy(true);
    setErr(null);
    setDiagram(null);
    try {
      setDiagram(await makeDiagram(docId));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runFigure(blob: Blob, name: string) {
    setBusy(true);
    setErr(null);
    setFig(null);
    try {
      const r = await makeFigure(blob, {
        metric: "correct",
        groupBy: "condition",
        kind: "line",
        filename: name,
      });
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
        {
          ...fig.chart,
          backgroundColor: "transparent",
          // ★浅色主题：原来写死 #d8d8d5（深色主题的灰白字），在白底上几乎看不见
          textStyle: { color: "#3f3f46" },
        },
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
      <PageHeader
        title="写作 Copilot"
        desc="数据出图，图注只依据统计量；论文框架的参考文献只从库内选，编造一条都算失败。"
      />

      <Segmented
        fullWidth
        label="写作功能"
        value={tab}
        onChange={(v) => setTab(v as Tab)}
        options={[
          { value: "figure", label: "图表 + 图注" },
          { value: "framework", label: "论文框架" },
          { value: "diagram", label: "架构拓扑图" },
          { value: "future", label: "未来工作" },
        ]}
        className="mb-6"
      />

      {err && (
        <Alert variant="destructive" className="mb-4">
          {err}
        </Alert>
      )}

      {tab === "figure" && (
        <section className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-center gap-3">
              <Input
                type="file"
                accept=".csv,text/csv"
                aria-label="上传 CSV"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void runFigure(f, f.name);
                }}
                className="h-9 w-auto max-w-full cursor-pointer py-1.5 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-[12px] file:text-foreground/80 hover:file:bg-muted/70"
              />
              <Button
                variant="subtle"
                size="sm"
                disabled={busy}
                onClick={async () => {
                  const r = await fetch("/sample_snn_trials.csv");
                  void runFigure(await r.blob(), "snn_trials.csv");
                }}
              >
                <FileUp className="h-3.5 w-3.5" />
                用示例数据（SNN 仿真 640 次 trial）
              </Button>
              {busy && (
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  处理中…
                </span>
              )}
            </div>
          </Card>

          {fig && (
            <>
              <Card className="p-2">
                <div ref={chartBox} className="h-[320px] w-full" />
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    图注（仅依据统计量生成）
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-[14px] leading-7">{fig.caption || "（未配置 LLM，图注为空）"}</p>
                </CardContent>
              </Card>
              <Card>
                <details className="group px-5 py-3">
                  <summary className="cursor-pointer list-none text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    图注依据（可展开核对）
                    <span className="ml-1 inline-block transition group-open:rotate-90">›</span>
                  </summary>
                  <pre className="mt-3 overflow-auto text-[11px] leading-5 text-muted-foreground">
                    {JSON.stringify(fig.stats, null, 2)}
                  </pre>
                </details>
              </Card>
            </>
          )}

          {!fig && !busy && (
            <EmptyState
              icon={<BarChart3 className="h-5 w-5" />}
              title="还没有生成图表"
              description="上传一份 CSV（需要数值列），或点上面的示例数据。CSV 的每一行都会被统计，图注只能看到统计量。"
            />
          )}
        </section>
      )}

      {tab === "framework" && (
        <section className="space-y-4">
          <div className="flex gap-2">
            <Input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="论文主题"
              aria-label="论文主题"
            />
            <Button
              onClick={() => void runFramework()}
              disabled={busy || topic.trim().length < 2}
              className="shrink-0"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {busy ? "生成中" : "生成框架"}
            </Button>
          </div>

          {fw && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">候选 {fw.n_candidates} 篇</Badge>
                <Badge variant="success">
                  引用 {fw.references.length} 条 · 全部来自库内
                </Badge>
                {fw.invalid_refs.length > 0 ? (
                  <Badge variant="destructive">剔除编造引用 {fw.invalid_refs.length} 条</Badge>
                ) : (
                  <Badge variant="secondary">零编造</Badge>
                )}
              </div>

              {Object.entries(fw.sections).map(([name, text]) => (
                <Card key={name}>
                  <CardHeader>
                    <CardTitle>{name}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">
                      {text}
                    </p>
                  </CardContent>
                </Card>
              ))}

              <Card>
                <CardHeader className="flex-row items-center justify-between gap-3">
                  <CardTitle>References（由本地元数据渲染）</CardTitle>
                  <Button
                    variant="selected"
                    size="sm"
                    onClick={() => void runTranslate()}
                    disabled={busy}
                  >
                    <Languages className="h-3.5 w-3.5" />
                    摘要译成英文
                  </Button>
                </CardHeader>
                <CardContent>
                  <ol className="space-y-1.5 text-[12px] leading-6 text-muted-foreground">
                    {fw.references.map((r) => (
                      <li key={r.doc_id}>
                        <span className="mr-1.5 font-mono text-[11px] text-foreground/60">
                          [{r.n}]
                        </span>
                        {r.authors.slice(0, 3).join(", ")}
                        {r.authors.length > 3 ? " et al." : ""}. {r.title}. {r.year ?? "年份未知"}.
                      </li>
                    ))}
                  </ol>
                </CardContent>
              </Card>

              {en && (
                <Card variant="accent">
                  <CardHeader>
                    <CardTitle className="text-primary">Abstract (English)</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">
                      {en}
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {!fw && !busy && (
            <EmptyState
              icon={<FileUp className="h-5 w-5" />}
              title="输入主题后生成论文框架"
              description="生成 Abstract / Introduction / Related Work；正文里的引用编号只能来自库内文献，参考文献条目由系统按元数据渲染，模型无法自己写条目。"
            />
          )}
        </section>
      )}

      {tab === "diagram" && (
        <section className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-center gap-3">
              <select
                aria-label="选择论文"
                value={docId}
                onChange={(e) => setDocId(e.target.value)}
                className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-3 text-[13px]"
              >
                {docs.length === 0 && <option value="">库中暂无文献</option>}
                {docs.map((d) => (
                  <option key={d.doc_id} value={d.doc_id}>
                    {d.title || d.filename}
                  </option>
                ))}
              </select>
              <Button onClick={() => void runDiagram()} disabled={busy || !docId} className="shrink-0">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {busy ? "生成中" : "生成拓扑图"}
              </Button>
            </div>
            <p className="mt-3 text-[12px] leading-6 text-muted-foreground">
              节点只取自这篇论文自己的章节树；父子层级由系统推导，模型只负责连"逻辑关系"边。
              模型点名不存在的节点会被丢弃并计数——它画不出论文里没有的章节。
            </p>
          </Card>

          {diagram && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                <Badge variant="outline">{diagram.n_nodes} 节点</Badge>
                <Badge variant="outline">{diagram.n_tree_edges} 条层级边</Badge>
                <Badge variant="outline">{diagram.n_logic_edges} 条逻辑边</Badge>
                {diagram.invalid_edges.length > 0 ? (
                  <Badge variant="destructive">拦下伪造节点 {diagram.invalid_edges.length}</Badge>
                ) : (
                  <Badge variant="success">零伪造节点</Badge>
                )}
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    Mermaid 源码（可直接复制进 Markdown / 绘图工具）
                  </CardTitle>
                  <Button
                    variant="subtle"
                    size="sm"
                    onClick={() => void navigator.clipboard.writeText(diagram.mermaid)}
                  >
                    复制
                  </Button>
                </CardHeader>
                <CardContent>
                  <pre className="max-h-80 overflow-auto text-[11px] leading-5 text-foreground/80">
                    {diagram.mermaid}
                  </pre>
                </CardContent>
              </Card>

              {diagram.notes.length > 0 && (
                <p className="text-[12px] leading-6 text-muted-foreground">
                  {diagram.notes.join("；")}
                </p>
              )}
            </>
          )}

          {!diagram && !busy && (
            <EmptyState
              icon={<FileUp className="h-5 w-5" />}
              title="选一篇论文，生成架构拓扑图"
              description="输出 Mermaid / Graphviz DOT / LaTeX TikZ 三种格式，可直接复制进论文或 Markdown。"
            />
          )}
        </section>
      )}

      {tab === "future" && (
        <section className="space-y-4">
          <Card className="p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] leading-6 text-muted-foreground">
                只读库里各篇论文的 <span className="font-mono text-[11px]">Future Work / Limitation</span> 原句，
                每条建议都必须挂回出处；看不出来的一律不写。
              </p>
              <Button onClick={() => void runFuture()} disabled={busy} className="shrink-0">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {busy ? "挖掘中" : "挖掘未来工作"}
              </Button>
            </div>
          </Card>

          {fut && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                <Badge variant="outline">{fut.n_docs} 篇命中</Badge>
                <Badge variant="outline">{fut.n_snippets} 条原文摘句</Badge>
                <Badge variant="outline">{fut.n_directions} 条方向</Badge>
                {fut.invalid_refs.length > 0 ? (
                  <Badge variant="destructive">拦下伪造出处 {fut.invalid_refs.length}</Badge>
                ) : (
                  <Badge variant="success">零伪造出处</Badge>
                )}
              </div>

              <div className="space-y-3">
                {fut.directions.map((d, i) => (
                  <Card key={`${d.doc_id}-${i}`}>
                    <CardContent className="space-y-2 pt-4">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 font-mono text-[11px] text-muted-foreground/60">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <div className="min-w-0">
                          <p className="text-[14px] leading-6">{d.idea}</p>
                          {d.why && (
                            <p className="mt-1 text-[12px] leading-6 text-muted-foreground">{d.why}</p>
                          )}
                          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/80">
                            <span className="rounded border border-border/70 px-1.5 py-0.5 font-mono">
                              {d.source}
                            </span>
                            <span>{d.status}</span>
                          </p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>

              <Card>
                <details className="px-5 py-3">
                  <summary className="cursor-pointer list-none text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                    原文摘句（{fut.n_snippets} 条，可逐条核对）
                    <span className="ml-1 inline-block">›</span>
                  </summary>
                  <ul className="mt-3 space-y-2 text-[12px] leading-6 text-muted-foreground">
                    {fut.snippets.map((s, i) => (
                      <li key={`${s.doc_id}-${i}`} className="border-l-2 border-border/60 pl-3">
                        <span className="font-mono text-[10px] text-muted-foreground/70">
                          {s.title.slice(0, 40)} · {s.year ?? "n.a."} · {s.section}
                        </span>
                        <p className="text-foreground/80">{s.text}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              </Card>

              {fut.notes.length > 0 && (
                <p className="text-[12px] leading-6 text-muted-foreground">{fut.notes.join("；")}</p>
              )}
            </>
          )}

          {!fut && !busy && (
            <EmptyState
              icon={<FileUp className="h-5 w-5" />}
              title="还没有挖掘未来工作"
              description="点上面的按钮，系统会从库内每篇论文里抽出 Future Work 原句，再让模型只在这些句子范围内提方向。"
            />
          )}
        </section>
      )}
    </SiteShell>
  );
}
