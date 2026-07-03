import axios from 'axios';
import type {
  ApplicationMaterialKit,
  GenerateMaterialKitInput,
  MaterialKitContent,
  MaterialKitViewModel,
  UpdateMaterialKitInput,
} from '@/types/materialKit';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

const emptyContent: MaterialKitContent = {
  resume_advice: { summary: '', highlights: [], rewrite_bullets: [], gaps: [], notes: '' },
  messages: [],
  checklist: [],
};

function normalizeContent(value: unknown): MaterialKitContent {
  if (!value || typeof value !== 'object') return emptyContent;

  const content = value as Partial<MaterialKitContent>;
  return {
    resume_advice: {
      ...emptyContent.resume_advice,
      ...(content.resume_advice || {}),
    },
    messages: Array.isArray(content.messages) ? content.messages : [],
    checklist: Array.isArray(content.checklist) ? content.checklist : [],
  };
}

export function parseMaterialKit(raw: ApplicationMaterialKit): MaterialKitViewModel {
  try {
    return { ...raw, content: normalizeContent(JSON.parse(raw.content_json || '{}')) };
  } catch {
    return { ...raw, content: emptyContent };
  }
}

export async function getApplicationMaterialKit(applicationID: number): Promise<MaterialKitViewModel | null> {
  try {
    const { data } = await http.get<ApplicationMaterialKit>(`/applications/${applicationID}/material-kit`);
    return parseMaterialKit(data);
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function generateApplicationMaterialKit(
  applicationID: number,
  input: GenerateMaterialKitInput,
): Promise<MaterialKitViewModel> {
  const { data } = await http.post<ApplicationMaterialKit>(
    `/applications/${applicationID}/material-kit/generate`,
    input,
  );
  return parseMaterialKit(data);
}

export async function updateMaterialKit(
  kitID: number,
  input: UpdateMaterialKitInput,
): Promise<MaterialKitViewModel> {
  const { data } = await http.put<ApplicationMaterialKit>(`/material-kits/${kitID}`, {
    ...input,
    content_json: JSON.stringify(input.content_json),
  });
  return parseMaterialKit(data);
}
