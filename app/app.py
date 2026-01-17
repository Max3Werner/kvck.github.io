#!/usr/bin/env python3
"""
Klubbans Vänner - Cycling Club Web Application
Run with: python app.py
"""

from __init__ import create_app

app = create_app()

if __name__ == '__main__':
    print("\n🚴 Klubbans Vänner startar...")
    print("📍 Öppna http://localhost:5001 i din webbläsare")
    print("🔐 Admin-konto: klubban / klubban2026")
    print("\nTryck Ctrl+C för att stänga av servern\n")
    app.run(debug=True, host='0.0.0.0', port=5001)
