"use client";

import Link from "next/link";
import {
  ArrowRight,
  Check,
  Columns2,
  FileText,
  MessageSquare,
  Network,
  PenTool,
  Sparkles,
  Upload,
} from "lucide-react";
import { SiteShell } from "@/components/site-shell";
import { Button } from "@/components/ui/button";

/**
 * 首页。
 *
 * ★改造前这一页还是 S0 骨架的样子：写着"S0 骨架阶段"、模块状态是"S3 待开发"、
 *   后端连接状态直接把 /health 的 JSON 摊在页面上。那是开发调试视图，
 *   评委（或视频）第一眼看到的会以为项目没做完 —— 而实际 J1~J8 已全部通过。
 * 现在这页要回答三件事：这是什么、做到哪了、从哪开始用。
 */

const MODULES = [
  {
    id: "M1",
    name: "PDF 解析与语义去重",
    desc: "标题树 / 公式 / 表格 / 参考文献，跨出版社适配",
    judges: ["J1", "J2", "J3"],
    href: "/library",
    icon: FileText,
    done: true,
  },
  {
    id: "M2",
    name: "抗幻觉 RAG 问答",
    desc: "混合召回 + 每句挂出处，查不到就明确拒答",
    judges: ["J4"],
    href: "/ask",
    icon: MessageSquare,
    done: true,
  },
  {
    id: "M3",
    name: "中英联动阅读",
    desc: "双栏对照、引用双向跳转、段落级同步滚动",
    judges: ["J5"],
    href: "/reader",
    icon: Columns2,
    done: true,
  },
  {
    id: "M5",
    name: "引用图谱挖掘",
    desc: "PageRank 找基石论文，点击高亮引用邻域",
    judges: ["J6"],
    href: "/graph",
    icon: Network,
    done: true,
  },
  {
    id: "M6",
    name: "写作与可视化 Copilot",
    desc: "CSV 出图 + 图注只看统计量；References 只点名不编写",
    judges: ["J7", "J8"],
    href: "/write",
    icon: PenTool,
    done: true,
  },
  {
    id: "M4",
    name: "arXiv 检索推荐",
    desc: "按标题/摘要检索并推荐，属补充线，可按剩余时间裁剪",
    judges: [],
    href: "/library",
    icon: Sparkles,
    done: false,
  },
];

const JUDGES = ["J1", "J2", "J3-a", "J3-b", "J4", "J5", "J6", "J7", "J8"];

export default function Home() {
  return (
    <SiteShell>
      {/* ---- 价值主张 ---- */}
      <section className="pb-10 pt-4">
        <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <span className="rounded-full bg-success/10 px-2.5 py-1 font-medium text-success">
            9 项官方判据全部通过
          </span>
          <span className="hidden sm:inline">省赛 B 组 · 个人参赛</span>
        </div>

        <h1 className="mt-5 max-w-3xl text-[34px] font-semibold leading-[1.25] tracking-tight sm:text-[40px]">
          从一篇 PDF 到可信的科研结论
        </h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
          解析论文、检索问答、中英对照阅读、引用图谱、数据出图与写作——
          每个论断都能追到原文的页码与章节，查不到就拒答，不编。
        </p>

        <div className="mt-7 flex flex-wrap gap-3">
          <Link href="/ask">
            <Button size="lg">
              开始提问
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link href="/library">
            <Button size="lg" variant="outline">
              <Upload className="h-4 w-4" />
              上传文献
            </Button>
          </Link>
        </div>
      </section>

      {/* ---- 判据条 ---- */}
      <section className="mb-10">
        <div className="section-label mb-3">判据完成情况</div>
        <div className="surface flex flex-wrap items-center gap-2 p-4">
          {JUDGES.map((j) => (
            <span
              key={j}
              className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2.5 py-1 text-[12px] font-medium text-success"
            >
              <Check className="h-3 w-3" strokeWidth={3} />
              {j}
            </span>
          ))}
          <span className="ml-auto text-[12px] text-muted-foreground">
            每条都有可复跑的判据脚本，不靠口头声明
          </span>
        </div>
      </section>

      {/* ---- 六大模块 ---- */}
      <section>
        <div className="mb-3 flex items-end justify-between">
          <div className="section-label">六大模块</div>
          <span className="text-[12px] text-muted-foreground">按赛题命题范围</span>
        </div>

        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => {
            const Icon = m.icon;
            return (
              <Link key={m.id} href={m.href} className="group">
                <div className="surface surface-hover flex h-full flex-col p-5">
                  <div className="mb-3 flex items-start justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/8 text-primary">
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <span className="text-[11px] font-medium tabular text-muted-foreground/70">
                      {m.id}
                    </span>
                  </div>

                  <h3 className="text-[15px] font-semibold leading-snug">{m.name}</h3>
                  <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-muted-foreground">
                    {m.desc}
                  </p>

                  <div className="mt-4 flex items-center gap-1.5">
                    {m.done ? (
                      <>
                        <span className="h-1.5 w-1.5 rounded-full bg-success" />
                        <span className="text-[12px] font-medium text-success">已通过</span>
                        {m.judges.length > 0 && (
                          <span className="text-[12px] text-muted-foreground/70">
                            {m.judges.join(" · ")}
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                        <span className="text-[12px] text-muted-foreground">补充线 · 可裁剪</span>
                      </>
                    )}
                    <ArrowRight className="ml-auto h-3.5 w-3.5 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    </SiteShell>
  );
}
