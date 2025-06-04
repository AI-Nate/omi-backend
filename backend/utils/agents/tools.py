"""
Agent tools for conversation analysis and retrieval
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from langchain.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from pydantic import BaseModel, Field

from database.vector_db import query_vectors, query_vectors_by_metadata
from database.conversations import get_conversations_by_id
from models.conversation import Conversation
from utils.llm import generate_embedding


class PineconeRetrievalInput(BaseModel):
    """Input for Pinecone conversation retrieval tool"""
    query: str = Field(description="Search query to find relevant conversations")
    start_timestamp: Optional[int] = Field(None, description="Start timestamp filter (Unix timestamp)")
    end_timestamp: Optional[int] = Field(None, description="End timestamp filter (Unix timestamp)")
    max_results: int = Field(5, description="Maximum number of conversations to retrieve")


class WebSearchInput(BaseModel):
    """Input for web search tool"""
    query: str = Field(description="Search query for web search")


@tool("pinecone_conversation_retrieval", args_schema=PineconeRetrievalInput)
def pinecone_conversation_retrieval(
    query: str, 
    uid: str,
    start_timestamp: Optional[int] = None, 
    end_timestamp: Optional[int] = None,
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Retrieve relevant conversations from Pinecone vector database based on semantic similarity.
    
    Args:
        query: The search query to find semantically similar conversations
        uid: User ID for filtering
        start_timestamp: Optional start timestamp filter (Unix timestamp)
        end_timestamp: Optional end timestamp filter (Unix timestamp)  
        max_results: Maximum number of conversations to return
    
    Returns:
        Dictionary containing retrieved conversations with summaries and metadata
    """
    try:
        # Query Pinecone for relevant conversation IDs
        conversation_ids = query_vectors(
            query=query,
            uid=uid,
            starts_at=start_timestamp,
            ends_at=end_timestamp,
            k=max_results
        )
        
        if not conversation_ids:
            return {
                "conversations": [],
                "count": 0,
                "message": "No relevant conversations found"
            }
        
        # Retrieve full conversation data from database
        conversations_data = get_conversations_by_id(uid, conversation_ids)
        conversations = [Conversation(**conv) for conv in conversations_data]
        
        # Format response with key information
        formatted_conversations = []
        for conv in conversations:
            formatted_conversations.append({
                "id": conv.id,
                "title": conv.structured.title if conv.structured else "No title",
                "overview": conv.structured.overview if conv.structured else "No overview",
                "created_at": conv.created_at.isoformat(),
                "category": conv.structured.category if conv.structured else None,
                "action_items": [item.content if hasattr(item, 'content') else str(item) 
                               for item in (conv.structured.action_items if conv.structured else [])],
                "transcript_preview": conv.get_transcript()[:200] + "..." if len(conv.get_transcript()) > 200 else conv.get_transcript()
            })
        
        return {
            "conversations": formatted_conversations,
            "count": len(formatted_conversations),
            "message": f"Found {len(formatted_conversations)} relevant conversations"
        }
        
    except Exception as e:
        return {
            "conversations": [],
            "count": 0,
            "error": f"Error retrieving conversations: {str(e)}"
        }


@tool("advanced_pinecone_retrieval", args_schema=PineconeRetrievalInput)
def advanced_pinecone_retrieval(
    query: str,
    uid: str,
    people: Optional[List[str]] = None,
    topics: Optional[List[str]] = None,
    entities: Optional[List[str]] = None,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None,
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Advanced conversation retrieval with metadata filtering.
    
    Args:
        query: The search query
        uid: User ID
        people: List of people names to filter by
        topics: List of topics to filter by  
        entities: List of entities to filter by
        start_timestamp: Start timestamp filter
        end_timestamp: End timestamp filter
        max_results: Maximum results to return
    
    Returns:
        Dictionary with retrieved conversations and metadata
    """
    try:
        # Generate embedding for the query
        vector = generate_embedding(query)
        
        # Use advanced metadata search
        conversation_ids = query_vectors_by_metadata(
            uid=uid,
            vector=vector,
            dates_filter=[
                datetime.fromtimestamp(start_timestamp) if start_timestamp else None,
                datetime.fromtimestamp(end_timestamp) if end_timestamp else None
            ] if start_timestamp or end_timestamp else [None, None],
            people=people or [],
            topics=topics or [],
            entities=entities or [],
            dates=[],
            limit=max_results
        )
        
        if not conversation_ids:
            return {
                "conversations": [],
                "count": 0,
                "message": "No conversations found matching the criteria"
            }
        
        # Get full conversation data
        conversations_data = get_conversations_by_id(uid, conversation_ids)
        conversations = [Conversation(**conv) for conv in conversations_data]
        
        # Format response
        formatted_conversations = []
        for conv in conversations:
            formatted_conversations.append({
                "id": conv.id,
                "title": conv.structured.title if conv.structured else "No title",
                "overview": conv.structured.overview if conv.structured else "No overview", 
                "created_at": conv.created_at.isoformat(),
                "category": conv.structured.category if conv.structured else None,
                "action_items": [item.content if hasattr(item, 'content') else str(item) 
                               for item in (conv.structured.action_items if conv.structured else [])],
                "people_mentioned": getattr(conv.structured, 'people_mentioned', []) if conv.structured else [],
                "topics": getattr(conv.structured, 'topics', []) if conv.structured else [],
                "transcript_preview": conv.get_transcript()[:300] + "..." if len(conv.get_transcript()) > 300 else conv.get_transcript()
            })
        
        return {
            "conversations": formatted_conversations,
            "count": len(formatted_conversations),
            "message": f"Found {len(formatted_conversations)} conversations matching criteria"
        }
        
    except Exception as e:
        return {
            "conversations": [],
            "count": 0,
            "error": f"Error in advanced retrieval: {str(e)}"
        }


@tool("web_search", args_schema=WebSearchInput)  
def web_search_tool(query: str) -> str:
    """
    Search the web for current information on any topic.
    
    Args:
        query: The search query
        
    Returns:
        Search results as formatted string
    """
    try:
        search = DuckDuckGoSearchRun()
        results = search.run(query)
        return f"Web search results for '{query}':\n{results}"
    except Exception as e:
        return f"Error performing web search: {str(e)}"


def get_agent_tools(uid: str) -> List:
    """
    Get all available tools for the agent with user context.
    
    Args:
        uid: User ID for context-aware tools
        
    Returns:
        List of available tools
    """
    # Create tools with bound user context
    def bound_pinecone_retrieval(query: str, start_timestamp: Optional[int] = None, 
                                end_timestamp: Optional[int] = None, max_results: int = 5):
        return pinecone_conversation_retrieval(query, uid, start_timestamp, end_timestamp, max_results)
    
    def bound_advanced_retrieval(query: str, people: Optional[List[str]] = None,
                                topics: Optional[List[str]] = None, entities: Optional[List[str]] = None,
                                start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None,
                                max_results: int = 5):
        return advanced_pinecone_retrieval(query, uid, people, topics, entities, 
                                         start_timestamp, end_timestamp, max_results)
    
    # Configure tools with descriptions
    bound_pinecone_retrieval.name = "conversation_retrieval"
    bound_pinecone_retrieval.description = """Retrieve relevant past conversations based on semantic similarity. 
    Use this when you need to find conversations related to specific topics, people, or events to provide context."""
    
    bound_advanced_retrieval.name = "advanced_conversation_search"  
    bound_advanced_retrieval.description = """Advanced conversation search with filtering by people, topics, and entities.
    Use this when you need more precise filtering of conversation results."""
    
    return [
        bound_pinecone_retrieval,
        bound_advanced_retrieval,
        web_search_tool
    ] 