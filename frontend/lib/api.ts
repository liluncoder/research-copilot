/** 后端地址与接口类型（前端唯一知道后端在哪的地方）。 */

// ★NEXT_PUBLIC_* 是**构建时**烧进代码的，不是运行时读的。
// 本地 Docker 构建没传这个变量 ⇒ 用下面这个兜底值（正好对）。
// 11 月部署到 HF Spaces 时必须用 build arg 传公网地址，否则线上前端会去连 localhost。
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DocumentMeta = {
  doc_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  doc_type: "text" | "scanned" | string;
  page_count: number;
  title: string | null;
  authors: string[];
  abstract_chars: number;
  n_headings: number;
  n_references: number;
  n_math_lines: number;
  warnings: string[];
  parse_seconds: number;
  duplicate_of: string | null;
};

export type OutlineNode = {
  label: string;
  level: number;
  page: number;
  children: OutlineNode[];
};

export type Section = {
  label: string;
  level: number;
  page_start: number;
  page_end: number;
  paragraphs: string[];
  math_lines: string[];
  n_chars: number;
};

export type Reference = {
  index: number;
  raw: string;
  year: number | null;
  arxiv_id: string | null;
};

export type UploadResult = {
  meta: DocumentMeta;
  outline: OutlineNode[];
  outline_flat: unknown[];
  references_preview: Reference[];
  dedup: DedupInfo;
};

export type DedupCandidate = {
  doc_id: string;
  filename: string;
  similarity: number;
  title_match: boolean;
  same_arxiv_id: boolean;
  existing_version: number | null;
  incoming_version: number | null;
  existing_is_newer: boolean;
  reason: string;
};

export type DedupInfo = {
  has_warning: boolean;
  threshold: number;
  metric: string;
  candidates: DedupCandidate[];
  exists_newer: boolean;
};

export type VersionDiff = {
  diff: {
    old_label: string;
    new_label: string;
    text_len: { old: number; new: number; delta: number };
    headings: { old: number; new: number; added: string[]; removed: string[] };
    references: { old: number; new: number; added: string[]; removed: string[] };
    changed_sections: { label: string; before: number; after: number; delta: number }[];
    math_lines: { old: number; new: number };
  };
  summary: string;
  summary_source: "llm" | "deterministic" | string;
  fallback_summary: string;
};

export type ParsedTable = {
  index: number;
  number: number | null;
  page: number;
  caption: string;
  n_rows: number;
  n_cols: number;
  header_rows: number;
  method: string;
  confidence: number;
  rows: string[][];
  markdown: string;
};

export type DocumentDetail = {
  meta: DocumentMeta;
  outline: OutlineNode[];
  outline_flat: unknown[];
  references: Reference[];
  sections: Section[];
  math_lines: { page: number; text: string; math_chars: number }[];
  tables?: ParsedTable[];
  abstract: string;
};

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 后端没返回 JSON，就用状态码 */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export type DocumentListResult = { count: number; items: DocumentMeta[] };

export function listDocuments(): Promise<DocumentListResult> {
  return fetch(`${API_URL}/api/v1/documents`, { cache: "no-store" }).then((r) =>
    asJson<DocumentListResult>(r),
  );
}

export function getDocument(docId: string): Promise<DocumentDetail> {
  return fetch(`${API_URL}/api/v1/documents/${docId}`, { cache: "no-store" }).then((r) =>
    asJson<DocumentDetail>(r),
  );
}

export function uploadDocument(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${API_URL}/api/v1/documents`, { method: "POST", body: form }).then((r) =>
    asJson<UploadResult>(r),
  );
}

export function deleteDocument(docId: string): Promise<{ deleted: string }> {
  return fetch(`${API_URL}/api/v1/documents/${docId}`, { method: "DELETE" }).then((r) =>
    asJson<{ deleted: string }>(r),
  );
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

// ---------------- S2 问答（J4） ----------------

export type QAStep = { node: string; detail: string; ms: number };

export type QAHit = {
  chunk_id: string;
  doc_id: string;
  filename: string;
  section: string;
  page: string;
  score: number;
  dense_rank: number | null;
  sparse_rank: number | null;
  text: string;
  citation: string;
};

export type QAResult = {
  question: string;
  answer: string;
  refused: boolean;
  citations: string[];
  invalid_citations: string[];
  hits: QAHit[];
  steps: QAStep[];
  orchestrator: string;
  error: string | null;
};

export function askQuestion(
  question: string,
  opts: { docIds?: string[]; topK?: number } = {},
): Promise<QAResult> {
  return fetch(`${API_URL}/api/v1/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      doc_ids: opts.docIds ?? null,
      top_k: opts.topK ?? 5,
    }),
  }).then((r) => asJson<QAResult>(r));
}

// ---------------- S3 阅读器（J5） ----------------

export type ReaderParagraph = {
  para_id: string;
  section: string;
  section_index: number;
  page_start: number;
  page_end: number;
  index_in_section: number;
  text: string;
  citations: number[];
};

export type ReaderRef = {
  index: number;
  raw: string;
  year: number | null;
  arxiv_id: string | null;
  cited_count: number;
  cited_in: string[];
};

export type ReaderSection = {
  index: number;
  label: string;
  level: number;
  page_start: number;
  page_end: number;
  n_paragraphs: number;
  para_ids: string[];
  nav_para_id?: string | null;
};

export type ReaderView = {
  doc_id: string;
  source: string;
  title: string | null;
  authors: string[];
  abstract: string;
  outline: OutlineNode[];
  sections: ReaderSection[];
  paragraphs: ReaderParagraph[];
  references: ReaderRef[];
  cited_by: Record<string, string[]>;
  stats: {
    n_sections: number;
    n_paragraphs: number;
    n_references: number;
    n_citation_marks: number;
    n_refs_cited: number;
    dangling_citations: number[];
  };
  meta: { filename: string; title: string | null; page_count: number; doc_type: string };
};

export function getReader(docId: string): Promise<ReaderView> {
  return fetch(`${API_URL}/api/v1/documents/${docId}/reader`, { cache: "no-store" }).then((r) =>
    asJson<ReaderView>(r),
  );
}

export type TranslateResult = {
  items: Record<string, string>;
  cached: number;
  translated: number;
  failed: number;
  errors?: string[];
};

export function translateParagraphs(docId: string, paraIds?: string[]): Promise<TranslateResult> {
  return fetch(`${API_URL}/api/v1/documents/${docId}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ para_ids: paraIds ?? null, limit: 8 }),
  }).then((r) => asJson<TranslateResult>(r));
}

export type DedupAction = "keep_both" | "replace_existing" | "discard_new";

export function resolveDedup(
  docId: string,
  action: DedupAction,
  targetDocId?: string,
): Promise<{ action: string; kept: string | null; deleted: string | null }> {
  return fetch(`${API_URL}/api/v1/documents/dedup/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, target_doc_id: targetDocId ?? null, action }),
  }).then((r) => asJson<{ action: string; kept: string | null; deleted: string | null }>(r));
}

export function compareDocuments(
  olderId: string,
  newerId: string,
  useLlm = true,
): Promise<VersionDiff> {
  const q = useLlm ? "" : "?use_llm=false";
  return fetch(`${API_URL}/api/v1/documents/${olderId}/compare/${newerId}${q}`, {
    cache: "no-store",
  }).then((r) => asJson<VersionDiff>(r));
}

// ---------------- S5 引用图谱（J6） ----------------

export type GraphNode = {
  id: string;
  label: string;
  kind: "local" | "external" | string;
  year: number | null;
  in_library: boolean;
  pagerank: number;
  pagerank_core: number;
  centrality: number;
  cited_by_local: number;
  cites: number;
};

export type GraphEdge = { source: string; target: string; refs: number };

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  display: { nodes: GraphNode[]; edges: GraphEdge[]; n_nodes: number; n_edges: number };
  stats: {
    n_nodes: number;
    n_local: number;
    n_external: number;
    n_edges: number;
    n_reference_entries: number;
    n_matched_to_local: number;
    local_match_rate: number;
    density: number;
  };
  foundational: {
    pagerank: GraphNode[];
    in_degree: GraphNode[];
    note: string;
  };
};

export function getGraph(limit = 40, top = 12): Promise<GraphData> {
  return fetch(`${API_URL}/api/v1/graph?limit=${limit}&top=${top}`, { cache: "no-store" }).then(
    (r) => asJson<GraphData>(r),
  );
}

export type GraphReview = {
  review: string;
  facts?: string[];
  allowed_titles?: string[];
  stats?: GraphData["stats"];
  error?: string;
  model?: string;
};

export function reviewGraph(top = 8): Promise<GraphReview> {
  return fetch(`${API_URL}/api/v1/graph/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ top }),
  }).then((r) => asJson<GraphReview>(r));
}

// ---------------- S6 写作 Copilot（J7 / J8） ----------------

export type ChartSpec = {
  title?: { text?: string; left?: string };
  tooltip?: Record<string, unknown>;
  legend?: Record<string, unknown>;
  grid?: Record<string, unknown>;
  xAxis?: Record<string, unknown>;
  yAxis?: Record<string, unknown>;
  series: { name: string; type: string; data: number[]; showSymbol?: boolean; smooth?: boolean }[];
};

export type FigureStats = {
  metric: string;
  n_rows: number;
  groups: Record<string, Record<string, number>>;
  overall: Record<string, number>;
};

export type FigureResult = {
  stats: FigureStats;
  chart: ChartSpec;
  caption: string;
  warnings: string[];
  model: string | null;
};

export function makeFigure(
  file: File | Blob,
  opts: { metric?: string; groupBy?: string; kind?: string; filename?: string } = {},
): Promise<FigureResult> {
  const form = new FormData();
  form.append("file", file, opts.filename ?? "data.csv");
  const q = new URLSearchParams();
  if (opts.metric) q.set("metric", opts.metric);
  if (opts.groupBy) q.set("group_by", opts.groupBy);
  if (opts.kind) q.set("kind", opts.kind);
  return fetch(`${API_URL}/api/v1/writing/figure?${q.toString()}`, {
    method: "POST",
    body: form,
  }).then((r) => asJson<FigureResult>(r));
}

export type FrameworkRef = {
  n: number;
  doc_id: string;
  title: string;
  authors: string[];
  year: number | null;
  source: string;
};

export type FrameworkResult = {
  topic: string;
  sections: Record<string, string>;
  references: FrameworkRef[];
  invalid_refs: string[];
  n_candidates: number;
  n_citations: number;
  model: string | null;
  error: string | null;
};

export function buildFramework(
  topic: string,
  opts: { docIds?: string[]; useEvidence?: boolean } = {},
): Promise<FrameworkResult> {
  return fetch(`${API_URL}/api/v1/writing/framework`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      doc_ids: opts.docIds ?? null,
      use_evidence: opts.useEvidence ?? true,
    }),
  }).then((r) => asJson<FrameworkResult>(r));
}

export function translateAbstract(text: string): Promise<{ text: string; model?: string; error?: string }> {
  return fetch(`${API_URL}/api/v1/writing/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target: "en" }),
  }).then((r) => asJson<{ text: string; model?: string; error?: string }>(r));
}
