from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Union
import requests
from firebase_service import get_summary_cache, set_summary_cache
from groq import Groq
import os
import logging
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, auth
from collections import defaultdict
import time
import json

firebase_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
if not firebase_json:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT not set")

firebase_dict = json.loads(firebase_json)
cred = credentials.Certificate(firebase_dict)
firebase_admin.initialize_app(cred)

logging.basicConfig(level=logging.INFO)

guest_summary_usage = defaultdict(list)
user_summary_usage = defaultdict(list)

logger = logging.getLogger(__name__)

class SummarizeRequest(BaseModel):
    paper_id: str
    abstract: str
    title: str = ""
    authors: List[str] = []
    published: Union[str, int] = ""

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    logger.error("GROQ_API_KEY not set")
ai_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GUEST_LIMIT = 5
USER_LIMIT = 50  # Higher limit for authenticated users
WINDOW_SECONDS = 3600  # 1 hour

def get_user_from_request(request: Request):
    """Extract user info from request, return (logged_in, user_id)"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get("uid")
            logger.info(f"Authenticated user: {user_id}")
            return True, user_id
        except Exception as e:
            logger.error(f"Failed to verify token: {str(e)}")
    return False, None

def get_remaining_summaries(logged_in: bool, user_id: str = None, ip: str = None):
    """Get remaining summaries for user or guest"""
    now = time.time()
    
    if logged_in and user_id:
        # Clean old entries
        user_summary_usage[user_id] = [
            ts for ts in user_summary_usage[user_id] if now - ts < WINDOW_SECONDS
        ]
        used = len(user_summary_usage[user_id])
        return max(0, USER_LIMIT - used)
    else:
        # Guest user
        if ip not in guest_summary_usage:
            guest_summary_usage[ip] = []
        
        # Clean old entries
        guest_summary_usage[ip] = [
            ts for ts in guest_summary_usage[ip] if now - ts < WINDOW_SECONDS
        ]
        used = len(guest_summary_usage[ip])
        return max(0, GUEST_LIMIT - used)

@app.get("/summary-quota")
async def get_summary_quota(request: Request):
    """Get remaining summaries for current user/IP"""
    logged_in, user_id = get_user_from_request(request)
    ip = request.client.host
    
    remaining = get_remaining_summaries(logged_in, user_id, ip)
    
    return {
        "remaining": remaining,
        "limit": USER_LIMIT if logged_in else GUEST_LIMIT,
        "window_hours": WINDOW_SECONDS // 3600,
        "authenticated": logged_in
    }

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"message": "Welcome to Frontier v0.2 API! Use /search-papers to find research or /summarize-paper for AI summaries."}

@app.get("/get-trending")
async def get_trending(
    category: str = Query(default='', description="Optional research category"),
    limit: int = Query(default=30, description="Number of trending papers"),
    days: int = Query(default=100, description="Lookback period for trending papers in days")
):
    logger.info(f"Fetching trending papers, category={category}, limit={limit}, days={days}")

    # Innovation-focused concept IDs for home page trending
    INNOVATION_CONCEPTS = [
        "C127313418",  # Computer science
        "C33923547",   # Mathematics  
        "C121332964",  # Physics
        "C185592680",  # Chemistry
        "C86803240",   # Biology
        "C127413603",  # Engineering
        "C39432304",   # Environmental science
        "C71924100",   # Medicine
        "C162324750",  # Economics (for fintech, behavioral econ, etc.)
    ]

    try:
        # Date filter: last X days
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        concept_filter = "|".join(INNOVATION_CONCEPTS)
        filters = f"from_publication_date:{from_date},type:article,concepts.id:{concept_filter}"

        if category:
            filters += f",concepts.id:{category}"

        response = requests.get(
            'https://api.openalex.org/works',
            params=[
                ('filter', filters),
                ('sort', 'cited_by_count:desc'),
                ('per_page', limit),  # ✅ correct param
                ('mailto', 'pranaunaras12@gmail.com')
            ],
            headers={"User-Agent": "FrontierApp/1.0"}
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        
        return results  # ✅ return array directly
    except requests.RequestException as e:
        logger.error(f"Trending error: {str(e)}")
        return {"error": str(e)}

@app.get("/search-papers")
async def search_papers(
    query: str = Query(default='', description="Search query for research papers"),
    sort: str = Query(default='relevance', description="Sort order for results"),
    year_filter: str = Query(default='2020-2025', description="Year range filter for results")
):
    logger.info(f"Received search request: query={query}, sort={sort}, year_filter={year_filter}")
    if not query.strip():
        logger.warning("Empty query received")
        return {"results": []}
    try:
        years = year_filter.split('-')
        from_year = years[0]
        to_year = years[1] if len(years) > 1 else years[0]
        filters = f"from_publication_date:{from_year}-01-01,to_publication_date:{to_year}-12-31,type:article"
        response = requests.get(
            'https://api.openalex.org/works',
            params=[
                ('search', query),
                ('filter', filters),
                ('per-page', 30),
                ('sort', 'relevance_score:desc'),
                ('mailto', 'pranaunaras12@gmail.com')
            ],
            headers={"User-Agent": "FrontierApp/1.0 (pranaunaras12@gmail.com)"}
        )
        response.raise_for_status()
        results = response.json()["results"]
        filtered = [paper for paper in results if paper.get("abstract_inverted_index") or paper.get("abstract")]
        logger.info(f"Returning {len(filtered)} papers")
        return filtered
    except requests.RequestException as e:
        logger.error(f"Search error: {str(e)}")
        return {"error": str(e)}

@app.post("/summarize-paper")
async def summarize_paper(req: SummarizeRequest, request: Request):
    logged_in, user_id = get_user_from_request(request)
    ip = request.client.host
    now = time.time()

    # Check and update rate limits
    if logged_in and user_id:
        # Clean old entries for authenticated user
        user_summary_usage[user_id] = [
            ts for ts in user_summary_usage[user_id] if now - ts < WINDOW_SECONDS
        ]
        
        if len(user_summary_usage[user_id]) >= USER_LIMIT:
            remaining = get_remaining_summaries(logged_in, user_id, ip)
            logger.warning(f"User limit reached for user: {user_id}")
            raise HTTPException(
                status_code=429, 
                detail=f"Rate limit exceeded. You have {remaining} summaries remaining."
            )
        
        user_summary_usage[user_id].append(now)
        logger.info(f"User {user_id} used summary ({len(user_summary_usage[user_id])}/{USER_LIMIT})")
    else:
        # Guest user rate limiting
        if ip not in guest_summary_usage:
            guest_summary_usage[ip] = []
            
        # Clean old entries for guest
        guest_summary_usage[ip] = [
            ts for ts in guest_summary_usage[ip] if now - ts < WINDOW_SECONDS
        ]
        
        if len(guest_summary_usage[ip]) >= GUEST_LIMIT:
            remaining = get_remaining_summaries(logged_in, user_id, ip)
            logger.warning(f"Guest limit reached for IP: {ip}")
            raise HTTPException(
                status_code=429,
                detail=f"Guest limit reached: {GUEST_LIMIT} summaries/hour. Please log in for more summaries. Remaining: {remaining}"
            )
        
        guest_summary_usage[ip].append(now)
        logger.info(f"Guest {ip} used summary ({len(guest_summary_usage[ip])}/{GUEST_LIMIT})")

    logger.info(f"Received summarize request: paper_id={req.paper_id}, title={req.title}, abstract_length={len(req.abstract)}")
    paper_id = req.paper_id
    abstract = req.abstract
    title = req.title
    authors = req.authors
    published = req.published

    if not abstract or abstract.strip() == '':
        logger.warning(f"No abstract for paper_id={paper_id}")
        return {"error": "Cannot summarize: No abstract available for this paper"}

    logger.info(f"Checking cache for paper_id={req.paper_id}")
    cached = get_summary_cache(paper_id)
    if cached:
        logger.info(f"Cache hit for paper_id={paper_id}")
        # Still return remaining count even for cached results
        remaining = get_remaining_summaries(logged_in, user_id, ip)
        return {
            "summary": cached.get("summary"), 
            "cached": True,
            "remaining_summaries": remaining
        }

    logger.info("Generating new summary")
    published_str = str(published) if published else 'Unknown year'
    prompt = f"""
        Title: {title}
        Abstract: {abstract}
        Authors: {', '.join([str(author) for author in authors])}
        Published: {published_str}

        You are a research curator helping people understand cutting-edge developments. Create a clear, digestible summary:

        - **What this study tackled**: Explain the problem they were solving, using everyday analogies when helpful. If there are complex terms, explain them immediately in parentheses.

        - **How they did it**: Describe their approach in simple terms. Think "they tested this by..." rather than technical jargon.

        - **Key discoveries**: Present findings with specific numbers, but explain what those numbers actually mean practically. Highlight anything surprising or counterintuitive.

        - **Why this matters**: Connect to real-world applications or implications a general audience would care about.

        Writing Guidelines:
        - Use proper markdown headers (##) for each section
        - Assume intelligent readers who aren't experts in this field
        - Immediately explain technical terms: "ptychography (an advanced imaging technique that...)"
        - Use analogies to familiar concepts for complex ideas
        - Keep sentences short and clear
        - Call out surprising findings as interesting
        - Focus on insights that make people think "oh, that's clever!"

        Keep each bullet point concise but informative.
    """

    try:
        logger.info("Calling Groq API")
        response = ai_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model='llama-3.3-70b-versatile',
            temperature=0.5
        )
        summary = response.choices[0].message.content
        logger.info(f"Groq response received for paper_id={paper_id}")
        
        try:
            set_summary_cache(paper_id, summary)
            logger.info(f"Cached summary for paper_id={paper_id}")
        except Exception as e:
            logger.error(f"Failed to cache summary for paper_id={paper_id}: {str(e)}")
            # Continue to return summary even if caching fails
        
        remaining = get_remaining_summaries(logged_in, user_id, ip)
        return {
            "summary": summary, 
            "cached": False,
            "remaining_summaries": remaining
        }
    except Exception as e:
        logger.error(f"Groq error for paper_id={paper_id}: {str(e)}")
        return {"error": f"Failed to generate summary: {str(e)}"}