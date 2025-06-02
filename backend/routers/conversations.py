from fastapi import APIRouter, Depends, HTTPException, Request, Body, File, UploadFile, Form
from typing import Optional, List, Dict, Union
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import traceback
from PIL import Image
from PIL.ExifTags import TAGS
import io
import threading

import database.conversations as conversations_db
import database.users as users_db
import database.redis_db as redis_db
from database.vector_db import delete_vector
from models.conversation import *
from models.conversation import SearchRequest

from utils.conversations.process_conversation import process_conversation, retrieve_in_progress_conversation, _extract_memories_from_image_conversation
from utils.conversations.search import search_conversations
from utils.llm import generate_summary_with_prompt, get_transcript_structure, EnhancedSummaryOutput, process_prompt, analyze_image_content
from utils.other import endpoints as auth
from utils.other.storage import get_conversation_recording_if_exists, upload_conversation_image, upload_multiple_conversation_images
from utils.app_integrations import trigger_external_integrations

router = APIRouter()


# Utility functions for image processing
def detect_image_type_from_content(content: bytes) -> str:
    """
    Detect image type using magic bytes (file signatures)
    Returns the detected MIME type or None if not an image
    """
    if len(content) < 12:
        return None
        
    # JPEG signature
    if content[:2] == b'\xff\xd8':
        return 'image/jpeg'
        
    # PNG signature 
    if content[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
        return 'image/png'
        
    # GIF signature
    if content[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
        
    # WEBP signature
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
        
    # BMP signature
    if content[:2] == b'BM':
        return 'image/bmp'
        
    # TIFF signature (little-endian and big-endian)
    if content[:4] in (b'II*\x00', b'MM\x00*'):
        return 'image/tiff'
        
    return None


def extract_image_timestamp(image_data: bytes) -> Optional[datetime]:
    """
    Extract the creation timestamp from image EXIF data and attempt to convert to UTC.
    Returns the UTC datetime when the photo was taken, or local time if timezone cannot be determined.
    """
    try:
        # Create PIL Image from bytes
        image = Image.open(io.BytesIO(image_data))
        
        # Get EXIF data
        exif_data = image.getexif()
        
        if not exif_data:
            print("DEBUG: No EXIF data found in image")
            return None
            
        local_timestamp = None
        gps_info = None
        timezone_offset = None
        
        # Extract timestamp
        timestamp_tags = [
            'DateTimeOriginal',   # Original date/time (preferred)
            'DateTime',           # General date/time
            'DateTimeDigitized',  # Digitized date/time
        ]
        
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, tag_id)
            
            if tag_name in timestamp_tags:
                try:
                    # Parse timestamp format: "YYYY:MM:DD HH:MM:SS"
                    local_timestamp = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    print(f"DEBUG: Found EXIF timestamp - {tag_name}: {local_timestamp}")
                    break
                except (ValueError, TypeError) as e:
                    print(f"DEBUG: Failed to parse timestamp {value}: {e}")
                    continue
                    
        if not local_timestamp:
            print("DEBUG: No valid timestamp found in EXIF data")
            return None
            
        # Try to extract timezone offset information (newer cameras)
        timezone_offset_tags = [
            'OffsetTimeOriginal',  # Timezone offset for DateTimeOriginal
            'OffsetTime',          # Timezone offset for DateTime  
            'OffsetTimeDigitized', # Timezone offset for DateTimeDigitized
        ]
        
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, tag_id)
            if tag_name in timezone_offset_tags and value:
                try:
                    # Parse timezone offset like "+07:00" or "-05:00"
                    if isinstance(value, str) and len(value) >= 6:
                        sign = 1 if value[0] == '+' else -1
                        hours = int(value[1:3])
                        minutes = int(value[4:6])
                        timezone_offset = sign * (hours * 60 + minutes)  # offset in minutes
                        print(f"DEBUG: Found timezone offset from {tag_name}: {value} ({timezone_offset} minutes)")
                        break
                except (ValueError, TypeError) as e:
                    print(f"DEBUG: Failed to parse timezone offset {value}: {e}")
                    
        # Try to extract GPS coordinates
        gps_ifd = exif_data.get_ifd(0x8825)  # GPS IFD tag
        if gps_ifd:
            try:
                lat_ref = gps_ifd.get(1)  # GPSLatitudeRef (N/S)
                lat_dms = gps_ifd.get(2)  # GPSLatitude (degrees, minutes, seconds)
                lon_ref = gps_ifd.get(3)  # GPSLongitudeRef (E/W)  
                lon_dms = gps_ifd.get(4)  # GPSLongitude (degrees, minutes, seconds)
                
                if all([lat_ref, lat_dms, lon_ref, lon_dms]):
                    # Convert DMS to decimal degrees
                    def dms_to_decimal(dms_tuple, ref):
                        degrees = float(dms_tuple[0])
                        minutes = float(dms_tuple[1])
                        seconds = float(dms_tuple[2])
                        decimal = degrees + minutes/60.0 + seconds/3600.0
                        if ref in ['S', 'W']:
                            decimal = -decimal
                        return decimal
                    
                    latitude = dms_to_decimal(lat_dms, lat_ref)
                    longitude = dms_to_decimal(lon_dms, lon_ref)
                    gps_info = (latitude, longitude)
                    print(f"DEBUG: Found GPS coordinates: {latitude}, {longitude}")
                    
            except Exception as e:
                print(f"DEBUG: Error extracting GPS coordinates: {e}")
                
        # Convert to UTC using available information
        if timezone_offset is not None:
            # Use timezone offset from EXIF
            utc_naive = local_timestamp - timedelta(minutes=timezone_offset)
            # Convert to timezone-aware UTC datetime
            import pytz
            utc_timestamp = pytz.UTC.localize(utc_naive)
            print(f"DEBUG: Converted to UTC using EXIF timezone offset: {utc_timestamp}")
            return utc_timestamp
            
        elif gps_info:
            # Use GPS coordinates to determine timezone
            try:
                timezone_name = get_timezone_from_coordinates(gps_info[0], gps_info[1])
                if timezone_name:
                    import pytz
                    local_tz = pytz.timezone(timezone_name)
                    # Localize the naive datetime to the GPS timezone
                    localized_dt = local_tz.localize(local_timestamp)
                    # Convert to UTC timezone-aware datetime
                    utc_timestamp = localized_dt.astimezone(pytz.UTC)
                    print(f"DEBUG: Converted to UTC using GPS timezone ({timezone_name}): {utc_timestamp}")
                    return utc_timestamp
            except Exception as e:
                print(f"DEBUG: Error converting GPS timezone: {e}")
                
        # Fallback: return local time (as before)
        print(f"DEBUG: Could not determine timezone, returning local time: {local_timestamp}")
        return local_timestamp
            
    except Exception as e:
        print(f"DEBUG: Error extracting EXIF timestamp: {e}")
    
    return None


def get_timezone_from_coordinates(latitude: float, longitude: float) -> Optional[str]:
    """
    Get timezone name from GPS coordinates using a geocoding service.
    Returns timezone name like 'America/Los_Angeles' or None if lookup fails.
    """
    try:
        # Option 1: Use timezonefinder library (lightweight, offline)
        try:
            from timezonefinder import TimezoneFinder
            tf = TimezoneFinder()
            timezone_name = tf.timezone_at(lat=latitude, lng=longitude)
            if timezone_name:
                print(f"DEBUG: Found timezone from coordinates: {timezone_name}")
                return timezone_name
        except ImportError:
            print("DEBUG: timezonefinder not installed, trying online service")
            
        # Option 2: Use Google Timezone API (requires API key and internet)
        import os
        import requests
        import time
        
        google_api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        if google_api_key:
            # Use current timestamp for timezone lookup
            timestamp = int(time.time())
            url = f"https://maps.googleapis.com/maps/api/timezone/json"
            params = {
                'location': f"{latitude},{longitude}",
                'timestamp': timestamp,
                'key': google_api_key
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'OK':
                    timezone_name = data.get('timeZoneId')
                    print(f"DEBUG: Found timezone from Google API: {timezone_name}")
                    return timezone_name
                    
    except Exception as e:
        print(f"DEBUG: Error looking up timezone from coordinates: {e}")
        
    return None


def _get_conversation_by_id(uid: str, conversation_id: str) -> dict:
    conversation = conversations_db.get_conversation(uid, conversation_id)
    if conversation is None or conversation.get('deleted', False):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def get_conversation_transcript(conversation: dict) -> str:
    """
    Extract the transcript from a conversation dictionary.
    """
    segments = conversation.get('transcript_segments', [])
    if not segments:
        return ""
    
    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda s: s.get('start_time', 0))
    
    # Build transcript text
    transcript = []
    for segment in sorted_segments:
        speaker = "You" if segment.get('is_user', False) else "Speaker"
        if segment.get('person_id'):
            # Try to get name from person_id
            speaker = segment.get('person_id')
        transcript.append(f"{speaker}: {segment.get('text', '')}")
    
    return "\n".join(transcript)


def _get_conversations_with_photos(uid: str, conversation: Optional[dict] = None) -> List[dict]:
    if conversation is None:
        conversations = conversations_db.get_conversations(uid, 100, 0, include_discarded=True)
    else:
        conversations = [conversation]
    
    conversations_with_photos = []
    for conversation in conversations:
        if conversation.get('photos', []):
            conversations_with_photos.append(conversation)
    
    return conversations_with_photos


@router.post("/v1/conversations", response_model=CreateConversationResponse, tags=['conversations'])
def process_in_progress_conversation(uid: str = Depends(auth.get_current_user_uid)):
    conversation = retrieve_in_progress_conversation(uid)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation in progress not found")
    redis_db.remove_in_progress_conversation_id(uid)

    conversation = Conversation(**conversation)
    conversations_db.update_conversation_status(uid, conversation.id, ConversationStatus.processing)
    conversation = process_conversation(uid, conversation.language, conversation, force_process=True)
    messages = trigger_external_integrations(uid, conversation)
    return CreateConversationResponse(conversation=conversation, messages=messages)


# class TranscriptRequest(BaseModel):
#     transcript: str

# @router.post('/v2/test-memory', response_model= [], tags=['conversations'])
# def process_test_memory(
#         request: TranscriptRequest, uid: str = Depends(auth.get_current_user_uid)
# ):
#   st =  get_transcript_structure(request.transcript, datetime.now(),'en','Asia/Kolkata')
#   return [st.json()]

@router.post('/v1/conversations/{conversation_id}/reprocess', response_model=Conversation, tags=['conversations'])
def reprocess_conversation(
        conversation_id: str, language_code: Optional[str] = None, app_id: Optional[str] = None,
        uid: str = Depends(auth.get_current_user_uid)
):
    """
    Whenever a user wants to reprocess a conversation, or wants to force process a discarded one
    :param conversation_id: The ID of the conversation to reprocess
    :param language_code: Optional language code to use for processing
    :param app_id: Optional app ID to use for processing (if provided, only this app will be triggered)
    :return: The updated conversation after reprocessing.
    """
    conversation = conversations_db.get_conversation(uid, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation = Conversation(**conversation)
    if not language_code:
        language_code = conversation.language or 'en'

    return process_conversation(uid, language_code, conversation, force_process=True, is_reprocess=True, app_id=app_id)


@router.get('/v1/conversations', response_model=List[Conversation], tags=['conversations'])
def get_conversations(limit: int = 100, offset: int = 0, statuses: str = "", include_discarded: bool = True,
                      uid: str = Depends(auth.get_current_user_uid)):
    print('get_conversations', uid, limit, offset, statuses)
    return conversations_db.get_conversations(uid, limit, offset, include_discarded=include_discarded,
                                              statuses=statuses.split(",") if len(statuses) > 0 else [])


@router.get("/v1/conversations/{conversation_id}", response_model=Conversation, tags=['conversations'])
def get_conversation_by_id(conversation_id: str, uid: str = Depends(auth.get_current_user_uid)):
    return _get_conversation_by_id(uid, conversation_id)


@router.patch("/v1/conversations/{conversation_id}/title", tags=['conversations'])
def patch_conversation_title(conversation_id: str, title: str, uid: str = Depends(auth.get_current_user_uid)):
    _get_conversation_by_id(uid, conversation_id)
    conversations_db.update_conversation_title(uid, conversation_id, title)
    return {'status': 'Ok'}


@router.get("/v1/conversations/{conversation_id}/photos", response_model=List[ConversationPhoto],
            tags=['conversations'])
def get_conversation_photos(conversation_id: str, uid: str = Depends(auth.get_current_user_uid)):
    _get_conversation_by_id(uid, conversation_id)
    return conversations_db.get_conversation_photos(uid, conversation_id)


@router.get(
    "/v1/conversations/{conversation_id}/transcripts", response_model=Dict[str, List[TranscriptSegment]],
    tags=['conversations']
)
def get_conversation_transcripts_by_models(conversation_id: str, uid: str = Depends(auth.get_current_user_uid)):
    _get_conversation_by_id(uid, conversation_id)
    return conversations_db.get_conversation_transcripts_by_model(uid, conversation_id)


@router.delete("/v1/conversations/{conversation_id}", status_code=204, tags=['conversations'])
def delete_conversation(conversation_id: str, uid: str = Depends(auth.get_current_user_uid)):
    print('delete_conversation', conversation_id, uid)
    conversations_db.delete_conversation(uid, conversation_id)
    delete_vector(conversation_id)
    return {"status": "Ok"}


@router.get("/v1/conversations/{conversation_id}/recording", response_model=dict, tags=['conversations'])
def conversation_has_audio_recording(conversation_id: str, uid: str = Depends(auth.get_current_user_uid)):
    _get_conversation_by_id(uid, conversation_id)
    return {'has_recording': get_conversation_recording_if_exists(uid, conversation_id) is not None}


@router.patch("/v1/conversations/{conversation_id}/events", response_model=dict, tags=['conversations'])
def set_conversation_events_state(
        conversation_id: str, data: SetConversationEventsStateRequest, uid: str = Depends(auth.get_current_user_uid)
):
    conversation = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation)
    events = conversation.structured.events
    for i, event_idx in enumerate(data.events_idx):
        if event_idx >= len(events):
            continue
        events[event_idx].created = data.values[i]

    conversations_db.update_conversation_events(uid, conversation_id, [event.dict() for event in events])
    return {"status": "Ok"}


@router.patch("/v1/conversations/{conversation_id}/action-items", response_model=dict, tags=['conversations'])
def set_action_item_status(data: SetConversationActionItemsStateRequest, conversation_id: str,
                           uid=Depends(auth.get_current_user_uid)):
    conversation = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation)
    action_items = conversation.structured.action_items
    for i, action_item_idx in enumerate(data.items_idx):
        if action_item_idx >= len(action_items):
            continue
        action_items[action_item_idx].completed = data.values[i]

    conversations_db.update_conversation_action_items(uid, conversation_id,
                                                      [action_item.dict() for action_item in action_items])
    return {"status": "Ok"}


@router.delete("/v1/conversations/{conversation_id}/action-items", response_model=dict, tags=['conversations'])
def delete_action_item(data: DeleteActionItemRequest, conversation_id: str, uid=Depends(auth.get_current_user_uid)):
    print('here inside of delete action item')
    conversation = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation)
    action_items = conversation.structured.action_items
    for i, action_item in enumerate(action_items):
        if action_item.description == data.description:
            action_item.deleted = True
    conversations_db.update_conversation_action_items(uid, conversation_id,
                                                      [action_item.dict() for action_item in action_items])
    return {"status": "Ok"}


@router.patch('/v1/conversations/{conversation_id}/segments/{segment_idx}/assign', response_model=Conversation,
              tags=['conversations'])
def set_assignee_conversation_segment(
        conversation_id: str, segment_idx: int, assign_type: str, value: Optional[str] = None,
        use_for_speech_training: bool = True, uid: str = Depends(auth.get_current_user_uid)
):
    """
    Another complex endpoint.

    Modify the assignee of a segment in the transcript of a conversation.
    But,
    if `use_for_speech_training` is True, the corresponding audio segment will be used for speech training.

    Speech training of whom?

    If `assign_type` is 'is_user', the segment will be used for the user speech training.
    If `assign_type` is 'person_id', the segment will be used for the person with the given id speech training.

    What is required for a segment to be used for speech training?
    1. The segment must have more than 5 words.
    2. The conversation audio file shuold be already stored in the user's bucket.

    :return: The updated conversation.
    """
    print('set_assignee_conversation_segment', conversation_id, segment_idx, assign_type, value,
          use_for_speech_training, uid)
    conversation = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation)

    if value == 'null':
        value = None

    is_unassigning = value is None or value is False

    if assign_type == 'is_user':
        conversation.transcript_segments[segment_idx].is_user = bool(value) if value is not None else False
        conversation.transcript_segments[segment_idx].person_id = None
    elif assign_type == 'person_id':
        conversation.transcript_segments[segment_idx].is_user = False
        conversation.transcript_segments[segment_idx].person_id = value
    else:
        print(assign_type)
        raise HTTPException(status_code=400, detail="Invalid assign type")

    conversations_db.update_conversation_segments(uid, conversation_id,
                                                  [segment.dict() for segment in conversation.transcript_segments])
    # thinh's note: disabled for now
    # segment_words = len(conversation.transcript_segments[segment_idx].text.split(' '))
    # # TODO: can do this async
    # if use_for_speech_training and not is_unassigning and segment_words > 5:  # some decent sample at least
    #     person_id = value if assign_type == 'person_id' else None
    #     expand_speech_profile(conversation_id, uid, segment_idx, assign_type, person_id)
    # else:
    #     path = f'{conversation_id}_segment_{segment_idx}.wav'
    #     delete_additional_profile_audio(uid, path)
    #     delete_speech_sample_for_people(uid, path)

    return conversation


@router.patch('/v1/conversations/{conversation_id}/assign-speaker/{speaker_id}', response_model=Conversation,
              tags=['conversations'])
def set_assignee_conversation_segment(
        conversation_id: str, speaker_id: int, assign_type: str, value: Optional[str] = None,
        use_for_speech_training: bool = True, uid: str = Depends(auth.get_current_user_uid)
):
    """
    Another complex endpoint.

    Modify the assignee of all segments in the transcript of a conversation with the given speaker_id.
    But,
    if `use_for_speech_training` is True, the corresponding audio segment will be used for speech training.

    Speech training of whom?

    If `assign_type` is 'is_user', the segment will be used for the user speech training.
    If `assign_type` is 'person_id', the segment will be used for the person with the given id speech training.

    What is required for a segment to be used for speech training?
    1. The segment must have more than 5 words.
    2. The conversation audio file should be already stored in the user's bucket.

    :return: The updated conversation.
    """
    print('set_assignee_conversation_segment', conversation_id, speaker_id, assign_type, value, use_for_speech_training,
          uid)
    conversation = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation)

    if value == 'null':
        value = None

    is_unassigning = value is None or value is False

    if assign_type == 'is_user':
        for segment in conversation.transcript_segments:
            if segment.speaker_id == speaker_id:
                segment.is_user = bool(value) if value is not None else False
                segment.person_id = None
    elif assign_type == 'person_id':
        for segment in conversation.transcript_segments:
            if segment.speaker_id == speaker_id:
                print(segment.speaker_id, speaker_id, value)
                segment.is_user = False
                segment.person_id = value
    else:
        print(assign_type)
        raise HTTPException(status_code=400, detail="Invalid assign type")

    conversations_db.update_conversation_segments(uid, conversation_id,
                                                  [segment.dict() for segment in conversation.transcript_segments])
    # This will be used when we setup recording for conversations, not used for now
    # get the segment with the most words with the speaker_id
    # segment_idx = 0
    # segment_words = 0
    # for segment in conversation.transcript_segments:
    #     if segment.speaker == speaker_id:
    #         if len(segment.text.split(' ')) > segment_words:
    #             segment_words = len(segment.text.split(' '))
    #             if segment_words > 5:
    #                 segment_idx = segment.idx
    #
    # if use_for_speech_training and not is_unassigning and segment_words > 5:  # some decent sample at least
    #     person_id = value if assign_type == 'person_id' else None
    #     expand_speech_profile(conversation_id, uid, segment_idx, assign_type, person_id)
    # else:
    #     path = f'{conversation_id}_segment_{segment_idx}.wav'
    #     delete_additional_profile_audio(uid, path)
    #     delete_speech_sample_for_people(uid, path)

    return conversation


# *********************************************
# *********** SHARING conversations ***********
# *********************************************

@router.patch('/v1/conversations/{conversation_id}/visibility', tags=['conversations'])
def set_conversation_visibility(
        conversation_id: str, value: ConversationVisibility, uid: str = Depends(auth.get_current_user_uid)
):
    print('update_conversation_visibility', conversation_id, value, uid)
    _get_conversation_by_id(uid, conversation_id)
    conversations_db.set_conversation_visibility(uid, conversation_id, value)
    if value == ConversationVisibility.private:
        redis_db.remove_conversation_to_uid(conversation_id)
        redis_db.remove_public_conversation(conversation_id)
    else:
        redis_db.store_conversation_to_uid(conversation_id, uid)
        redis_db.add_public_conversation(conversation_id)

    return {"status": "Ok"}


@router.get("/v1/conversations/{conversation_id}/shared", response_model=Conversation, tags=['conversations'])
def get_shared_conversation_by_id(conversation_id: str):
    uid = redis_db.get_conversation_uid(conversation_id)
    if not uid:
        raise HTTPException(status_code=404, detail="Conversation is private")

    # TODO: include speakers and people matched?
    # TODO: other fields that  shouldn't be included?
    conversation = _get_conversation_by_id(uid, conversation_id)
    visibility = conversation.get('visibility', ConversationVisibility.private)
    if not visibility or visibility == ConversationVisibility.private:
        raise HTTPException(status_code=404, detail="Conversation is private")
    conversation = Conversation(**conversation)
    conversation.geolocation = None
    return conversation


@router.get("/v1/public-conversations", response_model=List[Conversation], tags=['conversations'])
def get_public_conversations(offset: int = 0, limit: int = 1000):
    conversations = redis_db.get_public_conversations()
    data = []

    conversation_uids = redis_db.get_conversation_uids(conversations)

    data = [[uid, conversation_id] for conversation_id, uid in conversation_uids.items() if uid]
    # TODO: sort in some way to have proper pagination

    conversations = conversations_db.run_get_public_conversations(data[offset:offset + limit])
    for conversation in conversations:
        conversation['geolocation'] = None
    return conversations


@router.post("/v1/conversations/search", response_model=dict, tags=['conversations'])
def search_conversations_endpoint(search_request: SearchRequest, uid: str = Depends(auth.get_current_user_uid)):
    # Convert ISO datetime strings to Unix timestamps if provided
    start_timestamp = None
    end_timestamp = None

    if search_request.start_date:
        start_timestamp = int(datetime.fromisoformat(search_request.start_date).timestamp())

    if search_request.end_date:
        end_timestamp = int(datetime.fromisoformat(search_request.end_date).timestamp())

    return search_conversations(query=search_request.query, page=search_request.page,
                                per_page=search_request.per_page, uid=uid,
                                include_discarded=search_request.include_discarded,
                                start_date=start_timestamp,
                                end_date=end_timestamp)



@router.post("/v1/conversations/{conversation_id}/test-prompt", response_model=dict, tags=['conversations'])
def test_prompt(conversation_id: str, request: TestPromptRequest, uid: str = Depends(auth.get_current_user_uid)):
    conversation_data = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation_data)

    full_transcript = "\n".join([seg.text for seg in conversation.transcript_segments if seg.text])

    if not full_transcript:
        raise HTTPException(status_code=400, detail="Conversation has no text content to summarize.")

    summary = generate_summary_with_prompt(full_transcript, request.prompt)

    return {"summary": summary}


@router.post("/v1/conversations/{conversation_id}/image-summary", response_model=Conversation,
            tags=['conversations'])
def process_image_summary(
    conversation_id: str, 
    image_data: dict = Body(...), 
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Process one or more image descriptions and update the conversation summary with insights from the images.
    Handles both single image descriptions and an array of image descriptions.
    Accepts optional user_prompt for providing context and instructions for event generation.
    """
    # Get the existing conversation
    conversation = _get_conversation_by_id(uid, conversation_id)
    
    # Check if we're receiving a single image description or multiple
    image_description = image_data.get("image_description", "")
    image_descriptions = image_data.get("image_descriptions", [])
    user_prompt = image_data.get("user_prompt", "")  # Extract user prompt for context
    
    # Handle both single image and multiple images cases
    if not image_description and not image_descriptions:
        raise HTTPException(status_code=400, detail="Image description is required")
    
    # If we have a single image description, add it to the list
    if image_description:
        image_descriptions.append(image_description)
    
    # Get user language preference (or use English as default)
    user_language = users_db.get_user_language_preference(uid) or 'English'
    user_name = users_db.get_user_name(uid) or 'User'
    
    # Get conversation transcript
    transcript = get_conversation_transcript(conversation)
    
    # Note: transcript can be empty for image-only conversations
    # We'll use None for empty transcripts to match create-from-images behavior
    transcript_for_memory = transcript if transcript else None
    
    # If this is the first image analysis for this conversation, we'll do a complete analysis
    # For subsequent images, we'll do an incremental analysis to avoid overwriting previous insights
    is_first_analysis = not conversation.get('structured', {}).get('key_takeaways', [])
    
    if is_first_analysis:
        # Create a prompt to analyze the images and generate a new summary
        images_text = "\n\n".join([f"Image {i+1}:\n{desc.strip()}" for i, desc in enumerate(image_descriptions)])
        
        # Get valid categories for the prompt
        from models.conversation import CategoryEnum
        valid_categories = [cat.value for cat in CategoryEnum]
        valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
        
        prompt = f"""
        You are a personal growth coach helping {user_name} discover profound meaning and growth opportunities from the visual moments they choose to capture and preserve.

        {user_name} has shared visual content that was meaningful enough for them to capture and revisit. Your role is to help them understand the deeper significance of what they chose to document and how these visual moments can contribute to their personal journey and growth.

        **Think from {user_name}'s perspective**: These images represent moments that caught their attention, sparked their curiosity, or held some significance for them. Help them understand WHY these moments mattered and how they reflect their values, interests, and growth.

        {"**User Context**: " + user_prompt.strip() + " Please incorporate this context throughout your analysis, especially when generating events and insights." if user_prompt.strip() else ""}

        Create a comprehensive analysis that serves as a valuable tool for {user_name}'s self-discovery and development:

        1. **Overview**: Write directly to {user_name} about the significance of what they captured:
           - What these visual moments reveal about their interests, values, or current life focus
           - The personal meaning behind their choice to capture and preserve these specific moments
           - How these images reflect their way of seeing and engaging with the world
           - What this collection of visual content says about their personality, priorities, or journey
           - The emotional or practical significance of these moments in their life story

        2. **Key Takeaways**: Help {user_name} extract 3-5 profound insights from their visual choices:
           - Personal realizations about what draws their attention and why
           - Life lessons or patterns that emerge from what they choose to notice and capture
           - Understanding about their aesthetic preferences, interests, or values
           - Insights about their growth, curiosity, or areas of focus
           - Recognition of their unique perspective and way of engaging with experiences

        3. **Growth Opportunities**: Provide 2-3 personalized suggestions for {user_name}:
           - Start with empowering action verbs that inspire and motivate them
           - Focus on skills, habits, or perspectives that will enhance their ability to engage meaningfully with life
           - Connect improvements to their demonstrated interests and visual awareness
           - Explain HOW each improvement will enrich their experiences and personal satisfaction
           - Suggest ways to build on their existing strengths and curiosity
           - Make recommendations feel like natural extensions of what they already love doing

        4. **Learning Opportunities**: Suggest 1-2 areas that align with {user_name}'s demonstrated interests:
           - Topics directly related to what they chose to capture or the themes in their images
           - Skills that would enhance their ability to appreciate, understand, or engage with similar experiences
           - Knowledge areas that would deepen their enjoyment of their interests
           - Learning that would help them find even more meaning in the moments they choose to capture

        5. **Events**: Generate calendar events based on the images and any user context:
           - Create events that align with the content and context of the images
           - Use the user_prompt field to store any user-provided context or instructions for each event
           - Make events specific, actionable, and meaningful based on the visual content
           - Include appropriate timing and duration based on the activity type
           - {"Focus especially on events that relate to: " + user_prompt.strip() if user_prompt.strip() else "Focus on events that emerge naturally from the image content"}

        **Personal Growth Framework**:
        - Honor their choice to capture these particular moments as meaningful and valuable
        - Frame their visual attention as a strength and source of insight about themselves
        - Use encouraging language that celebrates their curiosity and unique perspective
        - Connect their visual choices to broader themes about who they are and who they're becoming
        - Help them see how their way of noticing and capturing moments is a valuable life skill
        - Encourage them to continue paying attention to what resonates with them visually

        **Technical Requirements:**
        - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
        - Choose the category that best represents the main theme or content of the images
        - For events, include the user-provided context in the user_prompt field for each event

        User Information for Deep Personalization:
        - Name: {user_name}
        - Primary language: {user_language}
        
        Visual Moments {user_name} Chose to Capture:
        {images_text}
        """
        
        # Process the prompt with the LLM
        result = process_prompt(
            EnhancedSummaryOutput,
            prompt,
            model_name="gpt-4o",
            temperature=0.1
        )
        
        # Update the structured data with the enhanced summary
        if 'structured' not in conversation:
            conversation['structured'] = {}
        
        structured = conversation['structured']
        structured['overview'] = result.overview
        structured['key_takeaways'] = result.key_takeaways
        structured['things_to_improve'] = result.things_to_improve
        structured['things_to_learn'] = result.things_to_learn
        
        # Convert EnhancedEvent objects to Event objects with user prompt
        if hasattr(result, 'events') and result.events:
            from models.conversation import Event
            from datetime import datetime
            
            structured_events = []
            for enhanced_event in result.events:
                try:
                    # Parse the ISO date string
                    start_datetime = datetime.fromisoformat(enhanced_event.start.replace('Z', '+00:00'))
                    
                    # Create Event object with user prompt
                    event = Event(
                        title=enhanced_event.title,
                        description=enhanced_event.description,
                        start=start_datetime,
                        duration=enhanced_event.duration,
                        user_prompt=user_prompt or enhanced_event.user_prompt,  # Use provided user prompt or extracted one
                        created=False
                    )
                    structured_events.append(event.dict())
                except Exception as e:
                    print(f"Error converting event: {e}")
                    continue
            
            structured['events'] = structured_events
    else:
        # For incremental updates, we'll analyze only the new images and merge insights
        # with the existing summary
        existing_structured = conversation.get('structured', {})
        existing_overview = existing_structured.get('overview', "")
        existing_takeaways = existing_structured.get('key_takeaways', [])
        existing_improvements = existing_structured.get('things_to_improve', [])
        existing_learnings = existing_structured.get('things_to_learn', [])
        
        # Create a prompt to analyze the images and provide incremental insights
        images_text = "\n\n".join([f"Image {i+1}:\n{desc.strip()}" for i, desc in enumerate(image_descriptions)])
        
        # Get valid categories for the prompt
        from models.conversation import CategoryEnum
        valid_categories = [cat.value for cat in CategoryEnum]
        valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
        
        prompt = f"""
        You are a personal growth coach helping {user_name} deepen the insights from their ongoing life journey.
        
        {user_name} is adding new visual content to a meaningful experience they previously shared. Your role is to help them discover additional layers of meaning and growth opportunities that emerge when they pay attention to more details from their life.

        **Think from {user_name}'s perspective**: They're continuing to process and understand a significant moment in their life. Help them see how these additional visual elements add richness to their understanding of themselves and their growth.

        Build upon their existing insights to create an even richer understanding:

        **Context of {user_name}'s Previous Insights**:
        - Previous Overview: {existing_overview}
        - Previous Key Takeaways: {", ".join(existing_takeaways)}
        - Previous Growth Areas: {", ".join(existing_improvements)}
        - Previous Learning Interests: {", ".join(existing_learnings)}

        **Help {user_name} Discover Additional Insights**:

        1. **Updated Overview**: Help {user_name} see how these new visual elements enrich their understanding:
           - How the new images add depth to their original experience
           - What additional aspects of their personality, values, or journey these reveal
           - How this expanded perspective enhances the meaning of this moment in their life
           - New connections between their thoughts, actions, and what they chose to capture

        2. **Additional Key Takeaways**: Guide {user_name} to discover new insights that emerge:
           - Fresh realizations that come from seeing more of the complete picture
           - New patterns or themes about their interests, values, or growth areas
           - Additional life lessons that become clear with this expanded view
           - Deeper understanding of their motivations or aspirations

        3. **Additional Growth Opportunities**: Suggest new ways {user_name} can evolve:
           - New skills or habits that would enhance their ability to engage with life fully
           - Growth areas revealed by their attention to visual details and experiences
           - Ways to build on their existing strengths and interests
           - Steps that feel like natural progressions in their personal development

        4. **Additional Learning Opportunities**: Suggest enriching knowledge areas for {user_name}:
           - New topics that emerge from their expanded experience
           - Skills that would help them better appreciate or engage with similar experiences
           - Knowledge that connects to their demonstrated curiosity and interests
           - Learning that would enhance their ability to find meaning in everyday moments

        **Enhancement Principles**:
        - Build on their existing insights rather than replacing them
        - Focus on how the new visual content adds richness to their understanding
        - Frame everything as exciting opportunities for continued growth
        - Help them see the value in paying attention to multiple dimensions of their experiences
        - Use encouraging language that celebrates their curiosity and growth mindset

        **Technical Requirements:**
        - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
        - Choose the category that best represents the main theme or content of the images

        User Information for Deep Personalization:
        - Name: {user_name}
        - Primary language: {user_language}
        
        {user_name}'s Original Conversation:
        {transcript}
        
        New Image Descriptions:
        {images_text}
        """
        
        # Process the prompt with the LLM
        result = process_prompt(
            EnhancedSummaryOutput,
            prompt,
            model_name="gpt-4o",
            temperature=0.1
        )
        
        # Merge the new insights with the existing structured data
        structured = conversation.get('structured', {})
        
        # Update overview by appending new insights if they don't already exist
        if not structured.get('overview'):
            structured['overview'] = result.overview
        else:
            # Check if the new overview contains significant new content to add
            if not _contains_similar_content(structured['overview'], result.overview):
                structured['overview'] = f"{structured['overview']}\n\nAdditional insights from new images: {result.overview}"
        
        # Update lists by adding new unique items
        existing_takeaways = structured.get('key_takeaways', [])
        for takeaway in result.key_takeaways:
            if not _contains_similar_item(existing_takeaways, takeaway):
                existing_takeaways.append(takeaway)
        structured['key_takeaways'] = existing_takeaways
        
        existing_improvements = structured.get('things_to_improve', [])
        for improvement in result.things_to_improve:
            if not _contains_similar_item(existing_improvements, improvement):
                existing_improvements.append(improvement)
        structured['things_to_improve'] = existing_improvements
        
        existing_learnings = structured.get('things_to_learn', [])
        for learning in result.things_to_learn:
            if not _contains_similar_item(existing_learnings, learning):
                existing_learnings.append(learning)
        structured['things_to_learn'] = existing_learnings
    
    # Update the conversation in the database
    conversations_db.upsert_conversation(uid, conversation.as_dict_cleaned_dates())
    
    # Extract memories from image content in background thread
    image_descriptions_list = image_descriptions  # The list we built above
    structured_summary_text = result.overview if hasattr(result, 'overview') else ""
    
    # Add key takeaways and insights to structured summary for memory extraction
    summary_parts = [structured_summary_text] if structured_summary_text else []
    if hasattr(result, 'key_takeaways') and result.key_takeaways:
        summary_parts.append("Key Takeaways: " + "; ".join(result.key_takeaways))
    if hasattr(result, 'things_to_improve') and result.things_to_improve:
        improvement_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_improve]
        summary_parts.append("Growth Opportunities: " + "; ".join(improvement_texts))
    if hasattr(result, 'things_to_learn') and result.things_to_learn:
        learning_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_learn]
        summary_parts.append("Learning Opportunities: " + "; ".join(learning_texts))
    
    full_structured_summary = "\n\n".join(summary_parts) if summary_parts else ""
    
    print(f"DEBUG: Starting memory extraction for upload-images with {len(image_descriptions)} image descriptions")
    threading.Thread(
        target=_extract_memories_from_image_conversation,
        args=(uid, conversation_id, image_descriptions_list, full_structured_summary, transcript_for_memory)
    ).start()
    
    return Conversation(**conversation)

# Helper function to check if a list already contains a similar item
def _contains_similar_item(items, new_item):
    return any(item.lower() in new_item.lower() or new_item.lower() in item.lower() for item in items)

# Helper function to check if text already contains similar content
def _contains_similar_content(existing_text, new_text):
    # Simple check - can be made more sophisticated if needed
    return existing_text.lower() in new_text.lower() or new_text.lower() in existing_text.lower()

@router.post("/v1/conversations/{conversation_id}/enhanced-summary", response_model=Conversation,
            tags=['conversations'])
def generate_enhanced_summary(
        conversation_id: str, uid: str = Depends(auth.get_current_user_uid)
):
    """
    Generate an enhanced summary for a conversation, including key takeaways, things to improve, and things to learn.
    
    :param conversation_id: The ID of the conversation to generate an enhanced summary for
    :return: The updated conversation with enhanced summary fields
    """
    conversation_data = _get_conversation_by_id(uid, conversation_id)
    conversation = Conversation(**conversation_data)
    
    # Get the full transcript
    full_transcript = "\n".join([seg.text for seg in conversation.transcript_segments if seg.text])
    
    if not full_transcript:
        raise HTTPException(status_code=400, detail="Conversation has no text content to summarize.")
    
    # Get user's timezone (using UTC as fallback)
    tz = "UTC"
    
    # Generate enhanced structured data
    enhanced_structured = get_transcript_structure(
        full_transcript, 
        conversation.started_at or conversation.created_at,
        conversation.language or 'en',
        tz,
        uid  # Pass the user ID to enable personalization
    )
    
    # Update the conversation with enhanced structured data
    conversation.structured = enhanced_structured
    
    # Save the updated conversation
    conversations_db.update_conversation_structured(uid, conversation_id, enhanced_structured.dict())
    
    return conversation

@router.post("/v1/conversations/{conversation_id}/upload-images", response_model=Conversation, tags=['conversations'])
async def upload_and_process_conversation_images(
    conversation_id: str,
    files: List[UploadFile] = File(...),
    user_prompt: Optional[str] = Form(default=""),
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Upload one or more images to Firebase Storage and process them with OpenAI to enhance the conversation summary.
    Accepts optional user_prompt for providing context and instructions for event generation.
    """
    print(f"DEBUG: Starting upload_and_process_conversation_images for conversation {conversation_id}, user {uid}")
    print(f"DEBUG: Received {len(files)} files")
    print(f"DEBUG: Files parameter type: {type(files)}")
    print(f"DEBUG: First file type: {type(files[0]) if files else 'No files'}")
    
    # Get the existing conversation
    try:
        conversation_data = _get_conversation_by_id(uid, conversation_id)
        conversation = Conversation(**conversation_data)
        print(f"DEBUG: Successfully retrieved conversation")
    except Exception as e:
        print(f"DEBUG: Error retrieving conversation: {e}")
        raise HTTPException(status_code=404, detail=f"Conversation not found: {str(e)}")
    
    # Validate files
    if not files:
        print(f"DEBUG: No files provided")
        raise HTTPException(status_code=400, detail="No files provided")
    
    print(f"DEBUG: Starting file validation")
    # Check file types and sizes using magic bytes detection
    for i, file in enumerate(files):
        print(f"DEBUG: Validating file {i}: {file.filename}, content_type: {file.content_type}")
        print(f"DEBUG: File headers: {getattr(file, 'headers', 'None')}")
        print(f"DEBUG: File size: {file.size}")
        print(f"DEBUG: Available file attributes: {dir(file)}")
        
        # Read file content to check magic bytes
        file_size = 0
        content = None
        try:
            content = await file.read()
            file_size = len(content)
            await file.seek(0)  # Reset file pointer
            print(f"DEBUG: File {file.filename} size: {file_size} bytes")
        except Exception as e:
            print(f"DEBUG: Error reading file {file.filename}: {e}")
            raise HTTPException(status_code=400, detail=f"Error reading file {file.filename}")
        
        # Detect actual image type using magic bytes
        detected_mime_type = detect_image_type_from_content(content)
        print(f"DEBUG: File {file.filename} detected MIME type from content: {detected_mime_type}")
        print(f"DEBUG: File {file.filename} reported content type: {file.content_type}")
        
        # Use detected MIME type for validation instead of HTTP content type
        if not detected_mime_type:
            print(f"DEBUG: File {file.filename} is not a valid image based on content analysis")
            # Show first few bytes for debugging
            if content:
                hex_preview = ' '.join(f'{b:02x}' for b in content[:16])
                print(f"DEBUG: First 16 bytes: {hex_preview}")
            raise HTTPException(status_code=400, detail=f"File {file.filename} is not a valid image format")
        
        # Check file size (limit to 10MB per image)
        if file_size > 10 * 1024 * 1024:  # 10MB limit
            print(f"DEBUG: File {file.filename} is too large: {file_size}")
            raise HTTPException(status_code=400, detail=f"File {file.filename} is too large (max 10MB)")
        
        print(f"DEBUG: File {file.filename} validation passed - detected as {detected_mime_type}")
    
    print(f"DEBUG: File validation completed successfully")
    
    try:
        # Read image data and upload to Firebase Storage
        images_data = []
        image_urls = []
        image_descriptions = []
        image_timestamps = []
        
        for file in files:
            image_data = await file.read()
            images_data.append(image_data)
            
            # Extract timestamp from EXIF data
            timestamp = extract_image_timestamp(image_data)
            image_timestamps.append(timestamp)
            print(f"DEBUG: Image {len(images_data)-1} EXIF timestamp: {timestamp}")
        
        # Upload images to Firebase Storage
        uploaded_urls = upload_multiple_conversation_images(images_data, uid, conversation_id)
        image_urls.extend(uploaded_urls)
        
        print(f"DEBUG: Uploaded {len(uploaded_urls)} images to Firebase Storage:")
        for i, url in enumerate(uploaded_urls):
            print(f"DEBUG: Image {i}: {url}")
        
        # Determine the conversation timestamp based on image timestamps
        valid_timestamps = [ts for ts in image_timestamps if ts is not None]
        
        if valid_timestamps:
            # Use the earliest image timestamp as the conversation timestamp
            earliest_timestamp = min(valid_timestamps)
            # EXIF timestamps are already in local time, so don't convert to UTC
            conversation_timestamp = earliest_timestamp
            print(f"DEBUG: Using earliest image timestamp for conversation: {conversation_timestamp} (preserving local time from EXIF)")
        else:
            # Fallback to current time if no EXIF timestamps found
            conversation_timestamp = datetime.now(timezone.utc)
            print(f"DEBUG: No EXIF timestamps found, using current time: {conversation_timestamp}")
        
        # Get image descriptions using OpenAI
        for image_data in images_data:
            try:
                description = analyze_image_content(image_data, user_prompt)
                image_descriptions.append(description)
            except Exception as e:
                print(f"Error analyzing image: {e}")
                image_descriptions.append("Image content could not be analyzed")
        
        # Get user preferences
        user_language = users_db.get_user_language_preference(uid) or 'English'
        user_name = users_db.get_user_name(uid) or 'User'
        
        # Get conversation transcript
        transcript = get_conversation_transcript(conversation_data)
        
        # Note: transcript can be empty for image-only conversations
        # We'll use None for empty transcripts to match create-from-images behavior
        transcript_for_memory = transcript if transcript else None
        
        # Check if this is the first image enhancement for this conversation
        existing_image_urls = conversation.structured.image_urls or []
        is_first_enhancement = len(existing_image_urls) == 0
        
        print(f"DEBUG: Existing image URLs: {existing_image_urls}")
        print(f"DEBUG: Is first enhancement: {is_first_enhancement}")
        print(f"DEBUG: Transcript available: {bool(transcript)}")
        
        # Create structured data from images
        images_text = "\n\n".join([f"Image {i+1}:\n{desc.strip()}" for i, desc in enumerate(image_descriptions)])
        
        # Get valid categories for the prompt
        from models.conversation import CategoryEnum
        valid_categories = [cat.value for cat in CategoryEnum]
        valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
        
        # Create different prompts depending on whether we have transcript content
        if transcript:
            # Conversation with both images and transcript
            prompt = f"""
            You are a personal growth coach helping {user_name} discover profound meaning and growth opportunities from their conversation experience that includes both spoken content and visual moments they chose to capture.

            {user_name} has shared a conversation alongside visual content that was meaningful enough for them to capture and preserve. Your role is to help them understand the deeper significance of both the spoken experience and the visual moments, and how together they contribute to their personal journey and growth.

            **Think from {user_name}'s perspective**: These images represent moments they chose to document during or related to their conversation. Help them understand WHY these moments mattered and how they connect to the broader themes and insights from their spoken experience.

            Create a comprehensive analysis that serves as a valuable tool for {user_name}'s self-discovery and development:

            1. **Overview**: Write directly to {user_name} about the significance of their complete experience:
               - How the visual moments enhance and deepen the insights from their conversation
               - What the combination of spoken content and visual documentation reveals about their interests, values, or current life focus
               - The personal meaning behind their choice to capture these specific moments alongside their conversation
               - How the images and conversation together reflect their way of engaging with and learning from experiences
               - The emotional or practical significance of this multi-modal experience in their life story

            2. **Key Takeaways**: Help {user_name} extract 3-5 profound insights from their complete experience:
               - Personal realizations that emerge from connecting their spoken insights with their visual choices
               - Life lessons or patterns that become clearer when viewing both conversation and images together
               - Understanding about their learning style, interests, or values revealed through multiple modes of engagement
               - Insights about their growth, curiosity, or areas of focus strengthened by this comprehensive experience
               - Recognition of their unique way of processing and documenting meaningful moments

            3. **Growth Opportunities**: Provide 2-3 personalized suggestions for {user_name}:
               - Start with empowering action verbs that inspire and motivate them
               - Focus on skills, habits, or perspectives that will enhance their ability to engage meaningfully with multi-faceted experiences
               - Connect improvements to their demonstrated ability to process information through multiple channels
               - Explain HOW each improvement will enrich their learning and personal satisfaction
               - Suggest ways to build on their strengths in both verbal processing and visual awareness
               - Make recommendations feel like natural extensions of their comprehensive engagement style

            4. **Learning Opportunities**: Suggest 1-2 areas that align with {user_name}'s demonstrated multi-modal learning approach:
               - Topics that would benefit from their ability to combine spoken reflection with visual documentation
               - Skills that would enhance their capacity to extract meaning from diverse types of experiences
               - Knowledge areas that would deepen their ability to connect insights across different modes of engagement
               - Learning that would help them continue developing their comprehensive approach to personal growth

            **Personal Growth Framework**:
            - Honor their choice to engage with experiences through multiple channels as a valuable learning strategy
            - Frame their multi-modal approach as a strength and source of deeper insight
            - Use encouraging language that celebrates their comprehensive curiosity and engagement
            - Connect their combined verbal and visual processing to broader themes about their learning style and growth
            - Help them see how their integrated approach to documenting and reflecting on experiences is a powerful tool for development
            - Encourage them to continue leveraging both spoken reflection and visual documentation for maximum insight

            **Technical Requirements:**
            - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
            - Choose the category that best represents the main theme or content of the overall experience

            User Information for Deep Personalization:
            - Name: {user_name}
            - Primary language: {user_language}
            
            Conversation Content:
            {transcript}
            
            Visual Moments {user_name} Chose to Capture:
            {images_text}
            """
        else:
            # Image-only conversation (no transcript)
            prompt = f"""
            You are a personal growth coach helping {user_name} discover profound meaning and growth opportunities from the visual moments they choose to capture and preserve.

            {user_name} has shared visual content that was meaningful enough for them to capture and revisit. Your role is to help them understand the deeper significance of what they chose to document and how these visual moments can contribute to their personal journey and growth.

            **Think from {user_name}'s perspective**: These images represent moments that caught their attention, sparked their curiosity, or held some significance for them. Help them understand WHY these moments mattered and how they reflect their values, interests, and growth.

            {"**User Context**: " + user_prompt.strip() + " Please incorporate this context throughout your analysis, especially when generating events and insights." if user_prompt.strip() else ""}

            Create a comprehensive analysis that serves as a valuable tool for {user_name}'s self-discovery and development:

            1. **Overview**: Write directly to {user_name} about the significance of what they captured:
               - What these visual moments reveal about their interests, values, or current life focus
               - The personal meaning behind their choice to capture and preserve these specific moments
               - How these images reflect their way of seeing and engaging with the world
               - What this collection of visual content says about their personality, priorities, or journey
               - The emotional or practical significance of these moments in their life story

            2. **Key Takeaways**: Help {user_name} extract 3-5 profound insights from their visual choices:
               - Personal realizations about what draws their attention and why
               - Life lessons or patterns that emerge from what they choose to notice and capture
               - Understanding about their aesthetic preferences, interests, or values
               - Insights about their growth, curiosity, or areas of focus
               - Recognition of their unique perspective and way of engaging with experiences

            3. **Growth Opportunities**: Provide 2-3 personalized suggestions for {user_name}:
               - Start with empowering action verbs that inspire and motivate them
               - Focus on skills, habits, or perspectives that will enhance their ability to engage meaningfully with life
               - Connect improvements to their demonstrated interests and visual awareness
               - Explain HOW each improvement will enrich their experiences and personal satisfaction
               - Suggest ways to build on their existing strengths and curiosity
               - Make recommendations feel like natural extensions of what they already love doing

            4. **Learning Opportunities**: Suggest 1-2 areas that align with {user_name}'s demonstrated interests:
               - Topics directly related to what they chose to capture or the themes in their images
               - Skills that would enhance their ability to appreciate, understand, or engage with similar experiences
               - Knowledge areas that would deepen their enjoyment of their interests
               - Learning that would help them find even more meaning in the moments they choose to capture

            5. **Events**: Generate calendar events based on the images and any user context:
               - Create events that align with the content and context of the images
               - Use the user_prompt field to store any user-provided context or instructions for each event
               - Make events specific, actionable, and meaningful based on the visual content
               - Include appropriate timing and duration based on the activity type
               - {"Focus especially on events that relate to: " + user_prompt.strip() if user_prompt.strip() else "Focus on events that emerge naturally from the image content"}

            **Personal Growth Framework**:
            - Honor their choice to capture these particular moments as meaningful and valuable
            - Frame their visual attention as a strength and source of insight about themselves
            - Use encouraging language that celebrates their curiosity and unique perspective
            - Connect their visual choices to broader themes about who they are and who they're becoming
            - Help them see how their way of noticing and capturing moments is a valuable life skill
            - Encourage them to continue paying attention to what resonates with them visually

            **Technical Requirements:**
            - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
            - Choose the category that best represents the main theme or content of the images
            - For events, include the user-provided context in the user_prompt field for each event

            User Information for Deep Personalization:
            - Name: {user_name}
            - Primary language: {user_language}
            
            Visual Moments {user_name} Chose to Capture:
            {images_text}
            """
        
        # Process with OpenAI
        result = process_prompt(
            EnhancedSummaryOutput,
            prompt,
            model_name="gpt-4o",
            temperature=0.1
        )
        
        print(f"DEBUG: OpenAI processing completed successfully")
        print(f"DEBUG: Result type: {type(result)}")
        print(f"DEBUG: Result overview: {result.overview}")
        print(f"DEBUG: Result key_takeaways: {result.key_takeaways}")
        print(f"DEBUG: Result things_to_improve type: {type(result.things_to_improve)}")
        print(f"DEBUG: Result things_to_improve: {result.things_to_improve}")
        print(f"DEBUG: Result things_to_learn type: {type(result.things_to_learn)}")
        print(f"DEBUG: Result things_to_learn: {result.things_to_learn}")
        
        # Update the conversation structured data
        if is_first_enhancement:
            # First enhancement - replace content
            conversation.structured.overview = result.overview
            conversation.structured.key_takeaways = result.key_takeaways
            conversation.structured.things_to_improve = result.things_to_improve
            conversation.structured.things_to_learn = result.things_to_learn
        else:
            # Incremental enhancement - merge content
            if result.overview and not _contains_similar_content(conversation.structured.overview, result.overview):
                conversation.structured.overview += f"\n\nAdditional insights from images: {result.overview}"
            
            # Add new takeaways
            for takeaway in result.key_takeaways:
                if not _contains_similar_item(conversation.structured.key_takeaways, takeaway):
                    conversation.structured.key_takeaways.append(takeaway)
            
            # Add new improvements
            for improvement in result.things_to_improve:
                improvement_content = improvement.content if hasattr(improvement, 'content') else str(improvement)
                existing_contents = [item.content if hasattr(item, 'content') else str(item) for item in conversation.structured.things_to_improve]
                if not _contains_similar_item(existing_contents, improvement_content):
                    conversation.structured.things_to_improve.append(improvement)
            
            # Add new learnings
            for learning in result.things_to_learn:
                learning_content = learning.content if hasattr(learning, 'content') else str(learning)
                existing_contents = [item.content if hasattr(item, 'content') else str(item) for item in conversation.structured.things_to_learn]
                if not _contains_similar_item(existing_contents, learning_content):
                    conversation.structured.things_to_learn.append(learning)
        
        # Convert EnhancedEvent objects to Event objects with user prompt (for both first and incremental enhancements)
        if hasattr(result, 'events') and result.events:
            from models.conversation import Event
            from datetime import datetime
            
            new_events = []
            for enhanced_event in result.events:
                try:
                    # Parse the ISO date string
                    start_datetime = datetime.fromisoformat(enhanced_event.start.replace('Z', '+00:00'))
                    
                    # Create Event object with user prompt
                    event = Event(
                        title=enhanced_event.title,
                        description=enhanced_event.description,
                        start=start_datetime,
                        duration=enhanced_event.duration,
                        user_prompt=user_prompt or enhanced_event.user_prompt,  # Use provided user prompt or extracted one
                        created=False
                    )
                    new_events.append(event)
                except Exception as e:
                    print(f"Error converting event: {e}")
                    continue
            
            # Add events based on enhancement type
            if is_first_enhancement:
                conversation.structured.events = new_events
            else:
                # For incremental enhancement, only add events that don't already exist
                existing_event_titles = [event.title.lower() for event in conversation.structured.events]
                for new_event in new_events:
                    if new_event.title.lower() not in existing_event_titles:
                        conversation.structured.events.append(new_event)
        
        print(f"DEBUG: Before adding image URLs - current image_urls: {conversation.structured.image_urls}")
        
        # Add image URLs to the conversation
        conversation.structured.image_urls.extend(image_urls)
        
        print(f"DEBUG: After adding image URLs - updated image_urls: {conversation.structured.image_urls}")
        
        # Update the conversation in the database
        conversations_db.update_conversation_structured(uid, conversation_id, conversation.structured.dict())
        
        print(f"DEBUG: Database updated successfully")
        
        # Extract memories from image content in background thread
        structured_summary_text = result.overview if hasattr(result, 'overview') else ""
        
        # Add key takeaways and insights to structured summary for memory extraction
        summary_parts = [structured_summary_text] if structured_summary_text else []
        if hasattr(result, 'key_takeaways') and result.key_takeaways:
            summary_parts.append("Key Takeaways: " + "; ".join(result.key_takeaways))
        if hasattr(result, 'things_to_improve') and result.things_to_improve:
            improvement_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_improve]
            summary_parts.append("Growth Opportunities: " + "; ".join(improvement_texts))
        if hasattr(result, 'things_to_learn') and result.things_to_learn:
            learning_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_learn]
            summary_parts.append("Learning Opportunities: " + "; ".join(learning_texts))
        
        full_structured_summary = "\n\n".join(summary_parts) if summary_parts else ""
        
        print(f"DEBUG: Starting memory extraction for upload-images with {len(image_descriptions)} image descriptions")
        threading.Thread(
            target=_extract_memories_from_image_conversation,
            args=(uid, conversation_id, image_descriptions, full_structured_summary, transcript_for_memory)
        ).start()
        
        # Fetch the updated conversation from database to ensure we have the latest data
        updated_conversation_data = _get_conversation_by_id(uid, conversation_id)
        final_conversation = Conversation(**updated_conversation_data)
        
        return final_conversation
        
    except Exception as e:
        print(f"Error processing images: {e}")
        # Clean up uploaded images if processing failed
        for url in image_urls:
            try:
                # Extract filename from URL and delete
                # This is a simplified cleanup - you might need more robust error handling
                pass
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Error processing images: {str(e)}")

@router.post("/v1/conversations/create-from-images", response_model=Conversation, tags=['conversations'])
async def create_conversation_from_images(
    files: List[UploadFile] = File(...),
    user_prompt: Optional[str] = Form(default=""),
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Create a new conversation from one or more uploaded images.
    This endpoint uploads images, analyzes their content, and creates a new conversation 
    with structured insights based on the image content.
    Accepts optional user_prompt for providing context and instructions for event generation.
    """
    print(f"DEBUG: Starting create_conversation_from_images for user {uid}")
    print(f"DEBUG: Received {len(files)} files")
    
    # Validate files
    if not files:
        print(f"DEBUG: No files provided")
        raise HTTPException(status_code=400, detail="No files provided")
    
    print(f"DEBUG: Starting file validation")
    
    # Validate each file
    for file in files:
        print(f"DEBUG: Validating file: {file.filename}")
        print(f"DEBUG: Content type: {file.content_type}")
        
        # Read file content for validation
        content = await file.read()
        await file.seek(0)  # Reset file pointer
        
        print(f"DEBUG: File size: {len(content)} bytes")
        
        # Detect MIME type from content
        detected_mime_type = detect_image_type_from_content(content)
        
        if not detected_mime_type:
            print(f"DEBUG: File {file.filename} is not a valid image")
            raise HTTPException(status_code=400, detail=f"File {file.filename} is not a valid image")
        
        # Check file size (limit to 10MB)
        if len(content) > 10 * 1024 * 1024:
            print(f"DEBUG: File {file.filename} is too large")
            raise HTTPException(status_code=400, detail=f"File {file.filename} is too large (max 10MB)")
        
        print(f"DEBUG: File {file.filename} validation passed - detected as {detected_mime_type}")
    
    print(f"DEBUG: File validation completed successfully")
    
    try:
        # Generate new conversation ID
        import uuid
        conversation_id = str(uuid.uuid4())
        print(f"DEBUG: Generated conversation ID: {conversation_id}")
        
        # Read image data and upload to Firebase Storage
        images_data = []
        image_urls = []
        image_descriptions = []
        image_timestamps = []
        
        for file in files:
            image_data = await file.read()
            images_data.append(image_data)
            
            # Extract timestamp from EXIF data
            timestamp = extract_image_timestamp(image_data)
            image_timestamps.append(timestamp)
            print(f"DEBUG: Image {len(images_data)-1} EXIF timestamp: {timestamp}")
        
        # Upload images to Firebase Storage
        uploaded_urls = upload_multiple_conversation_images(images_data, uid, conversation_id)
        image_urls.extend(uploaded_urls)
        
        print(f"DEBUG: Uploaded {len(uploaded_urls)} images to Firebase Storage:")
        for i, url in enumerate(uploaded_urls):
            print(f"DEBUG: Image {i}: {url}")
        
        # Determine the conversation timestamp based on image timestamps
        valid_timestamps = [ts for ts in image_timestamps if ts is not None]
        
        if valid_timestamps:
            # Use the earliest image timestamp as the conversation timestamp
            earliest_timestamp = min(valid_timestamps)
            # EXIF timestamps are already in local time, so don't convert to UTC
            conversation_timestamp = earliest_timestamp
            print(f"DEBUG: Using earliest image timestamp for conversation: {conversation_timestamp} (preserving local time from EXIF)")
        else:
            # Fallback to current time if no EXIF timestamps found
            conversation_timestamp = datetime.now(timezone.utc)
            print(f"DEBUG: No EXIF timestamps found, using current time: {conversation_timestamp}")
        
        # Get image descriptions using OpenAI
        for image_data in images_data:
            try:
                description = analyze_image_content(image_data, user_prompt)
                image_descriptions.append(description)
            except Exception as e:
                print(f"Error analyzing image: {e}")
                image_descriptions.append("Image content could not be analyzed")
        
        # Get user preferences
        user_language = users_db.get_user_language_preference(uid) or 'English'
        user_name = users_db.get_user_name(uid) or 'User'
        
        # Create structured data from images
        images_text = "\n\n".join([f"Image {i+1}:\n{desc.strip()}" for i, desc in enumerate(image_descriptions)])
        
        # Get valid categories for the prompt
        from models.conversation import CategoryEnum
        valid_categories = [cat.value for cat in CategoryEnum]
        valid_categories_str = ", ".join([f"'{cat}'" for cat in valid_categories])
        
        prompt = f"""
        You are a personal growth coach helping {user_name} discover profound meaning and growth opportunities from the visual moments they choose to capture and preserve.

        {user_name} has shared visual content that was meaningful enough for them to capture and revisit. Your role is to help them understand the deeper significance of what they chose to document and how these visual moments can contribute to their personal journey and growth.

        **Think from {user_name}'s perspective**: These images represent moments that caught their attention, sparked their curiosity, or held some significance for them. Help them understand WHY these moments mattered and how they reflect their values, interests, and growth.

        {"**User Context**: " + user_prompt.strip() + " Please incorporate this context throughout your analysis, especially when generating events and insights." if user_prompt.strip() else ""}

        Create a comprehensive analysis that serves as a valuable tool for {user_name}'s self-discovery and development:

        1. **Overview**: Write directly to {user_name} about the significance of what they captured:
           - What these visual moments reveal about their interests, values, or current life focus
           - The personal meaning behind their choice to capture and preserve these specific moments
           - How these images reflect their way of seeing and engaging with the world
           - What this collection of visual content says about their personality, priorities, or journey
           - The emotional or practical significance of these moments in their life story

        2. **Key Takeaways**: Help {user_name} extract 3-5 profound insights from their visual choices:
           - Personal realizations about what draws their attention and why
           - Life lessons or patterns that emerge from what they choose to notice and capture
           - Understanding about their aesthetic preferences, interests, or values
           - Insights about their growth, curiosity, or areas of focus
           - Recognition of their unique perspective and way of engaging with experiences

        3. **Growth Opportunities**: Provide 2-3 personalized suggestions for {user_name}:
           - Start with empowering action verbs that inspire and motivate them
           - Focus on skills, habits, or perspectives that will enhance their ability to engage meaningfully with life
           - Connect improvements to their demonstrated interests and visual awareness
           - Explain HOW each improvement will enrich their experiences and personal satisfaction
           - Suggest ways to build on their existing strengths and curiosity
           - Make recommendations feel like natural extensions of what they already love doing

        4. **Learning Opportunities**: Suggest 1-2 areas that align with {user_name}'s demonstrated interests:
           - Topics directly related to what they chose to capture or the themes in their images
           - Skills that would enhance their ability to appreciate, understand, or engage with similar experiences
           - Knowledge areas that would deepen their enjoyment of their interests
           - Learning that would help them find even more meaning in the moments they choose to capture

        5. **Events**: Generate calendar events based on the images and any user context:
           - Create events that align with the content and context of the images
           - Use the user_prompt field to store any user-provided context or instructions for each event
           - Make events specific, actionable, and meaningful based on the visual content
           - Include appropriate timing and duration based on the activity type
           - {"Focus especially on events that relate to: " + user_prompt.strip() if user_prompt.strip() else "Focus on events that emerge naturally from the image content"}

        **Personal Growth Framework**:
        - Honor their choice to capture these particular moments as meaningful and valuable
        - Frame their visual attention as a strength and source of insight about themselves
        - Use encouraging language that celebrates their curiosity and unique perspective
        - Connect their visual choices to broader themes about who they are and who they're becoming
        - Help them see how their way of noticing and capturing moments is a valuable life skill
        - Encourage them to continue paying attention to what resonates with them visually

        **Technical Requirements:**
        - For the category field, you MUST choose one of the following values EXACTLY as written: {valid_categories_str}
        - Choose the category that best represents the main theme or content of the images
        - For events, include the user-provided context in the user_prompt field for each event

        User Information for Deep Personalization:
        - Name: {user_name}
        - Primary language: {user_language}
        
        Visual Moments {user_name} Chose to Capture:
        {images_text}
        """
        
        # Process with OpenAI
        result = process_prompt(
            EnhancedSummaryOutput,
            prompt,
            model_name="gpt-4o",
            temperature=0.1
        )
        
        print(f"DEBUG: OpenAI processing completed successfully")
        
        # Generate a title based on the images
        title_prompt = f"""
        Based on these image descriptions, generate a concise, descriptive title (max 50 characters):
        
        {images_text}
        
        The title should be clear and capture the main theme or content of the images.
        """
        
        title_result = generate_summary_with_prompt("", title_prompt)
        title = title_result.strip().strip('"\'') if title_result else "Images Conversation"
        if len(title) > 50:
            title = title[:47] + "..."
        
        print(f"DEBUG: Generated title: {title}")
        
        # Create the new conversation
        from models.conversation import Structured, TranscriptSegment, ResourceItem as ConversationResourceItem
        
        # Convert things_to_improve to proper format
        things_to_improve_list = []
        if result.things_to_improve:
            for item in result.things_to_improve:
                if hasattr(item, 'content'):
                    # It's already a ResourceItem-like object
                    things_to_improve_list.append(ConversationResourceItem(
                        content=item.content,
                        url=getattr(item, 'url', ''),
                        title=getattr(item, 'title', '')
                    ))
                else:
                    # It's a string
                    things_to_improve_list.append(ConversationResourceItem(
                        content=str(item),
                        url='',
                        title=''
                    ))
        
        # Convert things_to_learn to proper format
        things_to_learn_list = []
        if result.things_to_learn:
            for item in result.things_to_learn:
                if hasattr(item, 'content'):
                    # It's already a ResourceItem-like object
                    things_to_learn_list.append(ConversationResourceItem(
                        content=item.content,
                        url=getattr(item, 'url', ''),
                        title=getattr(item, 'title', '')
                    ))
                else:
                    # It's a string
                    things_to_learn_list.append(ConversationResourceItem(
                        content=str(item),
                        url='',
                        title=''
                    ))
        
        print(f"DEBUG: Converted things_to_improve: {things_to_improve_list}")
        print(f"DEBUG: Converted things_to_learn: {things_to_learn_list}")
        
        # Create structured data
        structured = Structured(
            title=title,
            overview=result.overview,
            emoji='📸',  # Camera emoji for image-based conversations
            category=result.category,  # Use the LLM's category result instead of hardcoding
            key_takeaways=result.key_takeaways,
            things_to_improve=things_to_improve_list,
            things_to_learn=things_to_learn_list,
            image_urls=image_urls
        )
        
        # Convert EnhancedEvent objects to Event objects with user prompt
        if hasattr(result, 'events') and result.events:
            from models.conversation import Event
            from datetime import datetime
            
            for enhanced_event in result.events:
                try:
                    # Parse the ISO format datetime
                    start_time = datetime.fromisoformat(enhanced_event.start.replace('Z', '+00:00'))
                    
                    # Create Event object with user prompt
                    event = Event(
                        title=enhanced_event.title,
                        description=enhanced_event.description,
                        start=start_time,
                        duration=enhanced_event.duration,
                        user_prompt=user_prompt or enhanced_event.user_prompt  # Use provided user_prompt or from enhanced event
                    )
                    structured.events.append(event)
                    print(f"DEBUG: Added event: {event.title} with user_prompt: {event.user_prompt}")
                except Exception as e:
                    print(f"ERROR: Failed to process event {enhanced_event.title}: {e}")
                    # Create a default event for tomorrow if parsing fails
                    default_start = datetime.now() + timedelta(days=1)
                    default_start = default_start.replace(hour=10, minute=0, second=0, microsecond=0)
                    
                    event = Event(
                        title=enhanced_event.title,
                        description=enhanced_event.description,
                        start=default_start,
                        duration=getattr(enhanced_event, 'duration', 30),
                        user_prompt=user_prompt or getattr(enhanced_event, 'user_prompt', '')
                    )
                    structured.events.append(event)
                    print(f"DEBUG: Added default event: {event.title} with user_prompt: {event.user_prompt}")
        
        # Process action items
        if hasattr(result, 'action_items') and result.action_items:
            from models.conversation import ActionItem
            for item in result.action_items:
                structured.action_items.append(ActionItem(description=item))
                print(f"DEBUG: Added action item: {item}")
        
        # Create a conversation with empty transcript but rich structured data
        new_conversation = Conversation(
            id=conversation_id,
            uid=uid,
            structured=structured,
            transcript_segments=[],
            created_at=conversation_timestamp,
            started_at=conversation_timestamp,
            finished_at=conversation_timestamp,
            discarded=False,
            deleted=False,
            source='workflow',
            language='en',  # Default to English
            status='completed'
        )
        
        # Store the conversation in the database
        conversations_db.upsert_conversation(uid, new_conversation.as_dict_cleaned_dates())
        
        print(f"DEBUG: New conversation created successfully with ID: {conversation_id}")
        print(f"DEBUG: Conversation has {len(image_urls)} image URLs")
        
        # Extract memories from image content in background thread
        structured_summary_text = result.overview if hasattr(result, 'overview') else ""
        
        # Add key takeaways and insights to structured summary for memory extraction
        summary_parts = [structured_summary_text] if structured_summary_text else []
        if hasattr(result, 'key_takeaways') and result.key_takeaways:
            summary_parts.append("Key Takeaways: " + "; ".join(result.key_takeaways))
        if hasattr(result, 'things_to_improve') and result.things_to_improve:
            improvement_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_improve]
            summary_parts.append("Growth Opportunities: " + "; ".join(improvement_texts))
        if hasattr(result, 'things_to_learn') and result.things_to_learn:
            learning_texts = [item.content if hasattr(item, 'content') else str(item) for item in result.things_to_learn]
            summary_parts.append("Learning Opportunities: " + "; ".join(learning_texts))
        
        full_structured_summary = "\n\n".join(summary_parts) if summary_parts else ""
        
        print(f"DEBUG: Starting memory extraction for create-from-images with {len(image_descriptions)} image descriptions")
        threading.Thread(
            target=_extract_memories_from_image_conversation,
            args=(uid, conversation_id, image_descriptions, full_structured_summary, None)  # No transcript for image-only
        ).start()
        
        return new_conversation
        
    except Exception as e:
        print(f"ERROR: Exception during image conversation creation: {e}")
        print(f"ERROR: Stack trace: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to create conversation from images: {str(e)}")
