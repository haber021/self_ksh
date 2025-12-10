from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import login
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
import json
from datetime import timedelta
from decimal import Decimal

from members.models import Member
from transactions.models import Transaction
from .serializers import (
    MemberSerializer, TransactionSerializer, 
    BalanceTransactionSerializer, AccountSummarySerializer
)


@csrf_exempt
@require_http_methods(["POST"])
def mobile_login(request):
    """
    Enhanced login endpoint for mobile app using username and PIN
    Expected JSON: {"username": "john_doe", "pin": "1234"}
    Returns: JSON response with member info and session
    """
    try:
        # Parse JSON body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON format'},
                status=400
            )
        
        username = data.get('username', '').strip()
        pin = data.get('pin', '').strip()
        
        # Enhanced validation
        if not username:
            return JsonResponse(
                {'success': False, 'error': 'Username is required'},
                status=400
            )
        
        if not pin:
            return JsonResponse(
                {'success': False, 'error': 'PIN is required'},
                status=400
            )
        
        # Validate PIN format (should be 4 digits)
        if not pin.isdigit() or len(pin) != 4:
            return JsonResponse(
                {'success': False, 'error': 'PIN must be exactly 4 digits'},
                status=400
            )
        
        # Find member by username through user relationship
        try:
            from django.contrib.auth.models import User
            user = User.objects.get(username=username, is_active=True)
            member = Member.objects.get(user=user, is_active=True)
        except User.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'User not found or account is inactive'},
                status=404
            )
        except Member.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'Member account not found or is inactive'},
                status=404
            )
        
        # Verify PIN with enhanced error handling
        try:
            if not member.check_pin(pin):
                return JsonResponse(
                    {'success': False, 'error': 'Invalid PIN. Please try again.'},
                    status=401
                )
        except Exception as e:
            return JsonResponse(
                {'success': False, 'error': 'Error verifying PIN. Please try again.'},
                status=500
            )
        
        
        # Authenticate and login the user
        try:
            login(request, member.user)
        except Exception as e:
            return JsonResponse(
                {'success': False, 'error': 'Authentication failed. Please try again.'},
                status=500
            )
        
        # Serialize member data
        serializer = MemberSerializer(member)
        
        # Return success response with member info
        return JsonResponse({
            'success': True,
            'member': serializer.data,
            'message': f'Welcome back, {member.full_name}!',
            'session_id': request.session.session_key
        }, status=200)
        
    except Exception as e:
        # Log the error for debugging (in production, use proper logging)
        import traceback
        print(f"Mobile login error: {str(e)}")
        print(traceback.format_exc())
        
        return JsonResponse(
            {'success': False, 'error': 'An unexpected error occurred. Please try again later.'},
            status=500
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def account_info(request):
    """
    Get current member's account information
    Requires authentication
    """
    try:
        member = Member.objects.get(user=request.user, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Member account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Member.MultipleObjectsReturned:
        member = Member.objects.filter(user=request.user, is_active=True).first()
        if not member:
            return Response(
                {'success': False, 'error': 'Member account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    serializer = MemberSerializer(member)
    return Response({
        'success': True,
        'member': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def account_summary(request):
    """
    Get comprehensive account summary including recent transactions
    Query params: year (default current year), month (default current month, 1-12)
    """
    try:
        member = Member.objects.get(user=request.user, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Member account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Member.MultipleObjectsReturned:
        member = Member.objects.filter(user=request.user, is_active=True).first()
        if not member:
            return Response(
                {'success': False, 'error': 'Member account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    # Get recent transactions (last 10)
    recent_transactions = Transaction.objects.filter(
        member=member,
        status='completed'
    ).order_by('-created_at')[:10]
    
    # Get recent balance transactions (last 10)
    recent_balance_transactions = member.balance_transactions.all().order_by('-created_at')[:10]
    
    # Get month/year from query params or use current month/year
    now = timezone.now()
    year = int(request.query_params.get('year', now.year))
    month = int(request.query_params.get('month', now.month))
    
    # Validate month
    if month < 1 or month > 12:
        month = now.month
    
    # Calculate monthly totals for selected month
    start_of_month = timezone.datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    # Calculate end of month
    if month == 12:
        end_of_month = timezone.datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    else:
        end_of_month = timezone.datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
    
    monthly_transactions = Transaction.objects.filter(
        member=member,
        status='completed',
        created_at__gte=start_of_month,
        created_at__lt=end_of_month
    )
    
    total_spent_this_month = sum(t.total_amount for t in monthly_transactions)
    total_patronage_this_month = sum(t.patronage_amount for t in monthly_transactions)
    
    data = {
        'member': MemberSerializer(member).data,
        'recent_transactions': TransactionSerializer(recent_transactions, many=True).data,
        'recent_balance_transactions': BalanceTransactionSerializer(recent_balance_transactions, many=True).data,
        'total_spent_this_month': str(total_spent_this_month),
        'total_patronage_this_month': str(total_patronage_this_month),
        'selected_year': year,
        'selected_month': month
    }
    
    return Response({
        'success': True,
        'summary': data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transaction_history(request):
    """
    Get transaction history with pagination
    Query params: page (default 1), limit (default 20)
    """
    try:
        member = Member.objects.get(user=request.user, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Member account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Member.MultipleObjectsReturned:
        member = Member.objects.filter(user=request.user, is_active=True).first()
        if not member:
            return Response(
                {'success': False, 'error': 'Member account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    page = int(request.query_params.get('page', 1))
    limit = int(request.query_params.get('limit', 20))
    offset = (page - 1) * limit
    
    transactions = Transaction.objects.filter(
        member=member,
        status='completed'
    ).order_by('-created_at')[offset:offset + limit]
    
    total = Transaction.objects.filter(member=member, status='completed').count()
    
    serializer = TransactionSerializer(transactions, many=True)
    return Response({
        'success': True,
        'transactions': serializer.data,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'has_next': offset + limit < total,
            'has_previous': page > 1
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def balance_transactions(request):
    """
    Get balance transaction history (deposits, deductions, utang payments)
    Query params: page (default 1), limit (default 20)
    """
    try:
        member = Member.objects.get(user=request.user, is_active=True)
    except Member.DoesNotExist:
        return Response(
            {'success': False, 'error': 'Member account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Member.MultipleObjectsReturned:
        member = Member.objects.filter(user=request.user, is_active=True).first()
        if not member:
            return Response(
                {'success': False, 'error': 'Member account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    page = int(request.query_params.get('page', 1))
    limit = int(request.query_params.get('limit', 20))
    offset = (page - 1) * limit
    
    balance_transactions = member.balance_transactions.all().order_by('-created_at')[offset:offset + limit]
    total = member.balance_transactions.count()
    
    serializer = BalanceTransactionSerializer(balance_transactions, many=True)
    return Response({
        'success': True,
        'balance_transactions': serializer.data,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'has_next': offset + limit < total,
            'has_previous': page > 1
        }
    })
