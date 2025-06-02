# User Prompt Input for Image-Based Conversation Generation

## Overview
This implementation adds user prompt input functionality to both timeline image creation and conversation image summary features, allowing users to provide context and instructions to help generate more relevant events and insights.

## Backend Changes Made Previously
The backend was already updated to support user prompts in the following endpoints:
- `/v1/conversations/create-from-images` - accepts `user_prompt` form field
- `/v1/conversations/{id}/upload-images` - accepts `user_prompt` form field

The user prompt is passed to the LLM analysis to provide better context for generating events, action items, and insights.

## Frontend Changes Made

### 1. Updated API Functions (`app/lib/backend/http/api/conversations.dart`)

#### `createConversationFromImages`
- Added optional `userPrompt` parameter
- Sends `user_prompt` form field to backend when provided

#### `uploadAndProcessConversationImages`
- Added optional `userPrompt` parameter  
- Sends `user_prompt` form field to backend when provided

### 2. Created User Prompt Dialog Widget (`app/lib/widgets/user_prompt_dialog.dart`)

#### `UserPromptDialog` Widget
- Reusable dialog for collecting user context/instructions
- Features:
  - Multi-line text input with validation
  - Three action buttons: Cancel, Skip, Add Context
  - Dark theme styling consistent with app
  - Auto-focus for better UX

#### `showUserPromptDialog` Helper Function
- Convenient function to show the dialog
- Returns `String?` (null if cancelled, empty string if skipped, prompt text if provided)

### 3. Updated Timeline Provider (`app/lib/providers/timeline_provider.dart`)

#### `createTimelineConversationFromImages`
- Now accepts `BuildContext` parameter
- Shows user prompt dialog before creating conversation
- Passes user prompt to API call
- Returns early if user cancels

### 4. Updated Home Page (`app/lib/pages/home/page.dart`)

#### Timeline + Button Handler
- Passes `BuildContext` to `createTimelineConversationFromImages` call
- Maintains existing success/error messaging

### 5. Updated Conversation Detail Provider (`app/lib/pages/conversation_detail/conversation_detail_provider.dart`)

#### `addImageToSummary`
- Now accepts `BuildContext` parameter
- Shows user prompt dialog before uploading images
- Passes user prompt to API call
- Returns early if user cancels

### 6. Updated Conversation Detail Widgets (`app/lib/pages/conversation_detail/widgets.dart`)

#### "Add Image to Summary" Menu Item
- Passes `BuildContext` to `addImageToSummary` call

## User Experience Flow

### Timeline Image Creation
1. User taps + button in Timeline tab
2. Image picker opens for multi-image selection
3. If images selected, user prompt dialog appears with title "Add Context to Your Images"
4. User can:
   - Add context/instructions and tap "Add Context"
   - Skip by tapping "Skip" (empty prompt sent)
   - Cancel by tapping "Cancel" (operation cancelled)
5. Images and prompt sent to backend for processing
6. New conversation created with enhanced insights

### Conversation Image Summary
1. User navigates to conversation detail
2. User taps three-dot menu → "Add Image to Summary"
3. Image picker opens for multi-image selection
4. If images selected, user prompt dialog appears with title "Add Context to Your Images"
5. User can provide context, skip, or cancel (same as timeline)
6. Images and prompt sent to backend for processing
7. Conversation summary updated with image insights

## Example User Prompts
- "This was from our quarterly planning session - please create action items and follow-up meetings"
- "These screenshots show the key decisions we made - please extract action items and next steps"
- "This is from a technical discussion - focus on implementation details and technical requirements"
- "Meeting with client about project requirements - identify deliverables and timelines"

## Technical Benefits
1. **Better Context**: User prompts provide LLM with specific context about images
2. **Relevant Events**: Generated events are more aligned with user intentions  
3. **Actionable Items**: Action items and insights are more specific and useful
4. **User Control**: Users can guide the AI analysis based on their needs
5. **Consistent UX**: Same dialog used for both timeline and conversation features

## Integration with Backend
The frontend changes integrate seamlessly with the backend modifications that:
- Accept user prompts in API endpoints
- Include prompts in LLM analysis calls
- Generate enhanced events with user context
- Store user prompts in Event model for reference

This implementation provides a complete end-to-end solution for context-aware image-based conversation generation. 