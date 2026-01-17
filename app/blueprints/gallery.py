import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, Photo, Activity

gallery_bp = Blueprint('gallery', __name__)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


@gallery_bp.route('/')
def index():
    photos = Photo.query.order_by(Photo.uploaded_at.desc()).all()
    return render_template('gallery/index.html', photos=photos)


@gallery_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'photos' not in request.files:
            flash('Ingen fil vald.', 'error')
            return redirect(request.url)

        files = request.files.getlist('photos')
        caption = request.form.get('caption', '').strip()
        location = request.form.get('location', '').strip()

        uploaded_count = 0

        for file in files:
            if file and file.filename and allowed_file(file.filename):
                # Generate unique filename
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                original_filename = secure_filename(file.filename)

                # Save file
                upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                file.save(upload_path)

                # Create database entry
                photo = Photo(
                    filename=filename,
                    original_filename=original_filename,
                    caption=caption,
                    location=location,
                    uploader_id=current_user.id
                )
                db.session.add(photo)
                uploaded_count += 1

        if uploaded_count > 0:
            db.session.commit()

            # Create activity
            activity = Activity(
                activity_type='uploaded_photo',
                message=f'{current_user.display_name} laddade upp {uploaded_count} {"bild" if uploaded_count == 1 else "bilder"}',
                user_id=current_user.id
            )
            db.session.add(activity)
            db.session.commit()

            flash(f'{uploaded_count} {"bild" if uploaded_count == 1 else "bilder"} uppladdade!', 'success')
            return redirect(url_for('gallery.index'))
        else:
            flash('Inga giltiga bilder att ladda upp.', 'error')

    return render_template('gallery/upload.html')


@gallery_bp.route('/<int:photo_id>')
def detail(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    return render_template('gallery/detail.html', photo=photo)


@gallery_bp.route('/<int:photo_id>/delete', methods=['POST'])
@login_required
def delete(photo_id):
    photo = Photo.query.get_or_404(photo_id)

    if photo.uploader_id != current_user.id and not current_user.is_admin:
        flash('Du har inte behörighet att ta bort denna bild.', 'error')
        return redirect(url_for('gallery.index'))

    # Delete file
    try:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass

    db.session.delete(photo)
    db.session.commit()

    flash('Bild borttagen.', 'info')
    return redirect(url_for('gallery.index'))
