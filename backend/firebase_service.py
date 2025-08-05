import firebase_admin
from firebase_admin import credentials, firestore
import re

cred = credentials.Certificate("serviceAccountKey.json") 
firebase_admin.initialize_app(cred)
db = firestore.client()

def sanitize_paper_id(paper_id):
    """
    Sanitize paper_id for use as Firestore document ID.
    Extracts work ID from OpenAlex URLs or replaces invalid characters.
    """
    # If it's an OpenAlex URL, extract just the work ID
    if paper_id.startswith('https://openalex.org/'):
        return paper_id.split('/')[-1]  # Returns something like 'W2123456789'
    
    # Replace any remaining forward slashes and other invalid characters
    # Firestore document IDs cannot contain: / \ . # [ ] * ?
    sanitized = re.sub(r'[/\\\.#\[\]\*\?]', '_', paper_id)
    
    # Ensure it's not empty and not too long (Firestore has a 1500 byte limit)
    if not sanitized or len(sanitized) > 1000:
        # Fallback: create a hash of the original ID
        import hashlib
        return hashlib.md5(paper_id.encode()).hexdigest()
    
    return sanitized

def get_summary_cache(paper_id):
    try:
        sanitized_id = sanitize_paper_id(paper_id)
        doc = db.collection("summaries").document(sanitized_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error getting summary cache: {e}")
        return None

def set_summary_cache(paper_id, summary):
    try:
        sanitized_id = sanitize_paper_id(paper_id)
        db.collection("summaries").document(sanitized_id).set({
            "summary": summary,
            "original_paper_id": paper_id,  # Store original ID for reference
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"Error setting summary cache: {e}")
        return False