import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';

// 详情页懒加载：echarts 只在进入个股页时下载，首页首屏更轻
const StockDetail = lazy(() => import('./pages/StockDetail'));

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route
          path="/stock/:code"
          element={
            <Suspense fallback={<div className="loading">加载中……</div>}>
              <StockDetail />
            </Suspense>
          }
        />
      </Routes>
    </Layout>
  );
}
