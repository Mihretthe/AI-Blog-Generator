from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from .models import BlogPost

import google.generativeai as genai

from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi


# Create your views here.
@login_required
def index(request):
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):

    if request.method == "POST":
        try:
            data = json.loads(request.body)

            link = data['link']
            

            video_id = getVideoId(link)
            

            if not video_id:
                return JsonResponse({'error': "Invalid Url"}, status = 400)

            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
                answer = []
                for transc in transcript:
                    answer.append(transc['text'])

                transcript = " ".join(answer)
                

                content = generateBlogFromTranscription(transcript)[2:]
                
                new_article = BlogPost.objects.create(content = content, link = link, user = request.user)
                new_article.save()
                return JsonResponse({'content' : content})
            except:
                
                return JsonResponse({'error' : 'Error fetching transcript' })

            


        except (KeyError, json.JSONDecodeError):
            return JsonResponse({'error' : "Invalid data sent"}, status = 400)
        
def getVideoId(link):
    parsed_url = urlparse(link)

    if parsed_url.hostname in ["www.youtube.com", "youtube.com"]:
        return parse_qs(parsed_url.query).get("v", [None])[0]
    elif parsed_url.hostname in ["youtu.be"]:
        return parsed_url.path.lstrip("/")

    return None

        


def generateBlogFromTranscription(transcription):
    
    genai.configure(api_key="your_api_key")
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = f"""
            Based on the following transcript from a YouTube video, write a concise blog article of no more than 300 words. Ensure it is structured as a proper blog article and does not look like a YouTube video transcript:

            {transcription}
            
            Short Article:
            """
    try:
        response = model.generate_content(prompt)
    except Exception as e:
        print("Error: ", e)

    generated_content = response.text.strip()

    return generated_content

def user_login(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password'] 
                
        user = authenticate(request, username = username, password = password)
        if user:
            login(request, user)
            return redirect('/')
        
        else:
            error_message = "Credentials not Correct"
            return render(request, 'login.html', {'error_message' : error_message})


    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']
        
        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                print(user)
                user.save()
                login(request, user)
                return redirect('/')
            except:
                error_message = "Error Creating the User"
                return render(request, 'signup.html', {'error_message': error_message})

        else:
            error_message = "Password do not match."
            return render(request, 'signup.html', {'error_message': error_message})

    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')


def blog_list(request):
    articles = BlogPost.objects.filter(user=request.user)
    processed_articles = [
        {   
            'content' : article.content[1:],
            'title': article.content.split(":")[0],  # Extract the first part before ":"
            'id': article.id  # You can include other fields if needed
        }
        for article in articles
    ]
    return render(request, 'all-blogs.html', {'articles': processed_articles})

def blog_details(request, pk):
    blog_detail = BlogPost.objects.get(id = pk)
    if request.user == blog_detail.user:
        return render(request, 'blog-detail.html', {'blog_detail': blog_detail})
    return redirect('/')
