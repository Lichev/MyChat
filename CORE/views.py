from django.http import JsonResponse
from django.views.generic import TemplateView


class HomePage(TemplateView):
    template_name = 'core/index.html'


class ContactSuccessView(TemplateView):
    template_name = 'core/contact-form-success.html'


def health(request):
    """Minimal health-check endpoint for load balancer probes. Returns HTTP 200."""
    return JsonResponse({'status': 'ok'})
