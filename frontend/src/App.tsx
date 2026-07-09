import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import StockDetail from './pages/StockDetail';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/stock/:code" element={<StockDetail />} />
      </Routes>
    </Layout>
  );
}
