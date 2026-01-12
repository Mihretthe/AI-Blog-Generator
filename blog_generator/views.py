from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json, os
import traceback

from .models import BlogPost

# ────────────────────────────────────────────────
#   GOOGLE GEMINI – modern SDK style
# ────────────────────────────────────────────────
from google import genai
from google.genai import types

from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled


# ────────────────────────────────────────────────
#   VIEWS
# ────────────────────────────────────────────────

@login_required
def index(request):
    return render(request, 'index.html')


@csrf_exempt
def generate_blog(request):
    if request.method != "POST":
        return JsonResponse({'error': "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        link = data.get('link')

        if not link:
            return JsonResponse({'error': "No link provided"}, status=400)

        video_id = get_video_id(link)
        if not video_id:
            return JsonResponse({'error': "Invalid YouTube URL"}, status=400)

        # ── Modern & safer transcript fetching ───────────────────────────────
        try:
            # Option A: Simple & returns old dict format (recommended for compatibility)
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
            transcript_text = " ".join(
                entry['text'].strip() for entry in transcript_data
            )

            # Option B: More control (uncomment if you prefer manual language fallback)
            # transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            # try:
            #     transcript = transcript_list.find_manually_created_transcript(['en'])
            # except NoTranscriptFound:
            #     try:
            #         transcript = transcript_list.find_generated_transcript(['en'])
            #     except NoTranscriptFound:
            #         transcript = next(iter(transcript_list))
            # transcript_data = transcript.fetch()
            # transcript_text = " ".join(snippet.text.strip() for snippet in transcript_data)

            print(f"Transcript fetched successfully – length: {len(transcript_text)} chars")

        except (NoTranscriptFound, TranscriptsDisabled):
            return JsonResponse({'error': 'No English transcript available (captions may be disabled)'}, status=400)
        except Exception as e:
            print("Transcript error:", traceback.format_exc())
            return JsonResponse({'error': 'Could not fetch transcript'}, status=400)

        # ── Generate blog ────────────────────────────────────────────────────
        try:
            content = generate_blog_from_transcript(transcript_text)
            if not content.strip():
                return JsonResponse({'error': 'Generated content was empty'}, status=500)
        except Exception as gen_err:
            print("Generation failed:", traceback.format_exc())
            return JsonResponse({'error': f'Failed to generate blog: {str(gen_err)}'}, status=500)

        # Save
        new_article = BlogPost.objects.create(
            content=content,
            link=link,
            user=request.user
        )

        return JsonResponse({
            'success': True,
            'content': content,
            'id': new_article.id
        })

    except (KeyError, json.JSONDecodeError):
        return JsonResponse({'error': "Invalid JSON data"}, status=400)
    except Exception as e:
        print("Unexpected error:", traceback.format_exc())
        return JsonResponse({'error': 'Server error'}, status=500)


def get_video_id(link):
    """Extract YouTube video ID from various URL formats"""
    parsed = urlparse(link)
    hostname = parsed.hostname

    if hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return parse_qs(parsed.query).get("v", [None])[0]

    if hostname == "youtu.be":
        return parsed.path.lstrip('/')

    return None


def generate_blog_from_transcript(transcript: str) -> str:
    """
    IMPORTANT: Use environment variable in production!
    Never commit API keys to git.
    """
    # Recommended in production:
    # import os
    # api_key = os.getenv("GEMINI_API_KEY")
    api_key = os.getenv("GEMINI_API_KEY")  # ← REPLACE or REMOVE

    if not api_key:
        raise ValueError("No Gemini API key provided")

    client = genai.Client(api_key=api_key)

    prompt = f"""Based on the following YouTube video transcript, write a well-structured, concise blog article (250–300 words max).

Use proper blog format:
- Engaging title (start with # )
- Introduction paragraph
- Main sections with ## subheadings
- Bullet points or short paragraphs where appropriate
- Conclusion

Do NOT include timestamps, speaker names, or anything that makes it look like a transcript.
Write in natural, flowing English as an original blog post.
Use markdown formatting for better readability (headings, bold, etc.).

Transcript:
{transcript}

Full Blog Post:"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # This is valid in Jan 2026
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=1500,       # ↑ increased to allow full 300-word + formatting
                temperature=0.7,
                top_p=0.95,
                top_k=40,
            ),
        )

        text = response.text.strip()  # Just strip outer whitespace – KEEP newlines!

        # Debug: see what we really got
        print("Raw generated length:", len(text))
        print("Generated preview (first 300 chars):", text[:300])

        return text

    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {type(e).__name__} – {str(e)}")

# ────────────────────────────────────────────────
#   AUTH VIEWS
# ────────────────────────────────────────────────

def user_login(request):
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('index')

        return render(request, 'login.html', {'error_message': "Invalid credentials"})

    return render(request, 'login.html')


def user_signup(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        repeat_password = request.POST.get('repeatPassword')

        if password != repeat_password:
            return render(request, 'signup.html', {'error_message': "Passwords do not match"})

        try:
            user = User.objects.create_user(username, email, password)
            user.save()
            login(request, user)
            return redirect('index')
        except Exception as e:
            print("Signup error:", str(e))
            return render(request, 'signup.html', {'error_message': "Username already taken or invalid data"})

    return render(request, 'signup.html')


def user_logout(request):
    logout(request)
    return redirect('index')


@login_required
def blog_list(request):
    articles = BlogPost.objects.filter(user=request.user).order_by('-id')

    processed = []
    for article in articles:
        lines = article.content.split('\n', 2)
        title = lines[0].strip() if lines else "Untitled"
        if title.startswith('# '):
            title = title[2:].strip()

        processed.append({
            'id': article.id,
            'title': title,
            'content_preview': article.content[:220] + '...' if len(article.content) > 220 else article.content,
            'link': article.link,
            'created': getattr(article, 'created_at', None)
        })

    return render(request, 'all-blogs.html', {'articles': processed})


@login_required
def blog_details(request, pk):
    try:
        blog = BlogPost.objects.get(id=pk)
        if blog.user != request.user:
            return redirect('index')
        return render(request, 'blog-detail.html', {'blog_detail': blog})
    except BlogPost.DoesNotExist:
        return redirect('blog_list')