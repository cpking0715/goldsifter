import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { wsService } from '@/services/websocket'

export const AUTH_TOKEN_KEY = 'auth_token'

export function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY)
}

// Global State — 只有持有签名 token 才算已登录
const token = ref<string | null>(getAuthToken())
const username = ref<string | null>(token.value ? localStorage.getItem('auth_username') : null)
const isLoggedIn = ref(Boolean(token.value))

export function useAuth() {
  const router = useRouter()

  const isAuthenticated = computed(() => isLoggedIn.value)

  function setAuthenticated(user: string, accessToken: string) {
    username.value = user
    token.value = accessToken
    isLoggedIn.value = true

    localStorage.setItem('auth_username', user)
    localStorage.setItem('auth_logged_in', 'true')
    localStorage.setItem(AUTH_TOKEN_KEY, accessToken)

    // 启动 WebSocket 连接
    wsService.start()
  }

  function logout() {
    username.value = null
    token.value = null
    isLoggedIn.value = false
    localStorage.removeItem('auth_username')
    localStorage.removeItem('auth_logged_in')
    localStorage.removeItem(AUTH_TOKEN_KEY)

    // 停止 WebSocket 连接
    wsService.stop()

    // Redirect to login if using router
    if (router) {
      router.push('/login')
    } else {
      window.location.href = '/login'
    }
  }

  async function login(user: string, pass: string): Promise<boolean> {
    try {
      const response = await fetch('/auth/status', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username: user, password: pass }),
      })

      if (response.ok) {
        const data = await response.json().catch(() => ({}))
        if (!data?.token) return false
        setAuthenticated(user, data.token)
        return true
      } else {
        return false
      }
    } catch (e) {
      console.error('Login error', e)
      return false
    }
  }

  return {
    username,
    isAuthenticated,
    login,
    logout
  }
}
