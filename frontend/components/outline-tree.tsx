"use client";

import type { OutlineNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/** 标题树导航（S3 阅读器的左侧栏直接复用这个组件）。 */
export function OutlineTree({
  nodes,
  onSelect,
  activeLabel,
}: {
  nodes: OutlineNode[];
  onSelect?: (node: OutlineNode) => void;
  activeLabel?: string | null;
}) {
  if (nodes.length === 0) {
    return <p className="text-sm text-muted-foreground">（没有解析到标题）</p>;
  }
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => (
        <li key={`${node.level}-${node.page}-${node.label}`}>
          <button
            type="button"
            onClick={() => onSelect?.(node)}
            title={`第 ${node.page} 页 · 点击查看这一节正文`}
            className={cn(
              "group flex w-full cursor-pointer items-baseline gap-2 rounded-md border-l-2 border-transparent px-2 py-1 text-left text-[13px] transition-colors",
              "hover:border-primary/40 hover:bg-muted/60",
              node.level === 1 && "font-medium",
              node.level === 2 && "pl-5",
              node.level === 3 && "pl-9 text-muted-foreground",
              activeLabel === node.label &&
                "border-primary bg-primary/10 font-medium text-primary hover:bg-primary/15",
            )}
          >
            <span className="min-w-0 flex-1">{node.label}</span>
            <span
              className={cn(
                "shrink-0 text-xs text-muted-foreground",
                // 悬停时把页码换成"看正文"，让可点这件事自己说出来
                activeLabel === node.label && "text-primary/80",
              )}
            >
              p{node.page}
            </span>
          </button>
          {node.children.length > 0 && (
            <OutlineTree nodes={node.children} onSelect={onSelect} activeLabel={activeLabel} />
          )}
        </li>
      ))}
    </ul>
  );
}
