import Link from 'next/link'
import './merchant.css'

export default function MerchantLayout({children}:{children:React.ReactNode}) {
  return <div className="merchant-shell">
    <header className="merchant-header">
      <Link href="/merchant/dashboard" className="brand"><span className="brand-icon">C</span><span>Customer Service Copilot<small>商家工作台 · 单店本机演示</small></span></Link>
      <nav aria-label="商家导航"><Link href="/merchant/tickets">工单管理</Link><Link href="/merchant/dashboard">运营概览</Link><Link href="/">买家客服 ↗</Link></nav>
    </header>
    <main className="merchant-main">{children}</main>
    <footer className="merchant-footer">商品与订单为演示资料；工单与指标来自本机实际记录。工单已处理不代表退款到账或用户满意。</footer>
  </div>
}
