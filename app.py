
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory
import requests
import re
import logging
import time
import os
from urllib.parse import quote_plus
import instaloader

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- PWA Static Files Serving ---
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('.', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')
# --------------------------------

def get_file_size(url):
    """Get file size from URL."""
    try:
        resp = requests.head(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        size = int(resp.headers.get('content-length', 0))
        if size:
            return f"{size / (1024 * 1024):.2f} MB"
    except:
        pass
    return '0 MB'

def validate_instagram_url(url):
    """Validate Instagram URL."""
    try:
        u = url.strip().lower()
        patterns = [
            r'instagram\.com/p/[a-zA-Z0-9_-]+',
            r'instagram\.com/reel/[a-zA-Z0-9_-]+',
            r'instagram\.com/tv/[a-zA-Z0-9_-]+',
            r'instagram\.com/stories/[a-zA-Z0-9_.]+/?[a-zA-Z0-9_-]*/?',
            r'ig\.me/[a-zA-Z0-9_-]+',
        ]
        return any(re.search(p, u) for p in patterns) or re.fullmatch(r'[a-zA-Z0-9_-]{10,}', u)
    except:
        return False

def extract_post_id(url):
    """Extract post ID from URL."""
    u = url.strip()
    patterns = [
        r'instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_-]+)',
        r'ig\.me/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, u)
        if m:
            return m.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_-]{10,}', u):
        return u
    return None

def extract_with_instaloader(post_id):
    """Use Instaloader to extract post data."""
    try:
        logger.info(f"Trying Instaloader for post ID: {post_id}")
        
        L = instaloader.Instaloader()
        post = instaloader.Post.from_shortcode(L.context, post_id)
        
        media_list = []
        
        if post.typename == 'GraphSidecar':
            # Multiple media
            for i, node in enumerate(post.get_sidecar_nodes()):
                if node.is_video:
                    download_url = node.video_url
                    media_type = 'video'
                else:
                    download_url = node.display_url
                    media_type = 'image'
                
                filename = f"instagram_{post_id}_{i+1}.{'mp4' if media_type == 'video' else 'jpg'}"
                size = get_file_size(download_url)
                
                media_list.append({
                    'filename': filename,
                    'size': size,
                    'thumbnail': node.display_url,
                    'dlink': download_url,
                    'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
                    'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
                    'type': media_type
                })
        else:
            # Single media
            if post.is_video:
                download_url = post.video_url
                media_type = 'video'
            else:
                download_url = post.url
                media_type = 'image'
            
            try:
                thumbnail = post.url
            except AttributeError:
                thumbnail = download_url
            
            filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
            size = get_file_size(download_url)
            
            media_list.append({
                'filename': filename,
                'size': size,
                'thumbnail': thumbnail,
                'dlink': download_url,
                'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
                'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
                'type': media_type
            })
        
        logger.info(f"Success with Instaloader, {len(media_list)} media")
        return {'media': media_list}, None
        
    except Exception as e:
        logger.warning(f"Instaloader failed: {e}")
        return None, str(e)

def extract_with_instasocial(post_id):
    """Use InstaSocial - works with public posts."""
    try:
        logger.info(f"Trying InstaSocial for post ID: {post_id}")
        
        url = "https://www.instasocial.app/api/instagram/download"  # Updated URL to include www.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        payload = {
            "url": f"https://www.instagram.com/p/{post_id}/"
        }
        
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get('status'):
            return None, "Post not found"
        
        download_url = data.get('url') or data.get('download_url')
        if not download_url:
            return None, "No download URL"
        
        media_type = 'video' if 'mp4' in download_url.lower() else 'image'
        
        filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        media_list = [{
            'filename': filename,
            'size': size,
            'thumbnail': data.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }]
        logger.info("Success with InstaSocial")
        return {'media': media_list}, None
        
    except Exception as e:
        logger.warning(f"InstaSocial failed: {e}")
        return None, str(e)

def extract_with_imgdownloader(post_id):
    """Use ImgDownloader service."""
    try:
        logger.info(f"Trying ImgDownloader for post ID: {post_id}")
        
        url = "https://www.imgdownloader.com/api/instagram/download"  # Updated URL to include www.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "url": f"https://www.instagram.com/p/{post_id}/"
        }
        
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        download_url = data.get('url') or data.get('download_url')
        if not download_url:
            return None, "No download URL"
        
        media_type = 'video' if 'video' in download_url.lower() else 'image'
        
        filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        result = {
            'filename': filename,
            'size': size,
            'thumbnail': data.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }
        logger.info("Success with ImgDownloader")
        return result, None
        
    except Exception as e:
        logger.warning(f"ImgDownloader failed: {e}")
        return None, str(e)

def extract_with_dlpanda(post_id):
    """Use DLPanda service."""
    try:
        logger.info(f"Trying DLPanda for post ID: {post_id}")
        
        url = f"https://www.dlpanda.com/api/download?url=https://www.instagram.com/p/{post_id}/"  # Updated URL to include www.
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get('success'):
            return None, "Failed to fetch"
        
        download_url = data.get('url') or data.get('download_url')
        if not download_url:
            return None, "No download URL"
        
        media_type = 'video' if 'mp4' in download_url.lower() else 'image'
        
        filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        result = {
            'filename': filename,
            'size': size,
            'thumbnail': data.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }
        logger.info("Success with DLPanda")
        return result, None
        
    except Exception as e:
        logger.warning(f"DLPanda failed: {e}")
        return None, str(e)

def extract_with_instavery(post_id):
    """Use Instavery service."""
    try:
        logger.info(f"Trying Instavery for post ID: {post_id}")
        
        url = f"https://instavery.com/api/download?url={quote_plus(f'https://www.instagram.com/p/{post_id}/')}"  # Changed to GET with query param
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=15)  # Changed to GET
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get('success'):
            return None, "Post not found"
        
        download_url = data.get('url') or data.get('download_url')
        if not download_url:
            return None, "No download URL"
        
        media_type = 'video' if 'mp4' in download_url.lower() else 'image'
        
        filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        result = {
            'filename': filename,
            'size': size,
            'thumbnail': data.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }
        logger.info("Success with Instavery")
        return result, None
        
    except Exception as e:
        logger.warning(f"Instavery failed: {e}")
        return None, str(e)

def extract_with_igram(post_id):
    """Use iGram.world service."""
    try:
        logger.info(f"Trying iGram for post ID: {post_id}")
        
        url = f"https://igram.world/api/igram/{post_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get('status') or not data.get('data'):
            return None, "Post not found"
        
        media = data['data'][0]  # Assume first item
        download_url = media.get('url')
        if not download_url:
            return None, "No download URL"
        
        media_type = 'video' if media.get('type') == 'video' else 'image'
        
        filename = f"instagram_{post_id}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        result = {
            'filename': filename,
            'size': size,
            'thumbnail': media.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }
        logger.info("Success with iGram")
        return result, None
        
    except Exception as e:
        logger.warning(f"iGram failed: {e}")
        return None, str(e)

def extract_story_data(url):
    """Extract Instagram story data using StoriesIG."""
    try:
        logger.info(f"Trying StoriesIG for story URL: {url}")
        
        api_url = f"https://storiesig.com/api/ig/story?url={quote_plus(url)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get('status') or not data.get('data'):
            return None, "Story not found or private"
        
        # Take the first media item
        media = data['data'][0]
        download_url = media.get('url')
        if not download_url:
            return None, "No download URL"
        
        media_type = media.get('type', 'image')  # 'video' or 'image'
        
        filename = f"instagram_story_{int(time.time())}.{'mp4' if media_type == 'video' else 'jpg'}"
        size = get_file_size(download_url)
        
        result = {
            'filename': filename,
            'size': size,
            'thumbnail': media.get('thumbnail') or download_url,
            'dlink': download_url,
            'stream_url': f"/api/stream?url={quote_plus(download_url)}" if media_type == 'video' else None,
            'proxy_download': f"/api/download?url={quote_plus(download_url)}&filename={filename}",
            'type': media_type
        }
        logger.info("Success with StoriesIG")
        return result, None
        
    except Exception as e:
        logger.warning(f"StoriesIG failed: {e}")
        return None, str(e)

def extract_instagram_data(url):
    """Extract with multiple free API methods."""
    try:
        if 'stories' in url.lower():
            # Handle stories
            result, error = extract_story_data(url)
            if result:
                return result, None
            return None, error or "Unable to download story. Ensure the story is public and try again."
        
        # Handle posts/reels
        post_id = extract_post_id(url)
        if not post_id:
            return None, "Unable to extract Instagram post ID"
        
        logger.info(f"Extracted post ID: {post_id}")
        
        methods = [
            extract_with_instaloader,
            extract_with_instasocial,
            extract_with_dlpanda,
            extract_with_instavery,
            extract_with_imgdownloader,
            extract_with_igram,  # Added new method
        ]
        
        for method in methods:
            try:
                result, error = method(post_id)
                if result:
                    return result, None
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"{method.__name__} error: {e}")
                continue
        
        return None, "Unable to download. Ensure the post is public and try again."
        
    except Exception as e:
        logger.error(f"Extraction Error: {str(e)}")
        return None, "Server error. Please try again."

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/extract', methods=['POST'])
def handle_extract():
    try:
        data = request.get_json(force=True)
        url = (data.get('url') or '').strip()
        
        if not url:
            return jsonify({'error': 'Please provide an Instagram link.'}), 400
        
        if not validate_instagram_url(url):
            return jsonify({'error': 'Invalid Instagram URL.'}), 400
        
        result, error = extract_instagram_data(url)
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Extract error: {e}")
        return jsonify({'error': 'Server error.'}), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'ok'})

@app.route('/api/stream', methods=['GET'])
def proxy_stream():
    """Stream video through proxy."""
    remote = request.args.get('url')
    if not remote:
        return jsonify({'error': 'Missing url'}), 400
    try:
        resp = requests.get(remote, stream=True, timeout=25, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.instagram.com/'
        })
        resp.raise_for_status()
        headers = {k: v for k, v in resp.headers.items() if k.lower() in ['content-type', 'content-length']}
        return Response(stream_with_context(resp.iter_content(8192)), headers=headers)
    except Exception as e:
        logger.error(f"Stream error: {e}")
        return jsonify({'error': 'Stream failed'}), 500

@app.route('/api/download', methods=['GET'])
def proxy_download():
    """Download through proxy."""
    remote = request.args.get('url')
    filename = request.args.get('filename', 'instagram_media')
    if not remote:
        return jsonify({'error': 'Missing url'}), 400
    try:
        resp = requests.get(remote, stream=True, timeout=25, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.instagram.com/'
        })
        resp.raise_for_status()
        headers = {k: v for k, v in resp.headers.items() if k.lower() in ['content-type', 'content-length']}
        safe_name = "".join(c for c in filename if c.isalnum() or c in '._- ')[:100]
        headers['Content-Disposition'] = f'attachment; filename="{safe_name}"'
        return Response(stream_with_context(resp.iter_content(8192)), headers=headers)
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': 'Download failed'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
