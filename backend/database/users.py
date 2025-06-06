from datetime import datetime, timezone

from google.cloud.firestore_v1 import FieldFilter

from ._client import db, document_id_from_seed


def is_exists_user(uid: str):
    user_ref = db.collection('users').document(uid)
    if not user_ref.get().exists:
        return False
    return True


def get_user_store_recording_permission(uid: str):
    user_ref = db.collection('users').document(uid)
    user_data = user_ref.get().to_dict()
    return user_data.get('store_recording_permission', False)


def set_user_store_recording_permission(uid: str, value: bool):
    user_ref = db.collection('users').document(uid)
    user_ref.update({'store_recording_permission': value})


def create_person(uid: str, data: dict):
    people_ref = db.collection('users').document(uid).collection('people')
    people_ref.document(data['id']).set(data)
    return data


def get_person(uid: str, person_id: str):
    person_ref = db.collection('users').document(uid).collection('people').document(person_id)
    person_data = person_ref.get().to_dict()
    return person_data


def get_people(uid: str):
    people_ref = (
        db.collection('users').document(uid).collection('people')
        .where(filter=FieldFilter('deleted', '==', False))
    )
    people = people_ref.stream()
    return [person.to_dict() for person in people]


def update_person(uid: str, person_id: str, name: str):
    person_ref = db.collection('users').document(uid).collection('people').document(person_id)
    person_ref.update({'name': name})


def delete_person(uid: str, person_id: str):
    person_ref = db.collection('users').document(uid).collection('people').document(person_id)
    person_ref.update({'deleted': True})


def delete_user_data(uid: str):
    # TODO: why dont we delete the whole document ref here?
    user_ref = db.collection('users').document(uid)
    conversations_ref = user_ref.collection('memories')
    # delete all conversations
    batch = db.batch()
    for doc in conversations_ref.stream():
        batch.delete(doc.reference)
    batch.commit()
    # delete chat messages
    messages_ref = user_ref.collection('messages')
    batch = db.batch()
    for doc in messages_ref.stream():
        batch.delete(doc.reference)
    batch.commit()
    # delete memories
    batch = db.batch()
    memories_ref = user_ref.collection('facts')
    for doc in memories_ref.stream():
        batch.delete(doc.reference)
    batch.commit()
    # delete processing conversations
    processing_conversations_ref = user_ref.collection('processing_memories')
    batch = db.batch()
    for doc in processing_conversations_ref.stream():
        batch.delete(doc.reference)
    batch.commit()
    # delete user
    user_ref.delete()
    return {'status': 'ok', 'message': 'Account deleted successfully'}


# **************************************
# ************* Analytics **************
# **************************************

def set_conversation_summary_rating_score(uid: str, conversation_id: str, value: int):
    doc_id = document_id_from_seed('memory_summary' + conversation_id)
    db.collection('analytics').document(doc_id).set({
        'id': doc_id,
        'memory_id': conversation_id,
        'uid': uid,
        'value': value,
        'created_at': datetime.now(timezone.utc),
        'type': 'memory_summary',
    })


def get_conversation_summary_rating_score(conversation_id: str):
    doc_id = document_id_from_seed('memory_summary' + conversation_id)
    doc_ref = db.collection('analytics').document(doc_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None


def get_all_ratings(rating_type: str = 'memory_summary'):
    ratings = db.collection('analytics').where('type', '==', rating_type).stream()
    return [rating.to_dict() for rating in ratings]


def set_chat_message_rating_score(uid: str, message_id: str, value: int):
    doc_id = document_id_from_seed('chat_message' + message_id)
    db.collection('analytics').document(doc_id).set({
        'id': doc_id,
        'message_id': message_id,
        'uid': uid,
        'value': value,
        'created_at': datetime.now(timezone.utc),
        'type': 'chat_message',
    })


# **************************************
# ************** Payments **************
# **************************************

def get_stripe_connect_account_id(uid: str):
    user_ref = db.collection('users').document(uid)
    user_data = user_ref.get().to_dict()
    return user_data.get('stripe_account_id', None)


def set_stripe_connect_account_id(uid: str, account_id: str):
    user_ref = db.collection('users').document(uid)
    user_ref.update({'stripe_account_id': account_id})


def set_paypal_payment_details(uid: str, data: dict):
    user_ref = db.collection('users').document(uid)
    user_ref.update({'paypal_details': data})


def get_paypal_payment_details(uid: str):
    user_ref = db.collection('users').document(uid)
    user_data = user_ref.get().to_dict()
    return user_data.get('paypal_details', None)


def set_default_payment_method(uid: str, payment_method_id: str):
    user_ref = db.collection('users').document(uid)
    user_ref.update({'default_payment_method': payment_method_id})


def get_default_payment_method(uid: str):
    user_ref = db.collection('users').document(uid)
    user_data = user_ref.get().to_dict()
    return user_data.get('default_payment_method', None)

# **************************************
# ************* Language ***************
# **************************************

def get_user_language_preference(uid: str) -> str:
    """
    Get the user's preferred language.
    
    Args:
        uid: User ID
        
    Returns:
        Language code (e.g., 'en', 'vi') or empty string if not set
    """
    user_ref = db.collection('users').document(uid)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        user_data = user_doc.to_dict()
        return user_data.get('language', '')
    
    return ''  # Return empty string if not set


def set_user_language_preference(uid: str, language: str) -> None:
    """
    Set the user's preferred language.
    
    Args:
        uid: User ID
        language: Language code (e.g., 'en', 'vi')
    """
    user_ref = db.collection('users').document(uid)
    user_ref.set({'language': language}, merge=True)


def get_user_name(uid: str) -> str:
    """
    Get the user's name.
    
    Args:
        uid: User ID
        
    Returns:
        User's name or 'User' as default
    """
    user_ref = db.collection('users').document(uid)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        user_data = user_doc.to_dict()
        # Try different possible name fields
        name = user_data.get('name') or user_data.get('given_name') or user_data.get('full_name')
        if name:
            return name
    
    # Fallback to Firebase Auth if no name in Firestore
    try:
        from database.auth import get_user_name as get_auth_user_name
        auth_name = get_auth_user_name(uid, use_default=False)
        if auth_name and auth_name != 'The User':
            # Store the name in Firestore for future use
            user_ref.set({'name': auth_name}, merge=True)
            print(f"INFO: Stored Firebase Auth name '{auth_name}' to Firestore for uid: {uid}")
            return auth_name
    except Exception as e:
        print(f"WARNING: Error getting Firebase Auth name for uid {uid}: {e}")
    
    return 'User'  # Return default if all methods fail


def set_user_name(uid: str, name: str) -> None:
    """
    Set the user's name.
    
    Args:
        uid: User ID
        name: User's name
    """
    user_ref = db.collection('users').document(uid)
    user_ref.set({'name': name}, merge=True)
