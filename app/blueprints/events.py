from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Event, EventParticipant, Activity
from datetime import datetime

events_bp = Blueprint('events', __name__)


@events_bp.route('/')
def index():
    # Get all upcoming events
    upcoming_events = Event.query.filter(
        Event.date >= datetime.utcnow()
    ).order_by(Event.date).all()

    # Get past events (last 10)
    past_events = Event.query.filter(
        Event.date < datetime.utcnow()
    ).order_by(Event.date.desc()).limit(10).all()

    return render_template('events/index.html',
                           upcoming_events=upcoming_events,
                           past_events=past_events)


@events_bp.route('/<int:event_id>')
def detail(event_id):
    event = Event.query.get_or_404(event_id)
    participants = event.participants.all()

    is_participating = False
    if current_user.is_authenticated:
        is_participating = EventParticipant.query.filter_by(
            event_id=event_id,
            user_id=current_user.id
        ).first() is not None

    return render_template('events/detail.html',
                           event=event,
                           participants=participants,
                           is_participating=is_participating)


@events_bp.route('/<int:event_id>/join', methods=['POST'])
@login_required
def join(event_id):
    event = Event.query.get_or_404(event_id)

    existing = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()

    if existing:
        flash('Du ar redan anmald till detta event.', 'info')
    else:
        participant = EventParticipant(
            event_id=event_id,
            user_id=current_user.id
        )
        db.session.add(participant)

        # Create activity
        activity = Activity(
            activity_type='joined_event',
            message=f'{current_user.display_name} hanger med pa {event.title}',
            user_id=current_user.id,
            event_id=event_id
        )
        db.session.add(activity)
        db.session.commit()

        flash(f'Du ar nu anmald till {event.title}!', 'success')

    return redirect(url_for('events.detail', event_id=event_id))


@events_bp.route('/<int:event_id>/leave', methods=['POST'])
@login_required
def leave(event_id):
    event = Event.query.get_or_404(event_id)

    participant = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()

    if participant:
        db.session.delete(participant)
        db.session.commit()
        flash(f'Du har laemnat {event.title}.', 'info')
    else:
        flash('Du var inte anmald till detta event.', 'info')

    return redirect(url_for('events.detail', event_id=event_id))


@events_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        subtitle = request.form.get('subtitle', '').strip()
        description = request.form.get('description', '').strip()
        event_type = request.form.get('event_type', 'ride')
        date_str = request.form.get('date', '')
        location = request.form.get('location', '').strip()
        distance_km = request.form.get('distance_km', type=float)
        difficulty = request.form.get('difficulty', 'medium')

        if not title or not date_str:
            flash('Titel och datum kravs.', 'error')
        else:
            try:
                event_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Ogiltigt datumformat.', 'error')
                return render_template('events/create.html')

            event = Event(
                title=title,
                subtitle=subtitle,
                description=description,
                event_type=event_type,
                date=event_date,
                location=location,
                distance_km=distance_km,
                difficulty=difficulty,
                created_by_id=current_user.id
            )
            db.session.add(event)
            db.session.commit()

            # Create activity
            activity = Activity(
                activity_type='created_event',
                message=f'{current_user.display_name} skapade eventet {title}',
                user_id=current_user.id,
                event_id=event.id
            )
            db.session.add(activity)
            db.session.commit()

            flash('Event skapat!', 'success')
            return redirect(url_for('events.detail', event_id=event.id))

    return render_template('events/create.html')
