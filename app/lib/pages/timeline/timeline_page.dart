import 'package:flutter/material.dart';
import 'package:font_awesome_flutter/font_awesome_flutter.dart';
import 'package:intl/intl.dart';
import 'package:omi/providers/timeline_provider.dart';
import 'package:omi/pages/conversation_detail/conversation_detail_provider.dart';
import 'package:omi/pages/conversation_detail/page.dart';
import 'package:provider/provider.dart';
import 'package:visibility_detector/visibility_detector.dart';
import 'package:omi/providers/conversation_provider.dart';

// Helper class to represent a time marker's position and size
class TimeMarkerInfo {
  final double top;
  final double height;
  final bool isMajorHour;

  TimeMarkerInfo({
    required this.top,
    required this.height,
    required this.isMajorHour,
  });
}

// Helper functions for overlap detection
class TimelineOverlapHelper {
  static const double dayHeight = 1200.0;

  // Calculate all time marker positions for a day
  static List<TimeMarkerInfo> calculateTimeMarkerPositions() {
    List<TimeMarkerInfo> markers = [];

    for (int index = 0; index < 13; index++) {
      double position = index / 12;
      int hour = index * 2;
      bool isMajorHour = hour % 6 == 0;

      // Time marker position calculation (from the original code)
      double top = 40 + (dayHeight - 80) * position - 12;

      // Height based on whether it's major hour (from original styling)
      double height = isMajorHour ? 22 : 19; // padding + text height

      markers.add(TimeMarkerInfo(
        top: top,
        height: height,
        isMajorHour: isMajorHour,
      ));
    }

    return markers;
  }

  // Calculate event dot position based on time position
  static double calculateEventDotPosition(double timePosition) {
    // Event position calculation (from the original code)
    return 80 +
        (dayHeight - 240) * timePosition -
        80; // simplifies to: 960 * timePosition
  }

  // Check if an event dot overlaps with any time marker
  static bool isEventDotOverlapping(
      double timePosition, List<TimeMarkerInfo> timeMarkers) {
    double eventDotTop = calculateEventDotPosition(timePosition);
    const double dotRadius =
        9; // Maximum dot radius (16/2 = 8, plus some buffer)

    for (TimeMarkerInfo marker in timeMarkers) {
      // Check vertical overlap with buffer zone
      double markerTop = marker.top;
      double markerBottom = marker.top + marker.height;
      double dotTop = eventDotTop - dotRadius;
      double dotBottom = eventDotTop + dotRadius;

      // Overlap occurs if there's any vertical intersection
      if (!(dotBottom < markerTop || dotTop > markerBottom)) {
        return true;
      }
    }

    return false;
  }

  // Calculate transparency based on overlap
  static double calculateDotOpacity(
      double timePosition, List<TimeMarkerInfo> timeMarkers) {
    if (isEventDotOverlapping(timePosition, timeMarkers)) {
      return 0.4; // Reduced opacity when overlapping
    }
    return 1.0; // Full opacity when not overlapping
  }
}

class TimelinePage extends StatefulWidget {
  const TimelinePage({super.key});

  @override
  State<TimelinePage> createState() => _TimelinePageState();
}

class _TimelinePageState extends State<TimelinePage>
    with AutomaticKeepAliveClientMixin {
  final TextEditingController _searchController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() {
      context
          .read<TimelineProvider>()
          .updateSearchQuery(_searchController.text);
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Consumer<TimelineProvider>(
      builder: (context, timelineProvider, child) {
        return RefreshIndicator(
          backgroundColor: Colors.black,
          color: Colors.white,
          onRefresh: () => timelineProvider.refreshEvents(),
          child: CustomScrollView(
            controller: _scrollController,
            slivers: [
              const SliverToBoxAdapter(child: SizedBox(height: 20)),
              // Search Bar
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16.0),
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.grey[900],
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: Colors.grey[700]!),
                    ),
                    child: TextField(
                      controller: _searchController,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'Search timeline events...',
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        prefixIcon: Icon(Icons.search, color: Colors.grey[400]),
                        suffixIcon: _searchController.text.isNotEmpty
                            ? IconButton(
                                icon:
                                    Icon(Icons.clear, color: Colors.grey[400]),
                                onPressed: () {
                                  _searchController.clear();
                                  timelineProvider.updateSearchQuery('');
                                },
                              )
                            : null,
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 14,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SliverToBoxAdapter(child: SizedBox(height: 16)),
              // Category Filters
              if (timelineProvider.availableCategories.isNotEmpty)
                SliverToBoxAdapter(
                  child: SizedBox(
                    height: 40,
                    child: ListView.builder(
                      scrollDirection: Axis.horizontal,
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      itemCount: timelineProvider.availableCategories.length,
                      itemBuilder: (context, index) {
                        final category =
                            timelineProvider.availableCategories[index];
                        final isSelected = timelineProvider.selectedCategories
                            .contains(category);
                        final color = Color(int.parse(
                                timelineProvider
                                    .getCategoryColor(category)
                                    .substring(1),
                                radix: 16) +
                            0xFF000000);

                        return Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: FilterChip(
                            label: Text(
                              category.toUpperCase(),
                              style: TextStyle(
                                color: isSelected ? Colors.white : color,
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            selected: isSelected,
                            onSelected: (selected) {
                              timelineProvider.toggleCategoryFilter(category);
                            },
                            backgroundColor: Colors.transparent,
                            selectedColor: color,
                            checkmarkColor: Colors.white,
                            side: BorderSide(color: color, width: 1.5),
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                          ),
                        );
                      },
                    ),
                  ),
                ),
              const SliverToBoxAdapter(child: SizedBox(height: 24)),
              // Timeline Events
              if (timelineProvider.events.isEmpty)
                SliverToBoxAdapter(
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32.0),
                      child: Column(
                        children: [
                          const Icon(
                            FontAwesomeIcons.clock,
                            size: 48,
                            color: Colors.grey,
                          ),
                          const SizedBox(height: 16),
                          const Text(
                            'No timeline events found',
                            style: TextStyle(
                              color: Colors.grey,
                              fontSize: 18,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                          const SizedBox(height: 8),
                          const Text(
                            'Your conversations will appear here as timeline events',
                            style: TextStyle(
                              color: Colors.grey,
                              fontSize: 14,
                            ),
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 16),
                          ElevatedButton(
                            onPressed: () => timelineProvider.refreshEvents(),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.deepPurple,
                              foregroundColor: Colors.white,
                            ),
                            child: const Text('Refresh'),
                          ),
                        ],
                      ),
                    ),
                  ),
                )
              else
                SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      if (index >= timelineProvider.sortedDates.length) {
                        // Just return empty space at the end
                        return const SizedBox(height: 20);
                      }

                      final date = timelineProvider.sortedDates[index];
                      final eventsForDate =
                          timelineProvider.groupedEvents[date]!;
                      final isFirst = index == 0;
                      final isLast =
                          index == timelineProvider.sortedDates.length - 1;

                      return TimelineDayWidget(
                        date: date,
                        events: eventsForDate,
                        isFirst: isFirst,
                        isLast: isLast,
                        timelineProvider: timelineProvider,
                      );
                    },
                    childCount: timelineProvider.sortedDates.length + 1,
                  ),
                ),
              const SliverToBoxAdapter(child: SizedBox(height: 67)),
            ],
          ),
        );
      },
    );
  }
}

class TimelineEventWidget extends StatelessWidget {
  final TimelineEvent event;
  final bool isOnRight;
  final bool isFirst;
  final bool isLast;
  final TimelineProvider timelineProvider;

  const TimelineEventWidget({
    super.key,
    required this.event,
    required this.isOnRight,
    required this.isFirst,
    required this.isLast,
    required this.timelineProvider,
  });

  @override
  Widget build(BuildContext context) {
    final categoryColor = Color(int.parse(
            timelineProvider.getCategoryColor(event.category).substring(1),
            radix: 16) +
        0xFF000000);

    return Container(
      margin: const EdgeInsets.only(bottom: 24),
      child: Row(
        children: [
          // Left side content
          if (!isOnRight)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(right: 16),
                child: _buildEventCard(
                    context, categoryColor, Alignment.centerRight),
              ),
            )
          else
            Expanded(child: Container()),

          // Central timeline
          Container(
            width: 60,
            child: Column(
              children: [
                // Timeline line (top)
                if (!isFirst)
                  Container(
                    width: 2,
                    height: 30,
                    color: Colors.grey[700],
                  ),

                // Event dot
                Container(
                  width: event.isImportant ? 16 : 12,
                  height: event.isImportant ? 16 : 12,
                  decoration: BoxDecoration(
                    color: categoryColor,
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: Colors.black,
                      width: 2,
                    ),
                    boxShadow: event.isImportant
                        ? [
                            BoxShadow(
                              color: categoryColor.withOpacity(0.4),
                              blurRadius: 8,
                              spreadRadius: 2,
                            ),
                          ]
                        : null,
                  ),
                ),

                // Timeline line (bottom)
                if (!isLast)
                  Container(
                    width: 2,
                    height: 30,
                    color: Colors.grey[700],
                  ),
              ],
            ),
          ),

          // Right side content
          if (isOnRight)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(left: 16),
                child: _buildEventCard(
                    context, categoryColor, Alignment.centerLeft),
              ),
            )
          else
            Expanded(child: Container()),
        ],
      ),
    );
  }

  Widget _buildEventCard(
      BuildContext context, Color categoryColor, Alignment alignment) {
    return Align(
      alignment: alignment,
      child: GestureDetector(
        onTap: () {
          if (event.conversation != null) {
            // Find the conversation in the ConversationProvider to get proper index and date
            final conversationProvider = context.read<ConversationProvider>();
            DateTime? foundDate;
            int? foundIndex;

            // Search through grouped conversations to find the matching conversation
            for (var entry
                in conversationProvider.groupedConversations.entries) {
              final conversations = entry.value;
              for (int i = 0; i < conversations.length; i++) {
                if (conversations[i].id == event.conversation!.id) {
                  foundDate = entry.key;
                  foundIndex = i;
                  break;
                }
              }
              if (foundDate != null) break;
            }

            if (foundDate != null && foundIndex != null) {
              // Use the same navigation pattern as Home page
              context
                  .read<ConversationDetailProvider>()
                  .updateConversation(foundIndex, foundDate);

              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (context) => ConversationDetailPage(
                    conversation: event.conversation!,
                  ),
                ),
              );
            } else {
              // Fallback: if conversation not found in provider, show error
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Unable to load conversation details'),
                  backgroundColor: Colors.red,
                ),
              );
            }
          }
        },
        child: Container(
          constraints: const BoxConstraints(maxWidth: 300),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.grey[900],
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.grey[700]!),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.2),
                blurRadius: 8,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              // Timestamp
              Text(
                DateFormat('h:mm a').format(event.timestamp),
                style: TextStyle(
                  color: Colors.grey[400],
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 8),

              // Category tag and emoji
              Row(
                children: [
                  Text(
                    event.emoji,
                    style: const TextStyle(fontSize: 18),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: categoryColor,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      event.category.toUpperCase(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Title
              Text(
                event.title,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 8),

              // Summary
              Text(
                event.summary,
                style: TextStyle(
                  color: Colors.grey[300],
                  fontSize: 14,
                  height: 1.4,
                ),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),

              // Duration
              if (event.duration > 0) ...[
                const SizedBox(height: 12),
                Row(
                  children: [
                    Icon(
                      FontAwesomeIcons.clock,
                      color: Colors.grey[500],
                      size: 12,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${event.duration} min',
                      style: TextStyle(
                        color: Colors.grey[500],
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class TimelineDayWidget extends StatelessWidget {
  final DateTime date;
  final List<TimelineEvent> events;
  final bool isFirst;
  final bool isLast;
  final TimelineProvider timelineProvider;

  const TimelineDayWidget({
    super.key,
    required this.date,
    required this.events,
    required this.isFirst,
    required this.isLast,
    required this.timelineProvider,
  });

  @override
  Widget build(BuildContext context) {
    const double dayHeight =
        1200.0; // Doubled from 600 to 1200 for better spacing
    const double timelineWidth = 60.0;

    // Calculate time marker positions for overlap detection
    final timeMarkerPositions =
        TimelineOverlapHelper.calculateTimeMarkerPositions();

    return Container(
      margin: const EdgeInsets.only(
          bottom: 40), // Reduced from 120px to 40px (1/3 of original)
      child: Column(
        children: [
          // Date header
          Container(
            padding: const EdgeInsets.symmetric(
                vertical: 24), // Increased padding for date header
            child: Row(
              children: [
                Expanded(
                  child: Container(
                    height: 1,
                    color: Colors.grey[700],
                  ),
                ),
                Container(
                  margin: const EdgeInsets.symmetric(
                      horizontal: 20), // Increased horizontal margin
                  padding: const EdgeInsets.symmetric(
                      horizontal: 20, vertical: 12), // Increased padding
                  decoration: BoxDecoration(
                    color: Colors.grey[800],
                    borderRadius:
                        BorderRadius.circular(24), // Increased border radius
                    border: Border.all(color: Colors.grey[600]!, width: 1),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.3),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Text(
                    DateFormat('EEEE, MMM d, yyyy').format(date),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 15, // Slightly larger font
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                Expanded(
                  child: Container(
                    height: 1,
                    color: Colors.grey[700],
                  ),
                ),
              ],
            ),
          ),

          // Day timeline with events
          Container(
            height: dayHeight,
            padding:
                const EdgeInsets.symmetric(vertical: 40), // Increased padding
            margin: const EdgeInsets.only(
                bottom: 67), // Reduced from 200px to 67px (1/3 of original)
            child: Stack(
              children: [
                // Central timeline line
                Positioned(
                  left: (MediaQuery.of(context).size.width - timelineWidth) / 2,
                  top: 40, // Account for increased padding
                  bottom: 40, // Account for increased padding
                  child: Container(
                    width: 2,
                    color: Colors.grey[700],
                  ),
                ),

                // Time markers (every 2 hours for better granularity) - moved to right side
                ...List.generate(13, (index) {
                  double position =
                      index / 12; // 0 to 12/12 (1.0) for 13 markers
                  int hour = index * 2;

                  // Convert to 12-hour format with AM/PM
                  String timeLabel;
                  if (hour == 0) {
                    timeLabel = '12AM'; // Midnight
                  } else if (hour == 12) {
                    timeLabel = '12PM'; // Noon
                  } else if (hour == 24) {
                    timeLabel = '12AM'; // End of day (midnight)
                  } else if (hour < 12) {
                    timeLabel =
                        '${hour.toString().padLeft(2, '0')}AM'; // Morning hours
                  } else {
                    timeLabel =
                        '${(hour - 12).toString().padLeft(2, '0')}PM'; // Afternoon/Evening hours
                  }

                  // Highlight major time markers (midnight, 6am, noon, 6pm, midnight)
                  bool isMajorHour = hour % 6 == 0;

                  return Positioned(
                    left: (MediaQuery.of(context).size.width - timelineWidth) /
                            2 +
                        10,
                    top: 40 +
                        (dayHeight - 80) * position -
                        12, // Account for increased padding and center text
                    child: Container(
                      padding: EdgeInsets.symmetric(
                          horizontal: isMajorHour ? 10 : 8,
                          vertical: isMajorHour ? 5 : 4),
                      decoration: BoxDecoration(
                        color:
                            isMajorHour ? Colors.grey[750] : Colors.grey[800],
                        borderRadius:
                            BorderRadius.circular(isMajorHour ? 8 : 6),
                        border: Border.all(
                            color: isMajorHour
                                ? Colors.grey[500]!
                                : Colors.grey[600]!,
                            width: isMajorHour ? 1 : 0.5),
                        boxShadow: isMajorHour
                            ? [
                                BoxShadow(
                                  color: Colors.black.withOpacity(0.3),
                                  blurRadius: 4,
                                  offset: const Offset(0, 1),
                                ),
                              ]
                            : null,
                      ),
                      child: Text(
                        timeLabel,
                        style: TextStyle(
                          color:
                              isMajorHour ? Colors.grey[200] : Colors.grey[300],
                          fontSize: isMajorHour ? 12 : 11,
                          fontWeight:
                              isMajorHour ? FontWeight.w600 : FontWeight.w500,
                        ),
                      ),
                    ),
                  );
                }),

                // Events positioned based on time
                ...timelineProvider
                    .getGroupedEventsForDay(date)
                    .asMap()
                    .entries
                    .map((entry) {
                  int groupIndex = entry.key;
                  List<TimelineEvent> eventGroup = entry.value;

                  double timePosition = timelineProvider
                      .getAverageTimePositionForGroup(eventGroup);
                  bool isOnRight = groupIndex % 2 == 0;

                  return Positioned(
                    top: 80 +
                        (dayHeight - 240) * timePosition -
                        80, // More conservative positioning with larger safety margins
                    left: 0,
                    right: 0,
                    child: SwipeableEventStack(
                      events: eventGroup,
                      isOnRight: isOnRight,
                      timelineProvider: timelineProvider,
                      timePosition: timePosition,
                      timeMarkerPositions: timeMarkerPositions,
                    ),
                  );
                }).toList(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class TimelineEventWithPositioning extends StatelessWidget {
  final TimelineEvent event;
  final bool isOnRight;
  final TimelineProvider timelineProvider;
  final double timePosition;
  final List<TimeMarkerInfo> timeMarkerPositions;

  const TimelineEventWithPositioning({
    super.key,
    required this.event,
    required this.isOnRight,
    required this.timelineProvider,
    required this.timePosition,
    required this.timeMarkerPositions,
  });

  @override
  Widget build(BuildContext context) {
    final categoryColor = Color(int.parse(
            timelineProvider.getCategoryColor(event.category).substring(1),
            radix: 16) +
        0xFF000000);

    // Calculate opacity based on overlap
    final dotOpacity = TimelineOverlapHelper.calculateDotOpacity(
        timePosition, timeMarkerPositions);

    return Row(
      children: [
        // Left side content
        if (!isOnRight)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(
                  right: 18), // Matched with swipeable stack padding
              child: _buildEventCard(
                  context, categoryColor, Alignment.centerRight),
            ),
          )
        else
          Expanded(child: Container()),

        // Event dot on timeline
        Container(
          width: 60,
          margin: const EdgeInsets.only(
              left: 0), // Offset to align with shifted timeline
          child: Center(
            child: Opacity(
              opacity: dotOpacity,
              child: Container(
                width: event.isImportant ? 16 : 12,
                height: event.isImportant ? 16 : 12,
                decoration: BoxDecoration(
                  color: categoryColor,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: Colors.black,
                    width: 2,
                  ),
                  boxShadow: event.isImportant
                      ? [
                          BoxShadow(
                            color: categoryColor.withOpacity(0.4),
                            blurRadius: 8,
                            spreadRadius: 2,
                          ),
                        ]
                      : null,
                ),
              ),
            ),
          ),
        ),

        // Right side content
        if (isOnRight)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(
                  left: 18), // Matched with swipeable stack padding
              child:
                  _buildEventCard(context, categoryColor, Alignment.centerLeft),
            ),
          )
        else
          Expanded(child: Container()),
      ],
    );
  }

  Widget _buildEventCard(
      BuildContext context, Color categoryColor, Alignment alignment) {
    return Align(
      alignment: alignment,
      child: GestureDetector(
        onTap: () {
          if (event.conversation != null) {
            // Find the conversation in the ConversationProvider to get proper index and date
            final conversationProvider = context.read<ConversationProvider>();
            DateTime? foundDate;
            int? foundIndex;

            // Search through grouped conversations to find the matching conversation
            for (var entry
                in conversationProvider.groupedConversations.entries) {
              final conversations = entry.value;
              for (int i = 0; i < conversations.length; i++) {
                if (conversations[i].id == event.conversation!.id) {
                  foundDate = entry.key;
                  foundIndex = i;
                  break;
                }
              }
              if (foundDate != null) break;
            }

            if (foundDate != null && foundIndex != null) {
              // Use the same navigation pattern as Home page
              context
                  .read<ConversationDetailProvider>()
                  .updateConversation(foundIndex, foundDate);

              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (context) => ConversationDetailPage(
                    conversation: event.conversation!,
                  ),
                ),
              );
            } else {
              // Fallback: if conversation not found in provider, show error
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Unable to load conversation details'),
                  backgroundColor: Colors.red,
                ),
              );
            }
          }
        },
        child: Container(
          constraints: const BoxConstraints(maxWidth: 260),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.grey[900],
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey[700]!),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.2),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              // Timestamp
              Text(
                DateFormat('h:mm a').format(event.timestamp),
                style: TextStyle(
                  color: Colors.grey[400],
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 6),

              // Category tag and emoji
              Row(
                children: [
                  Text(
                    event.emoji,
                    style: const TextStyle(fontSize: 16),
                  ),
                  const SizedBox(width: 6),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: categoryColor,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      event.category.toUpperCase(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 9,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),

              // Title
              Text(
                event.title,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 4),

              // Summary
              Text(
                event.summary,
                style: TextStyle(
                  color: Colors.grey[300],
                  fontSize: 12,
                  height: 1.3,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),

              // Duration
              if (event.duration > 0) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    Icon(
                      FontAwesomeIcons.clock,
                      color: Colors.grey[500],
                      size: 10,
                    ),
                    const SizedBox(width: 3),
                    Text(
                      '${event.duration} min',
                      style: TextStyle(
                        color: Colors.grey[500],
                        fontSize: 10,
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class SwipeableEventStack extends StatefulWidget {
  final List<TimelineEvent> events;
  final bool isOnRight;
  final TimelineProvider timelineProvider;
  final double timePosition;
  final List<TimeMarkerInfo> timeMarkerPositions;

  const SwipeableEventStack({
    super.key,
    required this.events,
    required this.isOnRight,
    required this.timelineProvider,
    required this.timePosition,
    required this.timeMarkerPositions,
  });

  @override
  State<SwipeableEventStack> createState() => _SwipeableEventStackState();
}

class _SwipeableEventStackState extends State<SwipeableEventStack>
    with TickerProviderStateMixin {
  late PageController _pageController;
  int _currentIndex = 0;
  late AnimationController _dotAnimationController;

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
    _dotAnimationController = AnimationController(
      duration: const Duration(milliseconds: 300),
      vsync: this,
    );
  }

  @override
  void dispose() {
    _pageController.dispose();
    _dotAnimationController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.events.length == 1) {
      // Single event, use regular event widget
      return TimelineEventWithPositioning(
        event: widget.events[0],
        isOnRight: widget.isOnRight,
        timelineProvider: widget.timelineProvider,
        timePosition: widget.timePosition,
        timeMarkerPositions: widget.timeMarkerPositions,
      );
    }

    final categoryColor = Color(int.parse(
            widget.timelineProvider
                .getCategoryColor(widget.events[_currentIndex].category)
                .substring(1),
            radix: 16) +
        0xFF000000);

    // Calculate opacity based on overlap
    final dotOpacity = TimelineOverlapHelper.calculateDotOpacity(
        widget.timePosition, widget.timeMarkerPositions);

    return Row(
      children: [
        // Left side content
        if (!widget.isOnRight)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(
                  right: 18), // Slightly increased for consistency
              child: _buildSwipeableEventCard(Alignment.centerRight),
            ),
          )
        else
          Expanded(child: Container()),

        // Event dot on timeline with stack indicator
        Container(
          width: 60,
          margin: const EdgeInsets.only(
              left: 0), // Offset to align with shifted timeline
          child: Center(
            child: Opacity(
              opacity: dotOpacity,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  // Background dots for stack effect
                  if (widget.events.length > 1) ...[
                    Container(
                      width: 18,
                      height: 18,
                      decoration: BoxDecoration(
                        color: Colors.grey[600],
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.black, width: 1),
                      ),
                    ),
                    Container(
                      width: 16,
                      height: 16,
                      decoration: BoxDecoration(
                        color: Colors.grey[500],
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.black, width: 1),
                      ),
                    ),
                  ],
                  // Main dot
                  Container(
                    width: widget.events[_currentIndex].isImportant ? 16 : 12,
                    height: widget.events[_currentIndex].isImportant ? 16 : 12,
                    decoration: BoxDecoration(
                      color: categoryColor,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.black, width: 2),
                      boxShadow: widget.events[_currentIndex].isImportant
                          ? [
                              BoxShadow(
                                color: categoryColor.withOpacity(0.4),
                                blurRadius: 8,
                                spreadRadius: 2,
                              ),
                            ]
                          : null,
                    ),
                  ),
                  // Stack count indicator
                  if (widget.events.length > 1)
                    Positioned(
                      top: -8,
                      right: -8,
                      child: Container(
                        width: 16,
                        height: 16,
                        decoration: BoxDecoration(
                          color: Colors.deepPurple,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.black, width: 1),
                        ),
                        child: Center(
                          child: Text(
                            '${widget.events.length}',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 8,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),

        // Right side content
        if (widget.isOnRight)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(
                  left: 18), // Matched with right padding for consistency
              child: _buildSwipeableEventCard(Alignment.centerLeft),
            ),
          )
        else
          Expanded(child: Container()),
      ],
    );
  }

  Widget _buildSwipeableEventCard(Alignment alignment) {
    return Align(
      alignment: alignment,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 260),
        height: 160, // Fixed height for consistent swipe experience
        child: Stack(
          children: [
            // PageView for swipeable cards
            PageView.builder(
              controller: _pageController,
              onPageChanged: (index) {
                setState(() {
                  _currentIndex = index;
                });
                _dotAnimationController.forward().then((_) {
                  _dotAnimationController.reverse();
                });
              },
              itemCount: widget.events.length,
              itemBuilder: (context, index) {
                return _buildEventCard(widget.events[index], index);
              },
            ),

            // Page indicators
            if (widget.events.length > 1)
              Positioned(
                bottom: 8,
                left: 0,
                right: 0,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    // Swipe hint icon
                    Icon(
                      Icons.swipe_left,
                      color: Colors.grey[500],
                      size: 12,
                    ),
                    const SizedBox(width: 4),
                    // Page dots
                    ...List.generate(
                      widget.events.length,
                      (index) => Container(
                        margin: const EdgeInsets.symmetric(horizontal: 2),
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: index == _currentIndex
                              ? Colors.white
                              : Colors.grey[600],
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      Icons.swipe_right,
                      color: Colors.grey[500],
                      size: 12,
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildEventCard(TimelineEvent event, int index) {
    final categoryColor = Color(int.parse(
            widget.timelineProvider
                .getCategoryColor(event.category)
                .substring(1),
            radix: 16) +
        0xFF000000);

    return GestureDetector(
      onTap: () => _navigateToConversation(event),
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.grey[900],
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: index == _currentIndex ? categoryColor : Colors.grey[700]!,
            width: index == _currentIndex ? 2 : 1,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.2),
              blurRadius: 6,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // Timestamp
            Text(
              DateFormat('h:mm a').format(event.timestamp),
              style: TextStyle(
                color: Colors.grey[400],
                fontSize: 11,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(height: 6),

            // Category tag and emoji
            Row(
              children: [
                Text(
                  event.emoji,
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(width: 6),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: categoryColor,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    event.category.toUpperCase(),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 9,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),

            // Title
            Text(
              event.title,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 4),

            // Summary
            Expanded(
              child: Text(
                event.summary,
                style: TextStyle(
                  color: Colors.grey[300],
                  fontSize: 12,
                  height: 1.3,
                ),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ),

            // Duration
            if (event.duration > 0) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  Icon(
                    FontAwesomeIcons.clock,
                    color: Colors.grey[500],
                    size: 10,
                  ),
                  const SizedBox(width: 3),
                  Text(
                    '${event.duration} min',
                    style: TextStyle(
                      color: Colors.grey[500],
                      fontSize: 10,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _navigateToConversation(TimelineEvent event) {
    if (event.conversation != null) {
      final conversationProvider = context.read<ConversationProvider>();
      DateTime? foundDate;
      int? foundIndex;

      for (var entry in conversationProvider.groupedConversations.entries) {
        final conversations = entry.value;
        for (int i = 0; i < conversations.length; i++) {
          if (conversations[i].id == event.conversation!.id) {
            foundDate = entry.key;
            foundIndex = i;
            break;
          }
        }
        if (foundDate != null) break;
      }

      if (foundDate != null && foundIndex != null) {
        context
            .read<ConversationDetailProvider>()
            .updateConversation(foundIndex, foundDate);

        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (context) => ConversationDetailPage(
              conversation: event.conversation!,
            ),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Unable to load conversation details'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }
}
