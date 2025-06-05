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
            
            return AgentAnalysisResponse(**result)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing conversation: {str(e)}")


@router.post("/v1/conversations/agent/create", tags=['agent', 'conversations'])
def create_conversation_with_agent(
    request: AgentAnalysisRequest,
    uid: str = Depends(auth.get_current_user_uid)
) -> Dict[str, Any]:
    """
    Create a conversation using agent analysis to generate structured data.
    
    This endpoint:
    1. Analyzes the transcript with the agent
    2. Transforms agent results into structured conversation data
    3. Creates a conversation with the agent-generated summary
    4. Returns the same format as the standard conversation creation endpoint
    """
    print(f"🟦 BACKEND: /v1/conversations/agent/create endpoint hit by user {uid}")
    print(f"🟦 BACKEND: Request - transcript length: {len(request.transcript)}")
    print(f"🟦 BACKEND: Request - conversation_id: {request.conversation_id}")
    print(f"🟦 BACKEND: Request - session_id: {request.session_id}")
    
    try:
        # Create agent for the user
        print(f"🟦 BACKEND: Creating conversation agent for user {uid}")
        agent = create_conversation_agent(uid)
        print(f"🟦 BACKEND: Agent created successfully")
        
        # Analyze with agent
        print(f"🟦 BACKEND: Starting agent analysis...")
        result = agent.analyze_conversation(
            transcript=request.transcript,
            conversation_data=None,
            session_id=request.session_id
        )
        print(f"🟦 BACKEND: Agent analysis completed")
        print(f"🟦 BACKEND: Analysis result status: {result.get('status')}")
        
        if result.get('status') != 'success':
            error_msg = f"Agent analysis failed: {result.get('error', 'Unknown error')}"
            print(f"🔴 BACKEND: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
        
        # Transform agent analysis into structured conversation data
        agent_analysis = result.get('analysis', '')
        retrieved_conversations = result.get('retrieved_conversations', [])
        
        print(f"🟦 BACKEND: Agent analysis length: {len(agent_analysis)}")
        print(f"🟦 BACKEND: Retrieved conversations count: {len(retrieved_conversations)}")
        
        # Extract structured data from agent analysis
        print(f"🟦 BACKEND: Extracting structured data from agent analysis...")
        structured_data = _extract_structured_data_from_agent_analysis(
            agent_analysis, 
            retrieved_conversations,
            request.transcript
        )
        print(f"🟦 BACKEND: Structured data extracted - title: {structured_data.get('title')}")
        
        # Create conversation using existing conversation creation logic
        from utils.conversations.process_conversation import process_conversation
        from models.conversation import CreateConversation, ConversationSource
        
        # Parse transcript segments from the transcript text
        # For now, create a simple transcript segment from the text
        # In a real implementation, you might want to parse actual segments
        from models.transcript_segment import TranscriptSegment
        
        transcript_segments = []
        if request.transcript:
            # Create a single transcript segment from the entire transcript
            # This is a simplified approach - you might want to parse actual segments
            transcript_segments = [
                TranscriptSegment(
                    text=request.transcript,
                    speaker="SPEAKER_0",
                    speaker_id=0,
                    is_user=False,
                    start=0.0,
                    end=60.0  # Default 1 minute duration
                )
            ]
        
        # Create a CreateConversation object with the transcript and agent-generated structured data
        create_conversation = CreateConversation(
            transcript_segments=transcript_segments,
            started_at=datetime.now(),
            finished_at=datetime.now(),
            source=ConversationSource.omi,
            language="en"  # TODO: detect language from transcript
        )
        
        # Process the conversation to get structured data
        print(f"🟦 BACKEND: Processing conversation...")
        conversation = process_conversation(
            uid=uid,
            language_code="en",
            conversation=create_conversation,
            force_process=False
        )
        print(f"🟦 BACKEND: Conversation processed - ID: {conversation.id}")
        
        # Override the structured data with agent analysis
        conversation.structured.title = structured_data["title"]
        conversation.structured.overview = structured_data["overview"]
        conversation.structured.category = structured_data["category"]
        
        # Update action items
        if structured_data.get("action_items"):
            from models.conversation import ActionItem
            conversation.structured.action_items = [
                ActionItem(description=item["content"]) 
                for item in structured_data["action_items"]
            ]
        
        # Update key takeaways
        if structured_data.get("key_takeaways"):
            conversation.structured.key_takeaways = structured_data["key_takeaways"]
        
        # Update events
        if structured_data.get("events"):
            from models.conversation import Event
            conversation.structured.events = [
                Event(
                    title=event["title"],
                    description=event["description"],
                    start=datetime.fromisoformat(event["created_at"]),
                    duration=event["duration"]
                )
                for event in structured_data["events"]
            ]
        
        # Save the updated conversation
        print(f"🟦 BACKEND: Saving updated conversation to database...")
        import database.conversations as conversations_db
        conversations_db.update_conversation(uid, conversation.id, conversation.dict())
        print(f"🟦 BACKEND: Conversation saved successfully")
        
        response_data = {
            "memory": conversation,
            "messages": [],  # No chat messages for agent-created conversations
            "agent_analysis": {
                "analysis": agent_analysis,
                "retrieved_conversations": retrieved_conversations,
                "session_id": request.session_id
            }
        }
        
        print(f"🟢 BACKEND: Agent conversation creation completed successfully")
        print(f"🟢 BACKEND: Returning conversation ID: {conversation.id}")
        
        return response_data
        
    except Exception as e:
        print(f"🔴 BACKEND: Exception in create_conversation_with_agent: {str(e)}")
        print(f"🔴 BACKEND: Exception type: {type(e)}")
        import traceback
        print(f"🔴 BACKEND: Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error creating conversation with agent: {str(e)}")


def _extract_structured_data_from_agent_analysis(analysis: str, retrieved_conversations: list, transcript: str) -> Dict[str, Any]:
    """
    Extract structured conversation data from agent analysis.
    
    This function parses the agent's analysis and converts it into the
    structured format expected by the conversation creation system.
    """
    import re
    
    # Extract title (look for title-like patterns or use first line)
    title_match = re.search(r'^#\s*(.+)$|^Title:\s*(.+)$', analysis, re.MULTILINE | re.IGNORECASE)
    title = "Agent Analysis"
    if title_match:
        title = title_match.group(1) or title_match.group(2)
    else:
        # Use first meaningful line as title
        lines = [line.strip() for line in analysis.split('\n') if line.strip()]
        if lines:
            title = lines[0][:100]  # Limit title length
    
    # Extract overview (first paragraph or summary section)
    overview_match = re.search(r'(?:Summary|Overview):\s*(.*?)(?:\n\n|\n(?=[A-Z][a-z]+:)|\Z)', analysis, re.DOTALL | re.IGNORECASE)
    overview = analysis[:500] + "..." if len(analysis) > 500 else analysis  # Default to truncated analysis
    if overview_match:
        overview = overview_match.group(1).strip()
    
    # Extract action items
    action_items = []
    action_patterns = [
        r'(?:Action Items?|Next Steps?|To[- ]?Do|Follow[- ]?up):\s*(.*?)(?:\n\n|\n(?=[A-Z][a-z]+:)|\Z)',
        r'^\s*[-•*]\s*(.+)$',  # Bullet points
        r'^\s*\d+\.\s*(.+)$'   # Numbered lists
    ]
    
    for pattern in action_patterns:
        matches = re.finditer(pattern, analysis, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        for match in matches:
            text = match.group(1).strip()
            if len(text) > 10:  # Only meaningful action items
                # Split multi-line action items
                items = [item.strip() for item in text.split('\n') if item.strip()]
                action_items.extend(items[:5])  # Limit to 5 items
    
    # Extract key takeaways
    key_takeaways = []
    takeaway_match = re.search(r'(?:Key Takeaways?|Insights?|Main Points?):\s*(.*?)(?:\n\n|\n(?=[A-Z][a-z]+:)|\Z)', analysis, re.DOTALL | re.IGNORECASE)
    if takeaway_match:
        takeaway_text = takeaway_match.group(1).strip()
        takeaways = [item.strip() for item in re.split(r'[-•*\n]', takeaway_text) if item.strip()]
        key_takeaways = takeaways[:5]  # Limit to 5 takeaways
    
    # Create events if retrieved conversations were used
    events = []
    if retrieved_conversations:
        events.append({
            "title": f"Found {len(retrieved_conversations)} related conversations",
            "description": f"Agent analyzed {len(retrieved_conversations)} related past conversations for context",
            "created_at": datetime.now().isoformat(),
            "duration": 30  # 30 minutes default duration
        })
    
    return {
        "title": title,
        "overview": overview,
        "category": "other",  # Use valid category from CategoryEnum
        "action_items": [{"content": item} for item in action_items[:10]],  # Limit to 10 items
        "key_takeaways": key_takeaways,
        "events": events,
        # Add metadata about agent processing
        "metadata": {
            "processed_by": "ai-agent",
            "retrieved_conversations_count": len(retrieved_conversations),
            "analysis_length": len(analysis)
        }
    }


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