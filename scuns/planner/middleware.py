from django.utils.cache import patch_cache_control


class PrivateWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith(('/account/', '/api/workspace/', '/login/', '/signup/', '/teacher/', '/class/')):
            patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
        return response
