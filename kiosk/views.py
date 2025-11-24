from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.db.models import Q
from django.db import transaction as db_transaction
from inventory.models import Product, StockTransaction
from members.models import Member
from transactions.models import Transaction, TransactionItem
from decimal import Decimal
import json
import random
import string
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt


def generate_transaction_number():
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.digits, k=4))
    return f"TXN{timestamp}{random_str}"


from django.contrib.auth.decorators import login_required

@login_required
@ensure_csrf_cookie
def kiosk_home(request):
    # Pass VAT settings so client-side JS can use the same configuration
    context = {
        'VAT_RATE': settings.VAT_RATE,
        'VAT_INCLUSIVE': settings.VAT_INCLUSIVE,
    }
    return render(request, 'kiosk/kiosk.html', context)


@require_http_methods(["POST"])
def scan_product(request):
    try:
        data = json.loads(request.body)
        barcode = data.get('barcode')
        
        if not barcode:
            return JsonResponse({'success': False, 'error': 'Barcode is required'})
        
        try:
            product = Product.objects.get(barcode=barcode, is_active=True)
            
            if product.stock_quantity <= 0:
                return JsonResponse({'success': False, 'error': 'Product is out of stock'})
            
            # Check if product is expired
            if product.is_expired:
                expiration_date_str = product.expiration_date.strftime('%B %d, %Y') if product.expiration_date else 'N/A'
                return JsonResponse({
                    'success': False, 
                    'error': f'This product has expired (Expiration: {expiration_date_str}). Cannot be scanned for safety reasons.'
                })
            
            return JsonResponse({
                'success': True,
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'barcode': product.barcode,
                    'price': str(product.price),
                    'image': product.image.url if product.image else None,
                    'stock': product.stock_quantity,
                }
            })
        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Product not found'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@require_http_methods(["GET"])
def search_products(request):
    """
    Simple product search endpoint used by the kiosk JS.
    Query parameter: `q` (string). Returns JSON: { results: [ {id,name,barcode,price,stock}, ... ] }
    Matches against name (icontains) and barcode (exact or contains) and only active products.
    """
    q = request.GET.get('q', '')
    q = (q or '').strip()
    if not q or len(q) < 2:
        return JsonResponse({'results': []})

    try:
        # prefer name icontains, but allow barcode matches as well
        qs = Product.objects.filter(is_active=True)
        # If q looks numeric, include barcode matches first
        if q.isdigit():
            qs = qs.filter(Q(barcode__icontains=q) | Q(name__icontains=q))
        else:
            qs = qs.filter(name__icontains=q)

        qs = qs.order_by('name')[:50]

        results = []
        for p in qs:
            # Filter out expired products from search results
            if p.is_expired:
                continue
            results.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode,
                'price': str(p.price),
                'stock': getattr(p, 'stock_quantity', getattr(p, 'stock', 0)),
            })

        return JsonResponse({'results': results})
    except Exception:
        return JsonResponse({'results': []})


@require_http_methods(["POST"])
def scan_rfid(request):
    try:
        data = json.loads(request.body)
        rfid = data.get('rfid')
        
        if not rfid:
            return JsonResponse({'success': False, 'error': 'RFID is required'})
        
        try:
            member = Member.objects.get(rfid_card_number=rfid, is_active=True)
            
            request.session['kiosk_member_id'] = member.id
            request.session['kiosk_member_rfid'] = member.rfid_card_number
            
            return JsonResponse({
                'success': True,
                'member': {
                    'id': member.id,
                    'name': member.full_name,
                    'rfid': member.rfid_card_number,
                    'balance': str(member.balance),
                    'utang_balance': str(member.utang_balance),
                }
            })
        except Member.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member not found'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Server error occurred'})


@require_http_methods(["POST"])
@db_transaction.atomic
def process_payment(request):
    try:
        data = json.loads(request.body)
        
        member_id = data.get('member_id')
        items = data.get('items', [])
        payment_method = data.get('payment_method')
        
        if not items:
            return JsonResponse({'success': False, 'error': 'No items in cart'})
        
        if not payment_method or payment_method not in ['debit', 'credit', 'cash']:
            return JsonResponse({'success': False, 'error': 'Invalid payment method'})
        
        member = None
        if member_id:
            try:
                member_id = int(member_id)
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid member ID'})
            
            session_member_id = request.session.get('kiosk_member_id')
            
            if payment_method in ['debit', 'credit']:
                if not session_member_id or session_member_id != member_id:
                    return JsonResponse({'success': False, 'error': 'Member authentication required. Please scan RFID card again.'})
            
            try:
                member = Member.objects.get(id=member_id, is_active=True)
            except Member.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Member not found or inactive'})
            # For debit/credit payments require PIN validation
            if payment_method in ['debit', 'credit']:
                pin = data.get('pin')
                if not pin:
                    return JsonResponse({'success': False, 'error': 'PIN is required for member payments'})
                if not member.check_pin(pin):
                    return JsonResponse({'success': False, 'error': 'Invalid PIN'})
        else:
            if payment_method in ['debit', 'credit']:
                return JsonResponse({'success': False, 'error': 'Member required for debit/credit payment'})
            # For cash transactions, if user is logged in, try to associate with their member account
            elif payment_method == 'cash' and request.user.is_authenticated:
                try:
                    # Try to get the member associated with the logged-in user
                    member = Member.objects.get(user=request.user, is_active=True)
                except Member.DoesNotExist:
                    # User doesn't have a member account, that's okay for cash transactions
                    pass
                except Member.MultipleObjectsReturned:
                    # Multiple members found, use the first one
                    member = Member.objects.filter(user=request.user, is_active=True).first()
        
        # Validate item data and lock involved product rows to prevent race conditions
        product_ids = []
        for item_data in items:
            if 'product_id' not in item_data or 'quantity' not in item_data:
                return JsonResponse({'success': False, 'error': 'Invalid item data'})
            try:
                quantity = int(item_data['quantity'])
                if quantity <= 0:
                    return JsonResponse({'success': False, 'error': 'Quantity must be a positive number'})
                if quantity > 1000:
                    return JsonResponse({'success': False, 'error': 'Quantity exceeds maximum allowed (1000)'})
                item_data['quantity'] = quantity
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid quantity value'})
            product_ids.append(item_data['product_id'])

        # Lock product rows so stock checks and reductions are consistent under concurrency
        products_qs = Product.objects.select_for_update().filter(id__in=product_ids, is_active=True)
        product_map = {p.id: p for p in products_qs}

        # Ensure all requested products exist and have sufficient stock
        for item_data in items:
            pid = item_data['product_id']
            product = product_map.get(pid)
            if not product:
                return JsonResponse({'success': False, 'error': 'Invalid product'})
            if product.stock_quantity < item_data['quantity']:
                return JsonResponse({'success': False, 'error': f'Insufficient stock for {product.name}'})
            # Safety check: prevent purchasing expired products
            if product.is_expired:
                expiration_date_str = product.expiration_date.strftime('%B %d, %Y') if product.expiration_date else 'N/A'
                return JsonResponse({
                    'success': False, 
                    'error': f'Cannot purchase {product.name} - Product has expired (Expiration: {expiration_date_str}). For safety reasons, expired products cannot be sold.'
                })
        
        transaction = Transaction.objects.create(
            transaction_number=generate_transaction_number(),
            member=member,
            payment_method=payment_method,
            status='pending'
        )
        
        for item_data in items:
            pid = item_data['product_id']
            product = product_map.get(pid) or Product.objects.get(id=pid)
            # record current stock before change
            before_stock = product.stock_quantity

            TransactionItem.objects.create(
                transaction=transaction,
                product=product,
                product_name=product.name,
                product_barcode=product.barcode,
                unit_price=product.price,
                quantity=item_data['quantity']
            )

            # Attempt to reduce stock on the locked product instance
            if product.stock_quantity >= item_data['quantity']:
                product.stock_quantity -= item_data['quantity']
                product.save()
                StockTransaction.objects.create(
                    product=product,
                    transaction_type='out',
                    quantity=item_data['quantity'],
                    stock_before=before_stock,
                    stock_after=product.stock_quantity,
                    notes=f'Sale via kiosk transaction {transaction.transaction_number}'
                )
            else:
                raise Exception(f'Failed to reduce stock for {product.name}')
        
        transaction.calculate_totals()
        transaction.calculate_patronage()
        
        # Capture member balances before any changes for transparency in the response
        member_before_balance = None
        member_before_utang = None
        if member:
            member_before_balance = getattr(member, 'balance', None)
            member_before_utang = getattr(member, 'utang_balance', None)

        if payment_method == 'debit' and member:
            if member.balance >= transaction.total_amount:
                member.deduct_balance(transaction.total_amount)
                transaction.amount_from_balance = transaction.total_amount
                transaction.status = 'completed'
            else:
                amount_from_balance = member.balance
                member.deduct_balance(amount_from_balance)
                transaction.amount_from_balance = amount_from_balance
                
                amount_to_utang = transaction.total_amount - amount_from_balance
                member.add_utang(amount_to_utang)
                transaction.amount_to_utang = amount_to_utang
                transaction.payment_method = 'credit'
                transaction.status = 'completed'
        
        elif payment_method == 'credit' and member:
            member.add_utang(transaction.total_amount)
            transaction.amount_to_utang = transaction.total_amount
            transaction.status = 'completed'
        
        elif payment_method == 'cash':
            transaction.amount_paid = transaction.total_amount
            transaction.status = 'completed'
        
        transaction.save()
        
        if member:
            member.last_transaction = timezone.now()
            member.save()
        
        request.session.pop('kiosk_member_id', None)
        request.session.pop('kiosk_member_rfid', None)
        
        # Prepare member summary for response
        member_summary = None
        if member:
            member_summary = {
                'id': member.id,
                'name': member.full_name,
                'balance_before': str(member_before_balance) if member_before_balance is not None else str(member.balance),
                'balance_after': str(member.balance),
                'utang_before': str(member_before_utang) if member_before_utang is not None else str(member.utang_balance),
                'utang_after': str(member.utang_balance),
            }

        return JsonResponse({
            'success': True,
            'transaction': {
                'id': transaction.id,
                'transaction_number': transaction.transaction_number,
                    'subtotal': str(transaction.subtotal),
                    'vatable_sale': str(transaction.vatable_sale),
                'vat_amount': str(transaction.vat_amount),
                'items': [
                    {
                        'product_name': ti.product_name,
                        'quantity': ti.quantity,
                        'unit_price': str(ti.unit_price),
                        'total_price': str(ti.total_price),
                        'vat_amount': str(ti.vat_amount),
                        'vatable_sale': str(ti.vatable_sale),
                    } for ti in transaction.items.all()
                ],
                'total_amount': str(transaction.total_amount),
                'amount_to_utang': str(transaction.amount_to_utang),
                'patronage_amount': str(transaction.patronage_amount),
                'new_utang_balance': str(member.utang_balance) if member else '0.00',
                'amount_from_balance': str(transaction.amount_from_balance),
                'amount_paid': str(transaction.amount_paid),
                'member': member_summary,
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Transaction failed: {str(e)}'})


@csrf_exempt
@require_http_methods(["POST"])
def print_receipt_local(request):
    """
    POST endpoint to print plain-text receipts on the server's default Windows printer.
    Expects JSON: { "text": "...receipt text..." }
    This endpoint attempts to use pywin32 (win32print). If pywin32 is not installed or
    printing fails, it returns success: false with an error message.
    """
    try:
        data = json.loads(request.body)
        text = data.get('text', '')
        if not text:
            return JsonResponse({'success': False, 'error': 'No text to print'})

        try:
            import win32print

            printer_name = win32print.GetDefaultPrinter()
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                # Start a RAW print job
                win32print.StartDocPrinter(hPrinter, 1, ("KioskReceipt", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                # Write bytes to printer (encode as utf-8)
                win32print.WritePrinter(hPrinter, text.encode('utf-8'))
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Printing failed: {str(e)}'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
