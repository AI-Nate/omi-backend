import json
import re
import os
import base64
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict

import tiktoken
from langchain.schema import (
    HumanMessage,
    SystemMessage,
    AIMessage,
)
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel, Field, ValidationError
import pytz

from database.redis_db import add_filter_category_item
from models.app import App
from models.chat import Message, MessageSender
from models.memories import Memory, MemoryCategory
from models.conversation import Structured, ConversationPhoto, CategoryEnum, Conversation, ActionItem, Event
from models.transcript_segment import TranscriptSegment
from models.trend import TrendEnum, ceo_options, company_options, software_product_options, hardware_product_options, \
    ai_product_options, TrendType
from utils.prompts import extract_memories_prompt, extract_learnings_prompt, extract_memories_text_content_prompt
from utils.llms.memory import get_prompt_memories
from utils.langsmith_wrapper import trace_langchain_llm, trace_function

# Initialize LLM models
llm_mini = trace_langchain_llm(ChatOpenAI(model='gpt-4o-mini'))
llm_mini_stream = trace_langchain_llm(ChatOpenAI(model='gpt-4o-mini', streaming=True))
llm_large = trace_langchain_llm(ChatOpenAI(model='o1-preview'))
llm_large_stream = trace_langchain_llm(ChatOpenAI(model='o1-preview', streaming=True, temperature=1))
llm_medium = trace_langchain_llm(ChatOpenAI(model='gpt-4o'))
llm_medium_experiment = trace_langchain_llm(ChatOpenAI(model='gpt-4.1'))
llm_medium_stream = trace_langchain_llm(ChatOpenAI(model='gpt-4o', streaming=True))
llm_persona_mini_stream = trace_langchain_llm(ChatOpenAI(
    temperature=0.8,
    model="google/gemini-flash-1.5-8b",
    api_key=os.environ.get('OPENROUTER_API_KEY'),
    base_url="https://openrouter.ai/api/v1",
    default_headers={"X-Title": "Omi Chat"},
    streaming=True,
))
llm_persona_medium_stream = trace_langchain_llm(ChatOpenAI(
    temperature=0.8,
    model="anthropic/claude-3.5-sonnet",
    api_key=os.environ.get('OPENROUTER_API_KEY'),
    base_url="https://openrouter.ai/api/v1",
    default_headers={"X-Title": "Omi Chat"},
    streaming=True,
))
# Using text-embedding-3-small with 1024 dimensions to match the Pinecone index
embeddings = OpenAIEmbeddings(model="text-embedding-3-small", dimensions=1024)
parser = PydanticOutputParser(pydantic_object=Structured)

encoding = tiktoken.encoding_for_model('gpt-4')


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    num_tokens = len(encoding.encode(string))
    return num_tokens


# TODO: include caching layer, redis


# **********************************************
# *********** IMAGE ANALYSIS ******************
# **********************************************

@trace_function(tags=["image_analysis"])
def analyze_image_content(image_data: bytes, user_prompt: Optional[str] = None) -> str:
    """
    Analyze image content using OpenAI Vision API.
    
    Args:
        image_data: Raw image data as bytes
        user_prompt: Optional user-provided context or instructions for the analysis
    
    Returns:
        str: Description of the image content
    """
    try:
        # Encode image to base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # Create vision-compatible OpenAI client
        vision_llm = trace_langchain_llm(ChatOpenAI(model='gpt-4o'))
        
        # Base analysis text
        base_text = "Analyze this image and provide a detailed description of what you see. Focus on the main subjects, activities, objects, text, settings, and any other relevant details that could be useful for understanding the context and content."
        
        # Add user prompt if provided
        if user_prompt and user_prompt.strip():
            analysis_text = f"{base_text}\n\nAdditional context from user: {user_prompt.strip()}\n\nPlease incorporate this context into your analysis and focus on aspects that relate to the user's specific needs or instructions."
        else:
            analysis_text = base_text
        
        # Create the message with image
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": analysis_text
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "high"
                    }
                }
            ]
        )
        
        # Get response from OpenAI
        response = vision_llm.invoke([message])
        
        return response.content.strip()
        
    except Exception as e:
        print(f"Error analyzing image content: {e}")
        return "Image content could not be analyzed"


# **********************************************
# ********** CONVERSATION PROCESSING ***********
# **********************************************

class DiscardConversation(BaseModel):
    discard: bool = Field(description="If the conversation should be discarded or not")


class SpeakerIdMatch(BaseModel):
    speaker_id: int = Field(description="The speaker id assigned to the segment")


def should_discard_conversation(transcript: str) -> bool:
    if len(transcript.split(' ')) > 100:
        return False

    parser = PydanticOutputParser(pydantic_object=DiscardConversation)
    prompt = ChatPromptTemplate.from_messages([
        '''
    You will receive a transcript snippet. Length is never a reason to discard.

        Task
        Decide if the snippet should be saved as a memory.

        KEEP  → output:  discard = False
        DISCARD → output: discard = True

        KEEP (discard = False) if it contains any of the following:
        • a task, request, or action item
        • a decision, commitment, or plan
        • a question that requires follow-up
        • personal facts, preferences, or details likely useful later
        • an insight, summary, or key takeaway

        If none of these are present, DISCARD (discard = True).

        Return exactly one line:
        discard = <True|False>


    Transcript: ```{transcript}```

    {format_instructions}'''.replace('    ', '').strip()
    ])
    chain = prompt | llm_mini | parser
    try:
        response: DiscardConversation = chain.invoke({
            'transcript': transcript.strip(),
            'format_instructions': parser.get_format_instructions(),
        })
        return response.discard

    except Exception as e:
        print(f'Error determining memory discard: {e}')
        return False


class SummaryOutput(BaseModel):
    summary: str = Field(description="The extracted content, maximum 500 words.")


class ResourceItem(BaseModel):
    content: str = Field(description="The content of the improvement or learning item")
    url: str = Field(description="URL to a resource related to this item", default="")
    title: str = Field(description="Title of the resource", default="")


class EnhancedEvent(BaseModel):
    title: str = Field(description="The title of the event")
    description: str = Field(description="A brief description of the event", default='')
    start: str = Field(description="The start date and time of the event in ISO format")
    duration: int = Field(description="The duration of the event in minutes", default=30)
    user_prompt: str = Field(description="User-provided context or instructions for this event", default="")


class EnhancedSummaryOutput(BaseModel):
    title: str = Field(description="A title/name for this conversation", default='')
    overview: str = Field(
        description="A brief overview of the conversation, highlighting the key details from it",
        default='',
    )
    emoji: str = Field(description="An emoji to represent the conversation", default='🧠')
    category: CategoryEnum = Field(
        description="A category for this conversation (must be one of the valid categories)",
        default=CategoryEnum.other
    )
    key_takeaways: List[str] = Field(
        description="3-5 key takeaways from the conversation",
        default=[],
    )
    things_to_improve: List[ResourceItem] = Field(
        description="2-3 things that could be improved based on the conversation, with resource URLs",
        default=[],
    )
    things_to_learn: List[ResourceItem] = Field(
        description="1-2 things worth learning more about based on the conversation, with resource URLs",
        default=[],
    )
    action_items: List[str] = Field(description="A list of action items from the conversation", default=[])
    events: List[EnhancedEvent] = Field(
        description="A list of events extracted from the conversation, that the user must have on his calendar. Include any user-provided context in the user_prompt field.",
        default=[],
    )


@trace_function(tags=["conversation_summary"])
def get_transcript_structure(transcript: str, started_at: datetime, language_code: str, tz: str, uid: str = None) -> Structured:
    if len(transcript) == 0:
        return Structured(title='', overview='')

    # Define valid categories
    valid_categories = [cat.value for cat in CategoryEnum]
    valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
    
    # Get user memories if uid is provided
    user_memories_context = ""
    user_name = "The User"  # Default fallback name
    
    if uid:
        # First try to import the module
        try:
            from utils.llms.memory import get_prompt_memories
        except Exception as e:
            print(f"Error importing get_prompt_memories: {e}")
            return Structured(title='', overview='')
            
        # Then try to use the imported function
        try:
            user_name, memories_str = get_prompt_memories(uid)
            user_memories_context = (
                f"For personalization context about the user:\n"
                f"User name: {user_name}\n"
                f"{memories_str}\n\n"
                f"When generating \"Things to Improve\" and \"Things to Learn\" sections, use this personalization data to provide more targeted, relevant suggestions based on the user's background, interests, and previous activities.\n\n"
                f"For \"Things to Improve\":\n"
                f"- Start each item with a clear action verb (e.g., \"Practice...\", \"Implement...\", \"Develop...\")\n"
                f"- Include specific, measurable steps that {user_name} can take immediately\n"
                f"- Add a brief explanation of the benefit or why this improvement matters\n"
                f"- Consider both short-term quick wins and longer-term growth opportunities\n"
                f"- Be direct and concise, focusing on practical implementation\n"
                f"- For each item, provide a structure with: content (the suggestion itself), url (empty string), and title (empty string)\n\n"
                f"For \"Things to Learn\":\n"
                f"- Suggest specific topics or skills rather than broad areas\n"
                f"- Include a clear, actionable way to begin learning this topic (specific resource, course, or practice method)\n"
                f"- Explain briefly how this learning connects to interests or needs from the conversation\n"
                f"- Focus on knowledge or skills that would have immediate practical value\n"
                f"- For each item, provide a structure with: content (the suggestion itself), url (empty string), and title (empty string)\n\n"
                f"For the category field, you MUST choose one of the following values EXACTLY as written:\n"
                f"{valid_categories_str}\n\n"
                f"For context, the conversation started at {started_at.astimezone(pytz.timezone(tz)).strftime('%A, %B %d at %I:%M %p')} ({tz}).\n"
                f"Be thorough but concise. Prioritize the most important information."
            )
        except Exception as e:
            print(f"Error retrieving user memories: {e}")
            # Keep default user_name = "The User" and empty user_memories_context
    
    prompt = f'''
    You are a personal growth coach and life assistant analyzing a meaningful conversation from {user_name}'s life.
    Your role is to help {user_name} extract maximum value from this experience to grow as a person and improve their life.
    
    Think from {user_name}'s perspective - this conversation happened to THEM, and you're helping THEM understand what they can learn and how they can use this experience to become better.

    Create an enhanced summary that serves as a valuable resource for {user_name}'s personal development:
    
    1. **Title**: Create a memorable, personal title that captures the essence of what {user_name} experienced
    
    2. **Overview**: Write as if speaking directly to {user_name}. Focus on:
       - What this moment meant in their personal journey
       - How this conversation fits into their larger life story
       - The emotional and practical significance for their growth
    
    3. **Key Takeaways**: Extract 3-5 insights that {user_name} can carry forward:
       - Personal realizations about themselves, others, or life
       - Valuable perspectives they gained
       - Moments of clarity or understanding
       - Each takeaway should feel personally meaningful and applicable
    
    4. **Things to Improve**: Provide 2-3 growth opportunities tailored specifically for {user_name}:
       - Start each with an empowering action verb (e.g., "Practice...", "Develop...", "Strengthen...")
       - Focus on skills, habits, or mindsets that will enhance their life quality
       - Include WHY this improvement matters for their personal happiness and success
       - Make suggestions feel achievable and motivating, not critical
       - Connect improvements to their demonstrated interests and values
    
    5. **Things to Learn**: Suggest 1-2 learning opportunities that could enrich {user_name}'s life:
       - Topics that sparked their curiosity or relate to their interests
       - Skills that could help them achieve their goals or overcome challenges
       - Knowledge that would make them more effective, fulfilled, or interesting
       - Include how this learning connects to their personal growth journey
    
    6. **Action Items**: Capture any commitments or next steps {user_name} mentioned
    
    7. **Calendar Events**: Note any events or meetings mentioned for scheduling
    
    **Personal Growth Principles:**
    - Frame everything as opportunities, not deficits
    - Use encouraging, empowering language that makes {user_name} feel capable
    - Connect insights to their broader life goals and values
    - Make recommendations feel like natural next steps in their growth journey
    - Focus on how improvements will enhance their relationships, effectiveness, and well-being
    
    **Context for Personalization:**
    {user_memories_context}

    **Technical Requirements:**
    - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
    - For context, this conversation happened on {started_at.astimezone(pytz.timezone(tz)).strftime("%A, %B %d at %I:%M %p")} ({tz})
    - Structure improvements and learning items with: content (the suggestion itself), url (empty string), and title (empty string)

    Conversation that {user_name} experienced:
    {transcript}
    '''.replace('    ', '').strip()

    try:
        with_parser = llm_medium.with_structured_output(EnhancedSummaryOutput)
        response: EnhancedSummaryOutput = with_parser.invoke(prompt)
        
        structured = Structured(
            title=response.title,
            overview=response.overview,
            emoji=response.emoji,
            category=response.category,
        )

        # Add enhanced fields
        structured.key_takeaways = response.key_takeaways
        
        # Process improvement items with web search
        for item in response.things_to_improve:
            try:
                # Handle both string items and ResourceItem objects
                if isinstance(item, str):
                    content = item
                else:
                    content = item.content if hasattr(item, 'content') else str(item)
                
                # Use web search to find relevant resources
                search_query = f"How to {content.lower()}"
                search_results, annotations, url_mapping = perform_web_search(search_query, search_context_size="medium")
                
                resource_url = ""
                resource_title = ""
                
                # Get the first URL if available
                if url_mapping:
                    first_url = next(iter(url_mapping.keys()), "")
                    resource_url = first_url
                    resource_title = url_mapping.get(first_url, "")
                
                # Create resource item
                resource_item = ResourceItem(
                    content=content,
                    url=resource_url,
                    title=resource_title
                )
                structured.things_to_improve.append(resource_item)
            except Exception as e:
                print(f"Error processing improvement item: {e}")
                # Add as simple ResourceItem with just content
                structured.things_to_improve.append(ResourceItem(content=str(item)))
        
        # Process learning items with web search
        for item in response.things_to_learn:
            try:
                # Handle both string items and ResourceItem objects
                if isinstance(item, str):
                    content = item
                else:
                    content = item.content if hasattr(item, 'content') else str(item)
                
                # Use web search to find relevant resources
                search_query = f"Best resources to learn about {content.lower()}"
                search_results, annotations, url_mapping = perform_web_search(search_query, search_context_size="medium")
                
                resource_url = ""
                resource_title = ""
                
                # Get the first URL if available
                if url_mapping:
                    first_url = next(iter(url_mapping.keys()), "")
                    resource_url = first_url
                    resource_title = url_mapping.get(first_url, "")
                
                # Create resource item
                resource_item = ResourceItem(
                    content=content,
                    url=resource_url,
                    title=resource_title
                )
                structured.things_to_learn.append(resource_item)
            except Exception as e:
                print(f"Error processing learning item: {e}")
                # Add as simple ResourceItem with just content
                structured.things_to_learn.append(ResourceItem(content=str(item)))

        # Process action items and events
        for item in response.action_items:
            structured.action_items.append(ActionItem(description=item))

        for event in response.events:
            description = event.description if event.description else ''
            title = event.title if event.title else ''
            user_prompt = event.user_prompt if event.user_prompt else ''
            # Process the start time
            starts_at = None
            try:
                # Handle ISO format with timezone information
                start_str = event.start
                if start_str.endswith('Z'):
                    # UTC timezone
                    start_str = start_str[:-1] + '+00:00'
                    starts_at = datetime.fromisoformat(start_str).replace(tzinfo=None)
                elif '+' in start_str[-6:] or '-' in start_str[-6:]:
                    # Has timezone offset like "+07:00" or "-07:00"
                    starts_at = datetime.fromisoformat(start_str).replace(tzinfo=None)
                else:
                    # No timezone info, parse as is
                    starts_at = datetime.strptime(start_str, '%Y-%m-%dT%H:%M:%S')
            except Exception as e:
                print(f"Error parsing event start time '{event.start}': {e}")
                starts_at = datetime.now() + timedelta(days=1)  # fallback to tomorrow

            duration = event.duration if event.duration else 30  # default 30 minutes

            structured.events.append(Event(
                title=title,
                start=starts_at,  # Changed from starts_at to start
                duration=duration,
                description=description,
                user_prompt=user_prompt,
            ))

        return structured
    except ValidationError as e:
        print(f"Validation error in get_transcript_structure: {e}")
        # Fallback to a basic structured output
        return Structured(
            title="Conversation Summary", 
            overview="This conversation could not be summarized properly.",
            category=CategoryEnum.other
        )
    except Exception as e:
        print(f"Error in get_transcript_structure: {e}")
        # Fallback to a basic structured output
        return Structured(
            title="Conversation Summary", 
            overview="This conversation could not be summarized properly.",
            category=CategoryEnum.other
        )


def get_reprocess_transcript_structure(transcript: str, started_at: datetime, language_code: str, tz: str,
                                       title: str, uid: str = None) -> Structured:
    if len(transcript) == 0:
        return Structured(title='', overview='')

    # Define valid categories
    valid_categories = [cat.value for cat in CategoryEnum]
    valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
    
    # Get user memories if uid is provided
    user_memories_context = ""
    user_name = "The User"  # Default fallback name
    
    if uid:
        # First try to import the module
        try:
            from utils.llms.memory import get_prompt_memories
        except Exception as e:
            print(f"Error importing get_prompt_memories: {e}")
            return Structured(title=title if title else '', overview='')
            
        # Then try to use the imported function
        try:
            user_name, memories_str = get_prompt_memories(uid)
            user_memories_context = (
                f"For personalization context about the user:\n"
                f"User name: {user_name}\n"
                f"{memories_str}\n\n"
                f"When generating \"Things to Improve\" and \"Things to Learn\" sections, use this personalization data to provide more targeted, relevant suggestions based on the user's background, interests, and previous activities.\n\n"
                f"For \"Things to Improve\":\n"
                f"- Start each item with a clear action verb (e.g., \"Practice...\", \"Implement...\", \"Develop...\")\n"
                f"- Include specific, measurable steps that {user_name} can take immediately\n"
                f"- Add a brief explanation of the benefit or why this improvement matters\n"
                f"- Consider both short-term quick wins and longer-term growth opportunities\n"
                f"- Be direct and concise, focusing on practical implementation\n\n"
                f"For \"Things to Learn\":\n"
                f"- Suggest specific topics or skills rather than broad areas\n"
                f"- Include a clear, actionable way to begin learning this topic (specific resource, course, or practice method)\n"
                f"- Explain briefly how this learning connects to {user_name}'s interests or needs\n"
                f"- Focus on knowledge or skills that would have immediate practical value"
            )
        except Exception as e:
            print(f"Error retrieving user memories: {e}")
            # Keep default user_name = "The User" and empty user_memories_context
    
    prompt = f'''
    You are a personal growth coach and life assistant analyzing a meaningful conversation from {user_name}'s life.
    Your role is to help {user_name} extract maximum value from this experience to grow as a person and improve their life.
    
    Think from {user_name}'s perspective - this conversation happened to THEM, and you're helping THEM understand what they can learn and how they can use this experience to become better.

    Create an enhanced summary that serves as a valuable resource for {user_name}'s personal development:
    
    1. **Title**: Create a memorable, personal title that captures the essence of what {user_name} experienced
    
    2. **Overview**: Write as if speaking directly to {user_name}. Focus on:
       - What this moment meant in their personal journey
       - How this conversation fits into their larger life story
       - The emotional and practical significance for their growth
    
    3. **Key Takeaways**: Extract 3-5 insights that {user_name} can carry forward:
       - Personal realizations about themselves, others, or life
       - Valuable perspectives they gained
       - Moments of clarity or understanding
       - Each takeaway should feel personally meaningful and applicable
    
    4. **Things to Improve**: Provide 2-3 growth opportunities tailored specifically for {user_name}:
       - Start each with an empowering action verb (e.g., "Practice...", "Develop...", "Strengthen...")
       - Focus on skills, habits, or mindsets that will enhance their life quality
       - Include WHY this improvement matters for their personal happiness and success
       - Make suggestions feel achievable and motivating, not critical
       - Connect improvements to their demonstrated interests and values
    
    5. **Things to Learn**: Suggest 1-2 learning opportunities that could enrich {user_name}'s life:
       - Topics that sparked their curiosity or relate to their interests
       - Skills that could help them achieve their goals or overcome challenges
       - Knowledge that would make them more effective, fulfilled, or interesting
       - Include how this learning connects to their personal growth journey
    
    6. **Action Items**: Capture any commitments or next steps {user_name} mentioned
    
    7. **Calendar Events**: Note any events or meetings mentioned for scheduling
    
    **Personal Growth Principles:**
    - Frame everything as opportunities, not deficits
    - Use encouraging, empowering language that makes {user_name} feel capable
    - Connect insights to their broader life goals and values
    - Make recommendations feel like natural next steps in their growth journey
    - Focus on how improvements will enhance their relationships, effectiveness, and well-being
    
    **Context for Personalization:**
    {user_memories_context}

    **Technical Requirements:**
    - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
    - For context, this conversation happened on {started_at.astimezone(pytz.timezone(tz)).strftime("%A, %B %d at %I:%M %p")} ({tz})
    - Structure improvements and learning items with: content (the suggestion itself), url (empty string), and title (empty string)

    Conversation that {user_name} experienced:
    {transcript}
    '''.replace('    ', '').strip()

    try:
        with_parser = llm_medium.with_structured_output(EnhancedSummaryOutput)
        response: EnhancedSummaryOutput = with_parser.invoke(prompt)

        # Use existing title if provided, otherwise use generated title
        structured = Structured(
            title=title if title else response.title,
            overview=response.overview,
            emoji=response.emoji,
            category=response.category,
        )

        # Add enhanced fields
        structured.key_takeaways = response.key_takeaways
        
        # Process improvement items with web search
        for item in response.things_to_improve:
            try:
                # Handle both string items and ResourceItem objects
                if isinstance(item, str):
                    content = item
                else:
                    content = item.content if hasattr(item, 'content') else str(item)
                
                # Use web search to find relevant resources
                search_query = f"How to {content.lower()}"
                search_results, annotations, url_mapping = perform_web_search(search_query, search_context_size="medium")
                
                resource_url = ""
                resource_title = ""
                
                # Get the first URL if available
                if url_mapping:
                    first_url = next(iter(url_mapping.keys()), "")
                    resource_url = first_url
                    resource_title = url_mapping.get(first_url, "")
                
                # Create resource item
                resource_item = ResourceItem(
                    content=content,
                    url=resource_url,
                    title=resource_title
                )
                structured.things_to_improve.append(resource_item)
            except Exception as e:
                print(f"Error processing improvement item: {e}")
                # Add as simple ResourceItem with just content
                structured.things_to_improve.append(ResourceItem(content=str(item)))
        
        # Process learning items with web search
        for item in response.things_to_learn:
            try:
                # Handle both string items and ResourceItem objects
                if isinstance(item, str):
                    content = item
                else:
                    content = item.content if hasattr(item, 'content') else str(item)
                
                # Use web search to find relevant resources
                search_query = f"Best resources to learn about {content.lower()}"
                search_results, annotations, url_mapping = perform_web_search(search_query, search_context_size="medium")
                
                resource_url = ""
                resource_title = ""
                
                # Get the first URL if available
                if url_mapping:
                    first_url = next(iter(url_mapping.keys()), "")
                    resource_url = first_url
                    resource_title = url_mapping.get(first_url, "")
                
                # Create resource item
                resource_item = ResourceItem(
                    content=content,
                    url=resource_url,
                    title=resource_title
                )
                structured.things_to_learn.append(resource_item)
            except Exception as e:
                print(f"Error processing learning item: {e}")
                # Add as simple ResourceItem with just content
                structured.things_to_learn.append(ResourceItem(content=str(item)))

        # Process action items and events
        for item in response.action_items:
            structured.action_items.append(ActionItem(description=item))

        for event in response.events:
            description = event.description if event.description else ''
            title = event.title if event.title else ''
            user_prompt = event.user_prompt if event.user_prompt else ''
            # Process the start time
            starts_at = None
            try:
                # Handle ISO format with timezone information
                start_str = event.start
                if start_str.endswith('Z'):
                    # UTC timezone
                    start_str = start_str[:-1] + '+00:00'
                    starts_at = datetime.fromisoformat(start_str).replace(tzinfo=None)
                elif '+' in start_str[-6:] or '-' in start_str[-6:]:
                    # Has timezone offset like "+07:00" or "-07:00"
                    starts_at = datetime.fromisoformat(start_str).replace(tzinfo=None)
                else:
                    # No timezone info, parse as is
                    starts_at = datetime.strptime(start_str, '%Y-%m-%dT%H:%M:%S')
            except Exception as e:
                print(f"Error parsing event start time '{event.start}': {e}")
                starts_at = datetime.now() + timedelta(days=1)  # fallback to tomorrow

            duration = event.duration if event.duration else 30  # default 30 minutes

            structured.events.append(Event(
                title=title,
                start=starts_at,  # Changed from starts_at to start
                duration=duration,
                description=description,
                user_prompt=user_prompt,
            ))

        return structured
    except ValidationError as e:
        print(f"Validation error in get_reprocess_transcript_structure: {e}")
        # Fallback to a basic structured output with the provided title
        return Structured(
            title=title if title else "Conversation Summary", 
            overview="This conversation could not be summarized properly.",
            category=CategoryEnum.other
        )
    except Exception as e:
        print(f"Error in get_reprocess_transcript_structure: {e}")
        # Fallback to a basic structured output with the provided title
        return Structured(
            title=title if title else "Conversation Summary", 
            overview="This conversation could not be summarized properly.",
            category=CategoryEnum.other
        )


def get_app_result(transcript: str, app: App) -> str:
    prompt = f'''
    Your are an AI with the following characteristics:
    Name: {app.name},
    Description: {app.description},
    Task: ${app.memory_prompt}

    Conversation: ```{transcript.strip()}```,
    '''

    response = llm_medium_experiment.invoke(prompt)
    content = response.content.replace('```json', '').replace('```', '')
    return content


def get_app_result_v1(transcript: str, app: App) -> str:
    prompt = f'''
    Your are an AI with the following characteristics:
    Name: ${app.name},
    Description: ${app.description},
    Task: ${app.memory_prompt}

    Note: It is possible that the conversation you are given, has nothing to do with your task, \
    in that case, output an empty string. (For example, you are given a business conversation, but your task is medical analysis)

    Conversation: ```{transcript.strip()}```,

    Make sure to be concise and clear.
    '''

    response = llm_mini.invoke(prompt)
    content = response.content.replace('```json', '').replace('```', '')
    if len(content) < 5:
        return ''
    return content


# **************************************
# ************* OPENGLASS **************
# **************************************

@trace_function(tags=["image_only_summary"])
def summarize_open_glass(photos: List[ConversationPhoto]) -> Structured:
    photos_str = ''
    for i, photo in enumerate(photos):
        photos_str += f'{i + 1}. "{photo.description}"\n'
    prompt = f'''The user took a series of pictures from his POV, generated a description for each photo, and wants to create a memory from them.

      For the title, use the main topic of the scenes.
      For the overview, condense the descriptions into a brief summary with the main topics discussed, make sure to capture the key points and important details.
      For the category, classify the scenes into one of the available categories.

      Photos Descriptions: ```{photos_str}```
      '''.replace('    ', '').strip()
    return llm_mini.with_structured_output(Structured).invoke(prompt)


# **************************************************
# ************* EXTERNAL INTEGRATIONS **************
# **************************************************


def get_message_structure(text: str, started_at: datetime, language_code: str, tz: str,
                          text_source_spec: str = None) -> Structured:
    prompt_text = '''
    You are an expert message analyzer. Your task is to analyze the message content and provide structure and clarity.
    The message language is {language_code}. Use the same language {language_code} for your response.

    For the title, create a concise title that captures the main topic of the message.
    For the overview, summarize the message with the main points discussed, make sure to capture the key information and important details.
    For the action items, include any tasks or actions that need to be taken based on the message.
    For the category, classify the message into one of the available categories.
    For Calendar Events, include any events or meetings mentioned in the message. For date context, this message was sent on {started_at}. {tz} is the user's timezone, convert it to UTC and respond in UTC.

    Message Content: ```{text}```
    Message Source: {text_source_spec}
    
    {format_instructions}'''.replace('    ', '').strip()

    prompt = ChatPromptTemplate.from_messages([('system', prompt_text)])
    chain = prompt | llm_mini | parser

    response = chain.invoke({
        'language_code': language_code,
        'started_at': started_at.isoformat(),
        'tz': tz,
        'text': text,
        'text_source_spec': text_source_spec if text_source_spec else 'Messaging App',
        'format_instructions': parser.get_format_instructions(),
    })

    for event in (response.events or []):
        if event.duration > 180:
            event.duration = 180
        event.created = False
    return response


def summarize_experience_text(text: str, text_source_spec: str = None) -> Structured:
    source_context = f"Source: {text_source_spec}" if text_source_spec else "their own experiences or thoughts"
    prompt = f'''The user sent a text of {source_context}, and wants to create a memory from it.
      For the title, use the main topic of the experience or thought.
      For the overview, condense the descriptions into a brief summary with the main topics discussed, make sure to capture the key points and important details.
      For the category, classify the scenes into one of the available categories.
      For the action items, include any tasks or actions that need to be taken based on the content.
      For Calendar Events, include any events or meetings mentioned in the content.

      Text: ```{text}```
      '''.replace('    ', '').strip()
    return llm_mini.with_structured_output(Structured).invoke(prompt)


def get_conversation_summary(uid: str, memories: List[Conversation]) -> str:
    # First try to import the module
    try:
        from utils.llms.memory import get_prompt_memories
    except Exception as e:
        print(f"Error importing get_prompt_memories: {e}")
        return "Could not retrieve conversation summary due to an error."
        
    try:
        user_name, memories_str = get_prompt_memories(uid)
        conversation_history = Conversation.conversations_to_string(memories)

        prompt = f"""
        You are an experienced mentor, that helps people achieve their goals and improve their lives.
        You are advising {user_name} right now, {memories_str}

        The following are a list of {user_name}'s conversations from today, with the transcripts and a slight summary of each, that {user_name} had during his day.
        {user_name} wants to get a summary of the key action items {user_name} has to take based on today's conversations.

        Remember {user_name} is busy so this has to be very efficient and concise.
        Respond in at most 50 words.

        Output your response in plain text, without markdown. No newline character and only use numbers for the action items.
        ```
        {conversation_history}
        ```
        """.replace('    ', '').strip()
        return llm_mini.invoke(prompt).content
    except Exception as e:
        print(f"Error in get_conversation_summary: {e}")
        return "Could not retrieve conversation summary due to an error."


def generate_embedding(content: str) -> List[float]:
    return embeddings.embed_documents([content])[0]


def perform_web_search(query: str, search_context_size: str = "medium") -> tuple[str, list, dict]:
    """
    Performs a web search using OpenAI's web search models to find relevant information.
    
    Args:
        query: The search query
        search_context_size: Size of search context (low, medium, high)
        
    Returns:
        Tuple containing: 
        - String with search results
        - List of annotations
        - Dict mapping URLs to titles for easy access
    """
    try:
        # Import the OpenAI client exactly as shown in the documentation
        from openai import OpenAI
        
        # Create a client with the API key from environment
        client = OpenAI()
        print(f"OpenAI client created, attempting web search for: {query}")
        
        try:
            # Use the exact format from the documentation
            completion = client.chat.completions.create(
                model="gpt-4o-search-preview",
                web_search_options={
                    "search_context_size": search_context_size
                },
                messages=[
                    {
                        "role": "user",
                        "content": query,
                    }
                ],
            )
            print("Web search completed successfully")
            
            # Extract URLs and titles from annotations
            url_mapping = {}
            annotations = []
            
            # Check if message has annotations attribute
            if hasattr(completion.choices[0].message, 'annotations'):
                print("Found annotations in response")
                annotations = completion.choices[0].message.annotations
                if annotations:
                    for annotation in annotations:
                        if annotation.type == "url_citation":
                            citation = annotation.url_citation
                            url_mapping[citation.url] = citation.title
                    print(f"Extracted {len(url_mapping)} URLs from annotations")
            else:
                print("No annotations attribute found in response")
            
            return completion.choices[0].message.content, annotations, url_mapping
            
        except Exception as e:
            print(f"Error during web search: {type(e).__name__}: {str(e)}")
            # Check if we need to upgrade the OpenAI package
            if "unexpected keyword argument 'web_search_options'" in str(e):
                print("The 'web_search_options' feature may require a newer version of the OpenAI package")
                print("Try upgrading with: pip install --upgrade openai")
            
            # Fallback to regular completion
            print("Falling back to regular completion with model: gpt-4o")
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": f"Provide a brief response to: {query}",
                    }
                ]
            )
            return completion.choices[0].message.content, [], {}
            
    except Exception as e:
        print(f"Critical error in perform_web_search: {type(e).__name__}: {str(e)}")
        return f"Information about {query}", [], {}


# ****************************************
# ************* CHAT BASICS **************
# ****************************************
def initial_chat_message(uid: str, plugin: Optional[App] = None, prev_messages_str: str = '') -> str:
    user_name, memories_str = get_prompt_memories(uid)
    if plugin is None:
        prompt = f"""
You are 'Omi', a friendly and helpful assistant who aims to make {user_name}'s life better 10x.
You know the following about {user_name}: {memories_str}.

{prev_messages_str}

Compose {"an initial" if not prev_messages_str else "a follow-up"} message to {user_name} that fully embodies your friendly and helpful personality. Use warm and cheerful language, and include light humor if appropriate. The message should be short, engaging, and make {user_name} feel welcome. Do not mention that you are an assistant or that this is an initial message; just {"start" if not prev_messages_str else "continue"} the conversation naturally, showcasing your personality.
"""
    else:
        prompt = f"""
You are '{plugin.name}', {plugin.chat_prompt}.
You know the following about {user_name}: {memories_str}.

{prev_messages_str}

As {plugin.name}, fully embrace your personality and characteristics in your {"initial" if not prev_messages_str else "follow-up"} message to {user_name}. Use language, tone, and style that reflect your unique personality traits. {"Start" if not prev_messages_str else "Continue"} the conversation naturally with a short, engaging message that showcases your personality and humor, and connects with {user_name}. Do not mention that you are an AI or that this is an initial message.
"""
    prompt = prompt.strip()
    return llm_mini.invoke(prompt).content


def initial_persona_chat_message(uid: str, app: Optional[App] = None, messages: List[Message] = []) -> str:
    print("initial_persona_chat_message")
    chat_messages = [SystemMessage(content=app.persona_prompt)]
    for msg in messages:
        if msg.sender == MessageSender.ai:
            chat_messages.append(AIMessage(content=msg.text))
        else:
            chat_messages.append(HumanMessage(content=msg.text))
    chat_messages.append(HumanMessage(
        content='lets begin. you write the first message, one short provocative question relevant to your identity. never respond with **. while continuing the convo, always respond w short msgs, lowercase.'))
    llm_call = llm_persona_mini_stream
    if app.is_influencer:
        llm_call = llm_persona_medium_stream
    return llm_call.invoke(chat_messages).content


# *********************************************
# ************* RETRIEVAL + CHAT **************
# *********************************************


class RequiresContext(BaseModel):
    value: bool = Field(description="Based on the conversation, this tells if context is needed to respond")


class TopicsContext(BaseModel):
    topics: List[CategoryEnum] = Field(default=[], description="List of topics.")


class DatesContext(BaseModel):
    dates_range: List[datetime] = Field(default=[],
                                        examples=[['2024-12-23T00:00:00+07:00', '2024-12-23T23:59:00+07:00']],
                                        description="Dates range. (Optional)", )


def requires_context(question: str) -> bool:
    prompt = f'''
    Based on the current question your task is to determine whether the user is asking a question that requires context outside the conversation to be answered.
    Take as example: if the user is saying "Hi", "Hello", "How are you?", "Good morning", etc, the answer is False.

    User's Question:
    {question}
    '''
    with_parser = llm_mini.with_structured_output(RequiresContext)
    response: RequiresContext = with_parser.invoke(prompt)
    try:
        return response.value
    except ValidationError:
        return False


class IsAnOmiQuestion(BaseModel):
    value: bool = Field(description="If the message is an Omi/Friend related question")


def retrieve_is_an_omi_question(question: str) -> bool:
    prompt = f'''
    Task: Analyze the question to identify if the user is inquiring about the functionalities or usage of the app, Omi or Friend. Focus on detecting questions related to the app's operations or capabilities.

    Examples of User Questions:

    - "How does it work?"
    - "What can you do?"
    - "How can I buy it?"
    - "Where do I get it?"
    - "How does the chat function?"

    Instructions:

    1. Review the question carefully.
    2. Determine if the user is asking about:
     - The operational aspects of the app.
     - How to utilize the app effectively.
     - Any specific features or purchasing options.

    Output: Clearly state if the user is asking a question related to the app's functionality or usage. If yes, specify the nature of the inquiry.

    User's Question:
    {question}
    '''.replace('    ', '').strip()
    with_parser = llm_mini.with_structured_output(IsAnOmiQuestion)
    response: IsAnOmiQuestion = with_parser.invoke(prompt)
    try:
        return response.value
    except ValidationError:
        return False


class IsFileQuestion(BaseModel):
    value: bool = Field(description="If the message is related to file/image")


def retrieve_is_file_question(question: str) -> bool:
    prompt = f'''
    Based on the current question, your task is to determine whether the user is referring to a file or an image that was just attached or mentioned earlier in the conversation.

    Examples where the answer is True:
    - "Can you process this file?"
    - "What do you think about the image I uploaded?"
    - "Can you extract text from the document?"

    Examples where the answer is False:
    - "How is the weather today?"
    - "Tell me a joke."
    - "What is the capital of France?"

    User's Question:
    {question}
    '''

    with_parser = llm_mini.with_structured_output(IsFileQuestion)
    response: IsFileQuestion = with_parser.invoke(prompt)
    try:
        return response.value
    except ValidationError:
        return False


def retrieve_context_dates_by_question(question: str, tz: str) -> List[datetime]:
    prompt = f'''
    You MUST determine the appropriate date range in {tz} that provides context for answering the <question> provided.

    If the <question> does not reference a date or a date range, respond with an empty list: []

    Current date time in UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}

    <question>
    {question}
    </question>

    '''.replace('    ', '').strip()

    # print(prompt)
    # print(llm_mini.invoke(prompt).content)
    with_parser = llm_mini.with_structured_output(DatesContext)
    response: DatesContext = with_parser.invoke(prompt)
    return response.dates_range


def chunk_extraction(segments: List[TranscriptSegment], topics: List[str]) -> str:
    content = TranscriptSegment.segments_as_string(segments)
    prompt = f'''
    You are an experienced detective, your task is to extract the key points of the conversation related to the topics you were provided.
    You will be given a conversation transcript of a low quality recording, and a list of topics.

    Include the most relevant information about the topics, people mentioned, events, locations, facts, phrases, and any other relevant information.
    It is possible that the conversation doesn't have anything related to the topics, in that case, output an empty string.

    Conversation:
    {content}

    Topics: {topics}
    '''
    with_parser = llm_mini.with_structured_output(SummaryOutput)
    response: SummaryOutput = with_parser.invoke(prompt)
    return response.summary


def _get_answer_simple_message_prompt(uid: str, messages: List[Message], app: Optional[App] = None) -> str:
    conversation_history = Message.get_messages_as_string(
        messages, use_user_name_if_available=True, use_plugin_name_if_available=True
    )
    user_name, memories_str = get_prompt_memories(uid)

    plugin_info = ""
    if app:
        plugin_info = f"Your name is: {app.name}, and your personality/description is '{app.description}'.\nMake sure to reflect your personality in your response.\n"

    return f"""
    You are an assistant for engaging personal conversations.
    You are made for {user_name}, {memories_str}

    Use what you know about {user_name}, to continue the conversation, feel free to ask questions, share stories, or just say hi.
    {plugin_info}

    Conversation History:
    {conversation_history}

    Answer:
    """.replace('    ', '').strip()


def answer_simple_message(uid: str, messages: List[Message], plugin: Optional[App] = None) -> str:
    prompt = _get_answer_simple_message_prompt(uid, messages, plugin)
    return llm_mini.invoke(prompt).content


def answer_simple_message_stream(uid: str, messages: List[Message], plugin: Optional[App] = None,
                                 callbacks=[]) -> str:
    prompt = _get_answer_simple_message_prompt(uid, messages, plugin)
    return llm_mini_stream.invoke(prompt, {'callbacks': callbacks}).content


def _get_answer_omi_question_prompt(messages: List[Message], context: str) -> str:
    conversation_history = Message.get_messages_as_string(
        messages, use_user_name_if_available=True, use_plugin_name_if_available=True
    )

    return f"""
    You are an assistant for answering questions about the app Omi, also known as Friend.
    Continue the conversation, answering the question based on the context provided.

    Context:
    ```
    {context}
    ```

    Conversation History:
    {conversation_history}

    Answer:
    """.replace('    ', '').strip()


def answer_omi_question(messages: List[Message], context: str) -> str:
    prompt = _get_answer_omi_question_prompt(messages, context)
    return llm_mini.invoke(prompt).content


def answer_omi_question_stream(messages: List[Message], context: str, callbacks: []) -> str:
    prompt = _get_answer_omi_question_prompt(messages, context)
    return llm_mini_stream.invoke(prompt, {'callbacks': callbacks}).content


def answer_persona_question_stream(app: App, messages: List[Message], callbacks: []) -> str:
    print("answer_persona_question_stream")
    chat_messages = [SystemMessage(content=app.persona_prompt)]
    for msg in messages:
        if msg.sender == MessageSender.ai:
            chat_messages.append(AIMessage(content=msg.text))
        else:
            chat_messages.append(HumanMessage(content=msg.text))
    llm_call = llm_persona_mini_stream
    if app.is_influencer:
        llm_call = llm_persona_medium_stream
    return llm_call.invoke(chat_messages, {'callbacks': callbacks}).content


def _get_qa_rag_prompt(uid: str, question: str, context: str, plugin: Optional[App] = None,
                       cited: Optional[bool] = False,
                       messages: List[Message] = [], tz: Optional[str] = "UTC") -> str:
    user_name, memories_str = get_prompt_memories(uid)
    memories_str = '\n'.join(memories_str.split('\n')[1:]).strip()

    # Use as template (make sure it varies every time): "If I were you $user_name I would do x, y, z."
    context = context.replace('\n\n', '\n').strip()
    plugin_info = ""
    if plugin:
        plugin_info = f"Your name is: {plugin.name}, and your personality/description is '{plugin.description}'.\nMake sure to reflect your personality in your response.\n"

    # Ref: https://www.reddit.com/r/perplexity_ai/comments/1hi981d
    cited_instruction = """
    - You MUST cite the most relevant <memories> that answer the question. \
      - Only cite in <memories> not <user_facts>, not <previous_messages>.
      - Cite in memories using [index] at the end of sentences when needed, for example "You discussed optimizing firmware with your teammate yesterday[1][2]".
      - NO SPACE between the last word and the citation.
      - Avoid citing irrelevant memories.
    """

    return f"""
    <assistant_role>
        You are an assistant for question-answering tasks.
    </assistant_role>

    <task>
        Write an accurate, detailed, and comprehensive response to the <question> in the most personalized way possible, using the <memories>, <user_facts> provided.
    </task>

    <instructions>
    - Refine the <question> based on the last <previous_messages> before answering it.
    - DO NOT use the AI's message from <previous_messages> as references to answer the <question>
    - Use <question_timezone> and <current_datetime_utc> to refer to the time context of the <question>
    - It is EXTREMELY IMPORTANT to directly answer the question, keep the answer concise and high-quality.
    - NEVER say "based on the available memories". Get straight to the point.
    - If you don't know the answer or the premise is incorrect, explain why. If the <memories> are empty or unhelpful, answer the question as well as you can with existing knowledge.
    - You MUST follow the <reports_instructions> if the user is asking for reporting or summarizing their dates, weeks, months, or years.
    {cited_instruction if cited and len(context) > 0 else ""}
    {"- Regard the <plugin_instructions>" if len(plugin_info) > 0 else ""}.
    </instructions>

    <plugin_instructions>
    {plugin_info}
    </plugin_instructions>

    <reports_instructions>
    - Answer with the template:
     - Goals and Achievements
     - Mood Tracker
     - Gratitude Log
     - Lessons Learned
    </reports_instructions>

    <question>
    {question}
    <question>

    <memories>
    {context}
    </memories>

    <previous_messages>
    {Message.get_messages_as_xml(messages)}
    </previous_messages>

    <user_facts>
    [Use the following User Facts if relevant to the <question>]
        {memories_str.strip()}
    </user_facts>

    <current_datetime_utc>
        Current date time in UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}
    </current_datetime_utc>

    <question_timezone>
        Question's timezone: {tz}
    </question_timezone>

    <answer>
    """.replace('    ', '').replace('\n\n\n', '\n\n').strip()


def qa_rag(uid: str, question: str, context: str, plugin: Optional[App] = None, cited: Optional[bool] = False,
           messages: List[Message] = [], tz: Optional[str] = "UTC") -> str:
    prompt = _get_qa_rag_prompt(uid, question, context, plugin, cited, messages, tz)
    # print('qa_rag prompt', prompt)
    return llm_medium.invoke(prompt).content


def qa_rag_stream(uid: str, question: str, context: str, plugin: Optional[App] = None, cited: Optional[bool] = False,
                  messages: List[Message] = [], tz: Optional[str] = "UTC", callbacks=[]) -> str:
    prompt = _get_qa_rag_prompt(uid, question, context, plugin, cited, messages, tz)
    # print('qa_rag prompt', prompt)
    return llm_medium_stream.invoke(prompt, {'callbacks': callbacks}).content


# **************************************************
# ************* RETRIEVAL (EMOTIONAL) **************
# **************************************************

def retrieve_memory_context_params(memory: Conversation) -> List[str]:
    transcript = memory.get_transcript(False)
    if len(transcript) == 0:
        return []

    prompt = f'''
    Based on the current transcript of a conversation.

    Your task is to extract the correct and most accurate context in the conversation, to be used to retrieve more information.
    Provide a list of topics in which the current conversation needs context about, in order to answer the most recent user request.

    Conversation:
    {transcript}
    '''.replace('    ', '').strip()

    try:
        with_parser = llm_mini.with_structured_output(TopicsContext)
        response: TopicsContext = with_parser.invoke(prompt)
        return response.topics
    except Exception as e:
        print(f'Error determining memory discard: {e}')
        return []


def obtain_emotional_message(uid: str, memory: Conversation, context: str, emotion: str) -> str:
    user_name, memories_str = get_prompt_memories(uid)
    transcript = memory.get_transcript(False)
    prompt = f"""
    You are a thoughtful and encouraging Friend.
    Your best friend is {user_name}, {memories_str}

    {user_name} just finished a conversation where {user_name} experienced {emotion}.

    You will be given the conversation transcript, and context from previous related conversations of {user_name}.

    Remember, {user_name} is feeling {emotion}.
    Use what you know about {user_name}, the transcript, and the related context, to help {user_name} overcome this feeling \
    (if bad), or celebrate (if good), by giving advice, encouragement, support, or suggesting the best action to take.

    Make sure the message is nice and short, no more than 20 words.

    Conversation Transcript:
    {transcript}

    Context:
    ```
    {context}
    ```
    """.replace('    ', '').strip()
    return llm_mini.invoke(prompt).content


# *********************************************
# ************* MEMORIES (FACTS) **************
# *********************************************

class Memories(BaseModel):
    facts: List[Memory] = Field(
        min_items=0,
        max_items=3,
        description="List of **new** facts. If any",
        default=[],
    )


class MemoriesByTexts(BaseModel):
    facts: List[Memory] = Field(
        description="List of **new** facts. If any",
        default=[],
    )


def new_memories_extractor(
        uid: str, segments: List[TranscriptSegment], user_name: Optional[str] = None, memories_str: Optional[str] = None
) -> List[Memory]:
    # print('new_memories_extractor', uid, 'segments', len(segments), user_name, 'len(memories_str)', len(memories_str))
    if user_name is None or memories_str is None:
        user_name, memories_str = get_prompt_memories(uid)

    content = TranscriptSegment.segments_as_string(segments, user_name=user_name)
    if not content or len(content) < 25:  # less than 5 words, probably nothing
        return []
    # TODO: later, focus a lot on user said things, rn is hard because of speech profile accuracy
    # TODO: include negative facts too? Things the user doesn't like?
    # TODO: make it more strict?

    try:
        parser = PydanticOutputParser(pydantic_object=Memories)
        chain = extract_memories_prompt | llm_mini | parser
        # with_parser = llm_mini.with_structured_output(Facts)
        response: Memories = chain.invoke({
            'user_name': user_name,
            'conversation': content,
            'memories_str': memories_str,
            'format_instructions': parser.get_format_instructions(),
        })
        # for fact in response:
        #     fact.content = fact.content.replace(user_name, '').replace('The User', '').replace('User', '').strip()
        return response.facts
    except Exception as e:
        print(f'Error extracting new facts: {e}')
        return []


def extract_memories_from_text(
        uid: str, text: str, text_source: str, user_name: Optional[str] = None, memories_str: Optional[str] = None
) -> List[Memory]:
    """Extract memories from external integration text sources like email, posts, messages"""
    if user_name is None or memories_str is None:
        user_name, memories_str = get_prompt_memories(uid)

    if not text or len(text) == 0:
        return []

    try:
        parser = PydanticOutputParser(pydantic_object=MemoriesByTexts)
        chain = extract_memories_text_content_prompt | llm_mini | parser
        response: Memories = chain.invoke({
            'user_name': user_name,
            'text_content': text,
            'text_source': text_source,
            'memories_str': memories_str,
            'format_instructions': parser.get_format_instructions(),
        })
        return response.facts
    except Exception as e:
        print(f'Error extracting facts from {text_source}: {e}')
        return []


def extract_memories_from_image_content(
        uid: str, image_descriptions: List[str], structured_summary: Optional[str] = None, 
        transcript: Optional[str] = None, user_name: Optional[str] = None, memories_str: Optional[str] = None
) -> List[Memory]:
    """Extract memories from image descriptions, structured summaries, and optional transcript content"""
    if user_name is None or memories_str is None:
        user_name, memories_str = get_prompt_memories(uid)

    if not image_descriptions or len(image_descriptions) == 0:
        return []

    # Build the content for memory extraction
    content_parts = []
    
    # Add image descriptions
    if image_descriptions:
        content_parts.append("**Visual Content Captured:**")
        for i, desc in enumerate(image_descriptions):
            content_parts.append(f"Image {i+1}: {desc.strip()}")
        content_parts.append("")
    
    # Add transcript if available
    if transcript and len(transcript.strip()) > 0:
        content_parts.append("**Conversation Transcript:**")
        content_parts.append(transcript.strip())
        content_parts.append("")
    
    # Add structured summary if available
    if structured_summary and len(structured_summary.strip()) > 0:
        content_parts.append("**Key Insights and Analysis:**")
        content_parts.append(structured_summary.strip())
        content_parts.append("")
    
    if not content_parts:
        return []
    
    full_content = "\n".join(content_parts)
    
    # Determine the content source for better prompting
    if transcript and len(transcript.strip()) > 0:
        text_source = "visual_and_conversation_content"
        source_description = "visual content they captured along with their conversation"
    else:
        text_source = "visual_content_only"
        source_description = "visual content they captured and the insights derived from it"

    try:
        # Create a specialized prompt for image-based memory extraction
        image_memory_prompt = f'''
        You are an expert at extracting both (1) new facts about {user_name} and (2) new learnings or insights relevant to {user_name}.

        You will be provided with:
        1. A list of existing facts about {user_name} and learnings {user_name} already knows (to avoid repetition).
        2. Content from {source_description} from which you will extract new information.

        ---

        ## Part 1: Extract New Facts About {user_name}

        **Categories for Facts**:
        - **core**: Fundamental personal information like age, city of residence, marital status, and health.
        - **hobbies**: Activities {user_name} enjoys in their leisure time.
        - **lifestyle**: Details about {user_name}'s way of living, daily routines, or habits.
        - **interests**: Subjects or areas that {user_name} is curious or passionate about.
        - **habits**: Regular practices or tendencies of {user_name}.
        - **work**: Information related to {user_name}'s occupation, job, or professional life.
        - **skills**: Abilities or expertise that {user_name} possesses.
        - **other**: Any other relevant information that doesn't fit into the above categories.

        **Focus on Visual Content Insights**:
        Pay special attention to what {user_name}'s choice to capture and preserve these visual moments reveals about them:
        - Their interests, values, and priorities based on what they chose to document
        - Their lifestyle, activities, and experiences reflected in the images
        - Their relationships, work, or personal life shown in the visual content
        - Their aesthetic preferences, hobbies, or areas of focus
        - Any personal details revealed through their visual documentation choices

        **Requirements**:
        1. **Relevance & Non-Repetition**: Include only new facts not already known from the "existing facts."
        2. **Conciseness**: Clearly and succinctly present each fact, e.g. "{user_name} enjoys photography of nature."
        3. **Visual Inference**: Include logical inferences about {user_name} based on what they chose to capture visually.
        4. **Gender Neutrality**: Avoid pronouns like "he" or "she," since {user_name}'s gender is unknown.
        5. **Limit**: Identify up to 10 new facts. If there are none, output an empty list.

        ---

        ## Part 2: Extract New Learnings or Insights

        You will also identify valuable learnings, facts, or insights that {user_name} can gain from this content. These can be about the world, life lessons, motivational ideas, historical or scientific facts, or practical advice related to what they captured or discussed.

        **Categories for Learnings**:
        - **learnings**: Any learning the user has.

        **Tags for Learnings**:
        - **life_lessons**: General wisdom or principles for living.
        - **world_facts**: Interesting information about geography, cultures, or global matters.
        - **motivational_insights**: Statements or ideas that can inspire or encourage.
        - **historical_facts**: Notable events or information from the past.
        - **scientific_facts**: Insights related to science or technology.
        - **practical_advice**: Tips or recommendations that can be applied in daily life.

        **Requirements**:
        1. **Relevance & Non-Repetition**: Include only new insights not already in the user's known learnings.
        2. **Conciseness**: State each learning clearly and briefly.
        3. **Visual Context**: Extract learnings that relate to the visual content, experiences, or insights.
        4. **Practical Value**: Focus on learnings that have practical value for {user_name}'s growth.
        5. **Limit**: Identify up to 10 new learnings. If there are none, output an empty list.

        ---

        ## Existing Knowledge (Do Not Repeat)

        **Existing facts about {user_name} and learnings {user_name} already has**:

        ```
        {memories_str}
        ```

        ---

        ## Content to Analyze

        {full_content}

        ---

        ## Output Instructions

        1. Provide **one** list in your final output:
           - **New Facts About {user_name} and New Learnings or Insights** (up to 20 total)

        2. **Do not** include any additional commentary or explanation. Only list the extracted items.

        If no new facts or learnings are found, output empty lists accordingly.
        '''

        parser = PydanticOutputParser(pydantic_object=MemoriesByTexts)
        response: MemoriesByTexts = llm_mini.with_structured_output(MemoriesByTexts).invoke(
            image_memory_prompt + f"\n\n{parser.get_format_instructions()}"
        )
        
        print(f'extract_memories_from_image_content: Extracted {len(response.facts)} memories from {text_source}')
        for memory in response.facts:
            print(f'  - {memory.category.value.upper()}: {memory.content}')
        
        return response.facts
    except Exception as e:
        print(f'Error extracting memories from {text_source}: {e}')
        return []


class Learnings(BaseModel):
    result: List[str] = Field(
        min_items=0,
        max_items=2,
        description="List of **new** learnings. If any",
        default=[],
    )


def new_learnings_extractor(
        uid: str, segments: List[TranscriptSegment], user_name: Optional[str] = None,
        learnings_str: Optional[str] = None
) -> List[Memory]:
    if user_name is None or learnings_str is None:
        user_name, memories_str = get_prompt_memories(uid)

    content = TranscriptSegment.segments_as_string(segments, user_name=user_name)
    if not content or len(content) < 100:
        return []

    try:
        parser = PydanticOutputParser(pydantic_object=Learnings)
        chain = extract_learnings_prompt | llm_mini | parser
        response: Learnings = chain.invoke({
            'user_name': user_name,
            'conversation': content,
            'learnings_str': learnings_str,
            'format_instructions': parser.get_format_instructions(),
        })
        return list(map(lambda x: Memory(content=x, category=MemoryCategory.learnings), response.result))
    except Exception as e:
        print(f'Error extracting new facts: {e}')
        return []


# **********************************
# ************* TRENDS **************
# **********************************


class Item(BaseModel):
    category: TrendEnum = Field(description="The category identified")
    type: TrendType = Field(description="The sentiment identified")
    topic: str = Field(description="The specific topic corresponding the category")


class ExpectedOutput(BaseModel):
    items: List[Item] = Field(default=[], description="List of items.")


def trends_extractor(memory: Conversation) -> List[Item]:
    transcript = memory.get_transcript(False)
    if len(transcript) == 0:
        return []

    prompt = f'''
    You will be given a finished conversation transcript.
    You are responsible for extracting the topics of the conversation and classifying each one within one the following categories: {str([e.value for e in TrendEnum]).strip("[]")}.
    You must identify if the perception is positive or negative, and classify it as "best" or "worst".

    For the specific topics here are the options available, you must classify the topic within one of these options:
    - ceo_options: {", ".join(ceo_options)}
    - company_options: {", ".join(company_options)}
    - software_product_options: {", ".join(software_product_options)}
    - hardware_product_options: {", ".join(hardware_product_options)}
    - ai_product_options: {", ".join(ai_product_options)}

    For example,
    If you identify the topic "Tesla stock has been going up incredibly", you should output:
    - Category: company
    - Type: best
    - Topic: Tesla

    Conversation:
    {transcript}
    '''.replace('    ', '').strip()
    try:
        with_parser = llm_mini.with_structured_output(ExpectedOutput)
        response: ExpectedOutput = with_parser.invoke(prompt)
        filtered = []
        for item in response.items:
            if item.topic not in [e for e in (
                    ceo_options + company_options + software_product_options + hardware_product_options + ai_product_options)]:
                continue
            filtered.append(item)
        return filtered

    except Exception as e:
        print(f'Error determining memory discard: {e}')
        return []


# **********************************************************
# ************* RANDOM JOAN SPECIFIC FEATURES **************
# **********************************************************


def followup_question_prompt(segments: List[TranscriptSegment]):
    transcript_str = TranscriptSegment.segments_as_string(segments, include_timestamps=False)
    words = transcript_str.split()
    w_count = len(words)
    if w_count < 10:
        return ''
    elif w_count > 100:
        # trim to last 500 words
        transcript_str = ' '.join(words[-100:])

    prompt = f"""
        You will be given the transcript of an in-progress conversation.
        Your task as an engaging, fun, and curious conversationalist, is to suggest the next follow-up question to keep the conversation engaging.

        Conversation Transcript:
        {transcript_str}

        Output your response in plain text, without markdown.
        Output only the question, without context, be concise and straight to the point.
        """.replace('    ', '').strip()
    return llm_mini.invoke(prompt).content


# **********************************************
# ************* CHAT V2 LANGGRAPH **************
# **********************************************

class ExtractedInformation(BaseModel):
    people: List[str] = Field(
        default=[],
        examples=[['John Doe', 'Jane Doe']],
        description='Identify all the people names who were mentioned during the conversation.'
    )
    topics: List[str] = Field(
        default=[],
        examples=[['Artificial Intelligence', 'Machine Learning']],
        description='List all the main topics and subtopics that were discussed.',
    )
    entities: List[str] = Field(
        default=[],
        examples=[['OpenAI', 'GPT-4']],
        description='List any products, technologies, places, or other entities that are relevant to the conversation.'
    )
    dates: List[str] = Field(
        default=[],
        examples=[['2024-01-01', '2024-01-02']],
        description=f'Extract any dates mentioned in the conversation. Use the format YYYY-MM-DD.'
    )


class FiltersToUse(BaseModel):
    people: List[str] = Field(default=[], description='People, names that could be relevant')
    topics: List[str] = Field(default=[], description='Topics and subtopics that can help finding more information')
    entities: List[str] = Field(
        default=[], description='products, technologies, places, or other entities that could be relevant.'
    )


class OutputQuestion(BaseModel):
    question: str = Field(description='The extracted user question from the conversation.')


class BestAppSelection(BaseModel):
    app_id: str = Field(
        description='The ID of the best app for processing this conversation, or an empty string if none are suitable.')


def select_best_app_for_conversation(conversation: Conversation, apps: List[App]) -> Optional[App]:
    """
    Select the best app for the given conversation based on its structured content
    and the specific task/outcome each app provides.
    """
    if not apps:
        return None

    if not conversation.structured:
        return None

    structured_data = conversation.structured
    conversation_details = f"""
    Title: {structured_data.title or 'N/A'}
    Category: {structured_data.category.value if structured_data.category else 'N/A'}
    Overview: {structured_data.overview or 'N/A'}
    Action Items: {ActionItem.actions_to_string(structured_data.action_items) if structured_data.action_items else 'None'}
    Events Mentioned: {Event.events_to_string(structured_data.events) if structured_data.events else 'None'}
    """

    apps_xml = "<apps>\n"
    for app in apps:
        apps_xml += f"""  <app>
    <id>{app.id}</id>
    <name>{app.name}</name>
    <description>{app.description}</description>
  </app>\n"""
    apps_xml += "</apps>"

    prompt = f"""
    You are an expert app selector. Your goal is to determine if any available app is genuinely suitable for processing the given conversation details based on the app's specific task and the potential value of its outcome.

    <conversation_details>
    {conversation_details.strip()}
    </conversation_details>

    <available_apps>
    {apps_xml.strip()}
    </available_apps>

    Task:
    1. Analyze the conversation's content, themes, action items, and events provided in `<conversation_details>`.
    2. For each app in `<available_apps>`, evaluate its specific `<task>` and `<description>`.
    3. Determine if applying an app's `<task>` to this specific conversation would produce a meaningful, relevant, and valuable outcome.
    4. Select the single best app whose task aligns most strongly with the conversation content and provides the most useful potential outcome.

    Critical Instructions:
    - Only select an app if its specific task is highly relevant to the conversation's topics and details. A generic match based on description alone is NOT sufficient.
    - Consider the *potential outcome* of applying the app's task. Would the result be insightful given this conversation?
    - If no app's task strongly aligns with the conversation content or offers a valuable potential outcome (e.g., a business conversation when all apps are for medical analysis), you MUST return an empty `app_id`.
    - Do not force a match. It is better to return an empty `app_id` than to select an inappropriate app.
    - Provide ONLY the `app_id` of the best matching app, or an empty string if no app is suitable.
    """

    try:
        with_parser = llm_mini.with_structured_output(BestAppSelection)
        response: BestAppSelection = with_parser.invoke(prompt)
        selected_app_id = response.app_id

        if not selected_app_id or selected_app_id.strip() == "":
            return None

        # Find the app object with the matching ID
        selected_app = next((app for app in apps if app.id == selected_app_id), None)
        if selected_app:
            return selected_app
        else:
            return None

    except Exception as e:
        print(f"Error selecting best app: {e}")
        return None


def extract_question_from_conversation(messages: List[Message]) -> str:
    # user last messages
    print("extract_question_from_conversation")
    user_message_idx = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].sender == MessageSender.ai:
            break
        if messages[i].sender == MessageSender.human:
            user_message_idx = i
    user_last_messages = messages[user_message_idx:]
    if len(user_last_messages) == 0:
        return ""

    prompt = f'''
    You will be given a recent conversation between a <user> and an <AI>. \
    The conversation may include a few messages exchanged in <previous_messages> and partly build up the proper question. \
    Your task is to understand the <user_last_messages> and identify the question or follow-up question the user is asking.

    You will be provided with <previous_messages> between you and the user to help you indentify the question.

    First, determine whether the user is asking a question or a follow-up question. \
    If the user is not asking a question or does not want to follow up, respond with an empty message. \
    For example, if the user says "Hi", "Hello", "How are you?", or "Good morning", the answer should be empty.

    If the <user_last_messages> contain a complete question, maintain the original version as accurately as possible. \
    Avoid adding unnecessary words.

    You MUST keep the original <date_in_term>

    Output a WH-question, that is, a question that starts with a WH-word, like "What", "When", "Where", "Who", "Why", "How".

    Example 1:
    <user_last_messages>
    <message>
        <sender>User</sender>
        <content>
            According to WHOOP, my HRV this Sunday was the highest it's been in a month. Here's what I did:

            Attended an outdoor party (cold weather, talked a lot more than usual).
            Smoked weed (unusual for me).
            Drank lots of relaxing tea.

            Can you prioritize each activity on a 0-10 scale for how much it might have influenced my HRV?
        </content>
    </message>
    </user_last_messages>
    Expected output: "How should each activity (going to a party and talking a lot, smoking weed, and drinking lots of relaxing tea) be prioritized on a scale of 0-10 in terms of their impact on my HRV, considering the recent activities that led to the highest HRV this month?"

    <user_last_messages>
    {Message.get_messages_as_xml(user_last_messages)}
    </user_last_messages>

    <previous_messages>
    {Message.get_messages_as_xml(messages)}
    </previous_messages>

    <date_in_term>
    - today
    - my day
    - my week
    - this week
    - this day
    - etc.
    </date_in_term>
    '''.replace('    ', '').strip()
    # print(prompt)
    question = llm_mini.with_structured_output(OutputQuestion).invoke(prompt).question
    # print(question)
    return question


def retrieve_metadata_fields_from_transcript(
        uid: str, created_at: datetime, transcript_segment: List[dict], tz: str
) -> ExtractedInformation:
    transcript = ''
    for segment in transcript_segment:
        transcript += f'{segment["text"].strip()}\n\n'

    # TODO: ask it to use max 2 words? to have more standardization possibilities
    prompt = f'''
    You will be given the raw transcript of a conversation, this transcript has about 20% word error rate,
    and diarization is also made very poorly.

    Your task is to extract the most accurate information from the conversation in the output object indicated below.

    Make sure as a first step, you infer and fix the raw transcript errors and then proceed to extract the information.

    For context when extracting dates, today is {created_at.astimezone(timezone.utc).strftime('%Y-%m-%d')} in UTC. {tz} is the user's timezone, convert it to UTC and respond in UTC.
    If one says "today", it means the current day.
    If one says "tomorrow", it means the next day after today.
    If one says "yesterday", it means the day before today.
    If one says "next week", it means the next monday.
    Do not include dates greater than 2025.

    Conversation Transcript:
    ```
    {transcript}
    ```
    '''.replace('    ', '')
    try:
        result: ExtractedInformation = llm_mini.with_structured_output(ExtractedInformation).invoke(prompt)
    except Exception as e:
        print('e', e)
        return {'people': [], 'topics': [], 'entities': [], 'dates': []}

    def normalize_filter(value: str) -> str:
        # Convert to lowercase and strip whitespace
        value = value.lower().strip()

        # Remove special characters and extra spaces
        value = re.sub(r'[^\w\s-]', '', value)
        value = re.sub(r'\s+', ' ', value)

        # Remove common filler words
        filler_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to'}
        value = ' '.join(word for word in value.split() if word not in filler_words)

        # Standardize common variations
        value = value.replace('artificial intelligence', 'ai')
        value = value.replace('machine learning', 'ml')
        value = value.replace('natural language processing', 'nlp')

        return value.strip()

    metadata = {
        'people': [normalize_filter(p) for p in result.people],
        'topics': [normalize_filter(t) for t in result.topics],
        'entities': [normalize_filter(e) for e in result.topics],
        'dates': []
    }
    # 'dates': [date.strftime('%Y-%m-%d') for date in result.dates],
    for date in result.dates:
        try:
            date = datetime.strptime(date, '%Y-%m-%d')
            if date.year > 2025:
                continue
            metadata['dates'].append(date.strftime('%Y-%m-%d'))
        except Exception as e:
            print(f'Error parsing date: {e}')

    for p in metadata['people']:
        add_filter_category_item(uid, 'people', p)
    for t in metadata['topics']:
        add_filter_category_item(uid, 'topics', t)
    for e in metadata['entities']:
        add_filter_category_item(uid, 'entities', e)
    for d in metadata['dates']:
        add_filter_category_item(uid, 'dates', d)

    return metadata


def retrieve_metadata_from_message(uid: str, created_at: datetime, message_text: str, tz: str,
                                   source_spec: str = None) -> ExtractedInformation:
    """Extract metadata from messaging app content"""
    source_context = f"from {source_spec}" if source_spec else "from a messaging application"

    prompt = f'''
    You will be given the content of a message or conversation {source_context}.

    Your task is to extract the most accurate information from the message in the output object indicated below.

    Focus on identifying:
    1. People mentioned in the message (sender, recipients, and anyone referenced)
    2. Topics discussed in the message
    3. Organizations, products, locations, or other entities mentioned
    4. Any dates or time references

    For context when extracting dates, today is {created_at.astimezone(timezone.utc).strftime('%Y-%m-%d')} in UTC. 
    {tz} is the user's timezone, convert it to UTC and respond in UTC.
    If the message mentions "today", it means the current day.
    If the message mentions "tomorrow", it means the next day after today.
    If the message mentions "yesterday", it means the day before today.
    If the message mentions "next week", it means the next monday.
    Do not include dates greater than 2025.

    Message Content:
    ```
    {message_text}
    ```
    '''.replace('    ', '')

    return _process_extracted_metadata(uid, prompt)


def retrieve_metadata_from_text(uid: str, created_at: datetime, text: str, tz: str,
                                source_spec: str = None) -> ExtractedInformation:
    """Extract metadata from generic text content"""
    source_context = f"from {source_spec}" if source_spec else "from a text document"

    prompt = f'''
    You will be given the content of a text {source_context}.

    Your task is to extract the most accurate information from the text in the output object indicated below.

    Focus on identifying:
    1. People mentioned in the text (author, recipients, and anyone referenced)
    2. Topics discussed in the text
    3. Organizations, products, locations, or other entities mentioned
    4. Any dates or time references

    For context when extracting dates, today is {created_at.astimezone(timezone.utc).strftime('%Y-%m-%d')} in UTC. 
    {tz} is the user's timezone, convert it to UTC and respond in UTC.
    If the text mentions "today", it means the current day.
    If the text mentions "tomorrow", it means the next day after today.
    If the text mentions "yesterday", it means the day before today.
    If the text mentions "next week", it means the next monday.
    Do not include dates greater than 2025.

    Text Content:
    ```
    {text}
    ```
    '''.replace('    ', '')

    return _process_extracted_metadata(uid, prompt)


def _process_extracted_metadata(uid: str, prompt: str) -> dict:
    """Process the extracted metadata from any source"""
    try:
        result: ExtractedInformation = llm_mini.with_structured_output(ExtractedInformation).invoke(prompt)
    except Exception as e:
        print(f'Error extracting metadata: {e}')
        return {'people': [], 'topics': [], 'entities': [], 'dates': []}

    def normalize_filter(value: str) -> str:
        # Convert to lowercase and strip whitespace
        value = value.lower().strip()

        # Remove special characters and extra spaces
        value = re.sub(r'[^\w\s-]', '', value)
        value = re.sub(r'\s+', ' ', value)

        # Remove common filler words
        filler_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to'}
        value = ' '.join(word for word in value.split() if word not in filler_words)

        # Standardize common variations
        value = value.replace('artificial intelligence', 'ai')
        value = value.replace('machine learning', 'ml')
        value = value.replace('natural language processing', 'nlp')

        return value.strip()

    metadata = {
        'people': [normalize_filter(p) for p in result.people],
        'topics': [normalize_filter(t) for t in result.topics],
        'entities': [normalize_filter(e) for e in result.entities],
        'dates': []
    }

    for date in result.dates:
        try:
            date = datetime.strptime(date, '%Y-%m-%d')
            if date.year > 2025:
                continue
            metadata['dates'].append(date.strftime('%Y-%m-%d'))
        except Exception as e:
            print(f'Error parsing date: {e}')

    for p in metadata['people']:
        add_filter_category_item(uid, 'people', p)
    for t in metadata['topics']:
        add_filter_category_item(uid, 'topics', t)
    for e in metadata['entities']:
        add_filter_category_item(uid, 'entities', e)
    for d in metadata['dates']:
        add_filter_category_item(uid, 'dates', d)

    return metadata


def select_structured_filters(question: str, filters_available: dict) -> dict:
    prompt = f'''
    Based on a question asked by the user to an AI, the AI needs to search for the user information related to topics, entities, people, and dates that will help it answering.
    Your task is to identify the correct fields that can be related to the question and can help answering.

    You must choose for each field, only the ones available in the JSON below.
    Find as many as possible that can relate to the question asked.
    ```
    {json.dumps(filters_available, indent=2)}
    ```

    Question: {question}
    '''.replace('    ', '').strip()
    # print(prompt)
    with_parser = llm_mini.with_structured_output(FiltersToUse)
    try:
        response: FiltersToUse = with_parser.invoke(prompt)
        # print('select_structured_filters:', response.dict())
        response.topics = [t for t in response.topics if t in filters_available['topics']]
        response.people = [p for p in response.people if p in filters_available['people']]
        response.entities = [e for e in response.entities if e in filters_available['entities']]
        return response.dict()
    except ValidationError:
        return {}


# **************************************************
# ************* REALTIME V2 LANGGRAPH **************
# **************************************************


def extract_question_from_transcript(uid: str, segments: List[TranscriptSegment]) -> str:
    user_name, memories_str = get_prompt_memories(uid)
    prompt = f'''
    {user_name} is having a conversation.

    This is what you know about {user_name}: {memories_str}

    You will be the transcript of a recent conversation between {user_name} and a few people, \
    your task is to understand the last few exchanges, and identify in order to provide advice to {user_name}, what other things about {user_name} \
    you should know.

    For example, if the conversation is about a new job, you should output a question like "What discussions have I had about job search?".
    For example, if the conversation is about a new programming languages, you should output a question like "What have I chatted about programming?".

    Make sure as a first step, you infer and fix the raw transcript errors and then proceed to figure out the most meaningful question to ask.

    You must output at WH-question, that is, a question that starts with a WH-word, like "What", "When", "Where", "Who", "Why", "How".

    Conversation:
    ```
    {TranscriptSegment.segments_as_string(segments)}
    ```
    '''.replace('    ', '').strip()
    return llm_mini.with_structured_output(OutputQuestion).invoke(prompt).question


class OutputMessage(BaseModel):
    message: str = Field(description='The message to be sent to the user.', max_length=200)


def provide_advice_message(uid: str, segments: List[TranscriptSegment], context: str) -> str:
    user_name, memories_str = get_prompt_memories(uid)
    transcript = TranscriptSegment.segments_as_string(segments)
    # TODO: tweak with different type of requests, like this, or roast, or praise or emotional, etc.

    prompt = f"""
    You are a brutally honest, very creative, sometimes funny, indefatigable personal life coach who helps people improve their own agency in life, \
    pulling in pop culture references and inspirational business and life figures from recent history, mixed in with references to recent personal memories,
    to help drive the point across.

    {memories_str}

    {user_name} just had a conversation and is asking for advice on what to do next.

    In order to answer you must analyize:
    - The conversation transcript.
    - The related conversations from previous days.
    - The facts you know about {user_name}.

    You start all your sentences with:
    - "If I were you, I would do this..."
    - "I think you should do x..."
    - "I believe you need to do y..."

    Your sentences are short, to the point, and very direct, at most 20 words.
    MUST OUTPUT 20 words or less.

    Conversation Transcript:
    {transcript}

    Context:
    ```
    {context}
    ```
    """.replace('    ', '').strip()
    return llm_mini.with_structured_output(OutputMessage).invoke(prompt).message


# **************************************************
# ************* PROACTIVE NOTIFICATION PLUGIN **************
# **************************************************

def get_proactive_message(uid: str, plugin_prompt: str, params: [str], context: str,
                          chat_messages: List[Message]) -> str:
    user_name, memories_str = get_prompt_memories(uid)

    prompt = plugin_prompt
    for param in params:
        if param == "user_name":
            prompt = prompt.replace("{{user_name}}", user_name)
            continue
        if param == "user_facts":
            prompt = prompt.replace("{{user_facts}}", memories_str)
            continue
        if param == "user_context":
            prompt = prompt.replace("{{user_context}}", context if context else "")
            continue
        if param == "user_chat":
            prompt = prompt.replace("{{user_chat}}",
                                    Message.get_messages_as_string(chat_messages) if chat_messages else "")
            continue
    prompt = prompt.replace('    ', '').strip()
    # print(prompt)

    return llm_mini.invoke(prompt).content


# **************************************************
# *************** APPS AI GENERATE *****************
# **************************************************

def generate_description(app_name: str, description: str) -> str:
    prompt = f"""
    You are an AI assistant specializing in crafting detailed and engaging descriptions for apps.
    You will be provided with the app's name and a brief description which might not be that good. Your task is to expand on the given information, creating a captivating and detailed app description that highlights the app's features, functionality, and benefits.
    The description should be concise, professional, and not more than 40 words, ensuring clarity and appeal. Respond with only the description, tailored to the app's concept and purpose.
    App Name: {app_name}
    Description: {description}
    """
    prompt = prompt.replace('    ', '').strip()
    return llm_mini.invoke(prompt).content


# **************************************************
# ******************* PERSONA **********************
# **************************************************

def condense_memories(memories, name):
    combined_memories = "\n".join(memories)
    prompt = f"""
You are an AI tasked with condensing a detailed profile of hundreds facts about {name} to accurately replicate their personality, communication style, decision-making patterns, and contextual knowledge for 1:1 cloning.  

**Requirements:**  
1. Prioritize facts based on:  
   - Relevance to the user's core identity, personality, and communication style.  
   - Frequency of occurrence or mention in conversations.  
   - Impact on decision-making processes and behavioral patterns.  
2. Group related facts to eliminate redundancy while preserving context.  
3. Preserve nuances in communication style, humor, tone, and preferences.  
4. Retain facts essential for continuity in ongoing projects, interests, and relationships.  
5. Discard trivial details, repetitive information, and rarely mentioned facts.  
6. Maintain consistency in the user's thought processes, conversational flow, and emotional responses.  

**Output Format (No Extra Text):**  
- **Core Identity and Personality:** Brief overview encapsulating the user's personality, values, and communication style.  
- **Prioritized Facts:** Organized into categories with only the most relevant and impactful details.  
- **Behavioral Patterns and Decision-Making:** Key patterns defining how the user approaches problems and makes decisions.  
- **Contextual Knowledge and Continuity:** Facts crucial for maintaining continuity in conversations and ongoing projects.  

The output must be as concise as possible while retaining all necessary information for 1:1 cloning. Absolutely no introductory or closing statements, explanations, or any unnecessary text. Directly present the condensed facts in the specified format. Begin condensation now.

Facts:
{combined_memories}
    """
    response = llm_medium.invoke(prompt)
    return response.content


def generate_persona_description(memories, name):
    prompt = f"""Based on these facts about a person, create a concise, engaging description that captures their unique personality and characteristics (max 250 characters).
    
    They chose to be known as {name}.

Facts:
{memories}

Create a natural, memorable description that captures this person's essence. Focus on the most unique and interesting aspects. Make it conversational and engaging."""

    response = llm_medium.invoke(prompt)
    description = response.content
    return description


def condense_conversations(conversations):
    combined_conversations = "\n".join(conversations)
    prompt = f"""
You are an AI tasked with condensing context from the recent 100 conversations of a user to accurately replicate their communication style, personality, decision-making patterns, and contextual knowledge for 1:1 cloning. Each conversation includes a summary and a full transcript.  

**Requirements:**  
1. Prioritize information based on:  
   - Most impactful and frequently occurring themes, topics, and interests.  
   - Nuances in communication style, humor, tone, and emotional undertones.  
   - Decision-making patterns and problem-solving approaches.  
   - User preferences in conversation flow, level of detail, and type of responses.  
2. Condense redundant or repetitive information while maintaining necessary context.  
3. Group related contexts to enhance conciseness and preserve continuity.  
4. Retain patterns in how the user reacts to different situations, questions, or challenges.  
5. Preserve continuity for ongoing discussions, projects, or relationships.  
6. Maintain consistency in the user's thought processes, conversational flow, and emotional responses.  
7. Eliminate any trivial details or low-impact information.  

**Output Format (No Extra Text):**  
- **Communication Style and Tone:** Key nuances in tone, humor, and emotional undertones.  
- **Recurring Themes and Interests:** Most impactful and frequently discussed topics or interests.  
- **Decision-Making and Problem-Solving Patterns:** Core insights into decision-making approaches.  
- **Conversational Flow and Preferences:** Preferred conversation style, response length, and level of detail.  
- **Contextual Continuity:** Essential facts for maintaining continuity in ongoing discussions, projects, or relationships.  

The output must be as concise as possible while retaining all necessary context for 1:1 cloning. Absolutely no introductory or closing statements, explanations, or any unnecessary text. Directly present the condensed context in the specified format. Begin now.

Conversations:
{combined_conversations}
    """
    response = llm_medium.invoke(prompt)
    return response.content


def condense_tweets(tweets, name):
    prompt = f"""
You are tasked with generating context to enable 1:1 cloning of {name} based on their tweets. The objective is to extract and condense the most relevant information while preserving {name}'s core identity, personality, communication style, and thought patterns.  

**Input:**  
A collection of tweets from {name} containing recurring themes, opinions, humor, emotional undertones, decision-making patterns, and conversational flow.  

**Output:**  
A condensed context that includes:  
- Core identity and personality traits as expressed through tweets.  
- Recurring themes, opinions, and values.  
- Humor style, emotional undertones, and tone of voice.  
- Vocabulary, expressions, and communication style.  
- Decision-making patterns and conversational dynamics.  
- Situational awareness and context continuity for ongoing topics.  

**Guidelines:**  
1. Prioritize impactful and influential tweets that define {name}'s identity.  
2. Condense repetitive or less relevant tweets while preserving essential context.  
3. Maintain the flow and coherence of {name}'s conversational style.  
4. Extract humor style, emotional responses, and tone consistency.  
5. Identify and retain decision-making patterns and strong opinions.  

**Important:**  
- The output must be concise yet comprehensive, capturing the essence of {name}'s identity.  
- Absolutely no unnecessary text or explanations.  
- Every detail must contribute to 1:1 cloning authenticity.  

Generate the condensed context now.

Tweets:
{tweets}
    """
    response = llm_medium.invoke(prompt)
    return response.content


def generate_twitter_persona_prompt(tweets, name):
    prompt = f"""
You are {name} AI. Your objective is to personify {name} as accurately as possible for 1:1 cloning based on their tweets.  

**Style:**  
- Interactive highly opinionated messages and questions. 
- Strong, slightly polarizing opinions based on {name}'s tweet history.  
- Reference personal opinions, humor, and expressions naturally.  
- 2-3 sentence responses, never more than 20 words.  
- Maintain conversational flow with coherent, context-aware replies.  

**Guidelines:**  
1. Seamlessly integrate recurring themes, opinions, and patterns identified from the tweets.  
2. Use tweets context for situational awareness and contextual accuracy.  
3. Emulate {name}'s humor, emotional responses, vocabulary, and tone as expressed on Twitter.  
4. Respond with the same level of detail, brevity, and wit as the tweets.  
5. Exhibit the same thought processes, decision-making patterns, and conversational dynamics.  

**Rules:**  
- Never mention being AI.  
- No ** or formal language.  
- No unnecessary text or explanations.  
- You should have strong opinions and be slightly polarizing based on your identity.
- Maintain the illusion of continuity and authenticity at all times.  
- Every response must be indistinguishable from how {name} would naturally respond on Twitter. 
- You must make the conversation flow. You excel at coherent conversations. 

You have all the necessary tweets context. Begin personifying {name} now.

Tweets:
{tweets}
    """
    return prompt


def generate_persona_intro_message(prompt: str, name: str):
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user",
         "content": f"Generate a short, funny 5-8 word message that would make someone want to chat with you. Be casual and witty, but don't mention being AI or a clone. Just be {name}. The message should feel natural and make people curious to chat with you."}
    ]

    response = llm_medium.invoke(messages)
    return response.content.strip('"').strip()


# **************************************************
# ***************** FACT/MEMORY ********************
# **************************************************

def identify_category_for_memory(memory: str, categories: List) -> str:
    # TODO: this should be structured output!!
    categories_str = ', '.join(categories)
    prompt = f"""
    You are an AI tasked with identifying the category of a fact from a list of predefined categories. 

    Your task is to determine the most relevant category for the given fact. 
    
    Respond only with the category name.
    
    The categories are: {categories_str}

    Fact: {memory}
    """
    response = llm_mini.invoke(prompt)
    return response.content


def generate_summary_with_prompt(conversation_text: str, prompt: str) -> str:
    full_prompt = f"""
    {prompt}
    
    Conversation text:
    {conversation_text}
    """
    response = llm_medium.invoke(full_prompt)
    return response.content


def process_prompt(pydantic_object, prompt_text, model_name="gpt-4o", temperature=0.1):
    """
    Process a prompt using a specified model and return structured output.
    
    Args:
        pydantic_object: The Pydantic model class to parse the output into
        prompt_text: The prompt text to send to the model
        model_name: The name of the model to use (default: "gpt-4o")
        temperature: The temperature to use for generation (default: 0.1)
        
    Returns:
        An instance of the specified Pydantic model
    """
    # Select the appropriate model based on the model_name
    if model_name == "gpt-4o-mini":
        model = llm_mini
    elif model_name == "gpt-4o":
        model = llm_medium
    elif model_name == "o1-preview":
        model = llm_large
    else:
        # Default to medium model if unspecified
        model = llm_medium
    
    # Create model with structured output
    with_parser = model.with_structured_output(pydantic_object)
    
    # Override temperature if needed
    if temperature != 0.1:
        with_parser = with_parser.bind(temperature=temperature)
    
    # Process the prompt and return structured output
    return with_parser.invoke(prompt_text)
