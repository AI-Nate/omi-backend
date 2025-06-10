import 'package:flutter/services.dart';
import '../backend/schema/structured.dart';

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
    if (urgencyAssessment == null) return;

    final level = _parseUrgencyLevel(urgencyAssessment['level']);
    final actionRequired = urgencyAssessment['action_required'] ?? false;

    print(
        '🔔 HAPTIC: Triggering urgency haptic - Level: $level, Action Required: $actionRequired');

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
      switch (level) {
        case UrgencyLevel.high:
          // High urgency: Heavy impact multiple times
          print('🔴 HAPTIC: Executing HIGH urgency pattern (heavy impact)');
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
          print('🟡 HAPTIC: Executing MEDIUM urgency pattern (medium impact)');
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
          print('🟢 HAPTIC: Executing LOW urgency pattern (light impact)');
          await HapticFeedback.lightImpact();
          if (actionRequired) {
            await Future.delayed(Duration(milliseconds: 100));
            await HapticFeedback.lightImpact();
          }
          break;
      }

      print('✅ HAPTIC: Pattern executed successfully');
    } catch (e) {
      print('❌ HAPTIC: Error executing haptic pattern: $e');
    }
  }

  /// Test haptic patterns for user settings
  static Future<void> testHapticPattern(UrgencyLevel level) async {
    print('🧪 HAPTIC: Testing $level urgency pattern');
    await _executeHapticPattern(level, false);
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
}
