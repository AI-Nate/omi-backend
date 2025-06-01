import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:omi/backend/http/shared.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/backend/schema/structured.dart';
import 'package:omi/backend/schema/transcript_segment.dart';
import 'package:omi/env/env.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:instabug_flutter/instabug_flutter.dart';
import 'package:path/path.dart';
import 'package:omi/backend/http/openai.dart';
import 'package:omi/backend/preferences.dart';

Future<CreateConversationResponse?> processInProgressConversation() async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations',
    headers: {},
    method: 'POST',
    body: jsonEncode({}),
  );
  if (response == null) return null;
  debugPrint('createConversationServer: ${response.body}');
  if (response.statusCode == 200) {
    return CreateConversationResponse.fromJson(jsonDecode(response.body));
  } else {
    // TODO: Server returns 304 doesn't recover
    CrashReporting.reportHandledCrash(
      Exception('Failed to create conversation'),
      StackTrace.current,
      level: NonFatalExceptionLevel.info,
      userAttributes: {
        'response': response.body,
      },
    );
  }
  return null;
}

Future<List<ServerConversation>> getConversations(
    {int limit = 50,
    int offset = 0,
    List<ConversationStatus> statuses = const [],
    bool includeDiscarded = true}) async {
  var response = await makeApiCall(
      url:
          '${Env.apiBaseUrl}v1/conversations?include_discarded=$includeDiscarded&limit=$limit&offset=$offset&statuses=${statuses.map((val) => val.toString().split(".").last).join(",")}',
      headers: {},
      method: 'GET',
      body: '');
  if (response == null) return [];
  if (response.statusCode == 200) {
    // decode body bytes to utf8 string and then parse json so as to avoid utf8 char issues
    var body = utf8.decode(response.bodyBytes);
    var memories = (jsonDecode(body) as List<dynamic>)
        .map((conversation) => ServerConversation.fromJson(conversation))
        .toList();
    debugPrint('getConversations length: ${memories.length}');
    return memories;
  } else {
    debugPrint('getConversations error ${response.statusCode}');
  }
  return [];
}

Future<ServerConversation?> reProcessConversationServer(String conversationId,
    {String? appId}) async {
  var response = await makeApiCall(
    url:
        '${Env.apiBaseUrl}v1/conversations/$conversationId/reprocess${appId != null ? '?app_id=$appId' : ''}',
    headers: {},
    method: 'POST',
    body: '',
  );
  if (response == null) return null;
  debugPrint('reProcessConversationServer: ${response.body}');
  if (response.statusCode == 200) {
    return ServerConversation.fromJson(jsonDecode(response.body));
  }
  return null;
}

Future<bool> deleteConversationServer(String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId',
    headers: {},
    method: 'DELETE',
    body: '',
  );
  if (response == null) return false;
  debugPrint('deleteConversation: ${response.statusCode}');
  return response.statusCode == 204;
}

Future<ServerConversation?> getConversationById(String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId',
    headers: {},
    method: 'GET',
    body: '',
  );
  if (response == null) return null;
  if (response.statusCode == 200) {
    return ServerConversation.fromJson(jsonDecode(response.body));
  }
  return null;
}

Future<bool> updateConversationTitle(
    String conversationId, String title) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/title?title=$title',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('updateConversationTitle: ${response.body}');
  return response.statusCode == 200;
}

Future<List<ConversationPhoto>> getConversationPhotos(
    String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/photos',
    headers: {},
    method: 'GET',
    body: '',
  );
  if (response == null) return [];
  debugPrint('getConversationPhotos: ${response.body}');
  if (response.statusCode == 200) {
    return (jsonDecode(response.body) as List<dynamic>)
        .map((photo) => ConversationPhoto.fromJson(photo))
        .toList();
  }
  return [];
}

class TranscriptsResponse {
  List<TranscriptSegment> deepgram;
  List<TranscriptSegment> soniox;
  List<TranscriptSegment> whisperx;
  List<TranscriptSegment> speechmatics;

  TranscriptsResponse({
    this.deepgram = const [],
    this.soniox = const [],
    this.whisperx = const [],
    this.speechmatics = const [],
  });

  factory TranscriptsResponse.fromJson(Map<String, dynamic> json) {
    return TranscriptsResponse(
      deepgram: (json['deepgram'] as List<dynamic>)
          .map((segment) => TranscriptSegment.fromJson(segment))
          .toList(),
      soniox: (json['soniox'] as List<dynamic>)
          .map((segment) => TranscriptSegment.fromJson(segment))
          .toList(),
      whisperx: (json['whisperx'] as List<dynamic>)
          .map((segment) => TranscriptSegment.fromJson(segment))
          .toList(),
      speechmatics: (json['speechmatics'] as List<dynamic>)
          .map((segment) => TranscriptSegment.fromJson(segment))
          .toList(),
    );
  }
}

Future<TranscriptsResponse> getConversationTranscripts(
    String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/transcripts',
    headers: {},
    method: 'GET',
    body: '',
  );
  if (response == null) return TranscriptsResponse();
  debugPrint('getConversationTranscripts: ${response.body}');
  if (response.statusCode == 200) {
    var transcripts = (jsonDecode(response.body) as Map<String, dynamic>);
    return TranscriptsResponse.fromJson(transcripts);
  }
  return TranscriptsResponse();
}

Future<bool> hasConversationRecording(String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/recording',
    headers: {},
    method: 'GET',
    body: '',
  );
  if (response == null) return false;
  debugPrint('hasConversationRecording: ${response.body}');
  if (response.statusCode == 200) {
    return jsonDecode(response.body)['has_recording'] ?? false;
  }
  return false;
}

Future<bool> assignConversationTranscriptSegment(
  String conversationId,
  int segmentIdx, {
  bool? isUser,
  String? personId,
  bool useForSpeechTraining = true,
}) async {
  String assignType = isUser != null ? 'is_user' : 'person_id';
  var response = await makeApiCall(
    url:
        '${Env.apiBaseUrl}v1/conversations/$conversationId/segments/$segmentIdx/assign?value=${isUser ?? personId}'
        '&assign_type=$assignType&use_for_speech_training=$useForSpeechTraining',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('assignConversationTranscriptSegment: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> assignConversationSpeaker(
  String conversationId,
  int speakerId,
  bool isUser, {
  String? personId,
  bool useForSpeechTraining = true,
}) async {
  String assignType = isUser ? 'is_user' : 'person_id';
  var response = await makeApiCall(
    url:
        '${Env.apiBaseUrl}v1/conversations/$conversationId/assign-speaker/$speakerId?value=${isUser ? 'true' : personId}'
        '&assign_type=$assignType&use_for_speech_training=$useForSpeechTraining',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('assignConversationSpeaker: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> setConversationVisibility(String conversationId,
    {String visibility = 'shared'}) async {
  var response = await makeApiCall(
    url:
        '${Env.apiBaseUrl}v1/conversations/$conversationId/visibility?value=$visibility&visibility=$visibility',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('setConversationVisibility: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> setConversationEventsState(
  String conversationId,
  List<int> eventsIdx,
  List<bool> values,
) async {
  print(jsonEncode({
    'events_idx': eventsIdx,
    'values': values,
  }));
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/events',
    headers: {},
    method: 'PATCH',
    body: jsonEncode({
      'events_idx': eventsIdx,
      'values': values,
    }),
  );
  if (response == null) return false;
  debugPrint('setConversationEventsState: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> setConversationActionItemState(
  String conversationId,
  List<int> actionItemsIdx,
  List<bool> values,
) async {
  print(jsonEncode({
    'items_idx': actionItemsIdx,
    'values': values,
  }));
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/action-items',
    headers: {},
    method: 'PATCH',
    body: jsonEncode({
      'items_idx': actionItemsIdx,
      'values': values,
    }),
  );
  if (response == null) return false;
  debugPrint('setConversationActionItemState: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> deleteConversationActionItem(
    String conversationId, ActionItem item) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/action-items',
    headers: {},
    method: 'DELETE',
    body: jsonEncode({
      'completed': item.completed,
      'description': item.description,
    }),
  );
  if (response == null) return false;
  debugPrint('deleteConversationActionItem: ${response.body}');
  return response.statusCode == 204;
}

//this is expected to return complete memories
Future<List<ServerConversation>> sendStorageToBackend(
    File file, String sdCardDateTimeString) async {
  var request = http.MultipartRequest(
    'POST',
    Uri.parse('${Env.apiBaseUrl}sdcard_memory?date_time=$sdCardDateTimeString'),
  );
  request.headers.addAll({'Authorization': await getAuthHeader()});
  request.files.add(await http.MultipartFile.fromPath('file', file.path,
      filename: basename(file.path)));
  try {
    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      debugPrint('storageSend Response body: ${jsonDecode(response.body)}');
    } else {
      debugPrint('Failed to storageSend. Status code: ${response.statusCode}');
      return [];
    }

    var memories = (jsonDecode(response.body) as List<dynamic>)
        .map((conversation) => ServerConversation.fromJson(conversation))
        .toList();
    debugPrint('getMemories length: ${memories.length}');

    return memories;
  } catch (e) {
    debugPrint('An error occurred storageSend: $e');
    return [];
  }
}

Future<SyncLocalFilesResponse> syncLocalFiles(List<File> files) async {
  var request = http.MultipartRequest(
    'POST',
    Uri.parse('${Env.apiBaseUrl}v1/sync-local-files'),
  );
  for (var file in files) {
    request.files.add(await http.MultipartFile.fromPath('files', file.path,
        filename: basename(file.path)));
  }
  request.headers.addAll({'Authorization': await getAuthHeader()});

  try {
    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      debugPrint('syncLocalFile Response body: ${jsonDecode(response.body)}');
      return SyncLocalFilesResponse.fromJson(jsonDecode(response.body));
    } else {
      debugPrint(
          'Failed to upload sample. Status code: ${response.statusCode}');
      throw Exception(
          'Failed to upload sample. Status code: ${response.statusCode}');
    }
  } catch (e) {
    debugPrint('An error occurred uploadSample: $e');
    throw Exception('An error occurred uploadSample: $e');
  }
}

Future<(List<ServerConversation>, int, int)> searchConversationsServer(
  String query, {
  int? page,
  int? limit,
  bool includeDiscarded = true,
}) async {
  debugPrint(Env.apiBaseUrl);
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/search',
    headers: {},
    method: 'POST',
    body: jsonEncode({
      'query': query,
      'page': page ?? 1,
      'per_page': limit ?? 10,
      'include_discarded': includeDiscarded
    }),
  );
  if (response == null) return (<ServerConversation>[], 0, 0);
  if (response.statusCode == 200) {
    List<dynamic> items = (jsonDecode(response.body))['items'];
    int currentPage = (jsonDecode(response.body))['current_page'];
    int totalPages = (jsonDecode(response.body))['total_pages'];
    var convos = items
        .map<ServerConversation>((item) => ServerConversation.fromJson(item))
        .toList();
    return (convos, currentPage, totalPages);
  }
  return (<ServerConversation>[], 0, 0);
}

Future<String> testConversationPrompt(
    String prompt, String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/test-prompt',
    headers: {},
    method: 'POST',
    body: jsonEncode({
      'prompt': prompt,
    }),
  );
  if (response == null) return '';
  if (response.statusCode == 200) {
    return jsonDecode(response.body)['summary'];
  } else {
    return '';
  }
}

Future<ServerConversation?> getEnhancedSummary(String conversationId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v1/conversations/$conversationId/enhanced-summary',
    headers: {},
    method: 'POST',
    body: '',
  );
  if (response == null) return null;
  debugPrint('getEnhancedSummary: ${response.statusCode}');
  if (response.statusCode == 200) {
    return ServerConversation.fromJson(jsonDecode(response.body));
  }

  // Fallback: If the enhanced summary endpoint fails or doesn't exist yet,
  // we'll generate it client-side using OpenAI
  var conversation = await getConversationById(conversationId);
  if (conversation != null) {
    // Enrich the summary locally
    await enrichConversationSummary(conversation);
    return conversation;
  }

  return null;
}

// Helper method to locally enrich a conversation summary
Future<void> enrichConversationSummary(ServerConversation conversation) async {
  // Only process if we have some transcript content
  if (conversation.transcriptSegments.isEmpty) return;

  final transcript = conversation.getTranscript(generate: true);

  // Get user preferences and data from local storage for personalization
  final prefs = SharedPreferencesUtil();
  final userName = prefs.givenName ?? 'User';

  // Fetch recent conversation titles to provide context
  List<String> recentTitles = [];
  try {
    final recentConversations = await getConversations(limit: 5);
    if (recentConversations != null && recentConversations.isNotEmpty) {
      recentTitles = recentConversations
          .map((c) => c.structured.title)
          .where((title) => title.isNotEmpty)
          .toList();
    }
  } catch (e) {
    debugPrint('Error fetching recent conversations: $e');
  }

  // Get user language preference
  final userLanguage = prefs.userPrimaryLanguage.isNotEmpty
      ? prefs.userPrimaryLanguage
      : 'English';

  // Use OpenAI to generate enhanced summary components
  try {
    final prompt = '''
    Based on this conversation transcript, provide:
    1. Key Takeaways (3-5 bullet points)
    2. Things to Improve (2-3 specific, actionable recommendations for ${userName})
    3. Things to Learn (1-2 specific learning opportunities for ${userName})
    
    Format your response as JSON with these keys: keyTakeaways, thingsToImprove, thingsToLearn.
    Each keyTakeaways should be a string.
    Each of thingsToImprove and thingsToLearn should be an object with these properties:
      - content: The actual recommendation or learning opportunity (required)
      - url: "" (empty string for now)
      - title: "" (empty string for now)
    
    User Information for Personalization:
    - Name: ${userName}
    - Primary language: ${userLanguage}
    - Recent conversation topics: ${recentTitles.join(', ')}
    
    For "Things to Improve":
    - Start each item with a clear action verb (e.g., "Practice...", "Implement...", "Develop...")
    - Include specific, measurable steps that ${userName} can take immediately
    - Add a brief explanation of the benefit or why this improvement matters
    - Consider both short-term quick wins and longer-term growth opportunities
    - Be direct and concise, focusing on practical implementation
    
    For "Things to Learn":
    - Suggest specific topics or skills rather than broad areas
    - Include a clear, actionable way to begin learning this topic
    - Explain briefly how this learning connects to ${userName}'s interests or needs
    - Focus on knowledge or skills that would have immediate practical value
    
    Make "Things to Improve" and "Things to Learn" highly personalized, actionable, and relevant 
    based on both this conversation and the user's context.
    
    Transcript:
    ${transcript.trim()}
    ''';

    // Call your API or use a local prompt
    final response = await executeGptPrompt(prompt);

    try {
      final Map<String, dynamic> enrichmentData = jsonDecode(response);

      // Update the structured data with enriched content
      if (enrichmentData.containsKey('keyTakeaways')) {
        conversation.structured.keyTakeaways =
            (enrichmentData['keyTakeaways'] as List)
                .map((item) => item.toString())
                .toList();
      }

      // Add things to improve with placeholder URLs
      if (enrichmentData.containsKey('thingsToImprove')) {
        final improvements = enrichmentData['thingsToImprove'] as List;
        conversation.structured.thingsToImprove.clear();

        for (var item in improvements) {
          String content = item.toString();
          conversation.structured.thingsToImprove.add(ResourceItem(content));
        }
      }

      // Add things to learn with placeholder URLs
      if (enrichmentData.containsKey('thingsToLearn')) {
        final learning = enrichmentData['thingsToLearn'] as List;
        conversation.structured.thingsToLearn.clear();

        for (var item in learning) {
          String content = item.toString();
          conversation.structured.thingsToLearn.add(ResourceItem(content));
        }
      }

      // Enhance with web search URLs
      await _enhanceWithWebSearchURLs(conversation);
    } catch (e) {
      debugPrint('Error parsing enrichment data: $e');
    }
  } catch (e) {
    debugPrint('Error generating enriched summary: $e');
  }
}

Future<ServerConversation?> analyzeImageAndUpdateSummary(
    String conversationId, Uint8List imageData,
    {List<Uint8List>? additionalImages}) async {
  try {
    // Create a list to hold all images
    List<Uint8List> allImages = [imageData];
    if (additionalImages != null) {
      allImages.addAll(additionalImages);
    }

    // Get descriptions for all images
    List<String> descriptions = [];
    for (var img in allImages) {
      final description = await getPhotoDescription(img);
      descriptions.add(description);
    }

    // Create the request body
    Map<String, dynamic> requestBody;
    if (descriptions.length == 1) {
      // For backward compatibility, if there's only one image, use the old format
      requestBody = {
        'image_description': descriptions[0],
      };
    } else {
      // For multiple images, use the new format
      requestBody = {
        'image_descriptions': descriptions,
      };
    }

    // Call the API to update the summary with image content
    var response = await makeApiCall(
      url: '${Env.apiBaseUrl}v1/conversations/$conversationId/image-summary',
      headers: {'Content-Type': 'application/json'},
      method: 'POST',
      body: jsonEncode(requestBody),
    );

    if (response == null) return null;
    debugPrint('analyzeImageAndUpdateSummary: ${response.statusCode}');

    if (response.statusCode == 200) {
      return ServerConversation.fromJson(jsonDecode(response.body));
    }

    // Fallback: If the API endpoint fails or doesn't exist yet,
    // we'll generate it client-side using OpenAI
    var conversation = await getConversationById(conversationId);
    if (conversation != null) {
      // Enrich the summary locally with image content
      if (descriptions.length == 1) {
        await enrichConversationSummaryWithImage(conversation, descriptions[0]);
      } else {
        await enrichConversationSummaryWithMultipleImages(
            conversation, descriptions);
      }
      return conversation;
    }

    return null;
  } catch (e) {
    debugPrint('Error analyzing image and updating summary: $e');
    return null;
  }
}

// Helper method to locally enrich a conversation summary with image content
Future<void> enrichConversationSummaryWithImage(
    ServerConversation conversation, String imageDescription) async {
  try {
    final SharedPreferencesUtil prefs = SharedPreferencesUtil();
    final userName = prefs.givenName.isEmpty ? 'User' : prefs.givenName;
    final userLanguage = prefs.userPrimaryLanguage.isEmpty
        ? 'English'
        : prefs.userPrimaryLanguage;

    final transcript = conversation.getTranscript(generate: true);

    // Call the GPT-4o API for enhanced summary
    final prompt = '''
    Based on this conversation transcript and image description, provide an updated:
    1. Overview (a concise summary integrating the image content)
    2. Key Takeaways (3-5 bullet points, including insights from the image)
    3. Things to Improve (2-3 specific, actionable recommendations for ${userName}, incorporating image insights)
    4. Things to Learn (1-2 specific learning opportunities for ${userName}, related to the image content)
    
    Format your response as JSON with these keys: overview, keyTakeaways, thingsToImprove, thingsToLearn.
    Each of keyTakeaways should be a string.
    Each of thingsToImprove and thingsToLearn should be an object with these properties:
      - content: The actual recommendation or learning opportunity (required)
      - url: "" (empty string for now)
      - title: "" (empty string for now)
    
    User Information for Personalization:
    - Name: ${userName}
    - Primary language: ${userLanguage}
    
    For "Things to Improve":
    - Start each item with a clear action verb (e.g., "Practice...", "Implement...", "Develop...")
    - Include specific, measurable steps that ${userName} can take immediately
    - Add a brief explanation of the benefit or why this improvement matters
    - Consider both short-term quick wins and longer-term growth opportunities
    - Be direct and concise, focusing on practical implementation
    
    For "Things to Learn":
    - Suggest specific topics or skills rather than broad areas
    - Include a clear, actionable way to begin learning this topic
    - Explain briefly how this learning connects to ${userName}'s interests or needs
    - Focus on knowledge or skills that would have immediate practical value
    
    Make all sections highly personalized, actionable, and relevant based on both the conversation and the image content.
    
    Transcript:
    ${transcript.trim()}
    
    Image Description:
    ${imageDescription.trim()}
    ''';

    // Use ChatGPT-4o for enhanced summary then find resource URLs with web search
    final response = await executeGptPrompt(prompt);

    try {
      final Map<String, dynamic> enrichmentData = jsonDecode(response);

      // Update the structured data with enriched content
      if (enrichmentData.containsKey('overview')) {
        conversation.structured.overview = enrichmentData['overview'];
      }

      if (enrichmentData.containsKey('keyTakeaways')) {
        conversation.structured.keyTakeaways =
            (enrichmentData['keyTakeaways'] as List)
                .map((item) => item.toString())
                .toList();
      }

      // For things to improve, add URLs using web search
      if (enrichmentData.containsKey('thingsToImprove')) {
        final improvements = enrichmentData['thingsToImprove'] as List;
        conversation.structured.thingsToImprove.clear();

        for (var item in improvements) {
          String content = item.toString();

          // We'll use OpenAI web search to find resources later
          // For now, add the item without URL
          conversation.structured.thingsToImprove.add(
            ResourceItem(
              content,
              url: '', // Will be fetched from backend
              title: '',
            ),
          );

          // Note: In a production app, you would make an API call to your backend to fetch the URLs
          // The backend would then use the web search functionality we implemented
        }
      }

      // For things to learn, add URLs using web search
      if (enrichmentData.containsKey('thingsToLearn')) {
        final learning = enrichmentData['thingsToLearn'] as List;
        conversation.structured.thingsToLearn.clear();

        for (var item in learning) {
          String content = item.toString();

          // We'll use OpenAI web search to find resources later
          // For now, add the item without URL
          conversation.structured.thingsToLearn.add(
            ResourceItem(
              content,
              url: '', // Will be fetched from backend
              title: '',
            ),
          );

          // Note: In a production app, you would make an API call to your backend to fetch the URLs
          // The backend would then use the web search functionality we implemented
        }
      }

      // Enhance with web search URLs - in a real application, you would call
      // your backend API to do this search, not implement it client-side
      await _enhanceWithWebSearchURLs(conversation);
    } catch (e) {
      debugPrint('Error parsing image enrichment data: $e');
    }
  } catch (e) {
    debugPrint('Error generating image-enriched summary: $e');
  }
}

// Helper method to add web search URLs - in a production app this would be an API call
Future<void> _enhanceWithWebSearchURLs(ServerConversation conversation) async {
  // This is just a placeholder - in a real app you'd make an API call to your backend
  // which would use the OpenAI web search we implemented
  //
  // Example API call structure:
  //
  // final response = await makeApiCall(
  //   url: '${Env.apiBaseUrl}v1/conversations/${conversation.id}/enhance-with-urls',
  //   method: 'POST',
  //   body: jsonEncode({
  //     'improve_items': conversation.structured.thingsToImprove.map((i) => i.content).toList(),
  //     'learn_items': conversation.structured.thingsToLearn.map((i) => i.content).toList(),
  //   }),
  // );
  //
  // if (response != null && response.statusCode == 200) {
  //   final data = jsonDecode(response.body);
  //   // Update resources with URLs
  // }

  try {
    // For now, we'll use placeholder URLs for demonstration
    for (int i = 0; i < conversation.structured.thingsToImprove.length; i++) {
      final item = conversation.structured.thingsToImprove[i];
      // In production, these would come from the OpenAI web search API via your backend
      conversation.structured.thingsToImprove[i] = ResourceItem(
        item.content,
        url:
            'https://example.com/improve/${Uri.encodeComponent(item.content.toLowerCase().replaceAll(' ', '-'))}',
        title: 'Resource for ${item.content}',
      );
    }

    for (int i = 0; i < conversation.structured.thingsToLearn.length; i++) {
      final item = conversation.structured.thingsToLearn[i];
      // In production, these would come from the OpenAI web search API via your backend
      conversation.structured.thingsToLearn[i] = ResourceItem(
        item.content,
        url:
            'https://example.com/learn/${Uri.encodeComponent(item.content.toLowerCase().replaceAll(' ', '-'))}',
        title: 'Learn about ${item.content}',
      );
    }
  } catch (e) {
    debugPrint('Error enhancing with web search URLs: $e');
  }
}

// Helper method to locally enrich a conversation summary with multiple image descriptions
Future<void> enrichConversationSummaryWithMultipleImages(
    ServerConversation conversation, List<String> imageDescriptions) async {
  try {
    final SharedPreferencesUtil prefs = SharedPreferencesUtil();
    final userName = prefs.givenName.isEmpty ? 'User' : prefs.givenName;
    final userLanguage = prefs.userPrimaryLanguage.isEmpty
        ? 'English'
        : prefs.userPrimaryLanguage;

    final transcript = conversation.getTranscript(generate: true);

    // Format the image descriptions for the prompt
    final imagesText = imageDescriptions
        .asMap()
        .entries
        .map((entry) => "Image ${entry.key + 1}:\n${entry.value.trim()}")
        .join("\n\n");

    final prompt = '''
    Based on this conversation transcript and the following image descriptions, provide an updated:
    1. Overview (a concise summary integrating all image content)
    2. Key Takeaways (3-5 bullet points, including insights from the images)
    3. Things to Improve (2-3 specific, actionable recommendations for ${userName}, incorporating image insights)
    4. Things to Learn (1-2 specific learning opportunities for ${userName}, related to the image content)
    
    Format your response as JSON with these keys: overview, keyTakeaways, thingsToImprove, thingsToLearn.
    Each of keyTakeaways should be a string.
    Each of thingsToImprove and thingsToLearn should be an object with these properties:
      - content: The actual recommendation or learning opportunity (required)
      - url: "" (empty string for now)
      - title: "" (empty string for now)
    
    User Information for Personalization:
    - Name: ${userName}
    - Primary language: ${userLanguage}
    
    For "Things to Improve":
    - Start each item with a clear action verb (e.g., "Practice...", "Implement...", "Develop...")
    - Include specific, measurable steps that ${userName} can take immediately
    - Add a brief explanation of the benefit or why this improvement matters
    - Consider both short-term quick wins and longer-term growth opportunities
    - Be direct and concise, focusing on practical implementation
    
    For "Things to Learn":
    - Suggest specific topics or skills rather than broad areas
    - Include a clear, actionable way to begin learning this topic
    - Explain briefly how this learning connects to ${userName}'s interests or needs
    - Focus on knowledge or skills that would have immediate practical value
    
    Make all sections highly personalized, actionable, and relevant based on both the conversation and all image content.
    
    Transcript:
    ${transcript.trim()}
    
    Image Descriptions:
    ${imagesText}
    ''';

    // Call the GPT-4o API
    final response = await executeGptPrompt(prompt);

    try {
      final Map<String, dynamic> enrichmentData = jsonDecode(response);

      // Update the structured data with enriched content
      if (enrichmentData.containsKey('overview')) {
        // If this is a subsequent image analysis, append new insights
        if (conversation.structured.overview.isNotEmpty &&
            !conversation.structured.overview
                .contains(enrichmentData['overview'])) {
          conversation.structured.overview +=
              "\n\nAdditional insights from images: " +
                  enrichmentData['overview'];
        } else {
          conversation.structured.overview = enrichmentData['overview'];
        }
      }

      // Helper function to merge lists without duplicates - updated for ResourceItems
      void mergeLists(List<ResourceItem> existingList, List<dynamic> newItems) {
        for (var item in newItems) {
          String itemContent = item.toString();

          if (!existingList.any((existing) =>
              existing.content
                  .toLowerCase()
                  .contains(itemContent.toLowerCase()) ||
              itemContent
                  .toLowerCase()
                  .contains(existing.content.toLowerCase()))) {
            existingList.add(ResourceItem(itemContent));
          }
        }
      }

      if (enrichmentData.containsKey('keyTakeaways')) {
        conversation.structured.keyTakeaways = [
          ...conversation.structured.keyTakeaways,
          ...(enrichmentData['keyTakeaways'] as List)
              .map((item) => item.toString())
              .where((newItem) => !conversation.structured.keyTakeaways.any(
                  (existing) =>
                      existing.toLowerCase().contains(newItem.toLowerCase()) ||
                      newItem.toLowerCase().contains(existing.toLowerCase())))
              .toList()
        ];
      }

      if (enrichmentData.containsKey('thingsToImprove')) {
        mergeLists(conversation.structured.thingsToImprove,
            enrichmentData['thingsToImprove'] as List);
      }

      if (enrichmentData.containsKey('thingsToLearn')) {
        mergeLists(conversation.structured.thingsToLearn,
            enrichmentData['thingsToLearn'] as List);
      }

      // Enhance with web search URLs
      await _enhanceWithWebSearchURLs(conversation);
    } catch (e) {
      debugPrint('Error parsing image enrichment data: $e');
    }
  } catch (e) {
    debugPrint('Error generating image-enriched summary: $e');
  }
}

// New function to upload images directly to backend
Future<ServerConversation?> uploadAndProcessConversationImages(
    String conversationId, List<Uint8List> imagesData) async {
  try {
    debugPrint(
        'DEBUG CLIENT: Starting upload for conversation $conversationId');
    debugPrint('DEBUG CLIENT: Number of images: ${imagesData.length}');

    var request = http.MultipartRequest(
      'POST',
      Uri.parse(
          '${Env.apiBaseUrl}v1/conversations/$conversationId/upload-images'),
    );

    // Add authorization header
    request.headers.addAll({'Authorization': await getAuthHeader()});
    debugPrint('DEBUG CLIENT: Authorization header added');

    // Add image files to the request
    for (int i = 0; i < imagesData.length; i++) {
      debugPrint(
          'DEBUG CLIENT: Processing image $i, size: ${imagesData[i].length} bytes');

      // Check if image data starts with valid image headers
      String dataType = 'unknown';
      if (imagesData[i].length > 4) {
        if (imagesData[i][0] == 0xFF && imagesData[i][1] == 0xD8) {
          dataType = 'JPEG';
        } else if (imagesData[i][0] == 0x89 &&
            imagesData[i][1] == 0x50 &&
            imagesData[i][2] == 0x4E &&
            imagesData[i][3] == 0x47) {
          dataType = 'PNG';
        }
      }
      debugPrint('DEBUG CLIENT: Image $i detected type: $dataType');

      var multipartFile = http.MultipartFile.fromBytes(
        'files',
        imagesData[i],
        filename: 'image_$i.jpg',
        contentType: MediaType.parse('image/jpeg'),
      );

      debugPrint('DEBUG CLIENT: MultipartFile created for image $i');
      debugPrint('DEBUG CLIENT: - filename: ${multipartFile.filename}');
      debugPrint('DEBUG CLIENT: - contentType: ${multipartFile.contentType}');
      debugPrint('DEBUG CLIENT: - field: ${multipartFile.field}');
      debugPrint('DEBUG CLIENT: - length: ${multipartFile.length}');

      request.files.add(multipartFile);
    }

    debugPrint('DEBUG CLIENT: All files added to request');
    debugPrint('DEBUG CLIENT: Request headers: ${request.headers}');
    debugPrint('DEBUG CLIENT: Request fields: ${request.fields}');
    debugPrint('DEBUG CLIENT: Request files count: ${request.files.length}');

    // Send the request
    debugPrint('DEBUG CLIENT: Sending request...');
    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    debugPrint('DEBUG CLIENT: Response received');
    debugPrint('DEBUG CLIENT: Status code: ${response.statusCode}');
    debugPrint('DEBUG CLIENT: Response headers: ${response.headers}');
    debugPrint('DEBUG CLIENT: Response body: ${response.body}');

    if (response.statusCode == 200) {
      try {
        final responseData = jsonDecode(response.body);
        debugPrint('DEBUG CLIENT: Parsed response data successfully');

        // Check if structured data exists and has image URLs
        if (responseData['structured'] != null) {
          final structured = responseData['structured'];
          debugPrint('DEBUG CLIENT: Structured data found');

          // Check both possible field names
          final imageUrls =
              structured['imageUrls'] ?? structured['image_urls'] ?? [];
          debugPrint('DEBUG CLIENT: Image URLs in response: $imageUrls');
          debugPrint('DEBUG CLIENT: Number of image URLs: ${imageUrls.length}');

          // Check other structured fields
          debugPrint(
              'DEBUG CLIENT: Overview length: ${(structured['overview'] ?? '').length}');
          debugPrint(
              'DEBUG CLIENT: Key takeaways count: ${(structured['keyTakeaways'] ?? structured['key_takeaways'] ?? []).length}');
        } else {
          debugPrint('DEBUG CLIENT: No structured data in response');
        }

        final conversation = ServerConversation.fromJson(responseData);
        debugPrint('DEBUG CLIENT: ServerConversation created successfully');
        debugPrint(
            'DEBUG CLIENT: Conversation image URLs after parsing: ${conversation.structured.imageUrls}');
        debugPrint(
            'DEBUG CLIENT: Number of images in conversation object: ${conversation.structured.imageUrls.length}');

        return conversation;
      } catch (e) {
        debugPrint('ERROR CLIENT: Failed to parse response: $e');
        debugPrint('ERROR CLIENT: Response body was: ${response.body}');
        return null;
      }
    } else {
      debugPrint(
          'ERROR CLIENT: Upload failed with ${response.statusCode}: ${response.body}');
      return null;
    }
  } catch (e) {
    debugPrint('ERROR CLIENT: Exception during upload: $e');
    debugPrint('ERROR CLIENT: Stack trace: ${StackTrace.current}');
    return null;
  }
}

// Alternative function to upload images with different content type handling
Future<ServerConversation?> uploadAndProcessConversationImagesAlternative(
    String conversationId, List<Uint8List> imagesData) async {
  try {
    debugPrint(
        'DEBUG CLIENT ALT: Starting alternative upload for conversation $conversationId');
    debugPrint('DEBUG CLIENT ALT: Number of images: ${imagesData.length}');

    var request = http.MultipartRequest(
      'POST',
      Uri.parse(
          '${Env.apiBaseUrl}v1/conversations/$conversationId/upload-images'),
    );

    // Add authorization header
    request.headers.addAll({'Authorization': await getAuthHeader()});

    // Explicitly set content type for the entire request
    request.headers['Content-Type'] = 'multipart/form-data';
    debugPrint('DEBUG CLIENT ALT: Headers set: ${request.headers}');

    // Add image files to the request with explicit content type handling
    for (int i = 0; i < imagesData.length; i++) {
      debugPrint(
          'DEBUG CLIENT ALT: Processing image $i, size: ${imagesData[i].length} bytes');

      // Detect image type from magic bytes
      String detectedType = 'jpeg'; // default
      String mimeType = 'image/jpeg'; // default

      if (imagesData[i].length > 8) {
        // Check for JPEG
        if (imagesData[i][0] == 0xFF && imagesData[i][1] == 0xD8) {
          detectedType = 'jpeg';
          mimeType = 'image/jpeg';
        }
        // Check for PNG
        else if (imagesData[i][0] == 0x89 &&
            imagesData[i][1] == 0x50 &&
            imagesData[i][2] == 0x4E &&
            imagesData[i][3] == 0x47) {
          detectedType = 'png';
          mimeType = 'image/png';
        }
      }

      debugPrint(
          'DEBUG CLIENT ALT: Image $i detected as $detectedType, using MIME type: $mimeType');

      // Try using http.MultipartFile.fromBytes with explicit MediaType construction
      var mediaType =
          MediaType('image', detectedType == 'png' ? 'png' : 'jpeg');

      var multipartFile = http.MultipartFile.fromBytes(
        'files',
        imagesData[i],
        filename: 'image_$i.$detectedType',
        contentType: mediaType,
      );

      debugPrint('DEBUG CLIENT ALT: MultipartFile created for image $i');
      debugPrint('DEBUG CLIENT ALT: - filename: ${multipartFile.filename}');
      debugPrint(
          'DEBUG CLIENT ALT: - contentType: ${multipartFile.contentType}');
      debugPrint(
          'DEBUG CLIENT ALT: - contentType toString: ${multipartFile.contentType.toString()}');
      debugPrint('DEBUG CLIENT ALT: - field: ${multipartFile.field}');
      debugPrint('DEBUG CLIENT ALT: - length: ${multipartFile.length}');

      request.files.add(multipartFile);
    }

    debugPrint('DEBUG CLIENT ALT: All files added, sending request...');

    // Send the request
    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    debugPrint('DEBUG CLIENT ALT: Response received');
    debugPrint('DEBUG CLIENT ALT: Status code: ${response.statusCode}');
    debugPrint('DEBUG CLIENT ALT: Response body: ${response.body}');

    if (response.statusCode == 200) {
      return ServerConversation.fromJson(jsonDecode(response.body));
    } else {
      debugPrint(
          'ERROR CLIENT ALT: Upload failed with ${response.statusCode}: ${response.body}');
      return null;
    }
  } catch (e) {
    debugPrint('ERROR CLIENT ALT: Exception during upload: $e');
    debugPrint('ERROR CLIENT ALT: Stack trace: ${StackTrace.current}');
    return null;
  }
}

// Test function to help debug image upload issues
Future<Map<String, dynamic>> testImageUploadMethods(
    String conversationId, List<Uint8List> imagesData) async {
  debugPrint('=== STARTING IMAGE UPLOAD DEBUG TEST ===');

  Map<String, dynamic> results = {
    'primary_method': {'success': false, 'error': null, 'details': {}},
    'alternative_method': {'success': false, 'error': null, 'details': {}},
    'recommendations': []
  };

  // Test primary method
  debugPrint('\n--- Testing Primary Upload Method ---');
  try {
    var primaryResult =
        await uploadAndProcessConversationImages(conversationId, imagesData);
    if (primaryResult != null) {
      results['primary_method']['success'] = true;
      results['primary_method']
          ['details'] = {'result': 'Success - conversation returned'};
      debugPrint('✅ Primary method succeeded');
    } else {
      results['primary_method']['error'] = 'Method returned null';
      debugPrint('❌ Primary method failed - returned null');
    }
  } catch (e) {
    results['primary_method']['error'] = e.toString();
    debugPrint('❌ Primary method failed with exception: $e');
  }

  // Test alternative method
  debugPrint('\n--- Testing Alternative Upload Method ---');
  try {
    var altResult = await uploadAndProcessConversationImagesAlternative(
        conversationId, imagesData);
    if (altResult != null) {
      results['alternative_method']['success'] = true;
      results['alternative_method']
          ['details'] = {'result': 'Success - conversation returned'};
      debugPrint('✅ Alternative method succeeded');
    } else {
      results['alternative_method']['error'] = 'Method returned null';
      debugPrint('❌ Alternative method failed - returned null');
    }
  } catch (e) {
    results['alternative_method']['error'] = e.toString();
    debugPrint('❌ Alternative method failed with exception: $e');
  }

  // Generate recommendations
  List<String> recommendations = [];

  if (results['primary_method']['success'] &&
      results['alternative_method']['success']) {
    recommendations.add(
        'Both methods work! Use the primary method as it\'s the main implementation.');
  } else if (results['primary_method']['success']) {
    recommendations.add(
        'Primary method works! The server-side magic byte detection fix resolved the issue.');
  } else if (results['alternative_method']['success']) {
    recommendations.add(
        'Alternative method works! Consider using this as the main method or investigate why primary method fails.');
  } else {
    recommendations.add(
        'Both methods failed. Check server logs and network connectivity.');
    recommendations
        .add('Verify the conversation ID exists and the user has permissions.');
    recommendations.add('Check if the image data is valid and not corrupted.');
  }

  // Add technical recommendations based on errors
  String primaryError = results['primary_method']['error']?.toString() ?? '';
  String altError = results['alternative_method']['error']?.toString() ?? '';

  if (primaryError.contains('400') || altError.contains('400')) {
    recommendations
        .add('HTTP 400 error detected - check file validation on server side.');
  }

  if (primaryError.contains('401') || altError.contains('401')) {
    recommendations
        .add('HTTP 401 error detected - check authentication token.');
  }

  if (primaryError.contains('404') || altError.contains('404')) {
    recommendations.add(
        'HTTP 404 error detected - verify conversation ID and endpoint URL.');
  }

  results['recommendations'] = recommendations;

  debugPrint('\n=== TEST RESULTS SUMMARY ===');
  debugPrint('Primary method success: ${results['primary_method']['success']}');
  debugPrint(
      'Alternative method success: ${results['alternative_method']['success']}');
  debugPrint('Recommendations:');
  for (var rec in recommendations) {
    debugPrint('  • $rec');
  }
  debugPrint('=== END DEBUG TEST ===\n');

  return results;
}

// Function to create a new conversation from images
Future<ServerConversation?> createConversationFromImages(
    List<Uint8List> imagesData) async {
  debugPrint('DEBUG CLIENT: Starting createConversationFromImages');
  debugPrint('DEBUG CLIENT: Number of images: ${imagesData.length}');

  var request = http.MultipartRequest(
    'POST',
    Uri.parse('${Env.apiBaseUrl}v1/conversations/create-from-images'),
  );

  // Add authorization header
  request.headers.addAll({'Authorization': await getAuthHeader()});
  debugPrint('DEBUG CLIENT: Authorization header added');

  // Add image files to the request
  for (int i = 0; i < imagesData.length; i++) {
    debugPrint(
        'DEBUG CLIENT: Processing image $i, size: ${imagesData[i].length} bytes');

    // Detect image type from magic bytes
    String detectedType = 'jpeg'; // default
    String mimeType = 'image/jpeg'; // default

    if (imagesData[i].length > 8) {
      // Check for JPEG
      if (imagesData[i][0] == 0xFF && imagesData[i][1] == 0xD8) {
        detectedType = 'jpeg';
        mimeType = 'image/jpeg';
      }
      // Check for PNG
      else if (imagesData[i][0] == 0x89 &&
          imagesData[i][1] == 0x50 &&
          imagesData[i][2] == 0x4E &&
          imagesData[i][3] == 0x47) {
        detectedType = 'png';
        mimeType = 'image/png';
      }
    }

    debugPrint(
        'DEBUG CLIENT: Image $i detected as $detectedType, using MIME type: $mimeType');

    var mediaType = MediaType('image', detectedType == 'png' ? 'png' : 'jpeg');

    var multipartFile = http.MultipartFile.fromBytes(
      'files',
      imagesData[i],
      filename: 'image_$i.$detectedType',
      contentType: mediaType,
    );

    debugPrint('DEBUG CLIENT: MultipartFile created for image $i');
    request.files.add(multipartFile);
  }

  debugPrint('DEBUG CLIENT: All files added, sending request...');

  try {
    // Send the request
    var streamedResponse = await request.send();
    var response = await http.Response.fromStream(streamedResponse);

    debugPrint('DEBUG CLIENT: Response received');
    debugPrint('DEBUG CLIENT: Status code: ${response.statusCode}');
    debugPrint('DEBUG CLIENT: Response body: ${response.body}');

    if (response.statusCode == 200) {
      try {
        var conversation =
            ServerConversation.fromJson(jsonDecode(response.body));
        debugPrint(
            'DEBUG CLIENT: Successfully created new conversation from images');
        debugPrint('DEBUG CLIENT: New conversation ID: ${conversation.id}');
        debugPrint(
            'DEBUG CLIENT: Number of images in new conversation: ${conversation.structured.imageUrls.length}');
        return conversation;
      } catch (e) {
        debugPrint('ERROR CLIENT: Failed to parse response: $e');
        debugPrint('ERROR CLIENT: Response body was: ${response.body}');
        return null;
      }
    } else {
      debugPrint(
          'ERROR CLIENT: Create conversation failed with ${response.statusCode}: ${response.body}');
      return null;
    }
  } catch (e) {
    debugPrint('ERROR CLIENT: Exception during conversation creation: $e');
    return null;
  }
}
