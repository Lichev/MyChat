def hub_context(request):
    if not request.user.is_authenticated:
        return {"active_tab": None}
    path = request.path
    if path.startswith("/accounts/") or path.startswith("/friend/"):
        return {"active_tab": "account"}
    if path.startswith("/chat/"):
        return {"active_tab": "rooms"}
    return {"active_tab": None}
