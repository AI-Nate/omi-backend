from fastapi import APIRouter, Depends, HTTPException, Request, Body
from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel

import database.conversations as conversations_db
import database.users as users_db
import database.redis_db as redis_db
from database.vector_db import delete_vector
from models.conversation import *
from models.conversation import SearchRequest

from utils.conversations.process_conversation import process_conversation, retrieve_in_progress_conversation
from utils.conversations.search import search_conversations
from utils.llm import generate_summary_with_prompt, get_transcript_structure, EnhancedSummaryOutput, process_prompt
from utils.other import endpoints as auth
from utils.other.storage import get_conversation_recording_if_exists
from utils.app_integrations import trigger_external_integrations

router = APIRouter()





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
    """
    # Get the existing conversation
    conversation = _get_conversation_by_id(uid, conversation_id)
    
    # Check if we're receiving a single image description or multiple
    image_description = image_data.get("image_description", "")
    image_descriptions = image_data.get("image_descriptions", [])
    
    # Handle both single image and multiple images cases
    if not image_description and not image_descriptions:
        raise HTTPException(status_code=400, detail="Image description is required")
    
    # If we have a single image description, add it to the list
    if image_description:
        image_descriptions.append(image_description)
    
    # Get user language preference (or use English as default)
    user_language = users_db.get_user_language_preference(uid) or 'English'
    # Since we don't have a direct function to get the user's name, we'll use a default
    user_name = 'User'
    
    # Get existing transcript
    transcript = get_conversation_transcript(conversation)
    
    # If this is the first image analysis for this conversation, we'll do a complete analysis
    # For subsequent images, we'll do an incremental analysis to avoid overwriting previous insights
    is_first_analysis = not conversation.get('structured', {}).get('key_takeaways', [])
    
    if is_first_analysis:
        # Create a prompt to analyze the images and generate a new summary
        images_text = "\n\n".join([f"Image {i+1}:\n{desc.strip()}" for i, desc in enumerate(image_descriptions)])
        prompt = f"""
        Based on this conversation transcript and the following image descriptions, provide a comprehensive:
        1. Overview (a concise summary integrating the image content)
        2. Key Takeaways (3-5 bullet points, including insights from the images)
        3. Things to Improve (2-3 practical suggestions personalized for {user_name}, incorporating image insights)
        4. Things to Learn (1-2 topics worth exploring tailored to {user_name}'s interests, related to the image content)
        
        User Information for Personalization:
        - Name: {user_name}
        - Primary language: {user_language}
        
        Make all sections highly personalized, actionable, and relevant based on both the conversation and the image content.
        
        Transcript:
        {transcript}
        
        Images Descriptions:
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
        prompt = f"""
        Based on this conversation transcript, the existing summary, and the new image descriptions, provide additional insights to enhance the current summary.
        
        User Information for Personalization:
        - Name: {user_name}
        - Primary language: {user_language}
        
        Transcript:
        {transcript}
        
        Existing Summary Overview:
        {existing_overview}
        
        Existing Key Takeaways:
        {", ".join(existing_takeaways)}
        
        Existing Things to Improve:
        {", ".join(existing_improvements)}
        
        Existing Things to Learn:
        {", ".join(existing_learnings)}
        
        New Image Descriptions:
        {images_text}
        
        Please provide:
        1. Updated Overview (integrate new insights from the images with the existing overview)
        2. Additional Key Takeaways (new points not covered in existing takeaways)
        3. Additional Things to Improve (new suggestions based on image content)
        4. Additional Things to Learn (new topics related to the image content)
        
        Make all additions highly personalized, actionable, and relevant based on both the conversation and the new image content.
        Avoid repeating existing points.
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
    conversations_db.upsert_conversation(uid, conversation)
    
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
