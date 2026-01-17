from datetime import datetime, timedelta
from enum import Enum
import secrets
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class UserState(str, Enum):
    PENDING_EMAIL_VERIFICATION = 'pending_email_verification'
    PENDING_APPROVAL = 'pending_approval'
    ACTIVE = 'active'
    REJECTED = 'rejected'
    SUSPENDED = 'suspended'


class UserRole(str, Enum):
    USER = 'user'
    MODERATOR = 'moderator'
    ADMIN = 'admin'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(100))
    bio = db.Column(db.Text)
    avatar_url = db.Column(db.String(256))

    # State and role (replacing is_admin)
    state = db.Column(db.String(50), default=UserState.PENDING_EMAIL_VERIFICATION.value, nullable=False)
    role = db.Column(db.String(20), default=UserRole.USER.value, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # Keep for backwards compatibility during migration

    # Email verification
    email_verified_at = db.Column(db.DateTime)

    # Approval workflow
    approved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejection_reason = db.Column(db.Text)
    suspended_reason = db.Column(db.Text)

    # Leaderboard privacy
    leaderboard_opt_in = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    stories = db.relationship('Story', backref='author', lazy='dynamic')
    photos = db.relationship('Photo', backref='uploader', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    activities = db.relationship('Activity', backref='user', lazy='dynamic')
    approved_by = db.relationship('User', remote_side=[id], foreign_keys=[approved_by_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_active_user(self):
        """Check if user is in ACTIVE state (can login)."""
        return self.state == UserState.ACTIVE.value

    def has_admin_access(self):
        """Check if user has admin or moderator access."""
        return self.role in [UserRole.ADMIN.value, UserRole.MODERATOR.value]

    def is_admin_role(self):
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN.value

    def __repr__(self):
        return f'<User {self.username}>'


class EmailVerificationToken(db.Model):
    __tablename__ = 'email_verification_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('verification_tokens', lazy='dynamic'))

    @classmethod
    def create_for_user(cls, user, expiry_hours=24):
        """Create a new verification token for a user."""
        token = secrets.token_urlsafe(48)  # 64 chars
        verification = cls(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=expiry_hours)
        )
        return verification

    def is_valid(self):
        """Check if token is still valid (not expired, not used)."""
        return self.used_at is None and self.expires_at > datetime.utcnow()

    def mark_used(self):
        """Mark the token as used."""
        self.used_at = datetime.utcnow()


class UserStatsCache(db.Model):
    """Cache for Strava statistics to avoid frequent API calls."""
    __tablename__ = 'user_stats_cache'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)

    # Latest ride data
    latest_ride_strava_id = db.Column(db.BigInteger)
    latest_ride_name = db.Column(db.String(256))
    latest_ride_date = db.Column(db.DateTime)
    latest_ride_distance_meters = db.Column(db.Float, default=0)
    latest_ride_moving_time_seconds = db.Column(db.Integer, default=0)
    latest_ride_elevation_gain = db.Column(db.Float, default=0)
    latest_ride_cached_at = db.Column(db.DateTime)

    # Year totals (Stockholm timezone for year boundary)
    year = db.Column(db.Integer)  # Which year these stats are for
    year_total_distance_meters = db.Column(db.Float, default=0)
    year_total_moving_time_seconds = db.Column(db.Integer, default=0)
    year_total_elevation_gain = db.Column(db.Float, default=0)
    year_total_ride_count = db.Column(db.Integer, default=0)
    year_totals_cached_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('stats_cache', uselist=False))

    @property
    def latest_ride_distance_km(self):
        return self.latest_ride_distance_meters / 1000 if self.latest_ride_distance_meters else 0

    @property
    def latest_ride_distance_mil(self):
        """Swedish mil (1 mil = 10 km)."""
        return self.latest_ride_distance_meters / 10000 if self.latest_ride_distance_meters else 0

    @property
    def year_total_distance_km(self):
        return self.year_total_distance_meters / 1000 if self.year_total_distance_meters else 0

    @property
    def year_total_distance_mil(self):
        """Swedish mil (1 mil = 10 km)."""
        return self.year_total_distance_meters / 10000 if self.year_total_distance_meters else 0


class StravaOAuthState(db.Model):
    """CSRF protection for Strava OAuth flow."""
    __tablename__ = 'strava_oauth_states'

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # Null for login/signup flows
    purpose = db.Column(db.String(20), nullable=False)  # 'connect', 'login', 'signup'
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('strava_oauth_states', lazy='dynamic'))

    @classmethod
    def create(cls, purpose, user_id=None, expiry_minutes=10):
        """Create a new OAuth state."""
        state_value = secrets.token_urlsafe(48)
        state = cls(
            state=state_value,
            user_id=user_id,
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=expiry_minutes)
        )
        return state

    def is_valid(self):
        """Check if state is still valid."""
        return self.used_at is None and self.expires_at > datetime.utcnow()

    def mark_used(self):
        """Mark the state as used."""
        self.used_at = datetime.utcnow()


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(300))
    description = db.Column(db.Text)
    event_type = db.Column(db.String(50))  # ride, social, race, external
    date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    location = db.Column(db.String(200))
    distance_km = db.Column(db.Float)
    difficulty = db.Column(db.String(20))  # easy, medium, hard
    max_participants = db.Column(db.Integer)
    external_url = db.Column(db.String(500))
    image_url = db.Column(db.String(256))
    is_featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    created_by = db.relationship('User', backref='created_events')
    participants = db.relationship('EventParticipant', backref='event', lazy='dynamic')

    def participant_count(self):
        return self.participants.count()


class EventParticipant(db.Model):
    __tablename__ = 'event_participants'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='going')  # going, maybe, interested

    user = db.relationship('User', backref='event_participations')


class Photo(db.Model):
    __tablename__ = 'photos'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(256), nullable=False)
    original_filename = db.Column(db.String(256))
    caption = db.Column(db.String(500))
    location = db.Column(db.String(200))
    taken_at = db.Column(db.DateTime)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))

    # Relationships
    event = db.relationship('Event', backref='photos')


class Story(db.Model):
    __tablename__ = 'stories'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, index=True)
    excerpt = db.Column(db.String(500))
    content = db.Column(db.Text, nullable=False)
    cover_image_url = db.Column(db.String(256))
    distance_km = db.Column(db.Float)
    duration_hours = db.Column(db.Float)
    location = db.Column(db.String(200))
    ride_date = db.Column(db.DateTime)
    is_published = db.Column(db.Boolean, default=False)
    published_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))

    # Relationships
    photos = db.relationship('Photo', backref='story', lazy='dynamic')
    comments = db.relationship('Comment', backref='story', lazy='dynamic')
    event = db.relationship('Event', backref='stories')


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id'))
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'))

    # Relationships
    photo = db.relationship('Photo', backref='comments')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]))


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    activity_type = db.Column(db.String(50), nullable=False)  # joined_event, posted_story, uploaded_photo, commented
    message = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id'))
    photo_id = db.Column(db.Integer, db.ForeignKey('photos.id'))

    # Relationships
    event = db.relationship('Event', backref='activities')
    story = db.relationship('Story', backref='activities')
    photo = db.relationship('Photo', backref='activities')


class News(db.Model):
    __tablename__ = 'news'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(500))
    image_url = db.Column(db.String(256))
    is_published = db.Column(db.Boolean, default=False)
    is_featured = db.Column(db.Boolean, default=False)
    published_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    author = db.relationship('User', backref='news_posts')


class StravaToken(db.Model):
    __tablename__ = 'strava_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    strava_athlete_id = db.Column(db.BigInteger, unique=True, nullable=False)
    access_token = db.Column(db.String(256), nullable=False)
    refresh_token = db.Column(db.String(256), nullable=False)
    expires_at = db.Column(db.Integer, nullable=False)  # Unix timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('strava_token', uselist=False))

    def is_expired(self):
        """Check if access token is expired (with 5 min buffer)."""
        import time
        return time.time() > (self.expires_at - 300)

    def __repr__(self):
        return f'<StravaToken user_id={self.user_id}>'


class StravaActivity(db.Model):
    __tablename__ = 'strava_activities'

    id = db.Column(db.Integer, primary_key=True)
    strava_id = db.Column(db.BigInteger, unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(256))
    activity_type = db.Column(db.String(50))  # Ride, VirtualRide, etc.
    distance_meters = db.Column(db.Float, default=0)
    moving_time_seconds = db.Column(db.Integer, default=0)
    elapsed_time_seconds = db.Column(db.Integer, default=0)
    total_elevation_gain = db.Column(db.Float, default=0)
    start_date = db.Column(db.DateTime)
    start_date_local = db.Column(db.DateTime)
    average_speed = db.Column(db.Float)  # m/s
    max_speed = db.Column(db.Float)  # m/s
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref='strava_activities')

    @property
    def distance_km(self):
        """Return distance in kilometers."""
        return self.distance_meters / 1000 if self.distance_meters else 0

    @property
    def moving_time_hours(self):
        """Return moving time in hours."""
        return self.moving_time_seconds / 3600 if self.moving_time_seconds else 0

    def __repr__(self):
        return f'<StravaActivity {self.strava_id} {self.name}>'
