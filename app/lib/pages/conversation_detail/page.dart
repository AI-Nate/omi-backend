import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_provider_utilities/flutter_provider_utilities.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/backend/schema/person.dart';
import 'package:omi/pages/home/page.dart';
import 'package:omi/pages/conversation_detail/widgets.dart';
import 'package:omi/pages/settings/people.dart';
import 'package:omi/providers/connectivity_provider.dart';
import 'package:omi/providers/conversation_provider.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:omi/utils/other/temp.dart';
import 'package:omi/widgets/conversation_bottom_bar.dart';
import 'package:omi/widgets/expandable_text.dart';
import 'package:omi/widgets/extensions/string.dart';
import 'package:omi/widgets/photos_grid.dart';
import 'package:omi/widgets/transcript.dart';
import 'package:provider/provider.dart';
import 'package:tuple/tuple.dart';
import 'package:gradient_borders/box_borders/gradient_box_border.dart';

import 'conversation_detail_provider.dart';
import 'widgets/name_speaker_sheet.dart';
import 'widgets/enhanced_summary_section.dart';

class ConversationDetailPage extends StatefulWidget {
  final ServerConversation conversation;
  final bool isFromOnboarding;

  const ConversationDetailPage(
      {super.key, this.isFromOnboarding = false, required this.conversation});

  @override
  State<ConversationDetailPage> createState() => _ConversationDetailPageState();
}

class _ConversationDetailPageState extends State<ConversationDetailPage>
    with TickerProviderStateMixin {
  final scaffoldKey = GlobalKey<ScaffoldState>();
  final focusTitleField = FocusNode();
  final focusOverviewField = FocusNode();
  TabController? _controller;
  ConversationTab selectedTab = ConversationTab.summary;

  // TODO: use later for onboarding transcript segment edits
  // late AnimationController _animationController;
  // late Animation<double> _opacityAnimation;

  @override
  void initState() {
    super.initState();

    _controller = TabController(
        length: 3, vsync: this, initialIndex: 1); // Start with summary tab
    _controller!.addListener(() {
      setState(() {
        switch (_controller!.index) {
          case 0:
            selectedTab = ConversationTab.transcript;
            break;
          case 1:
            selectedTab = ConversationTab.summary;
            break;
          case 2:
            selectedTab = ConversationTab.actionItems;
            break;
          default:
            debugPrint('Invalid tab index: ${_controller!.index}');
            selectedTab = ConversationTab.summary;
        }
      });
    });

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        var provider =
            Provider.of<ConversationDetailProvider>(context, listen: false);

        // Set the conversation first to ensure it's available
        provider.setDirectConversation(widget.conversation);

        await provider.initConversation();
        if (provider.conversation.appResults.isEmpty) {
          await Provider.of<ConversationProvider>(context, listen: false)
              .updateSearchedConvoDetails(provider.conversation.id,
                  provider.selectedDate, provider.conversationIdx);
          provider.updateConversation(
              provider.conversationIdx, provider.selectedDate);
        }
      } catch (e, stackTrace) {
        debugPrint('Error initializing conversation: $e');
        debugPrint('Stack trace: $stackTrace');
        // Show a more specific error message
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  'Failed to load conversation details. Please try again.'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    });
    // _animationController = AnimationController(
    //   vsync: this,
    //   duration: const Duration(seconds: 60),
    // )..repeat(reverse: true);
    //
    // _opacityAnimation = Tween<double>(begin: 1.0, end: 0.5).animate(_animationController);

    super.initState();
  }

  @override
  void dispose() {
    _controller?.dispose();
    focusTitleField.dispose();
    focusOverviewField.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: true,
      child: MessageListener<ConversationDetailProvider>(
        showError: (error) {
          debugPrint('MessageListener received error: $error');
          if (error == 'REPROCESS_FAILED') {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text(
                    'Error while processing conversation. Please try again later.')));
          }
        },
        showInfo: (info) {
          debugPrint('MessageListener received info: $info');
        },
        child: Consumer<ConversationDetailProvider>(
          builder: (context, provider, child) {
            try {
              debugPrint('Building ConversationDetailPage UI');
              debugPrint('Conversation ID: ${provider.conversation.id}');
              debugPrint(
                  'Conversation title: ${provider.conversation.structured.title}');

              return Scaffold(
                key: scaffoldKey,
                extendBody: true,
                backgroundColor: Theme.of(context).colorScheme.primary,
                appBar: AppBar(
                  automaticallyImplyLeading: false,
                  backgroundColor: Theme.of(context).colorScheme.primary,
                  title: Consumer<ConversationDetailProvider>(
                      builder: (context, provider, child) {
                    try {
                      return Row(
                        mainAxisSize: MainAxisSize.max,
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        crossAxisAlignment: CrossAxisAlignment.center,
                        children: [
                          IconButton(
                            onPressed: () {
                              if (widget.isFromOnboarding) {
                                SchedulerBinding.instance
                                    .addPostFrameCallback((_) {
                                  Navigator.pushAndRemoveUntil(
                                      context,
                                      MaterialPageRoute(
                                          builder: (context) =>
                                              const HomePageWrapper()),
                                      (route) => false);
                                });
                              } else {
                                Navigator.pop(context);
                              }
                            },
                            icon: const Icon(Icons.arrow_back_rounded,
                                size: 24.0),
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: GestureDetector(
                              onTap: () {
                                if (provider.titleController != null &&
                                    provider.titleFocusNode != null) {
                                  provider.titleFocusNode!.requestFocus();
                                  // Select all text in the title field
                                  provider.titleController!.selection =
                                      TextSelection(
                                    baseOffset: 0,
                                    extentOffset:
                                        provider.titleController!.text.length,
                                  );
                                }
                              },
                              child: Text(
                                provider.structured.title,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 18),
                              ),
                            ),
                          ),
                          IconButton(
                            onPressed: () async {
                              await showModalBottomSheet(
                                context: context,
                                shape: const RoundedRectangleBorder(
                                  borderRadius: BorderRadius.only(
                                    topLeft: Radius.circular(16),
                                    topRight: Radius.circular(16),
                                  ),
                                ),
                                builder: (context) {
                                  return const ShowOptionsBottomSheet();
                                },
                              ).whenComplete(() {
                                provider.toggleShareOptionsInSheet(false);
                                provider.toggleDevToolsInSheet(false);
                              });
                            },
                            icon: const Icon(Icons.more_horiz),
                          ),
                        ],
                      );
                    } catch (e, stackTrace) {
                      debugPrint('Error building AppBar: $e');
                      debugPrint('AppBar Stack trace: $stackTrace');
                      // Return a fallback AppBar
                      return Row(
                        mainAxisSize: MainAxisSize.max,
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        crossAxisAlignment: CrossAxisAlignment.center,
                        children: [
                          IconButton(
                            onPressed: () => Navigator.pop(context),
                            icon: const Icon(Icons.arrow_back_rounded,
                                size: 24.0),
                          ),
                          const Expanded(
                            child: Text(
                              'Conversation',
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(fontSize: 18),
                            ),
                          ),
                          const SizedBox(
                              width: 48), // Placeholder for menu button
                        ],
                      );
                    }
                  }),
                ),
                // Removed floating action button as we now have the more button in the bottom bar
                body: SafeArea(
                  child: Stack(
                    children: [
                      Column(
                        children: [
                          Expanded(
                            child: Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 16),
                              child: Builder(builder: (context) {
                                try {
                                  debugPrint('Building TabBarView');
                                  return TabBarView(
                                    controller: _controller,
                                    physics:
                                        const NeverScrollableScrollPhysics(),
                                    children: [
                                      Selector<ConversationDetailProvider,
                                          ConversationSource?>(
                                        selector: (context, provider) =>
                                            provider.conversation?.source,
                                        builder: (context, source, child) {
                                          try {
                                            debugPrint(
                                                'Building transcript tab, source: $source');
                                            return source ==
                                                    ConversationSource.openglass
                                                ? ListView(
                                                    shrinkWrap: true,
                                                    children: const [
                                                        PhotosGridComponent(),
                                                        SizedBox(height: 32)
                                                      ])
                                                : const TranscriptWidgets();
                                          } catch (e, stackTrace) {
                                            debugPrint(
                                                'Error building transcript tab: $e');
                                            debugPrint(
                                                'Transcript tab stack trace: $stackTrace');
                                            return const Center(
                                              child: Text(
                                                'Error loading transcript',
                                                style: TextStyle(
                                                    color: Colors.white),
                                              ),
                                            );
                                          }
                                        },
                                      ),
                                      const SummaryTab(),
                                      const ActionItemsTab(),
                                    ],
                                  );
                                } catch (e, stackTrace) {
                                  debugPrint('Error building TabBarView: $e');
                                  debugPrint(
                                      'TabBarView stack trace: $stackTrace');
                                  return const Center(
                                    child: Text(
                                      'Error loading content',
                                      style: TextStyle(color: Colors.white),
                                    ),
                                  );
                                }
                              }),
                            ),
                          ),
                        ],
                      ),

                      // Floating bottom bar
                      Positioned(
                        bottom: 32,
                        left: 0,
                        right: 0,
                        child: Consumer<ConversationDetailProvider>(
                          builder: (context, provider, child) {
                            try {
                              final conversation = provider.conversation;
                              debugPrint('Building ConversationBottomBar');
                              return ConversationBottomBar(
                                mode: ConversationBottomBarMode.detail,
                                selectedTab: selectedTab,
                                hasSegments: conversation
                                        .transcriptSegments.isNotEmpty ||
                                    conversation.externalIntegration != null,
                                onTabSelected: (tab) {
                                  int index;
                                  switch (tab) {
                                    case ConversationTab.transcript:
                                      index = 0;
                                      break;
                                    case ConversationTab.summary:
                                      index = 1;
                                      break;
                                    case ConversationTab.actionItems:
                                      index = 2;
                                      break;
                                    default:
                                      debugPrint('Invalid tab selected: $tab');
                                      index = 1; // Default to summary tab
                                  }
                                  _controller!.animateTo(index);
                                },
                                onStopPressed: () {
                                  // Empty since we don't show the stop button in detail mode
                                },
                              );
                            } catch (e, stackTrace) {
                              debugPrint(
                                  'Error building ConversationBottomBar: $e');
                              debugPrint('BottomBar stack trace: $stackTrace');
                              return const SizedBox
                                  .shrink(); // Hide bottom bar if error
                            }
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              );
            } catch (e, stackTrace) {
              debugPrint('Error building ConversationDetailPage: $e');
              debugPrint('Main build stack trace: $stackTrace');
              // Return a fallback UI
              return Scaffold(
                backgroundColor: Theme.of(context).colorScheme.primary,
                appBar: AppBar(
                  title: const Text('Conversation'),
                  backgroundColor: Theme.of(context).colorScheme.primary,
                ),
                body: const Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.error_outline, size: 64, color: Colors.red),
                      SizedBox(height: 16),
                      Text(
                        'Error loading conversation details',
                        style: TextStyle(color: Colors.white, fontSize: 18),
                      ),
                      SizedBox(height: 8),
                      Text(
                        'Please check the debug logs for more information',
                        style: TextStyle(color: Colors.grey, fontSize: 14),
                      ),
                    ],
                  ),
                ),
              );
            }
          },
        ),
      ),
    );
  }
}

class SummaryTab extends StatelessWidget {
  const SummaryTab({super.key});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => FocusScope.of(context).unfocus(),
      child: Consumer<ConversationDetailProvider>(
        builder: (context, provider, child) {
          try {
            debugPrint('Building SummaryTab');
            debugPrint('Conversation ID: ${provider.conversation.id}');
            debugPrint(
                'Has enhanced summary: ${provider.hasEnhancedSummary()}');
            debugPrint(
                'Loading enhanced summary: ${provider.loadingEnhancedSummary}');
            debugPrint('Is discarded: ${provider.conversation.discarded}');

            return Selector<ConversationDetailProvider,
                Tuple4<bool, bool, Function(int), List<String>>>(
              selector: (context, provider) => Tuple4(
                  provider.conversation.discarded,
                  provider.showRatingUI,
                  provider.setConversationRating,
                  provider.conversation.structured.imageUrls),
              builder: (context, data, child) {
                try {
                  debugPrint('Building SummaryTab Selector');
                  // Get the most up-to-date conversation data
                  final provider = Provider.of<ConversationDetailProvider>(
                      context,
                      listen: true);
                  final conversationProvider =
                      Provider.of<ConversationProvider>(context, listen: true);

                  // Check if we need to refresh the conversation data
                  if (provider.conversation.appResults.isEmpty &&
                      provider.conversation.structured.overview
                          .trim()
                          .isNotEmpty) {
                    // If we have a structured overview but no app results, make sure the UI is updated
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      provider.notifyListeners();
                    });
                  } else if (provider.conversation.appResults.isNotEmpty) {
                    final summarizedApp = provider.getSummarizedApp();
                    if (summarizedApp != null &&
                        summarizedApp.content.trim().isEmpty) {
                      // If we have an empty summary, try to fetch updated data
                      WidgetsBinding.instance.addPostFrameCallback((_) async {
                        await conversationProvider.updateSearchedConvoDetails(
                            provider.conversation.id,
                            provider.selectedDate,
                            provider.conversationIdx);
                        provider.updateConversation(
                            provider.conversationIdx, provider.selectedDate);
                      });
                    }
                  }

                  return Stack(
                    children: [
                      ListView(
                        shrinkWrap: true,
                        controller: provider.summaryScrollController,
                        children: [
                          const GetSummaryWidgets(),

                          // Enhanced Summary Section
                          if (!data.item1 && provider.hasEnhancedSummary()) ...[
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              child: EnhancedSummarySection(
                                conversation: provider.conversation,
                                enhancedByImage:
                                    provider.hasImageEnhancedSummary(),
                              ),
                            ),
                            // Add space at the bottom but do not show the basic summary
                            const SizedBox(height: 150)
                          ] else if (!data.item1 &&
                              !provider.loadingEnhancedSummary &&
                              provider.conversation.structured.overview
                                  .isNotEmpty) ...[
                            // Show generate enriched summary button when no enhanced summary is available
                            const SizedBox(height: 8),
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              child: Center(
                                child: Container(
                                  decoration: BoxDecoration(
                                    border: const GradientBoxBorder(
                                      gradient: LinearGradient(colors: [
                                        Color.fromARGB(127, 208, 208, 208),
                                        Color.fromARGB(127, 188, 99, 121),
                                        Color.fromARGB(127, 86, 101, 182),
                                        Color.fromARGB(127, 126, 190, 236)
                                      ]),
                                      width: 2,
                                    ),
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: MaterialButton(
                                    onPressed: () async {
                                      await provider.fetchEnhancedSummary();
                                    },
                                    shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(8)),
                                    child: Padding(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 16, vertical: 8),
                                      child: Text(
                                        'Generate Enhanced Summary',
                                        style: TextStyle(
                                          color: Colors.white,
                                          fontSize: 16,
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                            // Show the basic summary below the generate button
                            data.item1
                                ? const ReprocessDiscardedWidget()
                                : const GetAppsWidgets(),
                            const SizedBox(height: 150)
                          ] else if (!data.item1 &&
                              provider.loadingEnhancedSummary) ...[
                            const SizedBox(height: 32),
                            const Center(
                              child: Column(
                                children: [
                                  CircularProgressIndicator(),
                                  SizedBox(height: 16),
                                  Text(
                                    'Generating enhanced summary...',
                                    style: TextStyle(color: Colors.white),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(height: 150)
                          ] else ...[
                            // For discarded conversations or if no summary exists at all
                            data.item1
                                ? const ReprocessDiscardedWidget()
                                : const GetAppsWidgets(),
                            const SizedBox(height: 150)
                          ],

                          // Show rating UI when needed
                          if (data.item2) // data.item2 is showRatingUI
                            ConversationRatingWidget(
                              setConversationRating: data
                                  .item3, // data.item3 is setConversationRating function
                            ),
                        ],
                      ),
                    ],
                  );
                } catch (e, stackTrace) {
                  debugPrint('Error building SummaryTab Selector: $e');
                  debugPrint('SummaryTab Selector stack trace: $stackTrace');
                  return const Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.error_outline, size: 48, color: Colors.red),
                        SizedBox(height: 16),
                        Text(
                          'Error loading summary',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ],
                    ),
                  );
                }
              },
            );
          } catch (e, stackTrace) {
            debugPrint('Error building SummaryTab: $e');
            debugPrint('SummaryTab stack trace: $stackTrace');
            return const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.error_outline, size: 48, color: Colors.red),
                  SizedBox(height: 16),
                  Text(
                    'Error loading summary content',
                    style: TextStyle(color: Colors.white, fontSize: 16),
                  ),
                ],
              ),
            );
          }
        },
      ),
    );
  }
}

class TranscriptWidgets extends StatelessWidget {
  const TranscriptWidgets({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<ConversationDetailProvider>(
      builder: (context, provider, child) {
        final segments = provider.conversation.transcriptSegments;

        if (segments.isEmpty) {
          return Padding(
            padding: const EdgeInsets.only(top: 32),
            child: ExpandableTextWidget(
              text: (provider.conversation.externalIntegration?.text ?? '')
                  .decodeString,
              maxLines: 1000,
              linkColor: Colors.grey.shade300,
              style: TextStyle(
                  color: Colors.grey.shade300, fontSize: 15, height: 1.3),
              toggleExpand: () {
                provider.toggleIsTranscriptExpanded();
              },
              isExpanded: provider.isTranscriptExpanded,
            ),
          );
        }

        // Use a Container with fixed height for large lists to enable proper scrolling
        return TranscriptWidget(
          segments: segments,
          horizontalMargin: false,
          topMargin: false,
          canDisplaySeconds: provider.canDisplaySeconds,
          isConversationDetail: true,
          bottomMargin: 200,
          editSegment: (i, j) {
            final connectivityProvider =
                Provider.of<ConnectivityProvider>(context, listen: false);
            if (!connectivityProvider.isConnected) {
              ConnectivityProvider.showNoInternetDialog(context);
              return;
            }
            showModalBottomSheet(
              context: context,
              isScrollControlled: true,
              backgroundColor: Colors.black,
              shape: const RoundedRectangleBorder(
                borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
              ),
              builder: (context) {
                return NameSpeakerBottomSheet(
                  speakerId: j,
                  segmentIdx: i,
                );
              },
            );
          },
        );
      },
    );
  }
}

class EditSegmentWidget extends StatelessWidget {
  final int segmentIdx;
  final List<Person> people;

  const EditSegmentWidget(
      {super.key, required this.segmentIdx, required this.people});

  @override
  Widget build(BuildContext context) {
    return Consumer<ConversationDetailProvider>(
        builder: (context, provider, child) {
      return Container(
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(16), topRight: Radius.circular(16)),
        ),
        height: 320,
        child: Stack(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 0),
              child: ListView(
                children: [
                  const SizedBox(height: 16),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16.0),
                    child: Row(
                      children: [
                        Text('Who\'s segment is this?',
                            style: Theme.of(context).textTheme.titleLarge),
                        const Spacer(),
                        TextButton(
                          onPressed: () {
                            MixpanelManager().unassignedSegment();
                            provider.unassignConversationTranscriptSegment(
                                provider.conversation.id, segmentIdx);
                            Navigator.pop(context);
                          },
                          child: const Text(
                            'Un-assign',
                            style: TextStyle(
                              color: Colors.grey,
                              decoration: TextDecoration.underline,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  CheckboxListTile(
                    title: const Text('Yours'),
                    value: provider
                        .conversation.transcriptSegments[segmentIdx].isUser,
                    checkboxShape: const RoundedRectangleBorder(
                        borderRadius: BorderRadius.all(Radius.circular(8))),
                    onChanged: (bool? value) async {
                      if (provider.editSegmentLoading) return;
                      // setModalState(() => loading = true);
                      provider.toggleEditSegmentLoading(true);
                      MixpanelManager().assignedSegment('User');
                      provider.conversation.transcriptSegments[segmentIdx]
                          .isUser = true;
                      provider.conversation.transcriptSegments[segmentIdx]
                          .personId = null;
                      bool result = await assignConversationTranscriptSegment(
                        provider.conversation.id,
                        segmentIdx,
                        isUser: true,
                        useForSpeechTraining:
                            SharedPreferencesUtil().hasSpeakerProfile,
                      );
                      try {
                        provider.toggleEditSegmentLoading(false);
                        Navigator.pop(context);
                        if (SharedPreferencesUtil().hasSpeakerProfile) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(result
                                  ? 'Segment assigned, and speech profile updated!'
                                  : 'Segment assigned, but speech profile failed to update. Please try again later.'),
                            ),
                          );
                        }
                      } catch (e) {}
                    },
                  ),
                  for (var person in people)
                    CheckboxListTile(
                      title: Text('${person.name}\'s'),
                      value: provider.conversation
                              .transcriptSegments[segmentIdx].personId ==
                          person.id,
                      checkboxShape: const RoundedRectangleBorder(
                          borderRadius: BorderRadius.all(Radius.circular(8))),
                      onChanged: (bool? value) async {
                        if (provider.editSegmentLoading) return;
                        provider.toggleEditSegmentLoading(true);
                        MixpanelManager().assignedSegment('User Person');
                        provider.conversation.transcriptSegments[segmentIdx]
                            .isUser = false;
                        provider.conversation.transcriptSegments[segmentIdx]
                            .personId = person.id;
                        bool result = await assignConversationTranscriptSegment(
                            provider.conversation.id, segmentIdx,
                            personId: person.id);
                        // TODO: make this un-closable or in a way that they receive the result
                        try {
                          provider.toggleEditSegmentLoading(false);
                          Navigator.pop(context);
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(result
                                  ? 'Segment assigned, and ${person.name}\'s speech profile updated!'
                                  : 'Segment assigned, but speech profile failed to update. Please try again later.'),
                            ),
                          );
                        } catch (e) {}
                      },
                    ),
                  ListTile(
                    title: const Text('Someone else\'s'),
                    trailing: const Padding(
                      padding: EdgeInsets.only(right: 8),
                      child: Icon(Icons.add),
                    ),
                    onTap: () {
                      Navigator.pop(context);
                      routeToPage(context, const UserPeoplePage());
                    },
                  ),
                ],
              ),
            ),
            if (provider.editSegmentLoading)
              Container(
                color: Colors.black.withOpacity(0.3),
                child: const Center(
                    child: CircularProgressIndicator(
                  valueColor: AlwaysStoppedAnimation(Colors.white),
                )),
              ),
          ],
        ),
      );
    });
  }
}

class ActionItemsTab extends StatelessWidget {
  const ActionItemsTab({super.key});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => FocusScope.of(context).unfocus(),
      child: Consumer<ConversationDetailProvider>(
        builder: (context, provider, child) {
          final hasActionItems = provider.conversation.structured.actionItems
              .where((item) => !item.deleted)
              .isNotEmpty;

          return ListView(
            shrinkWrap: true,
            children: [
              const SizedBox(height: 24),
              if (hasActionItems)
                const ActionItemsListWidget()
              else
                _buildEmptyState(context),
              const SizedBox(height: 150)
            ],
          );
        },
      ),
    );
  }

  Widget _buildEmptyState(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 40.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.check_circle_outline,
              size: 72,
              color: Colors.grey,
            ),
            const SizedBox(height: 24),
            Text(
              'No Action Items',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: Colors.white,
                  ),
            ),
            const SizedBox(height: 12),
            Text(
              'This memory doesn\'t have any action items yet. They\'ll appear here when your conversations include tasks or to-dos.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.grey.shade400,
                fontSize: 16,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
