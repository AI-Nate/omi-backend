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

    if (response != null && response.statusCode == 200) {
      return response.bodyBytes;
    } else {
      print(
          '🔴 TTS API: Error ${response?.statusCode}: ${response?.reasonPhrase}');
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
