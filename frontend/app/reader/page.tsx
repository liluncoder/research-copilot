"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listDocuments, type DocumentMeta } from "@/lib/api";

export default function ReaderIndex() {
  const [items, setItems] = useState<DocumentMeta[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then((r) => setItems(r.items))
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <main className="min-h-screen">
      <div className="mx-auto w-full max-w-3xl px-6 py-12">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight">阅读器</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            双栏对照阅读：左边原文、右边中文；点引用编号可跳到参考文献，点参考文献可反查正文。
          </p>
          <nav className="mt-5 flex gap-5 text-sm text-muted-foreground">
            <Link href="/" className="hover:text-foreground">首页</Link>
            <Link href="/library" className="hover:text-foreground">文献库</Link>
            <Link href="/ask" className="hover:text-foreground">问答</Link>
            <Link href="/reader" className="font-medium text-foreground">阅读器</Link>
          </nav>
        </header>

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
      </div>
    </main>
  );
}
