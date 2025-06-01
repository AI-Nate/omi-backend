import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:omi/services/firebase_storage_service.dart';

class FirebaseImageWidget extends StatefulWidget {
  final String storageUrl;
  final double? width;
  final double? height;
  final BoxFit fit;
  final Widget? placeholder;
  final Widget? errorWidget;
  final BorderRadius? borderRadius;

  const FirebaseImageWidget({
    Key? key,
    required this.storageUrl,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
    this.placeholder,
    this.errorWidget,
    this.borderRadius,
  }) : super(key: key);

  @override
  State<FirebaseImageWidget> createState() => _FirebaseImageWidgetState();
}

class _FirebaseImageWidgetState extends State<FirebaseImageWidget> {
  String? _downloadUrl;
  bool _isLoading = true;
  bool _hasError = false;

  @override
  void initState() {
    super.initState();
    _loadImage();
  }

  Future<void> _loadImage() async {
    try {
      setState(() {
        _isLoading = true;
        _hasError = false;
      });

      final url = await FirebaseStorageService()
          .getDownloadUrlFromStorageUrl(widget.storageUrl);

      if (mounted) {
        setState(() {
          _downloadUrl = url;
          _isLoading = false;
          _hasError = url == null;
        });
      }
    } catch (e) {
      debugPrint('Error loading Firebase image: $e');
      if (mounted) {
        setState(() {
          _isLoading = false;
          _hasError = true;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Container(
        width: widget.width,
        height: widget.height,
        decoration: BoxDecoration(
          color: Colors.grey[800],
          borderRadius: widget.borderRadius,
        ),
        child: widget.placeholder ??
            const Center(
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(Colors.grey),
              ),
            ),
      );
    }

    if (_hasError || _downloadUrl == null) {
      return Container(
        width: widget.width,
        height: widget.height,
        decoration: BoxDecoration(
          color: Colors.grey[800],
          borderRadius: widget.borderRadius,
        ),
        child: widget.errorWidget ??
            const Center(
              child: Icon(
                Icons.error_outline,
                color: Colors.red,
                size: 32,
              ),
            ),
      );
    }

    Widget imageWidget = CachedNetworkImage(
      imageUrl: _downloadUrl!,
      width: widget.width,
      height: widget.height,
      fit: widget.fit,
      placeholder: (context, url) =>
          widget.placeholder ??
          Container(
            color: Colors.grey[800],
            child: const Center(
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(Colors.grey),
              ),
            ),
          ),
      errorWidget: (context, url, error) =>
          widget.errorWidget ??
          Container(
            color: Colors.grey[800],
            child: const Center(
              child: Icon(
                Icons.error_outline,
                color: Colors.red,
                size: 32,
              ),
            ),
          ),
    );

    if (widget.borderRadius != null) {
      imageWidget = ClipRRect(
        borderRadius: widget.borderRadius!,
        child: imageWidget,
      );
    }

    return imageWidget;
  }
}

class FirebaseImageGallery extends StatelessWidget {
  final List<String> imageUrls;
  final double imageSize;
  final double spacing;
  final int crossAxisCount;

  const FirebaseImageGallery({
    Key? key,
    required this.imageUrls,
    this.imageSize = 100,
    this.spacing = 8,
    this.crossAxisCount = 3,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    if (imageUrls.isEmpty) {
      return const SizedBox.shrink();
    }

    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: crossAxisCount,
        crossAxisSpacing: spacing,
        mainAxisSpacing: spacing,
        childAspectRatio: 1,
      ),
      itemCount: imageUrls.length,
      itemBuilder: (context, index) {
        return GestureDetector(
          onTap: () => _showFullImage(context, imageUrls, index),
          child: FirebaseImageWidget(
            storageUrl: imageUrls[index],
            width: imageSize,
            height: imageSize,
            borderRadius: BorderRadius.circular(8),
          ),
        );
      },
    );
  }

  void _showFullImage(
      BuildContext context, List<String> urls, int initialIndex) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (context) => _FullImageViewer(
          imageUrls: urls,
          initialIndex: initialIndex,
        ),
      ),
    );
  }
}

class _FullImageViewer extends StatefulWidget {
  final List<String> imageUrls;
  final int initialIndex;

  const _FullImageViewer({
    required this.imageUrls,
    this.initialIndex = 0,
  });

  @override
  State<_FullImageViewer> createState() => __FullImageViewerState();
}

class __FullImageViewerState extends State<_FullImageViewer> {
  late PageController _pageController;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _currentIndex = widget.initialIndex;
    _pageController = PageController(initialPage: widget.initialIndex);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: Text(
          '${_currentIndex + 1} of ${widget.imageUrls.length}',
          style: const TextStyle(color: Colors.white),
        ),
        iconTheme: const IconThemeData(color: Colors.white),
      ),
      body: PageView.builder(
        controller: _pageController,
        onPageChanged: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        itemCount: widget.imageUrls.length,
        itemBuilder: (context, index) {
          return InteractiveViewer(
            child: Center(
              child: FirebaseImageWidget(
                storageUrl: widget.imageUrls[index],
                fit: BoxFit.contain,
              ),
            ),
          );
        },
      ),
    );
  }
}
