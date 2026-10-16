"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OutlineTree } from "@/components/outline-tree";
import {
  type DocumentDetail,
  type DocumentMeta,
  deleteDocument,
  getDocument,
  humanSize,
  listDocuments,
  uploadDocument,
} from "@/lib/api";

export default function LibraryPage() {
  const [items, setItems] = useState<DocumentMeta[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listDocuments();
      setItems(data.items);
    } catch (e) {
      setMessage({ kind: "err", text: `读取文献库失败：${String(e)}` });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setMessage({ kind: "err", text: "先选一个 PDF 文件" });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const res = await uploadDocument(file);
      setMessage({
        kind: "ok",
        text: `已入库 ${res.meta.doc_id}：${res.meta.n_headings} 个标题 / ${res.meta.n_references} 条参考文献 / 解析 ${res.meta.parse_seconds}s`,
      });
      await refresh();
      await open(res.meta.doc_id);
    } catch (e) {
      setMessage({ kind: "err", text: `上传失败：${String(e)}` });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function open(docId: string) {
    try {
      setSelected(await getDocument(docId));
      setActiveSection(null);
    } catch (e) {
      setMessage({ kind: "err", text: `打开失败：${String(e)}` });
    }
  }

  async function remove(docId: string) {
    setBusy(true);
    try {
      await deleteDocument(docId);
      if (selected?.meta.doc_id === docId) setSelected(null);
      await refresh();
      setMessage({ kind: "ok", text: `已删除 ${docId}` });
    } catch (e) {
      setMessage({ kind: "err", text: `删除失败：${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  const section = selected?.sections.find((s) => s.label === activeSection) ?? null;

  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto">
      <header className="mb-6">
        <div className="mb-2 flex items-baseline gap-3">
          <h1 className="text-3xl font-bold">文献库</h1>
          <Link href="/" className="text-sm text-muted-foreground underline">
            返回首页
          </Link>
        </div>
        <p className="text-muted-foreground">
          S1 · 上传 PDF ⇒ 结构化解析（标题树 / 公式 / 参考文献）⇒ 入库
        </p>
      </header>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">上传论文</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            className="text-sm file:mr-3 file:rounded file:border file:bg-muted file:px-3 file:py-1.5 file:text-sm"
          />
          <button
            type="button"
            onClick={onUpload}
            disabled={busy}
            className="rounded bg-primary px-4 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
          >
            {busy ? "处理中…" : "上传并解析"}
          </button>
          {message && (
            <span
              className={
                message.kind === "ok"
                  ? "text-sm text-muted-foreground"
                  : "text-sm text-destructive"
              }
            >
              {message.text}
            </span>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[20rem_1fr]">
        <section>
          <h2 className="mb-3 text-lg font-semibold">已入库（{items.length}）</h2>
          <ul className="space-y-2">
            {items.map((m) => (
              <li key={m.doc_id}>
                <Card
                  className={
                    selected?.meta.doc_id === m.doc_id ? "border-primary" : undefined
                  }
                >
                  <CardContent className="p-3">
                    <button
                      type="button"
                      onClick={() => void open(m.doc_id)}
                      className="w-full text-left"
                    >
                      <div className="flex items-center gap-2">
                        <Badge variant={m.doc_type === "scanned" ? "destructive" : "secondary"}>
                          {m.doc_type === "scanned" ? "扫描件" : "文本层"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {m.page_count} 页 · {humanSize(m.size_bytes)}
                        </span>
                      </div>
                      <p className="mt-1 text-sm font-medium">
                        {m.title ?? m.filename}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {m.n_headings} 标题 · {m.n_references} 参考文献 · {m.n_math_lines} 公式行
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(m.doc_id)}
                      disabled={busy}
                      className="mt-2 text-xs text-destructive underline disabled:opacity-50"
                    >
                      删除
                    </button>
                  </CardContent>
                </Card>
              </li>
            ))}
            {items.length === 0 && (
              <li className="text-sm text-muted-foreground">
                还没有文献。上面传一份 PDF 试试。
              </li>
            )}
          </ul>
        </section>

        <section>
          {!selected ? (
            <p className="text-sm text-muted-foreground">左侧点一篇，看解析出来的标题树。</p>
          ) : (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    {selected.meta.title ?? selected.meta.filename}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <p className="text-muted-foreground">
                    {selected.meta.authors.join("、") || "（未识别作者）"}
                  </p>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline">{selected.meta.page_count} 页</Badge>
                    <Badge variant="outline">{selected.meta.n_headings} 标题</Badge>
                    <Badge variant="outline">{selected.meta.n_references} 参考文献</Badge>
                    <Badge variant="outline">{selected.meta.n_math_lines} 公式行</Badge>
                    <Badge variant="outline">解析 {selected.meta.parse_seconds}s</Badge>
                  </div>
                  {selected.meta.warnings.length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-destructive">
                      {selected.meta.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  )}
                  {selected.abstract && (
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer">摘要（{selected.meta.abstract_chars} 字符）</summary>
                      <p className="mt-2 leading-relaxed">{selected.abstract}</p>
                    </details>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">标题树</CardTitle>
                </CardHeader>
                <CardContent>
                  <OutlineTree
                    nodes={selected.outline}
                    activeLabel={activeSection}
                    onSelect={(n) => setActiveSection(n.label)}
                  />
                </CardContent>
              </Card>

              {section && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      {section.label}
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        第 {section.page_start}
                        {section.page_end !== section.page_start ? `-${section.page_end}` : ""} 页 ·{" "}
                        {section.n_chars} 字符
                      </span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm leading-relaxed">
                    {section.paragraphs.slice(0, 6).map((p, i) => (
                      <p key={i}>{p}</p>
                    ))}
                    {section.paragraphs.length > 6 && (
                      <p className="text-xs text-muted-foreground">
                        …共 {section.paragraphs.length} 段，此处只显示前 6 段
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
