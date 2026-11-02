import { http } from '@/lib/http'

export interface CloudLicense {
  ok: boolean
  key: string
  plan: string
  expires_at: string | null
  expired: boolean
  last_verified_at?: string
}

export interface CloudStatus {
  server_url: string
  server_reachable: boolean
  device_id: string
  app_version: string
  license: CloudLicense | null
  telemetry: {
    enabled: boolean
    state: {
      last_snapshot_id?: number
      last_uploaded_at?: string
      uploaded_total?: number
    }
  }
}

export interface UpdateCheckResult {
  current_version: string
  latest: { version: string; url: string | null; notes?: string; mandatory?: boolean } | null
  error?: string
}

export async function getCloudStatus(): Promise<CloudStatus> {
  return await http('/api/cloud/status')
}

export async function activateLicense(key: string): Promise<CloudStatus['license']> {
  const result = await http('/api/cloud/license/activate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  })
  return result.license
}

export async function verifyLicense(): Promise<{ licensed: boolean; reason: string | null; in_grace?: boolean; offline?: boolean }> {
  return await http('/api/cloud/license/verify', { method: 'POST' })
}

export async function setTelemetryEnabled(enabled: boolean): Promise<boolean> {
  const result = await http('/api/cloud/telemetry', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  return result.enabled
}

export async function flushTelemetry(): Promise<number> {
  const result = await http('/api/cloud/telemetry/flush', { method: 'POST' })
  return result.uploaded
}

export async function checkUpdate(): Promise<UpdateCheckResult> {
  return await http('/api/cloud/update-check', { method: 'POST' })
}
