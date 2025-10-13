from functools import wraps
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.urls import reverse
import pandas as pd

def manager_view(template_name=None):
    """
    Decorator for manager views that handles common functionality:
    - Ensures manager is logged in
    - Provides consistent template rendering
    - Handles DataFrame to dict conversion
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Check if user is logged in and is a manager
            is_authenticated = request.session.get('authenticated', False)
            user_role = request.session.get('user_role', '')
            
            if not is_authenticated:
                # Not logged in at all - redirect to login
                return redirect('accounts:login')
            
            if user_role != 'Manager':
                # Logged in but wrong role - redirect to appropriate role page
                if user_role == 'Master':
                    return redirect('/master/')
                elif user_role == 'Tenaga Kesehatan':
                    return redirect('/nurse/')
                elif user_role == 'Karyawan':
                    return redirect('/karyawan/')
                else:
                    # Unknown role - logout and redirect to login
                    request.session.flush()
                    return redirect('accounts:login')

            # Call the view function
            response = view_func(request, *args, **kwargs)

            # If the response is already an HttpResponse, return it
            if isinstance(response, HttpResponse):
                return response

            # If the response is a tuple of (template, context)
            if isinstance(response, tuple) and len(response) == 2:
                template_override, context = response
                template_to_use = template_override or template_name
            else:
                # Response is just context
                template_to_use = template_name
                context = response if isinstance(response, dict) else {}

            # If no template specified, return context as JSON
            if not template_to_use:
                return JsonResponse(context)

            # Convert any DataFrames in context to dicts
            for key, value in context.items():
                if isinstance(value, pd.DataFrame):
                    context[key] = value.to_dict('records')

            # Add request.user to context if needed
            if 'user' not in context and hasattr(request, 'user'):
                context['user'] = request.user

            return render(request, template_to_use, context)

        return _wrapped_view
    return decorator