"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OutlineTree } from "@/components/outline-tree";
import { PageHeader, SiteShell } from "@/components/site-shell";
import {
  type DedupAction,
  type DedupInfo,
  type DocumentDetail,
  type DocumentMeta,
  type VersionDiff,
  compareDocuments,
  deleteDocument,
  getDocument,
  humanSize,
  listDocuments,
  resolveDedup,
  uploadDocument,
} from "@/lib/api";

export default function LibraryPage() {
  const [items, setItems] = useState<DocumentMeta[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [dedup, setDedup] = useState<(DedupInfo & { docId: string }) | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
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
      setDiff(null);
      setDedup(res.dedup.has_warning ? { ...res.dedup, docId: res.meta.doc_id } : null);
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

  async function act(action: DedupAction, targetDocId?: string) {
    if (!dedup) return;
    setBusy(true);
    try {
      const res = await resolveDedup(dedup.docId, action, targetDocId);
      const label: Record<DedupAction, string> = {
        keep_both: "已保留两份",
        replace_existing: "已用新上传的版本替换库中旧版",
        discard_new: "已放弃本次上传",
      };
      setMessage({ kind: "ok", text: label[action] });
      setDedup(null);
      setDiff(null);
      if (action !== "keep_both") setSelected(null);
      await refresh();
      void res;
    } catch (e) {
      setMessage({ kind: "err", text: `处理失败：${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  async function showDiff(candidateId: string, existingIsNewer: boolean) {
    if (!dedup) return;
    setBusy(true);
    try {
      // 旧的在前、新的在后：库中较新 ⇒ 新上传的是旧版
      const older = existingIsNewer ? dedup.docId : candidateId;
      const newer = existingIsNewer ? candidateId : dedup.docId;
      setDiff(await compareDocuments(older, newer));
    } catch (e) {
      setMessage({ kind: "err", text: `对比失败：${String(e)}` });
    } finally {
      setBusy(false);
    }
  }

  const section = selected?.sections.find((s) => s.label === activeSection) ?? null;

  return (
    <SiteShell width="wide">
      <PageHeader title="文献库" desc="上传 PDF 即完成结构化解析（标题树 / 公式 / 表格 / 参考文献）并自动建检索索引。" />

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

      {dedup && (
        <Card className="mb-6 border-destructive">
          <CardHeader>
            <CardTitle className="text-base text-destructive">
              检测到疑似重复：库中已有内容高度重合的论文
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {dedup.exists_newer && (
              <p className="rounded bg-muted p-2 text-destructive">
                ⚠ 库中已有<strong>更新</strong>的版本，你上传的是较旧的版本 —— 一般建议保留库中那份。
              </p>
            )}
            {dedup.candidates.map((c) => (
              <div key={c.doc_id} className="rounded border p-3">
                <p className="font-medium">{c.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {dedup.metric} {Math.round(c.similarity * 100)}%（判据阈值{" "}
                  {Math.round(dedup.threshold * 100)}%）
                </p>
                <p className="mt-1 text-xs">{c.reason}</p>
                <button
                  type="button"
                  onClick={() => void showDiff(c.doc_id, c.existing_is_newer)}
                  className="mt-2 text-xs underline"
                  disabled={busy}
                >
                  查看两版主要差异
                </button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void act("keep_both")}
                className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
              >
                保留两份
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act("replace_existing", dedup.candidates[0]?.doc_id)}
                className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
              >
                用新上传的替换库中旧版
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act("discard_new")}
                className="rounded border px-3 py-1.5 text-sm text-destructive disabled:opacity-50"
              >
                放弃本次上传
              </button>
            </div>

            {diff && (
              <div className="rounded bg-muted p-3 text-xs leading-relaxed">
                <p className="mb-1 font-medium">
                  {diff.diff.old_label} → {diff.diff.new_label}
                  <span className="ml-2 font-normal text-muted-foreground">
                    （摘要来源：{diff.summary_source === "llm" ? "大模型" : "确定性统计"}）
                  </span>
                </p>
                <p className="whitespace-pre-wrap">{diff.summary || diff.fallback_summary}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

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

              {(selected.tables?.length ?? 0) > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">
                      表格
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        {selected.tables!.length} 张（J2 表格解析）
                      </span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    {selected.tables!.map((t) => {
                      const header = t.rows[0] ?? [];
                      const body = t.rows.slice(1);
                      const width = Math.max(1, ...t.rows.map((r) => r.length));
                      return (
                        <div key={t.index} className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="secondary">Table {t.number ?? t.index}</Badge>
                            <span className="text-xs text-muted-foreground">
                              第 {t.page} 页 · {t.n_rows}×{t.n_cols} · 置信度{" "}
                              {Math.round(t.confidence * 100)}%
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground">{t.caption}</p>
                          <div className="overflow-x-auto rounded border">
                            <table className="w-full border-collapse text-xs">
                              <thead className="bg-muted/60">
                                <tr>
                                  {Array.from({ length: width }).map((_, i) => (
                                    <th
                                      key={i}
                                      className="whitespace-nowrap border-b px-2 py-1 text-left font-medium"
                                    >
                                      {header[i] ?? ""}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {body.map((r, ri) => (
                                  <tr key={ri} className="border-b last:border-0">
                                    {Array.from({ length: width }).map((_, ci) => (
                                      <td key={ci} className="px-2 py-1 align-top">
                                        {r[ci] ?? ""}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          {t.confidence < 0.7 && (
                            <p className="text-xs text-destructive">
                              结构置信度偏低，单元格可能有错位（见技术文档已知限制）
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              )}

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
    </SiteShell>
  );
}
