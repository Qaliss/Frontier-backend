import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Temporarily disable Firebase to get the app working
logger.warning("Firebase caching is temporarily disabled due to authentication issues")

def sanitize_paper_id(paper_id):
    """
    Sanitize paper_id for use as Firestore document ID.
    This is kept for future use when Firebase is re-enabled.
    """
    logger.info(f"Sanitizing paper_id: {paper_id}")
    if paper_id.startswith('https://openalex.org/'):
        sanitized = paper_id.split('/')[-1]  # Returns 'W2123456789'
        logger.info(f"Extracted OpenAlex ID: {sanitized}")
        return sanitized
    
    import re
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
    """
    Temporarily disabled - always returns None (no cache hit)
    This will make the app generate new summaries every time until Firebase is fixed
    """
    logger.info(f"Cache check skipped for paper_id={paper_id} (Firebase disabled)")
    return None

def set_summary_cache(paper_id, summary):
    """
    Temporarily disabled - always returns True (pretend success)
    This prevents the app from crashing when trying to cache
    """
    logger.info(f"Cache storage skipped for paper_id={paper_id} (Firebase disabled)")
    return True