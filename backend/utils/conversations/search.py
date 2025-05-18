import math
import os
from datetime import datetime
from typing import Dict

import typesense

# Only initialize the Typesense client if all required env variables are present
typesense_available = all([
    os.getenv('TYPESENSE_HOST'),
    os.getenv('TYPESENSE_HOST_PORT'),
    os.getenv('TYPESENSE_API_KEY')
])

client = None
if typesense_available:
    client = typesense.Client({
        'nodes': [{
            'host': os.getenv('TYPESENSE_HOST'),
            'port': os.getenv('TYPESENSE_HOST_PORT'),
            'protocol': 'https'
        }],
        'api_key': os.getenv('TYPESENSE_API_KEY'),
        'connection_timeout_seconds': 2
    })


def search_conversations(
        uid: str,
        query: str,
        page: int = 1,
        per_page: int = 10,
        include_discarded: bool = True,
        start_date: int = None,
        end_date: int = None,
) -> Dict:
    try:
        # If Typesense is not configured, return an empty result set
        if not typesense_available or client is None:
            return {
                'items': [],
                'total_pages': 0,
                'current_page': page,
                'per_page': per_page,
                'message': 'Search functionality requires Typesense configuration. Please set TYPESENSE_HOST, TYPESENSE_HOST_PORT, and TYPESENSE_API_KEY environment variables.'
            }

        filter_by = f'userId:={uid} && deleted:=false'
        if not include_discarded:
            filter_by = filter_by + ' && discarded:=false'

        # Add date range filters if provided
        if start_date is not None:
            filter_by = filter_by + f' && created_at:>={start_date}'
        if end_date is not None:
            filter_by = filter_by + f' && created_at:<={end_date}'

        search_parameters = {
            'q': query,
            'query_by': 'structured, transcript_segments',
            'filter_by': filter_by,
            'sort_by': 'created_at:desc',
            'per_page': per_page,
            'page': page,
        }

        results = client.collections['conversations'].documents.search(search_parameters)
        memories = []
        for item in results['hits']:
            item['document']['created_at'] = datetime.utcfromtimestamp(item['document']['created_at']).isoformat()
            item['document']['started_at'] = datetime.utcfromtimestamp(item['document']['started_at']).isoformat()
            item['document']['finished_at'] = datetime.utcfromtimestamp(item['document']['finished_at']).isoformat()
            memories.append(item['document'])
        return {
            'items': memories,
            'total_pages': math.ceil(results['found'] / per_page),
            'current_page': page,
            'per_page': per_page
        }
    except Exception as e:
        # Include a helpful message if there's a configuration issue
        if not typesense_available:
            return {
                'items': [],
                'total_pages': 0,
                'current_page': page,
                'per_page': per_page,
                'message': 'Search functionality requires Typesense configuration. Please set TYPESENSE_HOST, TYPESENSE_HOST_PORT, and TYPESENSE_API_KEY environment variables.'
            }
        raise Exception(f"Failed to search conversations: {str(e)}")
