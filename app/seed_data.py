#!/usr/bin/env python3
"""
Seed the database with sample data including Siljan Runt event.
Run with: python seed_data.py
"""

from datetime import datetime, timedelta
from __init__ import create_app
from models import db, User, Event, Activity

app = create_app()

with app.app_context():
    # Check if we already have events
    if Event.query.count() > 0:
        print("Database already has data. Skipping seed.")
    else:
        print("Seeding database with sample data...")

        # Get or create admin user
        admin = User.query.filter_by(username='klubban').first()
        if not admin:
            admin = User(
                username='klubban',
                email='klubban@klubbansvanners.se',
                display_name='Klubban',
                bio='Mystisk. Legendarisk. Alltid framför dig i backen.',
                is_admin=True
            )
            admin.set_password('klubban2026')
            db.session.add(admin)
            db.session.commit()

        # Create Siljan Runt event
        siljan_runt = Event(
            title='Siljan Runt – 59 år av dalacykling',
            subtitle='Dalacykling med Klubban',
            description='''Motionsrunda, inte tävling. Sollerö IF arrangerar och 2026 är det 59:e året.

DISTANSER:
• 7 mil (Orsasjön Runt)
• 12 mil (Siljan Runt)
• 16 mil (båda sjöarna)

PRAKTISKT:
• Kuperad terräng, så det finns backar
• Avslappnad stämning, fokus på att alla ska kunna delta
• Anmälan öppen nu
• Inga särskilda krav på utrustning

VARFÖR ÅKA:
En helg i Dalarna med cykling, relativt avslappnat tempo, etablerat lopp som har funnits i decennier.

Klubbans kommentar: "Jag cyklade 16 mil där 1987. Fortfarande ont i benen."

Kontakt: info@siljanrunt.se
Webbplats: https://www.siljanrunt.se''',
            event_type='external',
            date=datetime(2026, 6, 6, 8, 0),
            location='Runt Siljan och Orsasjön, Dalarna',
            distance_km=120,
            difficulty='medium',
            external_url='https://www.siljanrunt.se',
            is_featured=True,
            created_by_id=admin.id
        )
        db.session.add(siljan_runt)

        # Create more sample events
        events_data = [
            {
                'title': 'Morgonrunda med stil',
                'subtitle': 'Klassisk stockholmstur',
                'description': 'En klassisk morgontur genom stan innan Stockholm vaknar. Start vid Stureplan, finish med Stockholms bästa espresso.',
                'event_type': 'ride',
                'date': datetime.now() + timedelta(days=7),
                'location': 'Stureplan, Stockholm',
                'distance_km': 45,
                'difficulty': 'medium'
            },
            {
                'title': 'Fika & Cykla Special',
                'subtitle': 'Signaturtur med minst två fika-stopp',
                'description': 'Vår signaturtur: lätt tempo, vackra vyer och MINST två fika-stopp. Perfekt för nya medlemmar och alla som gillar kanelbullar.',
                'event_type': 'social',
                'date': datetime.now() + timedelta(days=14),
                'location': 'Djurgården, Stockholm',
                'distance_km': 25,
                'difficulty': 'easy'
            },
            {
                'title': 'Bergslagsutmaningen',
                'subtitle': 'För dig som vill testa gränserna',
                'description': 'Kuperad terräng, fantastisk utsikt och en välförtjänt lyxlunch vid målet. Klubban godkänner.',
                'event_type': 'ride',
                'date': datetime.now() + timedelta(days=21),
                'location': 'Nacka reservat',
                'distance_km': 80,
                'difficulty': 'hard'
            },
            {
                'title': 'Vinterglögg & Planering',
                'subtitle': 'Dags att planera vårens turer!',
                'description': 'Vi samlas för glögg (eller kaffe), gott snack och drömmer om långa sommarturer. Alla idéer välkomna!',
                'event_type': 'social',
                'date': datetime.now() + timedelta(days=30),
                'location': 'Klubblokalen',
                'distance_km': None,
                'difficulty': 'easy'
            }
        ]

        for event_data in events_data:
            event = Event(
                **event_data,
                created_by_id=admin.id
            )
            db.session.add(event)

        # Create sample activities
        activities_data = [
            {'activity_type': 'joined', 'message': 'Klubban skapade klubben! Välkomna!'},
            {'activity_type': 'created_event', 'message': 'Klubban skapade Siljan Runt 2026'},
            {'activity_type': 'created_event', 'message': 'Klubban skapade Morgonrunda med stil'},
        ]

        for act_data in activities_data:
            activity = Activity(
                **act_data,
                user_id=admin.id
            )
            db.session.add(activity)

        db.session.commit()
        print("✅ Database seeded successfully!")
        print(f"   - Created {Event.query.count()} events")
        print(f"   - Created {Activity.query.count()} activities")
        print(f"\n🔐 Admin login: klubban / klubban2026")
