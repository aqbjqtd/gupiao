// 按需注册 ECharts 模块，避免打包整个 echarts（bundle 可减小约 60%）
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, LineChart, RadarChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  CandlestickChart,
  LineChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
  CanvasRenderer,
]);

export { echarts };
export type { EChartsType } from 'echarts/core';
export type { EChartsOption } from 'echarts';
