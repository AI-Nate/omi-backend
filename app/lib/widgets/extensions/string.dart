import 'dart:convert';

extension StringExtensions on String {
  String get decodeString {
    try {
      return utf8.decode(codeUnits);
    } on Exception catch (_) {
      return this;
    }
  }

  /// Strip markdown formatting for clean text display in conversation previews
  String get stripMarkdown {
    String text = this;

    // Remove markdown headers (# ## ### etc.)
    text = text.replaceAll(RegExp(r'^#{1,6}\s+'), '');

    // Remove bold and italic formatting (**text** and *text*)
    text = text.replaceAll(RegExp(r'\*\*([^*]+)\*\*'), r'$1');
    text = text.replaceAll(RegExp(r'\*([^*]+)\*'), r'$1');

    // Remove underline formatting (__text__ and _text_)
    text = text.replaceAll(RegExp(r'__([^_]+)__'), r'$1');
    text = text.replaceAll(RegExp(r'_([^_]+)_'), r'$1');

    // Remove code blocks (```text```)
    text = text.replaceAll(RegExp(r'```[^`]*```'), '');

    // Remove inline code (`text`)
    text = text.replaceAll(RegExp(r'`([^`]+)`'), r'$1');

    // Remove links [text](url)
    text = text.replaceAll(RegExp(r'\[([^\]]+)\]\([^)]+\)'), r'$1');

    // Remove bullet points (- or *)
    text = text.replaceAll(RegExp(r'^[\s]*[-*]\s+', multiLine: true), '');

    // Remove numbered lists (1. 2. etc.)
    text = text.replaceAll(RegExp(r'^[\s]*\d+\.\s+', multiLine: true), '');

    // Remove blockquotes (>)
    text = text.replaceAll(RegExp(r'^>\s+', multiLine: true), '');

    // Clean up extra whitespace and newlines
    text = text.replaceAll(RegExp(r'\n+'), ' ');
    text = text.replaceAll(RegExp(r'\s+'), ' ');

    return text.trim();
  }

  String capitalize() {
    return isNotEmpty ? '${this[0].toUpperCase()}${substring(1)}' : '';
  }
}
