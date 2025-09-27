import os
import torch
import clip
from PIL import Image, ImageOps
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from .models import *
from django.utils import timezone
from django.core.files.storage import default_storage
from decimal import Decimal
import numpy as np
import time
import json
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q



device = "cuda" if torch.cuda.is_available() else "cpu"
model, preprocess = clip.load("ViT-L/14", device=device)

def home(request):
    return render(request, 'index.html')

def admin_dashboard(request):
    return render(request, 'admin_dashboard.html')


def chat_room(request):
    """Chat room page"""
    if 'current_chat' not in request.session:
        messages.error(request, "No active chat.")
        return redirect("owner_dashboard")
    
    chat_info = request.session['current_chat']
    
    # Get current user
    if request.user.is_authenticated:
        user = request.user
    else:
        user_id = request.session.get("user_id")
        user = AppUser.objects.get(id=user_id) if user_id else None

    if not user:
        messages.error(request, "You must be logged in.")
        return redirect("login")

    context = {
        'chat_info': chat_info,
        'current_user_id': user.id
    }
    
    return render(request, 'chat_room.html', context)


def start_chat(request, item_id):
    """Start chat with item owner/finder"""
    if request.method == "POST":
        try:
            # Get current user
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                messages.error(request, "You must be logged in to chat.")
                return redirect("login")

            # Get the item being discussed
            item = Item.objects.get(id=item_id)
            
            # Can't chat with yourself
            if item.owner == user:
                messages.error(request, "You can't chat with yourself.")
                return redirect("owner_dashboard")

            # Determine who is the other user
            other_user = item.owner

            # Store chat info in session - BOTH users should chat about the SAME item
            request.session['current_chat'] = {
                'item_id': item.id,  # This is the item they're discussing
                'item_title': item.title,
                'other_user_id': other_user.id,
                'other_user_name': other_user.username
            }
            
            
            return redirect("chat_room")

        except Item.DoesNotExist:
            messages.error(request, "Item not found.")
            return redirect("owner_dashboard")
        except Exception as e:
            print(f"Error starting chat: {e}")
            messages.error(request, "Error starting chat.")
            return redirect("owner_dashboard")

    return redirect("owner_dashboard")


def send_message(request):
    """Send a chat message"""
    if request.method == "POST":
        try:
            # Get current user
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                return JsonResponse({'success': False, 'error': 'Not logged in'})

            if 'current_chat' not in request.session:
                return JsonResponse({'success': False, 'error': 'No active chat'})

            chat_info = request.session['current_chat']
            message_text = request.POST.get('message', '').strip()

            if not message_text:
                return JsonResponse({'success': False, 'error': 'Empty message'})

            # Get item and receiver
            item = Item.objects.get(id=chat_info['item_id'])
            receiver = AppUser.objects.get(id=chat_info['other_user_id'])

            # Create message
            chat = Chat.objects.create(
                sender=user,
                receiver=receiver,
                item=item,
                message=message_text
            )

            print(f"Message created: ID={chat.id}, From={user.username}({user.id}), To={receiver.username}({receiver.id}), Item={item.id}")

            return JsonResponse({
                'success': True,
                'message_id': chat.id
            })

        except Exception as e:
            print(f"Error sending message: {e}")
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})


def get_messages(request):
    """Get all chat messages between current user and other user"""
    try:
        # Get current user
        if request.user.is_authenticated:
            user = request.user
        else:
            user_id = request.session.get("user_id")
            user = AppUser.objects.get(id=user_id) if user_id else None

        if not user:
            return JsonResponse({'success': False, 'error': 'Not logged in'})

        if 'current_chat' not in request.session:
            return JsonResponse({'success': False, 'error': 'No active chat'})

        chat_info = request.session['current_chat']
        other_user_id = chat_info['other_user_id']
        other_user = AppUser.objects.get(id=other_user_id)
        
        # Get ALL messages between these two users (regardless of item)
        # This way both users see the same conversation thread
        messages = Chat.objects.filter(
            models.Q(sender=user, receiver=other_user) |
            models.Q(sender=other_user, receiver=user)
        ).order_by('sent_at')
        
        
        messages_data = []
        for msg in messages:
            is_own_message = msg.sender.id == user.id
            
            messages_data.append({
                'id': msg.id,
                'sender': msg.sender.username,
                'message': msg.message,
                'sent_at': msg.sent_at.strftime('%H:%M'),
                'is_own': is_own_message,
                'item_title': msg.item.title  # Show which item they're talking about
            })

        # Mark messages sent TO current user as read
        Chat.objects.filter(receiver=user, sender=other_user, is_read=False).update(is_read=True)

        return JsonResponse({'success': True, 'messages': messages_data})

    except Exception as e:
        print(f"Error getting messages: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

def update_item_status(request):
    """Update item status from chat"""
    if request.method == "POST":
        try:
            # Get current user
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                return JsonResponse({'success': False, 'error': 'Not logged in'})

            if 'current_chat' not in request.session:
                return JsonResponse({'success': False, 'error': 'No active chat'})

            chat_info = request.session['current_chat']
            new_status = request.POST.get('status')

            if new_status not in ['recovered', 'closed']:
                return JsonResponse({'success': False, 'error': 'Invalid status'})

            # Get the item being discussed
            item = Item.objects.get(id=chat_info['item_id'])

            # Update item status - NO AUTHORIZATION CHECK for now
            old_status = item.status
            item.status = 'recovered'
            item.save()

            print(f"✅ Item {item.id} '{item.title}' status updated from '{old_status}' to '{new_status}' by {user.username}({user.id})")

            return JsonResponse({
                'success': True, 
                'status': new_status, 
                'updated_by': user.username,
                'item_title': item.title
            })

        except Exception as e:
            print(f"❌ Error updating item status: {e}")
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request'})

def owner_dashboard(request):
    # Get current user
    if request.user.is_authenticated:
        user = request.user
    else:
        user_id = request.session.get("user_id")
        user = AppUser.objects.get(id=user_id) if user_id else None
    
    context = {}
    
    if user:
        # Get user's items with images
        user_items = Item.objects.filter(owner=user).prefetch_related('images').order_by('-date_lost')
        context['user_items'] = user_items
    
    return render(request, 'owner_dashboard.html', context)


def delete_item(request, item_id):
    if request.method == "POST":
        try:
            # Get current user
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                messages.error(request, "You must be logged in.")
                return redirect("login")

            # Get item and verify ownership
            item = Item.objects.get(id=item_id, owner=user)
            item.delete()
            
            messages.success(request, "Item deleted successfully!")
            
        except Item.DoesNotExist:
            messages.error(request, "Item not found.")
        except Exception as e:
            messages.error(request, "Error deleting item.")
    
    return redirect("owner_dashboard")


# -------------------
# Signup
# -------------------
def signup(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        aadhaar = request.POST.get("aadhaar")
        phone = request.POST.get("phone")
        district = request.POST.get("district")

        if AppUser.objects.filter(username=username).exists():
            messages.error(request, "Username already taken")
            return redirect("signup")

        if AppUser.objects.filter(email=email).exists():
            messages.error(request, "Email already registered")
            return redirect("signup")

        AppUser.objects.create(
            username=username,
            email=email,
            password=password,  # plaintext, simple for hackathon
            aadhaar=aadhaar,
            phone=phone,
            district=district
        )
        messages.success(request, "Signup successful. Please login.")
        return redirect("login")

    return render(request, "signup.html")


# -------------------
# Login
# -------------------
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        try:
            user = AppUser.objects.get(username=username, password=password)
            request.session['user_id'] = user.id  # store logged-in user in session
            return redirect("owner_dashboard")
        except AppUser.DoesNotExist:
            messages.error(request, "Invalid username or password")
            return redirect("login")

    # GET request just renders login page
    return render(request, "login.html")


# -------------------
# Logout
# -------------------
def logout_view(request):
    request.session.flush()  # clear session
    messages.success(request, "Logged out successfully.")
    return redirect("login")



# -------------------------------
# CLIP Setup (Load once at startup)
# -------------------------------
try:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-L/14", device=device)
except Exception as e:
    print(f"Warning: CLIP model failed to load: {e}")
    model, preprocess = None, None

# -------------------------------
# Image Preprocessing
# -------------------------------
def clean_image(img_path):
    try:
        img = Image.open(img_path).convert("RGB")
        img = ImageOps.exif_transpose(img)
        img = ImageOps.autocontrast(img)
        return preprocess(img).unsqueeze(0).to(device)
    except Exception as e:
        print(f"Error processing image {img_path}: {e}")
        return None

def clear_search_results(request):
    if 'search_results' in request.session:
        del request.session['search_results']
    return redirect("owner_dashboard")

def search_similarity(request, item_id):
    if request.method == "POST":
        try:
            # --- Get User ---
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                messages.error(request, "You must be logged in.")
                return redirect("login")

            # Get the item and verify ownership
            search_item = Item.objects.get(id=item_id, owner=user)
            
            if not search_item.images.exists():
                messages.error(request, "This item has no images to search with.")
                return redirect("owner_dashboard")

            # --- CLIP Similarity Search ---
            SIMILARITY_THRESHOLD = 60.0  # Lowered for combined scoring
            TOP_N = 3
            
            start_time = time.time()
            results = []

            # Get search item's first image
            search_image = search_item.images.first()
            
            # Generate embedding if it doesn't exist
            if not search_image.embedding:
                print(f"Generating embedding for {search_item.status} item image...")
                if model and preprocess:
                    try:
                        abs_path = os.path.join(settings.MEDIA_ROOT, str(search_image.image))
                        tensor = clean_image(abs_path)
                        if tensor is not None:
                            with torch.no_grad():
                                features = model.encode_image(tensor)
                            features /= features.norm(dim=-1, keepdim=True)
                            
                            # Save embedding to database
                            search_image.embedding = features.cpu().numpy().flatten().tolist()
                            search_image.save()
                            print("Search item embedding generated and saved")
                        else:
                            messages.error(request, "Error processing item image.")
                            return redirect("owner_dashboard")
                    except Exception as e:
                        print(f"Error generating search item embedding: {e}")
                        messages.error(request, "Error processing item image.")
                        return redirect("owner_dashboard")
                else:
                    messages.error(request, "Image processing model not available.")
                    return redirect("owner_dashboard")

            # Convert image embedding to tensor
            search_embedding = np.array(search_image.embedding)
            search_embedding = torch.tensor(search_embedding).to(device)
            search_embedding /= search_embedding.norm(dim=-1, keepdim=True)

            # Generate text embedding for search item description
            search_text = f"{search_item.title} {search_item.description}".strip()
            search_text_token = clip.tokenize([search_text]).to(device)
            with torch.no_grad():
                search_text_features = model.encode_text(search_text_token)
            search_text_features /= search_text_features.norm(dim=-1, keepdim=True)

            # Determine what to search against based on item status
            if search_item.status == 'active':  # Lost item - search found items
                target_items = Item.objects.filter(status='found').exclude(owner=user).prefetch_related('images')
                search_type = "lost_searching_found"
                action_text = "potential matches"
            else:  # Found item - search lost items
                target_items = Item.objects.filter(status='active').exclude(owner=user).prefetch_related('images')
                search_type = "found_searching_lost"
                action_text = "potential owners"
            
            for target_item in target_items:
                if target_item.images.exists():
                    target_image = target_item.images.first()
                    
                    # Generate image embedding if it doesn't exist
                    if not target_image.embedding:
                        print(f"Generating embedding for target item {target_item.id}...")
                        if model and preprocess:
                            try:
                                abs_path = os.path.join(settings.MEDIA_ROOT, str(target_image.image))
                                tensor = clean_image(abs_path)
                                if tensor is not None:
                                    with torch.no_grad():
                                        features = model.encode_image(tensor)
                                    features /= features.norm(dim=-1, keepdim=True)
                                    
                                    # Save embedding to database
                                    target_image.embedding = features.cpu().numpy().flatten().tolist()
                                    target_image.save()
                                    print(f"Target item {target_item.id} embedding generated")
                                else:
                                    print(f"Error processing target item {target_item.id} image")
                                    continue
                            except Exception as e:
                                print(f"Error generating embedding for target item {target_item.id}: {e}")
                                continue
                        else:
                            print("Model not available, skipping target item")
                            continue
                    
                    # Now compare both image and text embeddings
                    if target_image.embedding:
                        try:
                            # Image similarity
                            target_embedding = np.array(target_image.embedding)
                            target_embedding = torch.tensor(target_embedding).to(device)
                            target_embedding /= target_embedding.norm(dim=-1, keepdim=True)
                            
                            image_similarity = (search_embedding @ target_embedding.T).item()
                            
                            # Text similarity
                            target_text = f"{target_item.title} {target_item.description}".strip()
                            target_text_token = clip.tokenize([target_text]).to(device)
                            with torch.no_grad():
                                target_text_features = model.encode_text(target_text_token)
                            target_text_features /= target_text_features.norm(dim=-1, keepdim=True)
                            
                            text_similarity = (search_text_features @ target_text_features.T).item()
                            
                            # Combined similarity score (weighted average)
                            # Image gets 70% weight, text gets 30% weight
                            combined_similarity = (image_similarity * 0.7) + (text_similarity * 0.3)
                            combined_similarity_percent = combined_similarity * 100
                            
                            print(f"Item {target_item.id}: Image={image_similarity*100:.1f}%, Text={text_similarity*100:.1f}%, Combined={combined_similarity_percent:.1f}%")
                            
                            if combined_similarity_percent >= SIMILARITY_THRESHOLD:
                                results.append({
                                    'item': target_item,
                                    'similarity': combined_similarity_percent,
                                    'image_similarity': image_similarity * 100,
                                    'text_similarity': text_similarity * 100
                                })
                                
                        except Exception as e:
                            print(f"Error comparing with item {target_item.id}: {e}")
                            continue

            # Sort by combined similarity (highest first) and get top N
            results.sort(key=lambda x: x['similarity'], reverse=True)
            results = results[:TOP_N]

            end_time = time.time()
            print(f"⏱ Similarity search completed in {end_time - start_time:.3f}s")

            if results:
                # Store results in session for display
                request.session['search_results'] = {
                    'search_item_id': search_item.id,
                    'search_type': search_type,
                    'matches': [
                        {
                            'id': r['item'].id,
                            'title': r['item'].title,
                            'similarity': round(r['similarity'], 1),
                            'image_similarity': round(r['image_similarity'], 1),
                            'text_similarity': round(r['text_similarity'], 1),
                            'location': r['item'].location_name,
                            'date': r['item'].date_lost.strftime('%Y-%m-%d'),
                            'image_url': r['item'].images.first().image.url if r['item'].images.exists() else None,
                            'status': r['item'].status
                        }
                        for r in results
                    ]
                }
                
                messages.success(request, f"🔍 Found {len(results)} {action_text}! Check below.")
            else:
                messages.warning(request, f"❌ No {action_text} found above {SIMILARITY_THRESHOLD}% similarity.")

        except Item.DoesNotExist:
            messages.error(request, "Item not found or you don't have permission.")
        except Exception as e:
            print(f"Error in search_similarity: {e}")
            messages.error(request, "An error occurred during the search.")
    
    return redirect("owner_dashboard")


def regenerate_embeddings(request):
    """Utility function to regenerate all missing embeddings - call this once if needed"""
    if not (request.user.is_authenticated and request.user.is_staff):
        messages.error(request, "Permission denied.")
        return redirect("home")
    
    if model and preprocess:
        images_without_embeddings = ItemImage.objects.filter(embedding=[])
        count = 0
        
        for item_image in images_without_embeddings:
            try:
                abs_path = os.path.join(settings.MEDIA_ROOT, str(item_image.image))
                if os.path.exists(abs_path):
                    tensor = clean_image(abs_path)
                    if tensor is not None:
                        with torch.no_grad():
                            features = model.encode_image(tensor)
                        features /= features.norm(dim=-1, keepdim=True)
                        
                        item_image.embedding = features.cpu().numpy().flatten().tolist()
                        item_image.save()
                        count += 1
                        print(f"Generated embedding for image {item_image.id}")
            except Exception as e:
                print(f"Error processing image {item_image.id}: {e}")
                continue
        
        messages.success(request, f"Generated {count} embeddings successfully!")
    else:
        messages.error(request, "CLIP model not available.")
    
    return redirect("admin_dashboard")

# -------------------------------
# Report Lost Item View
# -------------------------------
def report_lost_item(request):
    if request.method == "POST":
        try:
            # --- Get User ---
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                messages.error(request, "You must be logged in to report a lost item.")
                return redirect("login")

            # --- Collect Form Data (only use what exists in model) ---
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            location_name = request.POST.get("location_name", "").strip()
            reward_amount = request.POST.get("reward_amount", "0") or "0"
            date_lost = request.POST.get("date_lost")
            priority_boost = request.POST.get("priority_boost") == "1"

            # Get coordinates
            try:
                lat = float(request.POST.get("latitude") or 0.0)
                lng = float(request.POST.get("longitude") or 0.0)
            except (ValueError, TypeError):
                lat = 0.0
                lng = 0.0

            # Validate required fields
            if not all([title, description, location_name]):
                messages.error(request, "Please fill in all required fields.")
                return render(request, "owner_dashboard.html")

            # Parse date
            try:
                if date_lost:
                    date_lost = timezone.datetime.strptime(date_lost, "%Y-%m-%d")
                else:
                    date_lost = timezone.now()
            except ValueError:
                date_lost = timezone.now()

            # Parse reward amount
            try:
                reward_amount = Decimal(reward_amount)
            except:
                reward_amount = Decimal("0.00")

            # --- Create Lost Item (only with existing fields) ---
            lost_item = Item.objects.create(
                owner=user,
                title=title,
                description=description,
                location_name=location_name,
                location_lat=lat,
                location_lng=lng,
                status="active",
                date_lost=date_lost,
                reward_amount=reward_amount,
                boost=priority_boost
            )

            # --- Save Images + Extract Embeddings ---
            images = request.FILES.getlist("images")
            
            for img in images:
                try:
                    # Save file
                    file_path = default_storage.save(f"items/{img.name}", img)
                    abs_path = os.path.join(settings.MEDIA_ROOT, file_path)

                    # Create ItemImage record first
                    item_image = ItemImage.objects.create(
                        item=lost_item,
                        image=file_path,
                        embedding=[]  # Initialize with empty list
                    )

                    # Encode image if CLIP model is available
                    if model and preprocess:
                        tensor = clean_image(abs_path)
                        if tensor is not None:
                            with torch.no_grad():
                                features = model.encode_image(tensor)
                            features /= features.norm(dim=-1, keepdim=True)
                            
                            # Update with embedding
                            item_image.embedding = features.cpu().numpy().flatten().tolist()
                            item_image.save()

                except Exception as e:
                    print(f"Error processing image {img.name}: {e}")
                    continue

            messages.success(request, "✅ Lost item reported successfully!")
            return redirect("owner_dashboard")

        except Exception as e:
            print(f"Error in report_lost_item: {e}")
            messages.error(request, "An error occurred while reporting your item. Please try again.")
            return render(request, "owner_dashboard.html")

    return redirect("owner_dashboard")


def report_found_item(request):
    if request.method == "POST":
        try:
            # --- Get User ---
            if request.user.is_authenticated:
                user = request.user
            else:
                user_id = request.session.get("user_id")
                user = AppUser.objects.get(id=user_id) if user_id else None

            if not user:
                messages.error(request, "You must be logged in to report a found item.")
                return redirect("login")

            # --- Collect Form Data ---
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            location_name = request.POST.get("location_name", "").strip()
            date_found = request.POST.get("date_found")

            # Get coordinates
            try:
                lat = float(request.POST.get("latitude") or 0.0)
                lng = float(request.POST.get("longitude") or 0.0)
            except (ValueError, TypeError):
                lat = 0.0
                lng = 0.0

            # Validate required fields
            if not all([title, description, location_name]):
                messages.error(request, "Please fill in all required fields.")
                return render(request, "owner_dashboard.html")

            # Parse date
            try:
                if date_found:
                    date_found = timezone.datetime.strptime(date_found, "%Y-%m-%d")
                else:
                    date_found = timezone.now()
            except ValueError:
                date_found = timezone.now()

            # --- Create Found Item ---
            found_item = Item.objects.create(
                owner=user,
                title=title,
                description=description,
                location_name=location_name,
                location_lat=lat,
                location_lng=lng,
                status="found",
                date_lost=date_found,  # Using date_lost field for found date
                reward_amount=0.00,    # Found items don't have rewards
                boost=False            # Found items don't have boost
            )

            # --- Save Images + Extract Embeddings ---
            images = request.FILES.getlist("images")
            
            for img in images:
                try:
                    # Save file
                    file_path = default_storage.save(f"items/{img.name}", img)
                    abs_path = os.path.join(settings.MEDIA_ROOT, file_path)

                    # Create ItemImage record first
                    item_image = ItemImage.objects.create(
                        item=found_item,
                        image=file_path,
                        embedding=[]  # Initialize with empty list
                    )

                    # Encode image if CLIP model is available
                    if model and preprocess:
                        tensor = clean_image(abs_path)
                        if tensor is not None:
                            with torch.no_grad():
                                features = model.encode_image(tensor)
                            features /= features.norm(dim=-1, keepdim=True)
                            
                            # Update with embedding
                            item_image.embedding = features.cpu().numpy().flatten().tolist()
                            item_image.save()

                except Exception as e:
                    print(f"Error processing image {img.name}: {e}")
                    continue

            messages.success(request, "✅ Found item reported successfully!")
            return redirect("owner_dashboard")

        except Exception as e:
            print(f"Error in report_found_item: {e}")
            messages.error(request, "An error occurred while reporting the found item. Please try again.")
            return render(request, "owner_dashboard.html")

    return redirect("owner_dashboard")

def lost_items(request):
    """Display all lost items with filters"""
    # Get all active lost items
    items = Item.objects.filter(status='active').select_related('owner').prefetch_related('images').order_by('-date_lost')
    
    # Apply filters
    search_query = request.GET.get('search', '').strip()
    if search_query:
        items = items.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(location_name__icontains=search_query)
        )
    
    # District filter
    district = request.GET.get('district', '').strip()
    if district:
        items = items.filter(location_name__icontains=district)
    
    # Date filter
    date_filter = request.GET.get('date_filter', '').strip()
    if date_filter:
        if date_filter == 'today':
            from datetime import date
            items = items.filter(date_lost__date=date.today())
        elif date_filter == 'week':
            from datetime import date, timedelta
            week_ago = date.today() - timedelta(days=7)
            items = items.filter(date_lost__date__gte=week_ago)
        elif date_filter == 'month':
            from datetime import date, timedelta
            month_ago = date.today() - timedelta(days=30)
            items = items.filter(date_lost__date__gte=month_ago)
    
    # Reward filter
    has_reward = request.GET.get('reward', '').strip()
    if has_reward == 'yes':
        items = items.filter(reward_amount__gt=0)
    
    # Pagination
    paginator = Paginator(items, 12)  # 12 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'selected_district': district,
        'selected_date_filter': date_filter,
        'selected_reward': has_reward,
        'total_items': items.count()
    }
    
    return render(request, 'lost_items.html', context)


def item_detail(request, item_id):
    """Display single item detail"""
    try:
        item = Item.objects.select_related('owner').prefetch_related('images').get(id=item_id)
        
        # Get current user for chat button
        if request.user.is_authenticated:
            user = request.user
        else:
            user_id = request.session.get("user_id")
            user = AppUser.objects.get(id=user_id) if user_id else None
        
        context = {
            'item': item,
            'can_chat': user and user != item.owner,  # Can't chat with yourself
            'current_user': user
        }
        
        return render(request, 'item_detail.html', context)
        
    except Item.DoesNotExist:
        messages.error(request, "Item not found.")
        return redirect("lost_items")

def found_items(request):
    """Display all found items with filters"""
    # Get all found items
    items = Item.objects.filter(status='found').select_related('owner').prefetch_related('images').order_by('-date_lost')
    
    # Apply filters
    search_query = request.GET.get('search', '').strip()
    if search_query:
        items = items.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(location_name__icontains=search_query)
        )
    
    # District filter
    district = request.GET.get('district', '').strip()
    if district:
        items = items.filter(location_name__icontains=district)
    
    # Date filter
    date_filter = request.GET.get('date_filter', '').strip()
    if date_filter:
        if date_filter == 'today':
            from datetime import date
            items = items.filter(date_lost__date=date.today())
        elif date_filter == 'week':
            from datetime import date, timedelta
            week_ago = date.today() - timedelta(days=7)
            items = items.filter(date_lost__date__gte=week_ago)
        elif date_filter == 'month':
            from datetime import date, timedelta
            month_ago = date.today() - timedelta(days=30)
            items = items.filter(date_lost__date__gte=month_ago)
    
    # Pagination
    paginator = Paginator(items, 12)  # 12 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'selected_district': district,
        'selected_date_filter': date_filter,
        'total_items': items.count()
    }
    
    return render(request, 'found_items.html', context)

def found_item_detail(request, item_id):
    """Display single found item detail"""
    try:
        item = Item.objects.select_related('owner').prefetch_related('images').get(id=item_id, status='found')
        
        # Get current user for chat button
        if request.user.is_authenticated:
            user = request.user
        else:
            user_id = request.session.get("user_id")
            user = AppUser.objects.get(id=user_id) if user_id else None
        
        context = {
            'item': item,
            'can_chat': user and user != item.owner,  # Can't chat with yourself
            'current_user': user
        }
        
        return render(request, 'found_item_detail.html', context)
        
    except Item.DoesNotExist:
        messages.error(request, "Found item not found.")
        return redirect("found_items")

def interactive_map(request):
    """Display interactive map with lost items"""
    return render(request, 'interactive_map.html')

def map_items_api(request):
    """API endpoint to get items for the map"""
    try:
        # Get items with valid coordinates
        lost_items = Item.objects.filter(
            status='active', 
            location_lat__isnull=False, 
            location_lng__isnull=False
        ).exclude(
            location_lat=0, 
            location_lng=0
        ).select_related('owner').prefetch_related('images')

        found_items = Item.objects.filter(
            status='found',
            location_lat__isnull=False, 
            location_lng__isnull=False
        ).exclude(
            location_lat=0, 
            location_lng=0
        ).select_related('owner').prefetch_related('images')

        # Apply filters if provided
        item_type = request.GET.get('type', 'all')  # 'lost', 'found', 'all'
        search_query = request.GET.get('search', '').strip()
        
        items_data = []
        
        # Process lost items
        if item_type in ['all', 'lost']:
            filtered_lost = lost_items
            if search_query:
                filtered_lost = filtered_lost.filter(
                    Q(title__icontains=search_query) |
                    Q(description__icontains=search_query) |
                    Q(location_name__icontains=search_query)
                )
            
            for item in filtered_lost:
                item_data = {
                    'id': item.id,
                    'type': 'lost',
                    'title': item.title,
                    'description': item.description[:100] + '...' if len(item.description) > 100 else item.description,
                    'location_name': item.location_name,
                    'lat': float(item.location_lat),
                    'lng': float(item.location_lng),
                    'date': item.date_lost.strftime('%Y-%m-%d'),
                    'owner': item.owner.username,
                    'reward': float(item.reward_amount) if item.reward_amount else 0,
                    'boost': item.boost,
                    'image_url': item.images.first().image.url if item.images.exists() else None,
                    'detail_url': f'/item/{item.id}/'
                }
                items_data.append(item_data)

        # Process found items
        if item_type in ['all', 'found']:
            filtered_found = found_items
            if search_query:
                filtered_found = filtered_found.filter(
                    Q(title__icontains=search_query) |
                    Q(description__icontains=search_query) |
                    Q(location_name__icontains=search_query)
                )
            
            for item in filtered_found:
                item_data = {
                    'id': item.id,
                    'type': 'found',
                    'title': item.title,
                    'description': item.description[:100] + '...' if len(item.description) > 100 else item.description,
                    'location_name': item.location_name,
                    'lat': float(item.location_lat),
                    'lng': float(item.location_lng),
                    'date': item.date_lost.strftime('%Y-%m-%d'),
                    'owner': item.owner.username,
                    'reward': 0,
                    'boost': False,
                    'image_url': item.images.first().image.url if item.images.exists() else None,
                    'detail_url': f'/found-item/{item.id}/'
                }
                items_data.append(item_data)

        return JsonResponse({
            'success': True,
            'items': items_data,
            'count': len(items_data)
        })

    except Exception as e:
        print(f"Error in map_items_api: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'items': [],
            'count': 0
        })