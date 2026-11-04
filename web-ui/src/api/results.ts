import type { ResultCategoryCounts, ResultInsights, ResultItem } from '@/types/result.d.ts'
import { getAuthToken, useAuth } from '@/composables/useAuth'
import { http } from '@/lib/http'

export type ResultCategory =
  | 'all'
  | 'ai_recommended'
  | 'high_value'
  | 'keyword_hit'
  | 'favorite'
  | 'hidden'

export interface GetResultContentParams {
  category?: ResultCategory;
  search?: string;
  min_price?: number | null;
  max_price?: number | null;
  found_since?: string | null;
  include_hidden?: boolean;
  sort_by?: 'crawl_time' | 'publish_time' | 'price' | 'keyword_hit_count' | 'value_score';
  sort_order?: 'asc' | 'desc';
  page?: number;
  limit?: number;
}

export async function getResultFiles(): Promise<string[]> {
  const data = await http('/api/results/files')
  return data.files || []
}

export async function deleteResultFile(filename: string): Promise<{ message: string }> {
  return await http(`/api/results/files/${filename}`, { method: 'DELETE' })
}

export async function getResultContent(
  filename: string,
  params: GetResultContentParams = {}
): Promise<{ total_items: number; items: ResultItem[]; counts?: ResultCategoryCounts }> {
  return await http(`/api/results/${filename}`, { params: params as Record<string, any> })
}

export async function getResultCounts(filename: string): Promise<ResultCategoryCounts> {
  const data = await http(`/api/results/${filename}/counts`)
  return data.counts
}

export async function getResultInsights(filename: string): Promise<ResultInsights> {
  return await http(`/api/results/${filename}/insights`)
}

export async function getResultBlacklistRules(filename: string): Promise<{ keywords: string[] }> {
  return await http(`/api/results/${filename}/blacklist-rules`)
}

export async function updateResultBlacklistRules(filename: string, keywords: string[]): Promise<{ message: string; keywords: string[] }> {
  return await http(`/api/results/${filename}/blacklist-rules`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords }),
  })
}

export function buildResultExportUrl(filename: string, params: GetResultContentParams = {}): string {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value))
    }
  })
  const queryString = searchParams.toString()
  return `/api/results/${encodeURIComponent(filename)}/export${queryString ? `?${queryString}` : ''}`
}

export async function downloadResultExport(filename: string, params: GetResultContentParams = {}) {
  const url = buildResultExportUrl(filename, params)
  const token = getAuthToken()
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (response.status === 401) {
    useAuth().logout()
    throw new Error('Unauthorized')
  }
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename.replace(/\.jsonl$/i, '.csv')
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(objectUrl)
}

export async function updateItemStatus(filename: string, itemId: string, status: string): Promise<{ message: string; status: string }> {
  return await http(`/api/results/${filename}/items/${itemId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
}

export async function updateItemFavorite(filename: string, itemId: string, favorite: boolean): Promise<{ message: string; favorite: boolean }> {
  return await http(`/api/results/${filename}/items/${itemId}/favorite`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ favorite }),
  })
}
