import datetime
import json
import os
from typing import List

from google.cloud import storage
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google.cloud.storage import transfer_manager

from database.redis_db import cache_signed_url, get_cached_signed_url

if os.environ.get('SERVICE_ACCOUNT_JSON'):
    service_account_info = json.loads(os.environ["SERVICE_ACCOUNT_JSON"])
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT') or service_account_info.get('project_id', service_account_info.get('quota_project_id'))
    
    # Handle both service account and OAuth2 credentials
    if service_account_info.get('type') == 'service_account':
        credentials = service_account.Credentials.from_service_account_info(service_account_info)
        storage_client = storage.Client(project=project_id, credentials=credentials)
    else:
        # OAuth2 credentials (authorized_user type)
        print("Warning: Using OAuth2 credentials - signed URLs may not work. Consider using service account credentials.")
        credentials = OAuth2Credentials(
            token=None,
            refresh_token=service_account_info.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=service_account_info.get('client_id'),
            client_secret=service_account_info.get('client_secret')
        )
        storage_client = storage.Client(project=project_id, credentials=credentials)
else:
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    storage_client = storage.Client(project=project_id)

speech_profiles_bucket = os.getenv('BUCKET_SPEECH_PROFILES')
postprocessing_audio_bucket = os.getenv('BUCKET_POSTPROCESSING')
memories_recordings_bucket = os.getenv('BUCKET_MEMORIES_RECORDINGS')
syncing_local_bucket = os.getenv('BUCKET_TEMPORAL_SYNC_LOCAL')
omi_plugins_bucket = os.getenv('BUCKET_PLUGINS_LOGOS')
app_thumbnails_bucket = os.getenv('BUCKET_APP_THUMBNAILS')
chat_files_bucket = os.getenv('BUCKET_CHAT_FILES')

# *******************************************
# ************* SPEECH PROFILE **************
# *******************************************
def upload_profile_audio(file_path: str, uid: str):
    bucket = storage_client.bucket(speech_profiles_bucket)
    path = f'{uid}/speech_profile.wav'
    blob = bucket.blob(path)
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{speech_profiles_bucket}/{path}'


def get_user_has_speech_profile(uid: str) -> bool:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blob = bucket.blob(f'{uid}/speech_profile.wav')
    return blob.exists()


def get_profile_audio_if_exists(uid: str, download: bool = True) -> str:
    bucket = storage_client.bucket(speech_profiles_bucket)
    path = f'{uid}/speech_profile.wav'
    blob = bucket.blob(path)
    if blob.exists():
        if download:
            file_path = f'_temp/{uid}_speech_profile.wav'
            blob.download_to_filename(file_path)
            return file_path
        
        try:
            return _get_signed_url(blob, 60)
        except Exception as e:
            print(f"Failed to get signed URL for speech profile, falling back to download: {e}")
            # Force download if signed URL fails
            file_path = f'_temp/{uid}_speech_profile.wav'
            blob.download_to_filename(file_path)
            return file_path

    return None


def upload_additional_profile_audio(file_path: str, uid: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    path = f'{uid}/additional_profile_recordings/{file_path.split("/")[-1]}'
    blob = bucket.blob(path)
    blob.upload_from_filename(file_path)


def delete_additional_profile_audio(uid: str, file_name: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blob = bucket.blob(f'{uid}/additional_profile_recordings/{file_name}')
    if blob.exists():
        print('delete_additional_profile_audio deleting', file_name)
        blob.delete()


def get_additional_profile_recordings(uid: str, download: bool = False) -> List[str]:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blobs = bucket.list_blobs(prefix=f'{uid}/additional_profile_recordings/')
    if download:
        paths = []
        for blob in blobs:
            file_path = f'_temp/{uid}_{blob.name.split("/")[-1]}'
            blob.download_to_filename(file_path)
            paths.append(file_path)
        return paths

    return [_get_signed_url(blob, 60) for blob in blobs]


# ********************************************
# ************* PEOPLE PROFILES **************
# ********************************************

def upload_user_person_speech_sample(file_path: str, uid: str, person_id: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    path = f'{uid}/people_profiles/{person_id}/{file_path.split("/")[-1]}'
    blob = bucket.blob(path)
    blob.upload_from_filename(file_path)


def delete_user_person_speech_sample(uid: str, person_id: str, file_name: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blob = bucket.blob(f'{uid}/people_profiles/{person_id}/{file_name}')
    if blob.exists():
        blob.delete()


def delete_speech_sample_for_people(uid: str, file_name: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blobs = bucket.list_blobs(prefix=f'{uid}/people_profiles/')
    for blob in blobs:
        if file_name in blob.name:
            print('delete_speech_sample_for_people deleting', blob.name)
            blob.delete()


def delete_user_person_speech_samples(uid: str, person_id: str) -> None:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blobs = bucket.list_blobs(prefix=f'{uid}/people_profiles/{person_id}/')
    for blob in blobs:
        blob.delete()


def get_user_people_ids(uid: str) -> List[str]:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blobs = bucket.list_blobs(prefix=f'{uid}/people_profiles/')
    return [blob.name.split("/")[-2] for blob in blobs]


def get_user_person_speech_samples(uid: str, person_id: str, download: bool = False) -> List[str]:
    bucket = storage_client.bucket(speech_profiles_bucket)
    blobs = bucket.list_blobs(prefix=f'{uid}/people_profiles/{person_id}/')
    if download:
        paths = []
        for blob in blobs:
            file_path = f'_temp/{uid}_person_{blob.name.split("/")[-1]}'
            blob.download_to_filename(file_path)
            paths.append(file_path)
        return paths

    return [_get_signed_url(blob, 60) for blob in blobs]


# ********************************************
# ************* POST PROCESSING **************
# ********************************************
def upload_postprocessing_audio(file_path: str):
    bucket = storage_client.bucket(postprocessing_audio_bucket)
    blob = bucket.blob(file_path)
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{postprocessing_audio_bucket}/{file_path}'


def delete_postprocessing_audio(file_path: str):
    bucket = storage_client.bucket(postprocessing_audio_bucket)
    blob = bucket.blob(file_path)
    blob.delete()


# ***********************************
# ************* SDCARD **************
# ***********************************

def upload_sdcard_audio(file_path: str):
    bucket = storage_client.bucket(postprocessing_audio_bucket)
    blob = bucket.blob(file_path)
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{postprocessing_audio_bucket}/sdcard/{file_path}'


def download_postprocessing_audio(file_path: str, destination_file_path: str):
    bucket = storage_client.bucket(postprocessing_audio_bucket)
    blob = bucket.blob(file_path)
    blob.download_to_filename(destination_file_path)


# ************************************************
# *********** CONVERSATIONS RECORDINGS ***********
# ************************************************

def upload_conversation_recording(file_path: str, uid: str, conversation_id: str):
    bucket = storage_client.bucket(memories_recordings_bucket)
    path = f'{uid}/{conversation_id}.wav'
    blob = bucket.blob(path)
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{memories_recordings_bucket}/{path}'


def get_conversation_recording_if_exists(uid: str, memory_id: str) -> str:
    print('get_conversation_recording_if_exists', uid, memory_id)
    bucket = storage_client.bucket(memories_recordings_bucket)
    path = f'{uid}/{memory_id}.wav'
    blob = bucket.blob(path)
    if blob.exists():
        file_path = f'_temp/{memory_id}.wav'
        blob.download_to_filename(file_path)
        return file_path
    return None


def delete_all_conversation_recordings(uid: str):
    if not uid:
        return
    bucket = storage_client.bucket(memories_recordings_bucket)
    blobs = bucket.list_blobs(prefix=uid)
    for blob in blobs:
        blob.delete()


# ********************************************
# ************* SYNCING FILES **************
# ********************************************
def get_syncing_file_temporal_url(file_path: str):
    bucket = storage_client.bucket(syncing_local_bucket)
    blob = bucket.blob(file_path)
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{syncing_local_bucket}/{file_path}'

def get_syncing_file_temporal_signed_url(file_path: str):
    bucket = storage_client.bucket(syncing_local_bucket)
    blob = bucket.blob(file_path)
    blob.upload_from_filename(file_path)
    return _get_signed_url(blob, 15)


def delete_syncing_temporal_file(file_path: str):
    bucket = storage_client.bucket(syncing_local_bucket)
    blob = bucket.blob(file_path)
    blob.delete()


# **********************************
# ************* UTILS **************
# **********************************

def _get_signed_url(blob, minutes):
    if cached := get_cached_signed_url(blob.name):
        return cached

    try:
        # Try to generate signed URL (requires service account with private key)
        signed_url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(minutes=minutes), method="GET")
        cache_signed_url(blob.name, signed_url, minutes * 60)
        return signed_url
    except AttributeError as e:
        if "private key" in str(e).lower():
            print(f"Warning: Cannot generate signed URL - using public URL fallback. Error: {e}")
            # Fallback to public URL (only works if bucket/blob is publicly accessible)
            public_url = f"https://storage.googleapis.com/{blob.bucket.name}/{blob.name}"
            return public_url
        else:
            raise e
    except Exception as e:
        print(f"Error generating signed URL: {e}")
        # Fallback to public URL
        public_url = f"https://storage.googleapis.com/{blob.bucket.name}/{blob.name}"
        return public_url


def upload_plugin_logo(file_path: str, plugin_id: str):
    bucket = storage_client.bucket(omi_plugins_bucket)
    path = f'{plugin_id}.png'
    blob = bucket.blob(path)
    blob.cache_control = 'public, no-cache'
    blob.upload_from_filename(file_path)
    return f'https://storage.googleapis.com/{omi_plugins_bucket}/{path}'


def delete_plugin_logo(img_url: str):
    bucket = storage_client.bucket(omi_plugins_bucket)
    path = img_url.split(f'https://storage.googleapis.com/{omi_plugins_bucket}/')[1]
    print('delete_plugin_logo', path)
    blob = bucket.blob(path)
    blob.delete()

def upload_app_thumbnail(file_path: str, thumbnail_id: str) -> str:
    bucket = storage_client.bucket(app_thumbnails_bucket)
    path = f'{thumbnail_id}.jpg'
    blob = bucket.blob(path)
    blob.cache_control = 'public, no-cache'
    blob.upload_from_filename(file_path)
    public_url = f'https://storage.googleapis.com/{app_thumbnails_bucket}/{path}'
    return public_url

def get_app_thumbnail_url(thumbnail_id: str) -> str:
    path = f'{thumbnail_id}.jpg'
    return f'https://storage.googleapis.com/{app_thumbnails_bucket}/{path}'

# **********************************
# ************* CHAT FILES **************
# **********************************
def upload_multi_chat_files(files_name: List[str], uid: str) -> dict:
    """
    Upload multiple files to Google Cloud Storage in the chat files bucket.

    Args:
        files_name: List of file paths to upload
        uid: User ID to use as part of the storage path

    Returns:
        dict: A dictionary mapping original filenames to their Google Cloud Storage URLs
    """
    bucket = storage_client.bucket(chat_files_bucket)
    result = transfer_manager.upload_many_from_filenames(bucket, files_name, source_directory="./", blob_name_prefix=f'{uid}/')
    dictFiles = {}
    for name, result in zip(files_name, result):
        if isinstance(result, Exception):
            print("Failed to upload {} due to exception: {}".format(name, result))
        else:
            dictFiles[name] = f'https://storage.googleapis.com/{chat_files_bucket}/{uid}/{name}'
    return dictFiles


# **********************************
# ******* CONVERSATION IMAGES *******
# **********************************
def upload_conversation_image(image_data: bytes, uid: str, conversation_id: str, image_index: int = 0) -> str:
    """
    Upload an image for a conversation summary to Firebase Storage.
    
    Args:
        image_data: Raw image data as bytes
        uid: User ID
        conversation_id: ID of the conversation
        image_index: Index of the image (for multiple images per conversation)
    
    Returns:
        str: Signed URL of the uploaded image
    """
    import uuid
    import tempfile
    import os
    
    # Create a unique filename
    unique_id = str(uuid.uuid4())[:8]
    filename = f"{conversation_id}_{image_index}_{unique_id}.jpg"
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
        temp_file.write(image_data)
        temp_file_path = temp_file.name
    
    try:
        # Upload to Firebase Storage
        bucket = storage_client.bucket(chat_files_bucket)  # Reusing chat files bucket
        path = f'{uid}/conversation_images/{filename}'
        blob = bucket.blob(path)
        blob.cache_control = 'public, max-age=3600'  # Cache for 1 hour
        blob.upload_from_filename(temp_file_path)
        
        # Return signed URL instead of public storage URL
        return _get_signed_url(blob, 60 * 24)  # 24 hours expiry
        
    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


def upload_multiple_conversation_images(images_data: List[bytes], uid: str, conversation_id: str) -> List[str]:
    """
    Upload multiple images for a conversation summary to Firebase Storage.
    
    Args:
        images_data: List of raw image data as bytes
        uid: User ID
        conversation_id: ID of the conversation
    
    Returns:
        List[str]: List of public URLs of the uploaded images
    """
    urls = []
    for index, image_data in enumerate(images_data):
        try:
            url = upload_conversation_image(image_data, uid, conversation_id, index)
            urls.append(url)
        except Exception as e:
            print(f"Failed to upload image {index} for conversation {conversation_id}: {e}")
            continue
    return urls


def delete_conversation_images(uid: str, conversation_id: str):
    """
    Delete all images associated with a conversation.
    
    Args:
        uid: User ID
        conversation_id: ID of the conversation
    """
    bucket = storage_client.bucket(chat_files_bucket)
    prefix = f'{uid}/conversation_images/{conversation_id}_'
    blobs = bucket.list_blobs(prefix=prefix)
    
    for blob in blobs:
        try:
            blob.delete()
            print(f"Deleted conversation image: {blob.name}")
        except Exception as e:
            print(f"Failed to delete conversation image {blob.name}: {e}")


# **********************************
# ******* CONVERSATION AUDIO *******
# **********************************
def upload_conversation_audio(audio_data: bytes, uid: str, conversation_id: str, voice: str = "alloy", speed: float = 1.0) -> str:
    """
    Upload an audio file for a conversation TTS to Firebase Storage.
    
    Args:
        audio_data: Raw audio data as bytes
        uid: User ID
        conversation_id: ID of the conversation
        voice: TTS voice used
        speed: TTS speed used
    
    Returns:
        str: Signed URL of the uploaded audio file
    """
    import tempfile
    import os
    
    # Create filename with voice and speed parameters to ensure uniqueness
    filename = f"{conversation_id}_{voice}_{speed}.mp3"
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
        temp_file.write(audio_data)
        temp_file_path = temp_file.name
    
    try:
        # Upload to Firebase Storage
        bucket = storage_client.bucket(chat_files_bucket)  # Reusing chat files bucket
        path = f'{uid}/conversation_audio/{filename}'
        blob = bucket.blob(path)
        blob.cache_control = 'public, max-age=86400'  # Cache for 24 hours
        blob.content_type = 'audio/mpeg'
        blob.upload_from_filename(temp_file_path)
        
        # Return signed URL
        return _get_signed_url(blob, 60 * 24)  # 24 hours expiry
        
    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


def get_conversation_audio_url(uid: str, conversation_id: str, voice: str = "alloy", speed: float = 1.0) -> str:
    """
    Get signed URL for existing conversation audio file.
    
    Args:
        uid: User ID
        conversation_id: ID of the conversation
        voice: TTS voice used
        speed: TTS speed used
    
    Returns:
        str: Signed URL if file exists, None otherwise
    """
    bucket = storage_client.bucket(chat_files_bucket)
    filename = f"{conversation_id}_{voice}_{speed}.mp3"
    path = f'{uid}/conversation_audio/{filename}'
    blob = bucket.blob(path)
    
    try:
        # Check if the blob exists
        if blob.exists():
            return _get_signed_url(blob, 60 * 24)  # 24 hours expiry
        else:
            return None
    except Exception as e:
        print(f"Error checking conversation audio existence: {e}")
        return None


def delete_conversation_audio(uid: str, conversation_id: str, voice: str = None, speed: float = None):
    """
    Delete audio files associated with a conversation.
    If voice and speed are provided, delete specific file. Otherwise, delete all audio files for the conversation.
    
    Args:
        uid: User ID
        conversation_id: ID of the conversation
        voice: Specific voice to delete (optional)
        speed: Specific speed to delete (optional)
    """
    bucket = storage_client.bucket(chat_files_bucket)
    
    if voice is not None and speed is not None:
        # Delete specific audio file
        filename = f"{conversation_id}_{voice}_{speed}.mp3"
        path = f'{uid}/conversation_audio/{filename}'
        blob = bucket.blob(path)
        try:
            blob.delete()
            print(f"Deleted conversation audio: {blob.name}")
        except Exception as e:
            print(f"Failed to delete conversation audio {blob.name}: {e}")
    else:
        # Delete all audio files for this conversation
        prefix = f'{uid}/conversation_audio/{conversation_id}_'
        blobs = bucket.list_blobs(prefix=prefix)
        
        for blob in blobs:
            try:
                blob.delete()
                print(f"Deleted conversation audio: {blob.name}")
            except Exception as e:
                print(f"Failed to delete conversation audio {blob.name}: {e}")
