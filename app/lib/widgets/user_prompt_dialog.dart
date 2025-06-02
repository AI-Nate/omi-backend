import 'package:flutter/material.dart';

class UserPromptDialog extends StatefulWidget {
  final String title;
  final String hintText;
  final String? initialValue;
  final Function(String prompt) onSubmitted;
  final VoidCallback onCancelled;

  const UserPromptDialog({
    super.key,
    required this.title,
    required this.hintText,
    this.initialValue,
    required this.onSubmitted,
    required this.onCancelled,
  });

  @override
  State<UserPromptDialog> createState() => _UserPromptDialogState();
}

class _UserPromptDialogState extends State<UserPromptDialog> {
  late TextEditingController _controller;
  bool _isValid = false;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialValue ?? '');
    _isValid = _controller.text.trim().isNotEmpty;
    _controller.addListener(_onTextChanged);
  }

  void _onTextChanged() {
    setState(() {
      _isValid = _controller.text.trim().isNotEmpty;
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: Colors.grey[900],
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      child: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.title,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 20,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'Provide context or instructions to help generate more relevant events and insights:',
              style: TextStyle(
                color: Colors.grey,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 16),
            Container(
              decoration: BoxDecoration(
                color: Colors.grey[800],
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.grey[600]!),
              ),
              child: TextField(
                controller: _controller,
                style: const TextStyle(color: Colors.white),
                maxLines: 4,
                decoration: InputDecoration(
                  hintText: widget.hintText,
                  hintStyle: TextStyle(color: Colors.grey[400]),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.all(16),
                ),
                autofocus: true,
                onSubmitted: (_) {
                  if (_isValid) {
                    widget.onSubmitted(_controller.text.trim());
                  }
                },
              ),
            ),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: widget.onCancelled,
                  child: Text(
                    'Cancel',
                    style: TextStyle(color: Colors.grey[400]),
                  ),
                ),
                const SizedBox(width: 12),
                TextButton(
                  onPressed: () {
                    // Allow submission with empty prompt (skip)
                    widget.onSubmitted(_controller.text.trim());
                  },
                  child: Text(
                    'Skip',
                    style: TextStyle(color: Colors.grey[300]),
                  ),
                ),
                const SizedBox(width: 12),
                ElevatedButton(
                  onPressed: _isValid
                      ? () {
                          widget.onSubmitted(_controller.text.trim());
                        }
                      : null,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _isValid ? Colors.blue : Colors.grey[700],
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  child: const Text('Add Context'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Shows a user prompt dialog and returns the entered prompt
/// Returns empty string if skipped, null if cancelled
Future<String?> showUserPromptDialog({
  required BuildContext context,
  required String title,
  required String hintText,
  String? initialValue,
}) async {
  String? result;

  await showDialog<String>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext context) {
      return UserPromptDialog(
        title: title,
        hintText: hintText,
        initialValue: initialValue,
        onSubmitted: (prompt) {
          result = prompt;
          Navigator.of(context).pop();
        },
        onCancelled: () {
          result = null;
          Navigator.of(context).pop();
        },
      );
    },
  );

  return result;
}
