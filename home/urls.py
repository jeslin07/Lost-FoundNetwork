from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('owner_dashboard/', views.owner_dashboard, name='owner_dashboard'),    
    path("signup/", views.signup, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("report_lost/", views.report_lost_item, name="report_lost_item"),
    path('delete-item/<int:item_id>/', views.delete_item, name='delete_item'),

    path('report-found/', views.report_found_item, name='report_found_item'),
    path('search-similarity/<int:item_id>/', views.search_similarity, name='search_similarity'),
    path('clear-search-results/', views.clear_search_results, name='clear_search_results'),
    path('regenerate-embeddings/', views.regenerate_embeddings, name='regenerate_embeddings'),

    path('start-chat/<int:item_id>/', views.start_chat, name='start_chat'),
    path('chat/', views.chat_room, name='chat_room'),
    path('send-message/', views.send_message, name='send_message'),
    path('get-messages/', views.get_messages, name='get_messages'),
    path('update-item-status/', views.update_item_status, name='update_item_status'),
    path('lost-items/', views.lost_items, name='lost_items'),
    path('item/<int:item_id>/', views.item_detail, name='item_detail'),

    path('found-items/', views.found_items, name='found_items'),
    path('found-item/<int:item_id>/', views.found_item_detail, name='found_item_detail'),


    path('map/', views.interactive_map, name='interactive_map'),
    path('api/map-items/', views.map_items_api, name='map_items_api'),


]