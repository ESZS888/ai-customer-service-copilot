'use client'

import {useEffect, useState} from 'react'
import Link from 'next/link'
import {apiRequest} from '@/lib/api'
import {DataSource, Overview, RequestList, sourceLabels, statusLabels, TicketStatus} from '@/lib/types'

const intentLabels:Record<string,string> = {product:'商品咨询',order:'订单查询',logistics:'物流 / 复合查询',complaint:'投诉 / 售后申请',policy:'政策咨询',general:'一般 / 其他',unknown:'尚未分类'}
const requestLabels = {succeeded:'执行成功',failed:'失败',interrupted:'异常中断',processing:'处理中'}
const reasonLabels:Record<string,string> = {agent_request_failed:'模型或工作流失败',storage_commit_failed:'结果保存失败',storage_unavailable:'存储不可用',service_restarted:'服务重启中断'}
const seconds = (ms:number | null) => ms === null ? '暂无样本' : `${(ms/1000).toFixed(2)} 秒`

export default function DashboardPage() {
  const [source,setSource] = useState<DataSource>('demo')
  const [start,setStart] = useState('')
  const [end,setEnd] = useState('')
  const [range,setRange] = useState({start:'',end:''})
  const [reload,setReload] = useState(0)
  const [overview,setOverview] = useState<Overview | null>(null)
  const [requests,setRequests] = useState<RequestList | null>(null)
  const [failuresOnly,setFailuresOnly] = useState(true)
  const [offset,setOffset] = useState(0)
  const [loading,setLoading] = useState(true)
  const [error,setError] = useState('')

  useEffect(()=>{
    const controller = new AbortController()
    async function load() {
      setLoading(true);setError('')
      try {
        const params = new URLSearchParams({data_source:source})
        if (range.start) params.set('start_date',range.start)
        if (range.end) params.set('end_date',range.end)
        const detailParams = new URLSearchParams(params)
        detailParams.set('failures_only',String(failuresOnly));detailParams.set('limit','10');detailParams.set('offset',String(offset))
        const [summary,detail] = await Promise.all([
          apiRequest<Overview>(`/api/analytics/overview?${params}`,{signal:controller.signal}),
          apiRequest<RequestList>(`/api/analytics/requests?${detailParams}`,{signal:controller.signal}),
        ])
        setOverview(summary);setRequests(detail)
      } catch(e) {if (!controller.signal.aborted) {setOverview(null);setRequests(null);setError(e instanceof Error ? e.message : '统计读取失败')}}
      finally {if (!controller.signal.aborted) setLoading(false)}
    }
    void load()
    return ()=>controller.abort()
  },[source,range,reload,failuresOnly,offset])

  return <>
    <div className="page-heading"><div><h1>运营概览</h1><p className="muted">从每一次咨询和处理记录中，发现需要关注的问题。</p></div><button className="secondary" disabled={loading} onClick={()=>setReload(x=>x+1)}>刷新统计</button></div>
    <form className="toolbar" onSubmit={e=>{e.preventDefault();setOffset(0);setRange({start,end});setReload(x=>x+1)}}>
      <label className="field">数据来源<select value={source} onChange={e=>{setSource(e.target.value as DataSource);setOffset(0)}}>{Object.entries(sourceLabels).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></label>
      <label className="field">开始日期<input type="date" value={start} max={end || undefined} onChange={e=>setStart(e.target.value)} /></label>
      <label className="field">结束日期<input type="date" value={end} min={start || undefined} onChange={e=>setEnd(e.target.value)} /></label>
      <button className="primary" disabled={loading}>应用日期</button><span className="muted">UTC+8 · 日期含首尾，留空查看全部</span>
    </form>
    <div className="notice">{source === 'demo' ? '演示交互：本机实际发起的演示请求，商品与订单为模拟资料。' : '评测数据：自动化案例的实际请求记录，与演示交互分别统计。'} 当前日期范围：{range.start || '最早'} 至 {range.end || '最新'}。统计按请求接收时间，不按完成时间。</div>
    {error && <div role="alert" className="notice error">{error}。请检查后端并刷新统计。</div>}
    {loading ? <div role="status" className="panel empty">正在从数据库读取统计…</div> : overview && <>
      <div className="metric-grid">
        <Metric label="咨询量" value={overview.requests} detail={`有效唯一请求 · 成功 ${overview.request_status.succeeded} / 处理中 ${overview.request_status.processing}`} />
        <Metric label="独立会话数" value={overview.conversations} detail="按会话编号去重，不等于独立买家数" />
        <Metric label="当前待处理工单 · 全量" value={overview.pending_tickets_all_time} detail="全部日期的待处理 + 处理中" />
        <Metric label="请求失败率" value={overview.failure_rate === null ? '—' : `${(overview.failure_rate*100).toFixed(1)}%`} detail={`失败及中断 ${overview.failed_requests} / 终态请求 ${overview.completed_requests}`} />
      </div>
      <div className="chart-grid">
        <section className="panel"><h2>咨询意图分布</h2><p className="muted">按现有路由及明确物流 / 政策关键词归类；每个请求计一次。</p>
          {Object.keys(overview.intents).length ? Object.entries(overview.intents).sort((a,b)=>b[1]-a[1]).map(([name,count])=><div className="bar-row" key={name}><span>{intentLabels[name] || name}</span><div className="bar-track"><div className="bar-fill" style={{width:`${overview.requests ? count/overview.requests*100 : 0}%`}} /></div><span className="text-right">{count} 次</span></div>) : <div className="empty">暂无咨询记录。</div>}
        </section>
        <section className="panel"><h2>期间新建工单 · 当前状态</h2><p className="muted">所选日期创建 {overview.tickets_created} 条工单；状态随最新处理结果更新。</p>
          <div className="status-summary">{Object.entries(overview.ticket_status).map(([key,count])=><Link key={key} href={`/merchant/tickets?status=${key}&data_source=${source}`}><strong>{count}</strong><span className={`badge ${key}`}>{statusLabels[key as TicketStatus]}</span></Link>)}</div>
          <p className="muted">点击进入该状态的全量工单列表，工单页不限定创建日期。</p>
        </section>
        <section className="panel"><h2>响应耗时 · 中位数</h2><div className="details-meta"><div><dt>执行成功</dt><dd className="text-xl font-semibold">{seconds(overview.latency.success.median_ms)}</dd><p className="muted">{overview.latency.success.samples} 个有耗时样本</p></div><div><dt>失败 / 异常中断</dt><dd className="text-xl font-semibold">{seconds(overview.latency.failure.median_ms)}</dd><p className="muted">{overview.latency.failure.samples} 个有耗时样本</p></div></div><p className="muted">包含模型和执行耗时，统计至结果保存前；服务中断可能没有完整耗时。执行成功不等于问题已解决。</p></section>
        <section className="panel"><h2>失败原因</h2>{overview.failure_reasons.length ? overview.failure_reasons.map(item=><div className="flex justify-between py-3 text-xs" key={item.reason_code}><span>{reasonLabels[item.reason_code] || item.reason_code}</span><strong>{item.count} 次</strong></div>) : <div className="empty">当前范围没有失败或中断记录。</div>}<p className="muted">处理中请求单独统计；缺少订单信息等业务追问不算系统失败。</p></section>
      </div>
      <section className="panel"><div className="page-heading"><div><h2>请求明细</h2><p className="muted">查看问题文本、执行状态和错误类别。共 {requests?.total ?? 0} 条符合条件。</p></div><label className="field">显示范围<select value={failuresOnly?'failed':'all'} onChange={e=>{setFailuresOnly(e.target.value==='failed');setOffset(0)}}><option value="failed">仅失败 / 中断</option><option value="all">全部请求</option></select></label></div>
        {requests?.items.length ? <div className="table-wrap"><table><thead><tr><th>问题 / 请求编号</th><th>执行状态</th><th>问题类型 / 原因</th><th>接收时间 · UTC+8</th><th>耗时</th></tr></thead><tbody>{requests.items.map(item=><tr key={item.request_id}><td className="max-w-sm break-words">{item.message}<span className="ticket-code">{item.request_id}</span></td><td>{requestLabels[item.status]}</td><td>{intentLabels[item.business_intent || 'unknown'] || item.business_intent}<div className="error-code">{reasonLabels[item.reason_code || ''] || item.reason_code || '—'}</div></td><td className="muted">{new Date(item.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Hong_Kong',hour12:false})}</td><td>{seconds(item.latency_ms)}</td></tr>)}</tbody></table></div> : <div className="empty">暂无符合条件的请求。</div>}
        <div className="pager"><button className="secondary" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-10))}>上一页</button><span>第 {Math.floor(offset/10)+1} 页</span><button className="secondary" disabled={!requests || offset+10>=requests.total} onClick={()=>setOffset(offset+10)}>下一页</button></div>
      </section>
    </>}
  </>
}

function Metric({label,value,detail}:{label:string;value:number|string;detail:string}) {
  return <section className="panel"><div className="metric-label">{label}</div><div className="metric-value">{value}</div><p className="muted">{detail}</p></section>
}
