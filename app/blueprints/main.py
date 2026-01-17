from flask import Blueprint, render_template
from models import db, Event, Story, Activity, User, News, UserState
from datetime import datetime
from sqlalchemy import desc
from blueprints.strava import get_leaderboard_data, get_latest_ride_leaderboard, get_year_totals_leaderboard

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    # Get upcoming events
    upcoming_events = Event.query.filter(
        Event.date >= datetime.utcnow()
    ).order_by(Event.date).limit(4).all()

    # Get featured event (if any)
    featured_event = Event.query.filter(
        Event.is_featured == True,
        Event.date >= datetime.utcnow()
    ).first()

    # Get recent stories
    recent_stories = Story.query.filter_by(
        is_published=True
    ).order_by(desc(Story.published_at)).limit(3).all()

    # Get recent activities
    activities = Activity.query.order_by(
        desc(Activity.created_at)
    ).limit(10).all()

    # Get member count (only active users)
    member_count = User.query.filter_by(state=UserState.ACTIVE.value).count()

    # Get published news
    news = News.query.filter_by(
        is_published=True
    ).order_by(desc(News.published_at)).limit(5).all()

    # Get Strava leaderboards
    leaderboard = get_leaderboard_data(period_days=30, limit=5)
    latest_ride_leaderboard = get_latest_ride_leaderboard(limit=10)
    year_totals_leaderboard = get_year_totals_leaderboard(limit=10)

    return render_template('main/index.html',
                           upcoming_events=upcoming_events,
                           featured_event=featured_event,
                           recent_stories=recent_stories,
                           activities=activities,
                           member_count=member_count,
                           news=news,
                           leaderboard=leaderboard,
                           latest_ride_leaderboard=latest_ride_leaderboard,
                           year_totals_leaderboard=year_totals_leaderboard)


@main_bp.route('/about')
def about():
    return render_template('main/about.html')
