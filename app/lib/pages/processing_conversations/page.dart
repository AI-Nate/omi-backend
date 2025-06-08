import 'package:flutter/material.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/pages/capture/widgets/widgets.dart';
import 'package:omi/pages/conversation_detail/page.dart';
import 'package:omi/providers/conversation_provider.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:provider/provider.dart';

class ProcessingConversationPage extends StatefulWidget {
  final ServerConversation conversation;

  const ProcessingConversationPage({
    super.key,
    required this.conversation,
  });

  @override
  State<ProcessingConversationPage> createState() =>
      _ProcessingConversationPageState();
}

class _ProcessingConversationPageState extends State<ProcessingConversationPage>
    with TickerProviderStateMixin {
  final scaffoldKey = GlobalKey<ScaffoldState>();
  TabController? _controller;
  bool _isDeleting = false;

  @override
  void initState() {
    _controller = TabController(length: 2, vsync: this, initialIndex: 0);
    _controller!.addListener(() => setState(() {}));
    super.initState();
  }

  void _pushNewConversation(BuildContext context, conversation) async {
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (c) => ConversationDetailPage(
          conversation: conversation,
        ),
      ));
    });
  }

  void _deleteProcessingConversation() async {
    setState(() {
      _isDeleting = true;
    });

    try {
      // Clear the in-progress conversation from the backend
      bool success = await clearInProgressConversation();

      if (success) {
        // Remove the processing conversation from the provider
        if (mounted) {
          final provider =
              Provider.of<ConversationProvider>(context, listen: false);

          // Use the comprehensive cleanup method that handles all edge cases
          debugPrint(
              '🧹 PROCESSING_DELETE: Using comprehensive cleanup method');
          provider.clearAllProcessingConversations();

          // Refresh conversations from server to ensure backend and frontend are in sync
          debugPrint(
              '🔄 PROCESSING_DELETE: Refreshing conversations after clearing processing conversation');
          await provider.fetchConversations();

          // Show success message
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Processing conversation cleared successfully'),
                backgroundColor: Colors.green,
              ),
            );

            // Navigate back to home
            Navigator.of(context).pop();
          }
        }
      } else {
        // Show error message
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Failed to clear processing conversation'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    } catch (e) {
      // Show error message
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isDeleting = false;
        });
      }
    }
  }

  void _showDeleteDialog() {
    showDialog(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('Delete Processing Conversation'),
          content: const Text(
              'This conversation seems stuck in processing. Do you want to clear it and reset?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () {
                Navigator.of(context).pop();
                _deleteProcessingConversation();
              },
              style: TextButton.styleFrom(
                foregroundColor: Colors.red,
              ),
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<ConversationProvider>(builder: (context, provider, child) {
      // Track memory // FIXME
      // if (widget.memory.status == ServerProcessingMemoryStatus.done &&
      //     provider.memories.firstWhereOrNull((e) => e.id == widget.memory.memoryId) != null) {
      //   _pushNewMemory(context, provider.memories.firstWhereOrNull((e) => e.id == widget.memory.memoryId));
      // }

      // Conversation source
      var convoSource = ConversationSource.omi;
      return PopScope(
        canPop: true,
        child: Scaffold(
          key: scaffoldKey,
          backgroundColor: Theme.of(context).colorScheme.primary,
          appBar: AppBar(
            automaticallyImplyLeading: false,
            backgroundColor: Theme.of(context).colorScheme.primary,
            title: Row(
              mainAxisSize: MainAxisSize.max,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                IconButton(
                  onPressed: () {
                    Navigator.pop(context);
                    return;
                  },
                  icon: const Icon(Icons.arrow_back_rounded, size: 24.0),
                ),
                const SizedBox(width: 4),
                const Text("🎙️"),
                const SizedBox(width: 4),
                const Expanded(child: Text("In progress")),
                _isDeleting
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : IconButton(
                        onPressed: _showDeleteDialog,
                        icon: const Icon(Icons.delete_outline, size: 24.0),
                        tooltip: 'Clear stuck processing conversation',
                      ),
              ],
            ),
          ),
          body: Column(
            children: [
              TabBar(
                indicatorSize: TabBarIndicatorSize.label,
                isScrollable: false,
                padding: EdgeInsets.zero,
                indicatorPadding: EdgeInsets.zero,
                controller: _controller,
                labelStyle: Theme.of(context)
                    .textTheme
                    .titleLarge!
                    .copyWith(fontSize: 18),
                tabs: [
                  Tab(
                    text: convoSource == ConversationSource.openglass
                        ? 'Photos'
                        : convoSource == ConversationSource.screenpipe
                            ? 'Raw Data'
                            : 'Transcript',
                  ),
                  const Tab(text: 'Summary')
                ],
                indicator: BoxDecoration(
                    color: Colors.transparent,
                    borderRadius: BorderRadius.circular(16)),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: TabBarView(
                    controller: _controller,
                    physics: const NeverScrollableScrollPhysics(),
                    children: [
                      ListView(
                        shrinkWrap: true,
                        children: [
                          widget.conversation.transcriptSegments.isEmpty
                              ? const Column(
                                  children: [
                                    SizedBox(height: 80),
                                    Center(child: Text("No Transcript")),
                                  ],
                                )
                              : getTranscriptWidget(
                                  false,
                                  widget.conversation.transcriptSegments,
                                  [],
                                  null)
                        ],
                      ),
                      ListView(
                        shrinkWrap: true,
                        children: [
                          const SizedBox(height: 80),
                          Center(
                            child: Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 16.0),
                              child: Column(
                                children: [
                                  Text(
                                    widget.conversation.transcriptSegments
                                            .isEmpty
                                        ? "No summary"
                                        : "Processing",
                                    textAlign: TextAlign.center,
                                    style: const TextStyle(fontSize: 16),
                                  ),
                                  if (widget.conversation.transcriptSegments
                                      .isNotEmpty) ...[
                                    const SizedBox(height: 24),
                                    Text(
                                      "Taking longer than expected?",
                                      style: TextStyle(
                                        fontSize: 14,
                                        color: Colors.grey[600],
                                      ),
                                    ),
                                    const SizedBox(height: 16),
                                    _isDeleting
                                        ? const CircularProgressIndicator()
                                        : ElevatedButton.icon(
                                            onPressed: _showDeleteDialog,
                                            icon: const Icon(Icons.refresh,
                                                size: 20),
                                            label: const Text("Clear & Reset"),
                                            style: ElevatedButton.styleFrom(
                                              backgroundColor:
                                                  Colors.orange[100],
                                              foregroundColor:
                                                  Colors.orange[800],
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                horizontal: 20,
                                                vertical: 12,
                                              ),
                                            ),
                                          ),
                                  ],
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    });
  }
}
