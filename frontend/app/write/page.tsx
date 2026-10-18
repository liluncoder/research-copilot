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
  const chartInst = useRef<{
    setOption: (o: unknown, n?: boolean) => void;
    resize: () => void;
    dispose: () => void;
  } | null>(null);

  // ---- J8 ----
  const [topic, setTopic] = useState("局部学习规则在脉冲神经网络中的信用分配");
  const [fw, setFw] = useState<FrameworkResult | null>(null);
  const [en, setEn] = useState<string | null>(null);

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
          { value: "figure", label: "图表 + 图注（J7）" },
          { value: "framework", label: "论文框架（J8）" },
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
                    喂给模型的统计量（可核对）
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
    </SiteShell>
  );
}
