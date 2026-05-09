import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { MetaResponse, RangeKey } from '@/types/api'

interface State {
  data: MetaResponse | null
  loading: boolean
  error: string
  range: RangeKey
}

export const useMetaStore = defineStore('meta', {
  state: (): State => ({
    data: null,
    loading: false,
    error: '',
    range: 'all_available',
  }),
  actions: {
    async load() {
      if (this.data || this.loading) return
      this.loading = true
      try {
        this.data = await api.meta()
        this.error = ''
      } catch (e) {
        this.error = (e as Error).message
      } finally {
        this.loading = false
      }
    },
    setRange(r: RangeKey) {
      this.range = r
    },
  },
})
