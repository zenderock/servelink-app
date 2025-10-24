#!/usr/bin/env python3
import sys
sys.path.insert(0, 'app')

from forms.project import validate_start_command
from wtforms import StringField, Form
from wtforms.validators import ValidationError

class TestForm(Form):
    start_command = StringField()

test_cases = [
    ("gunicorn app:app", True, "Single worker gunicorn (no flag)"),
    ("gunicorn -w 1 app:app", True, "Gunicorn with 1 worker"),
    ("gunicorn --workers 1 app:app", True, "Gunicorn with 1 worker (long flag)"),
    ("gunicorn -w 2 app:app", False, "Gunicorn with 2 workers"),
    ("gunicorn --workers 4 app:app", False, "Gunicorn with 4 workers"),
    ("gunicorn -w 10 app:app", False, "Gunicorn with 10 workers"),
    ("uvicorn app:app", True, "Single worker uvicorn"),
    ("uvicorn --workers 3 app:app", False, "Uvicorn with 3 workers"),
    ("hypercorn -w 2 app:app", False, "Hypercorn with 2 workers"),
    ("python manage.py runserver", True, "Django runserver"),
    ("node server.js", True, "Node.js server"),
    ("puma -w 5 config.ru", False, "Puma with 5 workers"),
    ("waitress-serve --threads 8 app:app", False, "Waitress with 8 threads"),
]

print("=== Test de validation des commandes de démarrage ===\n")

passed = 0
failed = 0

for command, should_pass, description in test_cases:
    form = TestForm()
    form.start_command.data = command
    
    try:
        validate_start_command(form, form.start_command)
        result = "✅ PASS" if should_pass else "❌ FAIL"
        if should_pass:
            passed += 1
        else:
            failed += 1
            print(f"{result} - {description}")
            print(f"  Command: {command}")
            print(f"  Expected: Validation error, Got: No error\n")
    except ValidationError as e:
        result = "❌ FAIL" if should_pass else "✅ PASS"
        if not should_pass:
            passed += 1
        else:
            failed += 1
            print(f"{result} - {description}")
            print(f"  Command: {command}")
            print(f"  Expected: No error, Got: {str(e)}\n")

print(f"\n{'='*60}")
print(f"Résultats: {passed}/{len(test_cases)} tests réussis, {failed} échecs")
print(f"{'='*60}")
