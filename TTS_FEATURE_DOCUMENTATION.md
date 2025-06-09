# Text-to-Speech (TTS) Feature for Agent Conversations

## Overview
This feature adds the ability to listen to Agent API conversation summaries using Azure's Text-to-Speech service. Users can click a "Listen" button in the conversation detail view to have the entire conversation summary read aloud.

## Architecture

### Backend Components

#### 1. Azure TTS Configuration
- **Environment Variables**:
  - `AZURE_TTS_API_KEY`: Azure TTS service API key
  - `AZURE_TTS_ENDPOINT`: Azure TTS service endpoint
  - `AZURE_TTS_API_VERSION`: API version (default: 2025-03-01-preview)

#### 2. TTS Router (`backend/routers/tts.py`)
New API endpoints for text-to-speech functionality:

- **`POST /v1/tts/speak`**: Convert any text to speech
  - Request: `{text, voice, speed}`
  - Response: Audio stream (MP3)

- **`POST /v1/tts/conversation/{conversation_id}`**: Convert conversation summary to speech
  - Request: `{voice, speed}`
  - Response: Audio stream (MP3)

- **`GET /v1/tts/voices`**: Get available voices
  - Response: List of available voices and settings

#### 3. Features
- **Audio Format**: MP3 (compatible with all browsers/devices)
- **Voice Options**: alloy, echo, fable, onyx, nova, shimmer
- **Speed Control**: 0.25x to 4.0x playback speed
- **Error Handling**: Graceful error handling with user feedback

### Frontend Components

#### 1. TTS Service (`app/lib/services/tts_service.dart`)
Singleton service that manages TTS functionality:

- **Audio Playback**: Uses `just_audio` package for cross-platform audio
- **State Management**: Tracks TTS state (idle, loading, playing, paused, error)
- **Custom Audio Source**: `BytesAudioSource` for playing audio from API bytes
- **Error Handling**: Comprehensive error handling with user callbacks

#### 2. Enhanced Summary Widget Updates
Added TTS button to conversation detail page:

- **Location**: Next to "Enhanced Summary" title
- **Design**: Matches existing UI design language
- **States**: Visual feedback for different TTS states
- **Controls**: Play/Stop/Resume functionality

#### 3. User Experience
- **Visual Feedback**: Button changes color and icon based on state
- **Snackbar Notifications**: User feedback for start/stop/error events
- **Non-blocking**: Users can continue using the app while audio plays
- **State Persistence**: TTS state persists across widget rebuilds

## Usage

### For Users
1. Navigate to any conversation created by the Agent API
2. Scroll to the "Enhanced Summary" section
3. Click the "Listen" button next to the title
4. Audio will begin playing automatically
5. Click "Stop" to stop playback or "Resume" if paused

### For Developers

#### Backend API Usage
```bash
# Convert text to speech
curl -X POST "${API_BASE_URL}/v1/tts/speak" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, this is a test",
    "voice": "alloy",
    "speed": 1.0
  }' \
  --output audio.mp3

# Convert conversation to speech
curl -X POST "${API_BASE_URL}/v1/tts/conversation/$CONVERSATION_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "voice": "alloy",
    "speed": 1.0
  }' \
  --output conversation_audio.mp3
```

#### Frontend Service Usage
```dart
// Get TTS service instance
final ttsService = TTSService();

// Speak conversation summary
await ttsService.speakConversationSummary(
  conversation,
  voice: 'alloy',
  speed: 1.0,
  onStart: () => print('Started speaking'),
  onComplete: () => print('Finished speaking'),
  onError: (error) => print('Error: $error'),
);

// Listen to TTS state changes
ttsService.stateNotifier.addListener(() {
  print('TTS State: ${ttsService.stateNotifier.value}');
});
```

## Configuration

### Backend Setup
1. Add Azure TTS credentials to `backend/.env`:
```env
AZURE_TTS_API_KEY=your_api_key_here
AZURE_TTS_ENDPOINT=https://your-region.cognitiveservices.azure.com/openai/deployments/gpt-4o-mini-tts/audio/speech
AZURE_TTS_API_VERSION=2025-03-01-preview
```

2. The TTS router is automatically included in `main.py`

### Frontend Setup
1. The `just_audio` dependency is already included in `pubspec.yaml`
2. TTS service is automatically available app-wide
3. Enhanced summary widget automatically shows TTS button for conversations with content

## Error Handling

### Backend Errors
- **Missing Configuration**: Returns 500 with configuration error message
- **Azure API Errors**: Returns 500 with Azure-specific error details
- **Invalid Input**: Returns 400 with validation error details

### Frontend Errors
- **Network Errors**: Displays user-friendly error message
- **Audio Playback Errors**: Graceful fallback with error state
- **Service Unavailable**: Clear feedback to user with retry option

## Technical Considerations

### Performance
- **Audio Streaming**: Audio is streamed directly to the client
- **Memory Management**: Audio bytes are handled efficiently
- **Background Processing**: TTS generation happens asynchronously

### Security
- **Authentication**: All TTS endpoints require valid authentication
- **Rate Limiting**: Inherits existing API rate limiting
- **Input Validation**: Text length and parameter validation

### Compatibility
- **Cross-Platform**: Works on iOS, Android, and Web
- **Browser Support**: MP3 format supported by all modern browsers
- **Audio Hardware**: Compatible with device speakers, headphones, Bluetooth

## Future Enhancements

### Potential Improvements
1. **Voice Selection UI**: Allow users to choose preferred voice
2. **Speed Control UI**: Add playback speed controls
3. **Audio Caching**: Cache generated audio for repeated playback
4. **Offline Support**: Download audio for offline listening
5. **Background Playback**: Continue playing while app is in background
6. **Playlist Support**: Queue multiple conversations for sequential playback

### Technical Debt
- Consider moving to streaming TTS for very long conversations
- Add audio compression options for bandwidth optimization
- Implement audio transcription for accessibility

## Testing

### Backend Testing
```bash
# Test TTS configuration
cd backend
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('TTS configured:', bool(os.getenv('AZURE_TTS_API_KEY')))"

# Test router import
python -c "from routers.tts import router; print('TTS router works')"
```

### Frontend Testing
- TTS button appears in conversation detail view
- Button states change correctly during playback
- Audio plays through device speakers/headphones
- Error states display appropriate user feedback

## Deployment Notes

### Environment Variables
Ensure all Azure TTS environment variables are set in production:
- `AZURE_TTS_API_KEY`
- `AZURE_TTS_ENDPOINT` 
- `AZURE_TTS_API_VERSION`

### Dependencies
- Backend: `httpx` (already included)
- Frontend: `just_audio` (already included)

### Monitoring
- Monitor Azure TTS API usage and costs
- Track TTS feature adoption through analytics
- Monitor audio playback success/failure rates 