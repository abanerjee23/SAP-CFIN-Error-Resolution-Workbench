/** Display identity is projected from verified extraction, never guessed from the log. */
export type MetadataKey = 'sourceSystem' | 'sourceClient' | 'targetSystem' | 'targetClient' | 'company' | 'document' | 'interface';
export type SavedCaseMetadata = Partial<Record<MetadataKey, string>>;
type RecordValue = Record<string, unknown>;

const labels: Record<string, MetadataKey> = {
  'source system': 'sourceSystem', 'source client': 'sourceClient',
  'target system': 'targetSystem', 'target client': 'targetClient',
  'source company': 'company', 'source company code': 'company',
  'source document': 'document', 'source document number': 'document',
  interface: 'interface', 'interface name': 'interface',
};
const genericLabels: Record<string, MetadataKey> = {
  document: 'document', 'document number': 'document', 'company code': 'company',
};
const normalized = (value: string) => value.trim().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
const isRecord = (value: unknown): value is RecordValue => !!value && typeof value === 'object' && !Array.isArray(value);
const identifierCharacter = (value: string | undefined) => !!value && /[\p{L}\p{N}_/-]/u.test(value);

/** Verify a supplied pair, not a parser: both label and value must be adjacent in its cited text. */
function supportsPair(raw: string, label: string, value: string): boolean {
  if (value !== value.trim() || /[\r\n;|]/.test(value)) return false;
  const lower = raw.toLowerCase(), name = label.toLowerCase();
  for (let offset = lower.indexOf(name); offset !== -1; offset = lower.indexOf(name, offset + name.length)) {
    // The entire field label must begin the clause. A suffix such as "company code"
    // in "target company code" must never become a primary/source identity.
    if (raw.slice(0, offset).split(/[;|\r\n]/).at(-1)?.trim()) continue;
    let start = offset + name.length;
    // The extraction keeps the literal label spelling. Only field separators may intervene.
    const rest = raw.slice(start), separator = rest.match(/^(?:[ \t]*[:=][ \t]*|[ \t]+)/)?.[0];
    if (!separator) continue;
    start += separator.length;
    if (raw.slice(start, start + value.length) !== value) continue;
    if (identifierCharacter(raw[start + value.length])) continue;
    if (raw[start + value.length] === '.' && identifierCharacter(raw[start + value.length + 1])) continue;
    return true;
  }
  return false;
}

/** Every candidate's entry must first pass the same source-span check as visible citations. */
export function projectSavedMetadata(entries: RecordValue[], verifyEntry: (entry: RecordValue) => unknown): SavedCaseMetadata {
  const values = new Map<MetadataKey, Set<string>>();
  for (const entry of entries) {
    if (!Array.isArray(entry.fields)) continue;
    for (const field of entry.fields) {
      if (!isRecord(field) || typeof field.name_as_logged !== 'string' || typeof field.value_as_logged !== 'string') continue;
      const label = normalized(field.name_as_logged);
      let key: MetadataKey | undefined = Object.hasOwn(labels, label) ? labels[label] : undefined;
      // Unscoped document/company labels describe the primary document only in metadata.
      // A company mentioned inside an error or payload can be a target company instead.
      if (!key && entry.kind === 'metadata' && Object.hasOwn(genericLabels, label)) key = genericLabels[label];
      // The extraction contract also keeps the primary document_number in payload rows.
      if (!key && entry.kind === 'payload' && label === 'document number') key = 'document';
      if (!key) continue;
      const scope = typeof field.context_as_logged === 'string' ? normalized(field.context_as_logged) : '';
      const lineContext = scope.match(/^line ([1-9]\d*)$/);
      const attemptContext = typeof field.context_as_logged === 'string'
        ? field.context_as_logged.trim().match(/^(attempt_id|attempt id)[ \t]*[:=][ \t]*([^;|\r\n]+)$/i) : null;
      if (scope && scope !== 'source' && scope !== 'target' && !lineContext && !attemptContext) continue;
      if (scope === 'target' && (key === 'company' || key === 'document' || key.startsWith('source'))) continue;
      if (scope === 'source' && key.startsWith('target')) continue;
      verifyEntry(entry);
      const value = field.value_as_logged;
      if (!value.trim() || typeof entry.raw_text !== 'string') continue;
      let citedText = entry.raw_text;
      if (attemptContext) {
        // Compact extraction can group one attempt's header. Its scope must be
        // explicitly logged in this span, with no different attempt mixed in.
        const attempts = citedText.split(/[;|\r\n]/).map(clause => clause.trim())
          .filter(clause => /^attempt(?:_|[ \t]+)id(?:[ \t]*[:=]|[ \t]+)/i.test(clause));
        if (!attempts.length || !attempts.every(clause => supportsPair(clause, attemptContext[1], attemptContext[2]))) continue;
      }
      if (lineContext) {
        const span = entry.source_span;
        if (!isRecord(span) || typeof span.line_start !== 'number' || typeof span.line_end !== 'number') continue;
        const line = Number(lineContext[1]);
        if (!Number.isSafeInteger(line) || line < span.line_start || line > span.line_end) continue;
        citedText = entry.raw_text.split(/\r\n|\n|\r/)[line - span.line_start] || '';
      }
      if (!supportsPair(citedText, field.name_as_logged, value)) continue;
      if (!values.has(key)) values.set(key, new Set());
      values.get(key)!.add(value);
    }
  }
  return Object.fromEntries([...values].map(([key, candidates]) => {
    const sorted = [...candidates].sort();
    return [key, sorted.length === 1 ? sorted[0] : `Conflicting values: ${sorted.join(', ')}`];
  }));
}
