import 'dart:io';
import 'package:firebase_storage/firebase_storage.dart';
import 'package:flutter/foundation.dart';

class FirebaseStorageService {
  static final FirebaseStorageService _instance =
      FirebaseStorageService._internal();
  factory FirebaseStorageService() => _instance;
  FirebaseStorageService._internal();

  FirebaseStorage? _storage;

  /// Initialize Firebase Storage with the correct bucket
  void initialize({String? bucketName}) {
    try {
      if (bucketName != null) {
        _storage = FirebaseStorage.instanceFor(bucket: 'gs://$bucketName');
      } else {
        _storage = FirebaseStorage.instance;
      }
      debugPrint('Firebase Storage initialized successfully');
    } catch (e) {
      debugPrint('Failed to initialize Firebase Storage: $e');
    }
  }

  /// Get Firebase Storage instance
  FirebaseStorage get storage {
    if (_storage == null) {
      throw Exception(
          'Firebase Storage not initialized. Call initialize() first.');
    }
    return _storage!;
  }

  /// Get download URL for a Firebase Storage path
  Future<String?> getDownloadUrl(String path) async {
    try {
      final ref = storage.ref().child(path);
      final downloadUrl = await ref.getDownloadURL();
      debugPrint('Got download URL for path: $path');
      return downloadUrl;
    } catch (e) {
      debugPrint('Failed to get download URL for path $path: $e');
      return null;
    }
  }

  /// Get download URL from a full Firebase Storage URL
  /// Converts URLs like: https://storage.googleapis.com/bucket/path/file.jpg
  /// To the proper Firebase Storage reference and gets download URL
  Future<String?> getDownloadUrlFromStorageUrl(String storageUrl) async {
    try {
      debugPrint('Converting storage URL: $storageUrl');

      // Extract path from storage URL
      final uri = Uri.parse(storageUrl);
      if (uri.host == 'storage.googleapis.com') {
        // For URLs like: https://storage.googleapis.com/omi-how-to-learn-fd5fd.firebasestorage.app/SK0QVNGHWihPL2dixZF14SZSipA2/conversation_images/file.jpg
        // The bucket is in the first path segment, and the actual file path starts from the second segment
        final pathSegments = uri.pathSegments;
        if (pathSegments.isNotEmpty) {
          // Skip the bucket name (first segment) to get the file path
          final filePath = pathSegments.skip(1).join('/');
          debugPrint('Extracted file path: $filePath');

          if (filePath.isNotEmpty) {
            return await getDownloadUrl(filePath);
          }
        }
      } else if (uri.host.contains('firebasestorage.googleapis.com')) {
        // If it's already a Firebase download URL, return as is
        debugPrint('Already a Firebase download URL');
        return storageUrl;
      }

      // Fallback: return original URL
      debugPrint('Using original URL as fallback');
      return storageUrl;
    } catch (e) {
      debugPrint('Failed to convert storage URL to download URL: $e');
      return storageUrl; // Return original URL as fallback
    }
  }

  /// Upload an image file to Firebase Storage
  Future<String?> uploadImage({
    required File imageFile,
    required String userId,
    required String conversationId,
    String? customPath,
  }) async {
    try {
      final fileName =
          '${DateTime.now().millisecondsSinceEpoch}_${imageFile.path.split('/').last}';
      final path = customPath ??
          '$userId/conversation_images/${conversationId}_$fileName';

      final ref = storage.ref().child(path);
      final uploadTask = ref.putFile(imageFile);

      await uploadTask;
      final downloadUrl = await ref.getDownloadURL();

      debugPrint('Image uploaded successfully to: $path');
      return downloadUrl;
    } catch (e) {
      debugPrint('Failed to upload image: $e');
      return null;
    }
  }

  /// Delete an image from Firebase Storage
  Future<bool> deleteImage(String path) async {
    try {
      final ref = storage.ref().child(path);
      await ref.delete();
      debugPrint('Image deleted successfully: $path');
      return true;
    } catch (e) {
      debugPrint('Failed to delete image: $e');
      return false;
    }
  }

  /// Get metadata for a file in Firebase Storage
  Future<FullMetadata?> getMetadata(String path) async {
    try {
      final ref = storage.ref().child(path);
      return await ref.getMetadata();
    } catch (e) {
      debugPrint('Failed to get metadata for path $path: $e');
      return null;
    }
  }

  /// Check if a file exists in Firebase Storage
  Future<bool> fileExists(String path) async {
    try {
      final ref = storage.ref().child(path);
      await ref.getMetadata();
      return true;
    } catch (e) {
      return false;
    }
  }

  /// Get all images for a conversation
  Future<List<String>> getConversationImages({
    required String userId,
    required String conversationId,
  }) async {
    try {
      final path = '$userId/conversation_images/';
      final ref = storage.ref().child(path);
      final result = await ref.listAll();

      final List<String> imageUrls = [];
      for (final item in result.items) {
        if (item.name.contains(conversationId)) {
          try {
            final url = await item.getDownloadURL();
            imageUrls.add(url);
          } catch (e) {
            debugPrint('Failed to get download URL for ${item.name}: $e');
          }
        }
      }

      return imageUrls;
    } catch (e) {
      debugPrint('Failed to get conversation images: $e');
      return [];
    }
  }
}
