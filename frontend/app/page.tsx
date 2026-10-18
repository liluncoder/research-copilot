"use client";

import Link from "next/link";
import {
  ArrowRight,
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
 * ★不要在这页出现任何内部工作信息（2026-10-18 按李论要求改）：
 *   - 不写"J1/J2/J3 已通过"——判据编号是赛题内部评分口径，摊在首页像在向评委交作业；
 *     对外应该讲"能做什么"，而不是"我们过了哪几条"。
 *   - 不写"省赛 B 组 · 个人参赛"、不写参赛者姓名与学校——这些属于申报材料，不属于产品界面。
 *   - 不写"9 项官方判据全部通过"——理由同上：自证式陈述对使用者没有信息量。
 */

const MODULES = [
  {
    name: "PDF 解析与去重",
    desc: "标题树、公式、表格、参考文献一次抽全；跨出版社排版都能认，重复投稿会主动提醒。",
    href: "/library",
    icon: FileText,
    cap: ["标题树", "公式", "表格", "查重"],
  },
  {
    name: "可溯源问答",
    desc: "中文提问、英文原文作答。每个论断都挂页码与章节，库中没有的内容明确拒答。",
    href: "/ask",
    icon: MessageSquare,
    cap: ["混合检索", "逐句出处", "拒答"],
  },
  {
    name: "中英对照阅读",
    desc: "左侧原文、右侧译文段落对齐；点引用编号跳到参考文献，点条目反查正文。",
    href: "/reader",
    icon: Columns2,
    cap: ["双栏", "双向跳转", "联动滚动"],
  },
  {
    name: "引用图谱",
    desc: "把参考文献网络画成图，按 PageRank 找出真正的基石工作，点击即可看它的引用邻域。",
    href: "/graph",
    icon: Network,
    cap: ["引文网络", "PageRank", "自动综述"],
  },
  {
    name: "数据出图与写作",
    desc: "上传实验数据自动出图并写图注；论文框架只能引用库中已有文献，一条都不会编。",
    href: "/write",
    icon: PenTool,
    cap: ["图表", "图注", "参考文献"],
  },
  {
    name: "arXiv 检索推荐",
    desc: "按标题与摘要检索并推荐相关预印本，正在开发中。",
    href: "/library",
    icon: Sparkles,
    cap: ["开发中"],
  },
];

export default function Home() {
  return (
    <SiteShell>
      {/* ---- 价值主张 ---- */}
      <section className="pb-10 pt-6">
        <h1 className="max-w-3xl text-[34px] font-semibold leading-[1.25] tracking-tight sm:text-[42px]">
          从一篇 PDF 到可信的科研结论
        </h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
          解析论文、检索问答、中英对照阅读、引用图谱、数据出图——
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

      {/* ---- 能力卡片 ---- */}
      <section>
        <div className="mb-3 flex items-end justify-between">
          <div className="section-label">能做什么</div>
          <span className="text-[12px] text-muted-foreground">点击任一卡片进入</span>
        </div>

        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m, i) => {
            const Icon = m.icon;
            return (
              <Link
                key={m.name}
                href={m.href}
                className="group animate-fade-up"
                style={{ animationDelay: `${i * 45}ms` }}
              >
                <div className="surface surface-hover flex h-full flex-col p-5">
                  <div className="mb-3 flex items-start justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/8 text-primary">
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <ArrowRight className="mt-1 h-4 w-4 text-muted-foreground/30 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>

                  <h3 className="text-[15px] font-semibold leading-snug">{m.name}</h3>
                  <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-muted-foreground">
                    {m.desc}
                  </p>

                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {m.cap.map((c) => (
                      <span
                        key={c}
                        className="rounded-md bg-muted px-2 py-0.5 text-[11.5px] text-muted-foreground"
                      >
                        {c}
                      </span>
                    ))}
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
