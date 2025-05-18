import hashlib
import json
import os
import uuid

from google.cloud import firestore

# Try to load project ID from credentials file
project_id = None
try:
    with open('google-credentials.json', 'r') as f:
        credentials_data = json.load(f)
        project_id = credentials_data.get('quota_project_id')
except Exception:
    pass

if os.environ.get('SERVICE_ACCOUNT_JSON'):
    service_account_info = json.loads(os.environ["SERVICE_ACCOUNT_JSON"])
    # create google-credentials.json
    with open('google-credentials.json', 'w') as f:
        json.dump(service_account_info, f)
    # Update project_id from the service account info
    project_id = service_account_info.get('quota_project_id', project_id)

# Fallback to environment variable if still not found
if not project_id:
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')

# Initialize Firestore with project ID
db = firestore.Client(project=project_id)


def get_users_uid():
    users_ref = db.collection('users')
    return [str(doc.id) for doc in users_ref.stream()]




def document_id_from_seed(seed: str) -> uuid.UUID:
    """Avoid repeating the same data"""
    seed_hash = hashlib.sha256(seed.encode('utf-8')).digest()
    generated_uuid = uuid.UUID(bytes=seed_hash[:16], version=4)
    return str(generated_uuid)
