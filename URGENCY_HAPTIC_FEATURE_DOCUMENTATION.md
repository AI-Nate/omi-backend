# Urgency-Based Haptic Notification Feature

## Overview

The Urgency-Based Haptic Notification feature provides intelligent haptic feedback based on the urgency level of AI-generated conversation summaries. When the Agent API processes a conversation transcript, it automatically assesses the urgency and triggers appropriate haptic patterns to notify users of important content requiring immediate attention.

## Architecture

### Backend Components

#### 1. Agent Prompt Enhancement (`backend/utils/agents/core.py`)
- **Enhanced Prompt**: Extended the existing agent prompt to include urgency assessment without changing the current output format
- **Urgency Criteria**: Added specific criteria for HIGH, MEDIUM, and LOW urgency levels
- **Response Parsing**: Implemented parsing logic to extract urgency assessment from agent responses

#### 2. Urgency Models (`backend/models/urgency.py`)
- **UrgencyLevel Enum**: Defines three urgency levels (HIGH, MEDIUM, LOW)
- **UrgencyAssessment Model**: Pydantic model for urgency data structure
- **Haptic Mapping**: Function to map urgency levels to haptic intensity

#### 3. Agent Models Update (`backend/models/agent.py`)
- **Extended Response Model**: Added `urgency_assessment` field to `AgentAnalysisResponse`
- **Backward Compatibility**: Maintains existing API structure while adding new functionality

#### 4. Conversation Models (`backend/models/conversation.py`)
- **Structured Model Enhancement**: Added `urgency_assessment` field to store urgency data
- **Database Integration**: Urgency data is persisted with conversation records

#### 5. Router Integration (`backend/routers/agent_conversations.py`)
- **Urgency Processing**: Extracts and stores urgency assessment from agent results
- **Logging**: Comprehensive logging for debugging and monitoring

### Frontend Components

#### 1. Flutter Models (`app/lib/backend/schema/structured.dart`)
- **Urgency Field**: Added `urgencyAssessment` field to `Structured` class
- **JSON Parsing**: Handles both camelCase and snake_case field names
- **Serialization**: Includes urgency data in conversation serialization

#### 2. Haptic Service (`app/lib/services/urgency_haptic_service.dart`)
- **UrgencyHapticService**: Main service class for haptic functionality
- **Pattern Mapping**: Maps urgency levels to specific haptic patterns
- **Device Compatibility**: Uses Flutter's built-in HapticFeedback for cross-platform support
- **Error Handling**: Graceful fallback for devices without haptic support

#### 3. Integration (`app/lib/providers/capture_provider.dart`)
- **Conversation Processing**: Triggers haptic feedback when conversations are created
- **Background Processing**: Supports haptic feedback for background conversation processing
- **Error Handling**: Comprehensive error handling and logging

#### 4. Test Interface (`app/lib/pages/settings/urgency_haptic_test_page.dart`)
- **Testing UI**: Allows users to test different urgency patterns
- **Sample Assessments**: Provides realistic examples of urgency assessments
- **Feedback Display**: Shows test results and urgency descriptions

## Urgency Assessment Criteria

### HIGH Urgency
- **Triggers**: Urgent deadlines, emergencies, critical decisions, time-sensitive opportunities
- **Timeframe**: Requires action within hours
- **Haptic Pattern**: Double heavy impact with extra emphasis for action required
- **Examples**: 
  - Meeting in 30 minutes
  - Urgent client request
  - Critical system alert

### MEDIUM Urgency
- **Triggers**: Important information requiring action soon, significant decisions, flexible opportunities
- **Timeframe**: Requires action within days
- **Haptic Pattern**: Double medium impact with extra emphasis for action required
- **Examples**:
  - Project deadline next week
  - Important email requiring response
  - Scheduled follow-up task

### LOW Urgency
- **Triggers**: Informational content, routine discussions, casual planning
- **Timeframe**: No rush or flexible timing
- **Haptic Pattern**: Single light impact with extra emphasis for action required
- **Examples**:
  - Casual conversation
  - General information sharing
  - Long-term planning discussion

## Haptic Patterns

### Pattern Design
- **Low Urgency**: Single light haptic pulse (100ms)
- **Medium Urgency**: Double medium haptic pulse (300ms + 150ms pause + 300ms)
- **High Urgency**: Double heavy haptic pulse (500ms + 200ms pause + 500ms)
- **Action Required**: Additional short pulse for any urgency level requiring immediate action

### Implementation Details
- **Cross-Platform**: Uses Flutter's `HapticFeedback` class for iOS and Android compatibility
- **Fallback Support**: Graceful degradation for devices without haptic capabilities
- **User Control**: Patterns can be tested through the settings interface

## API Integration

### Agent API Enhancement
The existing Agent API now includes urgency assessment in the same LLM call:

```
URGENCY ASSESSMENT:
Level: [high/medium/low]
Reasoning: [Brief explanation for the urgency level]
Action Required: [yes/no - whether immediate action is needed]
Time Sensitivity: [Specific timeframe]
```

### Response Structure
```json
{
  "analysis": "...",
  "urgency_assessment": {
    "level": "medium",
    "reasoning": "Important project planning but no immediate deadlines",
    "action_required": false,
    "time_sensitivity": "within 1 week"
  }
}
```

## Usage Flow

1. **Conversation Recording**: User records conversation using omi device
2. **Agent Processing**: Backend processes transcript with enhanced agent prompt
3. **Urgency Assessment**: Agent evaluates urgency based on content and context
4. **Response Parsing**: Backend extracts urgency assessment from agent response
5. **Data Storage**: Urgency data is stored with conversation in database
6. **Haptic Trigger**: Frontend receives conversation and triggers appropriate haptic pattern
7. **User Notification**: User receives haptic feedback indicating conversation urgency

## Configuration

### Backend Configuration
- **Prompt Customization**: Urgency criteria can be adjusted in agent prompt
- **Assessment Logic**: Parsing logic can be modified for different urgency formats
- **Database Schema**: Urgency fields are optional and backward compatible

### Frontend Configuration
- **Haptic Patterns**: Pattern timing and intensity can be customized
- **User Preferences**: Future enhancement could include user-configurable patterns
- **Device Support**: Automatic detection and fallback for haptic capabilities

## Testing

### Backend Testing
- **Unit Tests**: Test urgency assessment parsing and validation
- **Integration Tests**: Test agent API with urgency assessment
- **Edge Cases**: Handle malformed or missing urgency data

### Frontend Testing
- **Haptic Testing**: Test page for all urgency patterns
- **Device Testing**: Verify functionality across different devices
- **Error Handling**: Test graceful degradation without haptic support

### Test Interface Usage
1. Navigate to Settings → Urgency Haptic Test
2. Test basic urgency levels (Low, Medium, High)
3. Test sample urgency assessments with realistic scenarios
4. Verify haptic patterns match expected intensity and duration

## Performance Considerations

### Backend Performance
- **Single LLM Call**: Urgency assessment uses the same agent call, no additional API requests
- **Efficient Parsing**: Regex-based parsing for fast urgency extraction
- **Optional Storage**: Urgency data is optional and doesn't affect existing functionality

### Frontend Performance
- **Lightweight Service**: Haptic service has minimal memory footprint
- **Async Processing**: Haptic feedback doesn't block UI operations
- **Error Recovery**: Quick fallback for failed haptic operations

## Future Enhancements

### Planned Features
1. **User Customization**: Allow users to customize haptic patterns
2. **Smart Scheduling**: Respect user's do-not-disturb settings
3. **Learning Algorithm**: Adapt urgency assessment based on user feedback
4. **Integration Settings**: Configure urgency thresholds per conversation type

### Potential Improvements
1. **Hardware Integration**: Direct integration with omi device haptic motor
2. **Context Awareness**: Consider user's current activity and location
3. **Batch Processing**: Handle multiple urgent conversations intelligently
4. **Analytics**: Track urgency assessment accuracy and user response

## Troubleshooting

### Common Issues
1. **No Haptic Feedback**: Check device haptic support and permissions
2. **Incorrect Urgency**: Verify agent prompt and parsing logic
3. **Performance Issues**: Monitor LLM response times and parsing efficiency

### Debug Information
- **Backend Logs**: Look for urgency assessment extraction logs
- **Frontend Logs**: Check haptic service execution logs
- **Test Interface**: Use test page to verify haptic functionality

### Error Handling
- **Graceful Degradation**: System continues to work without haptic feedback
- **Fallback Patterns**: Alternative haptic methods for unsupported devices
- **User Feedback**: Clear error messages and recovery suggestions

## Security and Privacy

### Data Handling
- **No Additional Data**: Urgency assessment doesn't collect new personal data
- **Local Processing**: Haptic patterns are generated locally on device
- **Optional Feature**: Users can disable haptic feedback if desired

### Privacy Considerations
- **Conversation Content**: Urgency assessment is based on existing conversation analysis
- **No External Calls**: Haptic processing doesn't send data to external services
- **User Control**: Full user control over haptic feedback preferences 