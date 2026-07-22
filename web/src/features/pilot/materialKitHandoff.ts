export interface MaterialKitHandoff {
  readonly applicationId: number;
  readonly resumeId: number;
  readonly jdText: string;
}

function cloneAndFreeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    Object.freeze(value);
    for (const child of Object.values(value as Record<string, unknown>)) {
      cloneAndFreeze(child);
    }
  }
  return value;
}

function freezeHandoff(value: MaterialKitHandoff): MaterialKitHandoff {
  const copy: MaterialKitHandoff = {
    applicationId: value.applicationId,
    resumeId: value.resumeId,
    jdText: value.jdText,
  };
  return cloneAndFreeze(copy);
}

export interface MaterialKitHandoffStore {
  write: (handoff: MaterialKitHandoff) => void;
  consumeMaterialKitHandoff: (applicationId: number) => MaterialKitHandoff | null;
  clear: () => void;
}

export function createMaterialKitHandoffStore(): MaterialKitHandoffStore {
  let pending: MaterialKitHandoff | null = null;
  return {
    write: (handoff) => {
      pending = freezeHandoff(handoff);
    },
    consumeMaterialKitHandoff: (applicationId) => {
      if (!pending || pending.applicationId !== applicationId) return null;
      const value = pending;
      pending = null;
      return value;
    },
    clear: () => {
      pending = null;
    },
  };
}

export const materialKitHandoffStore = createMaterialKitHandoffStore();

export const writeMaterialKitHandoff = materialKitHandoffStore.write;
export const consumeMaterialKitHandoff = materialKitHandoffStore.consumeMaterialKitHandoff;
