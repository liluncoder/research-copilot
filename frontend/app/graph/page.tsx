"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getGraph, reviewGraph, type GraphData, type GraphNode } from "@/lib/api";

type Metric = "pagerank_core" | "cited_by_local";

const LOCAL_COLOR = "#85B7EB";
const EXT_COLOR = "#B4B2A9";
const LOCAL_EDGE = "#5DCAA5";
const EXT_EDGE = "rgba(140,140,135,0.35)";

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
            borderColor: n.id === selected ? "#5DCAA5" : "transparent",
            borderWidth: n.id === selected ? 2 : 0,
          },
          label: {
            show: n.in_library || topIds.has(n.id) || n.id === selected,
            formatter: n.label.length > 26 ? `${n.label.slice(0, 26)}…` : n.label,
            color: "#D3D1C7",
            fontSize: 11,
          },
          raw: n,
        };
      });

      const links = data.display.edges.map((e) => {
        const active =
          !neighbors || (neighbors.has(e.source) && neighbors.has(e.target));
        return {
          source: e.source,
          target: e.target,
          lineStyle: {
            color: active ? (neighbors ? LOCAL_EDGE : EXT_EDGE) : "rgba(140,140,135,0.08)",
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
          tooltip: {
            backgroundColor: "#1b1d21",
            borderColor: "#33363b",
            textStyle: { color: "#e8e8e6", fontSize: 12 },
            formatter: (p: { data?: { raw?: GraphNode } }) => {
              const n = p.data?.raw;
              if (!n) return "";
              return [
                `<div style="max-width:320px;white-space:normal;line-height:1.5">${n.label}</div>`,
                `<div style="color:#9aa0a6;margin-top:4px">${n.in_library ? "库内文献" : "外部文献"}${
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

  const ranking = data ? (metric === "pagerank_core" ? data.foundational.pagerank : data.foundational.in_degree) : [];

  return (
    <main className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border/60 px-5 py-3">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← 首页
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-sm font-medium">引用图谱</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {data
              ? `${data.stats.n_nodes} 节点 / ${data.stats.n_edges} 边 · 库内 ${data.stats.n_local} 篇 · 参考文献 ${data.stats.n_reference_entries} 条 · 匹配到库内 ${data.stats.n_matched_to_local} 条（${(data.stats.local_match_rate * 100).toFixed(1)}%）`
              : "载入中…"}
          </p>
        </div>
        <div className="flex overflow-hidden rounded-md border border-border/70 text-xs">
          {(
            [
              ["pagerank_core", "PageRank"],
              ["cited_by_local", "入度"],
            ] as [Metric, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setMetric(k)}
              className={`px-3 py-1.5 transition ${
                metric === k ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => void makeReview()}
          disabled={busy}
          className="h-8 rounded-md border border-primary/40 bg-primary/10 px-3 text-xs text-primary transition hover:bg-primary/20 disabled:opacity-40"
        >
          {busy ? "生成中…" : "生成自动综述"}
        </button>
      </header>

      {err && <p className="px-5 py-3 text-sm text-destructive">{err}</p>}

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_20rem]">
        <div className="relative min-h-0">
          <div ref={boxRef} className="h-full w-full" />
          <div className="pointer-events-none absolute bottom-4 left-4 flex gap-4 text-[11px] text-muted-foreground">
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

        <aside className="min-h-0 overflow-auto border-l border-border/60 px-4 py-4">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
            基石论文 · {metric === "pagerank_core" ? "PageRank(核心)" : "被本库引用"}
          </p>
          <ol className="space-y-1">
            {ranking.slice(0, 10).map((n, i) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => setSelected(selected === n.id ? null : n.id)}
                  className={`flex w-full gap-2 rounded px-2 py-1.5 text-left text-[12px] transition ${
                    selected === n.id ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/30"
                  }`}
                >
                  <span className="w-4 shrink-0 font-mono text-[10px] text-muted-foreground/60">{i + 1}</span>
                  <span className="flex-1">
                    <span className="line-clamp-2">{n.label}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground/70">
                      {n.in_library ? "库内" : "外部"} · 入度 {n.cited_by_local} · PR {n.pagerank_core.toFixed(4)}
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
              <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                自动综述
              </p>
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
    </main>
  );
}
