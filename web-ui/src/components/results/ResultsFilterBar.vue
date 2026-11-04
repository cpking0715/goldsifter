<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Sparkles, TrendingUp, Tags, Star, EyeOff, LayoutGrid, Search } from 'lucide-vue-next'
import type { ResultCategory } from '@/api/results'
import type { ResultCategoryCounts } from '@/types/result.d.ts'
import type { FoundWithin } from '@/composables/useResults'

interface FileOption {
  value: string
  label: string
  taskName?: string
}

type SortBy = 'crawl_time' | 'publish_time' | 'price' | 'keyword_hit_count' | 'value_score'

interface Props {
  files: string[]
  fileOptions?: FileOption[]
  selectedFile: string | null
  category: ResultCategory
  search: string
  minPrice: string
  maxPrice: string
  foundWithin: FoundWithin
  counts: ResultCategoryCounts | null
  sortBy: SortBy
  sortOrder: 'asc' | 'desc'
  isLoading: boolean
  isReady: boolean
}

const props = defineProps<Props>()
const { t } = useI18n()

const options = computed(() => {
  if (!props.isReady) {
    return []
  }
  if (props.fileOptions && props.fileOptions.length > 0) {
    return props.fileOptions
  }
  return props.files.map((file) => ({ value: file, label: file }))
})

const selectedLabel = computed(() => {
  if (!props.isReady) return t('results.filters.loadingTaskNames')
  if (options.value.length === 0) return t('results.filters.noResults')
  if (!props.selectedFile) return t('results.filters.chooseResult')
  const match = options.value.find((option) => option.value === props.selectedFile)
  return match ? match.label : t('results.filters.taskNameLabel', { task: t('common.unnamed') })
})

const labelClass = computed(() => {
  const classes = ['transition-opacity', 'duration-200']
  if (!props.isReady || !props.selectedFile || options.value.length === 0) {
    classes.push('text-muted-foreground')
  }
  classes.push(props.isReady ? 'opacity-100' : 'opacity-70')
  return classes.join(' ')
})

const isSelectDisabled = computed(() => !props.isReady || options.value.length === 0)

const categoryTabs = computed(() => {
  const counts = props.counts
  return [
    { value: 'all' as ResultCategory, label: t('results.categories.all'), icon: LayoutGrid, count: counts?.all ?? null },
    { value: 'ai_recommended' as ResultCategory, label: t('results.categories.aiRecommended'), icon: Sparkles, count: counts?.ai_recommended ?? null },
    { value: 'high_value' as ResultCategory, label: t('results.categories.highValue'), icon: TrendingUp, count: counts?.high_value ?? null },
    { value: 'keyword_hit' as ResultCategory, label: t('results.categories.keywordHit'), icon: Tags, count: counts?.keyword_hit ?? null },
    { value: 'favorite' as ResultCategory, label: t('results.categories.favorite'), icon: Star, count: counts?.favorite ?? null },
    { value: 'hidden' as ResultCategory, label: t('results.categories.hidden'), icon: EyeOff, count: counts?.hidden ?? null },
  ]
})

const emit = defineEmits<{
  (e: 'update:selectedFile', value: string): void
  (e: 'update:category', value: ResultCategory): void
  (e: 'update:search', value: string): void
  (e: 'update:minPrice', value: string): void
  (e: 'update:maxPrice', value: string): void
  (e: 'update:foundWithin', value: FoundWithin): void
  (e: 'update:sortBy', value: SortBy): void
  (e: 'update:sortOrder', value: 'asc' | 'desc'): void
  (e: 'refresh'): void
  (e: 'export'): void
  (e: 'delete'): void
  (e: 'manage-blacklist'): void
}>()
</script>

<template>
  <div class="app-surface mb-6 p-4 sm:p-5">
    <div class="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div class="space-y-2">
        <Label class="text-xs font-semibold text-slate-500">{{ t('results.title') }}</Label>
        <Select
          :model-value="props.selectedFile || undefined"
          @update:model-value="(value) => emit('update:selectedFile', value as string)"
        >
          <SelectTrigger class="w-full" :disabled="isSelectDisabled">
            <span :class="labelClass">
              {{ selectedLabel }}
            </span>
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="option in options" :key="option.value" :value="option.value">
              {{ option.label }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div class="space-y-2">
        <Label class="text-xs font-semibold text-slate-500">{{ t('results.filters.sortLabel') }}</Label>
        <Select
          :model-value="props.sortBy"
          @update:model-value="(value) => emit('update:sortBy', value as SortBy)"
        >
          <SelectTrigger class="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="crawl_time">{{ t('results.filters.sortByCrawlTime') }}</SelectItem>
            <SelectItem value="publish_time">{{ t('results.filters.sortByPublishTime') }}</SelectItem>
            <SelectItem value="price">{{ t('results.filters.sortByPrice') }}</SelectItem>
            <SelectItem value="keyword_hit_count">{{ t('results.filters.sortByKeywordHits') }}</SelectItem>
            <SelectItem value="value_score">{{ t('results.filters.sortByValueScore') }}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div class="space-y-2">
        <Label class="text-xs font-semibold text-slate-500">{{ t('results.filters.asc') }} / {{ t('results.filters.desc') }}</Label>
        <Select
          :model-value="props.sortOrder"
          @update:model-value="(value) => emit('update:sortOrder', value as 'asc' | 'desc')"
        >
          <SelectTrigger class="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="desc">{{ t('results.filters.desc') }}</SelectItem>
            <SelectItem value="asc">{{ t('results.filters.asc') }}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>

    <!-- 分类 Tab -->
    <div class="mt-4 flex flex-wrap items-center gap-2" role="tablist" :aria-label="t('results.categories.label')">
      <button
        v-for="tab in categoryTabs"
        :key="tab.value"
        type="button"
        role="tab"
        :aria-selected="props.category === tab.value"
        class="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors border"
        :class="props.category === tab.value
          ? 'bg-primary text-primary-foreground border-transparent shadow-sm'
          : 'bg-white/70 text-slate-600 border-slate-200 hover:bg-slate-100'"
        @click="emit('update:category', tab.value)"
      >
        <component :is="tab.icon" class="w-3.5 h-3.5" />
        {{ tab.label }}
        <span
          class="ml-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
          :class="props.category === tab.value ? 'bg-white/25 text-primary-foreground' : 'bg-slate-200/80 text-slate-500'"
        >
          {{ tab.count ?? '–' }}
        </span>
      </button>
    </div>

    <!-- 过滤行 -->
    <div class="mt-4 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
      <div class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div class="space-y-2 sm:w-56">
          <Label class="text-xs font-semibold text-slate-500" for="result-search">
            {{ t('results.filters.searchLabel') }}
          </Label>
          <div class="relative">
            <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <Input
              id="result-search"
              :model-value="props.search"
              class="pl-9"
              :placeholder="t('results.filters.searchPlaceholder')"
              @update:model-value="(value) => emit('update:search', String(value))"
            />
          </div>
        </div>

        <div class="space-y-2">
          <Label class="text-xs font-semibold text-slate-500" for="result-min-price">
            {{ t('results.filters.priceRange') }}
          </Label>
          <div class="flex items-center gap-1.5">
            <Input
              id="result-min-price"
              :model-value="props.minPrice"
              type="number"
              min="0"
              class="w-24"
              :placeholder="t('results.filters.priceMin')"
              @update:model-value="(value) => emit('update:minPrice', String(value))"
            />
            <span class="text-slate-400">–</span>
            <Input
              :model-value="props.maxPrice"
              type="number"
              min="0"
              class="w-24"
              :placeholder="t('results.filters.priceMax')"
              @update:model-value="(value) => emit('update:maxPrice', String(value))"
            />
          </div>
        </div>

        <div class="space-y-2 sm:w-40">
          <Label class="text-xs font-semibold text-slate-500" for="result-found-within">
            {{ t('results.filters.foundWithin') }}
          </Label>
          <Select
            :model-value="String(props.foundWithin)"
            @update:model-value="(value) => emit('update:foundWithin', (value === 'last_visit' ? 'last_visit' : Number(value)) as FoundWithin)"
          >
            <SelectTrigger id="result-found-within" class="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">{{ t('results.filters.foundAll') }}</SelectItem>
              <SelectItem value="1">{{ t('results.filters.found24h') }}</SelectItem>
              <SelectItem value="3">{{ t('results.filters.found3d') }}</SelectItem>
              <SelectItem value="7">{{ t('results.filters.found7d') }}</SelectItem>
              <SelectItem value="30">{{ t('results.filters.found30d') }}</SelectItem>
              <SelectItem value="last_visit">{{ t('results.filters.foundSinceLastVisit') }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
        <Button @click="emit('refresh')" :disabled="props.isLoading">
          {{ t('common.refresh') }}
        </Button>

        <Button
          variant="outline"
          @click="emit('manage-blacklist')"
          :disabled="props.isLoading || !props.selectedFile"
        >
          {{ t('results.filters.manageBlacklist') }}
        </Button>

        <Button
          variant="outline"
          @click="emit('export')"
          :disabled="props.isLoading || !props.selectedFile"
        >
          {{ t('results.filters.exportCsv') }}
        </Button>

        <Button
          variant="destructive"
          @click="emit('delete')"
          :disabled="props.isLoading || !props.selectedFile"
        >
          {{ t('results.filters.deleteResult') }}
        </Button>
      </div>
    </div>
  </div>
</template>
