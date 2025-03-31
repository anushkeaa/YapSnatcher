"""Helper functions for debugging and logging"""
import sys
import traceback
from datetime import datetime

def log_error(message: str, exception: Exception = None):
    """Log error to console and error log file in a formatted way"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    error_message = f"[{timestamp}] ERROR: {message}\n"
    if exception:
        error_message += f"Exception: {str(exception)}\n"
        error_message += "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    
    # Print to console
    print(error_message, file=sys.stderr)
    
    # Also log to file
    try:
        with open("error_log.txt", "a") as f:
            f.write(error_message)
            f.write("\n" + "-"*80 + "\n")
    except:
        pass  # If file logging fails, just continue

    return error_message

def test_video_url(url: str) -> dict:
    """Test a YouTube URL for issues before attempting summary"""
    results = {"valid": False, "issues": []}
    
    # Test if URL is a valid YouTube URL
    import re
    patterns = [
        r'(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})',
    ]
    
    video_id = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            results["valid"] = True
            results["video_id"] = video_id
            break
    
    if not video_id:
        results["issues"].append("Invalid YouTube URL format")
        return results
    
    # Test if transcript is available
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        results["transcript_available"] = True
        results["transcript_length"] = len(transcript)
    except Exception as e:
        results["transcript_available"] = False
        results["transcript_error"] = str(e)
        results["issues"].append(f"Transcript unavailable: {str(e)}")
    
    # Test if video title can be retrieved
    try:
        import requests
        from bs4 import BeautifulSoup
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=headers)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_title = soup.find("meta", property="og:title")
            
            if meta_title and meta_title.get("content"):
                results["title_available"] = True
                results["title"] = meta_title["content"]
            else:
                results["title_available"] = False
                results["issues"].append("Unable to extract video title")
        else:
            results["title_available"] = False
            results["issues"].append(f"YouTube returned status code {response.status_code}")
    except Exception as e:
        results["title_available"] = False
        results["title_error"] = str(e)
        results["issues"].append(f"Title extraction error: {str(e)}")
    
    # Test if OpenAI API is configured
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            results["openai_configured"] = False
            results["issues"].append("OpenAI API key is missing")
        elif api_key.startswith("sk-"):
            results["openai_configured"] = True
        else:
            results["openai_configured"] = False
            results["issues"].append("OpenAI API key is invalid (should start with 'sk-')")
    except Exception as e:
        results["openai_configured"] = False
        results["openai_error"] = str(e)
        results["issues"].append(f"OpenAI configuration error: {str(e)}")
    
    return results
