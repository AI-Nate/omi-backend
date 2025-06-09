import 'dart:typed_data';
import 'dart:async';
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
  StreamSubscription<PlayerState>? _playerStateSubscription;

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

      print('🔊 TTS_SERVICE: Setting state to loading...');
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
      print('🔊 TTS_SERVICE: About to play audio from bytes...');

      // Play the audio
      try {
        await _playAudioFromBytes(audioData);
        print('🔊 TTS_SERVICE: Audio playback started successfully');
      } catch (e) {
        print('🔴 TTS_SERVICE: Error in _playAudioFromBytes: $e');
        _isLoading = false;
        _stateNotifier.value = TTSState.error;
        onError?.call('Error playing audio: $e');
        return false;
      }

      print('🔊 TTS_SERVICE: Setting state to playing...');
      _isLoading = false;
      _isPlaying = true;
      _stateNotifier.value = TTSState.playing;
      print(
          '🔊 TTS_SERVICE: State updated to playing: ${_stateNotifier.value}');

      // Set up completion callback
      _playerStateSubscription =
          _audioPlayer.playerStateStream.listen((PlayerState state) {
        print('🔊 TTS_SERVICE: Player state changed: ${state.processingState}');
        if (state.processingState == ProcessingState.completed) {
          print('🔊 TTS_SERVICE: Audio completed, setting state to idle');
          _isPlaying = false;
          _stateNotifier.value = TTSState.idle;
          onComplete?.call();
        }
      });

      return true;
    } catch (e) {
      print('🔴 TTS: Error speaking conversation summary: $e');
      print('🔴 TTS_SERVICE: Stack trace: ${StackTrace.current}');
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
      _playerStateSubscription =
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
      print(
          '🔊 TTS_SERVICE: _playAudioFromBytes called with ${audioData.length} bytes');

      // Stop any existing playback
      print('🔊 TTS_SERVICE: Stopping existing playback...');
      await _audioPlayer.stop();

      // Create an audio source from bytes and play
      print('🔊 TTS_SERVICE: Creating BytesAudioSource...');
      final audioSource = BytesAudioSource(audioData);

      print('🔊 TTS_SERVICE: Setting audio source...');
      await _audioPlayer.setAudioSource(audioSource);

      print('🔊 TTS_SERVICE: Starting playback...');
      await _audioPlayer.play();

      print('🔊 TTS: Audio playback started');
    } catch (e) {
      print('🔴 TTS: Error playing audio: $e');
      print(
          '🔴 TTS_SERVICE: _playAudioFromBytes stack trace: ${StackTrace.current}');
      rethrow;
    }
  }

  Future<void> stop() async {
    try {
      print('🔊 TTS_SERVICE: Stop called, cancelling subscription...');
      await _playerStateSubscription?.cancel();
      _playerStateSubscription = null;

      print('🔊 TTS_SERVICE: Stopping audio player...');
      await _audioPlayer.stop();

      _isPlaying = false;
      _isLoading = false;
      _stateNotifier.value = TTSState.idle;
      print('🔊 TTS: Audio playback stopped, state set to idle');
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
    _playerStateSubscription?.cancel();
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
