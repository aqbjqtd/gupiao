import { useState, useEffect, useCallback } from 'react';
import { fetchStocks, fetchRefreshStatus, triggerRefresh, StockItem } from '../api/stocks';
import StockTable from '../components/StockTable';

export default function Home() {
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
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
      setRefreshing(status.is_running);
    } catch (_) {}
  }, []);

  useEffect(() => {
    loadStocks();
    loadStatus();
    const timer = setInterval(loadStatus, 5000);
    return () => clearInterval(timer);
  }, [loadStocks, loadStatus]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await triggerRefresh();
    } catch (_) {}
    // 轮询等待刷新完成
    const poll = setInterval(async () => {
      const status = await fetchRefreshStatus();
      if (!status.is_running) {
        clearInterval(poll);
        setRefreshing(false);
        setLastRefresh(status.last_refresh);
        loadStocks();
      }
    }, 2000);
  };

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
          <h2>量化选股 · Top 20</h2>
          {lastRefresh && (
            <span className="refresh-info">上次更新：{lastRefresh}</span>
          )}
        </div>
        <button
          className="refresh-btn"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? '刷新中……' : '⟳ 手动刷新'}
        </button>
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
