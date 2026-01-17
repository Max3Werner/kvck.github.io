from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Story, Comment, Activity
from datetime import datetime
import re

stories_bp = Blueprint('stories', __name__)


def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


@stories_bp.route('/')
def index():
    stories = Story.query.filter_by(
        is_published=True
    ).order_by(Story.published_at.desc()).all()

    return render_template('stories/index.html', stories=stories)


@stories_bp.route('/<slug>')
def detail(slug):
    story = Story.query.filter_by(slug=slug).first_or_404()
    comments = story.comments.order_by(Comment.created_at).all()

    return render_template('stories/detail.html',
                           story=story,
                           comments=comments)


@stories_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        excerpt = request.form.get('excerpt', '').strip()
        content = request.form.get('content', '').strip()
        location = request.form.get('location', '').strip()
        distance_km = request.form.get('distance_km', type=float)
        ride_date_str = request.form.get('ride_date', '')

        if not title or not content:
            flash('Titel och innehall kravs.', 'error')
        else:
            slug = slugify(title)
            # Make slug unique
            existing = Story.query.filter_by(slug=slug).first()
            if existing:
                slug = f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"

            ride_date = None
            if ride_date_str:
                try:
                    ride_date = datetime.strptime(ride_date_str, '%Y-%m-%d')
                except ValueError:
                    pass

            story = Story(
                title=title,
                slug=slug,
                excerpt=excerpt,
                content=content,
                location=location,
                distance_km=distance_km,
                ride_date=ride_date,
                author_id=current_user.id,
                is_published=True,
                published_at=datetime.utcnow()
            )
            db.session.add(story)
            db.session.commit()

            # Create activity
            activity = Activity(
                activity_type='posted_story',
                message=f'{current_user.display_name} delade en ny berattelse: {title}',
                user_id=current_user.id,
                story_id=story.id
            )
            db.session.add(activity)
            db.session.commit()

            flash('Berattelsen publicerad!', 'success')
            return redirect(url_for('stories.detail', slug=story.slug))

    return render_template('stories/create.html')


@stories_bp.route('/<slug>/comment', methods=['POST'])
@login_required
def add_comment(slug):
    story = Story.query.filter_by(slug=slug).first_or_404()
    content = request.form.get('content', '').strip()

    if content:
        comment = Comment(
            content=content,
            author_id=current_user.id,
            story_id=story.id
        )
        db.session.add(comment)

        # Create activity
        activity = Activity(
            activity_type='commented',
            message=f'{current_user.display_name} kommenterade pa {story.title}',
            user_id=current_user.id,
            story_id=story.id
        )
        db.session.add(activity)
        db.session.commit()

        flash('Kommentar tillagd!', 'success')

    return redirect(url_for('stories.detail', slug=slug))
