from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, User, Story, Photo, Activity, EventParticipant, UserState
from datetime import datetime

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/<username>')
def view(username):
    user = User.query.filter_by(username=username).first_or_404()

    # Get user's stories
    stories = Story.query.filter_by(
        author_id=user.id,
        is_published=True
    ).order_by(Story.published_at.desc()).limit(5).all()

    # Get user's photos
    photos = Photo.query.filter_by(
        uploader_id=user.id
    ).order_by(Photo.uploaded_at.desc()).limit(8).all()

    # Get user's activities
    activities = Activity.query.filter_by(
        user_id=user.id
    ).order_by(Activity.created_at.desc()).limit(10).all()

    # Get event count
    event_count = EventParticipant.query.filter_by(user_id=user.id).count()

    return render_template('profile/view.html',
                           user=user,
                           stories=stories,
                           photos=photos,
                           activities=activities,
                           event_count=event_count)


@profile_bp.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        bio = request.form.get('bio', '').strip()
        leaderboard_opt_in = request.form.get('leaderboard_opt_in') == 'on'

        if display_name:
            current_user.display_name = display_name
        current_user.bio = bio
        current_user.leaderboard_opt_in = leaderboard_opt_in

        db.session.commit()
        flash('Profil uppdaterad!', 'success')
        return redirect(url_for('profile.view', username=current_user.username))

    return render_template('profile/edit.html')


@profile_bp.route('/members')
def members():
    # Only show active users on the members page
    users = User.query.filter_by(
        state=UserState.ACTIVE.value
    ).order_by(User.created_at).all()
    return render_template('profile/members.html', users=users)
