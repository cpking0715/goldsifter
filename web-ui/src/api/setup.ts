import { http } from '@/lib/http'

export interface SetupStatus {
  password_changed: boolean
  ai_configured: boolean
  notification_configured: boolean
}

export async function getSetupStatus(): Promise<SetupStatus> {
  return await http('/api/setup/status')
}

export interface PasswordChangeResult {
  message: string
  token: string
  username: string
}

export async function changePassword(payload: {
  old_username: string
  old_password: string
  new_username: string
  new_password: string
}): Promise<PasswordChangeResult> {
  return await http('/api/auth/password', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
