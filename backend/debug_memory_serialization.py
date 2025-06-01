#!/usr/bin/env python3

"""
Debug script to test MemoryDB serialization and identify the user_review field issue.
"""

import os
import sys
import json
from datetime import datetime, timezone

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.memories import MemoryDB, Memory, MemoryCategory

def test_memory_serialization():
    """Test how MemoryDB objects are serialized to identify the user_review issue."""
    
    print("🔍 Testing MemoryDB Serialization...")
    print("=" * 50)
    
    # Create a test memory (like extracted from images)
    test_memory = Memory(
        content="Nathan values family traditions and cultural heritage.",
        category=MemoryCategory.core
    )
    
    # Create MemoryDB object (like auto-extracted memories)
    memory_db = MemoryDB.from_memory(
        memory=test_memory,
        uid="test_uid",
        conversation_id="test_conversation_id",
        manually_added=False  # This should create user_review=None
    )
    
    print(f"✅ Created MemoryDB object:")
    print(f"   - manually_added: {memory_db.manually_added}")
    print(f"   - reviewed: {memory_db.reviewed}")
    print(f"   - user_review: {memory_db.user_review}")
    print(f"   - user_review type: {type(memory_db.user_review)}")
    print()
    
    # Test different serialization methods
    print("🧪 Testing different serialization methods:")
    print("-" * 30)
    
    # Method 1: Pydantic .dict()
    dict_result = memory_db.dict()
    print(f"1. memory_db.dict():")
    print(f"   - user_review: {dict_result.get('user_review')}")
    print(f"   - user_review type: {type(dict_result.get('user_review'))}")
    print(f"   - user_review is None: {dict_result.get('user_review') is None}")
    print(f"   - user_review is False: {dict_result.get('user_review') is False}")
    print()
    
    # Method 2: Pydantic .dict(exclude_none=False)
    dict_exclude_none_false = memory_db.dict(exclude_none=False)
    print(f"2. memory_db.dict(exclude_none=False):")
    print(f"   - user_review: {dict_exclude_none_false.get('user_review')}")
    print(f"   - user_review type: {type(dict_exclude_none_false.get('user_review'))}")
    print(f"   - user_review is None: {dict_exclude_none_false.get('user_review') is None}")
    print()
    
    # Method 3: JSON serialization (what Firebase might do)
    json_str = memory_db.json()
    json_dict = json.loads(json_str)
    print(f"3. JSON serialization:")
    print(f"   - JSON string snippet: ...\"user_review\": {json_dict.get('user_review')}...")
    print(f"   - user_review: {json_dict.get('user_review')}")
    print(f"   - user_review type: {type(json_dict.get('user_review'))}")
    print(f"   - user_review is None: {json_dict.get('user_review') is None}")
    print()
    
    # Method 4: Manual dict construction
    manual_dict = {
        'id': memory_db.id,
        'uid': memory_db.uid,
        'content': memory_db.content,
        'category': memory_db.category.value,
        'manually_added': memory_db.manually_added,
        'reviewed': memory_db.reviewed,
        'user_review': memory_db.user_review,
        'created_at': memory_db.created_at,
        'updated_at': memory_db.updated_at,
        'conversation_id': memory_db.conversation_id,
    }
    print(f"4. Manual dict construction:")
    print(f"   - user_review: {manual_dict.get('user_review')}")
    print(f"   - user_review type: {type(manual_dict.get('user_review'))}")
    print(f"   - user_review is None: {manual_dict.get('user_review') is None}")
    print()
    
    # Test the backend filter logic
    print("🔍 Testing backend filter logic:")
    print("-" * 30)
    
    # Simulate the backend filter: memory['user_review'] is not False
    test_memories = [dict_result, dict_exclude_none_false, json_dict, manual_dict]
    
    for i, test_dict in enumerate(test_memories, 1):
        user_review_value = test_dict.get('user_review')
        should_include = user_review_value is not False
        print(f"Method {i}: user_review={user_review_value} -> Include: {should_include}")
    
    print()
    print("🎯 Summary:")
    print("-" * 10)
    print("If any method shows user_review as False (instead of None), that's the issue!")
    print("The backend filter 'memory['user_review'] is not False' will exclude it.")

if __name__ == "__main__":
    test_memory_serialization() 