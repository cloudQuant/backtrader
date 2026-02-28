# Backtrader Web 前端优化方案 (Vue3 + ECharts)

本文档详细描述基于 Vue3 和 ECharts 的前端实现优化方案。

- --

## 目录

1. [技术栈升级](#技术栈升级)
2. [前端架构优化](#前端架构优化)
3. [ECharts 图表组件库](#echarts-图表组件库)
4. [状态管理优化](#状态管理优化)
5. [性能优化方案](#性能优化方案)
6. [组件设计规范](#组件设计规范)
7. [实时数据处理](#实时数据处理)
8. [UI/UX 优化](#uiux-优化)

- --

## 技术栈升级

### 核心依赖更新

```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.5",
    "pinia": "^2.1.7",
    "pinia-plugin-persistedstate": "^3.2.1",
    "element-plus": "^2.4.4",
    "@element-plus/icons-vue": "^2.3.1",
    "echarts": "^5.4.3",
    "vue-echarts": "^6.6.5",
    "axios": "^1.6.2",
    "dayjs": "^1.11.10",
    "@vueuse/core": "^10.7.0",
    "lodash-es": "^4.17.21",
    "sortablejs": "^1.15.2",
    "vuedraggable": "^4.1.0",
    "monaco-editor": "^0.45.0",
    "@codemirror/lang-python": "^6.0.0",
    "nprogress": "^0.2.0",
    "screenfull": "^6.0.2",
    "hotkeys-js": "^3.12.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "sass": "^1.69.5",
    "unplugin-auto-import": "^0.17.2",
    "unplugin-vue-components": "^0.26.0",
    "@types/lodash-es": "^4.17.12",
    "@types/sortablejs": "^1.15.7",
    "@types/nprogress": "^0.2.3",
    "vite-plugin-compression": "^0.5.1",
    "vite-plugin-imagemin": "^0.6.1",
    "rollup-plugin-visualizer": "^5.11.0"
  }
}

```bash

### Vite 配置优化

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { visualizer } from 'rollup-plugin-visualizer'
import viteCompression from 'vite-plugin-compression'

export default defineConfig({
  plugins: [
    vue(),
    // 自动导入 Vue API
    AutoImport({
      imports: [
        'vue',
        'vue-router',
        'pinia',
        '@vueuse/core'
      ],
      dts: 'src/auto-imports.d.ts',
      eslintrc: { enabled: true }
    }),
    // 自动导入组件
    Components({
      resolvers: [
        ElementPlusResolver(),
        // 自动导入 ECharts 组件
        (componentName) => {
          if (componentName.startsWith('EChart')) {
            return { name: componentName, from: 'vue-echarts' }
          }
        }
      ],
      dts: 'src/components.d.ts'
    }),
    // Gzip 压缩
    viteCompression({
      verbose: true,
      disable: false,
      threshold: 10240,
      algorithm: 'gzip',
      ext: '.gz'
    }),
    // 打包分析
    visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: '<http://localhost:8000',>
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  },
  build: {
    target: 'es2015',
    outDir: 'dist',
    assetsDir: 'assets',
    assetsInlineLimit: 4096,
    cssCodeSplit: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          'echarts': ['echarts', 'vue-echarts'],
          'editor': ['monaco-editor']
        },
        chunkFileNames: 'js/[name]-[hash].js',
        entryFileNames: 'js/[name]-[hash].js',
        assetFileNames: '[ext]/[name]-[hash].[ext]'
      }
    }
  }
})

```bash

- --

## 前端架构优化

### 目录结构优化

```bash
frontend/src/
├── api/                        # API 服务层

│   ├── index.ts               # API 入口

│   ├── request.ts             # Axios 封装

│   ├── types.ts               # API 类型定义

│   ├── modules/               # API 模块

│   │   ├── auth.ts
│   │   ├── strategy.ts
│   │   ├── backtest.ts
│   │   ├── live.ts
│   │   └── data.ts
│
├── assets/                     # 静态资源

│   ├── styles/                # 样式文件

│   │   ├── variables.scss     # SCSS 变量

│   │   ├── mixins.scss        # SCSS mixins

│   │   ├── element.scss       # Element Plus 覆盖样式

│   │   ├── transition.scss    # 过渡动画

│   │   └── index.scss         # 主样式

│   ├── images/                # 图片

│   └── icons/                 # SVG 图标

│
├── components/                 # 组件

│   ├── layout/                # 布局组件

│   │   ├── AppHeader.vue
│   │   ├── AppSidebar.vue
│   │   ├── AppMain.vue
│   │   └── AppTabs.vue
│   ├── charts/                # 图表组件

│   │   ├── base/              # 基础图表组件

│   │   │   ├── BaseChart.vue  # 图表基类

│   │   │   ├── ChartMixin.ts  # 图表混入

│   │   │   └── chart-types.ts # 图表类型定义

│   │   ├── trading/           # 交易图表

│   │   │   ├── KLineChart.vue
│   │   │   ├── DepthChart.vue
│   │   │   └── TimeShareChart.vue
│   │   ├── analysis/          # 分析图表

│   │   │   ├── EquityCurve.vue
│   │   │   ├── DrawdownChart.vue
│   │   │   ├── PnLChart.vue
│   │   │   ├── TradeDistChart.vue
│   │   │   └── MonthlyReturns.vue
│   │   └── indicators/        # 指标图表

│   │       ├── BollingerChart.vue
│   │       ├── MACDChart.vue
│   │       └── RSIChart.vue
│   ├── strategy/              # 策略组件

│   │   ├── StrategyCard.vue
│   │   ├── ParamEditor.vue
│   │   ├── CodeEditor.vue
│   │   ├── TemplateSelector.vue
│   │   └── StrategyRunner.vue
│   ├── trading/               # 交易组件

│   │   ├── OrderBook.vue
│   │   ├── OrderForm.vue
│   │   ├── PositionList.vue
│   │   ├── OrderList.vue
│   │   └── TradeList.vue
│   └── common/                # 通用组件

│       ├── DataTable.vue
│       ├── StatusTag.vue
│       ├── DateTimePicker.vue
│       ├── SymbolSelector.vue
│       ├── LogViewer.vue
│       ├── EmptyState.vue
│       └── LoadingSpinner.vue
│
├── composables/                # 组合式函数

│   ├── useApi.ts              # API 调用

│   ├── useWebSocket.ts        # WebSocket

│   ├── useChart.ts            # ECharts 封装

│   ├── useTable.ts            # 表格封装

│   ├── usePagination.ts       # 分页

│   ├── useDebounce.ts         # 防抖

│   ├── useThrottle.ts         # 节流

│   └── useLocalStorage.ts     # 本地存储

│
├── directives/                 # 自定义指令

│   ├── loading.ts
│   ├── permission.ts
│   └── debounce.ts
│
├── layouts/                    # 布局

│   ├── DefaultLayout.vue
│   ├── EmptyLayout.vue
│   └── FullscreenLayout.vue
│
├── router/                     # 路由

│   ├── index.ts
│   ├── routes.ts
│   └── guards.ts              # 路由守卫

│
├── stores/                     # Pinia 状态

│   ├── index.ts
│   ├── useAppStore.ts
│   ├── useUserStore.ts
│   ├── useStrategyStore.ts
│   ├── useBacktestStore.ts
│   ├── useLiveStore.ts
│   └── useWebSocketStore.ts
│
├── types/                      # TypeScript 类型

│   ├── index.ts
│   ├── global.d.ts
│   ├── components.d.ts
│   ├── vue-shim.d.ts
│   ├── api.ts
│   ├── strategy.ts
│   ├── backtest.ts
│   ├── live.ts
│   └── chart.ts
│
├── utils/                      # 工具函数

│   ├── format.ts              # 格式化

│   ├── validate.ts            # 验证

│   ├── storage.ts             # 存储

│   ├── constants.ts           # 常量

│   ├── date.ts                # 日期

│   ├── number.ts              # 数字

│   └── download.ts            # 下载

│
├── views/                      # 页面视图

│   ├── Dashboard.vue
│   ├── strategies/
│   ├── backtests/
│   ├── live/
│   ├── data/
│   └── settings/
│
├── App.vue
└── main.ts

```bash

- --

## ECharts 图表组件库

### 基础图表组件

```vue
<!-- components/charts/base/BaseChart.vue -->
<template>
  <div
    ref="chartRef"
    class="base-chart"
    :style="{ width: width, height: height }"
  ></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkPointComponent
} from 'echarts/components'
import type { ECharts, EChartsOption } from 'echarts'
import { useThemeStore } from '@/stores/useThemeStore'
import { debounce } from 'lodash-es'

// 注册必需的组件
use([
  CanvasRenderer,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkPointComponent
])

interface Props {
  option: EChartsOption
  width?: string
  height?: string
  theme?: string | object

  loading?: boolean
  loadingOptions?: object
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '400px',
  theme: '',
  loading: false,
  loadingOptions: () => ({
    text: '加载中...',
    color: '#26a69a',
    textColor: '#fff',
    maskColor: 'rgba(0, 0, 0, 0.3)',
    zlevel: 0
  })
})

const emit = defineEmits<{
  ready: [chart: ECharts]
  click: [params: any]
}>()

const chartRef = ref<HTMLElement>()
const themeStore = useThemeStore()
let chartInstance: ECharts | null = null

const initChart = () => {
  if (!chartRef.value) return

  chartInstance = echarts.init(
    chartRef.value,
    props.theme || themeStore.chartTheme

  )

  chartInstance.on('click', (params) => {
    emit('click', params)
  })

  emit('ready', chartInstance)
  updateChart()
}

const updateChart = () => {
  if (!chartInstance) return

  if (props.loading) {
    chartInstance.showLoading('default', props.loadingOptions)
  } else {
    chartInstance.hideLoading()
  }

  chartInstance.setOption(props.option, true)
}

const resize = debounce(() => {
  chartInstance?.resize()
}, 300)

onMounted(() => {
  initChart()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(() => props.option, updateChart, { deep: true })
watch(() => props.loading, updateChart)

// 暴露方法给父组件
defineExpose({
  getInstance: () => chartInstance,
  resize: () => chartInstance?.resize(),
  clear: () => chartInstance?.clear(),
  dispatchAction: (action: any) => chartInstance?.dispatchAction(action)
})
</script>

<style scoped lang="scss">
.base-chart {
  min-height: 200px;
}
</style>

```bash

### K 线图组件（完整版）

```vue
<!-- components/charts/trading/KLineChart.vue -->
<template>
  <base-chart
    ref="chartRef"
    :option="chartOption"
    :width="width"
    :height="height"
    @click="handleClick"
    @ready="handleReady"
  />
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { use } from 'echarts/core'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import BaseChart from '../base/BaseChart.vue'
import type { ECharts } from 'echarts'
import type { KLineData, IndicatorData } from '@/types/chart'

use([CandlestickChart, BarChart, LineChart])

interface Props {
  data: KLineData[]
  indicators?: IndicatorData
  width?: string
  height?: string
  title?: string
  showVolume?: boolean
  showDataZoom?: boolean
  colors?: {
    up?: string
    down?: string
    bg?: string
    grid?: string
  }
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '500px',
  title: '',
  showVolume: true,
  showDataZoom: true,
  colors: () => ({
    up: '#26a69a',
    down: '#ef5350',
    bg: '#161624',
    grid: '#232336'
  })
})

const emit = defineEmits<{
  click: [params: any]
  ready: [chart: ECharts]
}>()

const chartRef = ref<InstanceType<typeof BaseChart>>()

const chartOption = computed(() => {
  if (!props.data.length) return {}

  const dates = props.data.map(item => item.date)
  const candleData = props.data.map(item => [
    item.open,
    item.close,
    item.low,
    item.high
  ])
  const volumes = props.data.map((item, index) => [
    index,
    item.volume,
    item.open > item.close ? -1 : 1
  ])

  const grid = [
    {
      left: '10%',
      right: '10%',
      top: props.title ? '15%' : '8%',
      height: props.showVolume ? '50%' : '65%'
    }
  ]

  if (props.showVolume) {
    grid.push({
      left: '10%',
      right: '10%',
      top: '70%',
      height: '15%'
    })
  }

  const xAxis = [
    {
      type: 'category',
      data: dates,
      scale: true,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#777' } },
      splitLine: { show: false },
      min: 'dataMin',
      max: 'dataMax'
    }
  ]

  if (props.showVolume) {
    xAxis.push({
      type: 'category',
      gridIndex: 1,
      data: dates,
      scale: true,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#777' } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      min: 'dataMin',
      max: 'dataMax'
    })
  }

  const yAxis = [
    {
      scale: true,
      axisLine: { lineStyle: { color: '#777' } },
      splitLine: { lineStyle: { color: props.colors.grid } }
    }
  ]

  if (props.showVolume) {
    yAxis.push({
      scale: true,
      gridIndex: 1,
      splitNumber: 2,
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false }
    })
  }

  const series: any[] = [
    {
      name: 'K 线',
      type: 'candlestick',
      data: candleData,
      barWidth: '60%',
      itemStyle: {
        color: props.colors.up,
        color0: props.colors.down,
        borderColor: props.colors.up,
        borderColor0: props.colors.down
      }
    }
  ]

  // 添加指标线
  if (props.indicators?.upper) {
    series.push({
      name: '上轨',
      type: 'line',
      data: props.indicators.upper,
      smooth: true,
      lineStyle: { color: '#2962ff', width: 1 },
      showSymbol: false,
      lineStyle: { opacity: 0.8 }
    })
  }

  if (props.indicators?.middle) {
    series.push({
      name: '中轨',
      type: 'line',
      data: props.indicators.middle,
      smooth: true,
      lineStyle: { color: '#ff9800', width: 1 },
      showSymbol: false,
      lineStyle: { opacity: 0.8 }
    })
  }

  if (props.indicators?.lower) {
    series.push({
      name: '下轨',
      type: 'line',
      data: props.indicators.lower,
      smooth: true,
      lineStyle: { color: '#2962ff', width: 1 },
      showSymbol: false,
      lineStyle: { opacity: 0.8 }
    })
  }

  if (props.showVolume) {
    series.push({
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: volumes,
      barWidth: '60%',
      itemStyle: {
        color: (params: any) => {
          return params[2] > 0 ? props.colors.up : props.colors.down
        }
      }
    })
  }

  const dataZoom = props.showDataZoom ? [
    {
      type: 'inside',
      xAxisIndex: [0, 1],
      start: 70,
      end: 100
    },
    {
      show: true,
      xAxisIndex: [0, 1],
      type: 'slider',
      top: props.showVolume ? '90%' : '92%',
      start: 70,
      end: 100,
      backgroundColor: 'rgba(255,255,255,0.1)',
      borderColor: 'rgba(255,255,255,0.2)',
      textStyle: { color: '#999' },
      handleStyle: { color: '#fff' },
      dataBackground: {
        lineStyle: { color: 'rgba(255,255,255,0.1)' },
        areaStyle: { color: 'rgba(255,255,255,0.1)' }
      },
      selectedDataBackground: {
        lineStyle: { color: '#26a69a' },
        areaStyle: { color: '#26a69a' }
      }
    }
  ] : undefined

  return {
    backgroundColor: props.colors.bg,
    title: props.title ? {
      text: props.title,
      left: 'center',
      textStyle: { color: '#fff' }
    } : undefined,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(0,0,0,0.8)',
      borderColor: '#333',
      textStyle: { color: '#fff' },
      formatter: (params: any) => {
        if (!params.length) return ''
        const kLine = params[0]
        let html = `${kLine.axisValue}<br/>`
        html += `<span style="color:${kLine.color}">●</span> `
        html += `开: ${kLine.data[1]}<br/>`
        html += `<span style="color:${kLine.color}">●</span> `
        html += `收: ${kLine.data[2]}<br/>`
        html += `<span style="color:${kLine.color}">●</span> `
        html += `低: ${kLine.data[3]}<br/>`
        html += `<span style="color:${kLine.color}">●</span> `
        html += `高: ${kLine.data[4]}<br/>`
        // 添加指标
        if (props.indicators?.upper) {
          html += `上轨: ${props.indicators.upper[kLine.dataIndex].toFixed(2)}<br/>`
        }
        return html
      }
    },
    legend: {
      data: ['K 线', '上轨', '中轨', '下轨', '成交量'].filter(Boolean),
      top: props.title ? '50' : '10',
      textStyle: { color: '#999' }
    },
    grid,
    xAxis,
    yAxis,
    dataZoom,
    series
  }
})

const handleReady = (chart: ECharts) => {
  emit('ready', chart)
}

const handleClick = (params: any) => {
  emit('click', params)
}

// 暴露方法
defineExpose({
  getInstance: () => chartRef.value?.getInstance(),
  resize: () => chartRef.value?.resize(),
  dispatchAction: (action: any) => chartRef.value?.dispatchAction(action)
})
</script>

```bash

### 资金曲线图组件（完整版）

```vue
<!-- components/charts/analysis/EquityCurve.vue -->
<template>
  <base-chart
    ref="chartRef"
    :option="chartOption"
    :width="width"
    :height="height"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import BaseChart from '../base/BaseChart.vue'
import type { EquityData } from '@/types/chart'

use([LineChart, BarChart])

interface Props {
  data: EquityData[]
  width?: string
  height?: string
  title?: string
  showDrawdown?: boolean
  showTrades?: boolean
  colors?: {
    equity?: string
    drawdown?: string
    trade?: string
  }
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '400px',
  title: '资金曲线',
  showDrawdown: true,
  showTrades: true,
  colors: () => ({
    equity: '#26a69a',
    drawdown: '#ef5350',
    trade: '#ff9800'
  })
})

const chartOption = computed(() => {
  if (!props.data.length) return {}

  const dates = props.data.map(item => item.date)
  const equity = props.data.map(item => item.equity)
  const drawdown = props.data.map(item => item.drawdown || 0)

  const trades = props.data.map(item => item.trades || 0)

  const series: any[] = [
    {
      name: '权益',
      type: 'line',
      data: equity,
      smooth: true,
      symbol: 'none',
      lineStyle: {
        color: props.colors.equity,
        width: 2
      },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(38, 166, 154, 0.4)' },
            { offset: 1, color: 'rgba(38, 166, 154, 0.05)' }
          ]
        }
      },
      markLine: {
        symbol: 'none',
        label: { show: false },
        data: [{ yAxis: props.data[0].equity }],
        lineStyle: { color: '#999', type: 'dashed', opacity: 0.5 }
      }
    }
  ]

  if (props.showDrawdown) {
    series.push({
      name: '回撤',
      type: 'line',
      data: drawdown,
      smooth: true,
      symbol: 'none',
      lineStyle: {
        color: props.colors.drawdown,
        width: 1,
        type: 'dashed'
      },
      yAxisIndex: 1
    })
  }

  if (props.showTrades) {
    series.push({
      name: '交易次数',
      type: 'bar',
      data: trades,
      itemStyle: {
        color: props.colors.trade,
        opacity: 0.3
      },
      yAxisIndex: 2
    })
  }

  return {
    backgroundColor: '#161624',
    title: {
      text: props.title,
      left: 'center',
      textStyle: { color: '#fff' }
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(0,0,0,0.8)',
      borderColor: '#333',
      textStyle: { color: '#fff' },
      formatter: (params: any) => {
        if (!params.length) return ''
        let html = `${params[0].axisValue}<br/>`
        params.forEach((param: any) => {
          const value = param.seriesName === '回撤'
            ? `${param.value.toFixed(2)}%`
            : param.seriesName === '交易次数'
            ? param.value
            : `$${param.value.toFixed(2)}`
          html += `${param.marker} ${param.seriesName}: ${value}<br/>`
        })
        return html
      }
    },
    legend: {
      data: ['权益', '回撤', '交易次数'].filter((_, i) =>
        i === 0 || (i === 1 && props.showDrawdown) || (i === 2 && props.showTrades)

      ),
      top: 30,
      textStyle: { color: '#999' }
    },
    grid: [
      {
        left: '3%',
        right: props.showDrawdown || props.showTrades ? '15%' : '4%',

        top: '15%',
        height: '70%'
      }
    ],
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: '#777' } },
      axisLabel: { color: '#999' }
    },
    yAxis: [
      {
        type: 'value',
        scale: true,
        axisLine: { lineStyle: { color: '#777' } },
        axisLabel: { color: '#999', formatter: '${value}' },
        splitLine: { lineStyle: { color: '#232336' } }
      }
    ].concat(
      props.showDrawdown
        ? [{
            type: 'value',
            scale: true,
            position: 'right',
            axisLine: { show: false },
            axisLabel: { color: '#999', formatter: '{value}%' },
            splitLine: { show: false }
          }]
        : []
    ).concat(
      props.showTrades
        ? [{
            type: 'value',
            scale: true,
            position: 'right',
            offset: props.showDrawdown ? 60 : 0,
            axisLine: { show: false },
            axisLabel: { color: '#999' },
            splitLine: { show: false }
          }]
        : []
    ),
    series
  }
})
</script>

```bash

### 深度图组件

```vue
<!-- components/charts/trading/DepthChart.vue -->
<template>
  <base-chart
    ref="chartRef"
    :option="chartOption"
    :width="width"
    :height="height"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import BaseChart from '../base/BaseChart.vue'

use([BarChart])

interface DepthItem {
  price: number
  amount: number
  total?: number
}

interface Props {
  bids: DepthItem[]
  asks: DepthItem[]
  width?: string
  height?: string
  maxDepth?: number
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '300px',
  maxDepth: 20
})

const chartOption = computed(() => {
  // 计算累计
  const calcTotal = (arr: DepthItem[]) => {
    let sum = 0
    return arr.map(item => {
      sum += item.amount
      return { ...item, total: sum }
    })
  }

  const bidsWithTotal = calcTotal(props.bids.slice(0, props.maxDepth).reverse())
  const asksWithTotal = calcTotal(props.asks.slice(0, props.maxDepth))

  const bidPrices = bidsWithTotal.map(item => item.price.toFixed(2))
  const bidAmounts = bidsWithTotal.map(item => item.total)
  const askPrices = asksWithTotal.map(item => item.price.toFixed(2))
  const askAmounts = asksWithTotal.map(item => item.total)

  return {
    backgroundColor: '#161624',
    grid: {
      left: '3%',
      right: '4%',
      top: '5%',
      bottom: '15%'
    },
    xAxis: {
      type: 'category',
      data: [...bidPrices, '---', ...askPrices],
      axisLine: { lineStyle: { color: '#777' } },
      axisLabel: {
        color: '#999',
        interval: 0,
        rotate: 45
      }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#777' } },
      axisLabel: { color: '#999' },
      splitLine: { lineStyle: { color: '#232336' } }
    },
    series: [
      {
        name: '买单',
        type: 'bar',
        data: [...bidAmounts, 0, ...new Array(askPrices.length).fill(0)],
        itemStyle: { color: '#26a69a' },
        stack: 'depth'
      },
      {
        name: '卖单',
        type: 'bar',
        data: [...new Array(bidPrices.length).fill(0), 0, ...askAmounts],
        itemStyle: { color: '#ef5350' },
        stack: 'depth'
      }
    ],
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(0,0,0,0.8)',
      borderColor: '#333',
      textStyle: { color: '#fff' },
      formatter: (params: any) => {
        if (!params.length || !params[0].name) return ''

        return `价格: ${params[0].name}<br/>累计: ${params[0].value.toFixed(4)}`
      }
    }
  }
})
</script>

```bash

### 交易分布图组件

```vue
<!-- components/charts/analysis/TradeDistChart.vue -->
<template>
  <base-chart
    ref="chartRef"
    :option="chartOption"
    :width="width"
    :height="height"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import BaseChart from '../base/BaseChart.vue'

use([ScatterChart])

interface TradePoint {
  entryTime: string
  exitTime: string
  pnl: number
  pnlPercent: number
  duration: number
  side: 'long' | 'short'

}

interface Props {
  trades: TradePoint[]
  width?: string
  height?: string
  chartType?: 'pnl-time' | 'pnl-duration' | 'entry-exit'

}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '400px',
  chartType: 'pnl-time'
})

const chartOption = computed(() => {
  if (!props.trades.length) return {}

  let data: any[] = []
  let xAxisName = ''
  let yAxisName = ''

  switch (props.chartType) {
    case 'pnl-time':
      data = props.trades.map(t => [t.exitTime, t.pnlPercent, t.side])
      xAxisName = '平仓时间'
      yAxisName = '收益率 (%)'
      break
    case 'pnl-duration':
      data = props.trades.map(t => [t.duration, t.pnlPercent, t.side])
      xAxisName = '持仓时长 (分钟)'
      yAxisName = '收益率 (%)'
      break
    case 'entry-exit':
      data = props.trades.map(t => [t.entryTime, t.exitTime, t.pnlPercent])
      xAxisName = '开仓时间'
      yAxisName = '平仓时间'
      break
  }

  return {
    backgroundColor: '#161624',
    grid: {
      left: '10%',
      right: '5%',
      top: '10%',
      bottom: '15%'
    },
    xAxis: {
      type: props.chartType === 'entry-exit' ? 'time' : 'category',
      name: xAxisName,
      nameTextStyle: { color: '#999' },
      axisLine: { lineStyle: { color: '#777' } },
      axisLabel: { color: '#999' }
    },
    yAxis: {
      type: props.chartType === 'entry-exit' ? 'time' : 'value',
      name: yAxisName,
      nameTextStyle: { color: '#999' },
      axisLine: { lineStyle: { color: '#777' } },
      axisLabel: { color: '#999' },
      splitLine: { lineStyle: { color: '#232336' } }
    },
    visualMap: {
      show: true,
      dimension: props.chartType === 'entry-exit' ? 2 : 2,
      min: -10,
      max: 10,
      inRange: {
        color: ['#ef5350', '#fff', '#26a69a']
      },
      textStyle: { color: '#999' },
      calculable: true,
      right: '2%',
      bottom: '5%'
    },
    series: [
      {
        type: 'scatter',
        symbolSize: (val: any) => Math.abs(val[2]) * 3 + 5,
        data,
        itemStyle: {
          opacity: 0.8,
          borderColor: '#fff',
          borderWidth: 1
        },
        markLine: {
          lineStyle: { color: '#999', type: 'dashed' },
          data: [{ yAxis: 0 }]
        }
      }
    ],
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(0,0,0,0.8)',
      borderColor: '#333',
      textStyle: { color: '#fff' },
      formatter: (params: any) => {
        const [x, y, z] = params.value
        let html = `${params.marker}<br/>`
        if (props.chartType === 'pnl-time') {
          html += `平仓: ${x}<br/>收益率: ${z.toFixed(2)}%`
        } else if (props.chartType === 'pnl-duration') {
          html += `时长: ${x} 分钟<br/>收益率: ${z.toFixed(2)}%`
        } else {
          html += `开仓: ${new Date(x).toLocaleString()}<br/>`
          html += `平仓: ${new Date(y).toLocaleString()}<br/>`
          html += `收益: ${z.toFixed(2)}%`
        }
        return html
      }
    }
  }
})
</script>

```bash

- --

## 状态管理优化

### 响应式存储配置

```typescript
// stores/index.ts
import { createPinia } from 'pinia'
import { createPersistedState } from 'pinia-plugin-persistedstate'

const pinia = createPinia()
pinia.use(createPersistedState({
  storage: localStorage,
  key: id => `__persisted__${id}`
}))

export default pinia

```bash

### 应用状态 Store

```typescript
// stores/useAppStore.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { store } from './index'

export const useAppStore = defineStore('app', () => {
  // 状态
  const sidebarCollapsed = ref(false)
  const theme = ref<'dark' | 'light'>('dark')

  const loading = ref(false)
  const breadcrumbs = ref<Array<{ name: string, path?: string }>>([])
  const tabs = ref<Array<{
    key: string
    title: string
    path: string
    closable: boolean
  }>>([])
  const activeTab = ref('')

  // 计算属性
  const chartTheme = computed(() => theme.value === 'dark' ? 'dark' : '')

  // 方法
  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  const setTheme = (newTheme: 'dark' | 'light') => {

    theme.value = newTheme
    document.documentElement.className = newTheme
  }

  const setLoading = (value: boolean) => {
    loading.value = value
  }

  const addTab = (tab: { key: string, title: string, path: string, closable?: boolean }) => {
    const exists = tabs.value.find(t => t.key === tab.key)
    if (!exists) {
      tabs.value.push({ ...tab, closable: tab.closable ?? true })
    }
    activeTab.value = tab.key
  }

  const removeTab = (key: string) => {
    const index = tabs.value.findIndex(t => t.key === key)
    if (index > -1) {
      tabs.value.splice(index, 1)
      if (activeTab.value === key && tabs.value.length) {
        activeTab.value = tabs.value[Math.max(0, index - 1)].key
      }
    }
  }

  const setBreadcrumbs = (crumbs: Array<{ name: string, path?: string }>) => {
    breadcrumbs.value = crumbs
  }

  return {
    // 状态
    sidebarCollapsed,
    theme,
    loading,
    breadcrumbs,
    tabs,
    activeTab,
    // 计算属性
    chartTheme,
    // 方法
    toggleSidebar,
    setTheme,
    setLoading,
    addTab,
    removeTab,
    setBreadcrumbs
  }
}, {
  persist: {
    key: 'app',
    paths: ['sidebarCollapsed', 'theme', 'tabs']
  }
})

```bash

### WebSocket Store

```typescript
// stores/useWebSocketStore.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

type MessageHandler = (data: any) => void
type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export const useWebSocketStore = defineStore('websocket', () => {
  const ws = ref<WebSocket | null>(null)

  const status = ref<ConnectionStatus>('disconnected')
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 5
  const reconnectDelay = 3000

  const handlers = ref<Map<string, Set<MessageHandler>>>(new Map())

  const isConnected = computed(() => status.value === 'connected')

  const connect = (url: string) => {
    if (ws.value?.readyState === WebSocket.OPEN) {
      return
    }

    status.value = 'connecting'

    try {
      ws.value = new WebSocket(url)

      ws.value.onopen = () => {
        status.value = 'connected'
        reconnectAttempts.value = 0
        console.log('WebSocket connected')
      }

      ws.value.onclose = () => {
        status.value = 'disconnected'
        console.log('WebSocket disconnected')

        // 自动重连
        if (reconnectAttempts.value < maxReconnectAttempts) {
          reconnectAttempts.value++
          setTimeout(() => connect(url), reconnectDelay)
        }
      }

      ws.value.onerror = (error) => {
        status.value = 'error'
        console.error('WebSocket error:', error)
      }

      ws.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          const { type, payload } = data

          const typeHandlers = handlers.value.get(type)
          if (typeHandlers) {
            typeHandlers.forEach(handler => handler(payload))
          }

          // 通用处理器
          const allHandlers = handlers.value.get('*')
          if (allHandlers) {
            allHandlers.forEach(handler => handler(data))
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }
    } catch (error) {
      status.value = 'error'
      console.error('Failed to create WebSocket:', error)
    }
  }

  const disconnect = () => {
    ws.value?.close()
    ws.value = null
    status.value = 'disconnected'
  }

  const send = (type: string, payload?: any) => {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type, payload }))
    }
  }

  const subscribe = (type: string, handler: MessageHandler) => {
    if (!handlers.value.has(type)) {
      handlers.value.set(type, new Set())
    }
    handlers.value.get(type)!.add(handler)

    // 返回取消订阅函数
    return () => {
      const typeHandlers = handlers.value.get(type)
      if (typeHandlers) {
        typeHandlers.delete(handler)
        if (typeHandlers.size === 0) {
          handlers.value.delete(type)
        }
      }
    }
  }

  const subscribeOnce = (type: string, handler: MessageHandler) => {
    const wrappedHandler = (payload: any) => {
      handler(payload)
      unsubscribe()
    }
    const unsubscribe = subscribe(type, wrappedHandler)
  }

  return {
    status,
    isConnected,
    reconnectAttempts,
    connect,
    disconnect,
    send,
    subscribe,
    subscribeOnce
  }
})

```bash

- --

## 性能优化方案

### 虚拟滚动组件

```vue
<!-- components/common/VirtualList.vue -->
<template>
  <div
    ref="containerRef"
    class="virtual-list"
    :style="{ height: containerHeight }"
    @scroll="handleScroll"
  >
    <div
      class="virtual-list-spacer"
      :style="{ height: `${totalHeight}px` }"
    >
      <div
        class="virtual-list-content"
        :style="{ transform: `translateY(${offsetY}px)` }"
      >
        <div
          v-for="item in visibleItems"
          :key="item[keyField]"
          class="virtual-list-item"
          :style="{ height: `${itemHeight}px` }"
        >
          <slot :item="item" :index="item._index" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'

interface Props {
  items: any[]
  itemHeight: number
  containerHeight: string
  keyField?: string
  buffer?: number
}

const props = withDefaults(defineProps<Props>(), {
  keyField: 'id',
  buffer: 5
})

const containerRef = ref<HTMLElement>()
const scrollTop = ref(0)

const totalHeight = computed(() => props.items.length *props.itemHeight)

const visibleCount = computed(() => {
  const height = parseInt(props.containerHeight)
  return Math.ceil(height / props.itemHeight) + props.buffer*2
})

const startIndex = computed(() => {
  const index = Math.floor(scrollTop.value / props.itemHeight) - props.buffer
  return Math.max(0, index)
})

const endIndex = computed(() => {
  return Math.min(props.items.length, startIndex.value + visibleCount.value)
})

const offsetY = computed(() => {
  return startIndex.value*props.itemHeight
})

const visibleItems = computed(() => {
  return props.items.slice(startIndex.value, endIndex.value).map((item, i) => ({
    ...item,
    _index: startIndex.value + i
  }))
})

const handleScroll = (e: Event) => {
  scrollTop.value = (e.target as HTMLElement).scrollTop
}

// 暴露滚动方法
defineExpose({
  scrollTo: (index: number) => {
    if (containerRef.value) {
      const top = index* props.itemHeight
      containerRef.value.scrollTop = top
    }
  }
})
</script>

<style scoped lang="scss">
.virtual-list {
  overflow-y: auto;
  position: relative;

  &-spacer {
    position: relative;
  }

  &-content {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
  }
}
</style>

```bash

### 请求缓存封装

```typescript
// composables/useCache.ts
import { ref, shallowRef } from 'vue'

interface CacheOptions {
  ttl?: number // 毫秒
  staleWhileRevalidate?: boolean
}

const cache = new Map<string, {
  data: any
  timestamp: number
  ttl: number
}>()

export function useCache<T>(key: string, options: CacheOptions = {}) {
  const { ttl = 60000, staleWhileRevalidate = true } = options

  const data = shallowRef<T | null>(null)

  const isLoading = ref(false)
  const error = ref<Error | null>(null)

  const get = () => {
    const cached = cache.get(key)
    if (cached) {
      const age = Date.now() - cached.timestamp
      if (age < cached.ttl) {
        data.value = cached.data
        return true
      } else if (staleWhileRevalidate) {
        // 返回过期数据，同时在后台刷新
        data.value = cached.data
        return false
      }
    }
    return false
  }

  const set = (value: T) => {
    cache.set(key, {
      data: value,
      timestamp: Date.now(),
      ttl
    })
    data.value = value
  }

  const clear = () => {
    cache.delete(key)
    data.value = null
  }

  return {
    data,
    isLoading,
    error,
    get,
    set,
    clear
  }
}

export function clearCache(pattern?: string) {
  if (pattern) {
    const regex = new RegExp(pattern)
    for (const key of cache.keys()) {
      if (regex.test(key)) {
        cache.delete(key)
      }
    }
  } else {
    cache.clear()
  }
}

```bash

### 防抖/节流 Composable

```typescript
// composables/useDebounce.ts
import { ref, watch } from 'vue'
import { debounce as _debounce, throttle as _throttle } from 'lodash-es'

export function useDebounce<T>(value: Ref<T>, delay: number) {
  const debouncedValue = ref(value.value)

  const updater = _debounce((newValue: T) => {
    debouncedValue.value = newValue
  }, delay)

  watch(value, (newValue) => {
    updater(newValue)
  })

  return debouncedValue
}

export function useThrottle<T>(value: Ref<T>, delay: number) {
  const throttledValue = ref(value.value)

  const updater = _throttle((newValue: T) => {
    throttledValue.value = newValue
  }, delay)

  watch(value, (newValue) => {
    updater(newValue)
  })

  return throttledValue
}

// 函数防抖
export function useDebounceFn<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): T & { cancel: () => void } {
  const debounced = _debounce(fn, delay) as T & { cancel: () => void }
  return debounced
}

// 函数节流
export function useThrottleFn<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): T & { cancel: () => void } {
  const throttled = _throttle(fn, delay) as T & { cancel: () => void }
  return throttled
}

```bash

- --

## 组件设计规范

### 组件 Props 规范

```typescript
// types/components.ts

// 基础 Props 约束
export interface BaseProps {
  class?: string
  style?: string | Record<string, any>

}

// 加载状态 Props
export interface LoadingProps {
  loading?: boolean
  loadingText?: string
}

// 尺寸 Props
export type Size = 'small' | 'medium' | 'large'

export interface SizeProps {
  size?: Size
  width?: string | number

  height?: string | number

}

// 主题 Props
export type Theme = 'primary' | 'success' | 'warning' | 'danger' | 'info'

export interface ThemeProps {
  theme?: Theme
}

```bash

### 组件 Emit 规范

```typescript
// 组件事件类型定义示例
export interface StrategyCardEmits {
  // 点击卡片
  click: [strategy: Strategy]
  // 编辑策略
  edit: [strategyId: string]
  // 删除策略
  delete: [strategyId: string]
  // 启动/停止
  toggle: [strategyId: string, running: boolean]
}

// 使用示例
const emit = defineEmits<StrategyCardEmits>()

```bash

- --

## 实时数据处理

### 实时价格更新 Hook

```typescript
// composables/useRealtimePrice.ts
import { ref, onUnmounted } from 'vue'
import { useWebSocketStore } from '@/stores/useWebSocketStore'

export function useRealtimePrice(symbol: string) {
  const price = ref<number | null>(null)

  const change24h = ref<number | null>(null)

  const volume24h = ref<number | null>(null)

  const lastUpdate = ref<Date | null>(null)

  const wsStore = useWebSocketStore()

  const unsubscribe = wsStore.subscribe(`ticker:${symbol}`, (data) => {
    price.value = data.price
    change24h.value = data.change24h
    volume24h.value = data.volume24h
    lastUpdate.value = new Date()
  })

  const subscribe = () => {
    wsStore.send('subscribe', { channel: 'ticker', symbol })
  }

  const unsubscribe = () => {
    wsStore.send('unsubscribe', { channel: 'ticker', symbol })
    unsubscribe()
  }

  onUnmounted(() => {
    unsubscribe()
  })

  return {
    price,
    change24h,
    volume24h,
    lastUpdate,
    subscribe,
    unsubscribe
  }
}

```bash

- --

## UI/UX 优化

### 全局样式变量

```scss
// assets/styles/variables.scss

// 颜色系统
$color-primary: #26a69a;
$color-success: #26a69a;
$color-warning: #ff9800;
$color-danger: #ef5350;
$color-info: #2196f3;

// 主题色 - 深色模式
$bg-dark-primary: #161624;
$bg-dark-secondary: #1e1e2f;
$bg-dark-tertiary: #232336;

$border-dark: #3a3a4a;

$text-dark-primary: #ffffff;
$text-dark-secondary: #b0b0c0;
$text-dark-tertiary: #777788;

// 主题色 - 浅色模式
$bg-light-primary: #ffffff;
$bg-light-secondary: #f5f5f7;
$bg-light-tertiary: #e5e5ea;

$border-light: #d1d1d6;

$text-light-primary: #1c1c1e;
$text-light-secondary: #636366;
$text-light-tertiary: #999999;

// 间距系统
$spacing-xs: 4px;
$spacing-sm: 8px;
$spacing-md: 16px;
$spacing-lg: 24px;
$spacing-xl: 32px;
$spacing-xxl: 48px;

// 圆角
$radius-sm: 4px;
$radius-md: 8px;
$radius-lg: 12px;
$radius-xl: 16px;

// 阴影
$shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
$shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
$shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);

// 过渡
$transition-fast: 150ms;
$transition-normal: 300ms;
$transition-slow: 500ms;

// Z-index 层级
$z-dropdown: 1000;
$z-sticky: 1020;
$z-fixed: 1030;
$z-modal-backdrop: 1040;
$z-modal: 1050;
$z-popover: 1060;
$z-tooltip: 1070;

```bash

### Element Plus 主题覆盖

```scss
// assets/styles/element.scss

// 导入变量
@import './variables.scss';

// 覆盖 Element Plus 变量
@forward 'element-plus/theme-chalk/src/common/var.scss' with (
  $colors: (
    'primary': (
      'base': $color-primary
    ),
    'success': (
      'base': $color-success
    ),
    'warning': (
      'base': $color-warning
    ),
    'danger': (
      'base': $color-danger
    ),
    'info': (
      'base': $color-info
    )
  ),
  $button: (
    'border-radius': $radius-md
  ),
  $input: (
    'border-radius': $radius-md
  )
);

// 深色模式覆盖
.dark {

  - -el-bg-color: #{$bg-dark-primary};
  - -el-bg-color-overlay: #{$bg-dark-secondary};
  - -el-text-color-primary: #{$text-dark-primary};
  - -el-text-color-regular: #{$text-dark-secondary};
  - -el-border-color: #{$border-dark};
  - -el-border-color-light: #{$border-dark};
  - -el-fill-color-light: #{$bg-dark-tertiary};

  .el-card {
    background-color: $bg-dark-secondary;
    border-color: $border-dark;
  }

  .el-table {
    background-color: $bg-dark-secondary;
    color: $text-dark-primary;

    th, td {
      border-color: $border-dark;
    }

    &--enable-row-hover .el-table__body tr:hover > td {
      background-color: $bg-dark-tertiary;
    }
  }

  .el-dialog {
    background-color: $bg-dark-secondary;
  }

  .el-drawer {
    background-color: $bg-dark-secondary;
  }
}

```bash

- --

## 开发规范

### 命名规范

```bash
组件文件:        PascalCase (StrategyCard.vue)
组合式函数:      camelCase with 'use' prefix (useApi.ts)
工具函数:        camelCase (formatNumber.ts)
常量:            UPPER_SNAKE_CASE (API_BASE_URL)
类型:            PascalCase (StrategyData)
接口:            PascalCase with 'I' prefix (IUserData)

```bash

### 文件导入顺序

```typescript
// 1. Vue 导入
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

// 2. 第三方库
import { debounce } from 'lodash-es'
import dayjs from 'dayjs'

// 3. 内部组件
import BaseChart from '@/components/charts/base/BaseChart.vue'

// 4. Composables
import { useApi } from '@/composables/useApi'
import { useWebSocketStore } from '@/stores/useWebSocketStore'

// 5. 类型
import type { StrategyData } from '@/types/strategy'

// 6. 工具函数
import { formatNumber } from '@/utils/format'

```bash

- --

## 总结

本优化方案涵盖：

1. **技术栈升级**: 完整的依赖和 Vite 配置
2. **架构优化**: 更清晰的目录结构
3. **图表组件库**: 完整的 ECharts 组件封装
4. **状态管理**: 优化的 Pinia Store 设计
5. **性能优化**: 虚拟滚动、缓存、防抖节流
6. **组件规范**: 统一的 Props 和 Emit 类型定义
7. **实时数据**: WebSocket Hook 封装
8. **UI/UX**: 完整的样式系统和主题支持
