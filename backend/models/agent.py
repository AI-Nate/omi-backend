"""
Pydantic models for agent API requests and responses
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


class AgentAnalysisRequest(BaseModel):
    """Request model for agent conversation analysis"""
    transcript: str = Field(..., description="The conversation transcript to analyze")
    conversation_id: Optional[str] = Field(None, description="Optional conversation ID for context")
    session_id: Optional[str] = Field("default", description="Session ID for maintaining conversation context")
    stream: Optional[bool] = Field(False, description="Whether to stream the response")
    
    class Config:
        schema_extra = {
            "example": {
                "transcript": "I had a meeting with John about the new project. We discussed the timeline and budget constraints.",
                "conversation_id": "conv_123",
                "session_id": "user_session_1",
                "stream": False
            }
        }


class AgentContinueRequest(BaseModel):
    """Request model for continuing a conversation with the agent"""
    message: str = Field(..., description="User's follow-up message or question")
    session_id: Optional[str] = Field("default", description="Session ID to maintain context")
    
    class Config:
        schema_extra = {
            "example": {
                "message": "Can you give me more specific action items for this project?",
                "session_id": "user_session_1"
            }
        }


class RetrievedConversation(BaseModel):
    """Model for retrieved conversation summary"""
    id: str
    title: str
    overview: str
    created_at: str
    category: Optional[str]
    action_items: List[str]
    transcript_preview: str


class AgentAnalysisResponse(BaseModel):
    """Response model for agent conversation analysis"""
    analysis: str = Field(..., description="The agent's analysis of the conversation")
    session_id: str = Field(..., description="Session ID for continued conversations")
    timestamp: str = Field(..., description="Timestamp of the analysis")
    status: str = Field(..., description="Status of the analysis (success/error)")
    error: Optional[str] = Field(None, description="Error message if status is error")
    retrieved_conversations: Optional[List[RetrievedConversation]] = Field(
        None, description="Conversations retrieved during analysis"
    )
    urgency_assessment: Optional[Dict[str, Any]] = Field(
        None, description="Urgency assessment for the conversation including level, reasoning, action_required, and time_sensitivity"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "analysis": "Based on your conversation with John about the new project, I found several key insights...",
                "session_id": "user_session_1",
                "timestamp": "2024-01-15T10:30:00Z",
                "status": "success",
                "urgency_assessment": {
                    "level": "medium",
                    "reasoning": "Important project planning but no immediate deadlines",
                    "action_required": False,
                    "time_sensitivity": "within 1 week"
                },
                "retrieved_conversations": [
                    {
                        "id": "conv_456",
                        "title": "Previous project planning meeting",
                        "overview": "Discussion about project management best practices",
                        "created_at": "2024-01-10T14:20:00Z",
                        "category": "work",
                        "action_items": ["Review timeline", "Set up weekly check-ins"],
                        "transcript_preview": "In our last project meeting we discussed..."
                    }
                ]
            }
        }


class AgentContinueResponse(BaseModel):
    """Response model for continuing conversation with agent"""
    response: str = Field(..., description="The agent's response to the user's message")
    session_id: str = Field(..., description="Session ID for the conversation")
    timestamp: str = Field(..., description="Timestamp of the response")
    status: str = Field(..., description="Status of the response (success/error)")
    error: Optional[str] = Field(None, description="Error message if status is error")
    
    class Config:
        schema_extra = {
            "example": {
                "response": "Based on your project discussion, here are specific action items you should prioritize...",
                "session_id": "user_session_1",
                "timestamp": "2024-01-15T10:35:00Z",
                "status": "success"
            }
        }


class StreamEvent(BaseModel):
    """Model for streaming events"""
    type: str = Field(..., description="Type of event (message, completion, error)")
    content: Optional[str] = Field(None, description="Content of the message")
    role: Optional[str] = Field(None, description="Role of the message sender")
    timestamp: str = Field(..., description="Timestamp of the event")
    error: Optional[str] = Field(None, description="Error message if type is error")
    
    class Config:
        schema_extra = {
            "example": {
                "type": "message",
                "content": "I'm analyzing your conversation...",
                "role": "assistant",
                "timestamp": "2024-01-15T10:30:15Z"
            }
        } 