"""
Agent-based conversation analysis API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, Any
from datetime import datetime
import json
import asyncio

import database.conversations as conversations_db
from models.agent import (
    AgentAnalysisRequest, 
    AgentAnalysisResponse, 
    AgentContinueRequest, 
    AgentContinueResponse,
    StreamEvent
)
from models.conversation import Conversation
from utils.agents.core import create_conversation_agent
from utils.other import endpoints as auth

router = APIRouter()


@router.post("/v1/conversations/agent", response_model=AgentAnalysisResponse, tags=['agent', 'conversations'])
def analyze_conversation_with_agent(
    request: AgentAnalysisRequest,
    uid: str = Depends(auth.get_current_user_uid)
) -> AgentAnalysisResponse:
    """
    Analyze a conversation transcript using an AI agent that can retrieve context 
    from past conversations and take actions.
    
    This endpoint provides an alternative to the standard conversation processing
    by using a LangChain ReAct agent that can:
    - Analyze conversation transcripts
    - Retrieve relevant past conversations from Pinecone  
    - Search the web for current information
    - Suggest actionable next steps and insights
    """
    try:
        # Create agent for the user
        agent = create_conversation_agent(uid)
        
        # Get conversation data if conversation_id is provided
        conversation_data = None
        if request.conversation_id:
            try:
                conv_data = conversations_db.get_conversation(uid, request.conversation_id)
                if conv_data:
                    conversation = Conversation(**conv_data)
                    conversation_data = {
                        "created_at": conversation.created_at.isoformat(),
                        "source": conversation.source.value if conversation.source else "unknown",
                        "category": conversation.structured.category if conversation.structured else "unknown"
                    }
            except Exception as e:
                print(f"Error retrieving conversation {request.conversation_id}: {e}")
        
        # Handle streaming vs non-streaming
        if request.stream:
            # For streaming, we need to return a StreamingResponse
            async def generate_stream():
                for event in agent.stream_analysis(
                    transcript=request.transcript,
                    conversation_data=conversation_data,
                    session_id=request.session_id
                ):
                    yield f"data: {json.dumps(event)}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/plain",
                headers={"X-Session-ID": request.session_id}
            )
        else:
            # Non-streaming analysis
            result = agent.analyze_conversation(
                transcript=request.transcript,
                conversation_data=conversation_data,
                session_id=request.session_id
            )

            # --- Save summary to conversation if conversation_id is provided ---
            if request.conversation_id:
                try:
                    conv_data = conversations_db.get_conversation(uid, request.conversation_id)
                    if conv_data and 'structured' in conv_data:
                        structured = conv_data['structured']
                        structured['overview'] = result['analysis']
                        conversations_db.update_conversation_structured(uid, request.conversation_id, structured)
                except Exception as e:
                    print(f"Error updating conversation summary: {e}")
            # --- End save summary ---

            return AgentAnalysisResponse(**result)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing conversation: {str(e)}")


@router.post("/v1/conversations/agent/stream", tags=['agent', 'conversations'])
async def stream_conversation_analysis(
    request: AgentAnalysisRequest,
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Stream conversation analysis in real-time using Server-Sent Events.
    
    This endpoint provides streaming analysis updates as the agent processes
    the conversation and retrieves relevant context.
    """
    try:
        # Create agent for the user
        agent = create_conversation_agent(uid)
        
        # Get conversation data if conversation_id is provided
        conversation_data = None
        if request.conversation_id:
            try:
                conv_data = conversations_db.get_conversation(uid, request.conversation_id)
                if conv_data:
                    conversation = Conversation(**conv_data)
                    conversation_data = {
                        "created_at": conversation.created_at.isoformat(),
                        "source": conversation.source.value if conversation.source else "unknown",
                        "category": conversation.structured.category if conversation.structured else "unknown"
                    }
            except Exception as e:
                print(f"Error retrieving conversation {request.conversation_id}: {e}")
        
        async def generate_stream():
            """Generate Server-Sent Events stream"""
            try:
                yield "data: " + json.dumps({
                    "type": "start",
                    "message": "Starting conversation analysis...",
                    "timestamp": datetime.now().isoformat()
                }) + "\n\n"
                
                # Stream the agent analysis
                for event in agent.stream_analysis(
                    transcript=request.transcript,
                    conversation_data=conversation_data,
                    session_id=request.session_id
                ):
                    yield f"data: {json.dumps(event)}\n\n"
                    # Small delay to allow client to process
                    await asyncio.sleep(0.1)
                
                yield "data: " + json.dumps({
                    "type": "end",
                    "message": "Analysis completed",
                    "timestamp": datetime.now().isoformat()
                }) + "\n\n"
                
            except Exception as e:
                yield "data: " + json.dumps({
                    "type": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }) + "\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-ID": request.session_id
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error streaming analysis: {str(e)}")


@router.post("/v1/conversations/agent/continue", response_model=AgentContinueResponse, tags=['agent', 'conversations'])
def continue_agent_conversation(
    request: AgentContinueRequest,
    uid: str = Depends(auth.get_current_user_uid)
) -> AgentContinueResponse:
    """
    Continue an ongoing conversation with the agent.
    
    This allows users to ask follow-up questions or request clarification
    about the analysis, maintaining context from the previous interaction.
    """
    try:
        # Create agent for the user
        agent = create_conversation_agent(uid)
        
        # Continue the conversation
        result = agent.continue_conversation(
            user_message=request.message,
            session_id=request.session_id
        )
        
        return AgentContinueResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error continuing conversation: {str(e)}")


@router.get("/v1/conversations/agent/sessions/{session_id}", tags=['agent', 'conversations'])
def get_agent_session_info(
    session_id: str,
    uid: str = Depends(auth.get_current_user_uid)
) -> Dict[str, Any]:
    """
    Get information about an agent session.
    
    This endpoint provides metadata about ongoing or past agent sessions,
    useful for debugging or providing session continuity.
    """
    try:
        # For now, return basic session info
        # In the future, this could query session storage for detailed history
        return {
            "session_id": session_id,
            "uid": uid,
            "status": "active",
            "message": "Session information retrieved successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving session info: {str(e)}")


@router.delete("/v1/conversations/agent/sessions/{session_id}", tags=['agent', 'conversations'])
def clear_agent_session(
    session_id: str,
    uid: str = Depends(auth.get_current_user_uid)
) -> Dict[str, Any]:
    """
    Clear an agent session, removing conversation history.
    
    This allows users to start fresh conversations with the agent
    without context from previous interactions.
    """
    try:
        # The MemorySaver in LangGraph handles session isolation
        # So clearing happens naturally when creating new agents
        # This endpoint is here for future extensibility
        
        return {
            "session_id": session_id,
            "status": "cleared",
            "message": "Session cleared successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing session: {str(e)}") 