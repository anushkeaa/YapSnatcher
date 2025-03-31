from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import openai
import os
from dotenv import load_dotenv
import re
from datetime import datetime
from backend.debug_helpers import log_error, test_video_url
import sys

# Make sure the parent directory is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from local_summarizer import summarize_video as local_summarize
    local_summarizer_available = True
except ImportError:
    local_summarizer_available = False

# Apply pytube patches to handle YouTube API changes
try:
    from backend.pytube_patches import apply_patches
    apply_patches()
    print("Applied runtime patches to pytube")
except Exception as e:
    print(f"Failed to apply pytube patches: {e}")

load_dotenv()

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory
try:
    app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
    templates = Jinja2Templates(directory="frontend/templates")
except RuntimeError:
    os.makedirs("frontend/static", exist_ok=True)
    os.makedirs("frontend/templates", exist_ok=True)
    app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
    templates = Jinja2Templates(directory="frontend/templates")

class VideoURL(BaseModel):
    url: str

def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise HTTPException(status_code=400, detail="Invalid YouTube URL")

def get_video_transcript(video_id: str) -> str:
    """Get video transcript using youtube_transcript_api."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join([entry["text"] for entry in transcript_list])
    except Exception as e:
        print(f"Transcript error: {str(e)}")  # Add logging for debugging
        raise HTTPException(status_code=400, detail=f"Failed to get video transcript: {str(e)}")

def get_video_title(url: str) -> str:
    """Get video title using multiple approaches to handle YouTube API changes."""
    video_id = extract_video_id(url)
    print(f"Getting title for video ID: {video_id}")
    
    # Method 1: Try BeautifulSoup method first since it's more reliable
    try:
        print("Trying BeautifulSoup method to get title via page content")
        import requests
        from bs4 import BeautifulSoup
        
        # Use a proper User-Agent to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=headers)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find title in meta tags (most reliable)
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.get("content"):
                title = meta_title["content"]
                print(f"Got title from meta tags: {title}")
                return title
                
            # Try to find title in title tag as backup
            title_tag = soup.find("title")
            if title_tag:
                # YouTube titles typically have " - YouTube" at the end
                title = title_tag.text.replace(" - YouTube", "").strip()
                if title:
                    print(f"Got title from page title: {title}")
                    return title
    except Exception as e:
        print(f"BeautifulSoup title extraction error: {str(e)}")
    
    # Method 2: Using pytube as fallback with error handling and retries
    for attempt in range(2):
        try:
            print(f"Attempt {attempt+1} to get title using pytube")
            yt = YouTube(url)
            title = yt.title
            if title:
                print(f"Successfully retrieved title with pytube: {title}")
                return title
        except Exception as e:
            print(f"Pytube error (attempt {attempt+1}): {str(e)}")
            # Wait a bit before next attempt
            import time
            time.sleep(1)
    
    # Method 3: Fallback to video ID if all methods fail
    print("All methods failed, using video ID as fallback title")
    return f"YouTube Video ({video_id})"

def generate_summary(transcript: str, title: str) -> dict:
    """Generate summary using OpenAI API or fall back to local summarization."""
    try:
        # Try using OpenAI API first
        openai_api_key = os.getenv("OPENAI_API_KEY")
        
        # If OpenAI API key is not present or is set to use local summarization, use local
        use_local = os.getenv("USE_LOCAL_SUMMARIZER", "false").lower() == "true"
        
        if use_local and local_summarizer_available:
            print("Using local summarization as configured in environment")
            raise ValueError("Using local summarization as configured")
        
        # Verify the API key is present and not a placeholder
        if not openai_api_key:
            print("ERROR: OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key is missing. Please check your .env file.")
        
        if openai_api_key in ["your_actual_openai_api_key_here", "your_openai_api_key"]:
            print("ERROR: You are using a placeholder API key")
            raise ValueError("OpenAI API key appears to be a placeholder. Please update your .env file.")
            
        # Validate the API key format (should start with "sk-")
        if not openai_api_key.startswith("sk-"):
            print("ERROR: API key appears to be in invalid format")
            raise ValueError("OpenAI API key appears to be invalid. It should start with 'sk-'.")
        
        # Create the client
        client = openai.OpenAI(api_key=openai_api_key)
        
        # Log info about what we're processing
        print(f"Generating summary for video: {title}")
        print(f"Transcript length: {len(transcript)} characters")
        
        # Truncate transcript if too long
        max_transcript_length = 10000
        if len(transcript) > max_transcript_length:
            print(f"Transcript too long ({len(transcript)} chars), truncating to {max_transcript_length} characters")
            transcript = transcript[:max_transcript_length] + "..."
        
        # Make API call with timeout handling
        import time
        start_time = time.time()
        print("Making request to OpenAI API...")
        
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates concise video summaries. Create a summary and extract key points from the transcript."
                    },
                    {
                        "role": "user",
                        "content": f"Title: {title}\n\nTranscript: {transcript}\n\nPlease provide a concise summary and key points."
                    }
                ],
                temperature=0.7,
                max_tokens=800,
                timeout=60  # 60 seconds timeout
            )
            print(f"API response received in {time.time() - start_time:.2f} seconds")
            
            # Process the response
            summary = response.choices[0].message.content
            print("Summary content received successfully!")
            
            # Split the summary into main summary and key points
            parts = summary.split("Key Points:")
            main_summary = parts[0].strip()
            key_points = []
            if len(parts) > 1:
                key_points = [point.strip("- ").strip() for point in parts[1].strip().split("\n") if point.strip()]
            
            print(f"Extracted {len(key_points)} key points")
            
            return {
                "title": title,
                "summary": main_summary,
                "keyPoints": key_points,
                "timestamp": datetime.now().isoformat()
            }
            
        except openai.APITimeoutError:
            print("Error: OpenAI API request timed out")
            raise HTTPException(status_code=504, detail="OpenAI API request timed out. Please try again.")
        except openai.APIError as e:
            print(f"OpenAI API Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"OpenAI API Error: {str(e)}")
        except openai.RateLimitError as e:
            print(f"Rate limit exceeded: {str(e)}")
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
            
    except Exception as e:
        print(f"OpenAI summary generation error: {str(e)}")
        
        # If OpenAI fails and local summarizer is available, use it
        if local_summarizer_available:
            try:
                print("Falling back to local summarization")
                
                # We need a URL to use local_summarize, so we'll use a workaround:
                # Extract video ID from the title if it's in our default format
                video_id_match = re.search(r'\(([0-9A-Za-z_-]{11})\)', title)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    # Create a fake URL with a video ID that won't be used
                    # since we already have the transcript and title
                    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                
                # Replace the default implementation with our custom implementation
                # that uses the existing transcript and title
                def get_video_info_override(url):
                    return title, transcript
                
                # Save the original function
                original_get_video_info = sys.modules['local_summarizer'].get_video_info
                
                # Replace with our override
                sys.modules['local_summarizer'].get_video_info = get_video_info_override
                
                # Generate summary using local summarizer
                result = local_summarize(url)
                
                # Restore the original function
                sys.modules['local_summarizer'].get_video_info = original_get_video_info
                
                if result["success"]:
                    return result["data"]
                else:
                    raise ValueError(result["error"])
            except Exception as local_error:
                print(f"Local summarization also failed: {str(local_error)}")
                # If both methods fail, re-raise the original OpenAI error
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to generate summary with both OpenAI and local methods: {str(e)}")
        else:
            # If local summarizer is not available, raise the original error
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to generate summary with OpenAI: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def get_home_page(request: Request):
    year = datetime.now().year
    return templates.TemplateResponse("index.html", {"request": request, "year": year})

@app.get("/summarize", response_class=HTMLResponse)
async def get_summarize_page(request: Request):
    year = datetime.now().year
    return templates.TemplateResponse("index.html", {"request": request, "year": year})

@app.post("/summarize")
async def summarize_video(video: VideoURL):
    try:
        video_id = extract_video_id(video.url)
        transcript = get_video_transcript(video_id)
        title = get_video_title(video.url)
        summary = generate_summary(transcript, title)
        
        return {"success": True, "data": summary}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/summarize-form")
async def summarize_video_form(request: Request, url: str = Form(...)):
    try:
        print(f"\n\n====== Processing New Request ======")
        print(f"Processing video URL: {url}")
        
        # First, run a diagnostic test on the URL
        print("Running URL diagnostics...")
        diagnostics = test_video_url(url)
        
        if not diagnostics["valid"]:
            issues = "; ".join(diagnostics["issues"])
            print(f"URL validation failed: {issues}")
            return templates.TemplateResponse("index.html", {
                "request": request,
                "error": f"Invalid YouTube URL: {issues}",
                "url": url,
                "year": datetime.now().year
            })
        
        if not diagnostics.get("transcript_available", False):
            error_msg = diagnostics.get("transcript_error", "Unknown error")
            print(f"Transcript unavailable: {error_msg}")
            return templates.TemplateResponse("index.html", {
                "request": request,
                "error": f"This video doesn't have a transcript available. YouTube error: {error_msg}",
                "url": url,
                "year": datetime.now().year
            })
            
        if not diagnostics.get("openai_configured", False):
            issues = [issue for issue in diagnostics["issues"] if "OpenAI" in issue]
            error_msg = issues[0] if issues else "OpenAI API is not properly configured"
            print(f"OpenAI configuration issue: {error_msg}")
            return templates.TemplateResponse("index.html", {
                "request": request,
                "error": error_msg,
                "url": url,
                "year": datetime.now().year
            })
        
        # Now proceed with the standard flow
        video_id = extract_video_id(url)
        print(f"Extracted video ID: {video_id}")
        
        transcript = get_video_transcript(video_id)
        print(f"Got transcript of length: {len(transcript)}")
        
        title = get_video_title(url)
        print(f"Got video title: {title}")
        
        summary = generate_summary(transcript, title)
        print("Summary generated successfully")
        
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "summary": summary["summary"], 
            "keyPoints": summary["keyPoints"],
            "title": summary["title"],
            "url": url,
            "year": datetime.now().year
        })
    except HTTPException as e:
        error_detail = str(e.detail)
        print(f"HTTP Exception: {error_detail}")
        log_error(f"HTTP Exception in summarize_video_form: {error_detail}")
        
        # Provide more user-friendly error messages
        if "transcript" in error_detail.lower():
            user_message = "This video doesn't have available captions or transcripts. Try another video that has captions enabled."
        elif "openai" in error_detail.lower():
            user_message = "Error communicating with OpenAI. Check your API key and internet connection."
        else:
            user_message = error_detail
            
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": user_message,
            "url": url,
            "year": datetime.now().year
        })
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error: {error_msg}")
        log_error("Unexpected error in summarize_video_form", e)
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": f"An unexpected error occurred: {error_msg}",
            "url": url,
            "year": datetime.now().year
        })