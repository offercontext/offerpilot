export type DiffModule =
  | 'contact'
  | 'education'
  | 'experience'
  | 'projects'
  | 'skills'
  | 'career_intent'
  | 'other';

export type DiffKind = 'added' | 'removed' | 'changed';

export type DiffText = {
  full: string;
  preview: string;
  truncated: boolean;
};

export type DiffValue = {
  valueType: 'string' | 'number' | 'boolean' | 'null' | 'object' | 'array' | 'unsupported';
  text: DiffText;
};

export type ResumeDiffItem = {
  kind: DiffKind;
  module: DiffModule;
  path: string;
  before?: DiffValue;
  after?: DiffValue;
};

export type ResumeVersionDiffResult = {
  items: ResumeDiffItem[];
  counts: {
    added: number;
    removed: number;
    changed: number;
  };
  identical: boolean;
};

type ContainerKind = 'object' | 'array';
type ValueKind = DiffValue['valueType'];

type ContainerEntry = {
  key: string;
  value: unknown;
};

type ContainerInfo = {
  kind: ContainerKind;
  entries: ContainerEntry[];
};

type Inspection = {
  kind: ValueKind;
  container?: ContainerInfo;
};

type SafeNode =
  | { kind: 'string'; value: string }
  | { kind: 'number'; value: number }
  | { kind: 'boolean'; value: boolean }
  | { kind: 'null' }
  | { kind: 'object'; entries: Array<[string, SafeNode]> }
  | { kind: 'array'; entries: SafeNode[] }
  | { kind: 'unsupported' };

const UNSUPPORTED_TEXT = '（无法安全展示）';
const UNSUPPORTED_MARKER = '__offerpilot_unsupported__';
const MAX_PREVIEW_CODE_POINTS = 160;
const MODULE_ORDER: DiffModule[] = [
  'contact',
  'education',
  'experience',
  'projects',
  'skills',
  'career_intent',
  'other',
];
const KIND_ORDER: DiffKind[] = ['added', 'removed', 'changed'];

export function diffResumeContent(
  baselineContent: unknown,
  targetContent: unknown,
): ResumeVersionDiffResult {
  const items: ResumeDiffItem[] = [];
  compareValues(baselineContent, targetContent, '', items, new Set<object>(), new Set<object>());

  items.sort((left, right) => {
    const moduleDifference = MODULE_ORDER.indexOf(left.module) - MODULE_ORDER.indexOf(right.module);
    if (moduleDifference !== 0) return moduleDifference;
    const pathDifference = left.path < right.path ? -1 : left.path > right.path ? 1 : 0;
    if (pathDifference !== 0) return pathDifference;
    return KIND_ORDER.indexOf(left.kind) - KIND_ORDER.indexOf(right.kind);
  });

  const counts = items.reduce(
    (result, item) => {
      result[item.kind] += 1;
      return result;
    },
    { added: 0, removed: 0, changed: 0 },
  );

  return {
    items,
    counts,
    identical: items.length === 0,
  };
}

function compareValues(
  left: unknown,
  right: unknown,
  path: string,
  items: ResumeDiffItem[],
  leftAncestors: Set<object>,
  rightAncestors: Set<object>,
) {
  if (Object.is(left, right)) return;

  const leftInspection = inspectValue(left);
  const rightInspection = inspectValue(right);
  const leftCycle = isCycleAtCurrent(left, leftAncestors);
  const rightCycle = isCycleAtCurrent(right, rightAncestors);

  if (leftCycle || rightCycle) {
    addChanged(items, path, left, right, true);
    return;
  }

  if (
    leftInspection.kind !== rightInspection.kind ||
    !isContainerKind(leftInspection.kind) ||
    !isContainerKind(rightInspection.kind)
  ) {
    addChanged(items, path, left, right);
    return;
  }

  const leftContainer = leftInspection.container;
  const rightContainer = rightInspection.container;
  if (!leftContainer || !rightContainer || leftContainer.kind !== rightContainer.kind) {
    addChanged(items, path, left, right);
    return;
  }

  if (!isObjectLike(left)) leftAncestors.clear();
  if (!isObjectLike(right)) rightAncestors.clear();
  if (isObjectLike(left)) leftAncestors.add(left);
  if (isObjectLike(right)) rightAncestors.add(right);

  const leftEntries = new Map(leftContainer.entries.map((entry) => [entry.key, entry.value]));
  const rightEntries = new Map(rightContainer.entries.map((entry) => [entry.key, entry.value]));
  const keys = Array.from(new Set([...leftEntries.keys(), ...rightEntries.keys()])).sort(compareKeys);

  for (const key of keys) {
    const childPath = appendPointer(path, key);
    const leftHasKey = leftEntries.has(key);
    const rightHasKey = rightEntries.has(key);
    if (!leftHasKey) {
      addAdded(items, childPath, rightEntries.get(key));
      continue;
    }
    if (!rightHasKey) {
      addRemoved(items, childPath, leftEntries.get(key));
      continue;
    }
    compareValues(
      leftEntries.get(key),
      rightEntries.get(key),
      childPath,
      items,
      leftAncestors,
      rightAncestors,
    );
  }

  if (isObjectLike(left)) leftAncestors.delete(left);
  if (isObjectLike(right)) rightAncestors.delete(right);
}

function addAdded(items: ResumeDiffItem[], path: string, value: unknown) {
  items.push({
    kind: 'added',
    module: moduleForPath(path),
    path,
    after: createDiffValue(value),
  });
}

function addRemoved(items: ResumeDiffItem[], path: string, value: unknown) {
  items.push({
    kind: 'removed',
    module: moduleForPath(path),
    path,
    before: createDiffValue(value),
  });
}

function addChanged(
  items: ResumeDiffItem[],
  path: string,
  left: unknown,
  right: unknown,
  forceUnsupported = false,
) {
  items.push({
    kind: 'changed',
    module: moduleForPath(path),
    path,
    before: createDiffValue(left, forceUnsupported),
    after: createDiffValue(right, forceUnsupported),
  });
}

function createDiffValue(value: unknown, forceUnsupported = false): DiffValue {
  if (forceUnsupported) {
    return {
      valueType: 'unsupported',
      text: makeDiffText(UNSUPPORTED_TEXT),
    };
  }

  const inspection = inspectValue(value);
  if (inspection.kind === 'string') {
    return { valueType: 'string', text: makeDiffText(value as string) };
  }
  if (inspection.kind === 'number') {
    return { valueType: 'number', text: makeDiffText(String(value)) };
  }
  if (inspection.kind === 'boolean') {
    return { valueType: 'boolean', text: makeDiffText(value ? 'true' : 'false') };
  }
  if (inspection.kind === 'null') {
    return { valueType: 'null', text: makeDiffText('null') };
  }
  if (inspection.kind === 'unsupported') {
    return { valueType: 'unsupported', text: makeDiffText(UNSUPPORTED_TEXT) };
  }

  const safeNode = buildSafeNode(value, new Set<object>());
  const full = canonicalSerialize(safeNode);
  return {
    valueType: inspection.kind,
    text: makeDiffText(full),
  };
}

function buildSafeNode(value: unknown, ancestors: Set<object>): SafeNode {
  const inspection = inspectValue(value);
  if (inspection.kind === 'string') return { kind: 'string', value: value as string };
  if (inspection.kind === 'number') return { kind: 'number', value: value as number };
  if (inspection.kind === 'boolean') return { kind: 'boolean', value: value as boolean };
  if (inspection.kind === 'null') return { kind: 'null' };
  if (inspection.kind === 'unsupported' || !inspection.container || !isObjectLike(value)) {
    return { kind: 'unsupported' };
  }
  if (ancestors.has(value)) return { kind: 'unsupported' };

  ancestors.add(value);
  const node = inspection.container.kind === 'array'
    ? {
        kind: 'array' as const,
        entries: inspection.container.entries.map((entry) => buildSafeNode(entry.value, ancestors)),
      }
    : {
        kind: 'object' as const,
        entries: inspection.container.entries
          .slice()
          .sort((left, right) => compareKeys(left.key, right.key))
          .map((entry) => [entry.key, buildSafeNode(entry.value, ancestors)] as [string, SafeNode]),
      };
  ancestors.delete(value);
  return node;
}

function canonicalSerialize(node: SafeNode): string {
  switch (node.kind) {
    case 'string':
      return JSON.stringify(node.value);
    case 'number':
      return String(node.value);
    case 'boolean':
      return node.value ? 'true' : 'false';
    case 'null':
      return 'null';
    case 'unsupported':
      return `{"${UNSUPPORTED_MARKER}":${JSON.stringify(UNSUPPORTED_TEXT)}}`;
    case 'array':
      return `[${node.entries.map(canonicalSerialize).join(',')}]`;
    case 'object':
      return `{${node.entries
        .map(([key, value]) => `${JSON.stringify(key)}:${canonicalSerialize(value)}`)
        .join(',')}}`;
  }
}

function inspectValue(value: unknown): Inspection {
  if (value === null) return { kind: 'null' };
  if (typeof value === 'string') return { kind: 'string' };
  if (typeof value === 'boolean') return { kind: 'boolean' };
  if (typeof value === 'number') return Number.isFinite(value) ? { kind: 'number' } : { kind: 'unsupported' };
  if (typeof value !== 'object') return { kind: 'unsupported' };

  return inspectContainer(value);
}

function inspectContainer(value: object): Inspection {
  try {
    const prototype = Object.getPrototypeOf(value);
    const ownKeys = Reflect.ownKeys(value);
    if (new Set(ownKeys).size !== ownKeys.length) return { kind: 'unsupported' };
    if (Array.isArray(value)) {
      return inspectArray(value, prototype, ownKeys);
    }
    return inspectObject(prototype, ownKeys, value);
  } catch {
    return { kind: 'unsupported' };
  }
}

function inspectObject(prototype: object | null, ownKeys: (string | symbol)[], value: object): Inspection {
  if (prototype !== Object.prototype && prototype !== null) return { kind: 'unsupported' };

  const entries: ContainerEntry[] = [];
  for (const key of ownKeys) {
    if (typeof key !== 'string') return { kind: 'unsupported' };
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !descriptor.enumerable || !('value' in descriptor)) return { kind: 'unsupported' };
    entries.push({ key, value: descriptor.value });
  }
  return { kind: 'object', container: { kind: 'object', entries } };
}

function inspectArray(value: object, prototype: object | null, ownKeys: (string | symbol)[]): Inspection {
  if (prototype !== Array.prototype) return { kind: 'unsupported' };

  const lengthDescriptor = Object.getOwnPropertyDescriptor(value, 'length');
  if (!lengthDescriptor || !('value' in lengthDescriptor) || lengthDescriptor.enumerable) {
    return { kind: 'unsupported' };
  }
  const length = lengthDescriptor.value;
  if (typeof length !== 'number' || !Number.isInteger(length) || length < 0) return { kind: 'unsupported' };

  const indexKeys: string[] = [];
  for (const key of ownKeys) {
    if (typeof key !== 'string') return { kind: 'unsupported' };
    if (key === 'length') continue;
    if (!isArrayIndexKey(key, length)) return { kind: 'unsupported' };
    indexKeys.push(key);
  }
  if (indexKeys.length !== length) return { kind: 'unsupported' };
  indexKeys.sort((left, right) => Number(left) - Number(right));

  const entries: ContainerEntry[] = [];
  for (let index = 0; index < indexKeys.length; index += 1) {
    const key = indexKeys[index];
    if (key !== String(index)) return { kind: 'unsupported' };
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !descriptor.enumerable || !('value' in descriptor)) return { kind: 'unsupported' };
    entries.push({ key, value: descriptor.value });
  }
  return { kind: 'array', container: { kind: 'array', entries } };
}

function isArrayIndexKey(key: string, length: number) {
  if (key === '' || key === '0') return key === '0' && length > 0;
  if (!/^[1-9]\d*$/.test(key)) return false;
  const index = Number(key);
  return Number.isSafeInteger(index) && index >= 0 && index < length && String(index) === key;
}

function isObjectLike(value: unknown): value is object {
  return typeof value === 'object' && value !== null;
}

function isContainerKind(kind: ValueKind): kind is ContainerKind {
  return kind === 'object' || kind === 'array';
}

function isCycleAtCurrent(value: unknown, ancestors: Set<object>) {
  return isObjectLike(value) && ancestors.has(value);
}

function appendPointer(path: string, key: string) {
  return `${path}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;
}

function moduleForPath(path: string): DiffModule {
  if (path === '') return 'other';
  const firstSegment = path.slice(1).split('/')[0].replace(/~1/g, '/').replace(/~0/g, '~');
  return MODULE_ORDER.includes(firstSegment as DiffModule) ? firstSegment as DiffModule : 'other';
}

function compareKeys(left: string, right: string) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function makeDiffText(full: string): DiffText {
  const codePoints = Array.from(full);
  if (codePoints.length <= MAX_PREVIEW_CODE_POINTS) {
    return { full, preview: full, truncated: false };
  }
  return {
    full,
    preview: `${codePoints.slice(0, MAX_PREVIEW_CODE_POINTS).join('')}…`,
    truncated: true,
  };
}
