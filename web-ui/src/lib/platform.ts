import { t } from '@/i18n'

export function platformLabel(platform?: string | null) {
  const id = String(platform || 'xianyu').trim().toLowerCase() || 'xianyu'
  const key = `platforms.${id}`
  const translated = t(key)
  return translated === key ? id : translated
}

export function platformNeedsLogin(platform?: string | null) {
  return String(platform || 'xianyu').trim().toLowerCase() !== 'kongfz'
}

export function parseResultFilename(filename: string) {
  const stem = String(filename || '').replace(/_full_data\.jsonl$/i, '')
  const marker = stem.indexOf('__')
  if (marker > 0) {
    const platform = stem.slice(0, marker).toLowerCase()
    if (platform && platform !== 'xianyu') {
      return { platform, keyword: stem.slice(marker + 2) }
    }
  }
  return { platform: 'xianyu', keyword: stem }
}
