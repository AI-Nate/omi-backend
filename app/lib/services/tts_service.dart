import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';
import 'package:omi/backend/http/api/tts.dart';
import 'package:omi/backend/schema/conversation.dart';

class TTSService {
  static final TTSService _instance = TTSService._internal();
  factory TTSService() => _instance;
  TTSService._internal();

  final AudioPlayer _audioPlayer = AudioPlayer();
  bool _isPlaying = false;
  bool _isLoading = false;

  bool get isPlaying => _isPlaying;
  bool get isLoading => _isLoading;

  // Stream to notify UI about TTS state changes
  final ValueNotifier<TTSState> _stateNotifier = ValueNotifier(TTSState.idle);
  ValueNotifier<TTSState> get stateNotifier => _stateNotifier;

  Future<bool> speakConversationSummary(
    ServerConversation conversation, {
    String voice = 'alloy',
    double speed = 1.0,
    VoidCallback? onStart,
    VoidCallback? onComplete,
    Function(String)? onError,
  }) async {
    try {
      if (_isPlaying) {
        await stop();
      }

      _isLoading = true;
      _stateNotifier.value = TTSState.loading;
      onStart?.call();

      print('🔊 TTS: Starting speech for conversation ${conversation.id}');

      // Call backend TTS API
      final audioData = await convertConversationToSpeech(
        conversation.id,
        voice: voice,
        speed: speed,
      );

      if (audioData == null) {
        print('🔴 TTS: No audio data received');
        _isLoading = false;
        _stateNotifier.value = TTSState.error;
        onError?.call('No audio data received from server');
        return false;
      }

      print('🔊 TTS: Received audio data: ${audioData.length} bytes');

      // Play the audio
      await _playAudioFromBytes(audioData);

      _isLoading = false;
      _isPlaying = true;
      _stateNotifier.value = TTSState.playing;

      // Set up completion callback
      _audioPlayer.playerStateStream.listen((PlayerState state) {
        if (state.processingState == ProcessingState.completed) {
          _isPlaying = false;
          _stateNotifier.value = TTSState.idle;
          onComplete?.call();
        }
      });

      return true;
    } catch (e) {
      print('🔴 TTS: Error speaking conversation summary: $e');
      _isLoading = false;
      _isPlaying = false;
      _stateNotifier.value = TTSState.error;
      onError?.call(e.toString());
      return false;
    }
  }

  Future<bool> speakText(
    String text, {
    String voice = 'alloy',
    double speed = 1.0,
    VoidCallback? onStart,
    VoidCallback? onComplete,
    Function(String)? onError,
  }) async {
    try {
      if (_isPlaying) {
        await stop();
      }

      _isLoading = true;
      _stateNotifier.value = TTSState.loading;
      onStart?.call();

      print('🔊 TTS: Starting speech for text (${text.length} chars)');

      // Call backend TTS API
      final audioData = await convertTextToSpeech(
        text,
        voice: voice,
        speed: speed,
      );

      if (audioData == null) {
        print('🔴 TTS: No audio data received');
        _isLoading = false;
        _stateNotifier.value = TTSState.error;
        onError?.call('No audio data received from server');
        return false;
      }

      print('🔊 TTS: Received audio data: ${audioData.length} bytes');

      // Play the audio
      await _playAudioFromBytes(audioData);

      _isLoading = false;
      _isPlaying = true;
      _stateNotifier.value = TTSState.playing;

      // Set up completion callback
      _audioPlayer.playerStateStream.listen((PlayerState state) {
        if (state.processingState == ProcessingState.completed) {
          _isPlaying = false;
          _stateNotifier.value = TTSState.idle;
          onComplete?.call();
        }
      });

      return true;
    } catch (e) {
      print('🔴 TTS: Error speaking text: $e');
      _isLoading = false;
      _isPlaying = false;
      _stateNotifier.value = TTSState.error;
      onError?.call(e.toString());
      return false;
    }
  }

  Future<void> _playAudioFromBytes(Uint8List audioData) async {
    try {
      // Stop any existing playback
      await _audioPlayer.stop();

      // Create an audio source from bytes and play
      final audioSource = BytesAudioSource(audioData);
      await _audioPlayer.setAudioSource(audioSource);
      await _audioPlayer.play();

      print('🔊 TTS: Audio playback started');
    } catch (e) {
      print('🔴 TTS: Error playing audio: $e');
      rethrow;
    }
  }

  Future<void> stop() async {
    try {
      await _audioPlayer.stop();
      _isPlaying = false;
      _isLoading = false;
      _stateNotifier.value = TTSState.idle;
      print('🔊 TTS: Audio playback stopped');
    } catch (e) {
      print('🔴 TTS: Error stopping audio: $e');
    }
  }

  Future<void> pause() async {
    try {
      await _audioPlayer.pause();
      _isPlaying = false;
      _stateNotifier.value = TTSState.paused;
      print('🔊 TTS: Audio playback paused');
    } catch (e) {
      print('🔴 TTS: Error pausing audio: $e');
    }
  }

  Future<void> resume() async {
    try {
      await _audioPlayer.play();
      _isPlaying = true;
      _stateNotifier.value = TTSState.playing;
      print('🔊 TTS: Audio playback resumed');
    } catch (e) {
      print('🔴 TTS: Error resuming audio: $e');
    }
  }

  void dispose() {
    _audioPlayer.dispose();
    _stateNotifier.dispose();
  }
}

// Custom audio source for bytes
class BytesAudioSource extends StreamAudioSource {
  final Uint8List bytes;

  BytesAudioSource(this.bytes);

  @override
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    start = start ?? 0;
    end = end ?? bytes.length;
    return StreamAudioResponse(
      sourceLength: bytes.length,
      contentLength: end - start,
      offset: start,
      stream: Stream.value(bytes.sublist(start, end)),
      contentType: 'audio/mpeg',
    );
  }
}

enum TTSState {
  idle,
  loading,
  playing,
  paused,
  error,
}

// Extension to get user-friendly state descriptions
extension TTSStateExtension on TTSState {
  String get description {
    switch (this) {
      case TTSState.idle:
        return 'Ready';
      case TTSState.loading:
        return 'Loading...';
      case TTSState.playing:
        return 'Playing';
      case TTSState.paused:
        return 'Paused';
      case TTSState.error:
        return 'Error';
    }
  }

  IconData get icon {
    switch (this) {
      case TTSState.idle:
        return Icons.volume_up;
      case TTSState.loading:
        return Icons.hourglass_empty;
      case TTSState.playing:
        return Icons.stop;
      case TTSState.paused:
        return Icons.play_arrow;
      case TTSState.error:
        return Icons.error;
    }
  }
}
