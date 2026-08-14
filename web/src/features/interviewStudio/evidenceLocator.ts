export interface StudioEvidenceReference {
  source: string;
  path: string;
  excerpt: string;
}

export interface StudioEvidenceEntry extends StudioEvidenceReference {
  key: string;
  label: string;
}

export function evidenceKey(reference: StudioEvidenceReference): string {
  return `${reference.source}:${reference.path}:${reference.excerpt}`;
}

function turnNumber(path: string): string | null {
  const match = path.match(/\/turns\/(\d+)\/answer/);
  return match ? String(Number(match[1])) : null;
}

function labelFor(reference: StudioEvidenceReference): string {
  const turn = reference.source === 'turn' ? turnNumber(reference.path) : null;
  if (turn) return `上一轮回答 · 第 ${turn} 轮`;
  if (reference.source === 'jd') return `冻结 JD · ${reference.path}`;
  if (reference.source === 'resume') return `冻结简历 · ${reference.path}`;
  return `${reference.source} · ${reference.path}`;
}

export function buildEvidenceEntries(
  references: StudioEvidenceReference[] | undefined,
): StudioEvidenceEntry[] {
  const seen = new Set<string>();
  return (references ?? []).filter((reference) => {
    const key = evidenceKey(reference);
    if (seen.has(key) || !reference.excerpt.trim()) return false;
    seen.add(key);
    return true;
  }).map((reference) => ({
    ...reference,
    key: evidenceKey(reference),
    label: labelFor(reference),
  }));
}
