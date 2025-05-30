import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/providers/conversation_provider.dart';

class TimelineEvent {
  final String id;
  final String title;
  final String summary;
  final DateTime timestamp;
  final String category;
  final String emoji;
  final bool isImportant;
  final int duration; // in minutes
  final ServerConversation? conversation;

  TimelineEvent({
    required this.id,
    required this.title,
    required this.summary,
    required this.timestamp,
    required this.category,
    required this.emoji,
    this.isImportant = false,
    this.duration = 30,
    this.conversation,
  });

  static TimelineEvent fromConversation(ServerConversation conversation) {
    // Calculate importance based on events, action items, or duration
    bool isImportant = conversation.structured.events.isNotEmpty ||
        conversation.structured.actionItems.isNotEmpty ||
        (conversation.finishedAt != null &&
            conversation.startedAt != null &&
            conversation.finishedAt!
                    .difference(conversation.startedAt!)
                    .inMinutes >
                60);

    // Calculate duration in minutes
    int duration = 30; // default
    if (conversation.finishedAt != null && conversation.startedAt != null) {
      duration = conversation.finishedAt!
          .difference(conversation.startedAt!)
          .inMinutes;
      if (duration <= 0) duration = 30;
    }

    return TimelineEvent(
      id: conversation.id,
      title: conversation.structured.title.isNotEmpty
          ? conversation.structured.title
          : 'Conversation',
      summary: conversation.structured.overview.isNotEmpty
          ? conversation.structured.overview
          : 'No summary available',
      timestamp: conversation.startedAt ?? conversation.createdAt,
      category: conversation.structured.category.toString().split('.').last,
      emoji: conversation.structured.emoji.isNotEmpty
          ? conversation.structured.emoji
          : '🧠',
      isImportant: isImportant,
      duration: duration,
      conversation: conversation,
    );
  }
}

class TimelineProvider extends ChangeNotifier {
  List<TimelineEvent> _events = [];
  String _searchQuery = '';
  List<String> _selectedCategories = [];
  ConversationProvider? _conversationProvider;

  List<TimelineEvent> get events => _filteredEvents();
  List<TimelineEvent> get allEvents => _events;
  String get searchQuery => _searchQuery;
  List<String> get selectedCategories => _selectedCategories;

  // Group events by date for better timeline organization
  Map<DateTime, List<TimelineEvent>> get groupedEvents {
    Map<DateTime, List<TimelineEvent>> grouped = {};
    for (var event in events) {
      DateTime dateKey = DateTime(
        event.timestamp.year,
        event.timestamp.month,
        event.timestamp.day,
      );
      if (!grouped.containsKey(dateKey)) {
        grouped[dateKey] = [];
      }
      grouped[dateKey]!.add(event);
    }

    // Sort events within each date by time
    grouped.forEach((date, events) {
      events.sort((a, b) => a.timestamp.compareTo(b.timestamp));
    });

    return grouped;
  }

  // Calculate the vertical position of an event within a day (0.0 to 1.0)
  double getTimePositionInDay(TimelineEvent event) {
    int hour = event.timestamp.hour;
    int minute = event.timestamp.minute;

    // Convert to total minutes from midnight
    int totalMinutes = hour * 60 + minute;

    // Calculate position as percentage of day (0.0 = midnight, 1.0 = end of day)
    return totalMinutes / (24 * 60);
  }

  // Get a list of sorted dates
  List<DateTime> get sortedDates {
    return groupedEvents.keys.toList()
      ..sort((a, b) => b.compareTo(a)); // Most recent first
  }

  // Group events that are close in time to handle overlapping
  List<List<TimelineEvent>> getGroupedEventsForDay(DateTime date) {
    List<TimelineEvent> eventsForDate = groupedEvents[date] ?? [];
    if (eventsForDate.isEmpty) return [];

    List<List<TimelineEvent>> groupedList = [];
    const double overlapThresholdHours =
        1.0; // Events within 1 hour are considered overlapping

    for (TimelineEvent event in eventsForDate) {
      bool addedToGroup = false;

      // Try to add to existing group if within threshold
      for (List<TimelineEvent> group in groupedList) {
        if (group.isNotEmpty) {
          // Check if this event is close enough to any event in the group
          bool isCloseToGroup = group.any((groupEvent) {
            double hoursDifference = event.timestamp
                    .difference(groupEvent.timestamp)
                    .inMinutes
                    .abs() /
                60.0;
            return hoursDifference <= overlapThresholdHours;
          });

          if (isCloseToGroup) {
            group.add(event);
            // Sort group by time
            group.sort((a, b) => a.timestamp.compareTo(b.timestamp));
            addedToGroup = true;
            break;
          }
        }
      }

      // If not added to any group, create new group
      if (!addedToGroup) {
        groupedList.add([event]);
      }
    }

    return groupedList;
  }

  // Calculate average time position for a group of events
  double getAverageTimePositionForGroup(List<TimelineEvent> eventGroup) {
    if (eventGroup.isEmpty) return 0.0;

    double totalPosition = 0.0;
    for (TimelineEvent event in eventGroup) {
      totalPosition += getTimePositionInDay(event);
    }

    return totalPosition / eventGroup.length;
  }

  List<String> get availableCategories {
    Set<String> categories = _events.map((e) => e.category).toSet();
    return categories.toList()..sort();
  }

  void setConversationProvider(ConversationProvider conversationProvider) {
    _conversationProvider = conversationProvider;
    _conversationProvider!.addListener(_onConversationsUpdated);
    _loadEventsFromProvider();
  }

  void _onConversationsUpdated() {
    _loadEventsFromProvider();
  }

  void _loadEventsFromProvider() {
    if (_conversationProvider == null) return;

    // Get all conversations from the conversation provider
    List<ServerConversation> allConversations = [];
    _conversationProvider!.groupedConversations.forEach((date, conversations) {
      allConversations.addAll(conversations);
    });

    // Filter only completed conversations and convert to timeline events
    _events = allConversations
        .where((conversation) =>
            conversation.status == ConversationStatus.completed)
        .map((conversation) => TimelineEvent.fromConversation(conversation))
        .toList();

    // Sort by timestamp (most recent first)
    _events.sort((a, b) => b.timestamp.compareTo(a.timestamp));

    notifyListeners();
  }

  TimelineProvider() {
    // Initial load will happen when conversation provider is set
  }

  List<TimelineEvent> _filteredEvents() {
    List<TimelineEvent> filtered = _events;

    // Apply search filter
    if (_searchQuery.isNotEmpty) {
      filtered = filtered.where((event) {
        return event.title.toLowerCase().contains(_searchQuery.toLowerCase()) ||
            event.summary.toLowerCase().contains(_searchQuery.toLowerCase()) ||
            event.category.toLowerCase().contains(_searchQuery.toLowerCase());
      }).toList();
    }

    // Apply category filter
    if (_selectedCategories.isNotEmpty) {
      filtered = filtered.where((event) {
        return _selectedCategories.contains(event.category);
      }).toList();
    }

    // Sort by timestamp (most recent first)
    filtered.sort((a, b) => b.timestamp.compareTo(a.timestamp));

    return filtered;
  }

  Future<void> refreshEvents() async {
    if (_conversationProvider != null) {
      await _conversationProvider!.getInitialConversations();
      // Events will be updated automatically via listener
    }
  }

  void updateSearchQuery(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  void toggleCategoryFilter(String category) {
    if (_selectedCategories.contains(category)) {
      _selectedCategories.remove(category);
    } else {
      _selectedCategories.add(category);
    }
    notifyListeners();
  }

  void clearFilters() {
    _searchQuery = '';
    _selectedCategories.clear();
    notifyListeners();
  }

  // Get color for category
  String getCategoryColor(String category) {
    Map<String, String> categoryColors = {
      'work': '#3B82F6',
      'business': '#3B82F6',
      'personal': '#10B981',
      'social': '#10B981',
      'education': '#8B5CF6',
      'health': '#F59E0B',
      'technology': '#EF4444',
      'entertainment': '#EC4899',
      'travel': '#06B6D4',
      'finance': '#84CC16',
      'family': '#F97316',
      'sports': '#14B8A6',
      'music': '#A855F7',
      'food': '#F59E0B',
    };
    return categoryColors[category.toLowerCase()] ?? '#6B7280';
  }

  @override
  void dispose() {
    _conversationProvider?.removeListener(_onConversationsUpdated);
    super.dispose();
  }
}
