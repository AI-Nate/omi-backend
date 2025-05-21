import 'package:flutter/material.dart';
import 'package:omi/backend/schema/structured.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'dart:typed_data';
import 'package:url_launcher/url_launcher.dart';

class EnhancedSummarySection extends StatelessWidget {
  final ServerConversation conversation;
  final bool enhancedByImage;
  final List<Uint8List>? imageDataList;
  final List<String>? imageDescriptions;

  const EnhancedSummarySection({
    super.key,
    required this.conversation,
    this.enhancedByImage = false,
    this.imageDataList,
    this.imageDescriptions,
  });

  @override
  Widget build(BuildContext context) {
    final structured = conversation.structured;
    final userName = SharedPreferencesUtil().givenName.isEmpty
        ? 'You'
        : SharedPreferencesUtil().givenName;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Title with optional image enhanced indicator
        Row(
          children: [
            Text(
              'Enhanced Summary',
              style: Theme.of(context).textTheme.titleLarge!.copyWith(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                  ),
            ),
            if (enhancedByImage &&
                imageDataList != null &&
                imageDataList!.isNotEmpty) ...[
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.purple.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.purple.withOpacity(0.5)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.image,
                      size: 14,
                      color: Colors.purple,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      imageDataList!.length > 1
                          ? '${imageDataList!.length} Images'
                          : 'Image Enhanced',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.purple,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 16),

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
          _buildPersonalizedSectionHeader(
              context, 'Things to Improve for $userName', Icons.trending_up),
          _buildPersonalizedBulletPointList(structured.thingsToImprove),
          const SizedBox(height: 24),
        ],

        // Things to Learn Section
        if (structured.thingsToLearn.isNotEmpty) ...[
          _buildPersonalizedSectionHeader(
              context, 'Things for $userName to Learn', Icons.school_outlined),
          _buildPersonalizedBulletPointList(structured.thingsToLearn),
          const SizedBox(height: 24),
        ],

        // Add image gallery at the bottom if available
        if (imageDataList != null && imageDataList!.isNotEmpty) ...[
          const SizedBox(height: 24),
          _buildImagesSection(context),
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

  Widget _buildPersonalizedSectionHeader(
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
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium!.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const SizedBox(height: 4),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [
                        Colors.deepPurple.withOpacity(0.3),
                        Colors.blue.withOpacity(0.3),
                      ],
                    ),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text(
                    'Personalized for you',
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.white70,
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

  Widget _buildBulletPointList(List<String> items) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: items.map((item) => _buildBulletPoint(item)).toList(),
    );
  }

  Widget _buildPersonalizedBulletPointList(List<dynamic> items) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: items.map((item) {
        if (item is ResourceItem) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '•',
                  style: TextStyle(
                    fontSize: 18,
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.content,
                        style: const TextStyle(
                          fontSize: 16,
                          height: 1.5,
                          color: Colors.white,
                        ),
                      ),
                      if (item.url.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: InkWell(
                            onTap: () async {
                              final Uri url = Uri.parse(item.url);
                              if (await canLaunchUrl(url)) {
                                await launchUrl(url);
                              }
                            },
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12, vertical: 8),
                              decoration: BoxDecoration(
                                color: Colors.deepPurple.withOpacity(0.2),
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(
                                    color: Colors.deepPurple.withOpacity(0.3)),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  const Icon(
                                    Icons.link,
                                    size: 16,
                                    color: Colors.deepPurple,
                                  ),
                                  const SizedBox(width: 8),
                                  Flexible(
                                    child: Text(
                                      item.title.isNotEmpty
                                          ? item.title
                                          : item.url,
                                      style: const TextStyle(
                                        color: Colors.deepPurple,
                                        fontWeight: FontWeight.bold,
                                        fontSize: 14,
                                      ),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          );
        } else {
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '•',
                  style: TextStyle(
                    fontSize: 18,
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    item.toString(),
                    style: const TextStyle(
                      fontSize: 16,
                      height: 1.5,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),
          );
        }
      }).toList(),
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

  Widget _buildImagesSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Section header
        _buildSectionHeader(
            context,
            imageDataList!.length > 1 ? 'Source Images' : 'Source Image',
            Icons.photo_library),

        // Image gallery
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            childAspectRatio: 1.0,
          ),
          itemCount: imageDataList!.length,
          itemBuilder: (context, index) {
            return _buildImageCard(context, index);
          },
        ),
      ],
    );
  }

  Widget _buildImageCard(BuildContext context, int index) {
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
      ),
      elevation: 4,
      clipBehavior: Clip.antiAlias,
      color: Colors.black.withOpacity(0.3),
      child: InkWell(
        onTap: () {
          // Show full-screen image with description when tapped
          _showFullScreenImage(context, index);
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Image takes most of the card space
            Expanded(
              flex: 4,
              child: Image.memory(
                imageDataList![index],
                fit: BoxFit.cover,
              ),
            ),

            // Description preview (if available)
            if (imageDescriptions != null &&
                index < imageDescriptions!.length &&
                imageDescriptions![index].isNotEmpty)
              Expanded(
                flex: 1,
                child: Container(
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: Colors.black.withOpacity(0.5),
                  ),
                  child: Text(
                    _truncateDescription(imageDescriptions![index]),
                    style: const TextStyle(
                      fontSize: 10,
                      color: Colors.white70,
                    ),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  void _showFullScreenImage(BuildContext context, int index) {
    showDialog(
      context: context,
      builder: (context) => Dialog.fullscreen(
        child: Container(
          color: Colors.black,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // App bar with close button
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.close, color: Colors.white),
                      onPressed: () => Navigator.of(context).pop(),
                    ),
                    Text(
                      'Image ${index + 1}/${imageDataList!.length}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                      ),
                    ),
                    const SizedBox(width: 48), // Balance the layout
                  ],
                ),
              ),

              // Full screen image
              Expanded(
                child: InteractiveViewer(
                  minScale: 0.5,
                  maxScale: 4.0,
                  child: Center(
                    child: Image.memory(
                      imageDataList![index],
                      fit: BoxFit.contain,
                    ),
                  ),
                ),
              ),

              // Image description
              if (imageDescriptions != null &&
                  index < imageDescriptions!.length &&
                  imageDescriptions![index].isNotEmpty)
                Container(
                  padding: const EdgeInsets.all(16),
                  color: Colors.black.withOpacity(0.7),
                  width: double.infinity,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Image Description:',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Colors.grey,
                          fontSize: 14,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        imageDescriptions![index],
                        style: const TextStyle(
                          fontSize: 14,
                          color: Colors.white,
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  String _truncateDescription(String description) {
    if (description.length <= 50) return description;
    return '${description.substring(0, 47)}...';
  }
}
