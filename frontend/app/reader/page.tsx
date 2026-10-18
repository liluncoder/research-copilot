"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listDocuments, type DocumentMeta } from "@/lib/api";
import { PageHeader, SiteShell } from "@/components/site-shell";

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
      <PageHeader title="阅读器" desc="双栏对照阅读：左边原文、右边中文；点引用编号可跳到参考文献，点参考文献可反查正文。" />

        {err && <p className="text-sm text-destructive">读取失败：{err}</p>}

        <ul className="divide-y divide-border/60">
          {items.map((d) => (
            <li key={d.doc_id}>
              <Link
                href={`/reader/${d.doc_id}`}
                className="flex items-baseline gap-3 py-3 transition hover:opacity-80"
              >
                <span className="flex-1 truncate text-sm">{d.title ?? d.filename}</span>
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {d.page_count} 页 · {d.n_headings} 标题
                </span>
              </Link>
            </li>
          ))}
          {!err && items.length === 0 && (
            <li className="py-6 text-sm text-muted-foreground">
              文献库是空的，先去 <Link href="/library" className="text-primary underline">文献库</Link> 传一份 PDF。
            </li>
          )}
        </ul>
    </SiteShell>
  );
}
