"""
Runtime patches for pytube to handle YouTube API changes.
This module applies monkey patches to pytube without modifying its source files.
"""
import re
import logging

logger = logging.getLogger(__name__)

def apply_patches():
    """Apply all available pytube patches at runtime"""
    try:
        logger.info("Applying pytube patches")
        
        # Patch 1: Fix cipher function detection
        try:
            from pytube import cipher
            if hasattr(cipher, "get_initial_function_name"):
                original_get_initial_function_name = cipher.get_initial_function_name
                
                def patched_get_initial_function_name(js):
                    try:
                        return original_get_initial_function_name(js)
                    except Exception as e:
                        logger.warning(f"Original get_initial_function_name failed: {e}")
                        # Try a different pattern
                        pattern = r'(?:a=a\.split\(""\);(.*?)\.join\(""\))'
                        results = re.search(pattern, js)
                        if results:
                            return results.group(1).split(".")[-1]
                        else:
                            # Another pattern that sometimes works
                            pattern = r'(?:a=a\.split\(""\);).*?\..*?\..*?\(a,([a-zA-Z0-9$]+)\)'
                            results = re.search(pattern, js)
                            if results:
                                return results.group(1)
                            # Fallback to the original error
                            raise
                
                cipher.get_initial_function_name = patched_get_initial_function_name
                logger.info("Patched cipher.get_initial_function_name")
        except Exception as e:
            logger.error(f"Failed to patch cipher.get_initial_function_name: {e}")
        
        # Patch 2: Fix regex extraction patterns
        try:
            from pytube import extract
            if hasattr(extract, "video_id"):
                original_video_id = extract.video_id
                
                def patched_video_id(url):
                    try:
                        return original_video_id(url)
                    except Exception:
                        # Try a more generous pattern
                        patterns = [
                            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
                            r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
                            r'(?:shorts\/)([0-9A-Za-z_-]{11})',
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, url)
                            if match:
                                return match.group(1)
                        # Fallback to original error
                        return original_video_id(url)
                
                extract.video_id = patched_video_id
                logger.info("Patched extract.video_id")
        except Exception as e:
            logger.error(f"Failed to patch extract.video_id: {e}")
        
        logger.info("Pytube patches applied successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to apply pytube patches: {e}")
        return False

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    # Apply patches when run directly
    success = apply_patches()
    print(f"Patch application {'succeeded' if success else 'failed'}")
