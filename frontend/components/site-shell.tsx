"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * 全站统一外壳。
 *
 * ★为什么要抽这一层：改造前 7 个页面各自手写 <header> + 一套 <nav>，
 *   容器宽度有 3xl/4xl/5xl/6xl 四种，导航文案也不一致（首页还把"写作"写了两遍）。
 *   页面之间点来点去，内容宽度和顶栏位置都在跳 —— 这是"看着不专业"最直接的来源。
 */
const NAV = [
  { href: "/", label: "首页" },
  { href: "/library", label: "文献库", hint: "M1 解析" },
  { href: "/ask", label: "问答", hint: "M2 抗幻觉" },
  { href: "/reader", label: "阅读器", hint: "M3 联动" },
  { href: "/graph", label: "图谱", hint: "M5 引用" },
  { href: "/write", label: "写作", hint: "M6 出图" },
];

type Health = { status: string; version: string; llm_provider: string; llm_configured: boolean };

export function SiteShell({
  children,
  width = "wide",
}: {
  children: React.ReactNode;
  /** wide = 六栏内容页；narrow = 阅读/问答这类单列长文 */
  width?: "wide" | "narrow";
}) {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then((d) => alive && setHealth(d))
      .catch(() => alive && setDown(true));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="site-header">
        <div className="container-page flex h-14 items-center gap-6">
          {/* 品牌标记：一个实心方块 + 内嵌细线，表达"论文 → 结构化" */}
          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-primary">
              <span className="h-2.5 w-2.5 rounded-[2px] border border-primary-foreground/90" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">科研助手</span>
          </Link>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "shrink-0 rounded-lg px-3 py-1.5 text-[13.5px] transition-colors",
                    active
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* 服务状态：一个点就够，不再往页面上摊 JSON */}
          <div className="hidden shrink-0 items-center gap-2 text-[12px] text-muted-foreground sm:flex">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                health ? "bg-success" : down ? "bg-destructive" : "bg-muted-foreground/40",
              )}
            />
            {health ? "服务正常" : down ? "服务未连接" : "连接中"}
          </div>
        </div>
      </header>

      <main
        className={cn(
          "flex-1 py-10",
          width === "narrow" ? "mx-auto w-full max-w-4xl px-5 sm:px-8" : "container-page",
        )}
      >
        {children}
      </main>

      <footer className="mt-8 border-t border-border/70">
        <div className="container-page flex flex-wrap items-center justify-between gap-2 py-6 text-[12px] text-muted-foreground">
          <span>全流程科研助手 Agent · 全国高校 AI 大模型挑战赛（B 组）</span>
          <span>李论 · 北华航天工业学院</span>
        </div>
      </footer>
    </div>
  );
}

/** 页面标题区：统一字号/间距，各页不再各写一套 <header> */
export function PageHeader({
  title,
  desc,
  aside,
}: {
  title: string;
  desc?: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {desc && <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">{desc}</p>}
      </div>
      {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
    </div>
  );
}
