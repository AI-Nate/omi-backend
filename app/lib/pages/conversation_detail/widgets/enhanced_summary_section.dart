import 'package:flutter/material.dart';
import 'package:omi/backend/schema/structured.dart';

class EnhancedSummarySection extends StatelessWidget {
  final Structured structured;

  const EnhancedSummarySection({
    super.key,
    required this.structured,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Main Overview
        Container(
          margin: const EdgeInsets.only(bottom: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: Colors.deepPurple.withOpacity(0.2),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      structured.getEmoji(),
                      style: const TextStyle(fontSize: 20),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    'Overview',
                    style: Theme.of(context).textTheme.titleMedium!.copyWith(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                structured.overview,
                style: const TextStyle(
                  fontSize: 16,
                  height: 1.5,
                  color: Colors.white,
                ),
              ),
            ],
          ),
        ),

        // Key Takeaways Section
        if (structured.keyTakeaways.isNotEmpty) ...[
          _buildSectionHeader(
              context, 'Key Takeaways', Icons.lightbulb_outline),
          _buildBulletPointList(structured.keyTakeaways),
          const SizedBox(height: 24),
        ],

        // Things to Improve Section
        if (structured.thingsToImprove.isNotEmpty) ...[
          _buildSectionHeader(context, 'Things to Improve', Icons.trending_up),
          _buildBulletPointList(structured.thingsToImprove),
          const SizedBox(height: 24),
        ],

        // Things to Learn Section
        if (structured.thingsToLearn.isNotEmpty) ...[
          _buildSectionHeader(
              context, 'Things to Learn', Icons.school_outlined),
          _buildBulletPointList(structured.thingsToLearn),
          const SizedBox(height: 24),
        ],
      ],
    );
  }

  Widget _buildSectionHeader(
      BuildContext context, String title, IconData icon) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Icon(
            icon,
            size: 20,
            color: Colors.deepPurple.shade300,
          ),
          const SizedBox(width: 8),
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium!.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildBulletPointList(List<String> items) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: items.map((item) => _buildBulletPoint(item)).toList(),
    );
  }

  Widget _buildBulletPoint(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '•',
            style: TextStyle(
              color: Colors.deepPurple,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 15,
                height: 1.4,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
