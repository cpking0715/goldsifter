<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSettings } from '@/composables/useSettings'
import type { NotificationSettingsUpdate, NotificationTestResponse } from '@/api/settings'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from '@/components/ui/toast'
import { getPromptContent, listPrompts, updatePrompt } from '@/api/prompts'
import {
  activateLicense,
  checkUpdate,
  flushTelemetry,
  getCloudStatus,
  setTelemetryEnabled,
  verifyLicense,
  type CloudStatus,
  type UpdateCheckResult,
} from '@/api/cloud'
import { changePassword } from '@/api/setup'
import {
  listAiProviders,
  matchProvider,
  type AIProviderPreset,
} from '@/api/aiProviders'
import { Switch } from '@/components/ui/switch'
import NotificationSettingsPanel from '@/components/settings/NotificationSettingsPanel.vue'
import RotationSettingsPanel from '@/components/settings/RotationSettingsPanel.vue'
const { t } = useI18n()

const {
  notificationSettings,
  aiSettings,
  rotationSettings,
  systemStatus,
  isLoading,
  isSaving,
  isReady,
  error,
  refreshStatus,
  saveNotificationSettings,
  testNotification,
  saveAiSettings,
  saveRotationSettings,
  testAiConnection
} = useSettings()

const activeTab = ref('ai')
const route = useRoute()
const validTabs = new Set(['notifications', 'ai', 'rotation', 'status', 'prompts', 'cloud'])

// ---- 云服务（授权 / 行情回传 / 更新） ----
const cloudStatus = ref<CloudStatus | null>(null)
const licenseKeyInput = ref('')
const isCloudBusy = ref(false)
const updateResult = ref<UpdateCheckResult | null>(null)

// ---- 账号与安全（改用户名/密码） ----
const securityForm = ref({ old_username: '', old_password: '', new_username: '', new_password: '' })
const isSecurityBusy = ref(false)

async function handleChangePassword() {
  const f = securityForm.value
  if (!f.old_username || !f.old_password || !f.new_username || !f.new_password) return
  isSecurityBusy.value = true
  try {
    const result = await changePassword({ ...f })
    notifySuccess(result.message)
    // 旧 token 已失效：换存新 token
    localStorage.setItem('auth_token', result.token)
    localStorage.setItem('auth_username', result.username)
    securityForm.value = { old_username: '', old_password: '', new_username: '', new_password: '' }
  } catch (e) {
    notifyError(t('settings.security.changeFailed'), (e as Error).message)
  } finally {
    isSecurityBusy.value = false
  }
}

// ---- AI 供应商预设 ----
const aiProviders = ref<AIProviderPreset[]>([])
const selectedProviderId = ref<string>('zhipu')
const showAiGuide = ref(true)

const selectedProvider = computed(() =>
  aiProviders.value.find((p) => p.id === selectedProviderId.value),
)
const selectedModelPreset = computed(() =>
  selectedProvider.value?.models.find((m) => m.name === aiSettings.value.OPENAI_MODEL_NAME),
)

async function loadAiProviders() {
  try {
    aiProviders.value = await listAiProviders()
    // 依据已保存的 base_url 回显供应商
    if (aiProviders.value.length) {
      const matched = matchProvider(aiProviders.value, aiSettings.value.OPENAI_BASE_URL || '')
      if (matched) selectedProviderId.value = matched.id
    }
  } catch (e) {
    console.error('load ai providers failed', e)
    aiProviders.value = []
  }
}

function onProviderChange(providerId: string) {
  selectedProviderId.value = providerId
  const provider = aiProviders.value.find((p) => p.id === providerId)
  if (!provider) return
  if (provider.id !== 'custom') {
    aiSettings.value.OPENAI_BASE_URL = provider.base_url
    // 默认选第一个支持看图的模型；没有则选第一个
    const preferred = provider.models.find((m) => m.vision) || provider.models[0]
    if (preferred) aiSettings.value.OPENAI_MODEL_NAME = preferred.name
    aiSettings.value.OPENAI_TEXT_MODEL_NAME = provider.recommended_text_model || ''
  }
}

watch(isReady, (ready) => {
  if (ready && !aiProviders.value.length) loadAiProviders()
}, { immediate: true })

async function refreshCloudStatus() {
  try {
    cloudStatus.value = await getCloudStatus()
  } catch (e) {
    console.error('cloud status failed', e)
  }
}

async function handleActivateLicense() {
  if (!licenseKeyInput.value.trim()) return
  isCloudBusy.value = true
  try {
    await activateLicense(licenseKeyInput.value.trim())
    licenseKeyInput.value = ''
    notifySuccess(t('settings.cloud.licenseActivated'))
    await refreshCloudStatus()
  } catch (e) {
    notifyError(t('settings.cloud.licenseActivateFailed'), (e as Error).message)
  } finally {
    isCloudBusy.value = false
  }
}

async function handleVerifyLicense() {
  isCloudBusy.value = true
  try {
    const result = await verifyLicense()
    if (result.licensed) {
      notifySuccess(t('settings.cloud.licenseValid'), result.in_grace ? t('settings.cloud.inGrace') : undefined)
    } else {
      notifyError(t('settings.cloud.licenseInvalid'), result.reason || undefined)
    }
    await refreshCloudStatus()
  } catch (e) {
    notifyError(t('settings.cloud.licenseVerifyFailed'), (e as Error).message)
  } finally {
    isCloudBusy.value = false
  }
}

async function handleToggleTelemetry(enabled: boolean) {
  try {
    await setTelemetryEnabled(enabled)
    await refreshCloudStatus()
    notifySuccess(enabled ? t('settings.cloud.telemetryOn') : t('settings.cloud.telemetryOff'))
  } catch (e) {
    notifyError(t('common.operationFailed'), (e as Error).message)
  }
}

async function handleFlushTelemetry() {
  isCloudBusy.value = true
  try {
    const uploaded = await flushTelemetry()
    notifySuccess(t('settings.cloud.telemetryFlushed'), `${uploaded}`)
    await refreshCloudStatus()
  } catch (e) {
    notifyError(t('common.operationFailed'), (e as Error).message)
  } finally {
    isCloudBusy.value = false
  }
}

async function handleCheckUpdate() {
  isCloudBusy.value = true
  try {
    updateResult.value = await checkUpdate()
  } catch (e) {
    notifyError(t('common.operationFailed'), (e as Error).message)
  } finally {
    isCloudBusy.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'cloud' && !cloudStatus.value) refreshCloudStatus()
})

const promptFiles = ref<string[]>([])
const selectedPrompt = ref<string | null>(null)
const promptContent = ref('')
const isPromptLoading = ref(false)
const isPromptSaving = ref(false)
const promptError = ref<string | null>(null)

function notifySuccess(title: string, description?: string) {
  toast({ title, description })
}

function notifyError(title: string, description?: string) {
  toast({ title, description, variant: 'destructive' })
}

async function handleSaveNotifications(payload: NotificationSettingsUpdate) {
  try {
    await saveNotificationSettings(payload)
    notifySuccess(t('settings.notifications.saved'))
  } catch (e) {
    notifyError(t('settings.notifications.saveFailed'), (e as Error).message)
  }
}

async function handleTestNotification(payload: {
  channel?: string
  settings: NotificationSettingsUpdate
}): Promise<NotificationTestResponse> {
  try {
    const result = await testNotification(payload)
    return result
  } catch (e) {
    notifyError(t('settings.notifications.testFailed'), (e as Error).message)
    throw e
  }
}

async function handleSaveAi() {
  try {
    await saveAiSettings()
    notifySuccess(t('settings.ai.saved'))
  } catch (e) {
    notifyError(t('settings.ai.saveFailed'), (e as Error).message)
  }
}

async function handleSaveRotation() {
  try {
    await saveRotationSettings()
    notifySuccess(t('settings.rotation.saved'))
  } catch (e) {
    notifyError(t('settings.rotation.saveFailed'), (e as Error).message)
  }
}

async function handleTestAi() {
  try {
    const res = await testAiConnection()
    notifySuccess(t('settings.ai.testSuccess'), res.message)
  } catch (e) {
    notifyError(t('settings.ai.testFailed'), (e as Error).message)
  }
}

async function fetchPrompts() {
  isPromptLoading.value = true
  promptError.value = null
  try {
    const files = await listPrompts()
    promptFiles.value = files

    if (selectedPrompt.value && files.includes(selectedPrompt.value)) {
      return
    }

    const lastSelected = localStorage.getItem('lastSelectedPrompt')
    if (lastSelected && files.includes(lastSelected)) {
      selectedPrompt.value = lastSelected
      return
    }

    selectedPrompt.value = files[0] || null
  } catch (e) {
    promptError.value = (e as Error).message || t('settings.prompts.promptListFailed')
  } finally {
    isPromptLoading.value = false
  }
}

async function handleSavePrompt() {
  if (!selectedPrompt.value) {
    notifyError(t('settings.prompts.selectPromptFile'))
    return
  }
  isPromptSaving.value = true
  try {
    const res = await updatePrompt(selectedPrompt.value, promptContent.value)
    notifySuccess(t('settings.prompts.saveSuccess'), res.message)
  } catch (e) {
    notifyError(t('settings.prompts.saveFailed'), (e as Error).message)
  } finally {
    isPromptSaving.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'prompts') {
    fetchPrompts()
  }
})

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && validTabs.has(tab)) {
      activeTab.value = tab
    }
  },
  { immediate: true }
)

watch(selectedPrompt, async (value) => {
  if (!value) {
    promptContent.value = ''
    return
  }
  localStorage.setItem('lastSelectedPrompt', value)
  isPromptLoading.value = true
  promptError.value = null
  try {
    const data = await getPromptContent(value)
    promptContent.value = data.content
  } catch (e) {
    promptError.value = (e as Error).message || t('settings.prompts.promptContentFailed')
  } finally {
    isPromptLoading.value = false
  }
})
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold text-gray-800 mb-6">{{ t('settings.title') }}</h1>
    
    <div v-if="error" class="app-alert-error mb-4" role="alert">
      {{ error.message }}
    </div>

    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="mb-4 flex w-full flex-nowrap justify-start gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1">
        <TabsTrigger class="shrink-0" value="ai">{{ t('settings.tabs.ai') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="rotation">{{ t('settings.tabs.rotation') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="notifications">{{ t('settings.tabs.notifications') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="status">{{ t('settings.tabs.status') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="prompts">{{ t('settings.tabs.prompts') }}</TabsTrigger>
        <TabsTrigger class="shrink-0" value="cloud">{{ t('settings.tabs.cloud') }}</TabsTrigger>
      </TabsList>

      <!-- AI Tab -->
      <TabsContent value="ai">
        <Card>
          <CardHeader>
            <CardTitle>{{ t('settings.ai.title') }}</CardTitle>
            <CardDescription>{{ t('settings.ai.description') }}</CardDescription>
          </CardHeader>
          <CardContent v-if="isReady" class="space-y-4">
            <!-- 快速入门 -->
            <div v-if="showAiGuide" class="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm space-y-1">
              <div class="flex items-center justify-between">
                <span class="font-medium text-blue-800">{{ t('settings.ai.guide.title') }}</span>
                <button class="text-xs text-gray-500 hover:text-gray-700" @click="showAiGuide = false">✕</button>
              </div>
              <ol class="list-decimal list-inside text-blue-900/80 space-y-0.5">
                <li>{{ t('settings.ai.guide.step1') }}</li>
                <li>{{ t('settings.ai.guide.step2') }}</li>
                <li>{{ t('settings.ai.guide.step3') }}</li>
                <li>{{ t('settings.ai.guide.step4') }}</li>
              </ol>
            </div>

            <!-- 供应商 -->
            <div class="grid gap-2">
              <Label>{{ t('settings.ai.provider') }}</Label>
              <Select :model-value="selectedProviderId" @update:model-value="(v) => onProviderChange(v as string)">
                <SelectTrigger><SelectValue :placeholder="t('settings.ai.providerPlaceholder')" /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in aiProviders" :key="p.id" :value="p.id">
                    {{ p.display_name }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <p v-if="selectedProvider?.note" class="text-xs text-gray-500">{{ selectedProvider.note }}</p>
            </div>

            <!-- API Key -->
            <div class="grid gap-2">
              <div class="flex items-center justify-between">
                <Label>API Key</Label>
                <a
                  v-if="selectedProvider?.key_url"
                  :href="selectedProvider.key_url"
                  target="_blank"
                  class="text-xs text-blue-600 underline"
                >{{ t('settings.ai.getApiKey') }} →</a>
              </div>
              <Input
                v-model="aiSettings.OPENAI_API_KEY"
                type="password"
                :placeholder="t('settings.ai.keyPlaceholder')"
              />
              <p class="text-xs text-gray-500">
                {{ systemStatus?.env_file.openai_api_key_set ? t('settings.ai.keyConfigured') : t('settings.ai.keyMissing') }}
              </p>
            </div>

            <!-- 模型：内置供应商下拉（免费角标/Vision），自定义手填 -->
            <div v-if="selectedProvider?.models.length" class="grid gap-2">
              <Label>{{ t('settings.ai.modelName') }}</Label>
              <Select v-model="aiSettings.OPENAI_MODEL_NAME">
                <SelectTrigger><SelectValue :placeholder="t('settings.ai.modelPlaceholder')" /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="m in selectedProvider.models" :key="m.name" :value="m.name">
                    <span class="inline-flex items-center gap-1.5">
                      <span
                        v-if="m.badge === 'free'"
                        class="text-[10px] font-bold bg-green-100 text-green-700 px-1 py-px rounded"
                      >FREE</span>
                      <span
                        v-else-if="m.badge === 'free_quota'"
                        class="text-[10px] font-bold bg-amber-100 text-amber-700 px-1 py-px rounded"
                      >{{ t('settings.ai.freeQuota') }}</span>
                      <span>{{ m.name }}</span>
                      <span v-if="m.vision" :title="t('settings.ai.visionCapable')">👁</span>
                      <span v-if="m.note" class="text-xs text-gray-400">{{ m.note }}</span>
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p v-if="selectedModelPreset && !selectedModelPreset.vision" class="text-xs text-amber-600">
                {{ t('settings.ai.noVisionWarning') }}
              </p>
            </div>
            <div v-else class="grid gap-2">
              <Label>{{ t('settings.ai.modelName') }}</Label>
              <Input v-model="aiSettings.OPENAI_MODEL_NAME" placeholder="e.g. gpt-4o / qwen-vl-plus" />
            </div>

            <!-- 长文本模型（可选） -->
            <div class="grid gap-2">
              <Label>{{ t('settings.ai.textModel') }}</Label>
              <Select
                :model-value="aiSettings.OPENAI_TEXT_MODEL_NAME || '__none__'"
                @update:model-value="(v) => (aiSettings.OPENAI_TEXT_MODEL_NAME = v === '__none__' ? '' : (v as string))"
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{{ t('settings.ai.textModelNone') }}</SelectItem>
                  <SelectItem v-for="m in selectedProvider?.models || []" :key="m.name" :value="m.name">
                    {{ m.name }}<span v-if="!m.vision" class="text-xs text-gray-400">（text）</span>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p class="text-xs text-gray-500">{{ t('settings.ai.textModelHint') }}</p>
            </div>

            <!-- Base URL（内置自动填充；自定义必填） -->
            <div class="grid gap-2">
              <Label>API Base URL</Label>
              <Input v-model="aiSettings.OPENAI_BASE_URL" placeholder="https://api.openai.com/v1" />
            </div>

            <div class="grid gap-2">
              <Label>{{ t('settings.ai.proxy') }}</Label>
              <Input v-model="aiSettings.PROXY_URL" placeholder="http://127.0.0.1:7890" />
            </div>
          </CardContent>
          <CardContent v-else class="py-8 text-sm text-gray-500">
            {{ t('settings.ai.loading') }}
          </CardContent>
          <CardFooter v-if="isReady" class="flex gap-2">
            <Button variant="outline" @click="handleTestAi" :disabled="isSaving">{{ t('settings.ai.testConnection') }}</Button>
            <Button @click="handleSaveAi" :disabled="isSaving">{{ t('settings.ai.save') }}</Button>
          </CardFooter>
        </Card>
      </TabsContent>

      <!-- Rotation Tab -->
      <TabsContent value="rotation">
        <RotationSettingsPanel
          :settings="rotationSettings"
          :is-ready="isReady"
          :is-saving="isSaving"
          @save="handleSaveRotation"
        />
      </TabsContent>

      <!-- Notifications Tab -->
      <TabsContent value="notifications">
        <NotificationSettingsPanel
          :settings="notificationSettings"
          :is-ready="isReady"
          :is-saving="isSaving"
          :save-settings="handleSaveNotifications"
          :test-settings="handleTestNotification"
        />
      </TabsContent>

      <!-- Status Tab -->
      <TabsContent value="status">
        <!-- 账号与安全 -->
        <Card class="mb-6">
          <CardHeader>
            <CardTitle>{{ t('settings.security.title') }}</CardTitle>
            <CardDescription>{{ t('settings.security.description') }}</CardDescription>
          </CardHeader>
          <CardContent class="grid gap-3 md:grid-cols-2">
            <div class="grid gap-1.5">
              <Label>{{ t('settings.security.oldUsername') }}</Label>
              <Input v-model="securityForm.old_username" :placeholder="t('settings.security.oldPlaceholder')" />
            </div>
            <div class="grid gap-1.5">
              <Label>{{ t('settings.security.oldPassword') }}</Label>
              <Input v-model="securityForm.old_password" type="password" :placeholder="t('settings.security.oldPlaceholder')" />
            </div>
            <div class="grid gap-1.5">
              <Label>{{ t('settings.security.newUsername') }}</Label>
              <Input v-model="securityForm.new_username" placeholder="admin" />
            </div>
            <div class="grid gap-1.5">
              <Label>{{ t('settings.security.newPassword') }}</Label>
              <Input v-model="securityForm.new_password" type="password" :placeholder="t('settings.security.newPasswordHint')" />
            </div>
          </CardContent>
          <CardFooter>
            <Button @click="handleChangePassword" :disabled="isSecurityBusy || !securityForm.old_username || !securityForm.old_password || !securityForm.new_username || !securityForm.new_password">
              {{ t('settings.security.submit') }}
            </Button>
            <p class="text-xs text-gray-500 ml-3">{{ t('settings.security.note') }}</p>
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{{ t('settings.status.title') }}</CardTitle>
            <div class="flex justify-end">
                <Button variant="outline" size="sm" @click="refreshStatus" :disabled="isLoading">{{ t('settings.status.refresh') }}</Button>
            </div>
          </CardHeader>
          <CardContent>
            <div v-if="systemStatus" class="space-y-6">
              <!-- Scraper Process Status -->
              <div class="flex items-center justify-between border-b pb-4">
                <div>
                  <h3 class="font-medium">{{ t('settings.status.scraper') }}</h3>
                  <p class="text-sm text-gray-500">{{ t('settings.status.scraperDescription') }}</p>
                </div>
                <span :class="systemStatus.scraper_running ? 'text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full' : 'text-gray-500 bg-gray-100 px-3 py-1 rounded-full'">
                  {{ systemStatus.scraper_running ? t('common.running') : t('common.idle') }}
                </span>
              </div>

              <!-- Env Config Status -->
              <div>
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h3 class="font-medium">{{ t('settings.status.env') }}</h3>
                        <p class="text-sm text-gray-500">{{ t('settings.status.envDescription') }}</p>
                    </div>
                    <span :class="systemStatus.env_file.exists ? 'text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full' : 'text-red-600 font-bold bg-red-50 px-3 py-1 rounded-full'">
                        {{ systemStatus.env_file.exists ? t('settings.status.loaded') : t('settings.status.missing') }}
                    </span>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="p-3 border rounded-lg" :class="systemStatus.env_file.openai_api_key_set ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'">
                        <div class="flex justify-between items-center">
                            <span class="font-medium text-sm">OpenAI API Key</span>
                            <span class="text-xs font-bold" :class="systemStatus.env_file.openai_api_key_set ? 'text-green-700' : 'text-yellow-700'">
                                {{ systemStatus.env_file.openai_api_key_set ? t('common.active') : t('common.inactive') }}
                            </span>
                        </div>
                    </div>
                    
                    <div class="p-3 border rounded-lg" :class="systemStatus.configured_notification_channels?.length ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'">
                         <div class="flex justify-between items-center">
                            <span class="font-medium text-sm">{{ t('settings.status.channels') }}</span>
                             <span class="text-xs font-bold" :class="systemStatus.configured_notification_channels?.length ? 'text-green-700' : 'text-gray-500'">
                                {{ systemStatus.configured_notification_channels?.length ? t('common.active') : t('common.inactive') }}
                            </span>
                        </div>
                         <div class="text-xs text-gray-500 mt-1">
                            {{ systemStatus.configured_notification_channels?.join(', ') || t('settings.status.none') }}
                        </div>
                    </div>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-8 text-gray-500">
                {{ t('settings.status.fetching') }}
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- Cloud Tab：授权与行情回馈 -->
      <TabsContent value="cloud">
        <div class="space-y-6">
          <!-- License -->
          <Card>
            <CardHeader>
              <CardTitle>{{ t('settings.cloud.licenseTitle') }}</CardTitle>
              <CardDescription>{{ t('settings.cloud.licenseDescription') }}</CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
              <div v-if="cloudStatus?.license?.ok" class="flex items-center justify-between border-b pb-4">
                <div>
                  <h3 class="font-medium">{{ cloudStatus.license.plan }}</h3>
                  <p class="text-sm text-gray-500">
                    {{ cloudStatus.license.key }}
                    <span v-if="cloudStatus.license.expires_at"> · {{ t('settings.cloud.expiresAt') }}: {{ cloudStatus.license.expires_at.slice(0, 10) }}</span>
                  </p>
                </div>
                <span class="text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full">{{ t('common.active') }}</span>
              </div>
              <div v-else-if="cloudStatus" class="bg-yellow-50 border border-yellow-200 text-yellow-800 px-3 py-2 rounded text-sm">
                {{ t('settings.cloud.noLicense') }}
              </div>
              <div class="flex gap-2">
                <Input v-model="licenseKeyInput" :placeholder="t('settings.cloud.keyPlaceholder')" class="flex-1" />
                <Button @click="handleActivateLicense" :disabled="isCloudBusy || !licenseKeyInput.trim()">{{ t('settings.cloud.activate') }}</Button>
                <Button variant="outline" @click="handleVerifyLicense" :disabled="isCloudBusy">{{ t('settings.cloud.verify') }}</Button>
              </div>
            </CardContent>
          </Card>

          <!-- Telemetry -->
          <Card>
            <CardHeader>
              <CardTitle>{{ t('settings.cloud.telemetryTitle') }}</CardTitle>
              <CardDescription>{{ t('settings.cloud.telemetryDescription') }}</CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium">{{ t('settings.cloud.telemetryToggle') }}</h3>
                  <p class="text-xs text-gray-500">{{ t('settings.cloud.telemetryPrivacy') }}</p>
                </div>
                <Switch :model-value="cloudStatus?.telemetry.enabled ?? false" @update:model-value="handleToggleTelemetry" />
              </div>
              <div v-if="cloudStatus?.telemetry.state?.uploaded_total" class="text-sm text-gray-500">
                {{ t('settings.cloud.telemetryStats', {
                  total: cloudStatus.telemetry.state.uploaded_total,
                  time: (cloudStatus.telemetry.state.last_uploaded_at || '').slice(0, 19).replace('T', ' ')
                }) }}
              </div>
              <Button variant="outline" size="sm" @click="handleFlushTelemetry" :disabled="isCloudBusy || !cloudStatus?.telemetry.enabled">
                {{ t('settings.cloud.telemetryFlush') }}
              </Button>
            </CardContent>
          </Card>

          <!-- Update -->
          <Card>
            <CardHeader>
              <CardTitle>{{ t('settings.cloud.updateTitle') }}</CardTitle>
              <CardDescription>{{ t('settings.cloud.updateDescription') }}</CardDescription>
            </CardHeader>
            <CardContent class="space-y-3">
              <div class="flex items-center gap-3">
                <Button variant="outline" @click="handleCheckUpdate" :disabled="isCloudBusy">{{ t('settings.cloud.checkUpdate') }}</Button>
                <span class="text-sm text-gray-500">{{ t('settings.cloud.currentVersion') }}: {{ cloudStatus?.app_version || '-' }}</span>
              </div>
              <div v-if="updateResult" class="text-sm">
                <template v-if="updateResult.latest">
                  <span v-if="updateResult.latest.version === updateResult.current_version" class="text-green-600">{{ t('settings.cloud.upToDate') }}</span>
                  <span v-else class="text-blue-600">
                    {{ t('settings.cloud.newVersion', { version: updateResult.latest.version }) }}
                    <a v-if="updateResult.latest.url" :href="updateResult.latest.url" target="_blank" class="underline ml-1">{{ t('settings.cloud.download') }}</a>
                  </span>
                </template>
                <span v-else class="text-yellow-600">{{ t('settings.cloud.updateCheckFailed') }}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>

      <!-- Prompt Tab -->
      <TabsContent value="prompts">
        <Card>
          <CardHeader>
            <CardTitle>{{ t('settings.prompts.title') }}</CardTitle>
            <CardDescription>{{ t('settings.prompts.description') }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div v-if="promptError" class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded">
              {{ promptError }}
            </div>

            <div class="grid gap-2">
              <Label>{{ t('settings.prompts.selectFile') }}</Label>
              <Select
                :model-value="selectedPrompt || undefined"
                @update:model-value="(value) => selectedPrompt = value as string"
              >
                <SelectTrigger>
                  <SelectValue :placeholder="t('settings.prompts.placeholder')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="file in promptFiles" :key="file" :value="file">
                    {{ file }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <p v-if="!promptFiles.length && !isPromptLoading" class="text-sm text-gray-500">
                {{ t('settings.prompts.none') }}
              </p>
            </div>

            <div class="grid gap-2">
              <Label>{{ t('settings.prompts.content') }}</Label>
              <Textarea
                v-model="promptContent"
                class="min-h-[240px]"
                :disabled="!selectedPrompt || isPromptLoading"
                :placeholder="t('settings.prompts.contentPlaceholder')"
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button :disabled="isPromptSaving || !selectedPrompt" @click="handleSavePrompt">
              {{ isPromptSaving ? t('common.saving') : t('settings.prompts.save') }}
            </Button>
          </CardFooter>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
