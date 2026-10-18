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
            title={`第 ${node.page} 页`}
            className={cn(
              "w-full rounded-md px-2 py-1 text-left text-[13px] transition-colors hover:bg-muted/60",
              node.level === 1 && "font-medium",
              node.level === 2 && "pl-5",
              node.level === 3 && "pl-9 text-muted-foreground",
              activeLabel === node.label && "bg-primary/10 text-primary",
            )}
          >
            {node.label}
            <span className="ml-2 text-xs text-muted-foreground">p{node.page}</span>
          </button>
          {node.children.length > 0 && (
            <OutlineTree nodes={node.children} onSelect={onSelect} activeLabel={activeLabel} />
          )}
        </li>
      ))}
    </ul>
  );
}
