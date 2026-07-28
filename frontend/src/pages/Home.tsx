import { useState, useEffect, useCallback } from 'react';
import { fetchStocks, fetchRefreshStatus, StockItem } from '../api/stocks';
import StockTable from '../components/StockTable';

export default function Home() {
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [sortField, setSortField] = useState<string | null>('rank');
  const [sortAsc, setSortAsc] = useState(true);

  const loadStocks = useCallback(async () => {
    try {
      const data = await fetchStocks();
      setStocks(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const status = await fetchRefreshStatus();
      setLastRefresh(status.last_refresh);
    } catch (_) {}
  }, []);

  useEffect(() => {
    loadStocks();
    loadStatus();
    const timer = setInterval(loadStatus, 5000);
    return () => clearInterval(timer);
  }, [loadStocks, loadStatus]);

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  // 排序
  let sortedStocks = [...stocks];
  if (sortField) {
    sortedStocks.sort((a, b) => {
      const aVal = (a as any)[sortField];
      const bVal = (b as any)[sortField];
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      if (typeof aVal === 'string') {
        return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      return sortAsc ? aVal - bVal : bVal - aVal;
    });
  }

  return (
    <div className="home-page">
      <div className="page-header">
        <div className="page-title">
          <h2>
            量化选股 · Top 20
            <span className="title-sub">
              （数据每个交易日 11:30/14:00 自动更新
              {lastRefresh && <>, 最近更新：{lastRefresh}</>}）
            </span>
          </h2>
        </div>
      </div>

      {error && <div className="error-banner">⚠️ {error}</div>}

      {loading ? (
        <div className="loading">加载中……</div>
      ) : (
        <StockTable
          stocks={sortedStocks}
          sortField={sortField}
          sortAsc={sortAsc}
          onSort={handleSort}
        />
      )}
    </div>
  );
}
