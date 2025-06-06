import 'package:omi/widgets/extensions/string.dart';
import 'package:omi/backend/http/api/memories.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/memory.dart';
import 'package:omi/providers/base_provider.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:tuple/tuple.dart';
import 'package:uuid/uuid.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class MemoriesProvider extends ChangeNotifier {
  List<Memory> _memories = [];
  List<Memory> _unreviewed = [];
  bool _loading = true;
  String _searchQuery = '';
  MemoryCategory? _categoryFilter;
  List<Tuple2<MemoryCategory, int>> categories = [];
  MemoryCategory? selectedCategory;

  List<Memory> get memories => _memories;
  List<Memory> get unreviewed => _unreviewed;
  bool get loading => _loading;
  String get searchQuery => _searchQuery;
  MemoryCategory? get categoryFilter => _categoryFilter;

  List<Memory> get filteredMemories {
    return _memories.where((memory) {
      // Apply search filter
      final matchesSearch = _searchQuery.isEmpty ||
          memory.content.decodeString
              .toLowerCase()
              .contains(_searchQuery.toLowerCase());

      // Apply category filter
      final matchesCategory =
          _categoryFilter == null || memory.category == _categoryFilter;

      return matchesSearch && matchesCategory;
    }).toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
  }

  void setCategory(MemoryCategory? category) {
    selectedCategory = category;
    notifyListeners();
  }

  void setSearchQuery(String query) {
    _searchQuery = query.toLowerCase();
    notifyListeners();
  }

  void setCategoryFilter(MemoryCategory? category) {
    _categoryFilter = category;
    notifyListeners();
  }

  void _setCategories() {
    categories = MemoryCategory.values.map((category) {
      final count =
          memories.where((memory) => memory.category == category).length;
      return Tuple2(category, count);
    }).toList();
    notifyListeners();
  }

  Future<void> init() async {
    await loadMemories();
  }

  Future<void> forceRefresh() async {
    print('DEBUG: Force refreshing memories...');
    print('DEBUG: Current memories count before refresh: ${_memories.length}');
    print(
        'DEBUG: Current unreviewed count before refresh: ${_unreviewed.length}');
    print('DEBUG: Current loading state before refresh: $_loading');

    await loadMemories();

    print('DEBUG: Memories count after refresh: ${_memories.length}');
    print('DEBUG: Unreviewed count after refresh: ${_unreviewed.length}');
    print('DEBUG: Loading state after refresh: $_loading');

    notifyListeners();
    print('DEBUG: forceRefresh completed');
  }

  Future<void> loadMemories() async {
    _loading = true;
    notifyListeners();

    try {
      print('DEBUG: Starting to load memories...');
      _memories = await getMemories();
      print('DEBUG: Loaded ${_memories.length} total memories from API');

      // Safe filtering for recent memories
      final recentMemories = _memories.where((memory) {
        try {
          return memory.createdAt
              .isAfter(DateTime.now().subtract(const Duration(days: 7)));
        } catch (e) {
          print('DEBUG: Error checking memory date: $e');
          return false;
        }
      }).toList();

      print('DEBUG: Found ${recentMemories.length} memories from last 7 days');

      // Safe filtering for unreviewed memories
      _unreviewed = _memories.where((memory) {
        try {
          return !memory.reviewed &&
              memory.createdAt
                  .isAfter(DateTime.now().subtract(const Duration(days: 7)));
        } catch (e) {
          print('DEBUG: Error checking unreviewed memory: $e');
          return false;
        }
      }).toList();

      print('DEBUG: Found ${_unreviewed.length} unreviewed memories');
    } catch (e, stackTrace) {
      print('ERROR: Exception in loadMemories: $e');
      print('ERROR: Stack trace: $stackTrace');

      // Fallback to empty state
      _memories = [];
      _unreviewed = [];
    } finally {
      // Always ensure loading is set to false
      print('DEBUG: Setting _loading = false');
      _loading = false;
      _setCategories();
    }
  }

  void deleteMemory(Memory memory) async {
    await deleteMemoryServer(memory.id);
    _memories.remove(memory);
    _unreviewed.remove(memory);
    _setCategories();
  }

  void deleteAllMemories() async {
    final int countBeforeDeletion = _memories.length;
    await deleteAllMemoriesServer();
    _memories.clear();
    _unreviewed.clear();
    if (countBeforeDeletion > 0) {
      MixpanelManager().memoriesAllDeleted(countBeforeDeletion);
    }
    _setCategories();
  }

  void createMemory(String content,
      [MemoryVisibility visibility = MemoryVisibility.public,
      MemoryCategory category = MemoryCategory.core]) async {
    final newMemory = Memory(
      id: const Uuid().v4(),
      uid: SharedPreferencesUtil().uid,
      content: content,
      category: category,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      conversationId: null,
      reviewed: false,
      manuallyAdded: true,
      visibility: visibility,
    );

    await createMemoryServer(content, visibility.name);
    _memories.add(newMemory);
    _setCategories();
  }

  Future<void> updateMemoryVisibility(
      Memory memory, MemoryVisibility visibility) async {
    await updateMemoryVisibilityServer(memory.id, visibility.name);

    final idx = _memories.indexWhere((m) => m.id == memory.id);
    if (idx != -1) {
      Memory memoryToUpdate = _memories[idx];
      memoryToUpdate.visibility = visibility;
      _memories[idx] = memoryToUpdate;
      _unreviewed.removeWhere((m) => m.id == memory.id);

      MixpanelManager().memoryVisibilityChanged(memoryToUpdate, visibility);
      _setCategories();
    }
  }

  void editMemory(Memory memory, String value,
      [MemoryCategory? category]) async {
    await editMemoryServer(memory.id, value);

    final idx = _memories.indexWhere((m) => m.id == memory.id);
    if (idx != -1) {
      memory.content = value;
      if (category != null) {
        memory.category = category;
      }
      memory.updatedAt = DateTime.now();
      memory.edited = true;
      _memories[idx] = memory;

      // Remove from unreviewed if it was there
      final unreviewedIdx = _unreviewed.indexWhere((m) => m.id == memory.id);
      if (unreviewedIdx != -1) {
        _unreviewed.removeAt(unreviewedIdx);
      }

      _setCategories();
    }
  }

  void reviewMemory(Memory memory, bool approved, String source) async {
    MixpanelManager().memoryReviewed(memory, approved, source);

    await reviewMemoryServer(memory.id, approved);

    final idx = _memories.indexWhere((m) => m.id == memory.id);
    if (idx != -1) {
      memory.reviewed = true;
      memory.userReview = approved;

      if (!approved) {
        memory.deleted = true;
        _memories.removeAt(idx);
        _unreviewed.remove(memory);
        // Don't call deleteMemory again because it would be a duplicate deletion
      } else {
        _memories[idx] = memory;

        // Remove from unreviewed list
        final unreviewedIdx = _unreviewed.indexWhere((m) => m.id == memory.id);
        if (unreviewedIdx != -1) {
          _unreviewed.removeAt(unreviewedIdx);
        }
      }

      _setCategories();
    }
  }

  Future<void> updateAllMemoriesVisibility(bool makePrivate) async {
    final visibility =
        makePrivate ? MemoryVisibility.private : MemoryVisibility.public;
    int updatedCount = 0;
    List<Memory> memoriesSuccessfullyUpdated = [];

    for (var memory in List.from(_memories)) {
      if (memory.visibility != visibility) {
        try {
          await updateMemoryVisibilityServer(memory.id, visibility.name);
          final idx = _memories.indexWhere((m) => m.id == memory.id);
          if (idx != -1) {
            _memories[idx].visibility = visibility;
            memoriesSuccessfullyUpdated.add(_memories[idx]);
            updatedCount++;
          }
        } catch (e) {
          print('Failed to update visibility for memory ${memory.id}: $e');
        }
      }
    }

    if (updatedCount > 0) {
      MixpanelManager().memoriesAllVisibilityChanged(visibility, updatedCount);
    }

    _setCategories();
  }
}
