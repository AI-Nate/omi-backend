import os
from typing import Optional, Callable, Any, Dict, List
from functools import wraps
import logging

from langchain_core.language_models import BaseLanguageModel
from langchain_core.callbacks import Callbacks
from langchain_core.tracers.context import tracing_context
from langchain_core.tracers.langchain import LangChainTracer
from langchain_core.tracers import ConsoleCallbackHandler
from langsmith import Client
from langsmith.wrappers import wrap_openai

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize LangSmith client
try:
    langsmith_client = Client(
        api_key=os.environ.get("LANGSMITH_API_KEY"),
        api_url=os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    )
except Exception as e:
    logger.warning(f"Error initializing LangSmith client: {e}")
    langsmith_client = None

# Default project name
DEFAULT_PROJECT = os.environ.get("LANGSMITH_PROJECT", "omi-soul-ai")

def trace_langchain_llm(
    llm: BaseLanguageModel, 
    project_name: str = DEFAULT_PROJECT,
    add_console_callback: bool = False
) -> BaseLanguageModel:
    """
    Add tracing to a LangChain LLM.
    
    Args:
        llm: The LangChain LLM to trace
        project_name: The LangSmith project name to use
        add_console_callback: Whether to add console logging
        
    Returns:
        The traced LLM
    """
    if not os.environ.get("LANGSMITH_TRACING", "false").lower() == "true":
        return llm
    
    callbacks = []
    
    if add_console_callback:
        callbacks.append(ConsoleCallbackHandler())
    
    try:
        # Create a LangChain tracer and add to callbacks
        tracer = LangChainTracer(project_name=project_name)
        callbacks.append(tracer)
        
        # Create a new instance with callbacks
        new_llm = llm.bind(callbacks=callbacks)
        return new_llm
        
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
            if not os.environ.get("LANGSMITH_TRACING", "false").lower() == "true":
                return func(*args, **kwargs)
                
            try:
                # Create a name for the trace
                run_name = f"{func.__module__}.{func.__name__}"
                
                # Add tags
                run_tags = tags or []
                
                # Create a trace context
                with tracing_context(project_name=project_name, tags=run_tags, run_name=run_name):
                    return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in trace_function: {e}")
                return func(*args, **kwargs)
                
        return wrapper
    return decorator

# Make OpenAI client tracing available
wrap_openai_client = wrap_openai 