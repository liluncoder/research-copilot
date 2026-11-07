"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, FileText } from "lucide-react";
import { listDocuments, type DocumentMeta } from "@/lib/api";
import { PageHeader, SiteShell } from "@/components/site-shell";
import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";

export default function ReaderIndex() {
  const [items, setItems] = useState<DocumentMeta[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then((r) => setItems(r.items))
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <SiteShell width="narrow">
      <PageHeader
        title="阅读器"
        desc="双栏对照阅读：左边原文、右边中文；点引用编号可跳到参考文献，点参考文献可反查正文。"
      />

      {err && <Alert variant="destructive">读取失败：{err}</Alert>}

      {items.length > 0 ? (
        <Card className="mt-4 divide-y divide-border/60 overflow-hidden">
          {items.map((d) => (
            <Link
              key={d.doc_id}
              href={`/reader/${d.doc_id}`}
              className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/40"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <FileText className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{d.title ?? d.filename}</span>
                <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">
                  {d.page_count} 页 · {d.n_headings} 标题 · {d.n_references} 条参考文献
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </Card>
      ) : (
        !err && (
          <EmptyState
            className="mt-4"
            icon={<FileText className="h-5 w-5" />}
            title="还没有可阅读的文献"
            description="先去文献库上传一份 PDF，解析完成后就能双栏对照阅读。"
            action={
              <Link href="/library" className={buttonVariants({ size: "sm" })}>
                去文献库
              </Link>
            }
          />
        )
      )}
    </SiteShell>
  );
}
