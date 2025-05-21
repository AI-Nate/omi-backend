import os
import random
import asyncio
import websockets
from urllib.parse import urlparse

PusherAPI = os.getenv('HOSTED_PUSHER_API_URL')

def ensure_websocket_url(url):
    """Ensure the URL uses WebSocket protocol (ws:// or wss://)"""
    if not url:
        raise ValueError("HOSTED_PUSHER_API_URL is not set")
        
    # Parse the URL to get its components
    parsed = urlparse(url)
    
    # If already using WebSocket protocol, return as is
    if parsed.scheme in ['ws', 'wss']:
        return url
        
    # Convert HTTP to WebSocket
    if parsed.scheme == 'http':
        return url.replace('http://', 'ws://')
    elif parsed.scheme == 'https':
        return url.replace('https://', 'wss://')
    else:
        # If no valid scheme is found, assume it's a hostname and add ws://
        if '://' not in url:
            return f"ws://{url}"
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}. Must be http, https, ws, or wss.")

async def connect_to_trigger_pusher(uid: str, sample_rate: int = 8000, retries: int = 3):
    print("connect_to_trigger_pusher", uid)
    for attempt in range(retries):
        try:
            return await _connect_to_trigger_pusher(uid, sample_rate)
        except Exception as error:
            print(f'An error occurred: {error}', uid)
            if attempt == retries - 1:
                raise
        backoff_delay = calculate_backoff_with_jitter(attempt)
        print(f"Waiting {backoff_delay:.0f}ms before next retry...", uid)
        await asyncio.sleep(backoff_delay / 1000)

    raise Exception(f'Could not open socket: All retry attempts failed.', uid)

async def _connect_to_trigger_pusher(uid: str, sample_rate: int = 8000):
    try:
        print("Connecting to Pusher transcripts trigger WebSocket...", uid)
        try:
            ws_host = ensure_websocket_url(PusherAPI)
            print(f"Using WebSocket URL: {ws_host}")
        except ValueError as e:
            print(f"Error with Pusher URL: {e}")
            raise
            
        socket = await websockets.connect(f"{ws_host}/v1/trigger/listen?uid={uid}&sample_rate={sample_rate}")
        print("Connected to Pusher transcripts trigger WebSocket.", uid)
        return socket
    except Exception as e:
        print(f"Exception in connect_to_transcript_pusher: {e}", uid)
        raise


# Calculate backoff with jitter
def calculate_backoff_with_jitter(attempt, base_delay=1000, max_delay=15000):
    jitter = random.random() * base_delay
    backoff = min(((2 ** attempt) * base_delay) + jitter, max_delay)
    return backoff
