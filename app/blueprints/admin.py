import os
import uuid
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User, Event, Story, Photo, News, Activity, Comment, UserState, UserRole
from services.email import send_approval_notification, send_rejection_notification

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    """Decorator to require admin/moderator access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Du har inte behorighet att se denna sida.', 'error')
            return redirect(url_for('main.index'))
        # Check role-based access (ADMIN or MODERATOR)
        if not current_user.has_admin_access():
            flash('Du har inte behorighet att se denna sida.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def admin_only(f):
    """Decorator to require ADMIN role only (not moderator)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Du har inte behorighet att se denna sida.', 'error')
            return redirect(url_for('main.index'))
        if not current_user.is_admin_role():
            flash('Endast administratorer kan utfora denna atgard.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def allowed_file(filename):
    """Check if file extension is allowed"""
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def save_uploaded_file(file):
    """Save uploaded file and return the filename"""
    if file and allowed_file(file.filename):
        # Generate unique filename
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"

        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(upload_folder, exist_ok=True)

        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        return filename
    return None


# ============ DASHBOARD ============

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    """Admin dashboard with overview"""
    # Count pending approvals
    pending_approvals = User.query.filter_by(state=UserState.PENDING_APPROVAL.value).count()

    stats = {
        'events': Event.query.count(),
        'stories': Story.query.count(),
        'photos': Photo.query.count(),
        'members': User.query.filter_by(state=UserState.ACTIVE.value).count(),
        'news': News.query.count(),
        'pending_approvals': pending_approvals,
    }

    recent_events = Event.query.order_by(Event.created_at.desc()).limit(5).all()
    recent_stories = Story.query.order_by(Story.created_at.desc()).limit(5).all()
    recent_news = News.query.order_by(News.created_at.desc()).limit(5).all()

    return render_template('admin/dashboard.html',
                         stats=stats,
                         recent_events=recent_events,
                         recent_stories=recent_stories,
                         recent_news=recent_news)


# ============ APPROVALS ============

@admin_bp.route('/approvals')
@login_required
@admin_required
def approvals_list():
    """List pending approvals"""
    pending = User.query.filter_by(state=UserState.PENDING_APPROVAL.value).order_by(User.created_at.desc()).all()
    return render_template('admin/approvals/list.html', pending=pending)


@admin_bp.route('/approvals/<int:id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(id):
    """Approve a pending user"""
    user = User.query.get_or_404(id)

    if user.state != UserState.PENDING_APPROVAL.value:
        flash('Denna anvandare vantar inte pa godkannande.', 'warning')
        return redirect(url_for('admin.approvals_list'))

    user.state = UserState.ACTIVE.value
    user.approved_at = datetime.utcnow()
    user.approved_by_id = current_user.id

    # Create activity for joining
    activity = Activity(
        activity_type='joined',
        message=f'{user.display_name or user.username} gick med i Klubbans Vanner!',
        user_id=user.id
    )
    db.session.add(activity)
    db.session.commit()

    # Send approval notification email
    send_approval_notification(user)

    flash(f'{user.display_name or user.username} har godkants!', 'success')
    return redirect(url_for('admin.approvals_list'))


@admin_bp.route('/approvals/<int:id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_user(id):
    """Reject a pending user"""
    user = User.query.get_or_404(id)

    if user.state != UserState.PENDING_APPROVAL.value:
        flash('Denna anvandare vantar inte pa godkannande.', 'warning')
        return redirect(url_for('admin.approvals_list'))

    reason = request.form.get('reason', '').strip()

    user.state = UserState.REJECTED.value
    user.rejection_reason = reason if reason else None
    db.session.commit()

    # Send rejection notification email
    send_rejection_notification(user, reason)

    flash(f'{user.display_name or user.username} har avvisats.', 'info')
    return redirect(url_for('admin.approvals_list'))


# ============ EVENTS ============

@admin_bp.route('/events')
@login_required
@admin_required
def events_list():
    """List all events"""
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template('admin/events/list.html', events=events)


@admin_bp.route('/events/new', methods=['GET', 'POST'])
@login_required
@admin_required
def events_create():
    """Create new event"""
    if request.method == 'POST':
        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            image_filename = save_uploaded_file(request.files['image'])

        # Parse date and time
        date_str = request.form.get('date')
        time_str = request.form.get('time', '00:00')
        event_datetime = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')

        event = Event(
            title=request.form.get('title'),
            subtitle=request.form.get('subtitle'),
            description=request.form.get('description'),
            event_type=request.form.get('event_type', 'ride'),
            date=event_datetime,
            location=request.form.get('location'),
            distance_km=float(request.form.get('distance_km')) if request.form.get('distance_km') else None,
            difficulty=request.form.get('difficulty'),
            max_participants=int(request.form.get('max_participants')) if request.form.get('max_participants') else None,
            external_url=request.form.get('external_url'),
            image_url=f"/static/uploads/{image_filename}" if image_filename else None,
            is_featured=request.form.get('is_featured') == 'on',
            created_by_id=current_user.id
        )

        db.session.add(event)
        db.session.commit()

        flash('Evenemanget har skapats!', 'success')
        return redirect(url_for('admin.events_list'))

    return render_template('admin/events/form.html', event=None)


@admin_bp.route('/events/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def events_edit(id):
    """Edit event"""
    event = Event.query.get_or_404(id)

    if request.method == 'POST':
        # Handle image upload
        if 'image' in request.files and request.files['image'].filename:
            image_filename = save_uploaded_file(request.files['image'])
            if image_filename:
                event.image_url = f"/static/uploads/{image_filename}"

        # Parse date and time
        date_str = request.form.get('date')
        time_str = request.form.get('time', '00:00')
        event.date = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')

        event.title = request.form.get('title')
        event.subtitle = request.form.get('subtitle')
        event.description = request.form.get('description')
        event.event_type = request.form.get('event_type', 'ride')
        event.location = request.form.get('location')
        event.distance_km = float(request.form.get('distance_km')) if request.form.get('distance_km') else None
        event.difficulty = request.form.get('difficulty')
        event.max_participants = int(request.form.get('max_participants')) if request.form.get('max_participants') else None
        event.external_url = request.form.get('external_url')
        event.is_featured = request.form.get('is_featured') == 'on'

        db.session.commit()

        flash('Evenemanget har uppdaterats!', 'success')
        return redirect(url_for('admin.events_list'))

    return render_template('admin/events/form.html', event=event)


@admin_bp.route('/events/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def events_delete(id):
    """Delete event"""
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()

    flash('Evenemanget har tagits bort!', 'success')
    return redirect(url_for('admin.events_list'))


# ============ STORIES ============

@admin_bp.route('/stories')
@login_required
@admin_required
def stories_list():
    """List all stories"""
    stories = Story.query.order_by(Story.created_at.desc()).all()
    return render_template('admin/stories/list.html', stories=stories)


@admin_bp.route('/stories/new', methods=['GET', 'POST'])
@login_required
@admin_required
def stories_create():
    """Create new story"""
    if request.method == 'POST':
        # Handle cover image upload
        cover_filename = None
        if 'cover_image' in request.files:
            cover_filename = save_uploaded_file(request.files['cover_image'])

        # Generate slug from title
        import re
        title = request.form.get('title')
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

        # Make slug unique
        base_slug = slug
        counter = 1
        while Story.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Parse ride date if provided
        ride_date = None
        if request.form.get('ride_date'):
            ride_date = datetime.strptime(request.form.get('ride_date'), '%Y-%m-%d')

        is_published = request.form.get('is_published') == 'on'

        story = Story(
            title=title,
            slug=slug,
            excerpt=request.form.get('excerpt'),
            content=request.form.get('content'),
            cover_image_url=f"/static/uploads/{cover_filename}" if cover_filename else None,
            distance_km=float(request.form.get('distance_km')) if request.form.get('distance_km') else None,
            duration_hours=float(request.form.get('duration_hours')) if request.form.get('duration_hours') else None,
            location=request.form.get('location'),
            ride_date=ride_date,
            is_published=is_published,
            published_at=datetime.utcnow() if is_published else None,
            author_id=current_user.id
        )

        db.session.add(story)
        db.session.commit()

        flash('Berattelsen har skapats!', 'success')
        return redirect(url_for('admin.stories_list'))

    return render_template('admin/stories/form.html', story=None)


@admin_bp.route('/stories/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def stories_edit(id):
    """Edit story"""
    story = Story.query.get_or_404(id)

    if request.method == 'POST':
        # Handle cover image upload
        if 'cover_image' in request.files and request.files['cover_image'].filename:
            cover_filename = save_uploaded_file(request.files['cover_image'])
            if cover_filename:
                story.cover_image_url = f"/static/uploads/{cover_filename}"

        # Parse ride date if provided
        ride_date = None
        if request.form.get('ride_date'):
            ride_date = datetime.strptime(request.form.get('ride_date'), '%Y-%m-%d')

        was_published = story.is_published
        is_published = request.form.get('is_published') == 'on'

        story.title = request.form.get('title')
        story.excerpt = request.form.get('excerpt')
        story.content = request.form.get('content')
        story.distance_km = float(request.form.get('distance_km')) if request.form.get('distance_km') else None
        story.duration_hours = float(request.form.get('duration_hours')) if request.form.get('duration_hours') else None
        story.location = request.form.get('location')
        story.ride_date = ride_date
        story.is_published = is_published

        # Set published_at if newly published
        if is_published and not was_published:
            story.published_at = datetime.utcnow()

        db.session.commit()

        flash('Berattelsen har uppdaterats!', 'success')
        return redirect(url_for('admin.stories_list'))

    return render_template('admin/stories/form.html', story=story)


@admin_bp.route('/stories/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def stories_delete(id):
    """Delete story"""
    story = Story.query.get_or_404(id)
    db.session.delete(story)
    db.session.commit()

    flash('Berattelsen har tagits bort!', 'success')
    return redirect(url_for('admin.stories_list'))


# ============ PHOTOS ============

@admin_bp.route('/photos')
@login_required
@admin_required
def photos_list():
    """List all photos"""
    photos = Photo.query.order_by(Photo.uploaded_at.desc()).all()
    return render_template('admin/photos/list.html', photos=photos)


@admin_bp.route('/photos/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def photos_upload():
    """Upload new photos"""
    stories = Story.query.order_by(Story.title).all()
    events = Event.query.order_by(Event.date.desc()).all()

    if request.method == 'POST':
        files = request.files.getlist('photos')
        uploaded_count = 0

        for file in files:
            if file and allowed_file(file.filename):
                filename = save_uploaded_file(file)
                if filename:
                    photo = Photo(
                        filename=f"/static/uploads/{filename}",
                        original_filename=file.filename,
                        caption=request.form.get('caption'),
                        location=request.form.get('location'),
                        uploader_id=current_user.id,
                        story_id=int(request.form.get('story_id')) if request.form.get('story_id') else None,
                        event_id=int(request.form.get('event_id')) if request.form.get('event_id') else None
                    )
                    db.session.add(photo)
                    uploaded_count += 1

        db.session.commit()

        if uploaded_count > 0:
            flash(f'{uploaded_count} bild(er) har laddats upp!', 'success')
        else:
            flash('Ingen bild kunde laddas upp.', 'error')

        return redirect(url_for('admin.photos_list'))

    return render_template('admin/photos/upload.html', stories=stories, events=events)


@admin_bp.route('/photos/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def photos_edit(id):
    """Edit photo details"""
    photo = Photo.query.get_or_404(id)
    stories = Story.query.order_by(Story.title).all()
    events = Event.query.order_by(Event.date.desc()).all()

    if request.method == 'POST':
        photo.caption = request.form.get('caption')
        photo.location = request.form.get('location')
        photo.story_id = int(request.form.get('story_id')) if request.form.get('story_id') else None
        photo.event_id = int(request.form.get('event_id')) if request.form.get('event_id') else None

        db.session.commit()

        flash('Bilden har uppdaterats!', 'success')
        return redirect(url_for('admin.photos_list'))

    return render_template('admin/photos/edit.html', photo=photo, stories=stories, events=events)


@admin_bp.route('/photos/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def photos_delete(id):
    """Delete photo"""
    photo = Photo.query.get_or_404(id)

    # Try to delete the file
    if photo.filename:
        try:
            filepath = os.path.join(current_app.root_path, photo.filename.lstrip('/'))
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

    db.session.delete(photo)
    db.session.commit()

    flash('Bilden har tagits bort!', 'success')
    return redirect(url_for('admin.photos_list'))


# ============ NEWS ============

@admin_bp.route('/news')
@login_required
@admin_required
def news_list():
    """List all news"""
    news = News.query.order_by(News.created_at.desc()).all()
    return render_template('admin/news/list.html', news=news)


@admin_bp.route('/news/new', methods=['GET', 'POST'])
@login_required
@admin_required
def news_create():
    """Create news article"""
    if request.method == 'POST':
        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            image_filename = save_uploaded_file(request.files['image'])

        is_published = request.form.get('is_published') == 'on'

        news = News(
            title=request.form.get('title'),
            content=request.form.get('content'),
            excerpt=request.form.get('excerpt'),
            image_url=f"/static/uploads/{image_filename}" if image_filename else None,
            is_published=is_published,
            is_featured=request.form.get('is_featured') == 'on',
            published_at=datetime.utcnow() if is_published else None,
            author_id=current_user.id
        )

        db.session.add(news)
        db.session.commit()

        flash('Nyheten har skapats!', 'success')
        return redirect(url_for('admin.news_list'))

    return render_template('admin/news/form.html', news=None)


@admin_bp.route('/news/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def news_edit(id):
    """Edit news article"""
    news = News.query.get_or_404(id)

    if request.method == 'POST':
        # Handle image upload
        if 'image' in request.files and request.files['image'].filename:
            image_filename = save_uploaded_file(request.files['image'])
            if image_filename:
                news.image_url = f"/static/uploads/{image_filename}"

        was_published = news.is_published
        is_published = request.form.get('is_published') == 'on'

        news.title = request.form.get('title')
        news.content = request.form.get('content')
        news.excerpt = request.form.get('excerpt')
        news.is_published = is_published
        news.is_featured = request.form.get('is_featured') == 'on'

        # Set published_at if newly published
        if is_published and not was_published:
            news.published_at = datetime.utcnow()

        db.session.commit()

        flash('Nyheten har uppdaterats!', 'success')
        return redirect(url_for('admin.news_list'))

    return render_template('admin/news/form.html', news=news)


@admin_bp.route('/news/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def news_delete(id):
    """Delete news article"""
    news = News.query.get_or_404(id)
    db.session.delete(news)
    db.session.commit()

    flash('Nyheten har tagits bort!', 'success')
    return redirect(url_for('admin.news_list'))


# ============ MEMBERS ============

@admin_bp.route('/members')
@login_required
@admin_required
def members_list():
    """List all members"""
    members = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/members/list.html', members=members, UserState=UserState, UserRole=UserRole)


@admin_bp.route('/members/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def members_edit(id):
    """Edit member"""
    member = User.query.get_or_404(id)

    if request.method == 'POST':
        # Handle avatar upload
        if 'avatar' in request.files and request.files['avatar'].filename:
            avatar_filename = save_uploaded_file(request.files['avatar'])
            if avatar_filename:
                member.avatar_url = f"/static/uploads/{avatar_filename}"

        member.display_name = request.form.get('display_name')
        member.email = request.form.get('email')
        member.bio = request.form.get('bio')

        # Only admins can change roles
        if current_user.is_admin_role():
            new_role = request.form.get('role')
            if new_role in [r.value for r in UserRole]:
                member.role = new_role
                # Also update is_admin for backwards compatibility
                member.is_admin = new_role in [UserRole.ADMIN.value, UserRole.MODERATOR.value]

        # Update password if provided
        new_password = request.form.get('new_password')
        if new_password:
            member.set_password(new_password)

        db.session.commit()

        flash('Medlemmen har uppdaterats!', 'success')
        return redirect(url_for('admin.members_list'))

    return render_template('admin/members/form.html', member=member, UserRole=UserRole)


@admin_bp.route('/members/<int:id>/suspend', methods=['POST'])
@login_required
@admin_required
def members_suspend(id):
    """Suspend a member"""
    if id == current_user.id:
        flash('Du kan inte stanga av dig sjalv!', 'error')
        return redirect(url_for('admin.members_list'))

    member = User.query.get_or_404(id)

    # Cannot suspend admins (only other admins can)
    if member.is_admin_role() and not current_user.is_admin_role():
        flash('Du kan inte stanga av en administrator.', 'error')
        return redirect(url_for('admin.members_list'))

    reason = request.form.get('reason', '').strip()
    member.state = UserState.SUSPENDED.value
    member.suspended_reason = reason if reason else None
    db.session.commit()

    flash(f'{member.display_name or member.username} har stangts av.', 'info')
    return redirect(url_for('admin.members_list'))


@admin_bp.route('/members/<int:id>/reactivate', methods=['POST'])
@login_required
@admin_required
def members_reactivate(id):
    """Reactivate a suspended member"""
    member = User.query.get_or_404(id)

    if member.state not in [UserState.SUSPENDED.value, UserState.REJECTED.value]:
        flash('Denna anvandare ar inte avstangd eller avvisad.', 'warning')
        return redirect(url_for('admin.members_list'))

    member.state = UserState.ACTIVE.value
    member.suspended_reason = None
    member.rejection_reason = None
    db.session.commit()

    flash(f'{member.display_name or member.username} har ateraktiverats!', 'success')
    return redirect(url_for('admin.members_list'))


@admin_bp.route('/members/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def members_delete(id):
    """Delete member"""
    if id == current_user.id:
        flash('Du kan inte ta bort dig sjalv!', 'error')
        return redirect(url_for('admin.members_list'))

    member = User.query.get_or_404(id)

    # Cannot delete admins (only other admins can)
    if member.is_admin_role() and not current_user.is_admin_role():
        flash('Du kan inte ta bort en administrator.', 'error')
        return redirect(url_for('admin.members_list'))

    db.session.delete(member)
    db.session.commit()

    flash('Medlemmen har tagits bort!', 'success')
    return redirect(url_for('admin.members_list'))
