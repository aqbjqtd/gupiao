import { StockDetail } from '../api/stocks';

interface Props {
  stock: StockDetail;
}

function fmt(val: number | null, decimals: number = 2, suffix: string = ''): string {
  if (val === null || val === undefined) return '—';
  return val.toFixed(decimals) + suffix;
}

export default function StockCard({ stock }: Props) {
  return (
    <div className="stock-card">
      <div className="card-header">
        <h2>{stock.name} <span className="code-label">{stock.code}</span></h2>
        <span className="industry-tag">{stock.industry || '未知行业'}</span>
      </div>
      <div className="card-grid">
        <div className="card-item">
          <label>现价</label>
          <span className="mono value">{fmt(stock.price, 2)}</span>
        </div>
        <div className="card-item">
          <label>涨跌幅</label>
          <span className={`mono value ${(stock.change_pct ?? 0) >= 0 ? 'up' : 'down'}`}>
            {stock.change_pct !== null ? `${stock.change_pct >= 0 ? '+' : ''}${stock.change_pct.toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="card-item">
          <label>PE</label>
          <span className="mono value">{fmt(stock.pe, 2)}</span>
        </div>
        <div className="card-item">
          <label>PB</label>
          <span className="mono value">{fmt(stock.pb, 2)}</span>
        </div>
        <div className="card-item">
          <label>ROE</label>
          <span className="mono value">{fmt(stock.roe, 2)}%</span>
        </div>
        <div className="card-item">
          <label>市值</label>
          <span className="mono value">{stock.market_cap !== null ? `${stock.market_cap.toFixed(0)}亿` : '—'}</span>
        </div>
      </div>
    </div>
  );
}
