from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import Member


@ensure_csrf_cookie
def rfid_gate(request):
	"""Render a small page that asks for an RFID scan before allowing access to the login screen."""
	return render(request, 'members/rfid_gate.html')


@require_http_methods(["POST"])
def api_validate_rfid_login(request):
	"""Validate RFID sent in JSON body and return whether a linked active User exists.

	Expected JSON: { "rfid": "1001" }
	Response: { success: True, username: "admin" } or { success: False, error: "..." }
	"""
	import json
	try:
		data = json.loads(request.body)
		rfid = data.get('rfid')
		if not rfid:
			return JsonResponse({'success': False, 'error': 'RFID is required'})

		try:
			member = Member.objects.get(rfid_card_number=rfid, is_active=True)
		except Member.DoesNotExist:
			return JsonResponse({'success': False, 'error': 'Member not found'})

		if not member.user or not member.user.is_active:
			return JsonResponse({'success': False, 'error': 'No active user linked to this RFID'})

		return JsonResponse({'success': True, 'username': member.user.username})
	except json.JSONDecodeError:
		return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
	except Exception as e:
		return JsonResponse({'success': False, 'error': 'Server error occurred'})
