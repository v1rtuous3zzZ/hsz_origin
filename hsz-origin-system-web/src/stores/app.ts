import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({ title: '沪苏浙 G50 高速路段溯源系统' }),
})
