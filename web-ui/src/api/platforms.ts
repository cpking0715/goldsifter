import { http } from '@/lib/http'

export interface PlatformCapabilities {
  price_range: boolean
  personal_only: boolean
  free_shipping: boolean
  new_publish_option: boolean
  region: boolean
  requires_login_state: boolean
  seller_profile: boolean
}

export interface PlatformInfo {
  platform_id: string
  display_name: string
  capabilities: PlatformCapabilities
}

export async function listPlatforms(): Promise<PlatformInfo[]> {
  return await http('/api/platforms')
}
