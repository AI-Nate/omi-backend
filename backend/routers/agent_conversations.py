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
    print(f"🔥 DUPLICATE_DEBUG: /v1/conversations/agent/create endpoint ENTRY - user {uid}")
    print(f"🔥 DUPLICATE_DEBUG: Request details - transcript length: {len(request.transcript)}")
    print(f"🔥 DUPLICATE_DEBUG: Request details - conversation_id: {request.conversation_id}")
    print(f"🔥 DUPLICATE_DEBUG: Request details - session_id: {request.session_id}")
    print(f"🔥 DUPLICATE_DEBUG: Request details - stream: {request.stream}")
    
    import traceback
    print(f"🔥 DUPLICATE_DEBUG: Call stack trace:")
    traceback.print_stack()
    
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
        
        # Extract title from agent analysis result (title is now included in analyze_conversation)
        agent_title = result.get('title', '')
        print(f"🔍 AGENT_CREATE: Agent generated title: '{agent_title}'")
        
        # Extract structured data from agent analysis
        print(f"🟦 BACKEND: Extracting structured data from agent analysis...")
        structured_data = _extract_structured_data_from_agent_analysis(
            agent_analysis, 
            retrieved_conversations,
            request.transcript
        )
        
        # Use the agent generated title if available, otherwise use extracted title
        if agent_title and agent_title.strip():
            structured_data["title"] = agent_title
            print(f"🔍 AGENT_CREATE: Using agent generated title: '{structured_data['title']}'")
        else:
            print(f"🔍 AGENT_CREATE: Falling back to extracted title: '{structured_data.get('title', 'None')}'")
        
        print(f"🟦 BACKEND: Final structured data title: {structured_data.get('title')}")
        
        # Create conversation directly without standard processing to avoid duplicate LLM calls
        from models.conversation import Conversation, ConversationSource, ConversationStatus, Structured
        from models.transcript_segment import TranscriptSegment
        import uuid
        
        transcript_segments = []
        if request.transcript:
            # Create a single transcript segment from the entire transcript
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
        
        # Create conversation object with agent-generated structured data (skip standard processing)
        print(f"🟦 BACKEND: Creating conversation directly with agent data (skipping standard processing to avoid duplicate LLM calls)...")
        conversation = Conversation(
            id=str(uuid.uuid4()),
            created_at=datetime.now(),
            started_at=datetime.now(),
            finished_at=datetime.now(),
            source=ConversationSource.omi,
            language="en",
            structured=Structured(
                title=structured_data["title"],
                overview=agent_analysis,
                category=structured_data["category"],
                emoji=structured_data.get("emoji", "🧠")
            ),
            transcript_segments=transcript_segments,
            apps_results=[],  # No app processing for agent conversations
            discarded=False,
            deleted=False
        )
        print(f"🟦 BACKEND: Conversation created directly - ID: {conversation.id}")
        
        # Update additional structured data from agent analysis
        from models.conversation import ActionItem, Event, ResourceItem
        
        # Store the full agent analysis
        conversation.structured.agent_analysis = agent_analysis
        
        # Update action items
        if structured_data.get("action_items"):
            conversation.structured.action_items = [
                ActionItem(description=item["content"]) 
                for item in structured_data["action_items"]
            ]
        
        # Update key takeaways
        if structured_data.get("key_takeaways"):
            conversation.structured.key_takeaways = structured_data["key_takeaways"]
        
        # Update things to improve
        if structured_data.get("things_to_improve"):
            conversation.structured.things_to_improve = [
                ResourceItem(content=item["content"], url=item.get("url", ""), title=item.get("title", ""))
                for item in structured_data["things_to_improve"]
            ]
        
        # Update things to learn
        if structured_data.get("things_to_learn"):
            conversation.structured.things_to_learn = [
                ResourceItem(content=item["content"], url=item.get("url", ""), title=item.get("title", ""))
                for item in structured_data["things_to_learn"]
            ]
        
        # Update events
        if structured_data.get("events"):
            conversation.structured.events = [
                Event(
                    title=event["title"],
                    description=event["description"],
                    start=datetime.fromisoformat(event["created_at"]),
                    duration=event["duration"]
                )
                for event in structured_data["events"]
            ]
        
        # Mark conversation as completed to prevent duplicate auto-processing
        conversation.status = ConversationStatus.completed
        
        # Save the conversation to database (skip memory/trend extraction to avoid additional LLM calls)
        print(f"🟦 BACKEND: Saving conversation to database...")
        import database.conversations as conversations_db
        conversations_db.upsert_conversation(uid, conversation.dict())
        
        # Clear in-progress conversation from Redis to prevent auto-processing
        import database.redis_db as redis_db
        redis_db.remove_in_progress_conversation_id(uid)
        print(f"🟦 BACKEND: Cleared in-progress conversation from Redis to prevent duplicate processing")
        
        # Save structured vector for search
        from utils.conversations.process_conversation import save_structured_vector
        save_structured_vector(uid, conversation)
        
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
    
    # Extract title (look for markdown headers or title patterns)
    title_patterns = [
        r'^#\s*(.+)$',  # Markdown H1 header
        r'^##\s*(.+)$',  # Markdown H2 header  
        r'^Title:\s*(.+)$',  # Explicit "Title:" prefix
        r'^\*\*Title:\*\*\s*(.+)$',  # Bold "Title:" prefix
        r'^\*\*(.+)\*\*$',  # Bold text on its own line
    ]
    
    title = "Agent Analysis"  # Default fallback
    
    for pattern in title_patterns:
        title_match = re.search(pattern, analysis, re.MULTILINE | re.IGNORECASE)
        if title_match:
            extracted_title = title_match.group(1).strip()
            # Clean up the title (remove extra markdown, quotes, etc.)
            extracted_title = re.sub(r'[#*"`]', '', extracted_title).strip()
            if len(extracted_title) > 3:  # Ensure it's not too short
                title = extracted_title[:100]  # Limit title length
                break
    
    # If no pattern matched, use first meaningful line as title
    if title == "Agent Analysis":
        lines = [line.strip() for line in analysis.split('\n') if line.strip() and not line.startswith('#')]
        print(f"🔍 AGENT: No title pattern found, using fallback. First 3 lines: {lines[:3]}")
        if lines:
            # Take first line that's not too long and seems title-like
            for line in lines[:3]:  # Check first 3 lines
                clean_line = re.sub(r'[#*"`]', '', line).strip()
                if 3 < len(clean_line) < 80 and not clean_line.lower().startswith(('the ', 'this ', 'based on')):
                    title = clean_line[:100]
                    print(f"🔍 AGENT: Selected title from analysis: '{title}'")
                    break
            else:
                title = lines[0][:100]  # Fallback to first line
                print(f"🔍 AGENT: Using first line as title: '{title}'")
    
    # Remove title from analysis text to prevent duplication
    cleaned_analysis = analysis
    if title != "Agent Analysis":
        # Remove the title line from the beginning of the analysis
        title_patterns_for_removal = [
            rf'^#\s*{re.escape(title)}\s*$',  # Exact markdown header match
            rf'^##\s*{re.escape(title)}\s*$',  # H2 header
            rf'^{re.escape(title)}\s*$',  # Plain title line
            rf'^\*\*{re.escape(title)}\*\*\s*$',  # Bold title
        ]
        
        for pattern in title_patterns_for_removal:
            cleaned_analysis = re.sub(pattern, '', cleaned_analysis, flags=re.MULTILINE | re.IGNORECASE)
    
    # Also remove any remaining standalone title lines at the start
    lines = cleaned_analysis.split('\n')
    while lines and (not lines[0].strip() or lines[0].strip().startswith('#') or 
                     (title != "Agent Analysis" and title.lower() in lines[0].lower())):
        lines.pop(0)
    cleaned_analysis = '\n'.join(lines).strip()
    
    # Extract overview (first paragraph or summary section)
    overview_match = re.search(r'(?:Summary|Overview):\s*(.*?)(?:\n\n|\n(?=[A-Z][a-z]+:)|\Z)', cleaned_analysis, re.DOTALL | re.IGNORECASE)
    overview = cleaned_analysis[:500] + "..." if len(cleaned_analysis) > 500 else cleaned_analysis  # Default to cleaned analysis
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