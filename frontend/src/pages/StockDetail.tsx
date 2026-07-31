import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { fetchStockDetail, fetchKline, StockDetail, KlineResponse, FinancialHistoryItem } from '../api/stocks';
import StockCard from '../components/StockCard';
import KLineChart from '../components/KLineChart';
import { echarts } from '../lib/echarts';
import type { EChartsType, EChartsOption } from '../lib/echarts';
import { useRef, useCallback } from 'react';

export default function StockDetailPage() {
  const { code } = useParams<{ code: string }>();
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [kline, setKline] = useState<KlineResponse | null>(null);
  const [months, setMonths] = useState(12);
  const [loading, setLoading] = useState(true);
  const [klineLoading, setKlineLoading] = useState(false);
  const radarRef = useRef<HTMLDivElement>(null);
  const radarInstance = useRef<EChartsType | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    fetchStockDetail(code)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [code]);

  useEffect(() => {
    if (!code) return;
    setKlineLoading(true);
    fetchKline(code, months)
      .then(setKline)
      .catch(() => {})
      .finally(() => setKlineLoading(false));
  }, [code, months]);

  // 雷达图
  useEffect(() => {
    if (!detail || !radarRef.current) return;

    if (!radarInstance.current) {
      radarInstance.current = echarts.init(radarRef.current);
    }
    const chart = radarInstance.current;

    const maxScore = 100;
    const option: EChartsOption = {
      backgroundColor: 'transparent',
      radar: {
        indicator: [
          { name: '质量', max: maxScore },
          { name: '分红', max: maxScore },
          { name: '估值', max: maxScore },
          { name: '成长', max: maxScore },
          { name: '动量', max: maxScore },
        ],
        axisName: { color: '#e0e0e0', fontSize: 12, fontFamily: 'Noto Sans SC, sans-serif' },
        splitArea: { areaStyle: { color: ['rgba(240,185,11,0.02)', 'rgba(240,185,11,0.04)'] } },
        axisLine: { lineStyle: { color: '#333' } },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [
                detail.quality_score ?? 0,
                detail.dividend_score ?? 0,
                detail.value_score ?? 0,
                detail.growth_score ?? 0,
                detail.momentum_score ?? 0,
              ],
              name: '评分',
              areaStyle: { color: 'rgba(240,185,11,0.25)' },
              lineStyle: { color: '#F0B90B', width: 2 },
              itemStyle: { color: '#F0B90B' },
            },
          ],
        },
      ],
    };
    chart.setOption(option, true);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [detail]);

  if (loading) {
    return <div className="loading">加载中……</div>;
  }

  if (!detail) {
    return <div className="error-banner">股票不存在或加载失败</div>;
  }

  return (
    <div className="detail-page">
      <div className="breadcrumb">
        <Link to="/">首页</Link> &gt; <span>{code}</span>
      </div>

      <StockCard stock={detail} />

      {/* 五维雷达图 */}
      <div className="radar-section">
        <h3>五维评分</h3>
        <div ref={radarRef} className="radar-chart" />
      </div>

      {/* K 线 */}
      {klineLoading ? (
        <div className="loading">K 线加载中……</div>
      ) : kline && kline.data ? (
        <KLineChart
          data={kline.data}
          months={months}
          onMonthsChange={setMonths}
        />
      ) : (
        <div className="error-banner">K 线数据加载失败</div>
      )}

      {/* 财务数据 */}
      {detail.financials && detail.financials.length > 0 && (
        <div className="financial-section">
          <h3>财务数据（最近 4 季度）</h3>
          <div className="table-wrapper">
            <table className="stock-table">
              <thead>
                <tr>
                  <th>季度</th>
                  <th>营收</th>
                  <th>净利润</th>
                  <th>ROE%</th>
                  <th>毛利率%</th>
                  <th>营收增速%</th>
                  <th>利润增速%</th>
                </tr>
              </thead>
              <tbody>
                {detail.financials.map((f: FinancialHistoryItem, i: number) => (
                  <tr key={i}>
                    <td>{f.quarter || '—'}</td>
                    <td className="mono">{f.revenue?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{f.profit?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{f.roe?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{f.gross_margin?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{f.revenue_growth?.toFixed(2) ?? '—'}</td>
                    <td className="mono">{f.profit_growth?.toFixed(2) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
