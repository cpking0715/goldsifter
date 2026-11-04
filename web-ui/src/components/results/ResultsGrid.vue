<script setup lang="ts">
import type { ResultItem } from '@/types/result.d.ts'
import { useI18n } from 'vue-i18n'
import { Loader2 } from 'lucide-vue-next'
import ResultCard from './ResultCard.vue'
import { Button } from '@/components/ui/button'

interface Props {
  results: ResultItem[]
  isLoading: boolean
  isLoadingMore?: boolean
  canLoadMore?: boolean
  totalItems?: number
  newSince?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  isLoadingMore: false,
  canLoadMore: false,
  totalItems: 0,
  newSince: null,
})
const { t } = useI18n()

const emit = defineEmits<{
  (e: 'toggle-block', item: ResultItem): void
  (e: 'toggle-favorite', item: ResultItem): void
  (e: 'load-more'): void
}>()
const skeletonItems = Array.from({ length: 8 }, (_, index) => index)
</script>

<template>
  <div :aria-busy="isLoading">
    <div
      v-if="isLoading"
      class="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      aria-live="polite"
    >
      <div
        v-for="item in skeletonItems"
        :key="item"
        class="app-surface overflow-hidden"
      >
        <div class="aspect-[4/3] animate-pulse bg-slate-200/70"></div>
        <div class="space-y-3 p-4">
          <div class="h-5 w-4/5 animate-pulse rounded bg-slate-200/70"></div>
          <div class="h-7 w-1/3 animate-pulse rounded bg-slate-200/70"></div>
          <div class="rounded-xl border border-slate-100 bg-slate-50/80 p-3">
            <div class="h-4 w-1/2 animate-pulse rounded bg-slate-200/70"></div>
            <div class="mt-3 h-2 w-full animate-pulse rounded bg-slate-200/70"></div>
            <div class="mt-3 h-4 w-full animate-pulse rounded bg-slate-200/70"></div>
            <div class="mt-2 h-4 w-3/4 animate-pulse rounded bg-slate-200/70"></div>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="results.length === 0" class="app-surface text-center py-12 text-gray-500">
      {{ t('results.grid.empty') }}
    </div>
    <div v-else>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        <ResultCard
          v-for="item in results"
          :key="item.商品信息.商品ID"
          :item="item"
          :new-since="props.newSince"
          @toggle-block="emit('toggle-block', $event)"
          @toggle-favorite="emit('toggle-favorite', $event)"
        />
      </div>
      <div v-if="canLoadMore || totalItems > results.length" class="mt-8 flex flex-col items-center gap-2">
        <Button variant="outline" :disabled="isLoadingMore" @click="emit('load-more')">
          <Loader2 v-if="isLoadingMore" class="w-4 h-4 mr-2 animate-spin" />
          {{ t('results.grid.loadMore') }}
        </Button>
        <span class="text-xs text-slate-400">
          {{ t('results.grid.shownOfTotal', { shown: results.length, total: totalItems }) }}
        </span>
      </div>
    </div>
  </div>
</template>
