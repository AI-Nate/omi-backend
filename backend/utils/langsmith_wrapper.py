import os
from typing import Optional, Callable, Any, Dict, List
from functools import wraps
import logging

# Initialize logging
logger = logging.getLogger(__name__)

# Check if LangSmith is available and properly configured
LANGSMITH_AVAILABLE = False
LANGSMITH_CLIENT = None

try:
    from langsmith import Client
    LANGSMITH_CLIENT = Client(
        api_key=os.environ.get("LANGSMITH_API_KEY"),
        api_url=os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    )
    LANGSMITH_AVAILABLE = True
    logger.info("LangSmith client initialized successfully")
except Exception as e:
    logger.warning(f"LangSmith not available: {e}")
    LANGSMITH_AVAILABLE = False

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
        # Instead of binding callbacks which causes conflicts,
        # we'll wrap the LLM methods to add tracing when called
        class TracedLLM:
            def __init__(self, original_llm, project_name):
                self._original_llm = original_llm
                self._project_name = project_name
                # Copy all attributes from the original LLM
                for attr in dir(original_llm):
                    if not attr.startswith('_') and not callable(getattr(original_llm, attr)):
                        setattr(self, attr, getattr(original_llm, attr))
            
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