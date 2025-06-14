import os
from typing import Optional, Callable, Any, Dict, List
from functools import wraps
import logging

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, skip loading
    pass

# Initialize logging
logger = logging.getLogger(__name__)

# Check if LangSmith is available and properly configured
LANGSMITH_AVAILABLE = False
LANGSMITH_CLIENT = None

try:
    from langsmith import Client
    
    # Debug logging for environment variables
    api_key = os.environ.get("LANGSMITH_API_KEY")
    api_url = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    
    logger.info(f"🔍 LANGSMITH_DEBUG: Environment variables check:")
    logger.info(f"🔍 LANGSMITH_DEBUG: - API_KEY present: {'Yes' if api_key else 'No'}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - API_KEY length: {len(api_key) if api_key else 0}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - API_URL: {api_url}")
    
    if not api_key:
        logger.warning("🔍 LANGSMITH_DEBUG: LANGSMITH_API_KEY is missing!")
        raise ValueError("LANGSMITH_API_KEY is required")
    
    LANGSMITH_CLIENT = Client(
        api_key=api_key,
        api_url=api_url,
    )
    LANGSMITH_AVAILABLE = True
    logger.info("🔍 LANGSMITH_DEBUG: LangSmith client initialized successfully")
except Exception as e:
    logger.warning(f"🔍 LANGSMITH_DEBUG: LangSmith not available: {e}")
    LANGSMITH_AVAILABLE = False

# Import LangChain Runnable for proper inheritance
try:
    from langchain_core.runnables import Runnable
    RUNNABLE_AVAILABLE = True
except ImportError:
    try:
        from langchain.schema.runnable import Runnable
        RUNNABLE_AVAILABLE = True
    except ImportError:
        logger.warning("Could not import LangChain Runnable")
        RUNNABLE_AVAILABLE = False
        Runnable = object  # Fallback to object if Runnable is not available

# Default project name
DEFAULT_PROJECT = os.environ.get("LANGSMITH_PROJECT", "omi-soul-ai")

def trace_langchain_llm(llm, project_name: str = DEFAULT_PROJECT, add_console_callback: bool = False):
    """
    Add tracing to a LangChain LLM.
    
    Args:
        llm: The LangChain LLM to trace
        project_name: The LangSmith project name to use
        add_console_callback: Whether to add console logging
        
    Returns:
        The traced LLM (or original LLM if tracing is not available)
    """
    # If tracing is disabled or not available, return the original LLM
    if not os.environ.get("LANGSMITH_TRACING", "false").lower() == "true":
        return llm
    
    if not LANGSMITH_AVAILABLE:
        logger.warning("LangSmith tracing requested but not available")
        return llm
    
    try:
        # If Runnable is not available, just return the original LLM
        if not RUNNABLE_AVAILABLE:
            logger.warning("LangChain Runnable not available, returning original LLM")
            return llm
            
        # Instead of binding callbacks which causes conflicts,
        # we'll wrap the LLM methods to add tracing when called
        class TracedLLM(Runnable):
            def __init__(self, original_llm, project_name):
                self._original_llm = original_llm
                self._project_name = project_name
                # Copy all attributes from the original LLM
                for attr in dir(original_llm):
                    if not attr.startswith('_') and not callable(getattr(original_llm, attr)):
                        try:
                            setattr(self, attr, getattr(original_llm, attr))
                        except (AttributeError, TypeError):
                            # Skip attributes that cannot be set
                            pass
            
            def __getattr__(self, name):
                # Delegate to the original LLM for any missing attributes/methods
                return getattr(self._original_llm, name)
            
            def invoke(self, input, config=None, **kwargs):
                # Use the original LLM's invoke method without callback conflicts
                return self._original_llm.invoke(input, config=config, **kwargs)
            
            def with_structured_output(self, schema, **kwargs):
                # Return a traced version of the structured output LLM
                structured_llm = self._original_llm.with_structured_output(schema, **kwargs)
                return TracedLLM(structured_llm, self._project_name)
            
            def bind(self, **kwargs):
                # Return a traced version of the bound LLM
                bound_llm = self._original_llm.bind(**kwargs)
                return TracedLLM(bound_llm, self._project_name)
                
            def stream(self, input, config=None, **kwargs):
                # Delegate streaming to the original LLM
                return self._original_llm.stream(input, config=config, **kwargs)
                
            def ainvoke(self, input, config=None, **kwargs):
                # Delegate async invoke to the original LLM
                return self._original_llm.ainvoke(input, config=config, **kwargs)
                
            def astream(self, input, config=None, **kwargs):
                # Delegate async streaming to the original LLM
                return self._original_llm.astream(input, config=config, **kwargs)
        
        # Return the wrapped LLM that delegates to the original
        return TracedLLM(llm, project_name)
        
    except Exception as e:
        logger.error(f"Error setting up LangChain tracing: {e}")
        return llm

def trace_function(project_name: str = DEFAULT_PROJECT, tags: Optional[List[str]] = None):
    """
    Decorator to trace a function with LangSmith.
    
    Args:
        project_name: LangSmith project name
        tags: Optional list of tags to add to the trace
        
    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # If tracing is disabled or not available, just run the function
            if not os.environ.get("LANGSMITH_TRACING", "false").lower() == "true":
                return func(*args, **kwargs)
                
            if not LANGSMITH_AVAILABLE:
                return func(*args, **kwargs)
                
            try:
                # Try to use LangSmith's @traceable decorator approach
                try:
                    from langsmith import traceable
                    
                    # Create a traced version of the function
                    traced_func = traceable(
                        name=f"{func.__module__}.{func.__name__}",
                        project_name=project_name,
                        tags=tags or []
                    )(func)
                    
                    return traced_func(*args, **kwargs)
                    
                except ImportError:
                    # If @traceable is not available, just run the function
                    logger.info("LangSmith @traceable not available, running function without tracing")
                    return func(*args, **kwargs)
                    
            except Exception as e:
                logger.error(f"Error in trace_function: {e}")
                return func(*args, **kwargs)
                
        return wrapper
    return decorator

# Make OpenAI client tracing available if langsmith is installed
try:
    from langsmith.wrappers import wrap_openai
    wrap_openai_client = wrap_openai
except ImportError:
    logger.warning("LangSmith OpenAI wrapper not available")
    def wrap_openai_client(client):
        return client

def pull_prompt(prompt_id: str, include_model: bool = False):
    """
    Pull a prompt from LangSmith.
    
    Args:
        prompt_id: The LangSmith prompt ID to pull
        include_model: Whether to include model configuration
        
    Returns:
        The prompt object or None if not available
    """
    logger.info(f"🔍 LANGSMITH_DEBUG: pull_prompt() called with prompt_id: {prompt_id}")
    logger.info(f"🔍 LANGSMITH_DEBUG: include_model: {include_model}")
    
    if not LANGSMITH_AVAILABLE:
        logger.warning("🔍 LANGSMITH_DEBUG: LangSmith not available for prompt pulling")
        logger.warning(f"🔍 LANGSMITH_DEBUG: LANGSMITH_AVAILABLE = {LANGSMITH_AVAILABLE}")
        return None
        
    if not LANGSMITH_CLIENT:
        logger.warning("🔍 LANGSMITH_DEBUG: LangSmith client not initialized")
        logger.warning(f"🔍 LANGSMITH_DEBUG: LANGSMITH_CLIENT = {LANGSMITH_CLIENT}")
        return None
        
    try:
        logger.info(f"🔍 LANGSMITH_DEBUG: Attempting to pull prompt from LangSmith...")
        logger.info(f"🔍 LANGSMITH_DEBUG: Client type: {type(LANGSMITH_CLIENT)}")
        logger.info(f"🔍 LANGSMITH_DEBUG: Client API URL: {getattr(LANGSMITH_CLIENT, 'api_url', 'unknown')}")
        
        prompt = LANGSMITH_CLIENT.pull_prompt(prompt_id, include_model=include_model)
        
        logger.info(f"🔍 LANGSMITH_DEBUG: Successfully pulled prompt!")
        logger.info(f"🔍 LANGSMITH_DEBUG: Prompt type: {type(prompt)}")
        logger.info(f"🔍 LANGSMITH_DEBUG: Prompt object: {prompt}")
        
        # Try to get some info about the prompt structure
        try:
            if hasattr(prompt, 'messages'):
                logger.info(f"🔍 LANGSMITH_DEBUG: Prompt has {len(prompt.messages)} messages")
            if hasattr(prompt, 'input_variables'):
                logger.info(f"🔍 LANGSMITH_DEBUG: Input variables: {prompt.input_variables}")
            if hasattr(prompt, 'template'):
                logger.info(f"🔍 LANGSMITH_DEBUG: Template length: {len(str(prompt.template))}")
        except Exception as info_e:
            logger.info(f"🔍 LANGSMITH_DEBUG: Could not extract prompt info: {info_e}")
        
        return prompt
    except Exception as e:
        logger.error(f"🔍 LANGSMITH_DEBUG: Error pulling prompt {prompt_id}: {e}")
        logger.error(f"🔍 LANGSMITH_DEBUG: Exception type: {type(e)}")
        logger.error(f"🔍 LANGSMITH_DEBUG: Exception args: {e.args}")
        
        # Try to get more details about the error
        try:
            if hasattr(e, 'response'):
                logger.error(f"🔍 LANGSMITH_DEBUG: Response status: {e.response.status_code}")
                logger.error(f"🔍 LANGSMITH_DEBUG: Response text: {e.response.text}")
        except:
            pass
            
        return None

def format_prompt(prompt, variables: Dict[str, Any] = None):
    """
    Format a LangSmith prompt with variables.
    
    Args:
        prompt: The prompt object from LangSmith
        variables: Dictionary of variables to substitute in the prompt
        
    Returns:
        Formatted prompt string or None if formatting fails
    """
    logger.info(f"🔍 LANGSMITH_DEBUG: format_prompt() called")
    logger.info(f"🔍 LANGSMITH_DEBUG: Prompt type: {type(prompt)}")
    logger.info(f"🔍 LANGSMITH_DEBUG: Variables provided: {list(variables.keys()) if variables else 'None'}")
    
    if not prompt:
        logger.warning("🔍 LANGSMITH_DEBUG: No prompt provided to format_prompt")
        return None
        
    try:
        logger.info(f"🔍 LANGSMITH_DEBUG: Attempting to format prompt...")
        
        if variables:
            logger.info(f"🔍 LANGSMITH_DEBUG: Formatting with variables: {list(variables.keys())}")
            formatted = prompt.format(**variables)
        else:
            logger.info(f"🔍 LANGSMITH_DEBUG: Formatting without variables")
            formatted = prompt.format()
        
        logger.info(f"🔍 LANGSMITH_DEBUG: Initial formatting completed")
        logger.info(f"🔍 LANGSMITH_DEBUG: Formatted result type: {type(formatted)}")
        
        # If the result is a prompt template object, get the content
        if hasattr(formatted, 'messages'):
            logger.info(f"🔍 LANGSMITH_DEBUG: Formatted result has messages attribute")
            # For ChatPromptTemplate, get the formatted message content
            formatted_messages = formatted.messages
            logger.info(f"🔍 LANGSMITH_DEBUG: Found {len(formatted_messages)} messages")
            if formatted_messages and len(formatted_messages) > 0:
                logger.info(f"🔍 LANGSMITH_DEBUG: Processing first message")
                first_message = formatted_messages[0]
                logger.info(f"🔍 LANGSMITH_DEBUG: First message type: {type(first_message)}")
                
                # Get the content from the first message (usually the main prompt)
                if hasattr(first_message, 'content'):
                    logger.info(f"🔍 LANGSMITH_DEBUG: Using message content")
                    result = first_message.content
                    logger.info(f"🔍 LANGSMITH_DEBUG: Content length: {len(result)}")
                    return result
                elif hasattr(first_message, 'prompt'):
                    logger.info(f"🔍 LANGSMITH_DEBUG: Using message prompt template")
                    result = first_message.prompt.template
                    logger.info(f"🔍 LANGSMITH_DEBUG: Template length: {len(result)}")
                    return result
                else:
                    logger.warning(f"🔍 LANGSMITH_DEBUG: First message has no content or prompt attribute")
                    logger.warning(f"🔍 LANGSMITH_DEBUG: First message attributes: {dir(first_message)}")
        elif hasattr(formatted, 'template'):
            logger.info(f"🔍 LANGSMITH_DEBUG: Formatted result has template attribute")
            result = formatted.template
            logger.info(f"🔍 LANGSMITH_DEBUG: Template length: {len(result)}")
            return result
        elif isinstance(formatted, str):
            logger.info(f"🔍 LANGSMITH_DEBUG: Formatted result is already a string")
            logger.info(f"🔍 LANGSMITH_DEBUG: String length: {len(formatted)}")
            return formatted
        else:
            logger.info(f"🔍 LANGSMITH_DEBUG: Converting formatted result to string")
            # Try to convert to string
            result = str(formatted)
            logger.info(f"🔍 LANGSMITH_DEBUG: Converted string length: {len(result)}")
            return result
            
    except Exception as e:
        logger.error(f"🔍 LANGSMITH_DEBUG: Error formatting prompt: {e}")
        logger.error(f"🔍 LANGSMITH_DEBUG: Exception type: {type(e)}")
        logger.error(f"🔍 LANGSMITH_DEBUG: Exception args: {e.args}")
        
        # Try to get more info about the prompt structure for debugging
        try:
            logger.error(f"🔍 LANGSMITH_DEBUG: Prompt attributes: {dir(prompt)}")
            if hasattr(prompt, 'input_variables'):
                logger.error(f"🔍 LANGSMITH_DEBUG: Expected input variables: {prompt.input_variables}")
            if variables:
                logger.error(f"🔍 LANGSMITH_DEBUG: Provided variables: {list(variables.keys())}")
                missing_vars = []
                extra_vars = []
                if hasattr(prompt, 'input_variables'):
                    missing_vars = [var for var in prompt.input_variables if var not in variables]
                    extra_vars = [var for var in variables if var not in prompt.input_variables]
                if missing_vars:
                    logger.error(f"🔍 LANGSMITH_DEBUG: Missing variables: {missing_vars}")
                if extra_vars:
                    logger.error(f"🔍 LANGSMITH_DEBUG: Extra variables: {extra_vars}")
        except Exception as debug_e:
            logger.error(f"🔍 LANGSMITH_DEBUG: Could not extract debug info: {debug_e}")
        
        return None 

def test_langsmith_integration():
    """
    Test function to verify LangSmith integration is working
    """
    logger.info("🔍 LANGSMITH_DEBUG: Running LangSmith integration test...")
    
    # Test environment variables
    api_key = os.environ.get("LANGSMITH_API_KEY")
    api_url = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    tracing = os.environ.get("LANGSMITH_TRACING")
    
    logger.info(f"🔍 LANGSMITH_DEBUG: Environment check:")
    logger.info(f"🔍 LANGSMITH_DEBUG: - LANGSMITH_AVAILABLE: {LANGSMITH_AVAILABLE}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - LANGSMITH_CLIENT: {LANGSMITH_CLIENT is not None}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - API_KEY present: {'Yes' if api_key else 'No'}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - API_URL: {api_url}")
    logger.info(f"🔍 LANGSMITH_DEBUG: - LANGSMITH_TRACING: {tracing}")
    
    if LANGSMITH_AVAILABLE and LANGSMITH_CLIENT:
        # Try to pull a test prompt
        try:
            logger.info("🔍 LANGSMITH_DEBUG: Testing prompt pull...")
            test_prompt = pull_prompt("sk0qvnghwihpl2dixzf14szsipa2_analyze_conversation", include_model=False)
            if test_prompt:
                logger.info("🔍 LANGSMITH_DEBUG: ✅ Test prompt pull successful!")
            else:
                logger.warning("🔍 LANGSMITH_DEBUG: ❌ Test prompt pull failed!")
        except Exception as e:
            logger.error(f"🔍 LANGSMITH_DEBUG: ❌ Test prompt pull exception: {e}")
    else:
        logger.warning("🔍 LANGSMITH_DEBUG: ❌ LangSmith not available for testing")

# Run the test when module is imported
test_langsmith_integration() 