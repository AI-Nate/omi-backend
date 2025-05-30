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
  ServerConversation?
      _directConversation; // For conversations passed directly (e.g., from timeline)

  ServerConversation get conversation {
    // If we have a direct conversation (from timeline), use that
    if (_directConversation != null) {
      return _directConversation!;
    }

    // Otherwise, try to get from conversation provider
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

  void setDirectConversation(ServerConversation conversation) {
    _directConversation = conversation;

    // Clear image-related state when switching conversations
    isImageSummaryLoading = false;

    notifyListeners();
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

  bool isImageSummaryLoading = false;

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

    // Clear image-related state when switching conversations
    isImageSummaryLoading = false;

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

  // Method to check if the conversation has image-enhanced summary
  bool hasImageEnhancedSummary() {
    return conversation.structured.imageUrls.isNotEmpty;
  }

  // Method to handle adding an image to the summary
  Future<void> addImageToSummary() async {
    if (!isImageSummaryLoading && conversation != null) {
      try {
        isImageSummaryLoading = true;
        notifyListeners();

        final ImagePicker picker = ImagePicker();

        // Allow user to pick multiple images
        final List<XFile> images = await picker.pickMultiImage();

        if (images.isNotEmpty) {
          List<Uint8List> imagesData = [];

          // Read all selected images
          for (XFile image in images) {
            final Uint8List imageBytes = await image.readAsBytes();
            imagesData.add(imageBytes);
          }

          // Upload images to backend and get updated conversation
          final updatedConversation = await uploadAndProcessConversationImages(
              conversation!.id, imagesData);

          if (updatedConversation != null) {
            debugPrint(
                'PROVIDER DEBUG: Received updated conversation from backend');
            debugPrint(
                'PROVIDER DEBUG: Updated conversation has ${updatedConversation.structured.imageUrls.length} image URLs');
            debugPrint(
                'PROVIDER DEBUG: Image URLs: ${updatedConversation.structured.imageUrls}');

            // Update the conversation with the enhanced summary and image URLs
            // Update in the provider
            if (conversationProvider != null) {
              debugPrint('PROVIDER DEBUG: Updating conversation in provider');
              conversationProvider!.updateConversation(updatedConversation);
              debugPrint('PROVIDER DEBUG: Conversation updated in provider');
            }

            // Update the cached conversation reference
            debugPrint('PROVIDER DEBUG: Updating cached conversation');
            _cachedConversation = updatedConversation;
            debugPrint(
                'PROVIDER DEBUG: Cached conversation now has ${_cachedConversation!.structured.imageUrls.length} image URLs');

            notifyListeners();
            debugPrint('PROVIDER DEBUG: Listeners notified');

            debugPrint(
                'Successfully uploaded and processed ${images.length} images');
          } else {
            // Handle error
            debugPrint(
                'Failed to upload and process images - received null response');
          }
        }
      } catch (e) {
        debugPrint('Error in addImageToSummary: $e');
      } finally {
        isImageSummaryLoading = false;
        notifyListeners();
      }
    }
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
