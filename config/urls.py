from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from assistant import views as assistant_views
from documents import views as document_views

urlpatterns = [
    path('', assistant_views.ask, name='ask'),
    path('documents/<int:pk>/file/', document_views.document_file, name='document_file'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
]

# Lets staff open uploaded PDFs from the admin while developing. Does nothing
# when DEBUG is off. Students get PDFs through the access-checked view above.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
