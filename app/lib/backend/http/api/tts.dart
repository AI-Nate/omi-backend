import 'dart:convert';
import 'dart:typed_data';
import 'package:omi/backend/http/shared.dart';
import 'package:omi/env/env.dart';

/// Convert text to speech using Azure TTS service
Future<Uint8List?> convertTextToSpeech(
  String text, {
  String voice = 'alloy',
  double speed = 1.0,
}) async {
  try {
    final response = await makeApiCall(
      url: '${Env.apiBaseUrl}v1/tts/speak',
      headers: {
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'text': text,
        'voice': voice,
        'speed': speed,
      }),
      method: 'POST',
    );

    if (response != null && response.statusCode == 200) {
      return response.bodyBytes;
    } else {
      print(
          '🔴 TTS API: Error ${response?.statusCode}: ${response?.reasonPhrase}');
      return null;
    }
  } catch (e) {
    print('🔴 TTS API: Exception during text-to-speech conversion: $e');
    return null;
  }
}

/// Convert conversation summary to speech using Azure TTS service
/// This function handles caching - if audio is cached, it will download from Firebase Storage
Future<Uint8List?> convertConversationToSpeech(
  String conversationId, {
  String voice = 'alloy',
  double speed = 1.0,
}) async {
  try {
    final response = await makeApiCall(
      url: '${Env.apiBaseUrl}v1/tts/conversation/$conversationId',
      headers: {
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'voice': voice,
        'speed': speed,
      }),
      method: 'POST',
    );

    if (response != null) {
      if (response.statusCode == 200) {
        // Direct audio response from TTS generation
        return response.bodyBytes;
      } else if (response.statusCode == 302) {
        // Redirect to cached audio file
        final redirectUrl = response.headers['location'];
        if (redirectUrl != null) {
          print('🔊 TTS API: Redirected to cached audio: $redirectUrl');

          // Download the cached audio file
          final cachedResponse = await makeApiCall(
            url: redirectUrl,
            headers: {},
            method: 'GET',
            body: '',
          );

          if (cachedResponse != null && cachedResponse.statusCode == 200) {
            print(
                '🔊 TTS API: Successfully downloaded cached audio: ${cachedResponse.bodyBytes.length} bytes');
            return cachedResponse.bodyBytes;
          } else {
            print(
                '🔴 TTS API: Failed to download cached audio: ${cachedResponse?.statusCode}');
            return null;
          }
        } else {
          print('🔴 TTS API: Redirect response missing location header');
          return null;
        }
      } else {
        print(
            '🔴 TTS API: Error ${response.statusCode}: ${response.reasonPhrase}');
        return null;
      }
    } else {
      print('🔴 TTS API: No response received');
      return null;
    }
  } catch (e) {
    print('🔴 TTS API: Exception during conversation-to-speech conversion: $e');
    return null;
  }
}

/// Get available TTS voices from the backend
Future<Map<String, dynamic>?> getAvailableVoices() async {
  try {
    final response = await makeApiCall(
      url: '${Env.apiBaseUrl}v1/tts/voices',
      headers: {},
      method: 'GET',
      body: '',
    );

    if (response != null && response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      print(
          '🔴 TTS API: Error getting voices ${response?.statusCode}: ${response?.reasonPhrase}');
      return null;
    }
  } catch (e) {
    print('🔴 TTS API: Exception getting available voices: $e');
    return null;
  }
}
