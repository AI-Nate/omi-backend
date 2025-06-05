import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_provider_utilities/flutter_provider_utilities.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:omi/backend/http/api/users.dart' as users_api;
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/bt_device/bt_device.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/backend/schema/message.dart';
import 'package:omi/backend/schema/message_event.dart';
import 'package:omi/backend/schema/structured.dart';
import 'package:omi/backend/schema/transcript_segment.dart';
import 'package:omi/providers/conversation_provider.dart';
import 'package:omi/providers/message_provider.dart';
import 'package:omi/providers/agent_conversation_provider.dart';
import 'package:omi/services/devices.dart';
import 'package:omi/services/notifications.dart';
import 'package:omi/services/services.dart';
import 'package:omi/services/sockets/pure_socket.dart';
import 'package:omi/services/sockets/sdcard_socket.dart';
import 'package:omi/services/sockets/transcription_connection.dart';
import 'package:omi/services/wals.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:omi/utils/enums.dart';
import 'package:internet_connection_checker_plus/internet_connection_checker_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:uuid/uuid.dart';

class CaptureProvider extends ChangeNotifier
    with MessageNotifierMixin
    implements ITransctipSegmentSocketServiceListener {
  ConversationProvider? conversationProvider;
  MessageProvider? messageProvider;
  AgentConversationProvider? agentConversationProvider;
  TranscriptSegmentSocketService? _socket;
  SdCardSocketService sdCardSocket = SdCardSocketService();
  Timer? _keepAliveTimer;

  // In progress memory
  ServerConversation? _inProgressConversation;

  ServerConversation? get inProgressConversation => _inProgressConversation;

  IWalService get _wal => ServiceManager.instance().wal;

  IDeviceService get _deviceService => ServiceManager.instance().device;
  bool _isWalSupported = false;

  bool get isWalSupported => _isWalSupported;

  StreamSubscription<InternetStatus>? _internetStatusListener;
  InternetStatus? _internetStatus;

  get internetStatus => _internetStatus;

  List<ServerMessageEvent> _transcriptionServiceStatuses = [];
  List<ServerMessageEvent> get transcriptionServiceStatuses =>
      _transcriptionServiceStatuses;

  CaptureProvider() {
    _internetStatusListener = PureCore()
        .internetConnection
        .onStatusChange
        .listen((InternetStatus status) {
      onInternetSatusChanged(status);
    });
  }

  void updateProviderInstances(ConversationProvider? cp, MessageProvider? p,
      {AgentConversationProvider? agentProvider}) {
    conversationProvider = cp;
    messageProvider = p;
    agentConversationProvider = agentProvider;
    notifyListeners();
  }

  BtDevice? _recordingDevice;
  List<TranscriptSegment> segments = [];

  bool hasTranscripts = false;

  StreamSubscription? _bleBytesStream;

  get bleBytesStream => _bleBytesStream;

  StreamSubscription? _bleButtonStream;
  DateTime? _voiceCommandSession;
  List<List<int>> _commandBytes = [];

  StreamSubscription? _storageStream;

  get storageStream => _storageStream;

  RecordingState recordingState = RecordingState.stop;

  bool _transcriptServiceReady = false;

  bool get transcriptServiceReady =>
      _transcriptServiceReady && _internetStatus == InternetStatus.connected;

  // having a connected device or using the phone's mic for recording
  bool get recordingDeviceServiceReady =>
      _recordingDevice != null || recordingState == RecordingState.record;

  bool get havingRecordingDevice => _recordingDevice != null;

  // -----------------------
  // Conversation creation variables
  String conversationId = const Uuid().v4();

  void setHasTranscripts(bool value) {
    hasTranscripts = value;
    notifyListeners();
  }

  void setConversationCreating(bool value) {
    debugPrint('set Conversation creating $value');
    // ConversationCreating = value;
    notifyListeners();
  }

  void _updateRecordingDevice(BtDevice? device) {
    debugPrint(
        'connected device changed from ${_recordingDevice?.id} to ${device?.id}');
    _recordingDevice = device;
    notifyListeners();
  }

  void updateRecordingDevice(BtDevice? device) {
    _updateRecordingDevice(device);
  }

  Future _resetStateVariables() async {
    debugPrint('🔄 CAPTURE_PROVIDER: _resetStateVariables() called');
    debugPrint('🔄 CAPTURE_PROVIDER: Clearing ${segments.length} segments');
    segments = [];
    conversationId = const Uuid().v4();
    hasTranscripts = false;
    _hasManuallyProcessed =
        false; // Reset manual processing flag for new recording session
    debugPrint(
        '🔄 CAPTURE_PROVIDER: State variables reset completed - new conversationId: $conversationId');
    notifyListeners();
  }

  Future<void> onRecordProfileSettingChanged() async {
    await _resetState();
  }

  Future<void> changeAudioRecordProfile({
    required BleAudioCodec audioCodec,
    int? sampleRate,
  }) async {
    debugPrint("changeAudioRecordProfile");
    await _resetState();
    await _initiateWebsocket(audioCodec: audioCodec, sampleRate: sampleRate);
  }

  Future<void> _initiateWebsocket({
    required BleAudioCodec audioCodec,
    int? sampleRate,
    bool force = false,
  }) async {
    debugPrint('initiateWebsocket in capture_provider');

    BleAudioCodec codec = audioCodec;
    sampleRate ??= (codec.isOpusSupported() ? 16000 : 8000);

    debugPrint('is ws null: ${_socket == null}');

    // Connect to the transcript socket
    String language = SharedPreferencesUtil().hasSetPrimaryLanguage
        ? SharedPreferencesUtil().userPrimaryLanguage
        : "multi";
    _socket = await ServiceManager.instance().socket.conversation(
        codec: codec, sampleRate: sampleRate, language: language, force: force);
    if (_socket == null) {
      _startKeepAliveServices();
      debugPrint("Can not create new conversation socket");
      return;
    }
    _socket?.subscribe(this, this);
    _transcriptServiceReady = true;

    _loadInProgressConversation();

    notifyListeners();
  }

  void _processVoiceCommandBytes(String deviceId, List<List<int>> data) async {
    if (data.isEmpty) {
      debugPrint("voice frames is empty");
      return;
    }

    BleAudioCodec codec = await _getAudioCodec(_recordingDevice!.id);
    if (messageProvider != null) {
      await messageProvider?.sendVoiceMessageStreamToServer(
        data,
        onFirstChunkRecived: () {
          _playSpeakerHaptic(deviceId, 2);
        },
        codec: codec,
      );
    }
  }

  // Just incase the ble connection get loss
  void _watchVoiceCommands(String deviceId, DateTime session) {
    Timer.periodic(const Duration(seconds: 3), (t) async {
      debugPrint("voice command watch");
      if (session != _voiceCommandSession) {
        t.cancel();
        return;
      }
      var value = await _getBleButtonState(deviceId);
      var buttonState = ByteData.view(
              Uint8List.fromList(value.sublist(0, 4).reversed.toList()).buffer)
          .getUint32(0);
      debugPrint("watch device button $buttonState");

      // Force process
      if (buttonState == 5 && session == _voiceCommandSession) {
        _voiceCommandSession = null; // end session
        var data = List<List<int>>.from(_commandBytes);
        _commandBytes = [];
        _processVoiceCommandBytes(deviceId, data);
      }
    });
  }

  Future streamButton(String deviceId) async {
    debugPrint('streamButton in capture_provider');
    _bleButtonStream?.cancel();
    _bleButtonStream = await _getBleButtonListener(deviceId,
        onButtonReceived: (List<int> value) {
      final snapshot = List<int>.from(value);
      if (snapshot.isEmpty || snapshot.length < 4) return;
      var buttonState = ByteData.view(
              Uint8List.fromList(snapshot.sublist(0, 4).reversed.toList())
                  .buffer)
          .getUint32(0);
      debugPrint("device button $buttonState");

      // start long press
      if (buttonState == 3 && _voiceCommandSession == null) {
        _voiceCommandSession = DateTime.now();
        _commandBytes = [];
        _watchVoiceCommands(deviceId, _voiceCommandSession!);
        _playSpeakerHaptic(deviceId, 1);
      }

      // release
      if (buttonState == 5 && _voiceCommandSession != null) {
        _voiceCommandSession = null; // end session
        var data = List<List<int>>.from(_commandBytes);
        _commandBytes = [];
        _processVoiceCommandBytes(deviceId, data);
      }
    });
  }

  Future streamAudioToWs(String deviceId, BleAudioCodec codec) async {
    debugPrint('streamAudioToWs in capture_provider');
    _bleBytesStream?.cancel();
    _bleBytesStream = await _getBleAudioBytesListener(deviceId,
        onAudioBytesReceived: (List<int> value) {
      final snapshot = List<int>.from(value);
      if (snapshot.isEmpty || snapshot.length < 3) return;

      // Command button triggered
      if (_voiceCommandSession != null) {
        _commandBytes.add(snapshot.sublist(3));
      }

      // Support: opus codec, 1m from the first device connects
      var deviceFirstConnectedAt = _deviceService.getFirstConnectedAt();
      var checkWalSupported = codec.isOpusSupported() &&
          (deviceFirstConnectedAt != null &&
              deviceFirstConnectedAt.isBefore(
                  DateTime.now().subtract(const Duration(seconds: 15)))) &&
          SharedPreferencesUtil().localSyncEnabled;
      if (checkWalSupported != _isWalSupported) {
        setIsWalSupported(checkWalSupported);
      }
      if (_isWalSupported) {
        _wal.getSyncs().phone.onByteStream(snapshot);
      }

      // send ws
      if (_socket?.state == SocketServiceState.connected) {
        final trimmedValue = value.sublist(3);
        _socket?.send(trimmedValue);

        // synced
        if (_isWalSupported) {
          _wal.getSyncs().phone.onBytesSync(value);
        }
      }
    });
    notifyListeners();
  }

  Future<void> _resetState() async {
    debugPrint('resetState');
    await _cleanupCurrentState();
    await _ensureDeviceSocketConnection();
    await _initiateDeviceAudioStreaming();
    await initiateStorageBytesStreaming();

    notifyListeners();
  }

  Future _cleanupCurrentState() async {
    await _closeBleStream();
    notifyListeners();
  }

  // TODO: use connection directly
  Future<BleAudioCodec> _getAudioCodec(String deviceId) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return BleAudioCodec.pcm8;
    }
    return connection.getAudioCodec();
  }

  Future<bool> _playSpeakerHaptic(String deviceId, int level) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return false;
    }
    return connection.performPlayToSpeakerHaptic(level);
  }

  Future<StreamSubscription?> _getBleStorageBytesListener(
    String deviceId, {
    required void Function(List<int>) onStorageBytesReceived,
  }) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return Future.value(null);
    }
    return connection.getBleStorageBytesListener(
        onStorageBytesReceived: onStorageBytesReceived);
  }

  Future<StreamSubscription?> _getBleAudioBytesListener(
    String deviceId, {
    required void Function(List<int>) onAudioBytesReceived,
  }) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return Future.value(null);
    }
    return connection.getBleAudioBytesListener(
        onAudioBytesReceived: onAudioBytesReceived);
  }

  Future<StreamSubscription?> _getBleButtonListener(
    String deviceId, {
    required void Function(List<int>) onButtonReceived,
  }) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return Future.value(null);
    }
    return connection.getBleButtonListener(onButtonReceived: onButtonReceived);
  }

  Future<List<int>> _getBleButtonState(String deviceId) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return Future.value(<int>[]);
    }
    return connection.getBleButtonState();
  }

  Future<void> _ensureDeviceSocketConnection() async {
    if (_recordingDevice == null) {
      return;
    }
    BleAudioCodec codec = await _getAudioCodec(_recordingDevice!.id);
    var language = SharedPreferencesUtil().hasSetPrimaryLanguage
        ? SharedPreferencesUtil().userPrimaryLanguage
        : "multi";
    if (language != _socket?.language ||
        codec != _socket?.codec ||
        _socket?.state != SocketServiceState.connected) {
      await _initiateWebsocket(audioCodec: codec, force: true);
    }
  }

  Future<void> _initiateDeviceAudioStreaming() async {
    if (_recordingDevice == null) {
      return;
    }
    final deviceId = _recordingDevice!.id;
    BleAudioCodec codec = await _getAudioCodec(deviceId);
    await _wal.getSyncs().phone.onAudioCodecChanged(codec);
    await streamButton(deviceId);
    await streamAudioToWs(deviceId, codec);

    notifyListeners();
  }

  void clearTranscripts() {
    segments = [];
    hasTranscripts = false;
    notifyListeners();
  }

  Future _closeBleStream() async {
    await _bleBytesStream?.cancel();
    notifyListeners();
  }

  @override
  void dispose() {
    _bleBytesStream?.cancel();
    _socket?.unsubscribe(this);
    _keepAliveTimer?.cancel();
    _internetStatusListener?.cancel();
    super.dispose();
  }

  void updateRecordingState(RecordingState state) {
    recordingState = state;
    notifyListeners();
  }

  streamRecording() async {
    await Permission.microphone.request();

    // prepare
    await changeAudioRecordProfile(
        audioCodec: BleAudioCodec.pcm16, sampleRate: 16000);

    // record
    await ServiceManager.instance().mic.start(onByteReceived: (bytes) {
      if (_socket?.state == SocketServiceState.connected) {
        _socket?.send(bytes);
      }
    }, onRecording: () {
      updateRecordingState(RecordingState.record);
    }, onStop: () {
      updateRecordingState(RecordingState.stop);
    }, onInitializing: () {
      updateRecordingState(RecordingState.initialising);
    });
  }

  stopStreamRecording() async {
    await _cleanupCurrentState();
    ServiceManager.instance().mic.stop();
    await _socket?.stop(reason: 'stop stream recording');
  }

  Future streamDeviceRecording({BtDevice? device}) async {
    debugPrint("streamDeviceRecording $device");
    if (device != null) _updateRecordingDevice(device);

    await _resetState();
  }

  Future stopStreamDeviceRecording({bool cleanDevice = false}) async {
    if (cleanDevice) {
      _updateRecordingDevice(null);
    }
    await _cleanupCurrentState();
    await _socket?.stop(reason: 'stop stream device recording');
  }

  // Socket handling

  @override
  void onClosed() {
    _transcriptionServiceStatuses = [];
    _transcriptServiceReady = false;
    debugPrint('[Provider] Socket is closed');

    // Wait for in process Conversation or reset
    if (inProgressConversation == null) {
      _resetStateVariables();
    }

    notifyListeners();
    _startKeepAliveServices();
  }

  void _startKeepAliveServices() {
    _keepAliveTimer?.cancel();
    _keepAliveTimer = Timer.periodic(const Duration(seconds: 15), (t) async {
      debugPrint("[Provider] keep alive...");
      if (!recordingDeviceServiceReady ||
          _socket?.state == SocketServiceState.connected) {
        t.cancel();
        return;
      }
      if (_recordingDevice != null) {
        BleAudioCodec codec = await _getAudioCodec(_recordingDevice!.id);
        await _initiateWebsocket(audioCodec: codec);
        return;
      }
      if (recordingState == RecordingState.record) {
        await _initiateWebsocket(
            audioCodec: BleAudioCodec.pcm16, sampleRate: 16000);
        return;
      }
    });
  }

  @override
  void onError(Object err) {
    _transcriptionServiceStatuses = [];
    _transcriptServiceReady = false;
    debugPrint('err: $err');
    notifyListeners();
    _startKeepAliveServices();
  }

  @override
  void onConnected() {
    _transcriptServiceReady = true;

    // Send dev mode state to backend when WebSocket connects
    _sendDevModeStateToBackend();

    notifyListeners();
  }

  void _sendDevModeStateToBackend() {
    try {
      final devModeEnabled = SharedPreferencesUtil().devModeEnabled;
      final message = jsonEncode({
        'type': 'dev_mode_setting',
        'enabled': devModeEnabled,
      });

      debugPrint(
          '📡 CAPTURE_PROVIDER: Sending dev mode state to backend: $devModeEnabled');
      debugPrint('📡 CAPTURE_PROVIDER: Message content: $message');
      _socket?.send(message);
      debugPrint('📡 CAPTURE_PROVIDER: Dev mode message sent successfully');
    } catch (e) {
      debugPrint(
          '🔴 CAPTURE_PROVIDER: Error sending dev mode state to backend: $e');
    }
  }

  /// Send dev mode state to backend when it changes in settings
  void syncDevModeWithBackend() async {
    debugPrint('📡 CAPTURE_PROVIDER: syncDevModeWithBackend() called');
    debugPrint('📡 CAPTURE_PROVIDER: Socket exists: ${_socket != null}');
    debugPrint('📡 CAPTURE_PROVIDER: Socket state: ${_socket?.state}');

    if (_socket?.state == SocketServiceState.connected) {
      debugPrint(
          '📡 CAPTURE_PROVIDER: Socket is connected, sending dev mode state via WebSocket');
      _sendDevModeStateToBackend();
    } else {
      debugPrint(
          '📡 CAPTURE_PROVIDER: Socket not connected, using HTTP API fallback');
      final devModeEnabled = SharedPreferencesUtil().devModeEnabled;
      try {
        final success = await users_api.syncDevModeWithBackend(devModeEnabled);
        if (success) {
          debugPrint(
              '📡 CAPTURE_PROVIDER: Successfully synced dev mode via HTTP API');
        } else {
          debugPrint(
              '❌ CAPTURE_PROVIDER: Failed to sync dev mode via HTTP API');
        }
      } catch (e) {
        debugPrint(
            '❌ CAPTURE_PROVIDER: Error syncing dev mode via HTTP API: $e');
      }
    }
  }

  void _loadInProgressConversation() async {
    var memories = await getConversations(
        statuses: [ConversationStatus.in_progress], limit: 1);
    _inProgressConversation = memories.isNotEmpty ? memories.first : null;
    if (_inProgressConversation != null) {
      segments = _inProgressConversation!.transcriptSegments;
      setHasTranscripts(segments.isNotEmpty);
    }
    notifyListeners();
  }

  @override
  // Track if we've already manually processed to prevent duplicate processing
  bool _hasManuallyProcessed = false;

  void onMessageEventReceived(ServerMessageEvent event) {
    if (event.type == MessageEventType.conversationProcessingStarted) {
      if (event.conversation == null) {
        debugPrint(
            "Conversation data not received in event. Content is: $event");
        return;
      }

      // 🤖 DEV MODE: In dev mode, completely ignore backend auto-processing to prevent duplicates
      if (SharedPreferencesUtil().devModeEnabled) {
        debugPrint(
            "🤖 DEV MODE: Ignoring backend auto-processing event to prevent duplicate conversations");
        debugPrint(
            "🤖 DEV MODE: Use manual 'Stop Recording' button to trigger agent processing");
        return;
      }

      // Normal mode: just set processing state, actual processing handled by backend
      conversationProvider!.addProcessingConversation(event.conversation!);
      _resetStateVariables();
      return;
    }

    if (event.type == MessageEventType.conversationCreated) {
      debugPrint('🟢 CAPTURE_PROVIDER: Received conversationCreated event');
      if (event.conversation == null) {
        debugPrint(
            "Conversation data not received in event. Content is: $event");
        return;
      }
      debugPrint(
          '🟢 CAPTURE_PROVIDER: Processing conversation created - ID: ${event.conversation!.id}');
      event.conversation!.isNew = true;
      conversationProvider!
          .removeProcessingConversation(event.conversation!.id);
      _processConversationCreated(event.conversation, event.messages ?? []);
      return;
    }

    if (event.type == MessageEventType.lastConversation) {
      if (event.memoryId == null) {
        debugPrint(
            "Conversation ID not received in last_memory event. Content is: $event");
        return;
      }
      _handleLastConvoEvent(event.memoryId!);
      return;
    }

    if (event.type == MessageEventType.translating) {
      if (event.segments == null || event.segments?.isEmpty == true) {
        debugPrint(
            "No segments received in translating event. Content is: $event");
        return;
      }
      _handleTranslationEvent(event.segments!);
      return;
    }

    if (event.type == MessageEventType.serviceStatus) {
      if (event.status == null) {
        return;
      }

      _transcriptionServiceStatuses.add(event);
      _transcriptionServiceStatuses = List.from(_transcriptionServiceStatuses);
      notifyListeners();
      return;
    }
  }

  Future<void> forceProcessingCurrentConversation() async {
    // In development mode, use agent processing instead of standard processing
    if (SharedPreferencesUtil().devModeEnabled) {
      debugPrint(
          '🤖 DEV MODE: Using agent processing instead of standard processing');
      return forceProcessingCurrentConversationWithAgent();
    }

    return _forceProcessingCurrentConversationStandard();
  }

  Future<void> _forceProcessingCurrentConversationStandard() async {
    _hasManuallyProcessed =
        true; // Mark manual processing to prevent duplicates
    conversationProvider!.addProcessingConversation(
      ServerConversation(
          id: '0',
          createdAt: DateTime.now(),
          structured: Structured('', ''),
          status: ConversationStatus.processing),
    );
    processInProgressConversation().then((result) {
      if (result == null || result.conversation == null) {
        conversationProvider!.removeProcessingConversation('0');
        return;
      }
      conversationProvider!.removeProcessingConversation('0');
      result.conversation!.isNew = true;
      _processConversationCreated(result.conversation, result.messages);
    });

    return;
  }

  // Agent-based processing method that creates conversations WITH agent analysis integrated
  // This method directly calls the backend to create conversations with agent analysis
  Future<void> forceProcessingCurrentConversationWithAgent(
      {bool useStreaming = false}) async {
    debugPrint(
        '🟡 CAPTURE_PROVIDER: forceProcessingCurrentConversationWithAgent() called');
    debugPrint('🟡 CAPTURE_PROVIDER: segments.length = ${segments.length}');

    if (segments.isEmpty) {
      debugPrint(
          '🔴 CAPTURE_PROVIDER: No transcript segments available for agent processing');
      return;
    }

    // Mark that we've manually processed to prevent automatic duplicate processing
    _hasManuallyProcessed = true;

    debugPrint(
        '🟡 CAPTURE_PROVIDER: Starting agent conversation processing...');

    // Save segments BEFORE resetting state variables
    final currentSegments = List<TranscriptSegment>.from(segments);

    debugPrint(
        '🟡 CAPTURE_PROVIDER: Saved ${currentSegments.length} segments before processing');

    conversationProvider!.addProcessingConversation(
      ServerConversation(
          id: '0',
          createdAt: DateTime.now(),
          structured: Structured('', ''),
          status: ConversationStatus.processing),
    );

    try {
      // Create transcript and call agent conversation creation directly
      final transcript = TranscriptSegment.segmentsAsString(currentSegments);
      debugPrint(
          '🟡 CAPTURE_PROVIDER: transcript length = ${transcript.length}');

      // Call the backend endpoint that creates conversations with agent analysis directly
      debugPrint(
          '🟡 CAPTURE_PROVIDER: Calling createConversationWithAgent() API directly (eliminates duplicate calls)');
      final response = await createConversationWithAgent(
        transcript: transcript,
        sessionId: DateTime.now().millisecondsSinceEpoch.toString(),
      );

      debugPrint(
          '🟡 CAPTURE_PROVIDER: createConversationWithAgent() API response received');
      debugPrint('🟡 CAPTURE_PROVIDER: response = $response');

      if (response != null && response.conversation != null) {
        conversationProvider!.removeProcessingConversation('0');
        response.conversation!.isNew = true;

        // Store agent analysis in the conversation for display
        if (response.agentAnalysis != null) {
          debugPrint(
              '🟡 CAPTURE_PROVIDER: Agent analysis available for storage');
          debugPrint(
              '🟡 CAPTURE_PROVIDER: Analysis length: ${response.agentAnalysis!.analysis.length}');

          debugPrint(
              '🟡 CAPTURE_PROVIDER: Agent analysis will be displayed via conversation detail UI');
        }

        _processConversationCreated(response.conversation, response.messages);

        debugPrint(
            '🟢 CAPTURE_PROVIDER: Agent-analyzed conversation created successfully via backend');
      } else {
        debugPrint(
            '🔴 CAPTURE_PROVIDER: Failed to create conversation via agent endpoint, falling back to standard processing');
        conversationProvider!.removeProcessingConversation('0');

        // Fallback to standard processing
        _forceProcessingCurrentConversationStandard();
      }
    } catch (e) {
      debugPrint('🔴 CAPTURE_PROVIDER: Error in agent processing: $e');
      conversationProvider!.removeProcessingConversation('0');

      // Fallback to standard processing
      return _forceProcessingCurrentConversationStandard();
    }
  }

  /// NEW: Immediate UI reset with background processing
  /// This method provides instant user feedback by clearing the UI immediately
  /// while continuing to process the conversation in the background
  Future<void> forceProcessingWithImmediateUIReset() async {
    debugPrint(
        '🚀 CAPTURE_PROVIDER: Starting immediate UI reset with background processing');

    if (segments.isEmpty) {
      debugPrint(
          '🔴 CAPTURE_PROVIDER: No transcript segments available for processing');
      return;
    }

    // 1. Save current segments for background processing
    final segmentsToProcess = List<TranscriptSegment>.from(segments);
    debugPrint(
        '💾 CAPTURE_PROVIDER: Saved ${segmentsToProcess.length} segments for background processing');

    // 2. Immediately clear UI transcripts for instant feedback
    _resetStateVariables();
    debugPrint('✨ CAPTURE_PROVIDER: UI transcripts cleared immediately');

    // 3. Start background processing without affecting UI
    _processSegmentsInBackground(segmentsToProcess);
  }

  /// Background processing method that doesn't affect the UI state
  Future<void> _processSegmentsInBackground(
      List<TranscriptSegment> segmentsToProcess) async {
    debugPrint(
        '🔄 CAPTURE_PROVIDER: Starting background processing of ${segmentsToProcess.length} segments');

    final processingId = 'bg_${DateTime.now().millisecondsSinceEpoch}';

    // Add processing conversation to show in conversations list (but not in capture UI)
    conversationProvider!.addProcessingConversation(
      ServerConversation(
          id: processingId,
          createdAt: DateTime.now(),
          structured: Structured('', ''),
          status: ConversationStatus.processing,
          transcriptSegments: segmentsToProcess),
    );

    try {
      // Set timeout for background processing (2 minutes)
      final timeoutDuration = const Duration(minutes: 2);

      if (SharedPreferencesUtil().devModeEnabled) {
        await _processSegmentsWithAgent(segmentsToProcess, processingId)
            .timeout(timeoutDuration);
      } else {
        await _processSegmentsStandard(segmentsToProcess, processingId)
            .timeout(timeoutDuration);
      }
    } on TimeoutException catch (e) {
      debugPrint('⏰ CAPTURE_PROVIDER: Background processing timed out: $e');
      conversationProvider!.removeProcessingConversation(processingId);
    } catch (e) {
      debugPrint('🔴 CAPTURE_PROVIDER: Background processing failed: $e');
      conversationProvider!.removeProcessingConversation(processingId);
    }
  }

  /// Process segments using agent analysis in background
  Future<void> _processSegmentsWithAgent(
      List<TranscriptSegment> segments, String processingId) async {
    try {
      final transcript = TranscriptSegment.segmentsAsString(segments);
      debugPrint(
          '🤖 CAPTURE_PROVIDER: Background agent processing transcript length: ${transcript.length}');

      final response = await createConversationWithAgent(
        transcript: transcript,
        sessionId: DateTime.now().millisecondsSinceEpoch.toString(),
      );

      if (response != null && response.conversation != null) {
        conversationProvider!.removeProcessingConversation(processingId);
        response.conversation!.isNew = true;

        // Process the created conversation (this will add it to the conversations list)
        conversationProvider?.upsertConversation(response.conversation!);
        MixpanelManager().conversationCreated(response.conversation!);

        debugPrint(
            '🟢 CAPTURE_PROVIDER: Background agent processing completed successfully');

        // Optional: Show success notification
        notifyInfo('CONVERSATION_CREATED_BACKGROUND');
      } else {
        debugPrint(
            '🔴 CAPTURE_PROVIDER: Background agent processing failed, trying standard processing');
        await _processSegmentsStandard(segments, processingId);
      }
    } catch (e) {
      debugPrint('🔴 CAPTURE_PROVIDER: Background agent processing error: $e');
      // Fallback to standard processing
      await _processSegmentsStandard(segments, processingId);
    }
  }

  /// Process segments using standard processing in background
  Future<void> _processSegmentsStandard(
      List<TranscriptSegment> segments, String processingId) async {
    try {
      debugPrint('📝 CAPTURE_PROVIDER: Background standard processing');

      // Note: For proper background processing, we should create a conversation
      // from the segments directly, but for now we'll use the existing API
      final result = await processInProgressConversation();

      if (result != null && result.conversation != null) {
        conversationProvider!.removeProcessingConversation(processingId);
        result.conversation!.isNew = true;

        conversationProvider?.upsertConversation(result.conversation!);
        MixpanelManager().conversationCreated(result.conversation!);

        debugPrint(
            '🟢 CAPTURE_PROVIDER: Background standard processing completed successfully');

        // Optional: Show success notification
        notifyInfo('CONVERSATION_CREATED_BACKGROUND');
      } else {
        debugPrint(
            '🔴 CAPTURE_PROVIDER: Background standard processing failed');
        conversationProvider!.removeProcessingConversation(processingId);
        notifyError('BACKGROUND_PROCESSING_FAILED');
      }
    } catch (e) {
      debugPrint(
          '🔴 CAPTURE_PROVIDER: Background standard processing error: $e');
      conversationProvider!.removeProcessingConversation(processingId);
      notifyError('BACKGROUND_PROCESSING_FAILED');
    }
  }

  /// Manually discard any ongoing background processing (useful for user control)
  void discardBackgroundProcessing() {
    // Remove all background processing conversations
    final backgroundProcessingIds = conversationProvider
            ?.processingConversations
            .where((conv) => conv.id.startsWith('bg_'))
            .map((conv) => conv.id)
            .toList() ??
        [];

    for (final id in backgroundProcessingIds) {
      conversationProvider?.removeProcessingConversation(id);
    }

    debugPrint(
        '🗑️ CAPTURE_PROVIDER: Discarded ${backgroundProcessingIds.length} background processing conversations');
  }

  // Method to switch between standard and agent processing
  Future<void> forceProcessingCurrentConversationSmart(
      {bool preferAgent = true}) async {
    if (preferAgent && agentConversationProvider != null) {
      debugPrint('Using agent-based conversation processing');
      return forceProcessingCurrentConversationWithAgent();
    } else {
      debugPrint('Using standard conversation processing');
      return forceProcessingCurrentConversation();
    }
  }

  // Method to analyze current conversation WITHOUT agent integration (creates standard conversation first, then analyzes)
  // Note: This does NOT create a conversation with agent analysis - use forceProcessingCurrentConversationWithAgent() for that
  Future<void> analyzeCurrentConversationWithAgent(
      {bool useStreaming = false}) async {
    if (agentConversationProvider == null) {
      debugPrint('Agent conversation provider not available');
      return;
    }

    if (segments.isEmpty) {
      debugPrint('No transcript segments available for analysis');
      return;
    }

    try {
      // 1. Create the conversation first
      final createResponse = await processInProgressConversation();
      if (createResponse == null || createResponse.conversation == null) {
        debugPrint('Failed to create conversation before agent analysis');
        return;
      }
      final newConversationId = createResponse.conversation!.id;

      // 2. Now call the agent analysis with the new conversation ID
      await agentConversationProvider!.analyzeConversation(
        transcriptSegments: segments,
        conversationId: newConversationId,
        useStreaming: useStreaming,
      );

      debugPrint('Real-time agent analysis started');
    } catch (e) {
      debugPrint('Error starting agent analysis: $e');
    }
  }

  Future<void> _processConversationCreated(
      ServerConversation? conversation, List<ServerMessage> messages) async {
    if (conversation == null) return;
    conversationProvider?.upsertConversation(conversation);
    MixpanelManager().conversationCreated(conversation);

    // Reset the recording state so UI is ready for next recording
    await _resetStateVariables();
    debugPrint(
        '🟢 CAPTURE_PROVIDER: Recording state reset after conversation created - ready for new recording');
  }

  Future<void> _handleLastConvoEvent(String memoryId) async {
    bool conversationExists = conversationProvider?.conversations
            .any((conversation) => conversation.id == memoryId) ??
        false;
    if (conversationExists) {
      return;
    }
    ServerConversation? conversation = await getConversationById(memoryId);
    if (conversation != null) {
      debugPrint("Adding last conversation to conversations: $memoryId");
      conversationProvider?.upsertConversation(conversation);
    } else {
      debugPrint("Failed to fetch last conversation: $memoryId");
    }
  }

  void _handleTranslationEvent(List<TranscriptSegment> translatedSegments) {
    try {
      if (translatedSegments.isEmpty) return;

      debugPrint("Received ${translatedSegments.length} translated segments");

      // Update the segments with the translated ones
      var remainSegments =
          TranscriptSegment.updateSegments(segments, translatedSegments);
      if (remainSegments.isNotEmpty) {
        debugPrint("Adding ${remainSegments.length} new translated segments");
      }

      notifyListeners();
    } catch (e) {
      debugPrint("Error handling translation event: $e");
    }
  }

  @override
  void onSegmentReceived(List<TranscriptSegment> newSegments) {
    if (newSegments.isEmpty) return;

    if (segments.isEmpty) {
      debugPrint('newSegments: ${newSegments.last}');
      FlutterForegroundTask.sendDataToTask(jsonEncode({'location': true}));
      _loadInProgressConversation();
    }
    var remainSegments =
        TranscriptSegment.updateSegments(segments, newSegments);
    TranscriptSegment.combineSegments(segments, remainSegments);

    hasTranscripts = true;
    notifyListeners();
  }

  void onInternetSatusChanged(InternetStatus status) {
    debugPrint("[SocketService] Internet connection changed $status");
    _internetStatus = status;
    notifyListeners();
  }

  void setIsWalSupported(bool value) {
    _isWalSupported = value;
    notifyListeners();
  }

  /*
  *
  *
  *
  *
  *
  * */

  List<int> currentStorageFiles = <int>[];
  int sdCardFileNum = 1;

// To show the progress of the download in the UI
  int currentTotalBytesReceived = 0;
  double currentSdCardSecondsReceived = 0.0;
//--------------------------------------------

  int totalStorageFileBytes = 0; // how much in storage
  int totalBytesReceived = 0; // how much already received
  double sdCardSecondsTotal = 0.0; // time to send the next chunk
  double sdCardSecondsReceived = 0.0;
  bool sdCardDownloadDone = false;
  bool sdCardReady = false;
  bool sdCardIsDownloading = false;
  String btConnectedTime = "";
  Timer? sdCardReconnectionTimer;

  void setSdCardIsDownloading(bool value) {
    sdCardIsDownloading = value;
    notifyListeners();
  }

  Future<void> updateStorageList() async {
    currentStorageFiles = await _getStorageList(_recordingDevice!.id);
    if (currentStorageFiles.isEmpty) {
      debugPrint('No storage files found');
      SharedPreferencesUtil().deviceIsV2 = false;
      debugPrint('Device is not V2');
      return;
    }
    totalStorageFileBytes = currentStorageFiles[0];
    var storageOffset =
        currentStorageFiles.length < 2 ? 0 : currentStorageFiles[1];
    totalBytesReceived = storageOffset;
    notifyListeners();
  }

  Future<void> initiateStorageBytesStreaming() async {
    debugPrint('initiateStorageBytesStreaming');
    if (_recordingDevice == null) return;
    String deviceId = _recordingDevice!.id;
    var storageFiles = await _getStorageList(deviceId);
    if (storageFiles.isEmpty) {
      return;
    }
    var totalBytes = storageFiles[0];
    if (totalBytes <= 0) {
      return;
    }
    var storageOffset = storageFiles.length < 2 ? 0 : storageFiles[1];
    if (storageOffset > totalBytes) {
      // bad state?
      debugPrint("SDCard bad state, offset > total");
      storageOffset = 0;
    }

    // 80: frame length, 100: frame per seconds
    BleAudioCodec codec = await _getAudioCodec(deviceId);
    sdCardSecondsTotal = totalBytes /
        codec.getFramesLengthInBytes() /
        codec.getFramesPerSecond();
    sdCardSecondsReceived = storageOffset /
        codec.getFramesLengthInBytes() /
        codec.getFramesPerSecond();

    // > 10s
    if (totalBytes - storageOffset >
        10 * codec.getFramesLengthInBytes() * codec.getFramesPerSecond()) {
      sdCardReady = true;
    }

    notifyListeners();
  }

  Future _getFileFromDevice(int fileNum, int offset) async {
    sdCardFileNum = fileNum;
    int command = 0;
    _writeToStorage(_recordingDevice!.id, sdCardFileNum, command, offset);
  }

  Future _clearFileFromDevice(int fileNum) async {
    sdCardFileNum = fileNum;
    int command = 1;
    _writeToStorage(_recordingDevice!.id, sdCardFileNum, command, 0);
  }

  Future _pauseFileFromDevice(int fileNum) async {
    sdCardFileNum = fileNum;
    int command = 3;
    _writeToStorage(_recordingDevice!.id, sdCardFileNum, command, 0);
  }

  void _notifySdCardComplete() {
    NotificationService.instance.clearNotification(8);
    NotificationService.instance.createNotification(
      notificationId: 8,
      title: 'Sd Card Processing Complete',
      body: 'Your Sd Card data is now processed! Enter the app to see.',
    );
  }

  Future<bool> _writeToStorage(
      String deviceId, int numFile, int command, int offset) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return Future.value(false);
    }
    return connection.writeToStorage(numFile, command, offset);
  }

  Future<List<int>> _getStorageList(String deviceId) async {
    var connection =
        await ServiceManager.instance().device.ensureConnection(deviceId);
    if (connection == null) {
      return [];
    }
    return connection.getStorageList();
  }
}
