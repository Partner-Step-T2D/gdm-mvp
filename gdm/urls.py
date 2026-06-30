# gdm/urls.py
from django.contrib import admin
from django.urls import path, include
from core.admin_dashboard_views import dashboard_view, participant_detail_view, export_research_data_view

urlpatterns = [
    path('admin/dashboard/', dashboard_view, name='admin-dashboard'),
    path('admin/reports/export-research-data/', export_research_data_view, name='export_research_data'),
    path('admin/participant/<int:participant_id>/', participant_detail_view, name='participant_detail'),
    path('admin/', admin.site.urls),
    path('fitbit/', include('device_integration.urls', namespace='device_integration')),
    path('oauth/', include('device_integration.google_urls')),
    path('goals/', include('goals.urls')),
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
]