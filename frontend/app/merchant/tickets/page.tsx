'use client'

import {Suspense, useEffect, useState} from 'react'
import {useSearchParams} from 'next/navigation'
import {getTicket, listTickets, updateTicket} from '@/lib/api'
import {DataSource, Ticket, TicketList, TicketStatus, sourceLabels, statusLabels} from '@/lib/types'

const dateText = (value:string) => new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Hong_Kong',hour12:false})

export default function TicketsPage() {
  return <Suspense fallback={<div className="empty">正在打开工单页…</div>}><TicketRoute /></Suspense>
}

function TicketRoute() {
  const params = useSearchParams()
  return <TicketWorkspace key={params.toString()} />
}

function TicketWorkspace() {
  const params = useSearchParams()
  const initialStatus = params.get('status')
  const [source,setSource] = useState<DataSource>(params.get('data_source') === 'evaluation' ? 'evaluation' : 'demo')
  const [status,setStatus] = useState<TicketStatus | ''>(initialStatus && initialStatus in statusLabels ? initialStatus as TicketStatus : '')
  const [search,setSearch] = useState('')
  const [query,setQuery] = useState('')
  const [offset,setOffset] = useState(0)
  const [reload,setReload] = useState(0)
  const [data,setData] = useState<TicketList | null>(null)
  const [selectedId,setSelectedId] = useState(params.get('ticket') || '')
  const [ticket,setTicket] = useState<Ticket | null>(null)
  const [nextStatus,setNextStatus] = useState<TicketStatus>('open')
  const [note,setNote] = useState('')
  const [loading,setLoading] = useState(true)
  const [detailLoading,setDetailLoading] = useState(false)
  const [saving,setSaving] = useState(false)
  const [error,setError] = useState('')
  const [detailError,setDetailError] = useState('')
  const [message,setMessage] = useState('')

  useEffect(()=>{
    const controller = new AbortController()
    async function load() {
      setLoading(true); setError('')
      try {
        const params = new URLSearchParams({data_source:source,search:query,limit:'10',offset:String(offset)})
        if (status) params.set('status',status)
        setData(await listTickets(params,controller.signal))
      } catch(e) { if (!controller.signal.aborted) {setData(null); setError(e instanceof Error ? e.message : '工单加载失败')} }
      finally {if (!controller.signal.aborted) setLoading(false)}
    }
    void load()
    return ()=>controller.abort()
  },[source,status,query,offset,reload])

  useEffect(()=>{
    if (!selectedId) return
    const controller = new AbortController()
    async function load() {
      setDetailLoading(true); setDetailError(''); setTicket(null)
      try {
        const item = await getTicket(selectedId,controller.signal)
        setTicket(item); setNextStatus(item.status); setNote('')
      } catch(e) {if (!controller.signal.aborted) setDetailError(e instanceof Error ? e.message : '详情加载失败')}
      finally {if (!controller.signal.aborted) setDetailLoading(false)}
    }
    void load()
    return ()=>controller.abort()
  },[selectedId,reload])

  async function save() {
    if (!ticket || saving) return
    if (nextStatus === 'resolved' && !note.trim()) {setDetailError('标记已处理必须填写处理说明。');return}
    setSaving(true);setDetailError('');setMessage('')
    try {
      const saved = await updateTicket(ticket.ticket_id,nextStatus,note,ticket.version)
      setTicket(saved);setNote('')
      setReload(x=>x+1)
      setMessage('处理记录已保存。')
    } catch(e) {setDetailError(e instanceof Error ? e.message : '保存失败')}
    finally {setSaving(false)}
  }

  return <>
    <div className="page-heading"><div><h1>工单管理</h1><p className="muted">集中跟进买家诉求，让每一次投诉都有可追踪的记录。</p></div><button className="secondary" disabled={saving || loading} onClick={()=>setReload(x=>x+1)}>刷新数据</button></div>
    <form className="toolbar" onSubmit={e=>{e.preventDefault();setQuery(search.trim());setOffset(0);setSelectedId('');setTicket(null);setMessage('');setReload(x=>x+1)}}>
      <label className="field">数据来源<select aria-label="数据来源" value={source} disabled={saving} onChange={e=>{setSource(e.target.value as DataSource);setOffset(0);setSelectedId('');setTicket(null)}}>{Object.entries(sourceLabels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label className="field">状态筛选<select aria-label="状态筛选" value={status} disabled={saving} onChange={e=>{setStatus(e.target.value as TicketStatus | '');setOffset(0);setSelectedId('');setTicket(null);setMessage('')}}><option value="">全部状态</option>{Object.entries(statusLabels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label className="field" style={{flex:1}}>搜索工单<input value={search} maxLength={100} placeholder="工单编号、摘要或用户原话" onChange={e=>setSearch(e.target.value)} /></label>
      <button className="primary" disabled={saving}>搜索</button>
    </form>
    {source === 'evaluation' && <div className="notice">当前为评测数据，来自自动化验收请求；不代表真实买家咨询。</div>}
    {error && <div role="alert" className="notice error">{error}，请检查后端并刷新。</div>}
    <div className="ticket-grid">
      <section className="panel" aria-busy={loading}><h2>工单列表 <span className="muted">{data ? `共 ${data.total} 条` : ''}</span></h2>
        {loading ? <div className="empty">正在读取工单…</div> : data?.items.length ? <div className="table-wrap"><table><thead><tr><th>诉求摘要 / 编号</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{data.items.map(item=><tr className={`ticket-row ${selectedId===item.ticket_id?'active':''}`} key={item.ticket_id}>
          <td><button className="text-left hover:underline" disabled={saving} onClick={()=>{setSelectedId(item.ticket_id);setMessage('')}}>{item.ticket_summary}<span className="ticket-code">{item.ticket_id}</span></button></td><td><span className={`badge ${item.status}`}>{statusLabels[item.status]}</span></td><td className="muted">{dateText(item.created_at)}</td>
        </tr>)}</tbody></table></div> : <div className="empty">{error ? '暂时无法读取列表。' : '暂无符合条件的工单。可在买家客服页提交演示投诉。'}</div>}
        <div className="pager"><button className="secondary" disabled={!offset || loading || saving} onClick={()=>setOffset(Math.max(0,offset-10))}>上一页</button><span>第 {Math.floor(offset/10)+1} 页</span><button className="secondary" disabled={!data || offset+10>=data.total || loading || saving} onClick={()=>setOffset(offset+10)}>下一页</button></div>
      </section>
      <section className="panel" aria-busy={detailLoading}><h2>工单详情</h2>
        {detailError && <div role="alert" className="notice error">{detailError}</div>}
        {message && <div role="status" className="notice success">{message}</div>}
        {detailLoading ? <div className="empty">正在读取详情…</div> : ticket ? <>
          <span className={`badge ${ticket.status}`}>{statusLabels[ticket.status]}</span><span className="muted ml-3">{sourceLabels[ticket.data_source]} · 版本 {ticket.version}</span>
          <div className="ticket-code mt-3">{ticket.ticket_id}</div>
          <dl className="details-meta"><div><dt>问题类别</dt><dd>{ticket.issue_category}</dd></div><div><dt>紧急程度</dt><dd>{{high:'高',medium:'中',low:'低'}[ticket.urgency] || ticket.urgency}</dd></div><div><dt>关联订单（用户提供，未核验归属）</dt><dd>{ticket.order_ids.join('、') || '未提供'}</dd></div><div><dt>最后更新 · UTC+8</dt><dd>{dateText(ticket.updated_at)}</dd></div></dl>
          <div className="muted">买家原始诉求 · 内容待核实</div><div className="content-box">{ticket.original_message}</div>
          <div className="muted">AI 提取摘要 · 仅供处理参考</div><div className="content-box">{ticket.ticket_summary}<br/>{ticket.detail}</div>
          {ticket.processing_note && <><div className="muted">最新处理说明</div><div className="content-box">{ticket.processing_note}</div></>}
          <form className="detail-form" onSubmit={e=>{e.preventDefault();void save()}}>
            <label className="field">更新状态<select value={nextStatus} disabled={saving} onChange={e=>setNextStatus(e.target.value as TicketStatus)}>{(ticket.status === 'open' ? ['open','in_progress'] : ticket.status === 'in_progress' ? ['in_progress','resolved'] : ['resolved','in_progress']).map(k=><option key={k} value={k}>{statusLabels[k as TicketStatus]}</option>)}</select></label>
            <label className="field">处理说明 {nextStatus === 'resolved' || ticket.status === 'resolved' ? '（必填）' : '（可选）'}<textarea maxLength={2000} required={nextStatus === 'resolved' || ticket.status === 'resolved'} value={note} disabled={saving} onChange={e=>setNote(e.target.value)} placeholder="记录核实情况、处理动作和后续安排。请勿填写密钥或个人敏感信息。" /></label>
            <p className="muted">标记已处理只记录商家处理结果，不触发自动退款或人工通知。</p>
            <button className="primary" disabled={saving}>{saving?'保存中…':'保存处理记录'}</button>
          </form>
          <div className="timeline"><h2>处理记录</h2><ul>{ticket.history?.map((entry,index)=><li key={index}><div>{entry.event_type === 'ticket_created' ? '工单创建 · 待处理' : `${entry.from_status ? statusLabels[entry.from_status] : ''} → ${entry.to_status ? statusLabels[entry.to_status] : ''}`}</div>{entry.note && <div className="whitespace-pre-wrap break-words">{entry.note}</div>}<div className="muted">{dateText(entry.occurred_at)}</div></li>)}</ul></div>
        </> : <div className="empty">选择左侧工单，查看诉求并更新处理状态。</div>}
      </section>
    </div>
  </>
}
