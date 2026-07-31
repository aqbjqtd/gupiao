import { useEffect, useRef, useState } from 'react';
import { KlineItem } from '../api/stocks';
import { echarts } from '../lib/echarts';
import type { EChartsType, EChartsOption } from '../lib/echarts';

interface Props {
  data: KlineItem[];
  months: number;
  onMonthsChange: (m: number) => void;
}

export default function KLineChart({ data, months, onMonthsChange }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current);
    }
    const chart = instanceRef.current;

    const dates = data.map(d => d.date);
    const volumes = data.map(d => d.volume);
    const kData = data.map(d => [d.open, d.close, d.low, d.high]);
    const ma5 = data.map(d => d.ma5);
    const ma20 = data.map(d => d.ma20);
    const ma60 = data.map(d => d.ma60);

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(26,26,26,0.9)',
        borderColor: '#F0B90B',
        textStyle: { color: '#e0e0e0', fontFamily: 'JetBrains Mono, monospace' },
      },
      grid: [
        { left: '8%', right: '8%', top: '8%', height: '55%' },
        { left: '8%', right: '8%', top: '72%', height: '20%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { color: '#888', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
          splitLine: { show: false },
          gridIndex: 0,
        },
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { color: '#888', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
          splitLine: { show: false },
          gridIndex: 1,
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          splitLine: { lineStyle: { color: '#222' } },
          axisLabel: { color: '#888', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
        },
        {
          scale: true,
          gridIndex: 1,
          splitLine: { show: false },
          axisLabel: { color: '#888', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], start: 80, end: 100, bottom: 2, height: 12, borderColor: '#333', backgroundColor: '#1a1a1a', fillerColor: 'rgba(240,185,11,0.15)', handleStyle: { color: '#F0B90B' }, textStyle: { color: '#888', fontSize: 9 } },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: kData,
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
          xAxisIndex: 0,
          yAxisIndex: 0,
          encode: { x: 0, y: [1, 2, 3, 4] },
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma5,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#FFD54F', width: 1 },
          xAxisIndex: 0,
          yAxisIndex: 0,
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#4FC3F7', width: 1 },
          xAxisIndex: 0,
          yAxisIndex: 0,
        },
        {
          name: 'MA60',
          type: 'line',
          data: ma60,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#CE93D8', width: 1 },
          xAxisIndex: 0,
          yAxisIndex: 0,
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: {
            color: (params: any) => {
              const idx = params.dataIndex;
              const k = kData[idx];
              if (!k) return '#26a69a';
              // 与蜡烛颜色一致：上涨日（close >= open）红，下跌日绿
              return k[1] >= k[0] ? '#ef5350' : '#26a69a';
            },
          },
        },
      ],
    };

    chart.setOption(option, true);
    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [data]);

  const buttons = [
    { label: '6月', value: 6 },
    { label: '1年', value: 12 },
    { label: '2年', value: 24 },
    { label: '5年', value: 60 },
  ];

  return (
    <div className="kline-section">
      <div className="kline-header">
        <h3>前复权 K 线图</h3>
        <div className="kline-controls">
          {buttons.map(b => (
            <button
              key={b.value}
              className={`kline-btn ${months === b.value ? 'active' : ''}`}
              onClick={() => onMonthsChange(b.value)}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartRef} className="kline-chart" />
    </div>
  );
}
