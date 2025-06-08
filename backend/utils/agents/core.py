"""
Core agent implementation for conversation analysis and action taking
"""
from typing import List, Dict, Any, Optional, Generator
from datetime import datetime
import json
import os

from langchain_openai import AzureChatOpenAI
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
    
    def __init__(self, uid: str, model_name: str = "gpt-4.1"):
        self.uid = uid
        
        # Initialize Azure OpenAI with environment variables
        self.llm = AzureChatOpenAI(
            deployment_name="gpt-4.1",  # Your Azure deployment name
            model_name=model_name,
            temperature=0.1,
            api_version=os.getenv("OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY")
        )
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
4. Delegate specialized tasks to expert Azure OpenAI agents
5. Suggest actionable next steps and solutions
6. Provide insights and learning opportunities

MANDATORY TOOL USAGE WORKFLOW:
1. ALWAYS start with conversation_retrieval to find relevant past conversations
2. ALWAYS use web_search when:
   - User asks about specific places, restaurants, services, or businesses
   - Current information would be helpful (prices, hours, reviews, locations)
   - User needs factual data or recommendations
   - Past conversations don't provide sufficient context
3. Use MULTIPLE azure_agent tools for comprehensive multi-expert analysis:
   - Identify 2-4 different expertise areas needed for this conversation
   - Call azure_agent multiple times with different specialized system prompts
   - Each agent should have a distinct role, perspective, and focus area
   - Combine their insights for well-rounded, multi-perspective recommendations
   - Examples: Business + Technical + Market + Risk perspectives
4. Use ALL relevant tools together to provide comprehensive analysis

MULTI-AGENT ORCHESTRATION STRATEGY:
- IDENTIFY: What expertise areas are needed for this conversation topic?
- DESIGN: Create 2-4 specialized agents with distinct roles and perspectives
- EXECUTE: Call each azure_agent with specific system prompts tailored to their expertise
- SYNTHESIZE: Combine their recommendations into coherent, actionable insights
- HIGHLIGHT: Where experts agree/disagree and explain the reasoning

AZURE AGENT COMBINATIONS BY CONVERSATION TYPE:

🍽️ **Dining/Restaurant Conversations:**
- Local Food Expert: "You are a local dining expert specializing in [city] restaurants..."
- Health/Nutrition Specialist: "You are a nutritionist focused on healthy dining choices..."
- Budget Advisor: "You are a financial advisor specializing in dining budgets..."
- Cultural Expert: "You are a cultural expert on [cuisine type] dining experiences..."

💼 **Business/Career Conversations:**
- Business Analyst: "You are a business strategy expert analyzing market opportunities..."
- Career Coach: "You are a career development specialist focusing on professional growth..."
- Financial Advisor: "You are a financial consultant evaluating business decisions..."
- Risk Analyst: "You are a risk management expert identifying potential challenges..."

🏠 **Real Estate/Housing Conversations:**
- Market Analyst: "You are a real estate market expert analyzing property trends..."
- Financial Advisor: "You are a mortgage and financing specialist..."
- Local Area Expert: "You are a neighborhood specialist for [location]..."
- Legal Consultant: "You are a real estate legal expert on contracts and regulations..."

🎯 **Project/Planning Conversations:**
- Project Manager: "You are an experienced project management consultant..."
- Technical Lead: "You are a technical architecture and implementation expert..."
- Resource Planner: "You are a resource allocation and timeline specialist..."
- Quality Assurance: "You are a quality control and risk mitigation expert..."

🏥 **Health/Wellness Conversations:**
- Health Expert: "You are a healthcare professional specializing in [condition]..."
- Nutritionist: "You are a certified nutritionist focusing on dietary recommendations..."
- Fitness Specialist: "You are a fitness and exercise expert..."
- Mental Health Counselor: "You are a mental health professional..."

WEB SEARCH INTEGRATION:
- When you find useful web search results, format them nicely in your analysis
- Include relevant links, addresses, phone numbers, and key details
- Present web search findings in a dedicated section with proper markdown formatting
- Always explain how the web search results help the user

ANALYSIS STRUCTURE REQUIREMENTS:
- Include a "📍 Current Information" section when web search is used
- Include a "🤖 Multi-Expert Consultation" section when multiple azure_agents are used
- Format each expert's insights with clear role identification and recommendations
- Create a "🔗 Expert Synthesis" subsection combining all expert perspectives
- Highlight consensus and disagreements between experts with explanations
- Format expert agent insights with clear headings and actionable recommendations
- Provide actionable recommendations based on conversation history, current information, AND synthesized multi-expert analysis

MULTI-EXPERT ANALYSIS FORMAT:
🤖 **Multi-Expert Consultation**

**Expert 1 - [Role]:** [Specific findings and recommendations]
**Expert 2 - [Role]:** [Specific findings and recommendations]  
**Expert 3 - [Role]:** [Specific findings and recommendations]

🔗 **Expert Synthesis:**
- **Consensus:** What all experts agree on
- **Key Differences:** Where experts have different perspectives and why
- **Integrated Recommendations:** Combined wisdom from all experts

AZURE AGENT USAGE EXAMPLES (they can use web search automatically):
- Research Agent: "You are a research specialist. Analyze this data and provide insights..."
- Strategy Agent: "You are a strategic planning expert. Create an action plan for..."
- Technical Agent: "You are a technical consultant. Provide recommendations for..."
- Creative Agent: "You are a creative problem solver. Generate innovative solutions for..."
- Market Analyst: "You are a market research expert. Analyze current market trends for..."
- Local Expert: "You are a local area specialist. Research and recommend the best..."

Remember: You are analyzing conversations that have already happened. Your role is to help {user_name} understand patterns, gain insights, and decide on next steps based on their conversation history, current real-world information, AND specialized expert analysis from Azure agents."""

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
Please analyze this conversation transcript and help the user. You MUST use your available tools to provide comprehensive analysis.

REQUIRED TOOL USAGE:
1. ALWAYS use conversation_retrieval to search for relevant past conversations
2. ALWAYS use web_search if the conversation involves:
   - Specific places, restaurants, services, or businesses
   - Questions that would benefit from current information
   - Requests for recommendations or factual data
3. USE MULTIPLE azure_agent tools for comprehensive multi-expert analysis:
   - Identify 2-4 different expertise areas needed for this conversation
   - Call azure_agent multiple times with different specialized system prompts
   - Each expert should focus on a different aspect or perspective
   - Examples: Technical + Business + Market + User Experience perspectives

4. **🤖 Multi-Expert Consultation**: Use azure_agent tool multiple times to get diverse expert perspectives. For each expert:
   - Create a specific system prompt defining their role and expertise
   - Focus each expert on different aspects of the conversation
   - Get 2-4 different expert opinions (e.g., Business Analyst + Technical Expert + Market Researcher + Risk Analyst)
   - Note: Azure agents can automatically use web search when needed for current information

5. **🔗 Expert Synthesis**: After consulting multiple experts, synthesize their insights:
   - Identify where experts agree (consensus)
   - Highlight where they disagree and explain why
   - Provide integrated recommendations combining all expert perspectives

{context_info}

CONVERSATION TRANSCRIPT:
{transcript}

IMPORTANT: You MUST use the available tools (conversation_retrieval, web_search, and azure_agent) to gather comprehensive information before providing your analysis.

RESPONSE FORMAT REQUIREMENT:
You MUST format your response exactly as follows:

TITLE: [Generate a concise, descriptive title based on the main topic/theme of the conversation - max 60 characters]

ANALYSIS:
[Your comprehensive analysis here, including all tool results, expert insights, and recommendations. Format with bullet points, links, and relevant details.]

The TITLE should capture the essence of what the conversation is about, not just be generic. Examples:
- "Restaurant Recommendations in San Francisco"
- "Project Planning and Timeline Discussion" 
- "Health Insurance Options and Coverage"
- "Weekend Travel Plans to Portland"

Do NOT use generic titles like "Conversation" or "Discussion"."""

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