"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, Trash2, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
      <PageHeader
        title="文献库"
        desc="上传 PDF 即完成结构化解析（标题树 / 公式 / 表格 / 参考文献）并自动建检索索引。"
      />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">上传论文</CardTitle>
          <CardDescription>支持文本层 PDF 与扫描件；重复上传会先做语义查重再决定去留。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <Input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              aria-label="选择 PDF"
              className="h-9 w-auto max-w-full cursor-pointer py-1.5 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-[12px] file:text-foreground/80 hover:file:bg-muted/70"
            />
            <Button onClick={() => void onUpload()} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {busy ? "解析中…" : "上传并解析"}
            </Button>
          </div>
          {message && <Alert variant={message.kind === "ok" ? "success" : "destructive"}>{message.text}</Alert>}
        </CardContent>
      </Card>

      {dedup && (
        <Card variant="destructive" className="mb-6">
          <CardHeader>
            <CardTitle className="text-base text-destructive">
              检测到疑似重复：库中已有内容高度重合的论文
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {dedup.exists_newer && (
              <Alert variant="warning">
                库中已有<strong>更新</strong>的版本，你上传的是较旧的版本 —— 一般建议保留库中那份。
              </Alert>
            )}
            {dedup.candidates.map((c) => (
              <Card key={c.doc_id} variant="flat" className="p-3">
                <p className="font-medium">{c.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {dedup.metric} {Math.round(c.similarity * 100)}%（判据阈值{" "}
                  {Math.round(dedup.threshold * 100)}%）
                </p>
                <p className="mt-1 text-xs">{c.reason}</p>
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => void showDiff(c.doc_id, c.existing_is_newer)}
                  disabled={busy}
                  className="mt-2 h-auto p-0 text-xs"
                >
                  查看两版主要差异
                </Button>
              </Card>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={busy} onClick={() => void act("keep_both")}>
                保留两份
              </Button>
              <Button
                disabled={busy}
                onClick={() => void act("replace_existing", dedup.candidates[0]?.doc_id)}
              >
                用新上传的替换库中旧版
              </Button>
              <Button
                variant="destructive-outline"
                disabled={busy}
                onClick={() => void act("discard_new")}
              >
                放弃本次上传
              </Button>
            </div>

            {diff && (
              <Card variant="flat" className="bg-muted/50 p-3 text-xs leading-relaxed">
                <p className="mb-1 font-medium">
                  {diff.diff.old_label} → {diff.diff.new_label}
                  <span className="ml-2 font-normal text-muted-foreground">
                    （摘要来源：{diff.summary_source === "llm" ? "大模型" : "确定性统计"}）
                  </span>
                </p>
                <p className="whitespace-pre-wrap">{diff.summary || diff.fallback_summary}</p>
              </Card>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[20rem_1fr]">
        <section>
          <div className="section-label mb-3">已入库（{items.length}）</div>
          <ul className="space-y-2">
            {items.map((m) => {
              const active = selected?.meta.doc_id === m.doc_id;
              return (
                <li key={m.doc_id}>
                  <Card
                    variant="interactive"
                    className={active ? "border-primary/45 bg-primary/[0.03]" : undefined}
                  >
                    <CardContent className="p-3">
                      <button
                        type="button"
                        onClick={() => void open(m.doc_id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center gap-2">
                          <Badge variant={m.doc_type === "scanned" ? "warning" : "success"}>
                            {m.doc_type === "scanned" ? "扫描件" : "文本层"}
                          </Badge>
                          <span className="tabular text-xs text-muted-foreground">
                            {m.page_count} 页 · {humanSize(m.size_bytes)}
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-sm font-medium">
                          {m.title ?? m.filename}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {m.n_headings} 标题 · {m.n_references} 参考文献 · {m.n_math_lines} 公式行
                        </p>
                      </button>
                      <Button
                        variant="link"
                        size="sm"
                        onClick={() => void remove(m.doc_id)}
                        disabled={busy}
                        className="mt-2 h-auto gap-1 p-0 text-xs text-destructive"
                      >
                        <Trash2 className="h-3 w-3" />
                        删除
                      </Button>
                    </CardContent>
                  </Card>
                </li>
              );
            })}
            {items.length === 0 && (
              <li>
                <EmptyState
                  icon={<FileText className="h-5 w-5" />}
                  title="文献库还是空的"
                  description="在上面传一份 PDF，解析完成后这里会出现标题树与表格。"
                />
              </li>
            )}
          </ul>
        </section>

        <section>
          {!selected ? (
            <EmptyState
              icon={<FileText className="h-5 w-5" />}
              title="还没有选中文献"
              description="左侧点一篇，看解析出来的标题树、表格与章节正文。"
            />
          ) : (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    {selected.meta.title ?? selected.meta.filename}
                  </CardTitle>
                  <CardDescription>
                    {selected.meta.authors.join("、") || "（未识别作者）"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline">{selected.meta.page_count} 页</Badge>
                    <Badge variant="outline">{selected.meta.n_headings} 标题</Badge>
                    <Badge variant="outline">{selected.meta.n_references} 参考文献</Badge>
                    <Badge variant="outline">{selected.meta.n_math_lines} 公式行</Badge>
                    <Badge variant="outline">解析 {selected.meta.parse_seconds}s</Badge>
                  </div>
                  {selected.meta.warnings.length > 0 && (
                    <Alert variant="warning" hideIcon>
                      <ul className="list-disc pl-4 text-xs">
                        {selected.meta.warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </Alert>
                  )}
                  {selected.abstract && (
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer transition hover:text-foreground">
                        摘要（{selected.meta.abstract_chars} 字符）
                      </summary>
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
                  <CardContent className="space-y-6">
                    {selected.tables!.map((t) => {
                      const header = t.rows[0] ?? [];
                      const body = t.rows.slice(1);
                      const width = Math.max(1, ...t.rows.map((r) => r.length));
                      return (
                        <div key={t.index} className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="secondary">Table {t.number ?? t.index}</Badge>
                            <span className="tabular text-xs text-muted-foreground">
                              第 {t.page} 页 · {t.n_rows}×{t.n_cols} · 置信度{" "}
                              {Math.round(t.confidence * 100)}%
                            </span>
                          </div>
                          {t.caption && (
                            <p className="text-xs leading-relaxed text-muted-foreground">{t.caption}</p>
                          )}
                          <Table>
                            <TableHeader>
                              <TableRow>
                                {Array.from({ length: width }).map((_, i) => (
                                  <TableHead key={i}>{header[i] ?? ""}</TableHead>
                                ))}
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {body.map((r, ri) => (
                                <TableRow key={ri}>
                                  {Array.from({ length: width }).map((_, ci) => (
                                    <TableCell key={ci}>{r[ci] ?? ""}</TableCell>
                                  ))}
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                          {t.confidence < 0.7 && (
                            <Alert variant="warning" className="py-2 text-xs">
                              结构置信度偏低，单元格可能有错位（见技术文档已知限制）
                            </Alert>
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
