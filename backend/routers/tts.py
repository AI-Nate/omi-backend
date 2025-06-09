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

router = APIRouter()


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
    if len(text) <= max_chars:
        return text
    
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
        return truncated.strip()
    
    # Fallback: hard truncate at character limit
    return text[:max_chars].strip() + "..."


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
    try:
        # Get Azure TTS configuration from environment
        azure_tts_api_key = os.getenv("AZURE_TTS_API_KEY")
        azure_tts_endpoint = os.getenv("AZURE_TTS_ENDPOINT")
        azure_tts_api_version = os.getenv("AZURE_TTS_API_VERSION", "2025-03-01-preview")
        
        if not azure_tts_api_key or not azure_tts_endpoint:
            raise HTTPException(
                status_code=500, 
                detail="Azure TTS service not properly configured"
            )
        
        # Truncate text if it's too long for Azure TTS
        original_length = len(request.text)
        truncated_text = truncate_text_for_tts(request.text)
        
        print(f"🔊 TTS: Converting text to speech for user {uid}")
        print(f"🔊 TTS: Original text length: {original_length} characters")
        print(f"🔊 TTS: Truncated text length: {len(truncated_text)} characters")
        print(f"🔊 TTS: Voice: {request.voice}, Speed: {request.speed}")
        
        # Prepare Azure TTS request
        azure_url = f"{azure_tts_endpoint}?api-version={azure_tts_api_version}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {azure_tts_api_key}"
        }
        
        payload = {
            "model": "gpt-4o-mini-tts",
            "input": truncated_text,
            "voice": request.voice,
            "speed": request.speed
        }
        
        print(f"🔊 TTS: Making request to {azure_url}")
        print(f"🔊 TTS: Payload: {payload}")
        
        # Call Azure TTS service
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                azure_url,
                headers=headers,
                json=payload
            )
            
            print(f"🔊 TTS: Azure response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"🔴 TTS: Azure TTS API error: {response.status_code} - {response.text}")
                print(f"🔴 TTS: Response headers: {dict(response.headers)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Azure TTS service error: {response.status_code} - {response.text}"
                )
            
            # Get audio content
            audio_content = response.content
            print(f"🔊 TTS: Generated audio - {len(audio_content)} bytes")
            
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
        raise
    except Exception as e:
        print(f"🔴 TTS: Error converting text to speech: {str(e)}")
        print(f"🔴 TTS: Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error converting text to speech: {str(e)}"
        )


@router.post("/v1/tts/conversation/{conversation_id}", tags=['tts'])
async def convert_conversation_summary_to_speech(
    conversation_id: str,
    voice: str = "alloy",
    speed: float = 1.0,
    uid: str = Depends(auth.get_current_user_uid)
):
    """
    Convert a specific conversation's agent analysis to speech.
    
    This endpoint retrieves a conversation's agent analysis text
    and converts it to audio using Azure TTS service.
    """
    try:
        # Get conversation data
        import database.conversations as conversations_db
        conversation_data = conversations_db.get_conversation(uid, conversation_id)
        
        if not conversation_data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Extract agent analysis text
        agent_analysis = None
        if (conversation_data.get('structured', {}).get('agent_analysis')):
            agent_analysis = conversation_data['structured']['agent_analysis']
        elif (conversation_data.get('structured', {}).get('overview')):
            agent_analysis = conversation_data['structured']['overview']
        else:
            raise HTTPException(
                status_code=400, 
                detail="No agent analysis or summary content found in conversation"
            )
        
        print(f"🔊 TTS: Converting conversation {conversation_id} summary to speech")
        print(f"🔊 TTS: Content length: {len(agent_analysis)} characters")
        
        # Convert to speech using the main TTS function
        tts_request = TTSRequest(text=agent_analysis, voice=voice, speed=speed)
        return await convert_text_to_speech(tts_request, uid)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"🔴 TTS: Error converting conversation summary: {str(e)}")
        print(f"🔴 TTS: Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error converting conversation summary: {str(e)}"
        )


@router.get("/v1/tts/voices", tags=['tts'])
async def get_available_voices():
    """
    Get list of available TTS voices.
    
    Returns the voices supported by Azure TTS service.
    """
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