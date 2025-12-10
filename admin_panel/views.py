import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Avg, Q, F
from django.db.models.functions import TruncDate
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.template.loader import render_to_string

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
@require_http_methods(["POST"])
def api_create_product(request):
    """Create a product without using the Django admin UI"""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    name = (data.get('name') or '').strip()
    barcode = (data.get('barcode') or '').strip()
    description = (data.get('description') or '').strip()
    category_id = data.get('category_id')
    is_active = bool(data.get('is_active', True))

    if not name:
        return JsonResponse({'success': False, 'error': 'Product name is required'}, status=400)
    if not barcode:
        return JsonResponse({'success': False, 'error': 'Barcode is required'}, status=400)
    if Product.objects.filter(barcode=barcode).exists():
        return JsonResponse({'success': False, 'error': 'A product with this barcode already exists'}, status=400)

    try:
        price = Decimal(str(data.get('price', '0')))
        cost = Decimal(str(data.get('cost', '0')))
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid price or cost value'}, status=400)

    try:
        stock_quantity = int(data.get('stock_quantity', 0))
        low_stock_threshold = int(data.get('low_stock_threshold', 10))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Stock quantities must be whole numbers'}, status=400)

    category = None
    if category_id:
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Selected category does not exist'}, status=400)

    product = Product.objects.create(
        name=name,
        barcode=barcode,
        description=description,
        category=category,
        price=price,
        cost=cost,
        stock_quantity=stock_quantity,
        low_stock_threshold=low_stock_threshold,
        is_active=is_active,
    )

    return JsonResponse({
        'success': True,
        'message': 'Product created successfully',
        'product': {
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'price': str(product.price),
            'stock_quantity': product.stock_quantity,
            'category': product.category.name if product.category else None,
            'is_active': product.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_create_category(request):
    """Create a category without using the Django admin UI"""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    is_active = bool(data.get('is_active', True))

    if not name:
        return JsonResponse({'success': False, 'error': 'Category name is required'}, status=400)

    category = Category.objects.create(
        name=name,
        description=description,
        is_active=is_active,
    )

    return JsonResponse({
        'success': True,
        'message': 'Category created successfully',
        'category': {
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'is_active': category.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_update_product(request):
    """Update a product without using the Django admin UI"""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    product_id = data.get('id')
    if not product_id:
        return JsonResponse({'success': False, 'error': 'Product ID is required'}, status=400)

    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    name = (data.get('name') or '').strip()
    barcode = (data.get('barcode') or '').strip()
    description = (data.get('description') or '').strip()
    category_id = data.get('category_id')
    is_active = bool(data.get('is_active', True))

    if not name:
        return JsonResponse({'success': False, 'error': 'Product name is required'}, status=400)
    if not barcode:
        return JsonResponse({'success': False, 'error': 'Barcode is required'}, status=400)
    
    # Check if barcode is already used by another product
    if Product.objects.filter(barcode=barcode).exclude(id=product_id).exists():
        return JsonResponse({'success': False, 'error': 'A product with this barcode already exists'}, status=400)

    try:
        price = Decimal(str(data.get('price', '0')))
        cost = Decimal(str(data.get('cost', '0')))
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid price or cost value'}, status=400)

    try:
        stock_quantity = int(data.get('stock_quantity', 0))
        low_stock_threshold = int(data.get('low_stock_threshold', 10))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Stock quantities must be whole numbers'}, status=400)

    category = None
    if category_id:
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Selected category does not exist'}, status=400)

    # Update product
    product.name = name
    product.barcode = barcode
    product.description = description
    product.category = category
    product.price = price
    product.cost = cost
    product.stock_quantity = stock_quantity
    product.low_stock_threshold = low_stock_threshold
    product.is_active = is_active
    product.save()

    return JsonResponse({
        'success': True,
        'message': 'Product updated successfully',
        'product': {
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'price': str(product.price),
            'stock_quantity': product.stock_quantity,
            'category': product.category.name if product.category else None,
            'is_active': product.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_update_category(request):
    """Update a category without using the Django admin UI"""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    category_id = data.get('id')
    if not category_id:
        return JsonResponse({'success': False, 'error': 'Category ID is required'}, status=400)

    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Category not found'}, status=404)

    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    is_active = bool(data.get('is_active', True))

    if not name:
        return JsonResponse({'success': False, 'error': 'Category name is required'}, status=400)

    # Update category
    category.name = name
    category.description = description
    category.is_active = is_active
    category.save()

    return JsonResponse({
        'success': True,
        'message': 'Category updated successfully',
        'category': {
            'id': category.id,
            'name': category.name,
            'description': category.description,
            'is_active': category.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_create_member_type(request):
    """Create a member type without the Django admin UI."""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    patronage_rate = data.get('patronage_rate', 0.05)
    is_active = bool(data.get('is_active', True))

    if not name:
        return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)

    try:
        patronage_rate = Decimal(str(patronage_rate))
        if patronage_rate < 0 or patronage_rate > 1:
            return JsonResponse({'success': False, 'error': 'Patronage rate must be between 0 and 1'}, status=400)
    except (InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid patronage rate format'}, status=400)

    member_type = MemberType.objects.create(
        name=name,
        description=description,
        patronage_rate=patronage_rate,
        is_active=is_active,
    )

    return JsonResponse({
        'success': True,
        'message': 'Member type created successfully',
        'member_type': {
            'id': member_type.id,
            'name': member_type.name,
            'description': member_type.description,
            'patronage_rate': str(member_type.patronage_rate),
            'is_active': member_type.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_update_member_type(request):
    """Update a member type without the Django admin UI."""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    member_type_id = data.get('id')
    if not member_type_id:
        return JsonResponse({'success': False, 'error': 'Member type ID is required'}, status=400)

    try:
        member_type = MemberType.objects.get(id=member_type_id)
    except MemberType.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Member type not found'}, status=404)

    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    patronage_rate = data.get('patronage_rate')
    is_active = bool(data.get('is_active', member_type.is_active))

    if not name:
        return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)

    if patronage_rate is not None:
        try:
            patronage_rate = Decimal(str(patronage_rate))
            if patronage_rate < 0 or patronage_rate > 1:
                return JsonResponse({'success': False, 'error': 'Patronage rate must be between 0 and 1'}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid patronage rate format'}, status=400)
    else:
        patronage_rate = member_type.patronage_rate

    # Update the member type
    member_type.name = name
    member_type.description = description
    member_type.patronage_rate = patronage_rate
    member_type.is_active = is_active
    member_type.save()

    return JsonResponse({
        'success': True,
        'message': 'Member type updated successfully',
        'member_type': {
            'id': member_type.id,
            'name': member_type.name,
            'description': member_type.description,
            'patronage_rate': str(member_type.patronage_rate),
            'is_active': member_type.is_active,
        }
    })


@login_required
@require_http_methods(["POST"])
def api_create_member(request):
    """Create a member without redirecting to the admin site."""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    rfid = (data.get('rfid') or '').strip()
    email = (data.get('email') or '').strip() or None
    phone = (data.get('phone') or '').strip()
    member_type_id = data.get('member_type_id')
    role = (data.get('role') or 'member').strip() or 'member'
    is_active = bool(data.get('is_active', True))

    if not first_name or not last_name:
        return JsonResponse({'success': False, 'error': 'First and last name are required'}, status=400)
    if not rfid:
        return JsonResponse({'success': False, 'error': 'RFID card number is required'}, status=400)
    if Member.objects.filter(rfid_card_number=rfid).exists():
        return JsonResponse({'success': False, 'error': 'RFID card number already exists'}, status=400)
    if email and Member.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'error': 'Email already exists'}, status=400)

    member_type = None
    if member_type_id:
        try:
            member_type = MemberType.objects.get(id=member_type_id)
        except MemberType.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Selected member type does not exist'}, status=400)

    member = Member.objects.create(
        first_name=first_name,
        last_name=last_name,
        rfid_card_number=rfid,
        email=email,
        phone=phone,
        member_type=member_type,
        role=role if role in dict(Member.ROLE_CHOICES) else 'member',
        is_active=is_active,
    )

    return JsonResponse({
        'success': True,
        'message': 'Member created successfully',
        'member': {
            'id': member.id,
            'name': member.full_name,
            'rfid': member.rfid_card_number,
            'email': member.email or '',
            'phone': member.phone,
            'member_type': member.member_type.name if member.member_type else '',
            'role': member.role,
            'is_active': member.is_active,
            'balance': str(member.balance),
            'utang_balance': str(member.utang_balance),
        }
    })


@login_required
@require_http_methods(["POST"])
def api_update_member(request):
    """Update a member without redirecting to the admin site."""
    if not is_admin_user(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    member_id = data.get('member_id')
    if not member_id:
        return JsonResponse({'success': False, 'error': 'Member ID is required'}, status=400)

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Member not found'}, status=404)

    first_name = (data.get('first_name') or member.first_name).strip()
    last_name = (data.get('last_name') or member.last_name).strip()
    rfid = (data.get('rfid') or member.rfid_card_number).strip()
    email = (data.get('email') or '').strip() or None
    phone = (data.get('phone') or member.phone).strip()
    member_type_id = data.get('member_type_id')
    role = (data.get('role') or member.role).strip()
    is_active = bool(data.get('is_active', member.is_active))

    if not first_name or not last_name:
        return JsonResponse({'success': False, 'error': 'First and last name are required'}, status=400)
    if not rfid:
        return JsonResponse({'success': False, 'error': 'RFID card number is required'}, status=400)

    if Member.objects.filter(rfid_card_number=rfid).exclude(id=member.id).exists():
        return JsonResponse({'success': False, 'error': 'RFID card number already exists'}, status=400)
    if email and Member.objects.filter(email=email).exclude(id=member.id).exists():
        return JsonResponse({'success': False, 'error': 'Email already exists'}, status=400)

    member_type = None
    if member_type_id:
        try:
            member_type = MemberType.objects.get(id=member_type_id)
        except MemberType.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Selected member type does not exist'}, status=400)

    member.first_name = first_name
    member.last_name = last_name
    member.rfid_card_number = rfid
    member.email = email
    member.phone = phone
    member.member_type = member_type
    member.role = role if role in dict(Member.ROLE_CHOICES) else member.role
    member.is_active = is_active
    member.save()

    return JsonResponse({
        'success': True,
        'message': 'Member updated successfully',
        'member': {
            'id': member.id,
            'name': member.full_name,
            'rfid': member.rfid_card_number,
            'email': member.email or '',
            'phone': member.phone,
            'member_type': member.member_type.name if member.member_type else '',
            'role': member.role,
            'is_active': member.is_active,
            'balance': str(member.balance),
            'utang_balance': str(member.utang_balance),
        }
    })


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
    transactions_qs = Transaction.objects.select_related('member').prefetch_related('items').order_by('-created_at')
    paginator = Paginator(transactions_qs, 10)
    page_number = request.GET.get('page', 1)
    transactions_page = paginator.get_page(page_number)
    
    # Calculate statistics
    total_transactions = transactions_qs.count()
    completed_transactions = transactions_qs.filter(status='completed').count()
    pending_transactions = transactions_qs.filter(status='pending').count()
    cancelled_transactions = transactions_qs.filter(status='cancelled').count()
    total_revenue = transactions_qs.filter(status='completed').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    context = {
        'transactions': transactions_page,
        'page_obj': transactions_page,
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


def generate_refund_receipt_data(transaction, refund_reason, member, balance_before=None, balance_after=None, utang_before=None, utang_after=None, request=None):
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
    lines.append(timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'))
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
    
    # Payment method refund info - All refunds now go to balance
    lines.append('REFUND METHOD:')
    if member and balance_before is not None:
        lines.append('Refunded to Member Balance')
        lines.append(f'Balance Before: {money(balance_before)}')
        lines.append(f'Balance After: {money(balance_after)}')
    else:
        lines.append('Refunded to Member Balance')
    lines.append('')
    
    # Reason if provided
    if refund_reason:
        lines.append('Reason:')
        lines.append(refund_reason)
        lines.append('')
    
    lines.append('Thank you!')
    
    return {
        'text': '\r\n'.join(lines),
        'html': generate_refund_receipt_html(transaction, refund_reason, member, balance_before, balance_after, utang_before, utang_after, request=request)
    }


def generate_refund_receipt_html(transaction, refund_reason, member, balance_before=None, balance_after=None, utang_before=None, utang_after=None, request=None):
    """Generate HTML version of refund receipt using template"""
    from django.conf import settings
    
    vat_rate = getattr(settings, 'VAT_RATE', 0.12)
    vat_rate_percent = int(vat_rate * 100)
    
    # Get shop information
    shop_name = getattr(settings, 'SHOP_NAME', 'COOPERATIVE STORE')
    shop_address = getattr(settings, 'SHOP_ADDRESS', 'Address: Lorem Ipsum, 23-10')
    shop_phone = getattr(settings, 'SHOP_PHONE', 'Telp. 11223344')
    
    # Determine refund method display - All refunds now go to balance
    show_balance_refund = (member and balance_before is not None)
    show_utang_refund = False  # No longer reducing utang, all refunds go to balance
    show_cash_refund = False  # Cash refunds also go to balance now
    
    context = {
        'transaction': transaction,
        'member': member,
        'refund_reason': refund_reason,
        'refund_date': timezone.localtime(timezone.now()),
        'vat_rate_percent': vat_rate_percent,
        'balance_before': balance_before,
        'balance_after': balance_after,
        'utang_before': utang_before,
        'utang_after': utang_after,
        'show_balance_refund': show_balance_refund,
        'show_utang_refund': show_utang_refund,
        'show_cash_refund': show_cash_refund,
        'shop_name': shop_name,
        'shop_address': shop_address,
        'shop_phone': shop_phone,
    }
    
    # Render the template - use request if provided for proper context
    if request:
        html = render_to_string('admin_panel/refund_receipt.html', context, request=request)
    else:
        html = render_to_string('admin_panel/refund_receipt.html', context)
    
    return html


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
def view_refund_receipt(request, transaction_id):
    """View refund receipt for a cancelled transaction
    
    Access control:
    - Regular members: can only view receipts for their own transactions
    - Cashiers and admins: can view any transaction receipt
    """
    try:
        # Get the transaction - must be cancelled (refunded)
        transaction = Transaction.objects.select_related('member').prefetch_related('items').get(
            id=transaction_id, 
            status='cancelled'
        )
        
        # Check access control
        has_full_access = is_cashier_or_admin(request.user)
        if not has_full_access:
            # Get member associated with the logged-in user
            try:
                user_member = Member.objects.get(user=request.user, is_active=True)
            except Member.DoesNotExist:
                messages.error(request, 'You do not have permission to view this receipt')
                return redirect('process_refund')
            except Member.MultipleObjectsReturned:
                user_member = Member.objects.filter(user=request.user, is_active=True).first()
                if not user_member:
                    messages.error(request, 'You do not have permission to view this receipt')
                    return redirect('process_refund')
            
            # Check if the transaction belongs to the user
            if transaction.member != user_member:
                messages.error(request, 'You can only view receipts for your own transactions')
                return redirect('process_refund')
        
        member = transaction.member
        
        # Extract refund reason from transaction notes
        refund_reason = ''
        if transaction.notes and 'Refunded' in transaction.notes:
            # Extract reason if it exists (format: "Refunded. reason text")
            parts = transaction.notes.split('.', 1)
            if len(parts) > 1:
                refund_reason = parts[1].strip()
        
        # Try to get balance information from BalanceTransaction
        balance_before = None
        balance_after = None
        utang_before = None
        utang_after = None
        
        # Look for the most recent balance transaction related to this refund
        balance_txn = BalanceTransaction.objects.filter(
            notes__icontains=f'transaction {transaction.transaction_number}'
        ).filter(
            notes__icontains='Refund'
        ).order_by('-created_at').first()
        
        if balance_txn:
            balance_before = balance_txn.balance_before
            balance_after = balance_txn.balance_after
            utang_before = balance_txn.utang_before
            utang_after = balance_txn.utang_after
        elif member:
            # For cash refunds or if balance transaction not found, show current balance
            # Balance doesn't change for cash refunds, so before = after = current balance
            if transaction.payment_method == 'cash':
                balance_before = member.balance
                balance_after = member.balance
                utang_before = member.utang_balance
                utang_after = member.utang_balance
            else:
                # For other cases, try to get current balance as fallback
                balance_after = member.balance
                utang_after = member.utang_balance
        
        # Prepare context for template
        from django.conf import settings
        vat_rate = getattr(settings, 'VAT_RATE', 0.12)
        vat_rate_percent = int(vat_rate * 100)
        
        # Get shop information
        shop_name = getattr(settings, 'SHOP_NAME', 'COOPERATIVE STORE')
        shop_address = getattr(settings, 'SHOP_ADDRESS', 'Address: Lorem Ipsum, 23-10')
        shop_phone = getattr(settings, 'SHOP_PHONE', 'Telp. 11223344')
        
        # All refunds now go to balance, regardless of original payment method
        show_balance_refund = (member and balance_before is not None)
        show_utang_refund = False  # No longer reducing utang, all refunds go to balance
        show_cash_refund = False  # Cash refunds also go to balance now        
        context = {
            'transaction': transaction,
            'member': member,
            'refund_reason': refund_reason,
            'refund_date': timezone.localtime(transaction.updated_at) if transaction.updated_at else timezone.localtime(timezone.now()),  # Use when transaction was cancelled, converted to local timezone
            'vat_rate_percent': vat_rate_percent,
            'balance_before': balance_before,
            'balance_after': balance_after,
            'utang_before': utang_before,
            'utang_after': utang_after,
            'show_balance_refund': show_balance_refund,
            'show_utang_refund': show_utang_refund,
            'show_cash_refund': show_cash_refund,
            'shop_name': shop_name,
            'shop_address': shop_address,
            'shop_phone': shop_phone,
        }
        
        return render(request, 'admin_panel/refund_receipt.html', context)
        
    except Transaction.DoesNotExist:
        messages.error(request, 'Refund receipt not found')
        return redirect('process_refund')
    except Exception as e:
        messages.error(request, f'Error loading receipt: {str(e)}')
        return redirect('process_refund')


@login_required
@require_http_methods(["GET"])
def view_cash_receipt(request, transaction_id):
    """View cash receipt for a completed cash transaction
    
    Access control:
    - Regular members: can only view receipts for their own transactions
    - Cashiers and admins: can view any transaction receipt
    """
    try:
        # Get the transaction - must be completed and cash payment
        transaction = Transaction.objects.select_related('member').prefetch_related('items').get(
            id=transaction_id, 
            status='completed',
            payment_method='cash'
        )
        
        # Check access control
        has_full_access = is_cashier_or_admin(request.user)
        if not has_full_access:
            # Get member associated with the logged-in user
            try:
                user_member = Member.objects.get(user=request.user, is_active=True)
            except Member.DoesNotExist:
                messages.error(request, 'You do not have permission to view this receipt')
                return redirect('transaction_history')
            except Member.MultipleObjectsReturned:
                user_member = Member.objects.filter(user=request.user, is_active=True).first()
                if not user_member:
                    messages.error(request, 'You do not have permission to view this receipt')
                    return redirect('transaction_history')
            
            # Check if the transaction belongs to the user
            if transaction.member != user_member:
                messages.error(request, 'You can only view receipts for your own transactions')
                return redirect('transaction_history')
        
        # Calculate change amount
        change_amount = Decimal('0.00')
        if transaction.amount_paid > transaction.total_amount:
            change_amount = transaction.amount_paid - transaction.total_amount
        
        # Get shop information from settings (with defaults)
        shop_name = getattr(settings, 'SHOP_NAME', 'COOPERATIVE STORE')
        shop_address = getattr(settings, 'SHOP_ADDRESS', 'Address: Lorem Ipsum, 23-10')
        shop_phone = getattr(settings, 'SHOP_PHONE', 'Telp. 11223344')
        
        context = {
            'transaction': transaction,
            'change_amount': change_amount,
            'shop_name': shop_name,
            'shop_address': shop_address,
            'shop_phone': shop_phone,
        }
        
        return render(request, 'admin_panel/cash_receipt.html', context)
        
    except Transaction.DoesNotExist:
        messages.error(request, 'Cash receipt not found')
        return redirect('transaction_history')
    except Exception as e:
        messages.error(request, f'Error loading receipt: {str(e)}')
        return redirect('transaction_history')


@login_required
@require_http_methods(["GET"])
def view_debit_credit_receipt(request, transaction_id):
    """View debit/credit receipt for a completed debit or credit transaction
    
    Access control:
    - Regular members: can only view receipts for their own transactions
    - Cashiers and admins: can view any transaction receipt
    """
    try:
        # Get the transaction - must be completed and debit or credit payment
        transaction = Transaction.objects.select_related('member').prefetch_related('items').get(
            id=transaction_id, 
            status='completed',
            payment_method__in=['debit', 'credit']
        )
        
        # Check access control
        has_full_access = is_cashier_or_admin(request.user)
        if not has_full_access:
            # Get member associated with the logged-in user
            try:
                user_member = Member.objects.get(user=request.user, is_active=True)
            except Member.DoesNotExist:
                messages.error(request, 'You do not have permission to view this receipt')
                return redirect('transaction_history')
            except Member.MultipleObjectsReturned:
                user_member = Member.objects.filter(user=request.user, is_active=True).first()
                if not user_member:
                    messages.error(request, 'You do not have permission to view this receipt')
                    return redirect('transaction_history')
            
            # Check if the transaction belongs to the user
            if transaction.member != user_member:
                messages.error(request, 'You can only view receipts for your own transactions')
                return redirect('transaction_history')
        
        # Get shop information from settings (with defaults)
        shop_name = getattr(settings, 'SHOP_NAME', 'BUSINESS NAME')
        shop_address = getattr(settings, 'SHOP_ADDRESS', '1234 Main Street, Suite 567, City Name, State 54321')
        shop_phone = getattr(settings, 'SHOP_PHONE', '123-456-7890')
        merchant_id = getattr(settings, 'MERCHANT_ID', None)
        terminal_id = getattr(settings, 'TERMINAL_ID', None)
        approval_code = getattr(settings, 'APPROVAL_CODE', None)
        
        # Refresh member to get latest balance and credit balance for transparency
        # Show credit balance on all debit/credit receipts with members
        if transaction.member:
            transaction.member.refresh_from_db()
        
        context = {
            'transaction': transaction,
            'shop_name': shop_name,
            'shop_address': shop_address,
            'shop_phone': shop_phone,
            'merchant_id': merchant_id,
            'terminal_id': terminal_id,
            'approval_code': approval_code,
        }
        
        return render(request, 'admin_panel/debit_credit_receipt.html', context)
        
    except Transaction.DoesNotExist:
        messages.error(request, 'Receipt not found')
        return redirect('transaction_history')
    except Exception as e:
        messages.error(request, f'Error loading receipt: {str(e)}')
        return redirect('transaction_history')


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
            # Prefetch related items for receipt generation
            transaction = Transaction.objects.select_related('member').prefetch_related('items').get(id=transaction_id, status='completed')
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
        
        # Process refund - ALL refunds go directly to card balance regardless of payment method
        if member:
            # Refund to balance for all payment methods
            balance_before = member.balance
            utang_before = member.utang_balance
            member.add_balance(transaction.total_amount)
            balance_after = member.balance
            utang_after = member.utang_balance  # Utang remains unchanged
            
            # Record balance transaction
            BalanceTransaction.objects.create(
                member=member,
                transaction_type='deposit',
                amount=transaction.total_amount,
                balance_before=balance_before,
                balance_after=balance_after,
                utang_before=utang_before,
                utang_after=utang_after,
                notes=f"Refund for transaction {transaction.transaction_number} (Original: {transaction.get_payment_method_display()}). {refund_reason}" if refund_reason else f"Refund for transaction {transaction.transaction_number} (Original: {transaction.get_payment_method_display()})"
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
        
        # Generate refund receipt data - pass request for proper template rendering
        receipt_data = generate_refund_receipt_data(transaction, refund_reason, member, balance_before, balance_after, utang_before, utang_after, request=request)
        
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