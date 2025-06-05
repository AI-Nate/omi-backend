#!/usr/bin/env python3
"""
Quick script to check in-progress conversations in Firestore
"""
import sys
import os
sys.path.append('backend')

from database.conversations import get_conversations

def check_in_progress_conversations(uid):
    print(f"Checking in-progress conversations for user: {uid}")
    
    # Get conversations with in_progress status
    conversations = get_conversations(
        uid=uid, 
        statuses=['in_progress'],
        include_discarded=True,
        limit=100
    )
    
    print(f"Found {len(conversations)} in-progress conversations:")
    
    for i, conv in enumerate(conversations, 1):
        print(f"{i}. ID: {conv['id']}")
        print(f"   Created: {conv['created_at']}")
        print(f"   Status: {conv['status']}")
        print(f"   Discarded: {conv.get('discarded', 'N/A')}")
        print(f"   Title: {conv.get('structured', {}).get('title', 'N/A')}")
        print("   ---")
    
    return conversations

if __name__ == "__main__":
    # Your user ID from the logs
    user_id = "SK0QVNGHWihPL2dixZF14SZSipA2"
    check_in_progress_conversations(user_id) 