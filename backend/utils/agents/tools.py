"""
Agent tools for conversation analysis and retrieval
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
from langchain.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
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


class AzureAgentInput(BaseModel):
    """Input for Azure OpenAI agent tool"""
    system_prompt: str = Field(description="System prompt to define the agent's role and capabilities")
    user_message: str = Field(description="The specific task or question for the agent to handle")
    temperature: Optional[float] = Field(0.1, description="Temperature for response generation (0.0 to 1.0)")
    max_tokens: Optional[int] = Field(1000, description="Maximum tokens for the response")


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
                "transcript_preview": conv.get_transcript(False)[:200] + "..." if len(conv.get_transcript(False)) > 200 else conv.get_transcript(False)
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
                "transcript_preview": conv.get_transcript(False)[:300] + "..." if len(conv.get_transcript(False)) > 300 else conv.get_transcript(False)
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


def get_azure_agent_tools() -> List:
    """
    Get tools available for Azure agent tool.
    Currently includes web search capability.
    
    Returns:
        List of tools for Azure agent
    """
    return [web_search_tool]


@tool("azure_agent", args_schema=AzureAgentInput)
def azure_agent_tool(
    system_prompt: str, 
    user_message: str, 
    temperature: Optional[float] = 0.1,
    max_tokens: Optional[int] = 1000
) -> str:
    """
    Delegate a specific task to a specialized Azure OpenAI agent with custom system prompt and web search capability.
    
    This agent can:
    - Use web search to find current information when needed
    - Perform specialized analysis with domain expertise
    - Combine web research with custom reasoning
    - Generate comprehensive, well-researched responses
    
    Use this tool when you need to:
    - Create a specialized agent for a specific task (research, analysis, planning, etc.)
    - Generate content with specific expertise or perspective
    - Perform complex reasoning or analysis tasks requiring current information
    - Get detailed information or recommendations on specific topics
    
    Args:
        system_prompt: Define the agent's role, expertise, and behavior
        user_message: The specific task or question for the agent
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative)
        max_tokens: Maximum length of the response
        
    Returns:
        The specialized agent's response (may include web search results)
    """
    try:
        # Initialize Azure OpenAI LLM
        azure_llm = AzureChatOpenAI(
            deployment_name="gpt-4.1",
            model_name="gpt-4.1",
            temperature=temperature,
            max_tokens=max_tokens,
            api_version=os.getenv("OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY")
        )
        
        # Get tools for the Azure agent
        azure_tools = get_azure_agent_tools()
        
        # Create memory for the Azure agent
        azure_memory = MemorySaver()
        
        # Create the Azure agent with tools
        azure_agent = create_react_agent(
            azure_llm,
            azure_tools,
            checkpointer=azure_memory
        )
        
        # Enhanced system prompt that includes tool usage instructions
        enhanced_system_prompt = f"""{system_prompt}

AVAILABLE TOOLS:
- web_search: Use this to find current, real-time information from the internet when your task requires:
  * Current facts, data, or statistics
  * Recent news or developments
  * Specific information about places, businesses, or services
  * Prices, reviews, or ratings
  * Contact information or addresses
  * Any information that might have changed recently

TOOL USAGE GUIDELINES:
- Use web_search when the user's request would benefit from current, real-world information
- Always explain how the web search results help answer the user's question
- Format web search findings clearly with bullet points and relevant details
- Combine web search results with your specialized expertise to provide comprehensive analysis

Remember: You have access to web search, so use it strategically to enhance your specialized knowledge with current information."""

        # Create the analysis prompt for the Azure agent
        agent_prompt = f"""System: {enhanced_system_prompt}

User: {user_message}

Please provide a comprehensive response using your specialized expertise. Use web search when current information would enhance your analysis."""

        # Configure the Azure agent
        config = {"configurable": {"thread_id": f"azure_agent_{hash(user_message)}"}}
        
        # Run the Azure agent
        result = azure_agent.invoke(
            {"messages": [{"role": "user", "content": agent_prompt}]},
            config=config
        )
        
        # Extract the final response
        final_response = result["messages"][-1].content
        
        return final_response
        
    except Exception as e:
        return f"Error with Azure agent: {str(e)}"


def get_agent_tools(uid: str) -> List:
    """
    Get all available tools for the agent with user context.
    
    Args:
        uid: User ID for context-aware tools
        
    Returns:
        List of available tools
    """
    # Create tools with bound user context
    @tool("conversation_retrieval")
    def bound_pinecone_retrieval(query: str, start_timestamp: Optional[int] = None, 
                                end_timestamp: Optional[int] = None, max_results: int = 5):
        """
        Retrieve relevant past conversations based on semantic similarity.
        Use this when you need to find conversations related to specific topics, people, or events to provide context.
        
        Args:
            query: Search query to find relevant conversations
            start_timestamp: Optional start timestamp filter (Unix timestamp)
            end_timestamp: Optional end timestamp filter (Unix timestamp)
            max_results: Maximum number of conversations to retrieve
        """
        return pinecone_conversation_retrieval.func(query, uid, start_timestamp, end_timestamp, max_results)
    
    @tool("advanced_conversation_search")
    def bound_advanced_retrieval(query: str, people: Optional[List[str]] = None,
                                topics: Optional[List[str]] = None, entities: Optional[List[str]] = None,
                                start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None,
                                max_results: int = 5):
        """
        Advanced conversation search with filtering by people, topics, and entities.
        Use this when you need more precise filtering of conversation results.
        
        Args:
            query: The search query
            people: List of people names to filter by
            topics: List of topics to filter by
            entities: List of entities to filter by
            start_timestamp: Start timestamp filter
            end_timestamp: End timestamp filter
            max_results: Maximum results to return
        """
        return advanced_pinecone_retrieval.func(query, uid, people, topics, entities, 
                                         start_timestamp, end_timestamp, max_results)
    
    return [
        bound_pinecone_retrieval,
        bound_advanced_retrieval,
        web_search_tool,
        azure_agent_tool
    ] 