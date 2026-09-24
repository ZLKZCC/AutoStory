import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

export default defineConfig({
  plugins: [vue(), vueJsx()],
  resolve: {
    dedupe: ['vue'],
  },
  test: {
    environment: 'happy-dom',   // 轻量 DOM，够测 store 与组件交互
    globals: true,              // describe/it/expect/vi 全局可用
    include: ['tests/**/*.test.ts'],
  },
})
