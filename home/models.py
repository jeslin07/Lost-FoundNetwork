from django.db import models
from django.utils import timezone


# -------------------------
# User Model
# -------------------------
class AppUser(models.Model):
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)  # plaintext for hackathon MVP
    email = models.EmailField(unique=True)
    aadhaar = models.CharField(max_length=12)
    phone = models.CharField(max_length=15)
    district = models.CharField(max_length=100)
    rating = models.FloatField(default=0.0)  # optional finder reputation
    earned_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)


    def __str__(self):
        return self.username


# -------------------------
# Lost / Found Item
# -------------------------
class Item(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('found', 'Found'),
        ('recovered', 'Recovered'),
        ('closed', 'Closed'),
    ]

    owner = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    location_lat = models.FloatField(default=0.0)
    location_lng = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    date_lost = models.DateTimeField(default=timezone.now)
    reward_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) 
    boost = models.BooleanField(default=False)  # paid boost option

    def __str__(self):
        return f"{self.title} ({self.status})"


class ItemImage(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="items/")
    embedding = models.JSONField(default=list, blank=True)  # store vector encoding

    def __str__(self):
        return f"Image for {self.item.title}"


# -------------------------
# AI Matching Results
# -------------------------
class Match(models.Model):
    lost_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="matches")
    found_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="matched_to")
    confidence = models.FloatField()  # 0-100%
    matched_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.lost_item.title} ↔ {self.found_item.title} ({self.confidence:.1f}%)"


# -------------------------
# Messages / Chat
# -------------------------
class Chat(models.Model):
    sender = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="sent_chats")
    receiver = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="received_chats")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="chats")
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['sent_at']

    def __str__(self):
        return f"Chat from {self.sender.username} to {self.receiver.username}"


# -------------------------
# Case History / Timeline
# -------------------------
class CaseHistory(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.item.title} → {self.status} at {self.timestamp}"
