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
