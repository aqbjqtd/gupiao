import { useNavigate } from 'react-router-dom';
import { StockItem } from '../api/stocks';

interface Props {
  stocks: StockItem[];
  sortField: string | null;
  sortAsc: boolean;
  onSort: (field: string) => void;
}

function fmt(val: number | null, decimals: number = 2, suffix: string = ''): string {
  if (val === null || val === undefined) return '—';
  return val.toFixed(decimals) + suffix;
}

function fmtPrice(val: number | null): string {
  if (val === null || val === undefined) return '—';
  return val < 1 ? val.toFixed(3) : val.toFixed(2);
}

export default function StockTable({ stocks, sortField, sortAsc, onSort }: Props) {
  const navigate = useNavigate();

  const sortArrow = (field: string) => {
    if (sortField !== field) return '';
    return sortAsc ? ' ↑' : ' ↓';
  };

  return (
    <div className="table-wrapper">
      <table className="stock-table">
        <thead>
          <tr>
            <th onClick={() => onSort('rank')} className="sortable">排名{sortArrow('rank')}</th>
            <th onClick={() => onSort('code')} className="sortable">代码{sortArrow('code')}</th>
            <th onClick={() => onSort('name')} className="sortable">名称{sortArrow('name')}</th>
            <th onClick={() => onSort('industry')} className="sortable">行业{sortArrow('industry')}</th>
            <th onClick={() => onSort('price')} className="sortable">现价{sortArrow('price')}</th>
            <th onClick={() => onSort('change_pct')} className="sortable">涨跌幅{sortArrow('change_pct')}</th>
            <th onClick={() => onSort('pe')} className="sortable">PE{sortArrow('pe')}</th>
            <th onClick={() => onSort('pb')} className="sortable">PB{sortArrow('pb')}</th>
            <th onClick={() => onSort('roe')} className="sortable">ROE%{sortArrow('roe')}</th>
            <th onClick={() => onSort('revenue_growth')} className="sortable">营收增速%{sortArrow('revenue_growth')}</th>
            <th onClick={() => onSort('profit_growth')} className="sortable">利润增速%{sortArrow('profit_growth')}</th>
            <th onClick={() => onSort('dividend_yield')} className="sortable">股息率%{sortArrow('dividend_yield')}</th>
            <th onClick={() => onSort('total_score')} className="sortable score-col">综合评分{sortArrow('total_score')}</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((s) => (
            <tr key={s.code} onClick={() => navigate(`/stock/${s.code}`)} className="clickable-row">
              <td className="rank-cell">{s.rank}</td>
              <td className="code-cell">{s.code}</td>
              <td className="name-cell">{s.name}</td>
              <td>{s.industry || '—'}</td>
              <td className="mono">{fmtPrice(s.price)}</td>
              <td className={`mono ${(s.change_pct ?? 0) >= 0 ? 'up' : 'down'}`}>
                {s.change_pct !== null ? `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%` : '—'}
              </td>
              <td className="mono">{fmt(s.pe, 2)}</td>
              <td className="mono">{fmt(s.pb, 2)}</td>
              <td className="mono">{fmt(s.roe, 2)}</td>
              <td className="mono">{fmt(s.revenue_growth, 2)}</td>
              <td className="mono">{fmt(s.profit_growth, 2)}</td>
              <td className="mono">{fmt(s.dividend_yield, 2)}</td>
              <td className="score-col">
                <div className="score-bar-container">
                  <div className="score-bar" style={{ width: `${Math.min(s.total_score ?? 0, 100)}%` }} />
                  <span className="score-text">{s.total_score !== null ? s.total_score.toFixed(1) : '—'}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
