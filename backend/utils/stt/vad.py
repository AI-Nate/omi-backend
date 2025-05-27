import os
import sys
import urllib.error
from enum import Enum

import numpy as np
import requests
import torch
from fastapi import HTTPException
from pydub import AudioSegment

from database import redis_db

torch.set_num_threads(1)
torch.hub.set_dir('pretrained_models')

# Try to load the model locally first, if it fails with a GitHub authentication error,
# use the GitHub token from the environment variables
try:
    model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, trust_repo=True)
except urllib.error.HTTPError as e:
    if e.code == 401:  # Unauthorized
        # Check if we have a GitHub token in the environment
        github_token = os.getenv('GITHUB_TOKEN')
        if github_token:
            # Set the token for torch hub
            os.environ['GITHUB_TOKEN'] = github_token
            # Try again with the token
            model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, trust_repo=True)
        else:
            # Try loading from local cache without accessing GitHub
            try:
                # Check if the model exists in the pretrained_models directory
                model_dir = os.path.join('pretrained_models', 'hub', 'snakers4_silero-vad')
                if os.path.exists(model_dir):
                    model, utils = torch.hub.load(repo_or_dir=model_dir, model='silero_vad', force_reload=False, source='local', trust_repo=True)
                else:
                    print("Error: Cannot download silero-vad model. Add a GITHUB_TOKEN to .env or download the model manually.")
                    sys.exit(1)
            except Exception as ex:
                print(f"Failed to load model locally: {ex}")
                sys.exit(1)
    else:
        # Re-raise the exception if it's not an authentication error
        raise

(get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils


class SpeechState(str, Enum):
    speech_found = 'speech_found'
    no_speech = 'no_speech'


def is_speech_present(data, vad_iterator, window_size_samples=256):
    data_int16 = np.frombuffer(data, dtype=np.int16)
    data_float32 = data_int16.astype(np.float32) / 32768.0
    has_start, has_end = False, False

    for i in range(0, len(data_float32), window_size_samples):
        chunk = data_float32[i: i + window_size_samples]
        if len(chunk) < window_size_samples:
            break
        speech_dict = vad_iterator(chunk, return_seconds=False)
        if speech_dict:
            print(speech_dict)
            vad_iterator.reset_states()
            return SpeechState.speech_found

            # if not has_start and 'start' in speech_dict:
            #     has_start = True
            #
            # if not has_end and 'end' in speech_dict:
            #     has_end = True

    # if has_start:
    #     return SpeechState.speech_found
    # elif has_end:
    #     return SpeechState.no_speech
    vad_iterator.reset_states()
    return SpeechState.no_speech


def is_audio_empty(file_path, sample_rate=8000):
    wav = read_audio(file_path)
    timestamps = get_speech_timestamps(wav, model, sampling_rate=sample_rate)
    if len(timestamps) == 1:
        prob_not_speech = ((timestamps[0]['end'] / 1000) - (timestamps[0]['start'] / 1000)) < 1
        return prob_not_speech
    return len(timestamps) == 0


def vad_is_empty(file_path, return_segments: bool = False, cache: bool = False):
    """Uses vad_modal/vad.py deployment (Best quality) with local fallback"""
    caching_key = f'vad_is_empty:{file_path}'
    if cache:
        if exists := redis_db.get_generic_cache(caching_key):
            if return_segments:
                return exists
            return len(exists) == 0

    vad_api_url = os.getenv('HOSTED_VAD_API_URL', '').strip()
    print(f'VAD API URL: "{vad_api_url}" (length: {len(vad_api_url)})')
    
    # Try hosted VAD API if available
    if vad_api_url and vad_api_url.lower() not in ['none', 'null', '']:
        try:
            # file_duration = AudioSegment.from_wav(file_path).duration_seconds
            # print('vad_is_empty file duration:', file_duration)
            with open(file_path, 'rb') as file:
                files = {'file': (file_path.split('/')[-1], file, 'audio/wav')}
                response = requests.post(vad_api_url, files=files)
                segments = response.json()
                if cache:
                    redis_db.set_generic_cache(caching_key, segments, ttl=60 * 60 * 24)
                if return_segments:
                    return segments
                print('vad_is_empty', len(segments) == 0)  # compute % of empty files in someway
                return len(segments) == 0  # but also check likelyhood of silence if only 1 segment?
        except Exception as e:
            print('vad_is_empty hosted API failed, falling back to local:', e)
    else:
        print('No hosted VAD API configured, using local VAD')
    
    # Fallback to local VAD when hosted API is not available
    try:
        print('Using local VAD fallback for', file_path)
        wav = read_audio(file_path)
        timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
        
        if return_segments:
            # Convert timestamps to segments format
            segments = []
            for ts in timestamps:
                segments.append({
                    'start': ts['start'] / 1000.0,  # Convert to seconds
                    'end': ts['end'] / 1000.0
                })
            if cache:
                redis_db.set_generic_cache(caching_key, segments, ttl=60 * 60 * 24)
            return segments
        
        # Check if audio is empty
        is_empty = len(timestamps) == 0
        if len(timestamps) == 1:
            duration = (timestamps[0]['end'] - timestamps[0]['start']) / 1000.0
            is_empty = duration < 1
        
        print('vad_is_empty (local):', is_empty)
        return is_empty
        
    except Exception as e:
        print('vad_is_empty local fallback failed:', e)
        if return_segments:
            return []
        return False


def apply_vad_for_speech_profile(file_path: str):
    print('apply_vad_for_speech_profile', file_path)
    voice_segments = vad_is_empty(file_path, return_segments=True)
    if len(voice_segments) == 0:  # TODO: front error on post-processing, audio sent is bad.
        raise HTTPException(status_code=400, detail="Audio is empty")
    joined_segments = []
    for i, segment in enumerate(voice_segments):
        if joined_segments and (segment['start'] - joined_segments[-1]['end']) < 1:
            joined_segments[-1]['end'] = segment['end']
        else:
            joined_segments.append(segment)

    # trim silence out of file_path, but leave 1 sec of silence within chunks
    trimmed_aseg = AudioSegment.empty()
    for i, segment in enumerate(joined_segments):
        start = segment['start'] * 1000
        end = segment['end'] * 1000
        trimmed_aseg += AudioSegment.from_wav(file_path)[start:end]
        if i < len(joined_segments) - 1:
            trimmed_aseg += AudioSegment.from_wav(file_path)[end:end + 1000]

    # file_path.replace('.wav', '-cleaned.wav')
    trimmed_aseg.export(file_path, format="wav")
