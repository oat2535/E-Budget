from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    path('', views.budget_list_view, name='budget_list'),
    path('add/', views.budget_add_view, name='budget_add'),
    path('add_non_vet/', views.budget_add_non_vet_view, name='budget_add_non_vet'),
    path('api/get_documents/<str:category_code>/', views.get_budget_documents_api, name='api_get_documents'),
    path('api/document/<str:doc_type>/<str:doc_no>/', views.get_document_detail_api, name='api_document_detail'),
    path('api/document/update/<str:doc_type>/<str:doc_no>/', views.update_document_api, name='api_document_update'),
    path('add_adjustment/', views.budget_add_adjustment_view, name='budget_add_adjustment'),
    path('add_medical_equipment/', views.budget_add_medical_equipment_view, name='budget_add_medical_equipment'),
    path('add_computer_equipment/', views.budget_add_computer_equipment_view, name='budget_add_computer_equipment'),
    path('add_furniture/', views.budget_add_furniture_view, name='budget_add_furniture'),
    path('add_tools_equipment/', views.budget_add_tools_equipment_view, name='budget_add_tools_equipment'),
    path('add_gl_entry/', views.budget_add_gl_entry_view, name='budget_add_gl_entry'),
]
