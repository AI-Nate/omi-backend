import asyncio
import os
import random
import time
from typing import List, Dict, Optional
from enum import Enum

import websockets
from deepgram import DeepgramClient, DeepgramClientOptions, LiveTranscriptionEvents
from deepgram.clients.live.v1 import LiveOptions

from utils.stt.soniox_util import *

# Define a global lock for Deepgram connection creation
# This ensures we don't create multiple connections simultaneously
DEEPGRAM_LOCK = asyncio.Lock()

# Nova-3 specific lock since it only allows one connection at a time
NOVA3_LOCK = asyncio.Lock()
NOVA3_IN_USE = False

# Environment flag to completely disable nova-3 due to rate limiting issues
NOVA3_ENABLED = os.getenv('DEEPGRAM_ENABLE_NOVA3', '').lower() in ('true', '1', 'yes')
print(f"Nova-3 is {'enabled' if NOVA3_ENABLED else 'disabled'} based on environment setting")

class STTService(str, Enum):
    deepgram = "deepgram"
    soniox = "soniox"
    speechmatics = "speechmatics"

    @staticmethod
    def get_model_name(value):
        if value == STTService.deepgram:
            return 'deepgram_streaming'
        elif value == STTService.soniox:
            return 'soniox_streaming'
        elif value == STTService.speechmatics:
            return 'speechmatics_streaming'


# Languages supported by Soniox
soniox_supported_languages = ['multi','en', 'af', 'sq', 'ar', 'az', 'eu', 'be', 'bn', 'bs', 'bg', 'ca', 'zh', 'hr', 'cs', 'da', 'nl', 'et', 'fi', 'fr', 'gl', 'de', 'el', 'gu', 'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'kk', 'ko', 'lv', 'lt', 'mk', 'ms', 'ml', 'mr', 'no', 'fa', 'pl', 'pt', 'pa', 'ro', 'ru', 'sr', 'sk', 'sl', 'es', 'sw', 'sv', 'tl', 'ta', 'te', 'th', 'tr', 'uk', 'ur', 'vi', 'cy']
soniox_multi_languages = soniox_supported_languages

# Languages supported by Deepgram, nova-2/nova-3 model
deepgram_supported_languages = {'multi','bg','ca', 'zh', 'zh-CN', 'zh-Hans', 'zh-TW', 'zh-Hant', 'zh-HK', 'cs', 'da', 'da-DK', 'nl', 'en', 'en-US', 'en-AU', 'en-GB', 'en-NZ', 'en-IN', 'et', 'fi', 'nl-BE', 'fr', 'fr-CA', 'de', 'de-CH', 'el' 'hi', 'hu', 'id', 'it', 'ja', 'ko', 'ko-KR', 'lv', 'lt', 'ms', 'no', 'pl', 'pt', 'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'es', 'es-419', 'sv', 'sv-SE', 'th', 'th-TH', 'tr', 'uk', 'vi'}
deepgram_nova2_multi_languages = ['multi', 'en', 'es']
deepgram_multi_languages = ["multi", "en", "en-US", "en-AU", "en-GB", "en-NZ", "en-IN", "es", "es-419", "fr", "fr-CA", "de", "hi", "ru", "pt", "pt-BR", "pt-PT", "ja", "it", "nl", "nl-BE"]

def get_stt_service_for_language(language: str):
    # Check if nova-3 is available and enabled - if not, we'll use nova-2
    nova3_available = NOVA3_ENABLED and not NOVA3_IN_USE
    
    if not NOVA3_ENABLED:
        print("Using nova-2-general because nova-3 is disabled by configuration")
    elif NOVA3_IN_USE:
        print("Using nova-2-general because nova-3 is already in use")

    # Deepgram's 'multi', nova-3 (when available and enabled)
    if nova3_available and language in deepgram_multi_languages:
        return STTService.deepgram, 'multi', 'nova-3'

    # Deepgram's 'multi', nova-2
    if language in deepgram_nova2_multi_languages:
        return STTService.deepgram, 'multi', 'nova-2-general'

    # Deepgram
    if language in deepgram_supported_languages:
        return STTService.deepgram, language, 'nova-2-general'

    # Fallback to Deepgram en
    return STTService.deepgram, 'en', 'nova-2-general'


async def send_initial_file_path(file_path: str, transcript_socket_async_send):
    print('send_initial_file_path')
    start = time.time()
    # Reading and sending in chunks
    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(320)
            if not chunk:
                break
            # print('Uploading', len(chunk))
            await transcript_socket_async_send(bytes(chunk))
            await asyncio.sleep(0.0001)  # if it takes too long to transcribe

    print('send_initial_file_path', time.time() - start)


async def send_initial_file(data: List[List[int]], transcript_socket):
    print('send_initial_file2')
    start = time.time()

    # Reading and sending in chunks
    for i in range(0, len(data)):
        chunk = data[i]
        # print('Uploading', chunk)
        transcript_socket.send(bytes(chunk))
        await asyncio.sleep(0.00005)  # if it takes too long to transcribe

    print('send_initial_file', time.time() - start)


# Calculate backoff with jitter for more effective rate limit handling
def calculate_backoff_with_jitter(attempt, base_delay=2000, max_delay=60000):
    jitter = random.random() * base_delay * 0.5  # Add up to 50% jitter
    backoff = min(((2 ** attempt) * base_delay) + jitter, max_delay)
    return backoff


# Create a new DeepgramClient instance for each connection to avoid shared state issues
def create_deepgram_client(is_beta: bool = False) -> DeepgramClient:
    # Verify API key exists
    deepgram_api_key = os.getenv('DEEPGRAM_API_KEY')
    if not deepgram_api_key:
        raise ValueError("Deepgram API key is not set. Please set the DEEPGRAM_API_KEY environment variable.")
    
    # Configure client options
    client_options = DeepgramClientOptions(
        options={
            "keepalive": "true", 
            "termination_exception_connect": "true",
            "timeout": "60000",  # Increase timeout to 60 seconds
            "max_retries": "5",  # Allow more retries for API calls
        }
    )
    
    # Set appropriate URL based on whether this is the beta API
    if is_beta:
        client_options.url = "https://api.beta.deepgram.com"
    
    # Check for self-hosted configuration
    is_dg_self_hosted = os.getenv('DEEPGRAM_SELF_HOSTED_ENABLED', '').lower() == 'true'
    if is_dg_self_hosted:
        dg_self_hosted_url = os.getenv('DEEPGRAM_SELF_HOSTED_URL')
        if not dg_self_hosted_url:
            raise ValueError("DEEPGRAM_SELF_HOSTED_URL must be set when DEEPGRAM_SELF_HOSTED_ENABLED is true")
        client_options.url = dg_self_hosted_url
    
    # Create and return a fresh client instance
    return DeepgramClient(deepgram_api_key, client_options)


async def process_audio_dg(
    stream_transcript, language: str, sample_rate: int, channels: int, preseconds: int = 0, 
    model: str = 'nova-2-general', websocket_active_check=None
):
    print('process_audio_dg', language, sample_rate, channels, preseconds)

    # If nova-3 is disabled by config and we're trying to use it, fall back immediately
    if model == "nova-3" and not NOVA3_ENABLED:
        print("Nova-3 is disabled by configuration, falling back to nova-2-general")
        model = "nova-2-general"
        is_nova3 = False
    else:
        # Special handling for nova-3 which only allows one connection at a time
        global NOVA3_IN_USE
        is_nova3 = model == "nova-3"
        
        # If trying to use nova-3 and it's already in use, fall back to nova-2
        if is_nova3:
            async with NOVA3_LOCK:
                if NOVA3_IN_USE:
                    print("nova-3 is already in use, falling back to nova-2-general")
                    model = "nova-2-general"
                    is_nova3 = False
                else:
                    NOVA3_IN_USE = True
                    print("Acquired exclusive lock for nova-3")

    def on_message(self, result, **kwargs):
        sentence = result.channel.alternatives[0].transcript
        if len(sentence) == 0:
            return
        
        segments = []
        for word in result.channel.alternatives[0].words:
            is_user = True if word.speaker == 0 and preseconds > 0 else False
            if word.start < preseconds:
                continue
            if not segments:
                segments.append({
                    'speaker': f"SPEAKER_{word.speaker}",
                    'start': word.start - preseconds,
                    'end': word.end - preseconds,
                    'text': word.punctuated_word,
                    'is_user': is_user,
                    'person_id': None,
                })
            else:
                last_segment = segments[-1]
                if last_segment['speaker'] == f"SPEAKER_{word.speaker}":
                    last_segment['text'] += f" {word.punctuated_word}"
                    last_segment['end'] = word.end
                else:
                    segments.append({
                        'speaker': f"SPEAKER_{word.speaker}",
                        'start': word.start,
                        'end': word.end,
                        'text': word.punctuated_word,
                        'is_user': is_user,
                        'person_id': None,
                    })

        stream_transcript(segments)

    def on_speech_started(self, speech_started, **kwargs):
        pass
    
    def on_utterance_end(self, utterance_end, **kwargs):
        pass
    
    def on_unhandled(self, unhandled, **kwargs):
        pass
    
    def on_error(self, error, **kwargs):
        print(f"Deepgram Error: {error}")
    
    def on_close(self, close, **kwargs):
        print("Connection Closed")
        global NOVA3_IN_USE
        if is_nova3:
            # Release nova-3 lock when connection closes
            async def release_nova3():
                async with NOVA3_LOCK:
                    NOVA3_IN_USE = False
                    print("Released exclusive lock for nova-3")
            asyncio.create_task(release_nova3())

    # Attempt to connect with max_retries and backoff strategy
    max_retries = int(os.getenv('DEEPGRAM_MAX_RETRIES', '3'))
    
    # Track if we've already attempted to fall back to nova-2
    tried_fallback = False
    
    try:
        for attempt in range(max_retries):
            try:
                # Check if client is still connected before making another attempt
                if websocket_active_check and not websocket_active_check():
                    print("Client disconnected. Aborting Deepgram connection attempts.")
                    if is_nova3:
                        async with NOVA3_LOCK:
                            NOVA3_IN_USE = False
                            print("Released exclusive lock for nova-3 due to client disconnect")
                    raise Exception("Client disconnected")
                    
                print(f"Connecting to Deepgram (attempt {attempt+1}/{max_retries})")
                
                # Add a guard against rate limits - if we're on attempt > 1 and still using nova-3, try nova-2
                if attempt > 0 and is_nova3 and not tried_fallback:
                    print("Failed with nova-3, falling back to nova-2-general for better reliability")
                    # Release nova-3 lock
                    async with NOVA3_LOCK:
                        NOVA3_IN_USE = False
                        print("Released exclusive lock for nova-3 for fallback to nova-2")
                    # Switch to nova-2
                    model = "nova-2-general"
                    is_nova3 = False
                    tried_fallback = True
                
                # Use a global lock to prevent concurrent connection attempts
                async with DEEPGRAM_LOCK:
                    # Add forced delay between connection attempts (from env or default to 5s)
                    if attempt > 0:
                        connection_delay_ms = int(os.getenv('DEEPGRAM_CONNECTION_DELAY', '5000'))
                        print(f"Waiting {connection_delay_ms}ms before next connection attempt...")
                        await asyncio.sleep(connection_delay_ms / 1000.0)
                    
                    # Create a fresh DeepgramClient for each connection attempt
                    is_beta = (model == "nova-3")
                    client = create_deepgram_client(is_beta=is_beta)
                    
                    # Set up connection
                    print(f"Setting up connection with {'beta' if is_beta else 'standard'} client for {model}")
                    dg_connection = client.listen.websocket.v("1")
                    
                    # Register event handlers
                    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
                    dg_connection.on(LiveTranscriptionEvents.Error, on_error)
                    
                    # Define event callbacks
                    def on_open(self, open, **kwargs):
                        print("Connection Open")
                    
                    def on_metadata(self, metadata, **kwargs):
                        print(f"Metadata: {metadata}")
                    
                    def on_speech_started(self, speech_started, **kwargs):
                        pass
                    
                    def on_utterance_end(self, utterance_end, **kwargs):
                        pass
                    
                    def on_unhandled(self, unhandled, **kwargs):
                        pass
                    
                    # Register additional event handlers
                    dg_connection.on(LiveTranscriptionEvents.Open, on_open)
                    dg_connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
                    dg_connection.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
                    dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
                    dg_connection.on(LiveTranscriptionEvents.Close, on_close)
                    dg_connection.on(LiveTranscriptionEvents.Unhandled, on_unhandled)
                    
                    # Configure transcription options
                    options = LiveOptions(
                        punctuate=True,
                        no_delay=True,
                        endpointing=300,  # Increased from 100 to be less aggressive
                        language=language if language != 'multi' else 'en',  # Use specific language instead of multi
                        interim_results=True,  # Enable interim results for faster response
                        smart_format=True,
                        profanity_filter=False,
                        diarize=True,
                        filler_words=False,
                        channels=channels,
                        multichannel=channels > 1,
                        model=model,
                        sample_rate=sample_rate,
                        encoding='linear16',
                        vad_events=True,  # Enable voice activity detection events
                        utterance_end_ms=1000,  # Shorter utterance end for faster results
                    )
                    
                    # Start the connection with options
                    try:
                        result = dg_connection.start(options)
                        print(f'Deepgram connection started with {model}:', result)
                        return dg_connection
                    except websockets.exceptions.WebSocketException as e:
                        if "HTTP 429" in str(e):
                            print(f"Rate limit exceeded (HTTP 429) when starting connection")
                            # If using nova-3 and getting rate limited, try with nova-2 instead
                            if is_nova3 and not tried_fallback:
                                print("Falling back to nova-2-general due to rate limits with nova-3")
                                # Release nova-3 lock
                                async with NOVA3_LOCK:
                                    NOVA3_IN_USE = False
                                    print("Released exclusive lock for nova-3 due to rate limit")
                                # Retry with nova-2 on the next iteration
                                model = "nova-2-general"
                                is_nova3 = False
                                tried_fallback = True
                            # Let the outer try/except handle the backoff
                            raise
                        elif "HTTP 403" in str(e):
                            print(f"Authentication failed (HTTP 403). Your API key may be invalid or expired.")
                            print(f"API Key: {os.getenv('DEEPGRAM_API_KEY')[:5]}...{os.getenv('DEEPGRAM_API_KEY')[-5:]}")
                            raise Exception(f'Could not open socket: WebSocketException {e}')
                        else:
                            print(f"WebSocket exception: {e}")
                            raise Exception(f'Could not open socket: WebSocketException {e}')
            
            except Exception as e:
                print(f"Failed to connect to Deepgram: {e}")
                
                # Handle rate limits with longer backoff times
                if "HTTP 429" in str(e) or "Rate limit exceeded" in str(e):
                    if is_nova3 and not tried_fallback:
                        # If nova-3 rate limited, immediately try nova-2
                        print("Rate limited with nova-3, immediately falling back to nova-2-general")
                        # Release nova-3 lock
                        async with NOVA3_LOCK:
                            NOVA3_IN_USE = False
                            print("Released exclusive lock for nova-3 due to rate limit exception")
                        # Switch to nova-2 for the next attempt
                        model = "nova-2-general"
                        is_nova3 = False
                        tried_fallback = True
                        continue  # Skip the backoff and retry immediately with nova-2
                        
                    if attempt < max_retries - 1:  # If not the last attempt
                        # Use an aggressive backoff for rate limits
                        backoff_delay = calculate_backoff_with_jitter(
                            attempt,
                            base_delay=int(os.getenv('DEEPGRAM_BACKOFF_BASE', '5000')),
                            max_delay=int(os.getenv('DEEPGRAM_BACKOFF_MAX', '60000'))
                        )
                        print(f"Rate limit exceeded. Waiting {backoff_delay:.0f}ms before retry...")
                        await asyncio.sleep(backoff_delay / 1000)
                    else:
                        print(f"Maximum retry attempts reached for rate limit. Giving up.")
                        # Release nova-3 lock if we were using it
                        if is_nova3:
                            async with NOVA3_LOCK:
                                NOVA3_IN_USE = False
                                print("Released exclusive lock for nova-3 due to max retries")
                        raise Exception("Maximum retry attempts reached for Deepgram rate limit")
                elif "Client disconnected" in str(e):
                    # Don't retry if the client has disconnected
                    # Release nova-3 lock if we were using it
                    if is_nova3:
                        async with NOVA3_LOCK:
                            NOVA3_IN_USE = False
                            print("Released exclusive lock for nova-3 due to client disconnect")
                    raise Exception("Client disconnected")
                else:
                    # For other errors, use a shorter backoff
                    if attempt < max_retries - 1:
                        backoff_delay = calculate_backoff_with_jitter(attempt, base_delay=1000, max_delay=15000)
                        print(f"Error occurred. Waiting {backoff_delay:.0f}ms before retry...")
                        await asyncio.sleep(backoff_delay / 1000)
                    else:
                        print(f"Maximum retry attempts reached. Giving up.")
                        # Release nova-3 lock if we were using it
                        if is_nova3:
                            async with NOVA3_LOCK:
                                NOVA3_IN_USE = False
                                print("Released exclusive lock for nova-3 due to max retries/general error")
                        raise Exception(f"Failed to connect to Deepgram after {max_retries} attempts: {e}")

        # If we get here, all retries failed
        if is_nova3:
            async with NOVA3_LOCK:
                NOVA3_IN_USE = False
                print("Released exclusive lock for nova-3 after all attempts failed")
        raise Exception("Failed to connect to Deepgram after all retry attempts")
    
    except Exception as e:
        # Ensure nova-3 lock is released if any unexpected error occurs
        if is_nova3:
            async with NOVA3_LOCK:
                NOVA3_IN_USE = False
                print("Released exclusive lock for nova-3 due to exception")
        raise e


async def process_audio_soniox(stream_transcript, sample_rate: int, language: str, uid: str, preseconds: int = 0, language_hints: List[str] = []):
    # Soniox supports diarization primarily for English
    api_key = os.getenv('SONIOX_API_KEY')
    if not api_key:
        raise ValueError("SonioxAPI key is not set. Please set the SONIOX_API_KEY environment variable.")

    uri = 'wss://stt-rt.soniox.com/transcribe-websocket'

    # Speaker identification only works with English and 16kHz sample rate
    # New Soniox streaming is not supported speaker indentification
    has_speech_profile = False  # create_user_speech_profile(uid) if uid and sample_rate == 16000 and language == 'en' else False

    # Determine audio format based on sample rate
    audio_format = "s16le" if sample_rate == 16000 else "mulaw"

    # Construct the initial request with all required and optional parameters
    request = {
        'api_key': api_key,
        'model': 'stt-rt-preview',
        'audio_format': audio_format,
        'sample_rate': sample_rate,
        'num_channels': 1,
        'enable_speaker_tags': True,
        'language_hints': language_hints,
    }

    # Add speaker identification if available
    if has_speech_profile:
        request['enable_speaker_identification'] = True
        request['cand_speaker_names'] = [uid]

    try:
        # Connect to Soniox WebSocket
        print("Connecting to Soniox WebSocket...")
        soniox_socket = await websockets.connect(uri, ping_timeout=10, ping_interval=10)
        print("Connected to Soniox WebSocket.")

        # Send the initial request
        await soniox_socket.send(json.dumps(request))
        print(f"Sent initial request: {request}")

        # Variables to track current segment
        current_segment = None
        current_segment_time = None
        current_speaker_id = None

        # Start listening for messages from Soniox
        async def on_message():
            nonlocal current_segment, current_segment_time, current_speaker_id
            try:
                async for message in soniox_socket:
                    response = json.loads(message)
                    # print(response)

                    # Update last message time
                    current_time = time.time()

                    # Check for error responses
                    if 'error_code' in response:
                        error_message = response.get('error_message', 'Unknown error')
                        error_code = response.get('error_code', 0)
                        print(f"Soniox error: {error_code} - {error_message}")
                        raise Exception(f"Soniox error: {error_code} - {error_message}")

                    # Process response based on tokens field
                    if 'tokens' in response:
                        tokens = response.get('tokens', [])

                        if not tokens:
                            if current_segment:
                                stream_transcript([current_segment])
                                current_segment = None
                                current_segment_time = None
                            continue

                        # Extract speaker information and text from tokens
                        new_speaker_id = None
                        speaker_change_detected = False
                        token_texts = []

                        # First check if any token contains a speaker tag
                        for token in tokens:
                            token_text = token['text']
                            if token_text.startswith('spk:'):
                                new_speaker_id = token_text.split(':')[1] if ':' in token_text else "1"
                                speaker_change_detected = (current_speaker_id is not None and
                                                           current_speaker_id != new_speaker_id)
                                current_speaker_id = new_speaker_id
                            else:
                                token_texts.append(token_text)

                        # If no speaker tag found in this response, use the current speaker
                        if new_speaker_id is None and current_speaker_id is not None:
                            new_speaker_id = current_speaker_id
                        elif new_speaker_id is None:
                            new_speaker_id = "1"  # Default speaker

                        # If we have either a speaker change or threshold exceeded, send the current segment and start a new one
                        punctuation_marks = ['.', '?', '!', ',', ';', ':', ' ']
                        time_threshold_exceed = current_segment_time and current_time - current_segment_time > 0.3 and \
                            (current_segment and current_segment['text'][-1] in punctuation_marks)
                        if (speaker_change_detected or time_threshold_exceed) and current_segment:
                            stream_transcript([current_segment])
                            current_segment = None
                            current_segment_time = None

                        # Combine all non-speaker tokens into text
                        content = ''.join(token_texts)

                        # Get timing information
                        start_time = tokens[0]['start_ms'] / 1000.0
                        end_time = tokens[-1]['end_ms'] / 1000.0

                        if preseconds > 0 and start_time < preseconds:
                            # print('Skipping word', start_time)
                            continue

                        # Adjust timing if we have preseconds (for speech profile)
                        if preseconds > 0:
                            start_time -= preseconds
                            end_time -= preseconds

                        # Determine if this is the user based on speaker identification
                        is_user = False
                        if has_speech_profile and new_speaker_id == uid:
                            is_user = True
                        elif preseconds > 0 and new_speaker_id == "1":
                            is_user = True

                        # Create a new segment or append to existing one
                        if current_segment is None:
                            current_segment = {
                                'speaker': f"SPEAKER_0{new_speaker_id}",
                                'start': start_time,
                                'end': end_time,
                                'text': content,
                                'is_user': is_user,
                                'person_id': None
                            }
                            current_segment_time = current_time
                        else:
                            current_segment['text'] += content
                            current_segment['end'] = end_time

                    else:
                        print(f"Unexpected Soniox response format: {response}")
            except websockets.exceptions.ConnectionClosedOK:
                print("Soniox connection closed normally.")
            except Exception as e:
                print(f"Error receiving from Soniox: {e}")
            finally:
                if not soniox_socket.closed:
                    await soniox_socket.close()
                    print("Soniox WebSocket closed in on_message.")

        # Start the coroutines
        asyncio.create_task(on_message())
        asyncio.create_task(soniox_socket.keepalive_ping())

        # Return the Soniox WebSocket object
        return soniox_socket

    except Exception as e:
        print(f"Exception in process_audio_soniox: {e}")
        raise  # Re-raise the exception to be handled by the caller


async def process_audio_speechmatics(stream_transcript, sample_rate: int, language: str, preseconds: int = 0):
    api_key = os.getenv('SPEECHMATICS_API_KEY')
    uri = 'wss://eu2.rt.speechmatics.com/v2'

    request = {
        "message": "StartRecognition",
        "transcription_config": {
            "language": language,
            "diarization": "speaker",
            "operating_point": "enhanced",
            "max_delay_mode": "flexible",
            "max_delay": 3,
            "enable_partials": False,
            "enable_entities": True,
            "speaker_diarization_config": {"max_speakers": 4}
        },
        "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": sample_rate},
        # "audio_events_config": {
        #     "types": [
        #         "laughter",
        #         "music",
        #         "applause"
        #     ]
        # }
    }
    try:
        print("Connecting to Speechmatics WebSocket...")
        socket = await websockets.connect(uri, extra_headers={"Authorization": f"Bearer {api_key}"})
        print("Connected to Speechmatics WebSocket.")

        await socket.send(json.dumps(request))
        print(f"Sent initial request: {request}")

        async def on_message():
            try:
                async for message in socket:
                    response = json.loads(message)
                    if response['message'] == 'AudioAdded':
                        continue
                    if response['message'] == 'AddTranscript':
                        results = response['results']
                        if not results:
                            continue
                        segments = []
                        for r in results:
                            # print(r)
                            if not r['alternatives']:
                                continue

                            r_data = r['alternatives'][0]
                            r_type = r['type']  # word | punctuation
                            r_start = r['start_time']
                            r_end = r['end_time']

                            r_content = r_data['content']
                            r_confidence = r_data['confidence']
                            if r_confidence < 0.4:
                                print('Low confidence:', r)
                                continue
                            r_speaker = r_data['speaker'][1:] if r_data['speaker'] != 'UU' else '1'
                            speaker = f"SPEAKER_0{r_speaker}"

                            is_user = True if r_speaker == '1' and preseconds > 0 else False
                            if r_start < preseconds:
                                # print('Skipping word', r_start, r_content)
                                continue
                            # print(r_content, r_speaker, [r_start, r_end])
                            if not segments:
                                segments.append({
                                    'speaker': speaker,
                                    'start': r_start,
                                    'end': r_end,
                                    'text': r_content,
                                    'is_user': is_user,
                                    'person_id': None,
                                })
                            else:
                                last_segment = segments[-1]
                                if last_segment['speaker'] == speaker:
                                    last_segment['text'] += f' {r_content}'
                                    last_segment['end'] += r_end
                                else:
                                    segments.append({
                                        'speaker': speaker,
                                        'start': r_start,
                                        'end': r_end,
                                        'text': r_content,
                                        'is_user': is_user,
                                        'person_id': None,
                                    })

                        if segments:
                            stream_transcript(segments)
                        # print('---')
                    else:
                        print(response)
            except websockets.exceptions.ConnectionClosedOK:
                print("Speechmatics connection closed normally.")
            except Exception as e:
                print(f"Error receiving from Speechmatics: {e}")
            finally:
                if not socket.closed:
                    await socket.close()
                    print("Speechmatics WebSocket closed in on_message.")

        asyncio.create_task(on_message())
        return socket
    except Exception as e:
        print(f"Exception in process_audio_speechmatics: {e}")
        raise
