"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Health = {
  status: string;
  version: string;
  llm_provider: string;
  llm_configured: boolean;
};

const MODULES = [
  { id: "M1", name: "PDF 解析与语义去重", judge: "J1 / J2 / J3", state: "已过" },
  { id: "M2", name: "抗幻觉 RAG 问答", judge: "J4", state: "已过" },
  { id: "M3", name: "中英联动阅读", judge: "J5", state: "S3 待开发" },
  { id: "M4", name: "arXiv 检索推荐", judge: "—", state: "S4 补充线" },
  { id: "M5", name: "引用图谱挖掘", judge: "J6", state: "S5 待开发" },
  { id: "M6", name: "写作与可视化 Copilot", judge: "J7 / J8", state: "S6 待开发" },
];

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold mb-2">科研助手 Agent</h1>
        <p className="text-muted-foreground">
          全流程科研助手 · 全国高校 AI 大模型挑战赛（B 组 · 个人）· S0 骨架阶段
        </p>
        <nav className="mt-4 flex gap-4 text-sm">
          <Link href="/" className="font-medium underline">
            首页
          </Link>
          <Link href="/library" className="underline">
            文献库（M1 解析）
          </Link>
          <Link href="/ask" className="underline">
            问答（M2 抗幻觉）
          </Link>
          <Link href="/reader" className="underline">
            阅读器（M3 联动）
          </Link>
          <Link href="/graph" className="underline">
            图谱（M5 引用挖掘）
          </Link>
          <Link href="/write" className="underline">
            写作（M6 数据出图）
          </Link>
          <Link href="/write" className="underline">
            写作（M6 数据出图）
          </Link>
        </nav>
      </header>

      <Card className="mb-8">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            后端连接状态
            {health ? (
              <Badge variant="default">已连接</Badge>
            ) : error ? (
              <Badge variant="destructive">未连接</Badge>
            ) : (
              <Badge variant="secondary">连接中…</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="font-mono text-sm">
          {health ? (
            <pre className="whitespace-pre-wrap">{JSON.stringify(health, null, 2)}</pre>
          ) : error ? (
            <span className="text-destructive">{error}</span>
          ) : (
            <span className="text-muted-foreground">正在连接 {API_URL} …</span>
          )}
        </CardContent>
      </Card>

      <section>
        <h2 className="text-xl font-semibold mb-4">六大模块（按赛题命题范围）</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {MODULES.map((m) => (
            <Card key={m.id}>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Badge variant="outline">{m.id}</Badge>
                  {m.name}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                判据 {m.judge} · {m.state}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <footer className="mt-12 text-xs text-muted-foreground">
        李论 · 北华航天工业学院 · 计划表与路线图见仓库根目录 计划表.md
      </footer>
    </main>
  );
}
