import { http } from '@/lib/http'

export interface AIModelPreset {
  name: string
  vision: boolean
  badge: '' | 'free' | 'free_quota'
  note: string
}

export interface AIProviderPreset {
  id: string
  display_name: string
  base_url: string
  models: AIModelPreset[]
  key_url: string
  docs_url: string
  note: string
  recommended_text_model: string
}

export async function listAiProviders(): Promise<AIProviderPreset[]> {
  return await http('/api/ai-providers')
}

/** 依据当前 base_url 反推供应商（编辑回显用）；无匹配返回 custom */
export function matchProvider(providers: AIProviderPreset[], baseUrl: string): AIProviderPreset | undefined {
  const target = (baseUrl || '').trim().replace(/\/+$/, '')
  if (!target) return undefined
  return (
    providers.find((p) => p.id !== 'custom' && p.base_url.replace(/\/+$/, '') === target) ||
    providers.find((p) => p.id === 'custom')
  )
}
