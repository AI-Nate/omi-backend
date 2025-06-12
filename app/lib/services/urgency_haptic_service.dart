import 'package:flutter/services.dart';
import '../backend/schema/structured.dart';
import '../services/services.dart';
import '../services/devices.dart';
import '../services/devices/device_connection.dart';
import '../backend/preferences.dart';

enum UrgencyLevel {
  low,
  medium,
  high,
}

class UrgencyHapticService {
  static const String _methodChannel = 'haptic_urgency';
  static const MethodChannel _channel = MethodChannel(_methodChannel);

  /// Trigger haptic feedback based on urgency assessment
  static Future<void> triggerUrgencyHaptic(
      Map<String, dynamic>? urgencyAssessment) async {
    // Check if haptic feedback is enabled in settings
    if (!SharedPreferencesUtil().hapticFeedbackEnabled) {
      print('🔔 HAPTIC: Haptic feedback disabled in settings, skipping');
      return;
    }

    if (urgencyAssessment == null) {
      print('🔔 HAPTIC: No urgency assessment provided');
      return;
    }

    final level = _parseUrgencyLevel(urgencyAssessment['level']);
    final actionRequired = urgencyAssessment['action_required'] ?? false;

    print(
        '🔔 HAPTIC: Triggering urgency haptic - Level: $level, Action Required: $actionRequired');
    print('🔔 HAPTIC: Raw urgency assessment: $urgencyAssessment');

    // TODO: This currently only triggers phone haptic, need to trigger omi device haptic motor
    print(
        '⚠️ HAPTIC: WARNING - Currently only triggering PHONE haptic, not OMI DEVICE haptic motor');

    await _executeHapticPattern(level, actionRequired);
  }

  /// Trigger haptic feedback for a conversation with urgency assessment
  static Future<void> triggerHapticForConversation(
      Structured structured) async {
    // Check if haptic feedback is enabled in settings
    if (!SharedPreferencesUtil().hapticFeedbackEnabled) {
      print('🔔 HAPTIC: Haptic feedback disabled in settings, skipping');
      return;
    }

    if (structured.urgencyAssessment == null) {
      print('⚪ HAPTIC: No urgency assessment available for conversation');
      return;
    }

    await triggerUrgencyHaptic(structured.urgencyAssessment);
  }

  /// Parse urgency level from string
  static UrgencyLevel _parseUrgencyLevel(String? level) {
    switch (level?.toLowerCase()) {
      case 'high':
        return UrgencyLevel.high;
      case 'medium':
        return UrgencyLevel.medium;
      case 'low':
      default:
        return UrgencyLevel.low;
    }
  }

  /// Execute haptic pattern based on urgency level
  static Future<void> _executeHapticPattern(
      UrgencyLevel level, bool actionRequired) async {
    try {
      // First try to trigger haptic on the omi device
      bool deviceHapticTriggered =
          await _triggerOmiDeviceHaptic(level, actionRequired);

      if (deviceHapticTriggered) {
        print('✅ HAPTIC: OMI device haptic triggered successfully');
      } else {
        print(
            '⚠️ HAPTIC: OMI device not available, falling back to phone haptic');
        await _triggerPhoneHaptic(level, actionRequired);
      }

      print('✅ HAPTIC: Pattern executed successfully');
    } catch (e) {
      print('❌ HAPTIC: Error executing haptic pattern: $e');
      // Fallback to phone haptic in case of error
      try {
        await _triggerPhoneHaptic(level, actionRequired);
        print('✅ HAPTIC: Fallback phone haptic executed successfully');
      } catch (fallbackError) {
        print('❌ HAPTIC: Fallback phone haptic also failed: $fallbackError');
      }
    }
  }

  /// Trigger haptic feedback on the omi device hardware
  static Future<bool> _triggerOmiDeviceHaptic(
      UrgencyLevel level, bool actionRequired) async {
    try {
      // Get the connected device ID from SharedPreferences
      final deviceService = ServiceManager.instance().device;
      final deviceId = _getConnectedDeviceId();

      if (deviceId.isEmpty) {
        print('🔍 HAPTIC: No omi device connected (empty device ID)');
        return false;
      }

      // Get device connection with comprehensive retry logic
      DeviceConnection? connection =
          await _establishDeviceConnection(deviceId, deviceService);

      if (connection == null) {
        print('❌ HAPTIC: Failed to establish device connection');
        return false;
      }

      // Try Haptic/Speaker service first
      if (await _areHapticServicesAvailable(connection)) {
        return await _triggerHapticService(connection, level, actionRequired);
      }

      // Fallback to audio feedback using existing audio service
      print('🔊 HAPTIC: Attempting audio feedback via available services');
      return await _triggerAudioFeedback(connection, level, actionRequired);
    } catch (e) {
      print('❌ HAPTIC: Error triggering OMI device haptic: $e');
      return false;
    }
  }

  /// Trigger haptic using dedicated haptic/speaker service
  static Future<bool> _triggerHapticService(DeviceConnection connection,
      UrgencyLevel level, bool actionRequired) async {
    // Map urgency levels to omi device haptic levels
    int hapticLevel;
    switch (level) {
      case UrgencyLevel.high:
        hapticLevel = 3; // 500ms - strong haptic
        print('🔴 HAPTIC: Triggering HIGH urgency on OMI device (500ms)');
        break;
      case UrgencyLevel.medium:
        hapticLevel = 2; // 300ms (main) / 50ms (devkit) - medium haptic
        print(
            '🟡 HAPTIC: Triggering MEDIUM urgency on OMI device (300ms/50ms)');
        break;
      case UrgencyLevel.low:
      default:
        hapticLevel = 1; // 100ms (main) / 20ms (devkit) - light haptic
        print('🟢 HAPTIC: Triggering LOW urgency on OMI device (100ms/20ms)');
        break;
    }

    // Trigger the haptic with retry logic
    bool result = await _executeHapticWithRetry(connection, hapticLevel);

    // If action required, add an additional haptic after a delay
    if (result && actionRequired) {
      await Future.delayed(Duration(milliseconds: 300));
      await _executeHapticWithRetry(connection, hapticLevel);
      print('🎯 HAPTIC: Additional haptic triggered for action required');
    }

    return result;
  }

  /// Execute haptic with retry logic for better reliability
  static Future<bool> _executeHapticWithRetry(
      DeviceConnection connection, int intensity) async {
    for (int attempt = 1; attempt <= 2; attempt++) {
      try {
        print('🔍 HAPTIC: Execution attempt $attempt/2...');

        // Small delay before attempt
        if (attempt > 1) {
          await Future.delayed(Duration(milliseconds: 300));
        }

        bool result = await connection.performPlayToSpeakerHaptic(intensity);

        if (result) {
          print('✅ HAPTIC: Execution successful on attempt $attempt');
          return true;
        } else {
          print('❌ HAPTIC: Execution returned false on attempt $attempt');
        }
      } catch (e) {
        print('❌ HAPTIC: Execution attempt $attempt failed: $e');

        // If it's a Bluetooth timing error, wait before retry
        if (e.toString().contains('apple-code: 14') ||
            e.toString().contains('Unlikely error')) {
          print('🔄 HAPTIC: Bluetooth timing issue detected');
          if (attempt < 2) {
            await Future.delayed(Duration(milliseconds: 800));
          }
        }
      }
    }

    return false;
  }

  /// Trigger audio feedback using button or other available services
  static Future<bool> _triggerAudioFeedback(DeviceConnection connection,
      UrgencyLevel level, bool actionRequired) async {
    try {
      print('🔊 HAPTIC: Attempting audio feedback for urgency level: $level');

      // For DevKit 2 firmware 2.0.1, we can try to trigger audio feedback
      // by simulating button presses or other available mechanisms

      // Create audio pattern based on urgency level
      List<int> pattern;
      switch (level) {
        case UrgencyLevel.high:
          pattern = [3, 3, 3]; // Triple urgent pattern
          print('🔴 AUDIO: Triggering HIGH urgency audio pattern (triple)');
          break;
        case UrgencyLevel.medium:
          pattern = [2, 2]; // Double medium pattern
          print('🟡 AUDIO: Triggering MEDIUM urgency audio pattern (double)');
          break;
        case UrgencyLevel.low:
        default:
          pattern = [1]; // Single gentle pattern
          print('🟢 AUDIO: Triggering LOW urgency audio pattern (single)');
          break;
      }

      // Execute the audio pattern
      bool success = false;
      for (int i = 0; i < pattern.length; i++) {
        // Try to trigger any available feedback mechanism
        success = await _triggerAudioFeedbackPulse(connection, pattern[i]);
        if (success) {
          print('✅ AUDIO: Audio feedback pulse ${i + 1} successful');
        } else {
          print('❌ AUDIO: Audio feedback pulse ${i + 1} failed');
        }

        // Add delay between pulses
        if (i < pattern.length - 1) {
          await Future.delayed(Duration(milliseconds: 200));
        }
      }

      // If action required, add an additional sequence
      if (success && actionRequired) {
        await Future.delayed(Duration(milliseconds: 500));
        await _triggerAudioFeedbackPulse(connection, 3);
        print('🎯 AUDIO: Additional audio feedback for action required');
      }

      return success;
    } catch (e) {
      print('❌ AUDIO: Error triggering audio feedback: $e');
      return false;
    }
  }

  /// Trigger a single audio feedback pulse
  static Future<bool> _triggerAudioFeedbackPulse(
      DeviceConnection connection, int intensity) async {
    try {
      // For DevKit 2, we could try alternative approaches:
      // 1. Use the button service to simulate a press (might generate audio)
      // 2. Use other available characteristics
      // 3. Future: Direct audio service integration

      print('🔊 AUDIO: Attempting audio pulse with intensity $intensity');

      // Try button simulation for audio feedback
      if (connection is dynamic) {
        try {
          var bleDevice = connection.bleDevice;
          if (bleDevice != null) {
            var services = await bleDevice.discoverServices();

            // Look for button service (23ba7924-0000-1000-7450-346eac492e92)
            for (var service in services) {
              if (service.uuid.str128.toLowerCase() ==
                  '23ba7924-0000-1000-7450-346eac492e92') {
                for (var char in service.characteristics) {
                  if (char.uuid.str128.toLowerCase() ==
                      '23ba7925-0000-1000-7450-346eac492e92') {
                    // Try to write a pattern that might generate audio feedback
                    await char.write([intensity]);
                    print(
                        '🔊 AUDIO: Sent audio feedback command via button service');
                    return true;
                  }
                }
              }
            }
          }
        } catch (e) {
          print('❌ AUDIO: Button service audio attempt failed: $e');
        }
      }

      // Alternative: Log the attempt for future implementation
      print('🔊 AUDIO: Audio feedback logged for DevKit 2 firmware upgrade');
      print(
          '📝 AUDIO: Consider updating to firmware 2.0.10 for full speaker support');

      return false; // Return false so it falls back to phone haptic
    } catch (e) {
      print('❌ AUDIO: Error in audio feedback pulse: $e');
      return false;
    }
  }

  /// Get connected omi device ID from SharedPreferences
  static String _getConnectedDeviceId() {
    try {
      final deviceId = SharedPreferencesUtil().btDevice.id;
      print('🔍 HAPTIC: Retrieved device ID from SharedPreferences: $deviceId');
      return deviceId;
    } catch (e) {
      print('❌ HAPTIC: Error getting connected device ID: $e');
      return '';
    }
  }

  /// Fallback to phone haptic feedback
  static Future<void> _triggerPhoneHaptic(
      UrgencyLevel level, bool actionRequired) async {
    switch (level) {
      case UrgencyLevel.high:
        // High urgency: Heavy impact multiple times
        print(
            '🔴 HAPTIC: Executing HIGH urgency pattern on PHONE (heavy impact)');
        await HapticFeedback.heavyImpact();
        await Future.delayed(Duration(milliseconds: 200));
        await HapticFeedback.heavyImpact();
        if (actionRequired) {
          await Future.delayed(Duration(milliseconds: 100));
          await HapticFeedback.heavyImpact();
        }
        break;
      case UrgencyLevel.medium:
        // Medium urgency: Medium impact twice
        print(
            '🟡 HAPTIC: Executing MEDIUM urgency pattern on PHONE (medium impact)');
        await HapticFeedback.mediumImpact();
        await Future.delayed(Duration(milliseconds: 150));
        await HapticFeedback.mediumImpact();
        if (actionRequired) {
          await Future.delayed(Duration(milliseconds: 100));
          await HapticFeedback.mediumImpact();
        }
        break;
      case UrgencyLevel.low:
      default:
        // Low urgency: Single light impact
        print(
            '🟢 HAPTIC: Executing LOW urgency pattern on PHONE (light impact)');
        await HapticFeedback.lightImpact();
        if (actionRequired) {
          await Future.delayed(Duration(milliseconds: 100));
          await HapticFeedback.lightImpact();
        }
        break;
    }
  }

  /// Test haptic patterns for user settings
  static Future<void> testHapticPattern(UrgencyLevel level) async {
    print('🧪 HAPTIC: Testing $level urgency pattern');
    await _executeHapticPattern(level, false);
  }

  /// Test haptic patterns with action required for comprehensive testing
  static Future<void> testHapticPatternWithAction(UrgencyLevel level) async {
    print('🧪 HAPTIC: Testing $level urgency pattern WITH action required');
    await _executeHapticPattern(level, true);
  }

  /// Test device connection status (for debugging)
  static Future<void> testDeviceConnection() async {
    try {
      final deviceService = ServiceManager.instance().device;
      final deviceId = _getConnectedDeviceId();

      print('🔍 HAPTIC: Testing device connection...');
      print('🔍 HAPTIC: Device ID: $deviceId');

      if (deviceId.isEmpty) {
        print('❌ HAPTIC: No device ID found in SharedPreferences');
        return;
      }

      // Test current connection
      var connection = await deviceService.ensureConnection(deviceId);
      print(
          '🔍 HAPTIC: Current connection: ${connection != null ? 'EXISTS' : 'NULL'}');
      if (connection != null) {
        print('🔍 HAPTIC: Connection state: ${connection.connectionState}');
        print(
            '🔍 HAPTIC: Bluetooth connected: ${await connection.isConnected()}');
        print('🔍 HAPTIC: Can ping: ${await connection.ping()}');
      }

      // Test connection with retry logic
      connection = await _establishDeviceConnection(deviceId, deviceService);
      print(
          '🔍 HAPTIC: Connection after retry: ${connection != null ? 'ESTABLISHED' : 'FAILED'}');

      if (connection != null) {
        print(
            '🔍 HAPTIC: Final connection state: ${connection.connectionState}');
        print('🔍 HAPTIC: Testing haptic services...');
        bool servicesAvailable = await _areHapticServicesAvailable(connection);
        print('🔍 HAPTIC: Haptic services available: $servicesAvailable');
      }
    } catch (e) {
      print('❌ HAPTIC: Error testing device connection: $e');
    }
  }

  /// Check if urgency requires immediate attention
  static bool requiresImmediateAttention(
      Map<String, dynamic>? urgencyAssessment) {
    if (urgencyAssessment == null) return false;

    final level = _parseUrgencyLevel(urgencyAssessment['level']);
    final actionRequired = urgencyAssessment['action_required'] ?? false;

    return level == UrgencyLevel.high || actionRequired;
  }

  /// Get human-readable description of urgency assessment
  static String getUrgencyDescription(Map<String, dynamic>? urgencyAssessment) {
    if (urgencyAssessment == null) return 'No urgency assessment';

    final level = _parseUrgencyLevel(urgencyAssessment['level']);
    final reasoning = urgencyAssessment['reasoning'] ?? '';
    final actionRequired = urgencyAssessment['action_required'] ?? false;
    final timeSensitivity = urgencyAssessment['time_sensitivity'] ?? '';

    String description = '';

    switch (level) {
      case UrgencyLevel.high:
        description = '🔴 HIGH URGENCY';
        break;
      case UrgencyLevel.medium:
        description = '🟡 MEDIUM URGENCY';
        break;
      case UrgencyLevel.low:
        description = '🟢 LOW URGENCY';
        break;
    }

    if (actionRequired) {
      description += ' - Action Required';
    }

    if (timeSensitivity.isNotEmpty) {
      description += ' ($timeSensitivity)';
    }

    if (reasoning.isNotEmpty) {
      description += '\n$reasoning';
    }

    return description;
  }

  /// Establish device connection with comprehensive retry logic
  static Future<DeviceConnection?> _establishDeviceConnection(
      String deviceId, deviceService) async {
    // Step 1: Try normal connection
    DeviceConnection? connection =
        await deviceService.ensureConnection(deviceId);
    if (await _isConnectionValid(connection)) {
      print('🟢 HAPTIC: Device already connected');
      return connection;
    }

    // Step 2: Try forced reconnection
    print(
        '🔄 HAPTIC: Initial connection failed, attempting forced reconnection...');
    connection = await deviceService.ensureConnection(deviceId, force: true);
    if (await _isConnectionValid(connection)) {
      print('🟢 HAPTIC: Device reconnected successfully');
      return connection;
    }

    // Step 3: Try device discovery and connection
    print(
        '🔍 HAPTIC: Forced reconnection failed, attempting device discovery...');
    try {
      await deviceService.discover(desirableDeviceId: deviceId, timeout: 5);

      // Wait a bit for discovery to complete
      await Future.delayed(Duration(milliseconds: 1000));

      // Try connection after discovery
      connection = await deviceService.ensureConnection(deviceId, force: true);
      if (await _isConnectionValid(connection)) {
        print('🟢 HAPTIC: Device connected after discovery');
        return connection;
      }
    } catch (e) {
      print('❌ HAPTIC: Device discovery failed: $e');
    }

    // Step 4: Final failure
    print('❌ HAPTIC: All connection attempts failed');
    return null;
  }

  /// Validate if connection is truly connected and usable
  static Future<bool> _isConnectionValid(DeviceConnection? connection) async {
    if (connection == null) {
      print('🔍 HAPTIC: Connection is null');
      return false;
    }

    // Check connection state
    if (connection.connectionState != DeviceConnectionState.connected) {
      print(
          '🔍 HAPTIC: Connection state is not connected: ${connection.connectionState}');
      return false;
    }

    // Check if Bluetooth device is actually connected
    bool isConnected = await connection.isConnected();
    if (!isConnected) {
      print('🔍 HAPTIC: Bluetooth device is not connected');
      return false;
    }

    // Test if we can ping the device
    bool canPing = await connection.ping();
    if (!canPing) {
      print('🔍 HAPTIC: Cannot ping device');
      return false;
    }

    print('🟢 HAPTIC: Connection is valid and responsive');
    return true;
  }

  /// Check if haptic services are available on the device
  static Future<bool> _areHapticServicesAvailable(
      DeviceConnection connection) async {
    try {
      print('🔍 HAPTIC: Testing service availability...');

      // Add detailed service discovery debugging
      await _debugDeviceServices(connection);

      // Wait a bit for services to be fully ready after discovery
      await Future.delayed(Duration(milliseconds: 500));

      // Try a test haptic command with better error handling
      print('🔍 HAPTIC: Attempting test haptic command...');
      bool result = await _testHapticServiceWithRetry(connection);

      if (result) {
        print('🟢 HAPTIC: Haptic services are available and working');
        return true;
      } else {
        print('⚠️ HAPTIC: Haptic service test failed, but service exists');
        // Even if test fails, if service exists, we should try to use it
        return await _checkIfHapticServiceExists(connection);
      }
    } catch (e) {
      print('❌ HAPTIC: Error testing haptic services: $e');
      // Check if service exists even if test failed
      return await _checkIfHapticServiceExists(connection);
    }
  }

  /// Test haptic service with retry logic
  static Future<bool> _testHapticServiceWithRetry(
      DeviceConnection connection) async {
    for (int attempt = 1; attempt <= 3; attempt++) {
      try {
        print('🔍 HAPTIC: Test attempt $attempt/3...');

        // Use level 1 instead of 0 (some services might not respond to 0)
        bool result = await connection.performPlayToSpeakerHaptic(1);

        if (result) {
          print('✅ HAPTIC: Test successful on attempt $attempt');
          return true;
        }

        print('❌ HAPTIC: Test failed on attempt $attempt');

        // Wait before retry
        if (attempt < 3) {
          await Future.delayed(Duration(milliseconds: 200 * attempt));
        }
      } catch (e) {
        print('❌ HAPTIC: Test attempt $attempt failed: $e');

        // If it's a Bluetooth timing error, wait longer before retry
        if (e.toString().contains('apple-code: 14') ||
            e.toString().contains('Unlikely error')) {
          if (attempt < 3) {
            print(
                '🔄 HAPTIC: Bluetooth timing issue detected, waiting before retry...');
            await Future.delayed(Duration(milliseconds: 1000));
          }
        }
      }
    }

    return false;
  }

  /// Check if haptic service exists without testing it
  static Future<bool> _checkIfHapticServiceExists(
      DeviceConnection connection) async {
    try {
      if (connection is dynamic) {
        var bleDevice = connection.bleDevice;
        if (bleDevice != null) {
          var services = await bleDevice.discoverServices();

          for (var service in services) {
            if (service.uuid.str128.toLowerCase() ==
                'cab1ab95-2ea5-4f4d-bb56-874b72cfc984') {
              for (var char in service.characteristics) {
                if (char.uuid.str128.toLowerCase() ==
                    'cab1ab96-2ea5-4f4d-bb56-874b72cfc984') {
                  print(
                      '🟢 HAPTIC: Service and characteristic exist, assuming available');
                  return true;
                }
              }
            }
          }
        }
      }
      return false;
    } catch (e) {
      print('❌ HAPTIC: Error checking service existence: $e');
      return false;
    }
  }

  /// Debug what services are actually available on the device
  static Future<void> _debugDeviceServices(DeviceConnection connection) async {
    try {
      print('🔍 HAPTIC: === SERVICE DISCOVERY DEBUG ===');
      print('🔍 HAPTIC: Device type: ${connection.runtimeType}');
      print('🔍 HAPTIC: Connection state: ${connection.connectionState}');

      // Check expected service UUIDs
      print(
          '🔍 HAPTIC: Expected Haptic service UUID: cab1ab95-2ea5-4f4d-bb56-874b72cfc984');
      print(
          '🔍 HAPTIC: Expected Speaker service UUID: cab1ab95-2ea5-4f4d-bb56-874b72cfc984');

      // Try to access the actual services discovered
      if (connection is dynamic) {
        try {
          // Try to get the BLE device and discover services
          var bleDevice = connection.bleDevice;
          if (bleDevice != null) {
            print('🔍 HAPTIC: BLE Device found, discovering services...');

            // Force service discovery
            var services = await bleDevice.discoverServices();
            print('🔍 HAPTIC: Found ${services.length} total services:');

            for (var service in services) {
              var uuid = service.uuid.str128.toLowerCase();
              print('🔍 HAPTIC: Service UUID: $uuid');

              // Check for our target UUID
              if (uuid == 'cab1ab95-2ea5-4f4d-bb56-874b72cfc984') {
                print('🟢 HAPTIC: FOUND TARGET SERVICE! UUID: $uuid');
                print(
                    '🔍 HAPTIC: Service has ${service.characteristics.length} characteristics:');
                for (var char in service.characteristics) {
                  var charUuid = char.uuid.str128.toLowerCase();
                  print('🔍 HAPTIC: - Characteristic UUID: $charUuid');
                  if (charUuid == 'cab1ab96-2ea5-4f4d-bb56-874b72cfc984') {
                    print(
                        '🟢 HAPTIC: FOUND TARGET CHARACTERISTIC! UUID: $charUuid');
                  }
                }
              } else {
                print('🔍 HAPTIC: - Other service: $uuid');
              }

              // Check Device Information Service for firmware version
              if (uuid == '0000180a-0000-1000-8000-00805f9b34fb') {
                print('🔍 HAPTIC: Found Device Information Service');
                for (var char in service.characteristics) {
                  var charUuid = char.uuid.str128.toLowerCase();
                  if (charUuid == '00002a26-0000-1000-8000-00805f9b34fb') {
                    try {
                      var firmwareData = await char.read();
                      String firmwareVersion =
                          String.fromCharCodes(firmwareData);
                      print(
                          '🔍 HAPTIC: Device Firmware Version: $firmwareVersion');
                    } catch (e) {
                      print('❌ HAPTIC: Error reading firmware version: $e');
                    }
                  }
                }
              }
            }
          } else {
            print('❌ HAPTIC: BLE Device is null');
          }
        } catch (e) {
          print('❌ HAPTIC: Error accessing BLE services: $e');
        }
      }

      print('🔍 HAPTIC: === END SERVICE DEBUG ===');
    } catch (e) {
      print('❌ HAPTIC: Error in service debugging: $e');
    }
  }
}
