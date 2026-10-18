"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { SiteHeader } from "@/components/site-shell";
import {
  getReader,
  listDocuments,
  translateParagraphs,
  type DocumentMeta,
  type ReaderView,
} from "@/lib/api";

/** 把段落文本里的 [11] / [11, 12] 渲染成可点的小标签。 */
function renderWithCitations(text: string, onCite: (n: number) => void) {
  const re = /\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]/g;
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<span key={`t${last}`}>{text.slice(last, m.index)}</span>);
    const nums = m[1]
      .split(/\s*[,–-]\s*/)
      .map((s) => parseInt(s, 10))
      .filter((n) => !Number.isNaN(n));
    out.push(
      <button
        key={`c${m.index}`}
        type="button"
        onClick={() => nums[0] && onCite(nums[0])}
        title={`跳到参考文献 ${nums.join(", ")}`}
        className="mx-[1px] inline-flex translate-y-[-2px] items-center rounded border border-primary/25 bg-primary/10 px-1 font-mono text-[10px] leading-4 text-primary transition-colors hover:bg-primary/20"
      >
        {m[1].replace(/\s+/g, "")}
      </button>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key="tail">{text.slice(last)}</span>);
  return out;
}

export default function ReaderPage() {
  const params = useParams<{ id: string }>();
  const docId = params?.id as string;

  const [view, setView] = useState<ReaderView | null>(null);
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [showZh, setShowZh] = useState(true);
  const [syncOn, setSyncOn] = useState(true);
  const [zh, setZh] = useState<Record<string, string>>({});
  const [busyZh, setBusyZh] = useState(false);

  const [activeRef, setActiveRef] = useState<number | null>(null);
  const [activePara, setActivePara] = useState<string | null>(null);

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const refsRef = useRef<HTMLDivElement>(null);
  const syncing = useRef(false);
  const askedSections = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!docId) return;
    setView(null);
    setZh({});
    setErr(null);
    askedSections.current = new Set();
    getReader(docId).then(setView).catch((e) => setErr(String(e)));
    listDocuments().then((r) => setDocs(r.items)).catch(() => {});
  }, [docId]);

  const translateSection = useCallback(
    async (sectionIndex: number) => {
      if (!view || askedSections.current.has(sectionIndex) || busyZh) return;
      const paras = view.paragraphs.filter((p) => p.section_index === sectionIndex);
      const missing = paras.filter((p) => !zh[p.para_id]).slice(0, 8);
      if (!missing.length) {
        askedSections.current.add(sectionIndex);
        return;
      }
      askedSections.current.add(sectionIndex);
      setBusyZh(true);
      try {
        const res = await translateParagraphs(docId, missing.map((p) => p.para_id));
        setZh((prev) => ({ ...prev, ...res.items }));
      } catch {
        askedSections.current.delete(sectionIndex);
      } finally {
        setBusyZh(false);
      }
    },
    [view, zh, busyZh, docId],
  );

  useEffect(() => {
    if (!view || !showZh || !view.paragraphs.length) return;
    // 首屏先把前两节翻出来（Abstract + Introduction），否则右栏一开始是空的
    const firstTwo = Array.from(new Set(view.paragraphs.map((p) => p.section_index))).slice(0, 2);
    void (async () => {
      for (const idx of firstTwo) await translateSection(idx);
    })();
  }, [view, showZh, translateSection]);

  /** 段落级联动滚动的核心：把"从左边看到的那一段"在右边对齐到同一段。 */
  const syncScroll = useCallback(
    (from: "left" | "right") => {
      if (!syncOn) return;
      const a = from === "left" ? leftRef.current : rightRef.current;
      const b = from === "left" ? rightRef.current : leftRef.current;
      if (!a || !b || syncing.current) return;
      const paras = a.querySelectorAll<HTMLElement>("[data-para]");
      if (!paras.length) return;
      let cur = paras[0];
      let best = Number.POSITIVE_INFINITY;
      for (const p of Array.from(paras)) {
        const d = Math.abs(p.offsetTop - a.scrollTop);
        if (d < best) {
          best = d;
          cur = p;
        }
      }
      const target = b.querySelector<HTMLElement>(`[data-para="${cur.dataset.para}"]`);
      if (!target) return;
      syncing.current = true;
      b.scrollTop = target.offsetTop;
      requestAnimationFrame(() => {
        syncing.current = false;
      });
    },
    [syncOn],
  );

  const onLeftScroll = () => {
    syncScroll("left");
    if (!view) return;
    const a = leftRef.current;
    if (!a) return;
    const paras = a.querySelectorAll<HTMLElement>("[data-para]");
    for (const p of Array.from(paras)) {
      if (p.offsetTop >= a.scrollTop - 4) {
        const idx = Number(p.dataset.section);
        if (!Number.isNaN(idx) && showZh) void translateSection(idx);
        break;
      }
    }
  };

  const jumpToPara = (pid: string) => {
    const a = leftRef.current;
    const b = rightRef.current;
    const el = a?.querySelector<HTMLElement>(`[data-para="${pid}"]`);
    if (el && a) a.scrollTo({ top: el.offsetTop - 12, behavior: "smooth" });
    const eb = b?.querySelector<HTMLElement>(`[data-para="${pid}"]`);
    if (eb && b) b.scrollTo({ top: eb.offsetTop - 12, behavior: "smooth" });
    setActivePara(pid);
    window.setTimeout(() => setActivePara(null), 1600);
  };

  const onCite = (n: number) => {
    setActiveRef(n);
    const first = view?.cited_by[String(n)]?.[0];
    if (first) jumpToPara(first);
    const box = refsRef.current;
    const item = box?.querySelector<HTMLElement>(`[data-ref="${n}"]`);
    if (box && item) box.scrollTo({ top: item.offsetTop - 8, behavior: "smooth" });
  };

  if (err) {
    return (
      <div className="flex min-h-screen flex-col">
        <SiteHeader />
        <main className="container-page py-16">
          <Alert variant="destructive">读取失败：{err}</Alert>
          <Link
            href="/library"
            className={buttonVariants({ variant: "outline", size: "sm" }) + " mt-4"}
          >
            回文献库
          </Link>
        </main>
      </div>
    );
  }

  if (!view) {
    return (
      <div className="flex min-h-screen flex-col">
        <SiteHeader />
        <main className="container-page py-16 text-sm text-muted-foreground">正在载入阅读视图…</main>
      </div>
    );
  }

  const highlight = new Set(activeRef !== null ? view.cited_by[String(activeRef)] ?? [] : []);

  return (
    <div className="flex h-screen flex-col">
      <SiteHeader />

      <div className="toolbar">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[13px] font-medium">{view.meta.title ?? view.meta.filename}</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {view.stats.n_sections} 节 · {view.stats.n_paragraphs} 段 ·{" "}
            {view.stats.n_citation_marks} 处引用 · {view.stats.n_refs_cited}/{view.stats.n_references}{" "}
            条参考文献被引
          </p>
        </div>
        <Select
          value={docId}
          aria-label="切换文献"
          onChange={(e) => {
            window.location.href = `/reader/${e.target.value}`;
          }}
          className="max-w-[15rem]"
        >
          {docs.map((d) => (
            <option key={d.doc_id} value={d.doc_id} className="bg-card">
              {d.title ?? d.filename}
            </option>
          ))}
        </Select>
        <Button
          variant={showZh ? "selected" : "outline"}
          size="sm"
          aria-pressed={showZh}
          onClick={() => setShowZh((v) => !v)}
        >
          中文对照：{showZh ? "开" : "关"}
        </Button>
        <Button
          variant={syncOn ? "selected" : "outline"}
          size="sm"
          aria-pressed={syncOn}
          onClick={() => setSyncOn((v) => !v)}
        >
          联动滚动：{syncOn ? "开" : "关"}
        </Button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[15rem_1fr]">
        <aside className="hidden min-h-0 overflow-auto border-r border-border/60 px-3 py-4 md:block">
          <div className="section-label mb-2 px-2">标题树</div>
          <ul className="space-y-0.5">
            {view.sections.map((s) => {
              const target = s.nav_para_id;
              return (
                <li key={s.index}>
                  <button
                    type="button"
                    disabled={!target}
                    onClick={() => target && jumpToPara(target)}
                    className={`w-full truncate rounded-md px-2 py-1 text-left text-[12px] transition-colors hover:bg-muted/40 hover:text-foreground ${
                      s.n_paragraphs === 0 ? "text-muted-foreground/60" : "text-muted-foreground"
                    }`}
                    style={{ paddingLeft: `${8 + (s.level - 1) * 10}px` }}
                    title={`${s.label} · p${s.page_start}${s.n_paragraphs === 0 ? "（父节点，跳到子节）" : ""}`}
                  >
                    {s.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        <div className="flex min-h-0 flex-col">
          <div
            className={`grid min-h-0 flex-1 ${
              showZh ? "grid-cols-1 divide-y divide-border/60 md:grid-cols-2 md:divide-x md:divide-y-0" : "grid-cols-1"
            }`}
          >
            <div ref={leftRef} onScroll={onLeftScroll} className="relative min-h-0 overflow-auto px-5 py-6 sm:px-8">
              {view.paragraphs.map((p, i) => {
                const showSection = i === 0 || view.paragraphs[i - 1].section !== p.section;
                return (
                  <div key={p.para_id} className="mb-4">
                    {showSection && (
                      <h2 className="mb-2 mt-4 text-[15px] font-medium first:mt-0">{p.section}</h2>
                    )}
                    <p
                      data-para={p.para_id}
                      data-section={p.section_index}
                      className={`scroll-mt-4 text-[14px] leading-7 text-foreground/90 transition ${
                        activePara === p.para_id ? "rounded bg-primary/10 px-2 py-1" : ""
                      } ${highlight.has(p.para_id) ? "border-l-2 border-primary/60 pl-2" : ""}`}
                    >
                      {renderWithCitations(p.text, onCite)}
                    </p>
                  </div>
                );
              })}
            </div>

            {showZh && (
              <div
                ref={rightRef}
                onScroll={() => syncScroll("right")}
                className="relative min-h-0 overflow-auto px-5 py-6 sm:px-8"
              >
                {busyZh && <p className="mb-3 text-[11px] text-muted-foreground">正在翻译本节…</p>}
                {view.paragraphs.map((p, i) => {
                  const showSection = i === 0 || view.paragraphs[i - 1].section !== p.section;
                  return (
                    <div key={p.para_id} className="mb-4">
                      {showSection && (
                        <h2 className="mb-2 mt-4 text-[15px] font-medium first:mt-0">{p.section}</h2>
                      )}
                      <p
                        data-para={p.para_id}
                        data-section={p.section_index}
                        className={`text-[14px] leading-7 text-foreground/85 ${
                          zh[p.para_id] ? "" : "text-muted-foreground/40"
                        }`}
                      >
                        {zh[p.para_id] ?? "（本节译文待生成，滚动到这里会自动翻译）"}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="border-t border-border/60">
            <div className="flex items-center justify-between px-5 py-2">
              <div className="section-label">参考文献（点击可反查正文）</div>
              {activeRef !== null && (
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => setActiveRef(null)}
                  className="h-auto p-0 text-[11px]"
                >
                  清除高亮 [{activeRef}]
                </Button>
              )}
            </div>
            <div ref={refsRef} className="relative max-h-40 overflow-auto px-5 pb-4">
              <ul className="space-y-1">
                {view.references.map((r) => (
                  <li key={r.index} data-ref={r.index}>
                    <button
                      type="button"
                      onClick={() => {
                        setActiveRef(r.index);
                        if (r.cited_in[0]) jumpToPara(r.cited_in[0]);
                      }}
                      className={`flex w-full gap-2 rounded-md px-2 py-1 text-left text-[12px] transition-colors ${
                        activeRef === r.index
                          ? "bg-primary/10 text-foreground"
                          : "text-muted-foreground hover:bg-muted/30"
                      }`}
                    >
                      <span className="shrink-0 font-mono text-[11px] text-foreground/60">
                        [{r.index}]
                      </span>
                      <span className="line-clamp-2 flex-1">{r.raw}</span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">
                        ×{r.cited_count}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
