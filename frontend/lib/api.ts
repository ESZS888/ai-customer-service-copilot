import { EscalationTicket, Ticket, TicketList, TicketStatus } from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

export class ApiError extends Error {
  constructor(message:string, public status:number) {super(message)}
}

export interface ChatResponse {
  request_id: string
  conversation_id: string
  reply: string
  intent: string
  thought_chain: Array<{
    agent: string
    status: 'running' | 'completed' | 'error'
    input?: string
    output?: string
    detail?: string
  }>
  escalation_ticket: EscalationTicket | null
}

export async function sendMessage(message: string, request_id: string, conversation_id: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, request_id, conversation_id, data_source:'demo' }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }))
    throw new ApiError(typeof err.detail === 'string' ? err.detail : `请求参数不正确（${res.status}）`, res.status)
  }

  return res.json()
}

export async function apiRequest<T>(path:string, init?:RequestInit):Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {...init, cache:'no-store'})
  if (!res.ok) {
    const error = await res.json().catch(()=>({detail:'无法连接后端'}))
    throw new Error(typeof error.detail === 'string' ? error.detail : `请求参数不正确（${res.status}）`)
  }
  return res.json()
}

export const listTickets = (params:URLSearchParams, signal?:AbortSignal) => apiRequest<TicketList>(`/api/tickets?${params}`, {signal})
export const getTicket = (id:string, signal?:AbortSignal) => apiRequest<Ticket>(`/api/tickets/${encodeURIComponent(id)}`, {signal})
export const updateTicket = (id:string, status:TicketStatus, note:string, version:number) => apiRequest<Ticket>(`/api/tickets/${encodeURIComponent(id)}/status`, {
  method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status,note,version}),
})
