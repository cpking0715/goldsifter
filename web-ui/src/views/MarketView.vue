<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { http } from '@/lib/http'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import PriceTrendChart from '@/components/results/PriceTrendChart.vue'
import { platformLabel } from '@/lib/platform'

const { t } = useI18n()

interface MarketKeyword {
  platform: string
  keyword: string
  samples: number
  latest_at: string | null
  avg_price: number | null
  min_price: number | null
  max_price: number | null
}

interface DailyPoint {
  day: string
  sample_count: number
  avg_price: number
  min_price: number
  max_price: number
}

interface MarketSummary {
  platform: string | null
  keyword: string
  latest: { sample_count: number; avg_price: number | null; median_price: number | null; min_price: number | null; max_price: number | null }
  daily_trend: DailyPoint[]
  total_samples: number
  latest_snapshot_at: string | null
}

const keywords = ref<MarketKeyword[]>([])
const selected = ref<MarketKeyword | null>(null)
const summary = ref<MarketSummary | null>(null)
const filter = ref('')
const isLoading = ref(false)
const error = ref<string | null>(null)
const isProDenied = ref(false)

async function loadKeywords() {
  isLoading.value = true
  error.value = null
  try {
    keywords.value = await http('/api/market/keywords?limit=100')
    isProDenied.value = false
  } catch (e) {
    const msg = (e as Error).message || ''
    isProDenied.value = msg.includes('Pro')
    error.value = msg
  } finally {
    isLoading.value = false
  }
}

async function selectKeyword(item: MarketKeyword) {
  selected.value = item
  summary.value = null
  try {
    const params = new URLSearchParams({ keyword: item.keyword })
    if (item.platform) params.set('platform', item.platform)
    summary.value = await http(`/api/market/summary?${params.toString()}`)
  } catch (e) {
    error.value = (e as Error).message
  }
}

const filtered = computed(() => {
  const text = filter.value.trim().toLowerCase()
  if (!text) return keywords.value
  return keywords.value.filter(
    (k) => k.keyword.toLowerCase().includes(text) || k.platform.includes(text),
  )
})

const chartData = computed(() => {
  const trend = summary.value?.daily_trend || []
  return trend.map((d) => ({
    day: d.day,
    avg_price: d.avg_price,
    median_price: null as number | null,
  }))
})

onMounted(loadKeywords)
</script>

<template>
  <div class="space-y-6 animate-fade-in">
    <div>
      <h1 class="text-2xl font-black text-slate-800 tracking-tight">{{ t('market.title') }}</h1>
      <p class="text-slate-500 mt-1 text-sm">{{ t('market.description') }}</p>
    </div>

    <!-- Pro 门禁提示 -->
    <Card v-if="isProDenied">
      <CardContent class="py-10 text-center space-y-2">
        <p class="text-amber-600 font-medium">{{ t('market.proRequired') }}</p>
        <p class="text-sm text-gray-500">{{ t('market.proHint') }}</p>
        <router-link to="/settings">
          <Button variant="outline">{{ t('market.goActivate') }}</Button>
        </router-link>
      </CardContent>
    </Card>

    <div v-else class="grid gap-6 lg:grid-cols-[1fr_2fr]">
      <!-- 关键词列表 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">{{ t('market.keywords') }}</CardTitle>
          <Input v-model="filter" :placeholder="t('market.filterPlaceholder')" class="mt-2" />
        </CardHeader>
        <CardContent class="max-h-[560px] overflow-y-auto space-y-1">
          <p v-if="isLoading" class="text-sm text-gray-400 py-4 text-center">{{ t('common.loading') }}</p>
          <p v-else-if="!filtered.length" class="text-sm text-gray-400 py-4 text-center">{{ t('market.empty') }}</p>
          <button
            v-for="item in filtered"
            :key="`${item.platform}:${item.keyword}`"
            class="w-full text-left p-2.5 rounded-lg border transition-colors"
            :class="selected === item ? 'border-primary bg-primary/5' : 'border-transparent hover:bg-gray-50'"
            @click="selectKeyword(item)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium truncate">{{ item.keyword }}</span>
              <Badge variant="outline" class="shrink-0 text-[10px]">{{ platformLabel(item.platform) }}</Badge>
            </div>
            <div class="text-xs text-gray-500 mt-0.5">
              {{ t('market.samples', { n: item.samples }) }}
              <span v-if="item.avg_price"> · {{ t('market.avg') }} ¥{{ item.avg_price }}</span>
              <span v-if="item.min_price"> · {{ t('market.range', { lo: item.min_price, hi: item.max_price }) }}</span>
            </div>
          </button>
        </CardContent>
      </Card>

      <!-- 详情 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">
            <template v-if="selected">
              {{ selected.keyword }}
              <Badge variant="outline" class="ml-2 text-[10px]">{{ platformLabel(selected.platform) }}</Badge>
            </template>
            <template v-else>{{ t('market.detailTitle') }}</template>
          </CardTitle>
          <CardDescription v-if="summary">
            {{ t('market.totalSamples', { n: summary.total_samples }) }}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div v-if="!selected" class="py-16 text-center text-sm text-gray-400">{{ t('market.selectHint') }}</div>
          <div v-else-if="!summary" class="py-16 text-center text-sm text-gray-400">{{ t('common.loading') }}</div>
          <div v-else class="space-y-5">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div class="p-3 rounded-lg bg-gray-50 text-center">
                <div class="text-xs text-gray-500">{{ t('market.latestAvg') }}</div>
                <div class="text-lg font-bold text-slate-800">¥{{ summary.latest.avg_price ?? '-' }}</div>
              </div>
              <div class="p-3 rounded-lg bg-gray-50 text-center">
                <div class="text-xs text-gray-500">{{ t('market.latestMedian') }}</div>
                <div class="text-lg font-bold text-slate-800">¥{{ summary.latest.median_price ?? '-' }}</div>
              </div>
              <div class="p-3 rounded-lg bg-gray-50 text-center">
                <div class="text-xs text-gray-500">{{ t('market.latestLow') }}</div>
                <div class="text-lg font-bold text-green-700">¥{{ summary.latest.min_price ?? '-' }}</div>
              </div>
              <div class="p-3 rounded-lg bg-gray-50 text-center">
                <div class="text-xs text-gray-500">{{ t('market.latestHigh') }}</div>
                <div class="text-lg font-bold text-red-700">¥{{ summary.latest.max_price ?? '-' }}</div>
              </div>
            </div>

            <div v-if="summary.daily_trend.length">
              <div class="text-sm font-medium text-slate-700 mb-2">{{ t('market.trend30d') }}</div>
              <PriceTrendChart :points="chartData" />
            </div>
            <p v-else class="text-sm text-gray-400 text-center py-6">{{ t('market.noTrend') }}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
