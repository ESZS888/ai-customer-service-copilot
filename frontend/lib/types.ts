export interface AgentThought {
  agent: string
  status: 'running' | 'completed' | 'error'
  input?: string
  output?: string
  detail?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'agent'
  content: string
  thoughts?: AgentThought[]
  ticket?: EscalationTicket | null
}

export interface EscalationTicket {
  ticket_id: string
  ticket_summary: string
  issue_category: string
  urgency: string
  detail: string
  suggested_action: string
  timestamp: string
  is_persisted?: boolean
  status?: TicketStatus
}

export type TicketStatus = 'open' | 'in_progress' | 'resolved'
export type DataSource = 'demo' | 'evaluation'
export const statusLabels: Record<TicketStatus, string> = {open:'待处理', in_progress:'处理中', resolved:'已处理'}
export const sourceLabels: Record<DataSource, string> = {demo:'演示交互', evaluation:'评测数据'}

export interface Ticket extends EscalationTicket {
  status: TicketStatus
  data_source: DataSource
  order_ids: string[]
  conversation_id: string
  source_request_id: string
  original_message: string
  processing_note: string
  version: number
  created_at: string
  updated_at: string
  resolved_at: string | null
  history?: Array<{event_type:string; occurred_at:string; from_status?:TicketStatus; to_status?:TicketStatus; note?:string}>
}

export interface TicketList { items:Ticket[]; total:number; limit:number; offset:number; data_source:DataSource }

export interface Overview {
  data_source:DataSource
  timezone:string
  requests:number
  conversations:number
  request_status:Record<'processing'|'succeeded'|'failed'|'interrupted',number>
  completed_requests:number
  failed_requests:number
  failure_rate:number | null
  intents:Record<string,number>
  tickets_created:number
  ticket_status:Record<TicketStatus,number>
  pending_tickets_all_time:number
  latency:Record<'success'|'failure',{samples:number;median_ms:number | null}>
  failure_reasons:Array<{reason_code:string;count:number}>
}

export interface RequestRecord {
  request_id:string;conversation_id:string;data_source:DataSource;message:string
  status:'processing'|'succeeded'|'failed'|'interrupted'
  business_intent:string | null;reason_code:string | null;created_at:string;latency_ms:number | null
}
export interface RequestList {items:RequestRecord[];total:number;limit:number;offset:number}
