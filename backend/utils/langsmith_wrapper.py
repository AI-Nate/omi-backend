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
        # Try to import LangChain tracer
        from langchain_core.tracers.langchain import LangChainTracer
        
        callbacks = []
        
        if add_console_callback:
            try:
                from langchain_core.tracers import ConsoleCallbackHandler
                callbacks.append(ConsoleCallbackHandler())
            except ImportError:
                logger.warning("ConsoleCallbackHandler not available")
        
        # Create a LangChain tracer and add to callbacks
        tracer = LangChainTracer(project_name=project_name)
        callbacks.append(tracer)
        
        # Create a new instance with callbacks
        new_llm = llm.bind(callbacks=callbacks)
        return new_llm
        
    except ImportError as e:
        logger.warning(f"LangChain tracer not available: {e}")
        return llm
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
                    # If @traceable is not available, try the context approach
                    try:
                        from langchain_core.tracers.context import tracing_context
                        
                        # Create a name for the trace
                        run_name = f"{func.__module__}.{func.__name__}"
                        
                        # Add tags
                        run_tags = tags or []
                        
                        # Create a trace context
                        with tracing_context(project_name=project_name, tags=run_tags, run_name=run_name):
                            return func(*args, **kwargs)
                    except ImportError:
                        # Neither approach works, just run the function
                        logger.info("No tracing method available, running function without tracing")
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