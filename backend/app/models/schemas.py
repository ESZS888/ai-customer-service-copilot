from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import TypedDict, Optional, Literal
import re


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    data_source: Literal['demo', 'evaluation'] = 'demo'

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('message must not be blank')
        return value


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['open', 'in_progress', 'resolved']
    note: str = Field(default='', max_length=2000)
    version: int = Field(ge=1)

    @field_validator('note')
    @classmethod
    def trim_note(cls, value):
        return value.strip()


class SSEEvent(BaseModel):
    event: str = Field(..., pattern=r"^(thought|tool_call|message|error|done)$")
    data: dict


class AgentState(TypedDict):
    user_message: str
    messages: list
    intent: Optional[str]
    retrieved_docs: list
    tool_results: list
    escalation_ticket: Optional[dict]
    final_response: Optional[str]
    thought_chain: list
    answer: Optional[str]
    sources: list
    reason_code: Optional[str]


class RouterOutput(BaseModel):
    intent: Literal['order_query', 'product_inquiry', 'complaint', 'general']
    reason: str = ''


class OrderArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: str

    @field_validator('order_id')
    @classmethod
    def normalize(cls, value):
        value = value.strip().upper()
        if not re.fullmatch(r'ORD-\d+', value):
            raise ValueError('invalid order identifier')
        return value


class ProductArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: str

    @field_validator('product_id')
    @classmethod
    def normalize(cls, value):
        value = value.strip().upper()
        if not re.fullmatch(r'P\d+', value):
            raise ValueError('invalid product identifier')
        return value


class PolicyArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: Literal['electronics', 'clothing', 'books']


class TicketDraft(BaseModel):
    model_config = ConfigDict(extra='ignore')
    ticket_summary: str = Field(min_length=1, max_length=100)
    issue_category: str = Field(default='售后诉求', max_length=50)
    detail: str = Field(default='', max_length=2000)
    urgency: Literal['high', 'medium', 'low'] = 'medium'
    suggested_action: str = Field(default='请用户自行联系商家人工客服进一步处理。', max_length=300)
