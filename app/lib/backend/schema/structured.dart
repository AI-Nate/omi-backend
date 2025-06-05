import 'dart:convert';
import 'dart:math';

class Structured {
  int id = 0;

  String title;
  String overview;
  String emoji;
  String category;

  // New fields for enriched summary
  List<String> keyTakeaways = [];
  List<ResourceItem> thingsToImprove = [];
  List<ResourceItem> thingsToLearn = [];

  List<ActionItem> actionItems = [];

  List<Event> events = [];

  // Image URLs for images uploaded to Firebase Storage
  List<String> imageUrls = [];

  // Full agent analysis text with detailed insights
  String? agentAnalysis;

  Structured(this.title, this.overview,
      {this.id = 0,
      this.emoji = '',
      this.category = 'other',
      this.agentAnalysis});

  getEmoji() {
    try {
      if (emoji.isNotEmpty) return utf8.decode(emoji.toString().codeUnits);
      return ['🧠', '😎', '🧑‍💻', '🚀'][Random().nextInt(4)];
    } catch (e) {
      // return ['🧠', '😎', '🧑‍💻', '🚀'][Random(f).nextInt(4)];
      return emoji; // should return random?
    }
  }

  static Structured fromJson(Map<String, dynamic> json) {
    var structured = Structured(
      json['title'],
      json['overview'],
      emoji: json['emoji'],
      category: json['category'],
    );

    // Parse new summary enrichment fields
    if (json['keyTakeaways'] != null || json['key_takeaways'] != null) {
      final takeaways = json['keyTakeaways'] ?? json['key_takeaways'] ?? [];
      structured.keyTakeaways =
          (takeaways as List).map<String>((item) => item.toString()).toList();
    }

    if (json['thingsToImprove'] != null || json['things_to_improve'] != null) {
      final improvements =
          json['thingsToImprove'] ?? json['things_to_improve'] ?? [];
      structured.thingsToImprove =
          (improvements as List).map<ResourceItem>((item) {
        if (item is String) {
          return ResourceItem(item);
        } else {
          return ResourceItem.fromJson(item);
        }
      }).toList();
    }

    if (json['thingsToLearn'] != null || json['things_to_learn'] != null) {
      final learning = json['thingsToLearn'] ?? json['things_to_learn'] ?? [];
      structured.thingsToLearn = (learning as List).map<ResourceItem>((item) {
        if (item is String) {
          return ResourceItem(item);
        } else {
          return ResourceItem.fromJson(item);
        }
      }).toList();
    }

    var aItems = json['actionItems'] ?? json['action_items'];
    if (aItems != null) {
      for (dynamic item in aItems) {
        if (item.runtimeType == String) {
          if (item.isEmpty) continue;
          structured.actionItems.add(ActionItem(item));
        } else {
          structured.actionItems.add(ActionItem.fromJson(item));
        }
      }
    }

    if (json['events'] != null) {
      for (dynamic event in json['events']) {
        if (event.isEmpty) continue;
        structured.events.add(Event(
          event['title'],
          (event['startsAt'] ?? event['start']) is int
              ? DateTime.fromMillisecondsSinceEpoch(
                      (event['startsAt'] ?? event['start']) * 1000)
                  .toLocal()
              : DateTime.parse(event['startsAt'] ?? event['start']).toLocal(),
          event['duration'],
          description: event['description'] ?? '',
          created: event['created'] ?? false,
        ));
      }
    }

    // Parse image URLs
    if (json['imageUrls'] != null || json['image_urls'] != null) {
      final imageUrls = json['imageUrls'] ?? json['image_urls'] ?? [];
      structured.imageUrls =
          (imageUrls as List).map<String>((item) => item.toString()).toList();
    }

    // Parse agent analysis
    if (json['agentAnalysis'] != null || json['agent_analysis'] != null) {
      structured.agentAnalysis =
          json['agentAnalysis'] ?? json['agent_analysis'];
    }

    return structured;
  }

  @override
  String toString() {
    var str = '';
    str += '${getEmoji()} $title\n\n$overview\n\n'; // ($category)

    if (keyTakeaways.isNotEmpty) {
      str += 'Key Takeaways:\n';
      for (var item in keyTakeaways) {
        str += '- $item\n';
      }
      str += '\n';
    }

    if (thingsToImprove.isNotEmpty) {
      str += 'Things to Improve:\n';
      for (var item in thingsToImprove) {
        str += '- ${item.content}\n';
      }
      str += '\n';
    }

    if (thingsToLearn.isNotEmpty) {
      str += 'Things to Learn:\n';
      for (var item in thingsToLearn) {
        str += '- ${item.content}\n';
      }
      str += '\n';
    }

    if (actionItems.isNotEmpty) {
      str += 'Action Items:\n';
      for (var item in actionItems) {
        str += '- ${item.description}\n';
      }
    }
    if (events.isNotEmpty) {
      str += 'Events:\n';
      for (var event in events) {
        str +=
            '- ${event.title} (${event.startsAt.toLocal()} for ${event.duration} minutes)\n';
      }
    }
    return str.trim();
  }

  toJson() {
    return {
      'title': title,
      'overview': overview,
      'emoji': emoji,
      'category': category,
      'keyTakeaways': keyTakeaways,
      'thingsToImprove': thingsToImprove.map((item) => item.toJson()).toList(),
      'thingsToLearn': thingsToLearn.map((item) => item.toJson()).toList(),
      'actionItems': actionItems.map((item) => item.description).toList(),
      'events': events.map((event) => event.toJson()).toList(),
      'imageUrls': imageUrls,
      'agentAnalysis': agentAnalysis,
    };
  }
}

class ActionItem {
  int id = 0;

  String description;
  bool completed = false;
  bool deleted = false;

  ActionItem(this.description,
      {this.id = 0, this.completed = false, this.deleted = false});

  static fromJson(Map<String, dynamic> json) {
    return ActionItem(json['description'],
        completed: json['completed'] ?? false,
        deleted: json['deleted'] ?? false);
  }

  toJson() =>
      {'description': description, 'completed': completed, 'deleted': deleted};
}

class AppResponse {
  int id = 0;

  String? appId;
  String content;

  AppResponse(this.content, {this.id = 0, this.appId});

  toJson() => {'appId': appId, 'content': content};

  factory AppResponse.fromJson(Map<String, dynamic> json) {
    return AppResponse(json['content'], appId: json['appId'] ?? json['app_id']);
  }
}

class Event {
  int id = 0;

  String title;
  DateTime startsAt;
  int duration;

  String description;
  bool created = false;

  Event(this.title, this.startsAt, this.duration,
      {this.description = '', this.created = false, this.id = 0});

  toJson() {
    return {
      'title': title,
      'startsAt': startsAt.toUtc().toIso8601String(),
      'duration': duration,
      'description': description,
      'created': created,
    };
  }
}

class ConversationPhoto {
  int id = 0;

  String base64;
  String description;

  ConversationPhoto(this.base64, this.description, {this.id = 0});

  factory ConversationPhoto.fromJson(Map<String, dynamic> json) {
    return ConversationPhoto(json['base64'], json['description']);
  }

  toJson() {
    return {
      'base64': base64,
      'description': description,
    };
  }
}

class ResourceItem {
  String content;
  String url;
  String title;

  ResourceItem(this.content, {this.url = '', this.title = ''});

  static ResourceItem fromJson(Map<String, dynamic> json) {
    return ResourceItem(
      json['content'],
      url: json['url'] ?? '',
      title: json['title'] ?? '',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'content': content,
      'url': url,
      'title': title,
    };
  }
}
