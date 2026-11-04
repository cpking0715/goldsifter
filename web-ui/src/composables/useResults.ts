import { ref, reactive, watch, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { ResultCategoryCounts, ResultInsights, ResultItem } from '@/types/result.d.ts'
import * as resultsApi from '@/api/results'
import type { GetResultContentParams, ResultCategory } from '@/api/results'
import { useWebSocket } from '@/composables/useWebSocket'
import * as tasksApi from '@/api/tasks'
import { parseResultFilename, platformLabel } from '@/lib/platform'

/** 发现时间范围：0=全部，'last_visit'=自上次查看，其余为天数 */
export type FoundWithin = 0 | 1 | 3 | 7 | 30 | 'last_visit'

interface ResultsFilters {
  category: ResultCategory
  search: string
  minPrice: string
  maxPrice: string
  foundWithin: FoundWithin
  sort_by: 'crawl_time' | 'publish_time' | 'price' | 'keyword_hit_count' | 'value_score'
  sort_order: 'asc' | 'desc'
}

const FILTER_PERSIST_KEYS: (keyof ResultsFilters)[] = [
  'category',
  'search',
  'minPrice',
  'maxPrice',
  'foundWithin',
  'sort_by',
  'sort_order',
]

const FETCH_DEBOUNCE_MS = 300

function toLocalIso(date: Date): string {
  const pad = (value: number, length = 2) => String(value).padStart(length, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `.${pad(date.getMilliseconds(), 3)}`
  )
}

export function useResults() {
  const { t } = useI18n()
  const route = useRoute()
  // State
  const files = ref<string[]>([])
  const selectedFile = ref<string | null>(null)
  const results = ref<ResultItem[]>([])
  const insights = ref<ResultInsights | null>(null)
  const counts = ref<ResultCategoryCounts | null>(null)
  const totalItems = ref(0)
  const page = ref(1)
  const limit = ref(100)
  const blacklistKeywords = ref<string[]>([])
  const taskNameByKeyword = ref<Record<string, string>>({})
  const isFileOptionsReady = ref(false)
  const hasFetchedFiles = ref(false)
  const hasFetchedTasks = ref(false)
  const isSavingBlacklist = ref(false)
  const isLoadingMore = ref(false)
  // 「新商品」判定：watermark=上次查看到的最新爬取时间，prevVisit=当前角标基线
  const newSinceWatermark = ref<string | null>(null)
  const prevVisit = ref<string | null>(null)
  const readyDelayMs = 200
  let readyTimer: ReturnType<typeof setTimeout> | null = null
  let fetchDebounceTimer: ReturnType<typeof setTimeout> | null = null

  const STORAGE_KEY_FILTERS = 'resultFilters'

  function loadPersistedFilters(): ResultsFilters {
    const defaults: ResultsFilters = {
      category: 'all',
      search: '',
      minPrice: '',
      maxPrice: '',
      foundWithin: 0,
      sort_by: 'crawl_time',
      sort_order: 'desc',
    }
    try {
      const saved = localStorage.getItem(STORAGE_KEY_FILTERS)
      if (saved) {
        const parsed = JSON.parse(saved) as Partial<ResultsFilters>
        const sanitized: ResultsFilters = { ...defaults }
        const target = sanitized as unknown as Record<string, unknown>
        for (const key of FILTER_PERSIST_KEYS) {
          if (parsed[key] !== undefined) {
            target[key] = parsed[key]
          }
        }
        return sanitized
      }
    } catch { /* ignore */ }
    return defaults
  }

  const filters = reactive<ResultsFilters>(loadPersistedFilters())

  const isLoading = ref(false)
  const error = ref<Error | null>(null)
  const { on } = useWebSocket()

  function normalizeKeyword(value: string) {
    return value.trim().toLowerCase().replace(/\s+/g, '_')
  }

  function resultFileKey(filename: string) {
    const parsed = parseResultFilename(filename)
    return `${parsed.platform}:${normalizeKeyword(parsed.keyword)}`
  }

  function newSinceStorageKey(filename: string) {
    return `resultNewSince:${filename}`
  }

  function loadNewSinceState() {
    const file = selectedFile.value
    const stored = file ? localStorage.getItem(newSinceStorageKey(file)) : null
    newSinceWatermark.value = stored
    prevVisit.value = stored
  }

  /** 请求前把 UI 筛选翻译成 API 参数（不含分页）。 */
  function buildRequestParams(): GetResultContentParams {
    const params: GetResultContentParams = {
      category: filters.category,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    }
    const search = filters.search.trim()
    if (search) params.search = search
    if (filters.minPrice !== '') {
      const min = Number(filters.minPrice)
      if (!Number.isNaN(min)) params.min_price = min
    }
    if (filters.maxPrice !== '') {
      const max = Number(filters.maxPrice)
      if (!Number.isNaN(max)) params.max_price = max
    }
    if (filters.foundWithin === 'last_visit') {
      // prevVisit = 上一次看到新数据前的水位（首次访问为 null，筛选不生效）
      if (prevVisit.value) params.found_since = prevVisit.value
    } else if (filters.foundWithin > 0) {
      params.found_since = toLocalIso(new Date(Date.now() - filters.foundWithin * 86400000))
    }
    return params
  }

  /** 出现更新的记录时前移水位，并把角标基线定在旧水位。 */
  function advanceNewSince(items: ResultItem[]) {
    const file = selectedFile.value
    if (!file) return
    const newest = items
      .map((item) => item.爬取时间)
      .filter(Boolean)
      .sort()
      .pop()
    if (!newest) return
    const stored = localStorage.getItem(newSinceStorageKey(file))
    if (!stored) {
      // 首次访问：记录水位，不设角标基线（prevVisit 保持 null）
      localStorage.setItem(newSinceStorageKey(file), newest)
      newSinceWatermark.value = newest
    } else if (newest > stored) {
      prevVisit.value = stored
      localStorage.setItem(newSinceStorageKey(file), newest)
      newSinceWatermark.value = newest
    }
  }

  // Methods
  async function fetchFiles() {
    try {
      const fileList = await resultsApi.getResultFiles()
      files.value = fileList
      // If a file is selected that no longer exists, reset it.
      // Otherwise, if nothing is selected, select the first file by default.
      if (selectedFile.value && fileList.includes(selectedFile.value)) {
        return
      }

      const lastSelected = localStorage.getItem('lastSelectedResultFile')
      if (lastSelected && fileList.includes(lastSelected)) {
        selectedFile.value = lastSelected
        return
      }

      selectedFile.value = fileList[0] || null
    } catch (e) {
      if (e instanceof Error) error.value = e
    } finally {
      hasFetchedFiles.value = true
      scheduleFileOptionsReady()
    }
  }

  let fetchSeqCounter = 0

  async function fetchPage(targetPage: number, append: boolean) {
    const file = selectedFile.value
    if (!file) {
      results.value = []
      totalItems.value = 0
      counts.value = null
      return
    }

    // 请求序号 + 文件守卫：快切结果文件时丢弃过期的在途响应，
    // 避免旧响应覆盖新文件列表/counts，以及误推进另一文件的新品水位
    const seq = ++fetchSeqCounter
    if (append) isLoadingMore.value = true
    else isLoading.value = true
    error.value = null
    try {
      const data = await resultsApi.getResultContent(file, {
        ...buildRequestParams(),
        page: targetPage,
        limit: limit.value,
      })
      if (seq !== fetchSeqCounter || selectedFile.value !== file) return
      if (append) results.value.push(...data.items)
      else results.value = data.items
      totalItems.value = data.total_items
      if (data.counts) counts.value = data.counts
      page.value = targetPage
      advanceNewSince(data.items)
    } catch (e) {
      if (seq !== fetchSeqCounter || selectedFile.value !== file) return
      if (e instanceof Error) error.value = e
      if (!append) {
        results.value = []
        totalItems.value = 0
      }
    } finally {
      isLoading.value = false
      isLoadingMore.value = false
    }
  }

  function fetchResults() {
    return fetchPage(1, false)
  }

  const canLoadMore = computed(() => results.value.length < totalItems.value)

  async function loadMore() {
    if (!selectedFile.value || isLoading.value || isLoadingMore.value || !canLoadMore.value) return
    await fetchPage(page.value + 1, true)
  }

  async function fetchInsights() {
    if (!selectedFile.value) {
      insights.value = null
      return
    }

    try {
      insights.value = await resultsApi.getResultInsights(selectedFile.value)
    } catch (e) {
      if (e instanceof Error) error.value = e
      insights.value = null
    }
  }

  async function fetchBlacklistRules() {
    if (!selectedFile.value) {
      blacklistKeywords.value = []
      return
    }

    try {
      const data = await resultsApi.getResultBlacklistRules(selectedFile.value)
      blacklistKeywords.value = data.keywords || []
    } catch (e) {
      if (e instanceof Error) error.value = e
      blacklistKeywords.value = []
    }
  }

  async function fetchTaskNameMap() {
    try {
      const tasks = await tasksApi.getAllTasks()
      const mapping: Record<string, string> = {}
      tasks.forEach((task) => {
        if (task.keyword) {
          const platform = task.platform || 'xianyu'
          mapping[`${platform}:${normalizeKeyword(task.keyword)}`] = task.task_name
        }
      })
      taskNameByKeyword.value = mapping
    } catch (e) {
      if (e instanceof Error) error.value = e
    } finally {
      hasFetchedTasks.value = true
      scheduleFileOptionsReady()
    }
  }

  function scheduleFileOptionsReady() {
    if (isFileOptionsReady.value || !hasFetchedFiles.value || !hasFetchedTasks.value) return
    if (readyTimer) return
    readyTimer = setTimeout(() => {
      isFileOptionsReady.value = true
      readyTimer = null
    }, readyDelayMs)
  }

  // Real-time updates
  on('results_updated', async () => {
    const oldFile = selectedFile.value
    await fetchFiles()
    // If the selected file remains the same, refresh its content (in case of append)
    // If it changed (e.g. from null to new file), the watcher will handle it.
    if (selectedFile.value && selectedFile.value === oldFile) {
      fetchResults()
      fetchInsights()
    }
  })

  on('tasks_updated', () => {
    fetchTaskNameMap()
  })

  async function refreshResults() {
    const current = selectedFile.value
    await fetchFiles()
    if (selectedFile.value && selectedFile.value === current) {
      await fetchResults()
      await fetchInsights()
      await fetchBlacklistRules()
    }
  }

  async function exportSelectedResults() {
    if (!selectedFile.value) return
    try {
      await resultsApi.downloadResultExport(selectedFile.value, buildRequestParams())
    } catch (e) {
      if (e instanceof Error) error.value = e
    }
  }

  async function deleteSelectedFile(filename?: string) {
    const target = filename || selectedFile.value
    if (!target) return
    isLoading.value = true
    error.value = null
    try {
      await resultsApi.deleteResultFile(target)
      if (selectedFile.value === target) {
        const lastSelected = localStorage.getItem('lastSelectedResultFile')
        if (lastSelected === target) {
          localStorage.removeItem('lastSelectedResultFile')
        }
        localStorage.removeItem(newSinceStorageKey(target))
      }
      await fetchFiles()
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function toggleItemBlock(item: ResultItem) {
    if (!selectedFile.value) return
    const itemId = item.商品信息?.商品ID
    if (!itemId) return
    const newStatus = item._status === 'hidden' ? 'active' : 'hidden'
    try {
      await resultsApi.updateItemStatus(selectedFile.value, itemId, newStatus)
      await fetchResults()
    } catch (e) {
      if (e instanceof Error) error.value = e
    }
  }

  const favoritePending = new Set<string>()

  async function toggleItemFavorite(item: ResultItem) {
    const file = selectedFile.value
    const itemId = item.商品信息?.商品ID
    if (!file || !itemId) return
    // 同一商品的收藏操作全程序串行化（PATCH + counts 收尾），避免乱序覆盖
    if (favoritePending.has(itemId)) return
    favoritePending.add(itemId)
    try {
      const next = item._is_favorite !== true
      const previous = item._is_favorite === true
      item._is_favorite = next // 乐观更新，失败回滚
      try {
        await resultsApi.updateItemFavorite(file, itemId, next)
      } catch (e) {
        item._is_favorite = previous
        if (e instanceof Error) error.value = e
        return
      }
      // 收藏成功后的轻量收尾：计数刷新失败不回滚星标（服务端已生效）
      try {
        const newCounts = await resultsApi.getResultCounts(file)
        if (selectedFile.value === file) counts.value = newCounts
      } catch { /* counts 留旧值，下次刷新自然对齐 */ }
      // 在「收藏」分类下取消收藏：本地移除该卡片，保持视图与过滤语义一致
      if (!next && filters.category === 'favorite' && selectedFile.value === file) {
        results.value = results.value.filter(
          (candidate) => candidate.商品信息?.商品ID !== itemId
        )
        totalItems.value = Math.max(0, totalItems.value - 1)
      }
    } finally {
      favoritePending.delete(itemId)
    }
  }

  async function saveBlacklistRules(keywords: string[]) {
    if (!selectedFile.value) return
    isSavingBlacklist.value = true
    error.value = null
    try {
      const data = await resultsApi.updateResultBlacklistRules(selectedFile.value, keywords)
      blacklistKeywords.value = data.keywords || []
      await fetchResults()
      await fetchInsights()
    } catch (e) {
      if (e instanceof Error) error.value = e
      throw e
    } finally {
      isSavingBlacklist.value = false
    }
  }

  // Watchers
  watch(
    filters,
    (val) => {
      const persisted: Record<string, unknown> = {}
      for (const key of FILTER_PERSIST_KEYS) {
        persisted[key] = val[key]
      }
      localStorage.setItem(STORAGE_KEY_FILTERS, JSON.stringify(persisted))
    },
    { deep: true }
  )
  watch([selectedFile, filters], () => {
    // 输入防抖：搜索/价格等快速变化时不立刻打请求
    if (fetchDebounceTimer) clearTimeout(fetchDebounceTimer)
    fetchDebounceTimer = setTimeout(() => {
      fetchDebounceTimer = null
      fetchPage(1, false)
    }, FETCH_DEBOUNCE_MS)
  }, { deep: true })
  watch(selectedFile, () => {
    loadNewSinceState()
    fetchInsights()
    fetchBlacklistRules()
  })
  watch(selectedFile, (value) => {
    if (value) localStorage.setItem('lastSelectedResultFile', value)
  })
  watch(
    [() => route.query.file, files],
    ([routeFile, currentFiles]) => {
      if (typeof routeFile !== 'string') return
      if (currentFiles.includes(routeFile)) {
        selectedFile.value = routeFile
      }
    },
    { immediate: true }
  )

  const fileOptions = computed(() =>
    files.value.map((file) => {
      const parsed = parseResultFilename(file)
      const taskName = taskNameByKeyword.value[resultFileKey(file)]
      const task = taskName || t('common.unnamed')
      return {
        value: file,
        taskName: task,
        label: t('results.filters.fileLabel', {
          platform: platformLabel(parsed.platform),
          task,
        }),
      }
    })
  )

  // Lifecycle
  onMounted(() => {
    fetchFiles()
    fetchTaskNameMap()
    loadNewSinceState()
  })

  return {
    files,
    selectedFile,
    results,
    insights,
    counts,
    totalItems,
    page,
    filters,
    isLoading,
    isLoadingMore,
    canLoadMore,
    error,
    newSince: computed(() => prevVisit.value),
    fetchFiles, // Expose to allow manual refresh
    fetchResults,
    loadMore,
    refreshResults,
    exportSelectedResults,
    deleteSelectedFile,
    toggleItemBlock,
    toggleItemFavorite,
    blacklistKeywords,
    isSavingBlacklist,
    saveBlacklistRules,
    fileOptions,
    isFileOptionsReady,
  }
}
