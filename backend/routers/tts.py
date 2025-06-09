"""
Text-to-Speech API endpoints using Azure TTS service
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional
from pydantic import BaseModel, Field
import os
import httpx
import io
import traceback

from utils.other import endpoints as auth

# Add startup logging to verify this module loads
print("🔊 TTS_ROUTER: Loading TTS router module...")

router = APIRouter()

print("🔊 TTS_ROUTER: TTS router module loaded successfully!")


class TTSRequest(BaseModel):
    """Request model for TTS conversion"""
    text: str = Field(..., description="Text content to convert to speech", max_length=10000)
    voice: str = Field(default="alloy", description="Voice to use for TTS")
    speed: float = Field(default=1.0, description="Speech speed (0.25 to 4.0)", ge=0.25, le=4.0)


def truncate_text_for_tts(text: str, max_chars: int = 3000) -> str:
    """
    Truncate text to fit within Azure TTS limits.
    Azure TTS has a 2000 token limit, so we'll use a conservative 3000 character limit.
    """
    print(f"🔊 TTS_TRUNCATE: Input text length: {len(text)} characters")
    
    if len(text) <= max_chars:
        print(f"🔊 TTS_TRUNCATE: Text within limit, no truncation needed")
        return text
    
    print(f"🔊 TTS_TRUNCATE: Text exceeds {max_chars} chars, truncating...")
    
    # Try to truncate at sentence boundaries
    sentences = text.split('. ')
    truncated = ""
    
    for sentence in sentences:
        test_text = truncated + sentence + ". "
        if len(test_text) <= max_chars:
            truncated = test_text
        else:
            break
    
    # If we got at least some content, return it
    if len(truncated) > 100:
        print(f"🔊 TTS_TRUNCATE: Truncated at sentence boundary to {len(truncated)} characters")
        return truncated.strip()
    
    # Fallback: hard truncate at character limit
    fallback_text = text[:max_chars].strip() + "..."
    print(f"🔊 TTS_TRUNCATE: Hard truncated to {len(fallback_text)} characters")
    return fallback_text


@router.post("/v1/tts/speak", tags=['tts'])
async def convert_text_to_speech(
    request: TTSRequest,
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Convert text to speech using Azure TTS service.
    
    This endpoint takes text content (like Agent API conversation summaries)
    and converts it to audio using Azure's TTS service.
    
    Returns audio as a streaming MP3 response that can be played directly.
    """
    print(f"🔊 TTS_SPEAK: Starting convert_text_to_speech for user {uid}")
    
    try:
        # Get Azure TTS configuration from environment
        azure_tts_api_key = os.getenv("AZURE_TTS_API_KEY")
        azure_tts_endpoint = os.getenv("AZURE_TTS_ENDPOINT")
        azure_tts_api_version = os.getenv("AZURE_TTS_API_VERSION", "2025-03-01-preview")
        
        print(f"🔊 TTS_SPEAK: Azure config - endpoint: {azure_tts_endpoint}, version: {azure_tts_api_version}")
        print(f"🔊 TTS_SPEAK: Azure API key present: {bool(azure_tts_api_key)}")
        
        if not azure_tts_api_key or not azure_tts_endpoint:
            print(f"🔴 TTS_SPEAK: Azure TTS service not properly configured")
            print(f"🔴 TTS_SPEAK: API Key present: {bool(azure_tts_api_key)}")
            print(f"🔴 TTS_SPEAK: Endpoint: {repr(azure_tts_endpoint)}")
            raise HTTPException(
                status_code=500, 
                detail="Azure TTS service not properly configured"
            )
        
        # Skip truncation for testing - use original text
        text_to_convert = request.text
        
        print(f"🔊 TTS_SPEAK: Converting text to speech for user {uid}")
        print(f"🔊 TTS_SPEAK: Text length: {len(text_to_convert)} characters")
        print(f"🔊 TTS_SPEAK: Voice: {request.voice}, Speed: {request.speed}")
        
        # Prepare Azure TTS request
        azure_url = f"{azure_tts_endpoint}?api-version={azure_tts_api_version}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {azure_tts_api_key}"
        }
        
        payload = {
            "model": "gpt-4o-mini-tts",
            "input": text_to_convert,
            "voice": request.voice,
            "speed": request.speed
        }
        
        print(f"🔊 TTS_SPEAK: Making request to {azure_url}")
        print(f"🔊 TTS_SPEAK: Payload keys: {list(payload.keys())}")
        
        # Call Azure TTS service
        async with httpx.AsyncClient(timeout=60.0) as client:
            print(f"🔊 TTS_SPEAK: Sending request to Azure TTS...")
            response = await client.post(
                azure_url,
                headers=headers,
                json=payload
            )
            
            print(f"🔊 TTS_SPEAK: Azure response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"🔴 TTS_SPEAK: Azure TTS API error: {response.status_code} - {response.text}")
                print(f"🔴 TTS_SPEAK: Response headers: {dict(response.headers)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Azure TTS service error: {response.status_code} - {response.text}"
                )
            
            # Get audio content
            audio_content = response.content
            print(f"🔊 TTS_SPEAK: Generated audio - {len(audio_content)} bytes")
            
            # Create streaming response
            return StreamingResponse(
                io.BytesIO(audio_content),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Cache-Control": "no-cache"
                }
            )
            
    except HTTPException:
        print(f"🔴 TTS_SPEAK: HTTPException raised, re-raising")
        raise
    except Exception as e:
        print(f"🔴 TTS_SPEAK: Error converting text to speech: {str(e)}")
        print(f"🔴 TTS_SPEAK: Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error converting text to speech: {str(e)}"
        )


@router.post("/v1/tts/conversation/{conversation_id}", tags=['tts'])
async def convert_conversation_summary_to_speech(
    conversation_id: str,
    voice: str = "nova",
    speed: float = 1.2,
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Convert a specific conversation's agent analysis to speech.
    
    This endpoint first checks if a cached audio file exists in Firebase Storage.
    If found, it returns a redirect to the cached file URL.
    If not found, it generates new audio using Azure TTS and caches it.
    """
    print(f"🔊 TTS_CONVERSATION: Starting convert_conversation_summary_to_speech for conversation {conversation_id}, user {uid}")
    
    try:
        # First, check if cached audio exists in Firebase Storage
        from utils.other.storage import get_conversation_audio_url, upload_conversation_audio
        
        print(f"🔊 TTS_CONVERSATION: Checking for cached audio (voice: {voice}, speed: {speed})")
        cached_audio_url = get_conversation_audio_url(uid, conversation_id, voice, speed)
        
        if cached_audio_url:
            print(f"🔊 TTS_CONVERSATION: Found cached audio, redirecting to: {cached_audio_url}")
            # Return redirect to cached audio file
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=cached_audio_url, status_code=302)
        
        print(f"🔊 TTS_CONVERSATION: No cached audio found, generating new audio")
        
        # Get conversation data
        import database.conversations as conversations_db
        conversation_data = conversations_db.get_conversation(uid, conversation_id)
        
        if not conversation_data:
            print(f"🔴 TTS_CONVERSATION: Conversation {conversation_id} not found for user {uid}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        print(f"🔊 TTS_CONVERSATION: Retrieved conversation data")
        
        # Extract agent analysis text
        agent_analysis = None
        if (conversation_data.get('structured', {}).get('agent_analysis')):
            agent_analysis = conversation_data['structured']['agent_analysis']
            print(f"🔊 TTS_CONVERSATION: Using agent_analysis field")
        elif (conversation_data.get('structured', {}).get('overview')):
            agent_analysis = conversation_data['structured']['overview']
            print(f"🔊 TTS_CONVERSATION: Using overview field")
        else:
            print(f"🔴 TTS_CONVERSATION: No summary content found in conversation")
            raise HTTPException(
                status_code=400, 
                detail="No agent analysis or summary content found in conversation"
            )
        
        print(f"🔊 TTS_CONVERSATION: Converting conversation {conversation_id} summary to speech")
        print(f"🔊 TTS_CONVERSATION: Content length: {len(agent_analysis)} characters")
        
        # Generate audio using Azure TTS
        text_to_convert = agent_analysis
        
        # Get Azure TTS configuration
        azure_tts_api_key = os.getenv("AZURE_TTS_API_KEY")
        azure_tts_endpoint = os.getenv("AZURE_TTS_ENDPOINT")
        azure_tts_api_version = os.getenv("AZURE_TTS_API_VERSION", "2025-03-01-preview")
        
        if not azure_tts_api_key or not azure_tts_endpoint:
            print(f"🔴 TTS_CONVERSATION: Azure TTS service not properly configured")
            raise HTTPException(
                status_code=500, 
                detail="Azure TTS service not properly configured"
            )
        
        # Prepare Azure TTS request
        azure_url = f"{azure_tts_endpoint}?api-version={azure_tts_api_version}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {azure_tts_api_key}"
        }
        
        payload = {
            "model": "gpt-4o-mini-tts",
            "input": text_to_convert,
            "voice": voice,
            "speed": speed
        }
        
        print(f"🔊 TTS_CONVERSATION: Making request to Azure TTS...")
        
        # Call Azure TTS service
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                azure_url,
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                print(f"🔴 TTS_CONVERSATION: Azure TTS API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Azure TTS service error: {response.status_code} - {response.text}"
                )
            
            # Get audio content
            audio_content = response.content
            print(f"🔊 TTS_CONVERSATION: Generated audio - {len(audio_content)} bytes")
            
            # Cache the audio in Firebase Storage
            try:
                print(f"🔊 TTS_CONVERSATION: Uploading audio to Firebase Storage...")
                cached_url = upload_conversation_audio(audio_content, uid, conversation_id, voice, speed)
                print(f"🔊 TTS_CONVERSATION: Audio cached successfully at: {cached_url}")
            except Exception as cache_error:
                print(f"🔴 TTS_CONVERSATION: Failed to cache audio: {cache_error}")
                # Continue with direct audio response even if caching fails
            
            # Return the audio as streaming response
            return StreamingResponse(
                io.BytesIO(audio_content),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=speech.mp3",
                    "Cache-Control": "public, max-age=3600"  # Cache for 1 hour
                }
            )
        
    except HTTPException:
        print(f"🔴 TTS_CONVERSATION: HTTPException raised, re-raising")
        raise
    except Exception as e:
        print(f"🔴 TTS_CONVERSATION: Error converting conversation summary: {str(e)}")
        print(f"🔴 TTS_CONVERSATION: Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error converting conversation summary: {str(e)}"
        )


@router.delete("/v1/tts/conversation/{conversation_id}/cache", tags=['tts'])
async def clear_conversation_audio_cache(
    conversation_id: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Clear cached audio files for a conversation.
    
    If voice and speed are provided, clears specific cached file.
    Otherwise, clears all cached audio files for the conversation.
    """
    print(f"🔊 TTS_CACHE_CLEAR: Clearing audio cache for conversation {conversation_id}, user {uid}")
    
    try:
        from utils.other.storage import delete_conversation_audio
        
        delete_conversation_audio(uid, conversation_id, voice, speed)
        
        if voice and speed:
            print(f"🔊 TTS_CACHE_CLEAR: Cleared specific cache for voice={voice}, speed={speed}")
            return {"message": f"Cleared cached audio for voice={voice}, speed={speed}"}
        else:
            print(f"🔊 TTS_CACHE_CLEAR: Cleared all audio cache for conversation")
            return {"message": "Cleared all cached audio for conversation"}
            
    except Exception as e:
        print(f"🔴 TTS_CACHE_CLEAR: Error clearing audio cache: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error clearing audio cache: {str(e)}"
        )


@router.get("/v1/tts/voices", tags=['tts'])
async def get_available_voices():
    """
    Get list of available TTS voices.
    
    Returns the voices supported by Azure TTS service.
    """
    print(f"🔊 TTS_VOICES: Returning available voices list")
    return {
        "voices": [
            {"id": "alloy", "name": "Alloy", "description": "Neutral, balanced voice"},
            {"id": "echo", "name": "Echo", "description": "Calm, thoughtful voice"},
            {"id": "fable", "name": "Fable", "description": "Warm, storytelling voice"},
            {"id": "onyx", "name": "Onyx", "description": "Deep, authoritative voice"},
            {"id": "nova", "name": "Nova", "description": "Bright, energetic voice"},
            {"id": "shimmer", "name": "Shimmer", "description": "Gentle, soothing voice"}
        ],
        "default_voice": "alloy",
        "speed_range": {"min": 0.25, "max": 4.0, "default": 1.0}
    }

print("🔊 TTS_ROUTER: TTS router setup complete!") 