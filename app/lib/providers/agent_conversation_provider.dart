import 'dart:async';
import 'package:flutter/material.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:omi/backend/schema/transcript_segment.dart';
import 'package:omi/providers/base_provider.dart';

class AgentConversationProvider extends BaseProvider {
  bool _isAnalyzing = false;
  String? _currentSessionId;
  AgentAnalysisResponse? _currentAnalysis;
  String? _lastError;
  StreamSubscription<Map<String, dynamic>>? _streamSubscription;

  // Stream controller for real-time analysis updates
  final StreamController<Map<String, dynamic>> _analysisStreamController =
      StreamController<Map<String, dynamic>>.broadcast();

  // Getters
  bool get isAnalyzing => _isAnalyzing;
  String? get currentSessionId => _currentSessionId;
  AgentAnalysisResponse? get currentAnalysis => _currentAnalysis;
  String? get lastError => _lastError;
  Stream<Map<String, dynamic>> get analysisStream =>
      _analysisStreamController.stream;

  // Start analyzing a conversation with the agent
  Future<void> analyzeConversation({
    required List<TranscriptSegment> transcriptSegments,
    String? conversationId,
    bool useStreaming = false,
  }) async {
    debugPrint('🟣 AGENT_PROVIDER: analyzeConversation() called');
    debugPrint(
        '🟣 AGENT_PROVIDER: transcriptSegments.length = ${transcriptSegments.length}');
    debugPrint('🟣 AGENT_PROVIDER: conversationId = $conversationId');
    debugPrint('🟣 AGENT_PROVIDER: useStreaming = $useStreaming');

    if (_isAnalyzing) {
      debugPrint('🔴 AGENT_PROVIDER: Agent analysis already in progress');
      return;
    }

    _setAnalyzing(true);
    _clearError();

    // Generate session ID
    _currentSessionId = DateTime.now().millisecondsSinceEpoch.toString();
    debugPrint('🟣 AGENT_PROVIDER: Generated session ID: $_currentSessionId');

    // Convert transcript segments to text
    final transcript = TranscriptSegment.segmentsAsString(transcriptSegments);
    debugPrint(
        '🟣 AGENT_PROVIDER: Converted transcript, length = ${transcript.length}');

    if (transcript.isEmpty) {
      debugPrint('🔴 AGENT_PROVIDER: No transcript available for analysis');
      _setError('No transcript available for analysis');
      _setAnalyzing(false);
      return;
    }

    try {
      if (useStreaming) {
        debugPrint('🟣 AGENT_PROVIDER: Starting streaming analysis');
        await _startStreamingAnalysis(
          transcript: transcript,
          conversationId: conversationId,
        );
      } else {
        debugPrint('🟣 AGENT_PROVIDER: Starting standard analysis');
        await _performStandardAnalysis(
          transcript: transcript,
          conversationId: conversationId,
        );
      }
    } catch (e) {
      debugPrint('🔴 AGENT_PROVIDER: Error during agent analysis: $e');
      _setError('Analysis failed: ${e.toString()}');
      _setAnalyzing(false);
    }
  }

  // Standard (non-streaming) analysis
  Future<void> _performStandardAnalysis({
    required String transcript,
    String? conversationId,
  }) async {
    debugPrint('🟣 AGENT_PROVIDER: _performStandardAnalysis() called');
    debugPrint('🟣 AGENT_PROVIDER: Calling analyzeConversationWithAgent API');

    final response = await analyzeConversationWithAgent(
      transcript: transcript,
      conversationId: conversationId,
      sessionId: _currentSessionId!,
    );

    debugPrint(
        '🟣 AGENT_PROVIDER: analyzeConversationWithAgent API response received');
    debugPrint('🟣 AGENT_PROVIDER: response = $response');

    if (response != null && response.status == 'success') {
      debugPrint('🟢 AGENT_PROVIDER: Agent analysis successful');
      _currentAnalysis = response;

      final streamEvent = {
        'type': 'analysis_complete',
        'analysis': response.analysis,
        'retrieved_conversations': response.retrievedConversations,
        'timestamp': response.timestamp,
        'session_id': _currentSessionId,
      };

      debugPrint('🟣 AGENT_PROVIDER: Adding to analysis stream: $streamEvent');
      debugPrint(
          '🟣 AGENT_PROVIDER: Stream controller has ${_analysisStreamController.hasListener ? 'listeners' : 'NO listeners'}');
      _analysisStreamController.add(streamEvent);
      debugPrint('🟣 AGENT_PROVIDER: Stream event sent successfully');
      debugPrint('🟣 AGENT_PROVIDER: Agent analysis completed successfully');
    } else {
      debugPrint('🔴 AGENT_PROVIDER: Agent analysis failed');
      debugPrint(
          '🔴 AGENT_PROVIDER: Error: ${response?.error ?? 'Analysis failed with unknown error'}');
      _setError(response?.error ?? 'Analysis failed with unknown error');
    }

    _setAnalyzing(false);
    debugPrint('🟣 AGENT_PROVIDER: _performStandardAnalysis() completed');
  }

  // Streaming analysis
  Future<void> _startStreamingAnalysis({
    required String transcript,
    String? conversationId,
  }) async {
    try {
      final stream = streamAgentConversationAnalysis(
        transcript: transcript,
        conversationId: conversationId,
        sessionId: _currentSessionId!,
      );

      _streamSubscription = stream.listen(
        (event) {
          _analysisStreamController.add(event);

          // Handle completion
          if (event['type'] == 'completion' || event['type'] == 'done') {
            _setAnalyzing(false);
          }

          // Handle errors
          if (event['type'] == 'error') {
            _setError(event['error'] ?? 'Streaming analysis error');
            _setAnalyzing(false);
          }
        },
        onError: (error) {
          debugPrint('Streaming analysis error: $error');
          _setError('Streaming failed: ${error.toString()}');
          _setAnalyzing(false);
        },
        onDone: () {
          debugPrint('Streaming analysis completed');
          _setAnalyzing(false);
        },
      );
    } catch (e) {
      debugPrint('Error starting streaming analysis: $e');
      _setError('Failed to start streaming: ${e.toString()}');
      _setAnalyzing(false);
    }
  }

  // Continue conversation with follow-up questions
  Future<AgentContinueResponse?> askFollowUpQuestion(String message) async {
    if (_currentSessionId == null) {
      _setError('No active session for follow-up questions');
      return null;
    }

    try {
      final response = await continueAgentConversation(
        message: message,
        sessionId: _currentSessionId!,
      );

      if (response != null && response.status == 'success') {
        _analysisStreamController.add({
          'type': 'follow_up_response',
          'response': response.response,
          'timestamp': response.timestamp,
        });
        return response;
      } else {
        _setError(response?.error ?? 'Follow-up question failed');
        return null;
      }
    } catch (e) {
      debugPrint('Error in follow-up question: $e');
      _setError('Follow-up failed: ${e.toString()}');
      return null;
    }
  }

  // Get session information
  Future<Map<String, dynamic>?> getSessionInfo() async {
    if (_currentSessionId == null) return null;

    try {
      return await getAgentSessionInfo(_currentSessionId!);
    } catch (e) {
      debugPrint('Error getting session info: $e');
      return null;
    }
  }

  // Clear current session
  Future<void> clearSession() async {
    if (_currentSessionId != null) {
      try {
        await clearAgentSession(_currentSessionId!);
      } catch (e) {
        debugPrint('Error clearing session: $e');
      }
    }

    _resetSession();
  }

  // Stop any ongoing analysis
  void stopAnalysis() {
    _streamSubscription?.cancel();
    _streamSubscription = null;
    _setAnalyzing(false);
  }

  // Reset session state
  void _resetSession() {
    _currentSessionId = null;
    _currentAnalysis = null;
    _clearError();
    _setAnalyzing(false);
    stopAnalysis();
  }

  // Helper methods
  void _setAnalyzing(bool analyzing) {
    _isAnalyzing = analyzing;
    notifyListeners();
  }

  void _setError(String error) {
    _lastError = error;
    notifyListeners();
  }

  void _clearError() {
    _lastError = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _streamSubscription?.cancel();
    _analysisStreamController.close();
    super.dispose();
  }

  // Quick analysis method for existing conversations
  Future<void> analyzeExistingConversation(String conversationId) async {
    try {
      // This would require getting the conversation from the conversation provider
      // For now, we'll just create a session for the conversation ID
      _currentSessionId = DateTime.now().millisecondsSinceEpoch.toString();

      final response = await analyzeConversationWithAgent(
        transcript: '', // Would need to get transcript from conversation
        conversationId: conversationId,
        sessionId: _currentSessionId!,
      );

      if (response != null && response.status == 'success') {
        _currentAnalysis = response;
        _analysisStreamController.add({
          'type': 'analysis_complete',
          'analysis': response.analysis,
          'retrieved_conversations': response.retrievedConversations,
          'timestamp': response.timestamp,
        });
      } else {
        _setError(response?.error ?? 'Analysis failed');
      }
    } catch (e) {
      debugPrint('Error analyzing existing conversation: $e');
      _setError('Failed to analyze conversation: ${e.toString()}');
    }
  }
}
