import os
import uuid
import asyncio
import struct
from datetime import datetime, timezone, timedelta, time
from enum import Enum

import opuslib
import webrtcvad
from fastapi import APIRouter, Depends
from fastapi.websockets import WebSocketDisconnect, WebSocket
from pydub import AudioSegment
from starlette.websockets import WebSocketState

import database.conversations as conversations_db
import database.users as user_db
from database import redis_db
from database.redis_db import get_cached_user_geolocation
from models.conversation import Conversation, TranscriptSegment, ConversationStatus, Structured, Geolocation
from models.message_event import ConversationEvent, MessageEvent, MessageServiceStatusEvent, LastConversationEvent, TranslationEvent
from models.transcript_segment import Translation
from utils.apps import is_audio_bytes_app_enabled
from utils.conversations.location import get_google_maps_location
from utils.conversations.process_conversation import process_conversation, retrieve_in_progress_conversation
from utils.other.task import safe_create_task
from utils.app_integrations import trigger_external_integrations
from utils.stt.streaming import *
from utils.stt.streaming import get_stt_service_for_language, STTService
from utils.stt.streaming import process_audio_soniox, process_audio_dg, process_audio_speechmatics, send_initial_file_path
from utils.webhooks import get_audio_bytes_webhook_seconds
from utils.pusher import connect_to_trigger_pusher
from utils.translation import translate_text, detect_language
from utils.translation_cache import TranscriptSegmentLanguageCache


from utils.other import endpoints as auth
from utils.other.storage import get_profile_audio_if_exists

router = APIRouter()

async def _process_conversation_with_agent(conversation: Conversation, uid: str) -> Conversation:
    """Process conversation using agent analysis instead of standard pipeline"""
    try:
        from utils.agents.core import create_conversation_agent
        from models.conversation import Structured, ActionItem, Event, ResourceItem
        import uuid
        from datetime import datetime
        
        # Create agent for user
        agent = create_conversation_agent(uid)
        
        # Get transcript text
        transcript = conversation.get_transcript(False)
        
        # Analyze with agent
        result = agent.analyze_conversation(
            transcript=transcript,
            conversation_data={
                "created_at": conversation.created_at.isoformat(),
                "source": conversation.source.value if conversation.source else "omi",
                "category": conversation.structured.category if conversation.structured else "unknown"
            },
            session_id=f"auto_{conversation.id}"
        )
        
        if result.get('status') != 'success':
            print(f"🔴 TRANSCRIBE: Agent analysis failed for conversation {conversation.id}")
            # Fallback to standard processing
            from utils.conversations.process_conversation import process_conversation
            return process_conversation(uid, conversation.language or 'en', conversation)
        
        # Extract structured data from agent analysis
        agent_analysis = result.get('analysis', '')
        retrieved_conversations = result.get('retrieved_conversations', [])
        
        # Extract title from agent analysis result (title is now included in analyze_conversation)
        agent_title = result.get('title', '')
        print(f"🔍 TRANSCRIBE: Agent generated title: '{agent_title}'")
        
        # Extract structured data from agent analysis for other fields
        from routers.agent_conversations import _extract_structured_data_from_agent_analysis
        structured_data = _extract_structured_data_from_agent_analysis(
            agent_analysis, 
            retrieved_conversations,
            transcript
        )
        print(f"🔍 TRANSCRIBE: Agent analysis title: '{structured_data.get('title', 'None')}'")
        
        # Use the agent generated title if available
        if agent_title and agent_title.strip():
            structured_data["title"] = agent_title
            print(f"🔍 TRANSCRIBE: Using agent generated title: '{structured_data['title']}'")
        else:
            print(f"🔍 TRANSCRIBE: Falling back to agent extracted title: '{structured_data.get('title', 'None')}')")
        
        # Update conversation with agent-generated structured data
        conversation.structured = Structured(
            title=structured_data["title"],
            overview=agent_analysis,  # Use agent analysis directly since no title is included
            category=structured_data["category"],
            emoji=structured_data.get("emoji", "🧠")
        )
        
        # Store the full agent analysis
        conversation.structured.agent_analysis = agent_analysis
        
        # Update action items
        if structured_data.get("action_items"):
            conversation.structured.action_items = [
                ActionItem(description=item["content"]) 
                for item in structured_data["action_items"]
            ]
        
        # Update key takeaways
        if structured_data.get("key_takeaways"):
            conversation.structured.key_takeaways = structured_data["key_takeaways"]
        
        # Update things to improve
        if structured_data.get("things_to_improve"):
            conversation.structured.things_to_improve = [
                ResourceItem(content=item["content"], url=item.get("url", ""), title=item.get("title", ""))
                for item in structured_data["things_to_improve"]
            ]
        
        # Update things to learn
        if structured_data.get("things_to_learn"):
            conversation.structured.things_to_learn = [
                ResourceItem(content=item["content"], url=item.get("url", ""), title=item.get("title", ""))
                for item in structured_data["things_to_learn"]
            ]
        
        # Update events
        if structured_data.get("events"):
            conversation.structured.events = [
                Event(
                    title=event["title"],
                    description=event["description"],
                    start=datetime.fromisoformat(event["created_at"]),
                    duration=event["duration"]
                )
                for event in structured_data["events"]
            ]
        
        # Set conversation as completed
        conversation.status = ConversationStatus.completed
        conversation.discarded = False
        
        # Save to database
        conversations_db.upsert_conversation(uid, conversation.dict())
        
        # Clear in-progress conversation from Redis to prevent auto-processing
        redis_db.remove_in_progress_conversation_id(uid)
        print(f"🟢 TRANSCRIBE: Cleared in-progress conversation from Redis to prevent duplicate processing")
        
        # Save structured vector for search
        from utils.conversations.process_conversation import save_structured_vector
        save_structured_vector(uid, conversation)
        
        print(f"🟢 TRANSCRIBE: Agent processing completed for conversation {conversation.id}")
        return conversation
        
    except Exception as e:
        print(f"🔴 TRANSCRIBE: Error in agent processing for conversation {conversation.id}: {e}")
        # Fallback to standard processing
        from utils.conversations.process_conversation import process_conversation
        return process_conversation(uid, conversation.language or 'en', conversation)

async def handle_websocket_text_message(message_text: str, uid: str):
    """Handle text messages sent over WebSocket (commands, etc.)"""
    try:
        import json
        message_data = json.loads(message_text)
        
        # Dev mode sync is now handled via HTTP API endpoint
        # Handle other message types here in the future
        # if message_data.get('type') == 'some_command':
        #     ...
        
        print(f"📡 WEBSOCKET: Received text message type: {message_data.get('type', 'unknown')}")
            
    except json.JSONDecodeError:
        print(f"❌ WEBSOCKET: Invalid JSON message from WebSocket: {message_text}")
    except Exception as e:
        print(f"❌ WEBSOCKET: Error handling WebSocket text message: {e}")

async def _listen(
        websocket: WebSocket, uid: str, language: str = 'en', sample_rate: int = 8000, codec: str = 'pcm8',
        channels: int = 1, include_speech_profile: bool = True, stt_service: STTService = None,
        including_combined_segments: bool = False,
):
    print('_listen', uid, language, sample_rate, codec, include_speech_profile, stt_service)

    if not uid or len(uid) <= 0:
        await websocket.close(code=1008, reason="Bad uid")
        return

    # Frame size, codec
    frame_size: int = 160
    if codec == "opus_fs320":
        codec = "opus"
        frame_size = 320

    # Convert 'auto' to 'multi' for consistency
    language = 'multi' if language == 'auto' else language

    # Determine the best STT service
    stt_service, stt_language, stt_model = get_stt_service_for_language(language)
    if not stt_service or not stt_language:
        await websocket.close(code=1008, reason=f"The language is not supported, {language}")
        return

    try:
        await websocket.accept()
    except RuntimeError as e:
        print(e, uid)
        await websocket.close(code=1011, reason="Dirty state")
        return

    websocket_active = True
    websocket_close_code = 1001  # Going Away, don't close with good from backend

    async def _asend_message_event(msg: MessageEvent):
        nonlocal websocket_active
        print(f"Message: type ${msg.event_type}", uid)
        if not websocket_active:
            return False
        try:
            await websocket.send_json(msg.to_json())
            return True
        except WebSocketDisconnect:
            print("WebSocket disconnected", uid)
            websocket_active = False
        except RuntimeError as e:
            print(f"Can not send message event, error: {e}", uid)

        return False

    def _send_message_event(msg: MessageEvent):
        return asyncio.create_task(_asend_message_event(msg))

    # Heart beat
    started_at = time.time()
    timeout_seconds = 420  # 7m # Soft timeout, should < MODAL_TIME_OUT - 3m
    has_timeout = os.getenv('NO_SOCKET_TIMEOUT') is None
    inactivity_timeout_seconds = 30
    last_audio_received_time = None

    # Send pong every 10s then handle it in the app \
    # since Starlette is not support pong automatically
    async def send_heartbeat():
        print("send_heartbeat", uid)
        nonlocal websocket_active
        nonlocal websocket_close_code
        nonlocal started_at
        nonlocal last_audio_received_time

        try:
            while websocket_active:
                # ping fast
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text("ping")
                else:
                    break

                # timeout
                if has_timeout and time.time() - started_at >= timeout_seconds:
                    print(f"Session timeout is hit by soft timeout {timeout_seconds}", uid)
                    websocket_close_code = 1001
                    websocket_active = False
                    break

                # Inactivity timeout
                if last_audio_received_time and time.time() - last_audio_received_time > inactivity_timeout_seconds:
                    print(f"Session timeout due to inactivity ({inactivity_timeout_seconds}s)", uid)
                    websocket_close_code = 1001
                    websocket_active = False
                    break

                # next
                await asyncio.sleep(10)
        except WebSocketDisconnect:
            print("WebSocket disconnected", uid)
        except Exception as e:
            print(f'Heartbeat error: {e}', uid)
            websocket_close_code = 1011
        finally:
            websocket_active = False

    # Start heart beat
    heartbeat_task = asyncio.create_task(send_heartbeat())

    _send_message_event(MessageServiceStatusEvent(event_type="service_status", status="initiating", status_text="Service Starting"))

    # Validate user
    if not user_db.is_exists_user(uid):
        websocket_active = False
        await websocket.close(code=1008, reason="Bad user")
        return

    # Stream transcript
    async def _trigger_create_conversation_with_delay(delay_seconds: int, finished_at: datetime):
        try:
            await asyncio.sleep(delay_seconds)

            # recheck session
            conversation = retrieve_in_progress_conversation(uid)
            if not conversation:
                print(f"🔄 AUTO_PROCESSING: No in-progress conversation found for user {uid}, auto-processing cancelled")
                return
            if conversation['finished_at'] > finished_at:
                print(f"🔄 AUTO_PROCESSING: Newer conversation detected for user {uid}, auto-processing cancelled")
                return
            
            # 🤖 DEV MODE: Check if conversation was already processed manually
            # This prevents duplicate processing when user manually stops recording in dev mode
            conversation_obj = Conversation(**conversation)
            print(f"🔄 AUTO_PROCESSING: Found in-progress conversation {conversation_obj.id} with status: {conversation_obj.status}")
            
            if conversation_obj.status == ConversationStatus.completed:
                print(f"✅ AUTO_PROCESSING: Conversation {conversation_obj.id} already completed, skipping auto-processing for user {uid}")
                return
            
            print(f"▶️ AUTO_PROCESSING: Proceeding with auto-processing of conversation {conversation_obj.id} for user {uid}")
            
            await _create_current_conversation()
        except asyncio.CancelledError:
            pass

    async def _create_conversation(conversation: dict):
        conversation = Conversation(**conversation)
        if conversation.status != ConversationStatus.processing:
            _send_message_event(ConversationEvent(event_type="memory_processing_started", memory=conversation))
            conversations_db.update_conversation_status(uid, conversation.id, ConversationStatus.processing)
            conversation.status = ConversationStatus.processing

        try:
            # Geolocation
            geolocation = get_cached_user_geolocation(uid)
            if geolocation:
                geolocation = Geolocation(**geolocation)
                conversation.geolocation = get_google_maps_location(geolocation.latitude, geolocation.longitude)

            # Check if user has dev mode enabled for agent processing
            use_agent_processing = redis_db.get_user_dev_mode(uid)
            print(f"🤖 TRANSCRIBE: User {uid} dev mode enabled: {use_agent_processing}")
            
            if use_agent_processing:
                # Use agent processing for dev mode
                print(f"🤖 TRANSCRIBE: Processing conversation {conversation.id} with agent")
                conversation = await _process_conversation_with_agent(conversation, uid)
                messages = trigger_external_integrations(uid, conversation)
            else:
                # Use standard processing
                print(f"📝 TRANSCRIBE: Processing conversation {conversation.id} with standard pipeline")
                conversation = process_conversation(uid, language, conversation)
                messages = trigger_external_integrations(uid, conversation)
        except Exception as e:
            print(f"Error processing conversation: {e}", uid)
            conversations_db.set_conversation_as_discarded(uid, conversation.id)
            conversation.discarded = True
            messages = []

        _send_message_event(ConversationEvent(event_type="memory_created", memory=conversation, messages=messages))

    async def finalize_processing_conversations():
        # handle edge case of conversation was actually processing? maybe later, doesn't hurt really anyway.
        # also fix from getMemories endpoint?
        processing = conversations_db.get_processing_conversations(uid)
        print('finalize_processing_conversations len(processing):', len(processing), uid)
        if not processing or len(processing) == 0:
            return

        # Filter out conversations older than 1 hour to prevent processing stale conversations
        current_time = datetime.now(timezone.utc)
        recent_processing = []
        for conv in processing:
            created_at = conv.get('created_at')
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                elif hasattr(created_at, 'timestamp'):
                    # Handle Firestore timestamp
                    created_at = datetime.fromtimestamp(created_at.timestamp(), timezone.utc)
                
                age_hours = (current_time - created_at).total_seconds() / 3600
                if age_hours <= 1:  # Only process conversations less than 1 hour old
                    recent_processing.append(conv)
                else:
                    print(f'Skipping old conversation {conv.get("id", "unknown")} - age: {age_hours:.1f} hours', uid)
        
        if not recent_processing:
            print('No recent processing conversations found, skipping processing', uid)
            return
            
        print(f'Processing {len(recent_processing)} recent conversations (filtered from {len(processing)})', uid)

        # sleep for 1 second to yeld the network for ws accepted.
        await asyncio.sleep(1)
        for conversation in recent_processing:
            await _create_conversation(conversation)

    # Process processing conversations
    asyncio.create_task(finalize_processing_conversations())

    # Send last completed conversation to client
    async def send_last_conversation():
        last_conversation = conversations_db.get_last_completed_conversation(uid)
        if last_conversation:
            await _send_message_event(LastConversationEvent(memory_id=last_conversation['id']))
    asyncio.create_task(send_last_conversation())

    async def _create_current_conversation():
        print("_create_current_conversation", uid)

        # Reset state variables
        nonlocal seconds_to_trim
        nonlocal seconds_to_add
        seconds_to_trim = None
        seconds_to_add = None

        conversation = retrieve_in_progress_conversation(uid)
        if not conversation or not conversation['transcript_segments']:
            return
        await _create_conversation(conversation)

    conversation_creation_task_lock = asyncio.Lock()
    conversation_creation_task = None
    seconds_to_trim = None
    seconds_to_add = None

    conversation_creation_timeout = 120

    # Process existing conversations
    def _process_in_progess_memories():
        nonlocal conversation_creation_task
        nonlocal seconds_to_add
        nonlocal conversation_creation_timeout
        # Determine previous disconnected socket seconds to add + start processing timer if a conversation in progress
        if existing_conversation := retrieve_in_progress_conversation(uid):
            # segments seconds alignment
            started_at = datetime.fromisoformat(existing_conversation['started_at'].isoformat())
            seconds_to_add = (datetime.now(timezone.utc) - started_at).total_seconds()

            # processing if needed logic
            finished_at = datetime.fromisoformat(existing_conversation['finished_at'].isoformat())
            seconds_since_last_segment = (datetime.now(timezone.utc) - finished_at).total_seconds()
            if seconds_since_last_segment >= conversation_creation_timeout:
                print('_websocket_util processing existing_conversation', existing_conversation['id'], seconds_since_last_segment, uid)
                asyncio.create_task(_create_current_conversation())
            else:
                print('_websocket_util will process', existing_conversation['id'], 'in',
                      conversation_creation_timeout - seconds_since_last_segment, 'seconds')
                conversation_creation_task = asyncio.create_task(
                    _trigger_create_conversation_with_delay(conversation_creation_timeout - seconds_since_last_segment, finished_at)
                )

    _send_message_event(MessageServiceStatusEvent(status="in_progress_memories_processing", status_text="Processing Memories"))
    _process_in_progess_memories()

    def _upsert_in_progress_conversation(segments: List[TranscriptSegment], finished_at: datetime):
        if existing := retrieve_in_progress_conversation(uid):
            conversation = Conversation(**existing)
            conversation.transcript_segments, (starts, ends) = TranscriptSegment.combine_segments(conversation.transcript_segments, segments)
            conversations_db.update_conversation_segments(uid, conversation.id,
                                                          [segment.dict() for segment in conversation.transcript_segments])
            conversations_db.update_conversation_finished_at(uid, conversation.id, finished_at)
            redis_db.set_in_progress_conversation_id(uid, conversation.id)
            return conversation, (starts, ends)

        # new
        started_at = datetime.now(timezone.utc) - timedelta(seconds=segments[0].end - segments[0].start)
        conversation = Conversation(
            id=str(uuid.uuid4()),
            structured=Structured(),
            language=language,
            created_at=started_at,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            transcript_segments=segments,
            status=ConversationStatus.in_progress,
        )
        print('_get_in_progress_conversation new', conversation, uid)
        conversations_db.upsert_conversation(uid, conversation_data=conversation.dict())
        redis_db.set_in_progress_conversation_id(uid, conversation.id)
        return conversation, (0, len(segments))

    async def create_conversation_on_segment_received_task(finished_at: datetime):
        nonlocal conversation_creation_task
        async with conversation_creation_task_lock:
            if conversation_creation_task is not None:
                conversation_creation_task.cancel()
                try:
                    await conversation_creation_task
                except asyncio.CancelledError:
                    print("conversation_creation_task is cancelled now", uid)
            conversation_creation_task = asyncio.create_task(
                _trigger_create_conversation_with_delay(conversation_creation_timeout, finished_at))

    # STT
    # Validate websocket_active before initiating STT
    if not websocket_active or websocket.client_state != WebSocketState.CONNECTED:
        print("websocket was closed", uid)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=websocket_close_code)
            except Exception as e:
                print(f"Error closing WebSocket: {e}", uid)
        return

    # Process STT
    soniox_socket = None
    soniox_socket2 = None
    speechmatics_socket = None
    deepgram_socket = None
    deepgram_socket2 = None
    speech_profile_duration = 0

    realtime_segment_buffers = []

    def stream_transcript(segments):
        nonlocal realtime_segment_buffers
        realtime_segment_buffers.extend(segments)

    async def _process_stt():
        nonlocal websocket_close_code
        nonlocal soniox_socket
        nonlocal soniox_socket2
        nonlocal speechmatics_socket
        nonlocal deepgram_socket
        nonlocal deepgram_socket2
        nonlocal speech_profile_duration
        try:
            file_path, speech_profile_duration = None, 0
            # Thougts: how bee does for recognizing other languages speech profile?
            if (language == 'en' or language == 'auto') and (codec == 'opus' or codec == 'pcm16') and include_speech_profile:
                file_path = get_profile_audio_if_exists(uid)
                speech_profile_duration = AudioSegment.from_wav(file_path).duration_seconds + 5 if file_path else 0

            # DEEPGRAM
            if stt_service == STTService.deepgram:
                # Create a function to check if the WebSocket is still active
                def check_websocket_active():
                    nonlocal websocket_active
                    nonlocal websocket
                    try:
                        return websocket_active and websocket.client_state == WebSocketState.CONNECTED
                    except Exception:
                        return False

                deepgram_socket = await process_audio_dg(
                    stream_transcript, stt_language, sample_rate, 1, 
                    preseconds=speech_profile_duration, model=stt_model,
                    websocket_active_check=check_websocket_active)
                
                if speech_profile_duration:
                    # We'll use the same socket for speech profile data instead of creating a second connection
                    # This helps avoid hitting rate limits
                    async def deepgram_socket_send(data):
                        return deepgram_socket.send(data)
                    
                    safe_create_task(send_initial_file_path(file_path, deepgram_socket_send))

            # SONIOX
            elif stt_service == STTService.soniox:
                # For multi-language detection, provide language hints if available
                hints = None
                if stt_language == 'multi' and language != 'multi':
                    # Include the original language as a hint for multi-language detection
                    hints = [language]

                soniox_socket = await process_audio_soniox(
                    stream_transcript, sample_rate, stt_language,
                    uid if include_speech_profile else None,
                    preseconds=speech_profile_duration,
                    language_hints=hints
                )

                # Create a second socket for initial speech profile if needed
                print("speech_profile_duration", speech_profile_duration)
                print("file_path", file_path)
                if speech_profile_duration and file_path:
                    soniox_socket2 = await process_audio_soniox(
                        stream_transcript, sample_rate, stt_language,
                        uid if include_speech_profile else None,
                        language_hints=hints
                    )

                    safe_create_task(send_initial_file_path(file_path, soniox_socket.send))
                    print('speech_profile soniox duration', speech_profile_duration, uid)
            # SPEECHMATICS
            elif stt_service == STTService.speechmatics:
                speechmatics_socket = await process_audio_speechmatics(
                    stream_transcript, sample_rate, stt_language, preseconds=speech_profile_duration
                )
                if speech_profile_duration:
                    safe_create_task(send_initial_file_path(file_path, speechmatics_socket.send))
                    print('speech_profile speechmatics duration', speech_profile_duration, uid)

        except Exception as e:
            print(f"Initial processing error: {e}", uid)
            websocket_close_code = 1011
            await websocket.close(code=websocket_close_code)
            return

    # Pusher
    #
    def create_pusher_task_handler():
        nonlocal websocket_active

        pusher_ws = None
        pusher_connect_lock = asyncio.Lock()
        pusher_connected = False

        # Transcript
        transcript_ws = None
        segment_buffers = []
        in_progress_conversation_id = None

        def transcript_send(segments, conversation_id):
            nonlocal segment_buffers
            nonlocal in_progress_conversation_id
            in_progress_conversation_id = conversation_id
            segment_buffers.extend(segments)

        async def transcript_consume():
            nonlocal websocket_active
            nonlocal segment_buffers
            nonlocal in_progress_conversation_id
            nonlocal transcript_ws
            nonlocal pusher_connected
            while websocket_active or len(segment_buffers) > 0:
                await asyncio.sleep(1)
                if transcript_ws and len(segment_buffers) > 0:
                    try:
                        # 102|data
                        data = bytearray()
                        data.extend(struct.pack("I", 102))
                        data.extend(bytes(json.dumps({"segments":segment_buffers,"memory_id":in_progress_conversation_id}), "utf-8"))
                        segment_buffers = []  # reset
                        await transcript_ws.send(data)
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"Pusher transcripts Connection closed: {e}", uid)
                        transcript_ws = None
                        pusher_connected = False
                        await reconnect()
                    except Exception as e:
                        print(f"Pusher transcripts failed: {e}", uid)

        # Audio bytes
        audio_bytes_ws = None
        audio_buffers = bytearray()
        audio_bytes_enabled = bool(get_audio_bytes_webhook_seconds(uid)) or is_audio_bytes_app_enabled(uid)

        def audio_bytes_send(audio_bytes):
            nonlocal audio_buffers
            audio_buffers.extend(audio_bytes)

        async def audio_bytes_consume():
            nonlocal websocket_active
            nonlocal audio_buffers
            nonlocal audio_bytes_ws
            nonlocal pusher_connected
            while websocket_active or len(audio_buffers) > 0:
                await asyncio.sleep(1)
                if audio_bytes_ws and len(audio_buffers) > 0:
                    try:
                        # 101|data
                        data = bytearray()
                        data.extend(struct.pack("I", 101))
                        data.extend(audio_buffers.copy())
                        audio_buffers = bytearray()  # reset
                        await audio_bytes_ws.send(data)
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"Pusher audio_bytes Connection closed: {e}", uid)
                        audio_bytes_ws = None
                        pusher_connected = False
                        await reconnect()
                    except Exception as e:
                        print(f"Pusher audio_bytes failed: {e}", uid)

        async def reconnect():
            nonlocal pusher_connected
            nonlocal pusher_connect_lock
            async with pusher_connect_lock:
                if pusher_connected:
                    return
                await connect()

        async def connect():
            nonlocal pusher_ws
            nonlocal transcript_ws
            nonlocal audio_bytes_ws
            nonlocal audio_bytes_enabled
            nonlocal pusher_connected

            try:
                pusher_ws = await connect_to_trigger_pusher(uid, sample_rate)
                pusher_connected = True
                transcript_ws = pusher_ws
                if audio_bytes_enabled:
                    audio_bytes_ws = pusher_ws
            except Exception as e:
                print(f"Exception in connect: {e}")

        async def close(code: int = 1000):
            await pusher_ws.close(code)

        return (connect, close,
                transcript_send, transcript_consume,
                audio_bytes_send if audio_bytes_enabled else None,
                audio_bytes_consume if audio_bytes_enabled else None)

    transcript_send = None
    transcript_consume = None
    audio_bytes_send = None
    audio_bytes_consume = None
    pusher_close = None
    pusher_connect = None

    # Transcripts
    #
    current_conversation_id = None
    translation_enabled = including_combined_segments and stt_language == 'multi'
    language_cache = TranscriptSegmentLanguageCache()

    async def translate(segments: List[TranscriptSegment], conversation_id: str):
        try:
            translated_segments = []
            for segment in segments:
                segment_text = segment.text.strip()
                if not segment_text or len(segment_text) <= 0:
                    continue
                # Check cache for language detection result
                is_previously_target_language, diff_text = language_cache.get_language_result(segment.id, segment_text, language)
                if (is_previously_target_language is None or is_previously_target_language is True) \
                        and diff_text:
                    try:
                        detected_lang = detect_language(diff_text)
                        is_target_language = detected_lang is not None and detected_lang == language

                        # Update cache with the detection result
                        language_cache.update_cache(segment.id, segment_text, is_target_language)

                        # Skip translation if it's the target language
                        if is_target_language:
                            continue
                    except Exception as e:
                        print(f"Language detection error: {e}")
                        # Skip translation if couldn't detect the language
                        continue

                # Translate the text to the target language
                translated_text = translate_text(language, segment.text)

                # Skip, del cache to detect language again
                if translated_text == segment.text:
                    language_cache.delete_cache(segment.id)
                    continue

                # Create a Translation object
                translation = Translation(
                    lang=language,
                    text=translated_text,
                )

                # Check if a translation for this language already exists
                existing_translation_index = None
                for i, trans in enumerate(segment.translations):
                    if trans.lang == language:
                        existing_translation_index = i
                        break

                # Replace existing translation or add a new one
                if existing_translation_index is not None:
                    segment.translations[existing_translation_index] = translation
                else:
                    segment.translations.append(translation)

                translated_segments.append(segment)

            # Update the conversation in the database to persist translations
            if len(translated_segments) > 0:
                conversation = conversations_db.get_conversation(uid, conversation_id)
                if conversation:
                    should_updates = False
                    for segment in translated_segments:
                        for i, existing_segment in enumerate(conversation['transcript_segments']):
                            if existing_segment['id'] == segment.id:
                                conversation['transcript_segments'][i]['translations'] = segment.dict()['translations']
                                should_updates = True
                                break

                    # Update the database
                    if should_updates:
                        conversations_db.update_conversation_segments(
                            uid,
                            conversation_id,
                            conversation['transcript_segments']
                        )

            # Send a translation event to the client with the translated segments
            if websocket_active and len(translated_segments) > 0:
                translation_event = TranslationEvent(
                    segments=[segment.dict() for segment in translated_segments]
                )
                _send_message_event(translation_event)

        except Exception as e:
            print(f"Translation error: {e}", uid)

    async def stream_transcript_process():
        nonlocal websocket_active
        nonlocal realtime_segment_buffers
        nonlocal websocket
        nonlocal seconds_to_trim
        nonlocal current_conversation_id
        nonlocal including_combined_segments
        nonlocal translation_enabled

        while websocket_active or len(realtime_segment_buffers) > 0:
            try:
                await asyncio.sleep(0.3)  # 300ms

                if not realtime_segment_buffers or len(realtime_segment_buffers) == 0:
                    continue

                segments = realtime_segment_buffers.copy()
                realtime_segment_buffers = []

                # Align the start, end segment
                if seconds_to_trim is None:
                    seconds_to_trim = segments[0]["start"]

                finished_at = datetime.now(timezone.utc)
                await create_conversation_on_segment_received_task(finished_at)

                # Segments aligning duration seconds.
                if seconds_to_add:
                    for i, segment in enumerate(segments):
                        segment["start"] += seconds_to_add
                        segment["end"] += seconds_to_add
                        segments[i] = segment
                elif seconds_to_trim:
                    for i, segment in enumerate(segments):
                        segment["start"] -= seconds_to_trim
                        segment["end"] -= seconds_to_trim
                        segments[i] = segment

                transcript_segments, _ = TranscriptSegment.combine_segments([], [TranscriptSegment(**segment) for segment in segments])

                # can trigger race condition? increase soniox utterance?
                conversation, (starts, ends) = _upsert_in_progress_conversation(transcript_segments, finished_at)
                current_conversation_id = conversation.id

                # Send to client
                if including_combined_segments:
                    updates_segments = [segment.dict() for segment in conversation.transcript_segments[starts:ends]]
                else:
                    updates_segments = [segment.dict() for segment in transcript_segments]

                await websocket.send_json(updates_segments)

                # Send to external trigger
                if transcript_send is not None:
                    transcript_send([segment.dict() for segment in transcript_segments], current_conversation_id)

                # Translate
                if translation_enabled:
                    await translate(conversation.transcript_segments[starts:ends], conversation.id)

            except Exception as e:
                print(f'Could not process transcript: error {e}', uid)

    # Audio bytes
    #
    # # Initiate a separate vad for each websocket
    # w_vad = webrtcvad.Vad()
    # w_vad.set_mode(1)

    decoder = opuslib.Decoder(sample_rate, 1)

    # # A  frame must be either 10, 20, or 30 ms in duration
    # def _has_speech(data, sample_rate):
    #     sample_size = 320 if sample_rate == 16000 else 160
    #     offset = 0
    #     while offset < len(data):
    #         sample = data[offset:offset + sample_size]
    #         if len(sample) < sample_size:
    #             sample = sample + bytes([0x00] * (sample_size - len(sample) % sample_size))
    #         has_speech = w_vad.is_speech(sample, sample_rate)
    #         if has_speech:
    #             return True
    #         offset += sample_size
    #     return False

    async def receive_audio(dg_socket1, dg_socket2, soniox_socket, soniox_socket2, speechmatics_socket1):
        nonlocal websocket_active
        nonlocal websocket_close_code
        nonlocal last_audio_received_time

        timer_start = time.time()
        last_audio_received_time = timer_start
        
        try:
            while websocket_active:
                # Handle both text and binary messages
                message = await websocket.receive()
                
                # Handle text messages (dev mode, commands, etc.)
                if message['type'] == 'websocket.receive' and 'text' in message:
                    print(f"🔄 DEV_MODE: Received text message: {message['text']}")
                    await handle_websocket_text_message(message['text'], uid)
                    continue
                
                # Handle binary audio data
                if message['type'] == 'websocket.receive' and 'bytes' in message:
                    data = message['bytes']
                    last_audio_received_time = time.time()
                else:
                    # Skip if no binary data
                    continue
                
                if codec == 'opus' and sample_rate == 16000:
                    data = decoder.decode(bytes(data), frame_size=frame_size)

                # STT
                has_speech = True
                # thinh's comment: disabled cause bad performance
                # if include_speech_profile and codec != 'opus':  # don't do for opus 1.0.4 for now
                #     has_speech = _has_speech(data, sample_rate)

                if has_speech:
                    # Handle Soniox sockets
                    if soniox_socket is not None:
                        elapsed_seconds = time.time() - timer_start
                        if elapsed_seconds > speech_profile_duration or not soniox_socket2:
                            await soniox_socket.send(data)
                            if soniox_socket2:
                                print('Killing soniox_socket2', uid)
                                await soniox_socket2.close()
                                soniox_socket2 = None
                        else:
                            await soniox_socket2.send(data)

                    # Handle Speechmatics socket
                    if speechmatics_socket1 is not None:
                        await speechmatics_socket1.send(data)

                    # Handle Deepgram sockets
                    if dg_socket1 is not None:
                        dg_socket1.send(data)

                # Send to external trigger
                if audio_bytes_send is not None:
                    audio_bytes_send(data)

        except WebSocketDisconnect:
            print("WebSocket disconnected", uid)
        except Exception as e:
            print(f'Could not process audio: error {e}', uid)
            websocket_close_code = 1011
        finally:
            websocket_active = False

    # Ensure resources are properly cleaned up
    async def cleanup_resources():
        nonlocal deepgram_socket, deepgram_socket2, soniox_socket, soniox_socket2, speechmatics_socket
        print("Cleaning up STT resources", uid)
        
        # Close Deepgram connections
        try:
            if deepgram_socket and hasattr(deepgram_socket, 'finish'):
                await deepgram_socket.finish()
                print("Closed primary Deepgram connection", uid)
        except Exception as e:
            print(f"Error closing primary Deepgram connection: {e}", uid)
            
            # The second Deepgram socket is no longer used, but we'll keep the code
            # for backward compatibility for now
            try:
                if deepgram_socket2 and hasattr(deepgram_socket2, 'finish'):
                    await deepgram_socket2.finish()
                    print("Closed secondary Deepgram connection", uid)
            except Exception as e:
                print(f"Error closing secondary Deepgram connection: {e}", uid)
            
        # Close Soniox connections
        try:
            if soniox_socket and not soniox_socket.closed:
                await soniox_socket.close()
                print("Closed primary Soniox connection", uid)
        except Exception as e:
            print(f"Error closing primary Soniox connection: {e}", uid)
            
        try:
            if soniox_socket2 and not soniox_socket2.closed:
                await soniox_socket2.close()
                print("Closed secondary Soniox connection", uid)
        except Exception as e:
            print(f"Error closing secondary Soniox connection: {e}", uid)
            
        # Close Speechmatics connection
        try:
            if speechmatics_socket and not speechmatics_socket.closed:
                await speechmatics_socket.close()
                print("Closed Speechmatics connection", uid)
        except Exception as e:
            print(f"Error closing Speechmatics connection: {e}", uid)
            
        print("STT resources cleanup completed", uid)
    
    
    # Update the main WebSocket handler to call cleanup
    tasks = []
    try:
        # Init STT
        _send_message_event(MessageServiceStatusEvent(status="stt_initiating", status_text="STT Service Starting"))
        await _process_stt()

        # Init pusher
        pusher_connect, pusher_close, \
            transcript_send, transcript_consume, \
            audio_bytes_send, audio_bytes_consume = create_pusher_task_handler()

        # Tasks
        audio_process_task = asyncio.create_task(
            receive_audio(deepgram_socket, deepgram_socket2, soniox_socket, soniox_socket2, speechmatics_socket)
        )
        stream_transcript_task = asyncio.create_task(stream_transcript_process())

        # Pusher tasks
        pusher_tasks = [asyncio.create_task(pusher_connect())]
        if transcript_consume is not None:
            pusher_tasks.append(asyncio.create_task(transcript_consume()))
        if audio_bytes_consume is not None:
            pusher_tasks.append(asyncio.create_task(audio_bytes_consume()))

        _send_message_event(MessageServiceStatusEvent(status="ready"))

        tasks = [audio_process_task, stream_transcript_task, heartbeat_task] + pusher_tasks
        await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        print(f"Error during WebSocket operation: {e}", uid)
    finally:
        # Cancel all running tasks properly
        websocket_active = False
        
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # Wait for all tasks to be cancelled
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                print(f"Error during task cancellation: {e}", uid)
        
        # Ensure resources are cleaned up
        await cleanup_resources()
        
        # Close the client WebSocket if it's still open
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                print("Closing client WebSocket", uid)
                await websocket.close(code=websocket_close_code)
        except Exception as e:
            print(f"Error closing Client WebSocket: {e}", uid)
        
        print("_listen ended", uid)

@router.websocket("/v3/listen")
async def listen_handler_v3(
        websocket: WebSocket, uid: str = Depends(auth.get_current_user_uid), language: str = 'en', sample_rate: int = 8000, codec: str = 'pcm8',
        channels: int = 1, include_speech_profile: bool = True, stt_service: STTService = None
):
    await _listen(websocket, uid, language, sample_rate, codec, channels, include_speech_profile, None)

@router.websocket("/v4/listen")
async def listen_handler(
        websocket: WebSocket, uid: str = Depends(auth.get_current_user_uid), language: str = 'en', sample_rate: int = 8000, codec: str = 'pcm8',
        channels: int = 1, include_speech_profile: bool = True, stt_service: STTService = None
):
    await _listen(websocket, uid, language, sample_rate, codec, channels, include_speech_profile, None, including_combined_segments=True)
