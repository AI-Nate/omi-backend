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

      // Verify haptic services are available
      if (!await _areHapticServicesAvailable(connection)) {
        print('❌ HAPTIC: Haptic services not available on connected device');
        return false;
      }

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

      // Trigger the haptic on omi device
      bool result = await connection.performPlayToSpeakerHaptic(hapticLevel);

      // If action required, add an additional haptic after a delay
      if (result && actionRequired) {
        await Future.delayed(Duration(milliseconds: 300));
        await connection.performPlayToSpeakerHaptic(hapticLevel);
        print('🎯 HAPTIC: Additional haptic triggered for action required');
      }

      return result;
    } catch (e) {
      print('❌ HAPTIC: Error triggering OMI device haptic: $e');
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
      // For OMI devices, we can test if performPlayToSpeakerHaptic works
      // by calling it with level 0 (should be safe/no-op)
      print('🔍 HAPTIC: Testing service availability...');

      // Try a test haptic command (level 0 should be safe)
      bool result = await connection.performPlayToSpeakerHaptic(0);

      if (result) {
        print('🟢 HAPTIC: Haptic services are available');
        return true;
      } else {
        print('⚠️ HAPTIC: Haptic service test failed');
        return false;
      }
    } catch (e) {
      print('❌ HAPTIC: Error testing haptic services: $e');
      return false;
    }
  }
}
