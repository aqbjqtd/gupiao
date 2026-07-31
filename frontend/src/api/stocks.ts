import { BrowserRouter } from 'react-router-dom';

const BASE = '/api';

export interface StockItem {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  pe: number | null;
  pb: number | null;
  roe: number | null;
  revenue_growth: number | null;
  profit_growth: number | null;
  gross_margin: number | null;
  dividend_yield: number | null;
  market_cap: number | null;
  industry: string | null;
  total_score: number | null;
  quality_score: number | null;
  dividend_score: number | null;
  value_score: number | null;
  growth_score: number | null;
  momentum_score: number | null;
  rank: number | null;
}

export interface KlineItem {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
}

export interface KlineResponse {
  code: string;
  name: string;
  adj_type: string;
  data: KlineItem[];
}

export interface RefreshStatus {
  is_running: boolean;
  last_refresh: string | null;
  message: string;
}

export interface FinancialHistoryItem {
  quarter: string;
  revenue: number | null;
  profit: number | null;
  roe: number | null;
  gross_margin: number | null;
  revenue_growth: number | null;
  profit_growth: number | null;
}

export interface StockDetail extends StockItem {
  financials: FinancialHistoryItem[];
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchStocks(): Promise<StockItem[]> {
  return request<StockItem[]>('/stocks');
}

export async function fetchStockDetail(code: string): Promise<StockDetail> {
  return request<StockDetail>(`/stocks/${code}`);
}

export async function fetchKline(code: string, months: number = 12): Promise<KlineResponse> {
  return request<KlineResponse>(`/stocks/${code}/kline?months=${months}`);
}

export async function fetchRefreshStatus(): Promise<RefreshStatus> {
  return request<RefreshStatus>('/refresh/status');
}

export async function triggerRefresh(): Promise<any> {
  return request<any>('/refresh', { method: 'POST' });
}
