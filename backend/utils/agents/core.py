"""
Core agent implementation for conversation analysis and action taking
"""
from typing import List, Dict, Any, Optional, Generator
from datetime import datetime
import json

from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from models.conversation import Conversation, CreateConversation
from utils.agents.tools import get_agent_tools
from utils.llms.memory import get_prompt_memories
from utils.llm import retrieve_memory_context_params


class ConversationAgent:
    """
    AI Agent for analyzing conversations and taking actions
    """
    
    def __init__(self, uid: str, model_name: str = "gpt-4o-mini"):
        self.uid = uid
        self.llm = ChatOpenAI(model=model_name, temperature=0.1)
        self.tools = get_agent_tools(uid)
        self.memory = MemorySaver()
        
        # Create the agent with tools and memory
        self.agent = create_react_agent(
            self.llm,
            self.tools,
            checkpointer=self.memory
        )
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt with user context"""
        try:
            user_name, memories_str = get_prompt_memories(self.uid)
        except Exception as e:
            print(f"Error getting user memories: {e}")
            user_name = "User"
            memories_str = "No user memories available."
        
        return f"""You are a helpful AI assistant analyzing conversations and taking actions for {user_name}.

ABOUT THE USER:
{memories_str}

YOUR CAPABILITIES:
1. Analyze conversation transcripts to understand context, topics, and user needs
2. Retrieve relevant past conversations using semantic search
3. Search the web for current information when needed
4. Suggest actionable next steps and solutions
5. Provide insights and learning opportunities

CONVERSATION ANALYSIS APPROACH:
1. First, analyze the current conversation to understand the main topics and user's situation
2. Extract key keywords and topics that might relate to past conversations
3. Use conversation_retrieval tool to find relevant past conversations that provide context
4. If current information is needed, use web_search tool to get up-to-date facts
5. Synthesize all information to provide helpful insights and actionable recommendations

GUIDELINES:
- Always start by understanding what the user is trying to achieve or learn
- Look for patterns across conversations to provide deeper insights
- Suggest specific, actionable next steps the user can take
- Be concise but thorough in your analysis
- If you find relevant past conversations, reference them specifically
- Prioritize helping the user learn, solve problems, or take meaningful action

Remember: You are analyzing conversations that have already happened. Your role is to help {user_name} understand patterns, gain insights, and decide on next steps based on the conversation content and their history."""

    def analyze_conversation(
        self, 
        transcript: str, 
        conversation_data: Optional[Dict] = None,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Analyze a conversation transcript and suggest actions
        
        Args:
            transcript: The conversation transcript to analyze
            conversation_data: Optional additional conversation metadata
            session_id: Session ID for conversation memory
            
        Returns:
            Analysis results with insights and suggested actions
        """
        print(f"🔥 DUPLICATE_DEBUG: ConversationAgent.analyze_conversation() ENTRY")
        print(f"🔥 DUPLICATE_DEBUG: - uid: {self.uid}")
        print(f"🔥 DUPLICATE_DEBUG: - transcript length: {len(transcript)}")
        print(f"🔥 DUPLICATE_DEBUG: - session_id: {session_id}")
        print(f"🔥 DUPLICATE_DEBUG: - conversation_data: {conversation_data}")
        
        import traceback
        print(f"🔥 DUPLICATE_DEBUG: Agent analyze_conversation call stack:")
        traceback.print_stack()
        
        try:
            # Prepare conversation context
            context_info = ""
            if conversation_data:
                context_info = f"""
CONVERSATION METADATA:
- Created: {conversation_data.get('created_at', 'Unknown')}
- Source: {conversation_data.get('source', 'Unknown')}
- Category: {conversation_data.get('category', 'Unknown')}
"""
            
            # Create analysis prompt that includes title generation
            analysis_prompt = f"""
Please analyze this conversation transcript and help the user. Provide your response in this exact format:

TITLE: [Generate a concise, memorable title (3-8 words) that captures the essence of what was discussed]

ANALYSIS:
[Your comprehensive analysis covering the following areas:]

1. **Understanding the Context**: What is this conversation about? What are the main topics and themes?

2. **Finding Relevant History**: Search for past conversations that relate to these topics to provide additional context.

3. **Identifying Key Insights**: What patterns, opportunities, or important points should the user know about?

4. **Suggesting Actions**: What specific actions should the user take based on this conversation and their history?

5. **Learning Opportunities**: What can the user learn from this conversation? Any knowledge gaps to fill?

{context_info}

CONVERSATION TRANSCRIPT:
{transcript}

Please provide a comprehensive analysis with actionable recommendations. Start with "TITLE:" followed by a short descriptive title, then "ANALYSIS:" followed by your detailed analysis."""

            # Configure the agent with conversation config
            config = {"configurable": {"thread_id": session_id}}
            
            print(f"🔥 DUPLICATE_DEBUG: About to call self.agent.invoke() - this will trigger LangGraph")
            print(f"🔥 DUPLICATE_DEBUG: - session_id: {session_id}")
            print(f"🔥 DUPLICATE_DEBUG: - config: {config}")
            
            # Run the agent
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": analysis_prompt}]},
                config=config
            )
            
            print(f"🔥 DUPLICATE_DEBUG: self.agent.invoke() completed successfully")
            print(f"🔥 DUPLICATE_DEBUG: - result type: {type(result)}")
            print(f"🔥 DUPLICATE_DEBUG: - result keys: {result.keys() if isinstance(result, dict) else 'not a dict'}")
            
            # Extract the final response
            final_message = result["messages"][-1].content
            
            # Parse title and analysis from the response
            title = "Conversation"  # Default fallback
            analysis = final_message  # Default to full response
            
            import re
            
            # Try to extract title and analysis
            title_match = re.search(r'TITLE:\s*(.+?)(?:\n|$)', final_message, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
                # Clean up the title
                title = re.sub(r'^["\']|["\']$', '', title)  # Remove quotes
                title = re.sub(r'^#+ ', '', title)  # Remove markdown headers
                title = title.strip()
                
                # Validate title length
                if len(title) > 100:
                    title = title[:97] + "..."
                elif len(title) < 3:
                    title = "Conversation"
                
                print(f"🔍 AGENT: Extracted title from response: '{title}'")
            
            # Extract analysis part (everything after "ANALYSIS:")
            analysis_match = re.search(r'ANALYSIS:\s*(.+)', final_message, re.DOTALL | re.IGNORECASE)
            if analysis_match:
                analysis = analysis_match.group(1).strip()
                print(f"🔍 AGENT: Extracted analysis (length: {len(analysis)})")
            else:
                # If no ANALYSIS: marker found, use everything after TITLE:
                if title_match:
                    analysis = final_message[title_match.end():].strip()
                    # Remove any remaining "ANALYSIS:" markers
                    analysis = re.sub(r'^\s*ANALYSIS:\s*', '', analysis, flags=re.IGNORECASE)
                print(f"🔍 AGENT: Using fallback analysis extraction (length: {len(analysis)})")
            
            # Parse and structure the response
            return {
                "title": title,
                "analysis": analysis,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "status": "success"
            }
            
        except Exception as e:
            return {
                "analysis": f"Error analyzing conversation: {str(e)}",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e)
            }
    
    def stream_analysis(
        self, 
        transcript: str, 
        conversation_data: Optional[Dict] = None,
        session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Stream the conversation analysis in real-time
        
        Args:
            transcript: The conversation transcript to analyze
            conversation_data: Optional additional conversation metadata
            session_id: Session ID for conversation memory
            
        Yields:
            Stream of analysis progress updates
        """
        try:
            # Prepare context like in analyze_conversation
            context_info = ""
            if conversation_data:
                context_info = f"""
CONVERSATION METADATA:
- Created: {conversation_data.get('created_at', 'Unknown')}
- Source: {conversation_data.get('source', 'Unknown')}
- Category: {conversation_data.get('category', 'Unknown')}
"""
            
            analysis_prompt = f"""
Please analyze this conversation transcript and help the user by providing:

1. **Understanding the Context**: What is this conversation about? What are the main topics and themes?
2. **Finding Relevant History**: Search for past conversations that relate to these topics.
3. **Identifying Key Insights**: What patterns or important points should the user know?
4. **Suggesting Actions**: What specific actions should the user take?
5. **Learning Opportunities**: What can the user learn from this conversation?

{context_info}

CONVERSATION TRANSCRIPT:
{transcript}

Please provide a comprehensive analysis with actionable recommendations. Do NOT include a title or header - start directly with your analysis content."""

            config = {"configurable": {"thread_id": session_id}}
            
            # Stream the agent execution
            for event in self.agent.stream(
                {"messages": [{"role": "user", "content": analysis_prompt}]},
                config=config,
                stream_mode="values"
            ):
                if "messages" in event and len(event["messages"]) > 0:
                    last_message = event["messages"][-1]
                    yield {
                        "type": "message",
                        "content": last_message.content if hasattr(last_message, 'content') else str(last_message),
                        "role": getattr(last_message, 'type', 'unknown'),
                        "timestamp": datetime.now().isoformat()
                    }
            
            yield {
                "type": "completion",
                "message": "Analysis completed",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def continue_conversation(
        self, 
        user_message: str, 
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Continue an ongoing conversation with the agent
        
        Args:
            user_message: User's follow-up message or question
            session_id: Session ID to maintain context
            
        Returns:
            Agent's response
        """
        try:
            config = {"configurable": {"thread_id": session_id}}
            
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config=config
            )
            
            final_message = result["messages"][-1].content
            
            return {
                "response": final_message,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "status": "success"
            }
            
        except Exception as e:
            return {
                "response": f"Error processing message: {str(e)}",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e)
            }


def create_conversation_agent(uid: str) -> ConversationAgent:
    """
    Factory function to create a conversation agent for a user
    
    Args:
        uid: User ID
        
    Returns:
        Configured ConversationAgent instance
    """
    return ConversationAgent(uid) 