import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_provider_utilities/flutter_provider_utilities.dart';
import 'package:omi/backend/http/api/conversations.dart';
import 'package:omi/backend/http/api/users.dart';
import 'package:omi/backend/preferences.dart';
import 'package:omi/backend/schema/app.dart';
import 'package:omi/backend/schema/conversation.dart';
import 'package:omi/backend/schema/structured.dart';
import 'package:omi/backend/schema/transcript_segment.dart';
import 'package:omi/providers/app_provider.dart';
import 'package:omi/providers/conversation_provider.dart';
import 'package:omi/utils/analytics/mixpanel.dart';
import 'package:instabug_flutter/instabug_flutter.dart';
import 'package:tuple/tuple.dart';
import 'package:image_picker/image_picker.dart';
import 'package:omi/backend/http/openai.dart'; // For getPhotoDescription
import 'package:omi/backend/http/api/apps.dart';

class ConversationDetailProvider extends ChangeNotifier
    with MessageNotifierMixin {
  AppProvider? appProvider;
  ConversationProvider? conversationProvider;

  // late ServerConversation memory;

  int conversationIdx = 0;
  DateTime selectedDate = DateTime.now();

  bool isLoading = false;
  bool loadingReprocessConversation = false;
  bool loadingEnhancedSummary = false;
  bool loadingImageAnalysis = false;
  String reprocessConversationId = '';
  App? selectedAppForReprocessing;

  final scaffoldKey = GlobalKey<ScaffoldState>();
  List<App> get appsList => appProvider?.apps ?? [];

  Structured get structured {
    return conversation.structured;
  }

  ServerConversation? _cachedConversation;
  ServerConversation get conversation {
    if (conversationProvider == null ||
        !conversationProvider!.groupedConversations.containsKey(selectedDate) ||
        conversationProvider!.groupedConversations[selectedDate] == null ||
        conversationProvider!.groupedConversations[selectedDate]!.length <=
            conversationIdx) {
      // Return cached conversation if available, otherwise create an empty one
      if (_cachedConversation == null) {
        throw StateError("No conversation available");
      }
      return _cachedConversation!;
    }
    _cachedConversation = conversationProvider!
        .groupedConversations[selectedDate]![conversationIdx];
    return _cachedConversation!;
  }

  List<bool> appResponseExpanded = [];

  TextEditingController? titleController;
  FocusNode? titleFocusNode;

  bool isTranscriptExpanded = false;

  bool canDisplaySeconds = true;

  bool hasAudioRecording = false;

  List<ConversationPhoto> photos = [];
  List<Tuple2<String, String>> photosData = [];

  bool displayDevToolsInSheet = false;
  bool displayShareOptionsInSheet = false;

  bool editSegmentLoading = false;

  bool showUnassignedFloatingButton = true;

  // Image analysis data
  List<Uint8List> summaryImageDataList = [];
  List<String> summaryImageDescriptions = [];
  bool hasImageEnhancedSummary = false;

  // ScrollController for the summary page
  final ScrollController summaryScrollController = ScrollController();

  void toggleEditSegmentLoading(bool value) {
    editSegmentLoading = value;
    notifyListeners();
  }

  void setShowUnassignedFloatingButton(bool value) {
    showUnassignedFloatingButton = value;
    notifyListeners();
  }

  Future populatePhotosData() async {
    if (photos.isEmpty) return;
    // photosData = await compute<List<MemoryPhoto>, List<Tuple2<String, String>>>(
    //   (photos) => photos.map((e) => Tuple2(e.base64, e.description)).toList(),
    //   photos,
    // );
    photosData = photos.map((e) => Tuple2(e.base64, e.description)).toList();
    notifyListeners();
  }

  void toggleIsTranscriptExpanded() {
    isTranscriptExpanded = !isTranscriptExpanded;
    notifyListeners();
  }

  void toggleDevToolsInSheet(bool value) {
    displayDevToolsInSheet = value;
    notifyListeners();
  }

  void toggleShareOptionsInSheet(bool value) {
    displayShareOptionsInSheet = value;
    notifyListeners();
  }

  void setProviders(
      AppProvider provider, ConversationProvider conversationProvider) {
    this.conversationProvider = conversationProvider;
    appProvider = provider;
    notifyListeners();
  }

  updateLoadingState(bool loading) {
    isLoading = loading;
    notifyListeners();
  }

  updateReprocessConversationLoadingState(bool loading) {
    loadingReprocessConversation = loading;
    if (!loading) {
      selectedAppForReprocessing = null;
    }
    notifyListeners();
  }

  void setSelectedAppForReprocessing(App app) {
    selectedAppForReprocessing = app;
    notifyListeners();
  }

  void clearSelectedAppForReprocessing() {
    selectedAppForReprocessing = null;
    notifyListeners();
  }

  void updateReprocessConversationId(String id) {
    reprocessConversationId = id;
    notifyListeners();
  }

  void updateConversation(int memIdx, DateTime date) {
    conversationIdx = memIdx;
    selectedDate = date;
    appResponseExpanded = List.filled(conversation.appResults.length, false);
    notifyListeners();
  }

  void updateEventState(bool state, int i) {
    conversation.structured.events[i].created = state;
    notifyListeners();
  }

  void updateActionItemState(bool state, int i) {
    conversation.structured.actionItems[i].completed = state;
    notifyListeners();
  }

  List<ActionItem> deletedActionItems = [];

  void deleteActionItem(int i) {
    deletedActionItems.add(conversation.structured.actionItems[i]);
    conversation.structured.actionItems.removeAt(i);
    notifyListeners();
  }

  void undoDeleteActionItem(int idx) {
    conversation.structured.actionItems
        .insert(idx, deletedActionItems.removeLast());
    notifyListeners();
  }

  void deleteActionItemPermanently(ActionItem item, int itemIdx) {
    deletedActionItems.removeWhere((element) => element == item);
    deleteConversationActionItem(conversation.id, item);
    notifyListeners();
  }

  void updateAppResponseExpanded(int index) {
    appResponseExpanded[index] = !appResponseExpanded[index];
    notifyListeners();
  }

  bool hasConversationSummaryRatingSet = false;
  Timer? _ratingTimer;
  bool showRatingUI = false;

  void setShowRatingUi(bool value) {
    showRatingUI = value;
    notifyListeners();
  }

  void setConversationRating(int value) {
    try {
      debugPrint(
          'setConversationRating called with value: $value for conversation: ${conversation.id}');
      setConversationSummaryRating(conversation.id, value);
      hasConversationSummaryRatingSet = true;
      setShowRatingUi(false);
      debugPrint('setConversationRating completed successfully');
    } catch (e, stackTrace) {
      debugPrint('Error in setConversationRating: $e');
      debugPrint('Stack trace: $stackTrace');
      rethrow;
    }
  }

  Future initConversation() async {
    // updateLoadingState(true);
    titleController?.dispose();
    titleFocusNode?.dispose();
    _ratingTimer?.cancel();
    showRatingUI = false;
    hasConversationSummaryRatingSet = false;

    titleController = TextEditingController();
    titleFocusNode = FocusNode();

    showUnassignedFloatingButton = true;

    titleController!.text = conversation.structured.title;
    titleFocusNode!.addListener(() {
      print('titleFocusNode focus changed');
      if (!titleFocusNode!.hasFocus) {
        conversation.structured.title = titleController!.text;
        updateConversationTitle(conversation.id, titleController!.text);
      }
    });

    photos = [];
    canDisplaySeconds =
        TranscriptSegment.canDisplaySeconds(conversation.transcriptSegments);
    if (conversation.source == ConversationSource.openglass) {
      await getConversationPhotos(conversation.id).then((value) async {
        photos = value;
        await populatePhotosData();
      });
    }
    if (!conversation.discarded) {
      getHasConversationSummaryRating(conversation.id).then((value) {
        hasConversationSummaryRatingSet = value;
        notifyListeners();
        if (!hasConversationSummaryRatingSet) {
          _ratingTimer = Timer(const Duration(seconds: 15), () {
            setConversationSummaryRating(
                conversation.id, -1); // set -1 to indicate is was shown
            showRatingUI = true;
            notifyListeners();
          });
        }
      });
    }

    // updateLoadingState(false);
    notifyListeners();
  }

  Future<bool> reprocessConversation({String? appId}) async {
    debugPrint('_reProcessConversation with appId: $appId');
    updateReprocessConversationLoadingState(true);
    updateReprocessConversationId(conversation.id);
    try {
      var updatedConversation =
          await reProcessConversationServer(conversation.id, appId: appId);
      MixpanelManager().reProcessConversation(conversation);
      updateReprocessConversationLoadingState(false);
      updateReprocessConversationId('');
      if (updatedConversation == null) {
        notifyError('REPROCESS_FAILED');
        notifyListeners();
        return false;
      }

      // else
      conversationProvider!.updateConversation(updatedConversation);
      SharedPreferencesUtil().modifiedConversationDetails = updatedConversation;

      // Check if the summarized app is in the apps list
      AppResponse? summaryApp = getSummarizedApp();
      if (summaryApp != null &&
          summaryApp.appId != null &&
          appProvider != null) {
        String appId = summaryApp.appId!;
        bool appExists = appProvider!.apps.any((app) => app.id == appId);
        if (!appExists) {
          await appProvider!.getApps();
        }
      }
      notifyInfo('REPROCESS_SUCCESS');
      notifyListeners();
      return true;
    } catch (err, stacktrace) {
      print(err);
      var conversationReporting =
          MixpanelManager().getConversationEventProperties(conversation);
      CrashReporting.reportHandledCrash(err, stacktrace,
          level: NonFatalExceptionLevel.critical,
          userAttributes: {
            'conversation_transcript_length':
                conversationReporting['transcript_length'].toString(),
            'conversation_transcript_word_count':
                conversationReporting['transcript_word_count'].toString(),
          });
      notifyError('REPROCESS_FAILED');
      updateReprocessConversationLoadingState(false);
      updateReprocessConversationId('');
      notifyListeners();
      return false;
    }
  }

  void unassignConversationTranscriptSegment(
      String conversationId, int segmentIdx) {
    conversation.transcriptSegments[segmentIdx].isUser = false;
    conversation.transcriptSegments[segmentIdx].personId = null;
    assignConversationTranscriptSegment(conversationId, segmentIdx);
    notifyListeners();
  }

  /// Returns the first app result from the conversation if available
  /// This is typically the summary of the conversation
  AppResponse? getSummarizedApp() {
    if (conversation.appResults.isNotEmpty) {
      return conversation.appResults[0];
    }
    return null;
  }

  void setPreferredSummarizationApp(String appId) {
    setPreferredSummarizationAppServer(appId);
    notifyListeners();
  }

  // Method to fetch enhanced summary for a conversation
  Future<bool> fetchEnhancedSummary() async {
    if (loadingEnhancedSummary) return false;

    loadingEnhancedSummary = true;
    notifyListeners();

    try {
      final enhancedConversation = await getEnhancedSummary(conversation.id);
      if (enhancedConversation != null) {
        // Update the conversation with enhanced summary data
        if (enhancedConversation.structured.keyTakeaways.isNotEmpty ||
            enhancedConversation.structured.thingsToImprove.isNotEmpty ||
            enhancedConversation.structured.thingsToLearn.isNotEmpty) {
          // Copy enriched fields to current conversation
          conversation.structured.keyTakeaways =
              enhancedConversation.structured.keyTakeaways;
          conversation.structured.thingsToImprove =
              enhancedConversation.structured.thingsToImprove;
          conversation.structured.thingsToLearn =
              enhancedConversation.structured.thingsToLearn;

          // Update in the provider
          if (conversationProvider != null) {
            conversationProvider!.updateConversation(conversation);
          }

          loadingEnhancedSummary = false;
          notifyListeners();
          return true;
        }
      }

      loadingEnhancedSummary = false;
      notifyListeners();
      return false;
    } catch (err) {
      debugPrint('Error fetching enhanced summary: $err');
      loadingEnhancedSummary = false;
      notifyListeners();
      return false;
    }
  }

  // Method to check if an enhanced summary is available
  bool hasEnhancedSummary() {
    return conversation.structured.keyTakeaways.isNotEmpty ||
        conversation.structured.thingsToImprove.isNotEmpty ||
        conversation.structured.thingsToLearn.isNotEmpty;
  }

  // Method to handle adding an image to the summary
  Future<void> addImageToSummary(BuildContext context) async {
    try {
      // Show image picker
      final pickedFile =
          await ImagePicker().pickImage(source: ImageSource.gallery);
      if (pickedFile == null) return;

      // Read file bytes
      final bytes = await pickedFile.readAsBytes();

      // Store the image data
      summaryImageDataList.add(bytes);

      // Set loading state
      loadingImageAnalysis = true;
      notifyListeners();

      // Show processing dialog with a clear message
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Analyzing image and enhancing summary...'),
            duration: Duration(seconds: 10),
          ),
        );
      }

      // Call API to analyze image and update summary
      // If this is the first image, use the single image API
      // If it's an additional image, use the multi-image API with all previous images
      final updatedConversation = summaryImageDataList.length == 1
          ? await analyzeImageAndUpdateSummary(conversation.id, bytes)
          : await analyzeImageAndUpdateSummary(
              conversation.id,
              bytes,
              additionalImages: summaryImageDataList.sublist(
                  0, summaryImageDataList.length - 1),
            );

      if (updatedConversation != null) {
        // Update conversation with enriched content (preserve existing image-related content)
        // For the first image, just replace the content
        if (summaryImageDataList.length == 1) {
          conversation.structured.overview =
              updatedConversation.structured.overview;
          conversation.structured.keyTakeaways =
              updatedConversation.structured.keyTakeaways;
          conversation.structured.thingsToImprove =
              updatedConversation.structured.thingsToImprove;
          conversation.structured.thingsToLearn =
              updatedConversation.structured.thingsToLearn;
        } else {
          // For subsequent images, intelligently merge the content to avoid duplication
          // Add new insights from the latest image analysis
          _mergeStructuredContent(updatedConversation.structured);
        }

        // Get the image description
        final imageDescription = await getPhotoDescription(bytes);
        summaryImageDescriptions.add(imageDescription);

        hasImageEnhancedSummary = true;

        // Update in the provider
        if (conversationProvider != null) {
          conversationProvider!.updateConversation(conversation);
        }

        // Show success message with more details
        if (context.mounted) {
          ScaffoldMessenger.of(context).clearSnackBars();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  'Summary enhanced with ${summaryImageDataList.length > 1 ? "additional " : ""}image content! ✨'),
              action: SnackBarAction(
                label: 'View',
                onPressed: () {
                  // Scroll to summary section
                  scrollToSummarySection(context);
                },
              ),
              duration: const Duration(seconds: 5),
              backgroundColor: Colors.green.shade700,
            ),
          );

          // Vibrate to indicate completion
          HapticFeedback.mediumImpact();
        }
      } else {
        // Remove the image data if processing failed
        if (summaryImageDataList.isNotEmpty) {
          summaryImageDataList.removeLast();
        }

        // Show error message
        if (context.mounted) {
          ScaffoldMessenger.of(context).clearSnackBars();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Failed to analyze image content'),
              backgroundColor: Colors.red.shade700,
              duration: const Duration(seconds: 3),
            ),
          );
        }
      }
    } catch (e) {
      debugPrint('Error adding image to summary: $e');
      // Remove the last image if there was an error
      if (summaryImageDataList.isNotEmpty) {
        summaryImageDataList.removeLast();
      }
      if (summaryImageDescriptions.isNotEmpty) {
        summaryImageDescriptions.removeLast();
      }

      // Show error message
      if (context.mounted) {
        ScaffoldMessenger.of(context).clearSnackBars();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Error processing image'),
            backgroundColor: Colors.red.shade700,
            duration: const Duration(seconds: 3),
          ),
        );
      }
    } finally {
      // Reset loading state
      loadingImageAnalysis = false;
      notifyListeners();
    }
  }

  // Helper method to merge new content with existing structured data
  void _mergeStructuredContent(Structured newContent) {
    // For overview, append new insights if they're not already present
    if (!conversation.structured.overview.contains(newContent.overview)) {
      conversation.structured.overview =
          '${conversation.structured.overview}\n\nAdditional insights from image: ${newContent.overview}';
    }

    // For key takeaways, add new ones that aren't duplicates
    for (var takeaway in newContent.keyTakeaways) {
      if (!_containsSimilarItem(
          conversation.structured.keyTakeaways, takeaway)) {
        conversation.structured.keyTakeaways.add(takeaway);
      }
    }

    // For things to improve, add new ones that aren't duplicates
    for (var improvement in newContent.thingsToImprove) {
      String content = improvement is ResourceItem
          ? improvement.content
          : improvement.toString();

      if (!_containsSimilarItem(
          conversation.structured.thingsToImprove, improvement)) {
        if (improvement is ResourceItem) {
          conversation.structured.thingsToImprove.add(improvement);
        } else {
          conversation.structured.thingsToImprove.add(ResourceItem(content));
        }
      }
    }

    // For things to learn, add new ones that aren't duplicates
    for (var learning in newContent.thingsToLearn) {
      String content =
          learning is ResourceItem ? learning.content : learning.toString();

      if (!_containsSimilarItem(
          conversation.structured.thingsToLearn, learning)) {
        if (learning is ResourceItem) {
          conversation.structured.thingsToLearn.add(learning);
        } else {
          conversation.structured.thingsToLearn.add(ResourceItem(content));
        }
      }
    }
  }

  // Helper to check if a similar item already exists
  bool _containsSimilarItem(List items, dynamic newItem) {
    if (items.isEmpty) return false;

    if (items[0] is String && newItem is String) {
      return items.any((item) =>
          item.toLowerCase().contains(newItem.toLowerCase()) ||
          newItem.toLowerCase().contains(item.toLowerCase()));
    } else if (items[0] is ResourceItem && newItem is ResourceItem) {
      return items.any((item) =>
          item.content.toLowerCase().contains(newItem.content.toLowerCase()) ||
          newItem.content.toLowerCase().contains(item.content.toLowerCase()));
    } else if (items[0] is ResourceItem && newItem is String) {
      return items.any((item) =>
          item.content.toLowerCase().contains(newItem.toLowerCase()) ||
          newItem.toLowerCase().contains(item.content.toLowerCase()));
    } else if (items[0] is String && newItem is ResourceItem) {
      return items.any((item) =>
          item.toLowerCase().contains(newItem.content.toLowerCase()) ||
          newItem.content.toLowerCase().contains(item.toLowerCase()));
    }

    return false;
  }

  // Helper method to scroll to summary section
  void scrollToSummarySection(BuildContext context) {
    if (summaryScrollController.hasClients) {
      // Scroll to bottom where the image is displayed
      summaryScrollController.animateTo(
        summaryScrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 500),
        curve: Curves.easeInOut,
      );
    } else {
      // Fallback message if we can't scroll
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Summary updated in Overview section ☝️'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }
}
