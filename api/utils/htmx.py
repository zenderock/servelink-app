from flask import render_template, request

def render_htmx_partial(template, **context):
    """Render a template within the fragment layout for HTMX requests"""
    if request.headers.get('HX-Request'):
        return render_template(
            'layouts/fragment.html',
            fragment_content=render_template(template, is_fragment=True, **context)
        )
    
    return render_template(template, **context)