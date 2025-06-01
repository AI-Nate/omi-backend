import 'package:flutter/material.dart';
import 'package:font_awesome_flutter/font_awesome_flutter.dart';
import 'package:omi/backend/schema/memory.dart';
import 'package:omi/providers/home_provider.dart';
import 'package:omi/providers/memories_provider.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:omi/utils/ui_guidelines.dart';
import 'package:omi/widgets/extensions/functions.dart';
import 'package:provider/provider.dart';

import 'widgets/memory_edit_sheet.dart';
import 'widgets/memory_item.dart';
import 'widgets/memory_dialog.dart';
import 'widgets/memory_review_sheet.dart';
import 'widgets/memory_management_sheet.dart';

class MemoriesPage extends StatefulWidget {
  const MemoriesPage({super.key});

  @override
  State<MemoriesPage> createState() => MemoriesPageState();
}

class MemoriesPageState extends State<MemoriesPage>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  final TextEditingController _searchController = TextEditingController();
  MemoryCategory? _selectedCategory;
  final ScrollController _scrollController = ScrollController();

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    (() async {
      final provider = context.read<MemoriesProvider>();
      await provider.init();

      if (!mounted) return;
      final unreviewedMemories = provider.unreviewed;
      if (unreviewedMemories.isNotEmpty) {
        _showReviewSheet(context, unreviewedMemories, provider);
      }
    }).withPostFrameCallback();
  }

  void _filterByCategory(MemoryCategory? category) {
    setState(() {
      _selectedCategory = category;
    });
    context.read<MemoriesProvider>().setCategoryFilter(category);
  }

  Map<MemoryCategory, int> _getCategoryCounts(List<Memory> memories) {
    var counts = <MemoryCategory, int>{};
    for (var memory in memories) {
      counts[memory.category] = (counts[memory.category] ?? 0) + 1;
    }
    return counts;
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Consumer<MemoriesProvider>(
      builder: (context, provider, _) {
        return PopScope(
          canPop: true,
          child: Scaffold(
            backgroundColor: Theme.of(context).colorScheme.primary,
            body: provider.loading
                ? const Center(
                    child: CircularProgressIndicator(
                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                  ))
                : RefreshIndicator(
                    backgroundColor: Colors.black,
                    color: Colors.white,
                    onRefresh: () => provider.forceRefresh(),
                    child: CustomScrollView(
                      controller: _scrollController,
                      slivers: [
                        const SliverToBoxAdapter(child: SizedBox(height: 20)),
                        // Search Bar and Controls
                        SliverToBoxAdapter(
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
                            child: Row(
                              children: [
                                Consumer<HomeProvider>(
                                    builder: (context, home, child) {
                                  return Expanded(
                                    child: SizedBox(
                                      height: 44,
                                      child: SearchBar(
                                        hintText: 'Search memories',
                                        leading: const Padding(
                                          padding: EdgeInsets.only(left: 6.0),
                                          child: Icon(
                                              FontAwesomeIcons.magnifyingGlass,
                                              color: Colors.white70,
                                              size: 14),
                                        ),
                                        backgroundColor:
                                            WidgetStateProperty.all(
                                                AppStyles.backgroundSecondary),
                                        elevation: WidgetStateProperty.all(0),
                                        padding: WidgetStateProperty.all(
                                          const EdgeInsets.symmetric(
                                              horizontal: 12, vertical: 4),
                                        ),
                                        focusNode:
                                            home.memoriesSearchFieldFocusNode,
                                        controller: _searchController,
                                        trailing: provider
                                                .searchQuery.isNotEmpty
                                            ? [
                                                IconButton(
                                                  icon: const Icon(Icons.close,
                                                      color: Colors.white70,
                                                      size: 16),
                                                  padding: EdgeInsets.zero,
                                                  constraints:
                                                      const BoxConstraints(
                                                    minHeight: 36,
                                                    minWidth: 36,
                                                  ),
                                                  onPressed: () {
                                                    _searchController.clear();
                                                    provider.setSearchQuery('');
                                                    MixpanelManager()
                                                        .memorySearchCleared(
                                                            provider.memories
                                                                .length);
                                                  },
                                                )
                                              ]
                                            : null,
                                        hintStyle: WidgetStateProperty.all(
                                          TextStyle(
                                              color: AppStyles.textTertiary,
                                              fontSize: 14),
                                        ),
                                        textStyle: WidgetStateProperty.all(
                                          TextStyle(
                                              color: AppStyles.textPrimary,
                                              fontSize: 14),
                                        ),
                                        shape: WidgetStateProperty.all(
                                          RoundedRectangleBorder(
                                            borderRadius: BorderRadius.circular(
                                                AppStyles.radiusLarge),
                                          ),
                                        ),
                                        onChanged: (value) =>
                                            provider.setSearchQuery(value),
                                        onSubmitted: (value) {
                                          if (value.isNotEmpty) {
                                            MixpanelManager().memorySearched(
                                                value,
                                                provider
                                                    .filteredMemories.length);
                                          }
                                        },
                                      ),
                                    ),
                                  );
                                }),
                                const SizedBox(width: 8),
                                SizedBox(
                                  width: 44,
                                  height: 44,
                                  child: ElevatedButton(
                                    onPressed: () {
                                      _showMemoryManagementSheet(
                                          context, provider);
                                    },
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor:
                                          AppStyles.backgroundSecondary,
                                      foregroundColor: Colors.white,
                                      padding: EdgeInsets.zero,
                                      shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                    ),
                                    child: const Icon(FontAwesomeIcons.sliders,
                                        size: 16),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                SizedBox(
                                  width: 44,
                                  height: 44,
                                  child: ElevatedButton(
                                    onPressed: () {
                                      showMemoryDialog(context, provider);
                                      MixpanelManager()
                                          .memoriesPageCreateMemoryBtn();
                                    },
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor:
                                          AppStyles.backgroundSecondary,
                                      foregroundColor: Colors.white,
                                      padding: EdgeInsets.zero,
                                      shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                    ),
                                    child: const Icon(FontAwesomeIcons.plus,
                                        size: 18),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        // Review prompt header
                        if (provider.unreviewed.isNotEmpty)
                          SliverToBoxAdapter(
                            child: Material(
                              color:
                                  Theme.of(context).colorScheme.surfaceVariant,
                              elevation: 1,
                              child: InkWell(
                                onTap: () => _showReviewSheet(
                                    context, provider.unreviewed, provider),
                                child: Container(
                                  height: 56.0,
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 16.0),
                                  child: Row(
                                    mainAxisAlignment:
                                        MainAxisAlignment.spaceBetween,
                                    children: [
                                      Expanded(
                                        child: Row(
                                          children: [
                                            Icon(FontAwesomeIcons.listCheck,
                                                color: Theme.of(context)
                                                    .colorScheme
                                                    .onSurfaceVariant,
                                                size: 18),
                                            const SizedBox(width: 12),
                                            Flexible(
                                              child: Text(
                                                '${provider.unreviewed.length} ${provider.unreviewed.length == 1 ? "memory" : "memories"} to review',
                                                style: TextStyle(
                                                    color: Theme.of(context)
                                                        .colorScheme
                                                        .onSurfaceVariant,
                                                    fontWeight:
                                                        FontWeight.w500),
                                                overflow: TextOverflow.ellipsis,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                      Padding(
                                        padding:
                                            const EdgeInsets.only(left: 8.0),
                                        child: Text('Review',
                                            style: TextStyle(
                                                color: Theme.of(context)
                                                    .colorScheme
                                                    .primary,
                                                fontWeight: FontWeight.bold)),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ),
                        const SliverToBoxAdapter(child: SizedBox(height: 16)),
                        // Memory list or empty state
                        if (provider.filteredMemories.isEmpty)
                          SliverToBoxAdapter(
                            child: Center(
                              child: Padding(
                                padding: const EdgeInsets.all(32.0),
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Icon(Icons.note_add,
                                        size: 48, color: Colors.grey.shade600),
                                    const SizedBox(height: 16),
                                    Text(
                                      provider.searchQuery.isEmpty &&
                                              _selectedCategory == null
                                          ? 'No memories yet'
                                          : _selectedCategory != null
                                              ? 'No memories in this category'
                                              : 'No memories found',
                                      style: TextStyle(
                                        color: Colors.grey.shade400,
                                        fontSize: 18,
                                      ),
                                    ),
                                    if (provider.searchQuery.isEmpty &&
                                        _selectedCategory == null) ...[
                                      const SizedBox(height: 8),
                                      TextButton(
                                        onPressed: () =>
                                            showMemoryDialog(context, provider),
                                        child:
                                            const Text('Add your first memory'),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            ),
                          )
                        else
                          SliverList(
                            delegate: SliverChildBuilderDelegate(
                              (context, index) {
                                final memory = provider.filteredMemories[index];
                                return Padding(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 16.0, vertical: 4.0),
                                  child: MemoryItem(
                                    memory: memory,
                                    provider: provider,
                                    onTap: (BuildContext context,
                                        Memory tappedMemory,
                                        MemoriesProvider tappedProvider) {
                                      MixpanelManager()
                                          .memoryListItemClicked(tappedMemory);
                                      _showQuickEditSheet(context, tappedMemory,
                                          tappedProvider);
                                    },
                                  ),
                                );
                              },
                              childCount: provider.filteredMemories.length,
                            ),
                          ),
                        const SliverToBoxAdapter(child: SizedBox(height: 67)),
                      ],
                    ),
                  ),
          ),
        );
      },
    );
  }

  void _showQuickEditSheet(
      BuildContext context, Memory memory, MemoriesProvider provider) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) => MemoryEditSheet(
        memory: memory,
        provider: provider,
        onDelete: (_, __, ___) {},
      ),
    );
  }

  void _showReviewSheet(BuildContext context, List<Memory> memories,
      MemoriesProvider existingProvider) async {
    if (memories.isEmpty || !mounted) return;
    await showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isDismissible: true,
      enableDrag: false,
      isScrollControlled: true,
      builder: (sheetContext) {
        return ChangeNotifierProvider.value(
          value: existingProvider,
          child: MemoriesReviewSheet(
            memories: memories,
            provider: existingProvider,
          ),
        );
      },
    );
  }

  void _showDeleteAllConfirmation(
      BuildContext context, MemoriesProvider provider) {
    if (provider.memories.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No memories to delete'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: Colors.grey.shade900,
        title: const Text(
          'Clear Omi\'s Memory',
          style: TextStyle(color: Colors.white),
        ),
        content: Text(
          'Are you sure you want to clear Omi\'s memory? This action cannot be undone.',
          style: TextStyle(color: Colors.grey.shade300),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(
              'Cancel',
              style: TextStyle(color: Colors.grey.shade400),
            ),
          ),
          TextButton(
            onPressed: () {
              provider.deleteAllMemories();
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Omi\'s memory about you has been cleared'),
                  duration: Duration(seconds: 2),
                ),
              );
            },
            child: const Text(
              'Clear Memory',
              style: TextStyle(color: Colors.red),
            ),
          ),
        ],
      ),
    );
  }

  void _showMemoryManagementSheet(
      BuildContext context, MemoriesProvider provider) {
    MixpanelManager().memoriesManagementSheetOpened();
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) => MemoryManagementSheet(provider: provider),
    );
  }
}
