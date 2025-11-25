import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Avg, Q, F
from django.db.models.functions import TruncDate
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_http_methods
from django.conf import settings

from inventory.models import Product, Category
from members.models import Member, MemberType, BalanceTransaction
from transactions.models import Transaction, TransactionItem


def handle_login(request, redirect_to_dashboard=False):
    """Shared login logic that routes admin and regular users appropriately"""
    if request.user.is_authenticated:
        # Check if user is admin and redirect accordingly
        if is_admin_user(request.user):
            return redirect('dashboard')
        else:
            return redirect('user_choice')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            messages.error(request, 'Please enter both username and password.')
            return render(request, 'admin_panel/login.html')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            
            # Check if user is admin (staff/superuser or member with admin role)
            next_url = request.POST.get('next') or request.GET.get('next')
            if is_admin_user(user):
                # Admin users go to dashboard
                if next_url == 'dashboard':
                    return redirect('dashboard')
                if next_url and next_url.startswith('/') and next_url != '/admin/':
                    return redirect(next_url)
                return redirect('dashboard')
            else:
                # Regular users go to choice page (or next URL if provided)
                messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
                if next_url and next_url.startswith('/') and next_url != '/admin/':
                    return redirect(next_url)
                return redirect('user_choice')
        else:
            messages.error(request, 'Invalid username or password. Please try again.')
    
    return render(request, 'admin_panel/login.html')


@require_http_methods(["GET", "POST"])
def root_login(request):
    """Root login page - first page users see"""
    return handle_login(request)


@require_http_methods(["GET", "POST"])
def redirect_to_root_login(request):
    """Redirect /admin/login/ to root login page, preserving query parameters"""
    from django.urls import reverse
    
    # Build the root login URL
    root_login_url = reverse('root_login')
    
    # Preserve query parameters if they exist
    query_string = request.META.get('QUERY_STRING', '')
    if query_string:
        root_login_url = f"{root_login_url}?{query_string}"
    
    return redirect(root_login_url)


def is_admin_user(user):
    """Check if a user is an admin (staff/superuser or linked to Member with admin role)"""
    if user.is_staff or user.is_superuser:
        return True
    
    # Check if user is linked to a Member with admin role
    try:
        member = Member.objects.get(user=user)
        if member.role == 'admin' and member.is_active:
            return True
    except Member.DoesNotExist:
        pass
    except Exception:
        pass
    
    return False


def is_cashier_or_admin(user):
    """Check if a user is a cashier or admin (staff/superuser or linked to Member with cashier/admin role)"""
    if user.is_staff or user.is_superuser:
        return True
    
    # Check if user is linked to a Member with cashier or admin role
    try:
        member = Member.objects.get(user=user)
        if member.role in ['cashier', 'admin'] and member.is_active:
            return True
    except Member.DoesNotExist:
        pass
    except Exception:
        pass
    
    return False


@login_required
def dashboard(request):
    # Ensure only admin users can access dashboard
    if not is_admin_user(request.user):
        messages.warning(request, 'You do not have permission to access the admin dashboard.')
        return redirect('kiosk_home')
    today = timezone.now().date()
    two_weeks_ago = today - timedelta(days=13)
    month_ago = today - timedelta(days=30)

    base_qs = Transaction.objects.filter(status='completed')

    total_transactions = base_qs.count()
    total_revenue = base_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    today_transactions = base_qs.filter(created_at__date=today).count()
    today_revenue = base_qs.filter(created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    total_members = Member.objects.filter(is_active=True).count()
    members_with_utang = Member.objects.filter(is_active=True, utang_balance__gt=0).count()
    total_utang = Member.objects.filter(is_active=True).aggregate(Sum('utang_balance'))['utang_balance__sum'] or 0
    total_patronage = base_qs.aggregate(Sum('patronage_amount'))['patronage_amount__sum'] or 0

    low_stock_products = Product.objects.filter(is_active=True, stock_quantity__lte=10).count()
    out_of_stock_products = Product.objects.filter(is_active=True, stock_quantity=0).count()

    recent_transactions = base_qs.order_by('-created_at')[:10]
    top_products = TransactionItem.objects.filter(transaction__status='completed').values('product_name').annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_sold')[:10]

    # --- Chart data calculations ---
    daily_sales_raw = base_qs.filter(created_at__date__gte=two_weeks_ago).annotate(
        day=TruncDate('created_at')
    ).values('day').annotate(
        total=Sum('total_amount')
    ).order_by('day')

    daily_sales_map = {entry['day']: float(entry['total'] or 0) for entry in daily_sales_raw}
    daily_labels = []
    daily_totals = []
    for offset in range(14):
        day = two_weeks_ago + timedelta(days=offset)
        daily_labels.append(day.strftime('%b %d'))
        daily_totals.append(round(daily_sales_map.get(day, 0), 2))

    payment_breakdown = base_qs.values('payment_method').annotate(
        total=Sum('total_amount')
    )
    payment_label_map = dict(Transaction.PAYMENT_METHODS)
    payment_labels = []
    payment_totals = []
    for entry in payment_breakdown:
        label = payment_label_map.get(entry['payment_method'], entry['payment_method'].title())
        payment_labels.append(label)
        payment_totals.append(float(entry['total'] or 0))

    category_sales = TransactionItem.objects.filter(
        transaction__status='completed',
        product__category__isnull=False
    ).values('product__category__name').annotate(
        total=Sum('total_price')
    ).order_by('-total')[:6]
    category_labels = [entry['product__category__name'] or 'Uncategorized' for entry in category_sales]
    category_totals = [float(entry['total'] or 0) for entry in category_sales]

    top_members = Member.objects.filter(
        transactions__status='completed'
    ).annotate(
        total_spent=Sum('transactions__total_amount')
    ).order_by('-total_spent')[:5]

    # --- Refund statistics ---
    # Refunds are identified by: status='cancelled' AND notes contains 'Refund'
    # When a refund is processed, the transaction status is set to 'cancelled' and notes contain 'Refunded'
    # Also check BalanceTransaction records to catch any refunds that might have different note formats
    import re
    
    # Get transaction numbers from BalanceTransaction records with "Refund" in notes
    refund_balance_txns = BalanceTransaction.objects.filter(
        notes__icontains='Refund'
    ).values_list('notes', flat=True)
    
    # Extract transaction numbers from balance transaction notes
    refund_txn_numbers = set()
    for note in refund_balance_txns:
        # Match patterns like "Refund for transaction TXN-123" or "Refund for transaction TXN123"
        matches = re.findall(r'transaction\s+([A-Z0-9-]+)', note, re.IGNORECASE)
        refund_txn_numbers.update(matches)
    
    # Query for refunds: cancelled transactions with 'Refund' in notes OR transactions with numbers from balance records
    refund_qs = Transaction.objects.filter(
        Q(status='cancelled', notes__icontains='Refund') |
        Q(transaction_number__in=refund_txn_numbers)
    ).distinct()
    
    total_refunds = refund_qs.count()
    total_refund_amount = refund_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    today_refunds = refund_qs.filter(updated_at__date=today).count()
    today_refund_amount = refund_qs.filter(updated_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Recent refunds
    recent_refunds = refund_qs.order_by('-updated_at')[:10]
    
    # Daily refund trend (14 days)
    daily_refunds_raw = refund_qs.filter(updated_at__date__gte=two_weeks_ago).annotate(
        day=TruncDate('updated_at')
    ).values('day').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    ).order_by('day')
    
    daily_refunds_map = {entry['day']: {'amount': float(entry['total'] or 0), 'count': entry['count']} for entry in daily_refunds_raw}
    daily_refund_labels = []
    daily_refund_amounts = []
    daily_refund_counts = []
    for offset in range(14):
        day = two_weeks_ago + timedelta(days=offset)
        daily_refund_labels.append(day.strftime('%b %d'))
        refund_data = daily_refunds_map.get(day, {'amount': 0, 'count': 0})
        daily_refund_amounts.append(round(refund_data['amount'], 2))
        daily_refund_counts.append(refund_data['count'])

    context = {
        'total_transactions': total_transactions,
        'total_revenue': total_revenue,
        'today_transactions': today_transactions,
        'today_revenue': today_revenue,
        'total_members': total_members,
        'members_with_utang': members_with_utang,
        'total_utang': total_utang,
        'total_patronage': total_patronage,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'recent_transactions': recent_transactions,
        'top_products': top_products,
        'top_members': top_members,
        'daily_sales_labels': json.dumps(daily_labels),
        'daily_sales_totals': json.dumps(daily_totals),
        'payment_labels': json.dumps(payment_labels),
        'payment_totals': json.dumps(payment_totals),
        'category_labels': json.dumps(category_labels),
        'category_totals': json.dumps(category_totals),
        'user_display_name': request.user.get_full_name() or request.user.username,
        # Refund statistics
        'total_refunds': total_refunds,
        'total_refund_amount': total_refund_amount,
        'today_refunds': today_refunds,
        'today_refund_amount': today_refund_amount,
        'recent_refunds': recent_refunds,
        'daily_refund_labels': json.dumps(daily_refund_labels),
        'daily_refund_amounts': json.dumps(daily_refund_amounts),
        'daily_refund_counts': json.dumps(daily_refund_counts),
    }

    return render(request, 'admin_panel/dashboard.html', context)


@login_required
def inventory_management(request):
    if not is_admin_user(request.user):
        messages.warning(request, 'You do not have permission to access this page.')
        return redirect('kiosk_home')
    products = Product.objects.all().order_by('name')
    categories = Category.objects.all()
    
    # Calculate statistics
    total_products = products.count()
    low_stock_products = products.filter(is_active=True, stock_quantity__lte=F('low_stock_threshold'), stock_quantity__gt=0).count()
    out_of_stock_products = products.filter(is_active=True, stock_quantity=0).count()
    total_categories = categories.count()
    
    context = {
        'products': products,
        'categories': categories,
        'total_products': total_products,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'total_categories': total_categories,
    }
    
    return render(request, 'admin_panel/inventory.html', context)


@login_required
def member_management(request):
    if not is_admin_user(request.user):
        messages.warning(request, 'You do not have permission to access this page.')
        return redirect('kiosk_home')
    members = Member.objects.all().order_by('-date_joined')
    member_types = MemberType.objects.all()
    
    # Calculate statistics
    total_members = members.count()
    active_members = members.filter(is_active=True).count()
    members_with_utang = members.filter(is_active=True, utang_balance__gt=0).count()
    total_balances = members.aggregate(Sum('balance'))['balance__sum'] or 0
    
    context = {
        'members': members,
        'member_types': member_types,
        'total_members': total_members,
        'active_members': active_members,
        'members_with_utang': members_with_utang,
        'total_balances': total_balances,
    }
    
    return render(request, 'admin_panel/members.html', context)


@login_required
def patronage_settings(request):
    if not is_admin_user(request.user):
        messages.warning(request, 'You do not have permission to access this page.')
        return redirect('kiosk_home')
    member_types = MemberType.objects.all()
    
    context = {
        'member_types': member_types,
    }
    
    return render(request, 'admin_panel/patronage.html', context)


@login_required
def transaction_history(request):
    if not is_admin_user(request.user):
        messages.warning(request, 'You do not have permission to access this page.')
        return redirect('kiosk_home')
    
    # Get all transactions with related data
    transactions = Transaction.objects.select_related('member').prefetch_related('items').order_by('-created_at')
    
    # Calculate statistics
    total_transactions = transactions.count()
    completed_transactions = transactions.filter(status='completed').count()
    pending_transactions = transactions.filter(status='pending').count()
    cancelled_transactions = transactions.filter(status='cancelled').count()
    total_revenue = transactions.filter(status='completed').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    context = {
        'transactions': transactions,
        'total_transactions': total_transactions,
        'completed_transactions': completed_transactions,
        'pending_transactions': pending_transactions,
        'cancelled_transactions': cancelled_transactions,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'admin_panel/transactions.html', context)


@require_http_methods(["GET", "POST"])
def admin_logout(request):
    """Custom admin logout that redirects to root login page (login.html)"""
    # Get the next parameter before logging out (if provided)
    next_url = request.POST.get('next') or request.GET.get('next')
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    # Redirect to root login page (/) with next parameter if provided
    # Explicitly use '/' to avoid any redirect to /admin/login/
    if next_url:
        return redirect(f"/?{urlencode({'next': next_url})}")
    return redirect('/')


@require_http_methods(["GET", "POST"])
def kiosk_logout(request):
    """Logout endpoint that renders login.html directly"""
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return render(request, 'admin_panel/login.html')


@login_required
def user_choice(request):
    """Choice page for regular users after login - view transactions or go to kiosk"""
    if is_admin_user(request.user):
        return redirect('dashboard')
    return render(request, 'admin_panel/user_choice.html')


@login_required
def user_transactions(request):
    """View last 10 transactions for the logged-in user"""
    if is_admin_user(request.user):
        return redirect('dashboard')
    
    # Get member associated with user
    member = None
    transactions = []
    
    try:
        # Try to get the member associated with the logged-in user
        member = Member.objects.get(user=request.user, is_active=True)
        
        # Get last 10 completed transactions for this member
        # Prefetch related items to avoid N+1 queries
        transactions = Transaction.objects.filter(
            member=member,
            status='completed'
        ).select_related('member').prefetch_related('items').order_by('-created_at')[:10]
        
        # Force queryset evaluation by converting to list
        transactions = list(transactions)
        
        # Debug: If no transactions found, check if there are any transactions at all for this member
        if not transactions:
            # Check if there are any transactions (even with different status)
            all_transactions = Transaction.objects.filter(member=member).count()
            if all_transactions > 0:
                # Check what statuses exist
                statuses = Transaction.objects.filter(member=member).values_list('status', flat=True).distinct()
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Member {member.id} has {all_transactions} transactions but none with status 'completed'. Statuses found: {list(statuses)}")
    except Member.DoesNotExist:
        # User doesn't have a member account
        pass
    except Member.MultipleObjectsReturned:
        # Multiple members found for this user (shouldn't happen, but handle it)
        member = Member.objects.filter(user=request.user, is_active=True).first()
        if member:
            transactions = Transaction.objects.filter(
                member=member,
                status='completed'
            ).select_related('member').prefetch_related('items').order_by('-created_at')[:10]
            transactions = list(transactions)
    except Exception as e:
        # Log error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching transactions: {str(e)}", exc_info=True)
    
    context = {
        'transactions': transactions,
        'member': member,
    }
    return render(request, 'admin_panel/user_transactions.html', context)


@require_http_methods(["POST"])
def api_rfid_login(request):
    """Login directly using RFID card - authenticates and logs in the user"""
    try:
        data = json.loads(request.body)
        rfid = data.get('rfid')
        
        if not rfid:
            return JsonResponse({'success': False, 'error': 'RFID is required'})
        
        try:
            member = Member.objects.get(rfid_card_number=rfid, is_active=True)
        except Member.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member not found or inactive'})
        
        if not member.user or not member.user.is_active:
            return JsonResponse({'success': False, 'error': 'No active user account linked to this RFID card'})
        
        # Log in the user
        login(request, member.user)
        
        # Determine redirect URL
        next_url = data.get('next') or 'dashboard'
        if is_admin_user(member.user):
            if next_url == 'dashboard':
                redirect_url = '/dashboard/'
            elif next_url and next_url.startswith('/') and next_url != '/admin/':
                redirect_url = next_url
            else:
                redirect_url = '/dashboard/'
        else:
            # Regular users go to choice page
            if next_url and next_url.startswith('/') and next_url != '/admin/':
                redirect_url = next_url
            else:
                redirect_url = '/user-choice/'
        
        return JsonResponse({
            'success': True,
            'message': f'Welcome back, {member.user.get_full_name() or member.user.username}!',
            'redirect_url': redirect_url,
            'user': {
                'username': member.user.username,
                'name': member.user.get_full_name() or member.user.username,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})


@login_required
@require_http_methods(["GET"])
def api_search_members(request):
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    """Search members by RFID card number or name for balance refill"""
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'members': []})
    
    try:
        # Search by RFID (exact or partial) or by name
        members = Member.objects.filter(
            Q(rfid_card_number__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        ).filter(is_active=True)[:20]
        
        results = []
        for member in members:
            results.append({
                'id': member.id,
                'rfid': member.rfid_card_number,
                'name': member.full_name,
                'email': member.email or '',
                'current_balance': str(member.balance),
                'utang_balance': str(member.utang_balance),
            })
        
        return JsonResponse({'success': True, 'members': results})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@login_required
@require_http_methods(["POST"])
def api_refill_balance(request):
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    """Refill/add balance to a member's card"""
    try:
        data = json.loads(request.body)
        member_id = data.get('member_id')
        amount = data.get('amount')
        notes = data.get('notes', '').strip()
        
        if not member_id:
            return JsonResponse({'success': False, 'error': 'Member ID is required'})
        
        if not amount:
            return JsonResponse({'success': False, 'error': 'Amount is required'})
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return JsonResponse({'success': False, 'error': 'Amount must be greater than zero'})
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid amount format'})
        
        try:
            member = Member.objects.get(id=member_id, is_active=True)
        except Member.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member not found'})
        
        # Record balance before
        balance_before = member.balance
        utang_before = member.utang_balance
        
        # Add balance
        member.add_balance(amount)
        
        # Record balance after
        balance_after = member.balance
        
        # Create balance transaction record
        BalanceTransaction.objects.create(
            member=member,
            transaction_type='deposit',
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            utang_before=utang_before,
            utang_after=utang_before,  # Utang unchanged
            notes=f"Balance refill by admin. {notes}" if notes else "Balance refill by admin"
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully added ₱{amount:.2f} to {member.full_name}\'s balance',
            'member': {
                'id': member.id,
                'name': member.full_name,
                'rfid': member.rfid_card_number,
                'new_balance': str(member.balance),
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})


@login_required
@require_http_methods(["POST"])
def api_update_patronage_rate(request):
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    """Update patronage rate for a member type"""
    try:
        data = json.loads(request.body)
        member_type_id = data.get('member_type_id')
        patronage_rate = data.get('patronage_rate')
        
        if not member_type_id:
            return JsonResponse({'success': False, 'error': 'Member type ID is required'})
        
        if patronage_rate is None:
            return JsonResponse({'success': False, 'error': 'Patronage rate is required'})
        
        try:
            patronage_rate = Decimal(str(patronage_rate))
            if patronage_rate < 0 or patronage_rate > 1:
                return JsonResponse({'success': False, 'error': 'Patronage rate must be between 0 and 1'})
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid patronage rate format'})
        
        try:
            member_type = MemberType.objects.get(id=member_type_id)
        except MemberType.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member type not found'})
        
        # Update the patronage rate
        member_type.patronage_rate = patronage_rate
        member_type.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully updated patronage rate for {member_type.name} to {patronage_rate:.4f} ({(patronage_rate * 100):.2f}%)',
            'member_type': {
                'id': member_type.id,
                'name': member_type.name,
                'patronage_rate': str(member_type.patronage_rate),
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})


def generate_refund_receipt_data(transaction, refund_reason, member, balance_before=None, balance_after=None, utang_before=None, utang_after=None):
    """Generate refund receipt text data"""
    from django.conf import settings
    
    vat_rate = getattr(settings, 'VAT_RATE', 0.12)
    lines = []
    
    def money(v):
        if v is None:
            return '₱0.00'
        return '₱' + str(Decimal(str(v)).quantize(Decimal('0.01')))
    
    # Header
    lines.append('COOPERATIVE STORE')
    lines.append('REFUND RECEIPT')
    lines.append('')
    
    # Transaction info
    lines.append('Original Txn:')
    lines.append(transaction.transaction_number)
    lines.append('Refund Date:')
    lines.append(timezone.now().strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('')
    
    # Member info
    if member:
        lines.append('Member:')
        lines.append(member.full_name)
        if hasattr(member, 'member_id') and member.member_id:
            lines.append(f'Member ID: {member.member_id}')
        lines.append('')
    
    # Items refunded
    lines.append('ITEMS REFUNDED:')
    for item in transaction.items.all():
        name = item.product_name
        qty = item.quantity
        total = money(item.total_price)
        lines.append(f'{name} x{qty}')
        lines.append(total)
    lines.append('')
    
    # Amounts
    lines.append('Vatable Sale:')
    lines.append(money(transaction.vatable_sale))
    lines.append(f'VAT ({vat_rate*100:.0f}%):')
    lines.append(money(transaction.vat_amount))
    lines.append('Subtotal:')
    lines.append(money(transaction.subtotal))
    lines.append('Total Refund:')
    lines.append(money(transaction.total_amount))
    lines.append('')
    
    # Payment method refund info
    lines.append('REFUND METHOD:')
    if transaction.payment_method == 'debit' and member and balance_before is not None:
        lines.append('Refunded to Member Balance')
        lines.append(f'Balance Before: {money(balance_before)}')
        lines.append(f'Balance After: {money(balance_after)}')
    elif transaction.payment_method == 'credit' and member and utang_before is not None:
        lines.append('Reduced from Utang')
        lines.append(f'Utang Before: {money(utang_before)}')
        lines.append(f'Utang After: {money(utang_after)}')
    elif transaction.payment_method == 'cash':
        lines.append('Cash Refund')
    lines.append('')
    
    # Reason if provided
    if refund_reason:
        lines.append('Reason:')
        lines.append(refund_reason)
        lines.append('')
    
    lines.append('Thank you!')
    
    return {
        'text': '\r\n'.join(lines),
        'html': generate_refund_receipt_html(transaction, refund_reason, member, balance_before, balance_after, utang_before, utang_after)
    }


def generate_refund_receipt_html(transaction, refund_reason, member, balance_before=None, balance_after=None, utang_before=None, utang_after=None):
    """Generate HTML version of refund receipt"""
    from django.conf import settings
    
    vat_rate = getattr(settings, 'VAT_RATE', 0.12)
    
    def money(v):
        if v is None:
            return '₱0.00'
        return '₱' + str(Decimal(str(v)).quantize(Decimal('0.01')))
    
    items_html = ''.join([
        f'<div class="rp-line"><span>{item.product_name} x{item.quantity}</span><span>{money(item.total_price)}</span></div>'
        for item in transaction.items.all()
    ])
    
    member_info = ''
    if member:
        member_info = f'<div class="rp-line"><span>Member:</span><span>{member.full_name}</span></div>'
        if hasattr(member, 'member_id') and member.member_id:
            member_info += f'<div class="rp-line"><span>Member ID:</span><span>{member.member_id}</span></div>'
    
    refund_method_html = ''
    if transaction.payment_method == 'debit' and member and balance_before is not None:
        refund_method_html = f'''
            <div class="rp-section-title">REFUND METHOD</div>
            <div class="rp-line"><span>Refunded to Balance</span></div>
            <div class="rp-line"><span>Balance Before:</span><span>{money(balance_before)}</span></div>
            <div class="rp-line"><span>Balance After:</span><span>{money(balance_after)}</span></div>
        '''
    elif transaction.payment_method == 'credit' and member and utang_before is not None:
        refund_method_html = f'''
            <div class="rp-section-title">REFUND METHOD</div>
            <div class="rp-line"><span>Reduced from Utang</span></div>
            <div class="rp-line"><span>Utang Before:</span><span>{money(utang_before)}</span></div>
            <div class="rp-line"><span>Utang After:</span><span>{money(utang_after)}</span></div>
        '''
    elif transaction.payment_method == 'cash':
        refund_method_html = '''
            <div class="rp-section-title">REFUND METHOD</div>
            <div class="rp-line"><span>Cash Refund</span></div>
        '''
    
    reason_html = ''
    if refund_reason:
        reason_html = f'''
            <div class="rp-sep"></div>
            <div class="rp-line"><span>Reason:</span></div>
            <div class="rp-subline">{refund_reason}</div>
        '''
    
    html = f'''
        <div id="receiptPaper" class="receipt-paper">
            <div class="rp-center">
                <div class="rp-title">COOPERATIVE STORE</div>
                <div class="rp-sub">REFUND RECEIPT</div>
            </div>
            <div class="rp-line"><span>Original Txn:</span><span>{transaction.transaction_number}</span></div>
            <div class="rp-line"><span>Refund Date:</span><span>{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</span></div>
            {member_info}
            <div class="rp-section-title">ITEMS REFUNDED</div>
            {items_html}
            <div class="rp-sep"></div>
            <div class="rp-line"><span>Vatable Sale</span><span>{money(transaction.vatable_sale)}</span></div>
            <div class="rp-line"><span>VAT ({vat_rate*100:.0f}%)</span><span>{money(transaction.vat_amount)}</span></div>
            <div class="rp-line"><span>Subtotal:</span><span>{money(transaction.subtotal)}</span></div>
            <div class="rp-line rp-total"><span>Total Refund:</span><span>{money(transaction.total_amount)}</span></div>
            {refund_method_html}
            {reason_html}
            <div class="rp-center rp-thanks">Thank you!</div>
        </div>
    '''
    
    css = '''
        <style>
            @page { size: 58mm auto; margin: 2mm; }
            html, body { width: 58mm; padding: 0; margin: 0; }
            .receipt-paper { font-family: "Courier New", monospace; font-size: 12pt; line-height: 1.45; width: 56mm; max-width: 56mm; margin: 0 auto; color: #000 !important; }
            .receipt-paper * { color: #000 !important; }
            .receipt-paper .rp-center { text-align: center; }
            .receipt-paper .rp-title { font-weight: 700; font-size: 13pt; margin: 2mm 0 1mm; }
            .receipt-paper .rp-sub { font-size: 11pt; margin-bottom: 2mm; }
            .receipt-paper .rp-line { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
            .receipt-paper .rp-sep { border-top: 1px dashed #000; margin: 2mm 0; }
            .receipt-paper .rp-section-title { margin: 1mm 0; font-weight: 700; }
            .receipt-paper .rp-subline { font-size: 10pt; color: #000; }
            .receipt-paper .rp-total { font-weight: 700; font-size: 12pt; color: #c00 !important; }
            .receipt-paper .rp-thanks { margin-top: 2mm; }
        </style>
    '''
    
    return f'<!doctype html><html><head><meta charset="utf-8"><title>Refund Receipt</title>{css}</head><body>{html}</body></html>'


@login_required
def process_refund(request):
    """Refund management page - accessible to all logged-in users
    
    Access control:
    - Regular members: can only search and refund their own transactions
    - Cashiers and admins: can search and refund all transactions
    """
    # All logged-in users can access the refund page
    # Access control is enforced at the API level
    return render(request, 'admin_panel/refund.html')


@login_required
@require_http_methods(["GET"])
def api_search_transactions_for_refund(request):
    """Search transactions by transaction number for refund processing
    
    Access control:
    - Regular members: can only search their own transactions
    - Cashiers and admins: can search all transactions
    """
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'transactions': []})
    
    try:
        # Check if user is cashier or admin
        has_full_access = is_cashier_or_admin(request.user)
        
        # Base query for completed transactions
        transactions = Transaction.objects.filter(
            transaction_number__icontains=query,
            status='completed'
        ).select_related('member').prefetch_related('items')
        
        # If user is not cashier/admin, filter to only their own transactions
        if not has_full_access:
            # Get member associated with the logged-in user
            try:
                member = Member.objects.get(user=request.user, is_active=True)
                transactions = transactions.filter(member=member)
            except Member.DoesNotExist:
                # User doesn't have a member account, return empty results
                return JsonResponse({'success': True, 'transactions': []})
            except Member.MultipleObjectsReturned:
                # Multiple members found, use the first one
                member = Member.objects.filter(user=request.user, is_active=True).first()
                if member:
                    transactions = transactions.filter(member=member)
                else:
                    return JsonResponse({'success': True, 'transactions': []})
        
        # Order and limit results
        transactions = transactions.order_by('-created_at')[:20]
        
        results = []
        for transaction in transactions:
            # Get transaction items
            items = []
            for item in transaction.items.all():
                items.append({
                    'product_name': item.product_name,
                    'quantity': item.quantity,
                    'total_price': str(item.total_price),
                })
            
            results.append({
                'id': transaction.id,
                'transaction_number': transaction.transaction_number,
                'member_name': transaction.member.full_name if transaction.member else 'Guest',
                'member_id': transaction.member.id if transaction.member else None,
                'total_amount': str(transaction.total_amount),
                'payment_method': transaction.get_payment_method_display(),
                'created_at': transaction.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'items_count': transaction.items.count(),
                'items': items,
            })
        
        return JsonResponse({'success': True, 'transactions': results})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@login_required
@require_http_methods(["POST"])
def api_process_refund(request):
    """Process a refund for a transaction
    
    Access control:
    - Regular members: can only refund their own transactions
    - Cashiers and admins: can refund any transaction
    """
    try:
        data = json.loads(request.body)
        transaction_id = data.get('transaction_id')
        refund_reason = data.get('reason', '').strip()
        
        if not transaction_id:
            return JsonResponse({'success': False, 'error': 'Transaction ID is required'})
        
        try:
            transaction = Transaction.objects.get(id=transaction_id, status='completed')
        except Transaction.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Transaction not found or not eligible for refund'})
        
        # Check access control: regular members can only refund their own transactions
        has_full_access = is_cashier_or_admin(request.user)
        if not has_full_access:
            # Get member associated with the logged-in user
            try:
                user_member = Member.objects.get(user=request.user, is_active=True)
            except Member.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'You do not have permission to process refunds'}, status=403)
            except Member.MultipleObjectsReturned:
                user_member = Member.objects.filter(user=request.user, is_active=True).first()
                if not user_member:
                    return JsonResponse({'success': False, 'error': 'You do not have permission to process refunds'}, status=403)
            
            # Check if the transaction belongs to the user
            if transaction.member != user_member:
                return JsonResponse({'success': False, 'error': 'You can only refund your own transactions'}, status=403)
        
        member = transaction.member
        
        # Capture balances before refund for receipt
        balance_before = None
        balance_after = None
        utang_before = None
        utang_after = None
        
        # Process refund based on payment method
        if transaction.payment_method == 'debit' and member:
            # Refund to balance
            balance_before = member.balance
            member.add_balance(transaction.total_amount)
            balance_after = member.balance
            utang_before = member.utang_balance
            utang_after = member.utang_balance
            
            # Record balance transaction
            BalanceTransaction.objects.create(
                member=member,
                transaction_type='deposit',
                amount=transaction.total_amount,
                balance_before=balance_before,
                balance_after=balance_after,
                utang_before=utang_before,
                utang_after=utang_after,
                notes=f"Refund for transaction {transaction.transaction_number}. {refund_reason}" if refund_reason else f"Refund for transaction {transaction.transaction_number}"
            )
        
        elif transaction.payment_method == 'credit' and member:
            # Reduce utang
            utang_before = member.utang_balance
            balance_before = member.balance
            if member.reduce_utang(transaction.total_amount):
                utang_after = member.utang_balance
                balance_after = member.balance
                
                # Record balance transaction
                BalanceTransaction.objects.create(
                    member=member,
                    transaction_type='utang_payment',
                    amount=transaction.total_amount,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    utang_before=utang_before,
                    utang_after=utang_after,
                    notes=f"Refund for transaction {transaction.transaction_number}. {refund_reason}" if refund_reason else f"Refund for transaction {transaction.transaction_number}"
                )
        
        # Restore product stock
        for item in transaction.items.all():
            if item.product:
                item.product.stock_quantity += item.quantity
                item.product.save()
        
        # Mark transaction as cancelled
        transaction.status = 'cancelled'
        transaction.notes = f"Refunded. {refund_reason}" if refund_reason else "Refunded"
        transaction.save()
        
        # Refresh member to get updated balances
        if member:
            member.refresh_from_db()
        
        # Generate refund receipt data
        receipt_data = generate_refund_receipt_data(transaction, refund_reason, member, balance_before, balance_after, utang_before, utang_after)
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully processed refund for transaction {transaction.transaction_number}',
            'transaction': {
                'id': transaction.id,
                'transaction_number': transaction.transaction_number,
                'refund_amount': str(transaction.total_amount),
            },
            'receipt': receipt_data
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})