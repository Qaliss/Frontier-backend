from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Union
import requests
from firebase_service import get_summary_cache, set_summary_cache
from groq import Groq
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
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

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"message": "Welcome to Frontier v0.2 API! Use /search-papers to find research or /summarize-paper for AI summaries."}

@app.get("/get-trending")
async def get_trending(
    category: str = Query(default='', description="Optional research category"),
    limit: int = Query(default=10, description="Number of trending papers"),
    days: int = Query(default=14, description="Lookback period for trending papers in days")
):
    logger.info(f"Fetching trending papers, category={category}, limit={limit}, days={days}")
    try:
        # Date filter: last X days
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        filters = f"from_publication_date:{from_date},type:article"

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
async def summarize_paper(req: SummarizeRequest):
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
        return {"summary": cached.get("summary"), "cached": True}

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
        return {"summary": summary, "cached": False}
    except Exception as e:
        logger.error(f"Groq error for paper_id={paper_id}: {str(e)}")
        return {"error": f"Failed to generate summary: {str(e)}"}
