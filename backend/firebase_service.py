import firebase_admin
from firebase_admin import credentials, firestore
import os
import re
import logging
import json

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Firebase
try:
    # Try to get credentials from environment variable first (recommended for production)
    firebase_credentials = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    
    if firebase_credentials:
        # Parse the JSON string from environment variable
        logger.info("Loading Firebase credentials from environment variable")
        try:
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in FIREBASE_SERVICE_ACCOUNT: {str(e)}")
            raise
    else:
        # Fallback to file-based credentials (for local development)
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
        logger.info(f"Loading Firebase credentials from file: {cred_path}")
        
        if not os.path.exists(cred_path):
            logger.error(f"Service account file not found: {cred_path}")
            raise FileNotFoundError(f"Service account file not found: {cred_path}")
        
        cred = credentials.Certificate(cred_path)
    
    # Check if Firebase app is already initialized
    try:
        firebase_admin.get_app()
        logger.info("Firebase app already initialized")
    except ValueError:
        # App doesn't exist, initialize it
        firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized successfully")
        
except Exception as e:
    logger.error(f"Firebase initialization failed: {str(e)}")
    raise

db = firestore.client()

def sanitize_paper_id(paper_id):
    """
    Sanitize paper_id for use as Firestore document ID.
    Extracts work ID from OpenAlex URLs or replaces invalid characters.
    """
    logger.info(f"Sanitizing paper_id: {paper_id}")
    if paper_id.startswith('https://openalex.org/'):
        sanitized = paper_id.split('/')[-1]  # Returns 'W2123456789'
        logger.info(f"Extracted OpenAlex ID: {sanitized}")
        return sanitized
    
    # Replace invalid Firestore characters: / \ . # [ ] * ?
    sanitized = re.sub(r'[/\\\.#\[\]\*\?]', '_', paper_id)
    
    # Ensure not empty and not too long (Firestore limit: 1500 bytes)
    if not sanitized or len(sanitized) > 1000:
        import hashlib
        sanitized = hashlib.md5(paper_id.encode()).hexdigest()
        logger.warning(f"Generated hash for paper_id: {sanitized}")
    
    logger.info(f"Sanitized paper_id: {sanitized}")
    return sanitized

def get_summary_cache(paper_id):
    logger.info(f"Fetching cache for paper_id={paper_id}")
    try:
        sanitized_id = sanitize_paper_id(paper_id)
        doc = db.collection("summaries").document(sanitized_id).get()
        if doc.exists:
            logger.info(f"Cache found for paper_id={paper_id}")
            return doc.to_dict()
        logger.info(f"No cache for paper_id={paper_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching cache for paper_id={paper_id}: {str(e)}")
        return None

def set_summary_cache(paper_id, summary):
    logger.info(f"Setting cache for paper_id={paper_id}")
    try:
        sanitized_id = sanitize_paper_id(paper_id)
        db.collection("summaries").document(sanitized_id).set({
            "summary": summary,
            "original_paper_id": paper_id,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Successfully cached summary for paper_id={paper_id}")
        return True
    except Exception as e:
        logger.error(f"Error setting cache for paper_id={paper_id}: {str(e)}")
        return False