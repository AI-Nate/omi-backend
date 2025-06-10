import 'package:flutter/material.dart';
import '../../services/urgency_haptic_service.dart';

class UrgencyHapticTestPage extends StatefulWidget {
  const UrgencyHapticTestPage({Key? key}) : super(key: key);

  @override
  State<UrgencyHapticTestPage> createState() => _UrgencyHapticTestPageState();
}

class _UrgencyHapticTestPageState extends State<UrgencyHapticTestPage> {
  String _lastTestResult = '';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.primary,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        title: const Text(
          'Urgency Haptic Test',
          style: TextStyle(color: Colors.white, fontSize: 20),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Test Urgency Haptic Patterns',
              style: TextStyle(
                color: Colors.white,
                fontSize: 24,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Test different haptic patterns based on conversation urgency levels.\nSupports both OMI Haptic service and Speaker service fallback.',
              style: TextStyle(color: Colors.grey, fontSize: 16),
            ),
            const SizedBox(height: 32),

            // Urgency Level Tests
            _buildUrgencyTestSection(),

            const SizedBox(height: 32),

            // Advanced Testing Section
            _buildAdvancedTestSection(),

            const SizedBox(height: 32),

            // Device Status Section
            _buildDeviceStatusSection(),

            const SizedBox(height: 32),

            // Sample Urgency Assessments
            _buildSampleAssessmentsSection(),

            const SizedBox(height: 16),

            // Last test result
            if (_lastTestResult.isNotEmpty) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.grey.shade800,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Last Test Result:',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _lastTestResult,
                      style: const TextStyle(color: Colors.grey),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildUrgencyTestSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Basic Urgency Levels',
          style: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 16),

        // Low Urgency Test
        _buildTestButton(
          title: '🟢 Low Urgency',
          description: 'Light haptic: 100ms (main) / 20ms (devkit)',
          onPressed: () => _testUrgencyLevel(UrgencyLevel.low),
          color: Colors.green,
        ),

        const SizedBox(height: 12),

        // Medium Urgency Test
        _buildTestButton(
          title: '🟡 Medium Urgency',
          description: 'Medium haptic: 300ms (main) / 50ms (devkit)',
          onPressed: () => _testUrgencyLevel(UrgencyLevel.medium),
          color: Colors.orange,
        ),

        const SizedBox(height: 12),

        // High Urgency Test
        _buildTestButton(
          title: '🔴 High Urgency',
          description: 'Strong haptic: 500ms (both firmwares)',
          onPressed: () => _testUrgencyLevel(UrgencyLevel.high),
          color: Colors.red,
        ),
      ],
    );
  }

  Widget _buildAdvancedTestSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Advanced Pattern Testing',
          style: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          'Test patterns with "Action Required" flag (triggers additional pulse)',
          style: TextStyle(color: Colors.grey, fontSize: 14),
        ),
        const SizedBox(height: 16),

        // Low Urgency with Action Required
        _buildTestButton(
          title: '🟢 Low + Action Required',
          description: 'Light haptic with extra pulse for attention',
          onPressed: () => _testUrgencyLevelWithAction(UrgencyLevel.low),
          color: Colors.green.shade300,
        ),

        const SizedBox(height: 12),

        // Medium Urgency with Action Required
        _buildTestButton(
          title: '🟡 Medium + Action Required',
          description: 'Medium haptic with extra pulse for attention',
          onPressed: () => _testUrgencyLevelWithAction(UrgencyLevel.medium),
          color: Colors.orange.shade300,
        ),

        const SizedBox(height: 12),

        // High Urgency with Action Required
        _buildTestButton(
          title: '🔴 High + Action Required',
          description: 'Strong haptic with extra pulse for attention',
          onPressed: () => _testUrgencyLevelWithAction(UrgencyLevel.high),
          color: Colors.red.shade300,
        ),
      ],
    );
  }

  Widget _buildDeviceStatusSection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.grey.shade800,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey.shade600),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Device Connection Status',
            style: TextStyle(
              color: Colors.white,
              fontSize: 18,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '• Main OMI Firmware: Uses dedicated Haptic service',
            style: TextStyle(color: Colors.grey, fontSize: 14),
          ),
          const SizedBox(height: 4),
          const Text(
            '• DevKit Firmware: Uses Speaker service for haptic',
            style: TextStyle(color: Colors.grey, fontSize: 14),
          ),
          const SizedBox(height: 4),
          const Text(
            '• Both services use UUID: CAB1AB95-2EA5-4F4D-BB56-874B72CFC984',
            style: TextStyle(color: Colors.grey, fontSize: 12),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.blue.withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.blue.withOpacity(0.3)),
            ),
            child: const Row(
              children: [
                Icon(Icons.info_outline, color: Colors.blue, size: 16),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'The app will automatically use the available service with fallback to phone haptic.',
                    style: TextStyle(
                      color: Colors.blue,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSampleAssessmentsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Sample Urgency Assessments',
          style: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 16),

        // High urgency sample
        _buildSampleAssessmentCard(
          urgencyAssessment: {
            'level': 'high',
            'reasoning': 'Contains urgent deadline requiring immediate action',
            'action_required': true,
            'time_sensitivity': 'within 2 hours'
          },
          title: 'Urgent Meeting Reminder',
          description: 'Meeting with client in 30 minutes',
        ),

        const SizedBox(height: 12),

        // Medium urgency sample
        _buildSampleAssessmentCard(
          urgencyAssessment: {
            'level': 'medium',
            'reasoning': 'Important task with flexible deadline',
            'action_required': false,
            'time_sensitivity': 'within 1 week'
          },
          title: 'Project Planning Discussion',
          description: 'Planning next quarter objectives',
        ),

        const SizedBox(height: 12),

        // Low urgency sample
        _buildSampleAssessmentCard(
          urgencyAssessment: {
            'level': 'low',
            'reasoning': 'Casual conversation without time constraints',
            'action_required': false,
            'time_sensitivity': 'no rush'
          },
          title: 'Casual Chat with Friend',
          description: 'Weekend plans discussion',
        ),
      ],
    );
  }

  Widget _buildTestButton({
    required String title,
    required String description,
    required VoidCallback onPressed,
    required Color color,
  }) {
    return Container(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: color.withOpacity(0.2),
          foregroundColor: color,
          padding: const EdgeInsets.all(16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: color.withOpacity(0.3)),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              description,
              style: TextStyle(
                fontSize: 14,
                color: color.withOpacity(0.8),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSampleAssessmentCard({
    required Map<String, dynamic> urgencyAssessment,
    required String title,
    required String description,
  }) {
    final urgencyDescription =
        UrgencyHapticService.getUrgencyDescription(urgencyAssessment);
    final requiresAttention =
        UrgencyHapticService.requiresImmediateAttention(urgencyAssessment);

    return Container(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: () => _testUrgencyAssessment(urgencyAssessment, title),
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.grey.shade800,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.all(16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                if (requiresAttention)
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.2),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.red.withOpacity(0.3)),
                    ),
                    child: const Text(
                      'URGENT',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        color: Colors.red,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              description,
              style: const TextStyle(
                fontSize: 14,
                color: Colors.grey,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              urgencyDescription,
              style: const TextStyle(
                fontSize: 12,
                color: Colors.grey,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _testUrgencyLevel(UrgencyLevel level) async {
    try {
      await UrgencyHapticService.testHapticPattern(level);
      setState(() {
        _lastTestResult =
            'Tested ${level.name.toUpperCase()} urgency pattern successfully';
      });
    } catch (e) {
      setState(() {
        _lastTestResult = 'Error testing ${level.name} pattern: $e';
      });
    }
  }

  Future<void> _testUrgencyAssessment(
      Map<String, dynamic> urgencyAssessment, String title) async {
    try {
      await UrgencyHapticService.triggerUrgencyHaptic(urgencyAssessment);
      final description =
          UrgencyHapticService.getUrgencyDescription(urgencyAssessment);
      setState(() {
        _lastTestResult = 'Tested "$title" assessment:\n$description';
      });
    } catch (e) {
      setState(() {
        _lastTestResult = 'Error testing "$title" assessment: $e';
      });
    }
  }

  Future<void> _testUrgencyLevelWithAction(UrgencyLevel level) async {
    try {
      await UrgencyHapticService.testHapticPatternWithAction(level);
      setState(() {
        _lastTestResult =
            'Tested ${level.name.toUpperCase()} urgency pattern WITH action required successfully';
      });
    } catch (e) {
      setState(() {
        _lastTestResult = 'Error testing ${level.name} pattern with action: $e';
      });
    }
  }
}
