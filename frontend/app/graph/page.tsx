"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { getGraph, reviewGraph, type GraphData, type GraphNode } from "@/lib/api";
import { SiteHeader } from "@/components/site-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";

type Metric = "pagerank_core" | "cited_by_local";

/*
 * ★浅色主题的图谱配色：原来节点标签写死 #D3D1C7（深色底上的浅字），
 *   切到暖白底后标签几乎看不见。现在主色/成功色与站点 token 对齐。
 */
const LOCAL_COLOR = "#3E498E";
const EXT_COLOR = "#B9B6AD";
const LOCAL_EDGE = "#2F6A5E";
const EXT_EDGE = "rgba(120,118,112,0.35)";
const LABEL_COLOR = "#52525B";

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [metric, setMetric] = useState<Metric>("pagerank_core");
  const [selected, setSelected] = useState<string | null>(null);
  const [review, setReview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<{
    setOption: (o: unknown, notMerge?: boolean) => void;
    dispose: () => void;
    resize: () => void;
    on: (ev: string, fn: (p: { data?: { id?: string } }) => void) => void;
  } | null>(null);
  const echartsRef = useRef<{ init: (el: HTMLElement) => unknown } | null>(null);

  useEffect(() => {
    getGraph(40, 12)
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  // 邻居集合（点击高亮邻域）
  const neighbors = useMemo(() => {
    if (!data || !selected) return null;
    const s = new Set<string>([selected]);
    for (const e of data.display.edges) {
      if (e.source === selected) s.add(e.target);
      if (e.target === selected) s.add(e.source);
    }
    return s;
  }, [data, selected]);

  useEffect(() => {
    if (!data || !boxRef.current) return;
    let disposed = false;

    (async () => {
      if (!echartsRef.current) {
        const mod = await import("echarts");
        echartsRef.current = mod as unknown as { init: (el: HTMLElement) => unknown };
      }
      if (disposed || !boxRef.current) return;
      const chart = chartRef.current ?? (echartsRef.current!.init(boxRef.current) as never);
      chartRef.current = chart as never;

      const maxVal = Math.max(...data.display.nodes.map((n) => n[metric]), 1e-9);
      const topIds = new Set(
        [...data.display.nodes]
          .sort((a, b) => b[metric] - a[metric])
          .slice(0, 10)
          .map((n) => n.id),
      );

      const nodes = data.display.nodes.map((n) => {
        const active = !neighbors || neighbors.has(n.id);
        const size = 8 + 34 * Math.sqrt(n[metric] / maxVal);
        return {
          id: n.id,
          name: n.label,
          symbolSize: n.id === selected ? size + 8 : size,
          itemStyle: {
            color: n.in_library ? LOCAL_COLOR : EXT_COLOR,
            opacity: active ? 1 : 0.15,
            borderColor: n.id === selected ? LOCAL_EDGE : "transparent",
            borderWidth: n.id === selected ? 2 : 0,
          },
          label: {
            show: n.in_library || topIds.has(n.id) || n.id === selected,
            formatter: n.label.length > 26 ? `${n.label.slice(0, 26)}…` : n.label,
            color: LABEL_COLOR,
            fontSize: 11,
          },
          raw: n,
        };
      });

      const links = data.display.edges.map((e) => {
        const active = !neighbors || (neighbors.has(e.source) && neighbors.has(e.target));
        return {
          source: e.source,
          target: e.target,
          lineStyle: {
            color: active ? (neighbors ? LOCAL_EDGE : EXT_EDGE) : "rgba(120,118,112,0.08)",
            width: active ? 1.2 : 0.6,
            curveness: 0.08,
          },
        };
      });

      if (!(chart as unknown as { __bound?: boolean }).__bound) {
        (chart as unknown as { __bound?: boolean }).__bound = true;
        chart.on("click", (p) => setSelected(p?.data?.id ?? null));
      }

      chart.setOption(
        {
          backgroundColor: "transparent",
          textStyle: { color: LABEL_COLOR },
          // 浅色主题下用白底 tooltip；深色 tooltip 在暖白页面里像一块补丁
          tooltip: {
            backgroundColor: "#ffffff",
            borderColor: "#E7E4DE",
            textStyle: { color: "#26282D", fontSize: 12 },
            extraCssText: "box-shadow:0 6px 20px rgba(24,24,27,.10);border-radius:10px;",
            formatter: (p: { data?: { raw?: GraphNode } }) => {
              const n = p.data?.raw;
              if (!n) return "";
              return [
                `<div style="max-width:320px;white-space:normal;line-height:1.5">${n.label}</div>`,
                `<div style="color:#6B7280;margin-top:4px">${n.in_library ? "库内文献" : "外部文献"}${
                  n.year ? ` · ${n.year}` : ""
                }</div>`,
                `<div style="margin-top:4px">被本库引用 <b>${n.cited_by_local}</b> 次 · 引用他人 <b>${n.cites}</b> 篇</div>`,
                `<div>PageRank(核心) <b>${n.pagerank_core.toFixed(4)}</b></div>`,
              ].join("");
            },
          },
          series: [
            {
              type: "graph",
              layout: "force",
              roam: true,
              draggable: true,
              force: { repulsion: 130, edgeLength: [60, 130], gravity: 0.12, friction: 0.2 },
              emphasis: { focus: "adjacency", lineStyle: { width: 2 } },
              data: nodes,
              links,
            },
          ],
        },
        false,
      );
      chart.resize();
    })();

    return () => {
      disposed = true;
    };
  }, [data, metric, selected, neighbors]);

  useEffect(() => {
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  async function makeReview() {
    setBusy(true);
    setReview(null);
    try {
      const r = await reviewGraph(8);
      setReview(r.error ? `生成失败：${r.error}` : r.review);
    } catch (e) {
      setReview(`生成失败：${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const ranking = data
    ? metric === "pagerank_core"
      ? data.foundational.pagerank
      : data.foundational.in_degree
    : [];

  return (
    <div className="flex h-screen flex-col">
      <SiteHeader />

      <div className="toolbar">
        <div className="min-w-0 flex-1">
          <h1 className="text-[13px] font-medium">引用图谱</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {data
              ? `${data.stats.n_nodes} 节点 / ${data.stats.n_edges} 边 · 库内 ${data.stats.n_local} 篇 · 参考文献 ${data.stats.n_reference_entries} 条 · 匹配到库内 ${data.stats.n_matched_to_local} 条（${(data.stats.local_match_rate * 100).toFixed(1)}%）`
              : "载入中…"}
          </p>
        </div>
        <Segmented
          size="sm"
          label="排序指标"
          value={metric}
          onChange={(v) => setMetric(v as Metric)}
          options={[
            { value: "pagerank_core", label: "PageRank" },
            { value: "cited_by_local", label: "入度" },
          ]}
        />
        <Button variant="selected" size="sm" onClick={() => void makeReview()} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {busy ? "生成中…" : "生成自动综述"}
        </Button>
      </div>

      {err && (
        <Alert variant="destructive" className="m-3">
          {err}
        </Alert>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_20rem]">
        <div className="relative min-h-0">
          <div ref={boxRef} className="h-full w-full" />
          <div className="pointer-events-none absolute bottom-4 left-4 flex flex-wrap gap-4 rounded-lg bg-card/80 px-3 py-2 text-[11px] text-muted-foreground backdrop-blur-sm">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: LOCAL_COLOR }} />
              库内文献
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: EXT_COLOR }} />
              被引用的外部文献
            </span>
            <span>节点大小 = {metric === "pagerank_core" ? "PageRank" : "被本库引用次数"}</span>
          </div>
        </div>

        <aside className="hidden min-h-0 overflow-auto border-l border-border/60 px-4 py-4 lg:block">
          <div className="section-label mb-2">
            基石论文 · {metric === "pagerank_core" ? "PageRank(核心)" : "被本库引用"}
          </div>
          <ol className="space-y-1">
            {ranking.slice(0, 10).map((n, i) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => setSelected(selected === n.id ? null : n.id)}
                  className={`flex w-full gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition-colors ${
                    selected === n.id
                      ? "bg-primary/10 text-foreground"
                      : "text-muted-foreground hover:bg-muted/40"
                  }`}
                >
                  <span className="w-4 shrink-0 font-mono text-[10px] text-muted-foreground/60">
                    {i + 1}
                  </span>
                  <span className="flex-1">
                    <span className="line-clamp-2">{n.label}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground/70">
                      {n.in_library ? "库内" : "外部"} · 入度 {n.cited_by_local} · PR{" "}
                      {n.pagerank_core.toFixed(4)}
                      {n.year ? ` · ${n.year}` : ""}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ol>

          <p className="mt-4 border-t border-border/50 pt-3 text-[11px] leading-5 text-muted-foreground/80">
            {data?.foundational.note}
          </p>

          {(review || busy) && (
            <div className="mt-4 border-t border-border/50 pt-3">
              <div className="section-label mb-2">自动综述</div>
              <p className="whitespace-pre-wrap text-[12px] leading-6 text-foreground/85">
                {busy ? "正在依据图谱统计生成…" : review}
              </p>
              <p className="mt-2 text-[10px] text-muted-foreground/60">
                只依据上方结构化统计生成，未读取论文正文。
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
