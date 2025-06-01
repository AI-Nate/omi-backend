import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:omi/backend/http/shared.dart';
import 'package:omi/backend/schema/memory.dart';
import 'package:omi/env/env.dart';

Future<bool> createMemoryServer(String content, String visibility) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories',
    headers: {},
    method: 'POST',
    body: json.encode({
      'content': content,
      'visibility': visibility,
    }),
  );
  if (response == null) return false;
  debugPrint('createMemory response: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> updateMemoryVisibilityServer(
    String memoryId, String visibility) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories/$memoryId/visibility?value=$visibility',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('updateMemoryVisibility response: ${response.body}');
  return response.statusCode == 200;
}

Future<List<Memory>> getMemories({int limit = 100, int offset = 0}) async {
  final timestamp = DateTime.now().toIso8601String();
  print(
      'DEBUG API [$timestamp]: Calling getMemories with limit=$limit, offset=$offset');

  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories?limit=$limit&offset=$offset',
    headers: {},
    method: 'GET',
    body: '',
  );

  if (response == null) {
    print('DEBUG API [$timestamp]: getMemories response is null');
    return [];
  }

  print(
      'DEBUG API [$timestamp]: getMemories response status: ${response.statusCode}');
  print(
      'DEBUG API [$timestamp]: getMemories response body length: ${response.body.length}');

  if (response.statusCode != 200) {
    print(
        'DEBUG API [$timestamp]: getMemories failed with status ${response.statusCode}: ${response.body}');
    return [];
  }

  try {
    List<dynamic> memories = json.decode(response.body);
    print(
        'DEBUG API [$timestamp]: Parsed ${memories.length} memories from response');

    // Debug: Print sample of raw memory data
    if (memories.isNotEmpty) {
      print('DEBUG API [$timestamp]: Sample raw memory: ${memories[0]}');
    }

    final memoryObjects =
        memories.map((memory) => Memory.fromJson(memory)).toList();
    print(
        'DEBUG API [$timestamp]: Converted to ${memoryObjects.length} Memory objects');

    return memoryObjects;
  } catch (e) {
    print('DEBUG API [$timestamp]: Error parsing memories JSON: $e');
    return [];
  }
}

Future<bool> deleteMemoryServer(String memoryId) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories/$memoryId',
    headers: {},
    method: 'DELETE',
    body: '',
  );
  if (response == null) return false;
  debugPrint('deleteMemory response: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> deleteAllMemoriesServer() async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories',
    headers: {},
    method: 'DELETE',
    body: '',
  );
  if (response == null) return false;
  debugPrint('deleteAllMemories response: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> reviewMemoryServer(String memoryId, bool value) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories/$memoryId/review?value=$value',
    headers: {},
    method: 'POST',
    body: '',
  );
  if (response == null) return false;
  debugPrint('reviewMemory response: ${response.body}');
  return response.statusCode == 200;
}

Future<bool> editMemoryServer(String memoryId, String value) async {
  var response = await makeApiCall(
    url: '${Env.apiBaseUrl}v3/memories/$memoryId?value=$value',
    headers: {},
    method: 'PATCH',
    body: '',
  );
  if (response == null) return false;
  debugPrint('editMemory response: ${response.body}');
  return response.statusCode == 200;
}
