import { Link, useLocation } from 'react-router-dom';

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <Link to="/" className="logo">
            <span className="logo-icon">📊</span>
            <h1>A股量化选股</h1>
          </Link>
          <nav>
            {!isHome && (
              <Link to="/" className="nav-link">← 返回首页</Link>
            )}
          </nav>
        </div>
      </header>
      <main className="app-main">
        {children}
      </main>
      <footer className="app-footer">
        <p>数据来源：东方财富 · akshare | 仅作参考，不构成投资建议</p>
        <p>五维因子模型：质量 35% + 分红 20% + 估值 20% + 成长 15% + 动量 10%</p>
      </footer>
    </div>
  );
}
