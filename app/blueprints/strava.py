import time
import secrets
import requests
from datetime import datetime, timedelta
from flask import Blueprint, redirect, url_for, flash, request, current_app, session
from flask_login import login_required, current_user, login_user
from sqlalchemy import func
from models import (
    db, User, StravaToken, StravaActivity, Activity,
    StravaOAuthState, UserStatsCache, UserState, UserRole
)

strava_bp = Blueprint('strava', __name__)


def get_strava_authorize_url(callback_route='strava.callback', state_value=None):
    """Generate Strava OAuth authorization URL with state parameter."""
    client_id = current_app.config['STRAVA_CLIENT_ID']
    redirect_uri = url_for(callback_route, _external=True)
    scope = 'activity:read_all,profile:read_all'

    url = (
        f"{current_app.config['STRAVA_AUTHORIZE_URL']}"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
    )

    if state_value:
        url += f"&state={state_value}"

    return url


def create_oauth_state(purpose, user_id=None):
    """Create and store OAuth state for CSRF protection."""
    state = StravaOAuthState.create(purpose=purpose, user_id=user_id)
    db.session.add(state)
    db.session.commit()
    return state.state


def validate_oauth_state(state_value, purpose):
    """Validate OAuth state and mark as used."""
    state = StravaOAuthState.query.filter_by(state=state_value).first()

    if not state:
        return None, "Ogiltig state-parameter."

    if not state.is_valid():
        return None, "State har gatt ut. Forsok igen."

    if state.purpose != purpose:
        return None, "Felaktig state-purpose."

    state.mark_used()
    db.session.commit()

    return state, None


def exchange_code_for_token(code):
    """Exchange authorization code for access token."""
    response = requests.post(
        current_app.config['STRAVA_TOKEN_URL'],
        data={
            'client_id': current_app.config['STRAVA_CLIENT_ID'],
            'client_secret': current_app.config['STRAVA_CLIENT_SECRET'],
            'code': code,
            'grant_type': 'authorization_code'
        }
    )

    if response.status_code != 200:
        return None

    return response.json()


def refresh_access_token(strava_token):
    """Refresh an expired access token."""
    response = requests.post(
        current_app.config['STRAVA_TOKEN_URL'],
        data={
            'client_id': current_app.config['STRAVA_CLIENT_ID'],
            'client_secret': current_app.config['STRAVA_CLIENT_SECRET'],
            'refresh_token': strava_token.refresh_token,
            'grant_type': 'refresh_token'
        }
    )

    if response.status_code != 200:
        return False

    data = response.json()
    strava_token.access_token = data['access_token']
    strava_token.refresh_token = data['refresh_token']
    strava_token.expires_at = data['expires_at']
    strava_token.updated_at = datetime.utcnow()
    db.session.commit()

    return True


def get_valid_token(strava_token):
    """Get a valid access token, refreshing if necessary."""
    if strava_token.is_expired():
        if not refresh_access_token(strava_token):
            return None
    return strava_token.access_token


def fetch_strava_activities(access_token, after_timestamp=None, page=1, per_page=50):
    """Fetch activities from Strava API."""
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'page': page, 'per_page': per_page}

    if after_timestamp:
        params['after'] = after_timestamp

    response = requests.get(
        f"{current_app.config['STRAVA_API_BASE_URL']}/athlete/activities",
        headers=headers,
        params=params
    )

    if response.status_code != 200:
        return None

    return response.json()


def get_stockholm_timezone():
    """Get the Stockholm timezone."""
    try:
        import pytz
        return pytz.timezone(current_app.config.get('TIMEZONE', 'Europe/Stockholm'))
    except ImportError:
        return None


def get_year_start_timestamp():
    """Get the start of the current year in Stockholm timezone."""
    tz = get_stockholm_timezone()
    if tz:
        import pytz
        now = datetime.now(tz)
        year_start = tz.localize(datetime(now.year, 1, 1))
        return year_start
    else:
        # Fallback to UTC
        now = datetime.utcnow()
        return datetime(now.year, 1, 1)


def get_latest_ride_leaderboard(limit=10):
    """
    Get top users by their latest ride distance.
    Only includes ACTIVE users who have opted in to leaderboards.
    """
    # Get users with their latest ride
    subquery = db.session.query(
        StravaActivity.user_id,
        func.max(StravaActivity.start_date).label('latest_date')
    ).filter(
        StravaActivity.activity_type == 'Ride'  # Only real rides
    ).group_by(StravaActivity.user_id).subquery()

    results = db.session.query(
        User.id,
        User.display_name,
        User.username,
        StravaActivity.name,
        StravaActivity.distance_meters,
        StravaActivity.moving_time_seconds,
        StravaActivity.start_date
    ).join(
        StravaToken, User.id == StravaToken.user_id
    ).join(
        subquery, User.id == subquery.c.user_id
    ).join(
        StravaActivity,
        (StravaActivity.user_id == User.id) &
        (StravaActivity.start_date == subquery.c.latest_date) &
        (StravaActivity.activity_type == 'Ride')
    ).filter(
        User.state == UserState.ACTIVE.value,
        User.leaderboard_opt_in == True
    ).order_by(
        StravaActivity.distance_meters.desc()
    ).limit(limit).all()

    leaderboard = []
    for i, row in enumerate(results):
        distance_mil = row.distance_meters / 10000 if row.distance_meters else 0
        distance_km = row.distance_meters / 1000 if row.distance_meters else 0

        leaderboard.append({
            'rank': i + 1,
            'user_id': row.id,
            'display_name': row.display_name or row.username,
            'username': row.username,
            'ride_name': row.name,
            'distance_mil': round(distance_mil, 1),
            'distance_km': round(distance_km, 0),
            'moving_time_formatted': format_time(row.moving_time_seconds),
            'ride_date': row.start_date
        })

    return leaderboard


def get_year_totals_leaderboard(limit=10):
    """
    Get top users by total distance this year (Stockholm timezone).
    Only includes ACTIVE users who have opted in to leaderboards.
    """
    year_start = get_year_start_timestamp()

    stats = db.session.query(
        User.id,
        User.display_name,
        User.username,
        func.sum(StravaActivity.distance_meters).label('total_distance'),
        func.sum(StravaActivity.moving_time_seconds).label('total_time'),
        func.sum(StravaActivity.total_elevation_gain).label('total_elevation'),
        func.count(StravaActivity.id).label('ride_count')
    ).join(
        StravaToken, User.id == StravaToken.user_id
    ).join(
        StravaActivity, User.id == StravaActivity.user_id
    ).filter(
        User.state == UserState.ACTIVE.value,
        User.leaderboard_opt_in == True,
        StravaActivity.activity_type == 'Ride',  # Only real rides
        StravaActivity.start_date >= year_start
    ).group_by(
        User.id, User.display_name, User.username
    ).order_by(
        func.sum(StravaActivity.distance_meters).desc()
    ).limit(limit).all()

    leaderboard = []
    for i, row in enumerate(stats):
        distance_mil = row.total_distance / 10000 if row.total_distance else 0
        distance_km = row.total_distance / 1000 if row.total_distance else 0

        leaderboard.append({
            'rank': i + 1,
            'user_id': row.id,
            'display_name': row.display_name or row.username,
            'username': row.username,
            'total_mil': round(distance_mil, 1),
            'total_km': round(distance_km, 0),
            'total_time_formatted': format_time(row.total_time),
            'total_elevation': round(row.total_elevation) if row.total_elevation else 0,
            'ride_count': row.ride_count
        })

    return leaderboard


def format_time(seconds):
    """Format seconds as HH:MM:SS or MM:SS."""
    if not seconds:
        return "0:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def get_leaderboard_data(period_days=30, limit=5):
    """
    Get leaderboard data for users with Strava connected.
    Only includes ACTIVE users who have opted in.
    Returns list of dicts with user info and stats.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=period_days)

    # Query to aggregate stats per user - only Ride type
    stats = db.session.query(
        User.id,
        User.display_name,
        User.username,
        func.sum(StravaActivity.distance_meters).label('total_distance'),
        func.sum(StravaActivity.total_elevation_gain).label('total_elevation'),
        func.count(StravaActivity.id).label('ride_count')
    ).join(
        StravaActivity, User.id == StravaActivity.user_id
    ).join(
        StravaToken, User.id == StravaToken.user_id
    ).filter(
        User.state == UserState.ACTIVE.value,
        User.leaderboard_opt_in == True,
        StravaActivity.start_date >= cutoff_date,
        StravaActivity.activity_type == 'Ride'  # Only real rides
    ).group_by(
        User.id, User.display_name, User.username
    ).order_by(
        func.sum(StravaActivity.distance_meters).desc()
    ).limit(limit).all()

    leaderboard = []
    for i, row in enumerate(stats):
        distance_mil = row.total_distance / 10000 if row.total_distance else 0
        distance_km = row.total_distance / 1000 if row.total_distance else 0

        leaderboard.append({
            'rank': i + 1,
            'user_id': row.id,
            'display_name': row.display_name or row.username,
            'username': row.username,
            'total_km': round(distance_km, 1),
            'total_mil': round(distance_mil, 1),
            'total_elevation': round(row.total_elevation) if row.total_elevation else 0,
            'ride_count': row.ride_count
        })

    return leaderboard


def generate_username_from_strava(athlete):
    """Generate a unique username from Strava athlete data."""
    # Try firstname + lastname
    first = athlete.get('firstname', '').lower().replace(' ', '')
    last = athlete.get('lastname', '').lower().replace(' ', '')

    if first and last:
        base_username = f"{first}{last[0]}"
    elif first:
        base_username = first
    else:
        base_username = f"strava{athlete.get('id', '')}"

    # Ensure it's at least 3 characters
    if len(base_username) < 3:
        base_username = f"user{base_username}"

    # Check if username exists, if so add numbers
    username = base_username
    counter = 1
    while User.query.filter_by(username=username).first():
        username = f"{base_username}{counter}"
        counter += 1

    return username


@strava_bp.route('/login')
def strava_login():
    """Initiate Strava OAuth for login/signup."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    # Create OAuth state
    state = create_oauth_state(purpose='login')
    return redirect(get_strava_authorize_url('strava.login_callback', state))


@strava_bp.route('/login/callback')
def login_callback():
    """Handle Strava OAuth callback for login/signup."""
    error = request.args.get('error')
    if error:
        flash('Strava-inloggning avbruten.', 'error')
        return redirect(url_for('auth.login'))

    # Validate state
    state_value = request.args.get('state')
    if not state_value:
        flash('Saknar state-parameter.', 'error')
        return redirect(url_for('auth.login'))

    state, error_msg = validate_oauth_state(state_value, 'login')
    if error_msg:
        flash(error_msg, 'error')
        return redirect(url_for('auth.login'))

    code = request.args.get('code')
    if not code:
        flash('Ingen auktoriseringskod fran Strava.', 'error')
        return redirect(url_for('auth.login'))

    # Exchange code for tokens
    token_data = exchange_code_for_token(code)
    if not token_data:
        flash('Kunde inte ansluta till Strava. Forsok igen.', 'error')
        return redirect(url_for('auth.login'))

    athlete = token_data.get('athlete', {})
    strava_athlete_id = athlete.get('id')

    if not strava_athlete_id:
        flash('Kunde inte hamta Strava-profil.', 'error')
        return redirect(url_for('auth.login'))

    # Check if user with this Strava ID already exists
    existing_token = StravaToken.query.filter_by(strava_athlete_id=strava_athlete_id).first()

    if existing_token:
        # User exists - check their state
        user = existing_token.user

        if user.state != UserState.ACTIVE.value:
            if user.state == UserState.PENDING_APPROVAL.value:
                flash('Ditt konto vantar pa godkannande.', 'info')
                return redirect(url_for('auth.pending_approval'))
            elif user.state == UserState.SUSPENDED.value:
                flash('Ditt konto har stangts av.', 'error')
                return redirect(url_for('auth.login'))
            else:
                flash('Ditt konto ar inte aktivt.', 'error')
                return redirect(url_for('auth.login'))

        # Update tokens
        existing_token.access_token = token_data['access_token']
        existing_token.refresh_token = token_data['refresh_token']
        existing_token.expires_at = token_data['expires_at']
        existing_token.updated_at = datetime.utcnow()

        # Update last seen
        user.last_seen = datetime.utcnow()
        db.session.commit()

        login_user(user, remember=True)
        flash(f'Valkommen tillbaka, {user.display_name or user.username}!', 'success')
        return redirect(url_for('main.index'))

    else:
        # New user via Strava - they need approval too
        username = generate_username_from_strava(athlete)
        display_name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()

        # Create user with PENDING_APPROVAL state (email already "verified" via Strava)
        user = User(
            username=username,
            email=f"strava_{strava_athlete_id}@strava.local",  # Placeholder email
            display_name=display_name or username,
            avatar_url=athlete.get('profile'),
            bio=f"Cyklist fran {athlete.get('city', 'Sverige')}" if athlete.get('city') else None,
            state=UserState.PENDING_APPROVAL.value,  # Still needs admin approval
            role=UserRole.USER.value,
            email_verified_at=datetime.utcnow(),  # Strava = verified
            leaderboard_opt_in=False
        )
        # Set a random password (user won't use it, they login via Strava)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        db.session.flush()  # Get user.id

        # Create Strava token
        strava_token = StravaToken(
            user_id=user.id,
            strava_athlete_id=strava_athlete_id,
            access_token=token_data['access_token'],
            refresh_token=token_data['refresh_token'],
            expires_at=token_data['expires_at']
        )
        db.session.add(strava_token)
        db.session.commit()

        # Notify admins about pending approval
        from services.email import send_pending_approval_to_admins
        send_pending_approval_to_admins(user)

        flash('Konto skapat! Ditt konto vantar nu pa godkannande.', 'success')
        return redirect(url_for('auth.pending_approval'))


@strava_bp.route('/connect')
@login_required
def connect():
    """Initiate Strava OAuth flow."""
    # Only ACTIVE users can connect Strava
    if current_user.state != UserState.ACTIVE.value:
        flash('Du maste ha ett aktivt konto for att koppla Strava.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    # Check if already connected
    if current_user.strava_token:
        flash('Du ar redan kopplad till Strava!', 'info')
        return redirect(url_for('profile.view', username=current_user.username))

    # Create OAuth state with user_id
    state = create_oauth_state(purpose='connect', user_id=current_user.id)
    return redirect(get_strava_authorize_url('strava.callback', state))


@strava_bp.route('/callback')
@login_required
def callback():
    """Handle Strava OAuth callback."""
    error = request.args.get('error')
    if error:
        flash('Strava-koppling avbruten.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    # Validate state
    state_value = request.args.get('state')
    if not state_value:
        flash('Saknar state-parameter.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    state, error_msg = validate_oauth_state(state_value, 'connect')
    if error_msg:
        flash(error_msg, 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    # Verify state belongs to current user
    if state.user_id != current_user.id:
        flash('Ogiltig state for denna anvandare.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    code = request.args.get('code')
    if not code:
        flash('Ingen auktoriseringskod fran Strava.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    # Exchange code for tokens
    token_data = exchange_code_for_token(code)
    if not token_data:
        flash('Kunde inte koppla till Strava. Forsok igen.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    athlete = token_data.get('athlete', {})

    # Check if this Strava account is already linked to another user
    existing_token = StravaToken.query.filter_by(
        strava_athlete_id=athlete.get('id')
    ).first()

    if existing_token and existing_token.user_id != current_user.id:
        flash('Detta Strava-konto ar redan kopplat till en annan anvandare.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    # Create or update token
    if current_user.strava_token:
        strava_token = current_user.strava_token
        strava_token.access_token = token_data['access_token']
        strava_token.refresh_token = token_data['refresh_token']
        strava_token.expires_at = token_data['expires_at']
    else:
        strava_token = StravaToken(
            user_id=current_user.id,
            strava_athlete_id=athlete.get('id'),
            access_token=token_data['access_token'],
            refresh_token=token_data['refresh_token'],
            expires_at=token_data['expires_at']
        )
        db.session.add(strava_token)

    db.session.commit()

    flash('Strava-konto kopplat! Synkar aktiviteter...', 'success')
    return redirect(url_for('strava.sync'))


@strava_bp.route('/disconnect')
@login_required
def disconnect():
    """Disconnect Strava account."""
    if current_user.strava_token:
        # Delete activities
        StravaActivity.query.filter_by(user_id=current_user.id).delete()
        # Delete stats cache
        UserStatsCache.query.filter_by(user_id=current_user.id).delete()
        # Delete token
        db.session.delete(current_user.strava_token)
        db.session.commit()
        flash('Strava-konto bortkopplat.', 'success')

    return redirect(url_for('profile.view', username=current_user.username))


@strava_bp.route('/sync')
@login_required
def sync():
    """Sync activities from Strava."""
    if not current_user.strava_token:
        flash('Du maste forst koppla ditt Strava-konto.', 'error')
        return redirect(url_for('strava.connect'))

    # Only ACTIVE users can sync
    if current_user.state != UserState.ACTIVE.value:
        flash('Du maste ha ett aktivt konto for att synka aktiviteter.', 'error')
        return redirect(url_for('profile.view', username=current_user.username))

    access_token = get_valid_token(current_user.strava_token)
    if not access_token:
        flash('Kunde inte autentisera med Strava. Koppla om ditt konto.', 'error')
        return redirect(url_for('strava.connect'))

    # Get the most recent activity to determine sync start point
    latest_activity = StravaActivity.query.filter_by(
        user_id=current_user.id
    ).order_by(StravaActivity.start_date.desc()).first()

    after_timestamp = None
    if latest_activity and latest_activity.start_date:
        # Sync from 1 hour before latest to catch any updates
        after_timestamp = int((latest_activity.start_date - timedelta(hours=1)).timestamp())
    else:
        # First sync: get activities from last 90 days
        after_timestamp = int((datetime.utcnow() - timedelta(days=90)).timestamp())

    # Fetch activities
    synced_count = 0
    page = 1

    while True:
        activities = fetch_strava_activities(access_token, after_timestamp, page)

        if not activities:
            break

        for activity_data in activities:
            # ONLY sync "Ride" type - not VirtualRide or EBikeRide
            if activity_data.get('type') != 'Ride':
                continue

            # Check if activity already exists
            existing = StravaActivity.query.filter_by(
                strava_id=activity_data['id']
            ).first()

            if existing:
                # Update existing activity
                existing.name = activity_data.get('name')
                existing.distance_meters = activity_data.get('distance', 0)
                existing.moving_time_seconds = activity_data.get('moving_time', 0)
                existing.total_elevation_gain = activity_data.get('total_elevation_gain', 0)
                existing.average_speed = activity_data.get('average_speed')
                existing.max_speed = activity_data.get('max_speed')
                existing.synced_at = datetime.utcnow()
            else:
                # Parse dates
                start_date = None
                start_date_local = None
                if activity_data.get('start_date'):
                    try:
                        start_date = datetime.fromisoformat(
                            activity_data['start_date'].replace('Z', '+00:00')
                        )
                    except ValueError:
                        pass
                if activity_data.get('start_date_local'):
                    try:
                        start_date_local = datetime.fromisoformat(
                            activity_data['start_date_local'].replace('Z', '+00:00')
                        )
                    except ValueError:
                        pass

                # Create new activity
                strava_activity = StravaActivity(
                    strava_id=activity_data['id'],
                    user_id=current_user.id,
                    name=activity_data.get('name'),
                    activity_type=activity_data.get('type'),
                    distance_meters=activity_data.get('distance', 0),
                    moving_time_seconds=activity_data.get('moving_time', 0),
                    elapsed_time_seconds=activity_data.get('elapsed_time', 0),
                    total_elevation_gain=activity_data.get('total_elevation_gain', 0),
                    start_date=start_date,
                    start_date_local=start_date_local,
                    average_speed=activity_data.get('average_speed'),
                    max_speed=activity_data.get('max_speed')
                )
                db.session.add(strava_activity)
                synced_count += 1

        if len(activities) < 50:
            break

        page += 1

    db.session.commit()

    flash(f'{synced_count} nya aktiviteter synkade fran Strava!', 'success')
    return redirect(url_for('profile.view', username=current_user.username))
