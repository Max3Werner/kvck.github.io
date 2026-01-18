from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, UserState, UserRole, EmailVerificationToken
from services.email import send_verification_email, send_pending_approval_to_admins

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if user and user.check_password(password):
            # Check user state before allowing login
            if user.state == UserState.PENDING_EMAIL_VERIFICATION.value:
                # Store user id in session for resend functionality
                session['pending_verification_user_id'] = user.id
                flash('Du maste verifiera din e-postadress forst.', 'warning')
                return redirect(url_for('auth.verification_sent'))

            elif user.state == UserState.PENDING_APPROVAL.value:
                flash('Ditt konto vantar pa godkannande fran en administratör.', 'info')
                return redirect(url_for('auth.pending_approval'))

            elif user.state == UserState.REJECTED.value:
                flash('Ditt konto har inte godkants. Kontakta oss for mer information.', 'error')
                return redirect(url_for('auth.login'))

            elif user.state == UserState.SUSPENDED.value:
                flash('Ditt konto har stagts av. Kontakta oss for mer information.', 'error')
                return redirect(url_for('auth.login'))

            elif user.state == UserState.ACTIVE.value:
                login_user(user, remember=remember)
                next_page = request.args.get('next')
                flash('Valkommen tillbaka!', 'success')
                return redirect(next_page or url_for('main.index'))

            else:
                flash('Det gick inte att logga in. Kontakta oss for hjalp.', 'error')
        else:
            flash('Fel anvandarnamn eller losenord.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        errors = []

        if len(username) < 3:
            errors.append('Anvandarnamn maste vara minst 3 tecken.')

        if not email or '@' not in email:
            errors.append('Ange en giltig e-postadress.')

        if len(password) < 6:
            errors.append('Losenord maste vara minst 6 tecken.')

        if password != confirm_password:
            errors.append('Losenorden matchar inte.')

        if User.query.filter_by(username=username).first():
            errors.append('Anvandarnamnet ar redan taget.')

        if User.query.filter_by(email=email).first():
            errors.append('E-postadressen ar redan registrerad.')

        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            # Create user with PENDING_EMAIL_VERIFICATION state
            user = User(
                username=username,
                email=email,
                display_name=display_name or username,
                state=UserState.PENDING_EMAIL_VERIFICATION.value,
                role=UserRole.USER.value,
                leaderboard_opt_in=False
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()  # Get user.id

            # Create verification token
            token = EmailVerificationToken.create_for_user(user)
            db.session.add(token)
            db.session.commit()

            # Send verification email
          #  send_verification_email(user, token)

            # Store user id in session for resend functionality
            session['pending_verification_user_id'] = user.id

            # NO auto-login - redirect to verification sent page
            flash('Konto skapat! Kolla din e-post for att verifiera kontot.', 'success')
            return redirect(url_for('auth.verification_sent'))

    return render_template('auth/signup.html')


@auth_bp.route('/verification-sent')
def verification_sent():
    """Show 'check your email' page."""
    return render_template('auth/verification_sent.html')


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    """Verify email address using token."""
    verification = EmailVerificationToken.query.filter_by(token=token).first()

    if not verification:
        flash('Ogiltig verifieringslanke.', 'error')
        return redirect(url_for('auth.login'))

    if not verification.is_valid():
        flash('Verifieringslanken har gatt ut. Begär en ny.', 'error')
        session['pending_verification_user_id'] = verification.user_id
        return redirect(url_for('auth.verification_sent'))

    user = verification.user

    # Mark token as used
    verification.mark_used()

    # Update user state to PENDING_APPROVAL
    from datetime import datetime
    user.state = UserState.PENDING_APPROVAL.value
    user.email_verified_at = datetime.utcnow()
    db.session.commit()

    # Notify admins about pending approval
   # send_pending_approval_to_admins(user)

    flash('E-postadress verifierad! Ditt konto vantar nu pa godkannande.', 'success')
    return redirect(url_for('auth.pending_approval'))


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email."""
    user_id = session.get('pending_verification_user_id')

    if not user_id:
        # Try to get from form (email address)
        email = request.form.get('email', '').strip().lower()
        if email:
            user = User.query.filter_by(email=email).first()
            if user and user.state == UserState.PENDING_EMAIL_VERIFICATION.value:
                user_id = user.id

    if not user_id:
        flash('Kunde inte hitta kontot. Forsok registrera dig igen.', 'error')
        return redirect(url_for('auth.signup'))

    user = User.query.get(user_id)
    if not user:
        flash('Kunde inte hitta kontot.', 'error')
        return redirect(url_for('auth.signup'))

    if user.state != UserState.PENDING_EMAIL_VERIFICATION.value:
        flash('Kontot ar redan verifierat.', 'info')
        return redirect(url_for('auth.login'))

    # Invalidate old tokens by not using them (they'll expire)
    # Create new verification token
    token = EmailVerificationToken.create_for_user(user)
    db.session.add(token)
    db.session.commit()

    # Send verification email
  #  send_verification_email(user, token)

    flash('Ett nytt verifieringsmail har skickats!', 'success')
    return redirect(url_for('auth.verification_sent'))


@auth_bp.route('/pending-approval')
def pending_approval():
    """Show pending approval page."""
    return render_template('auth/pending_approval.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Du har loggat ut.', 'info')
    return redirect(url_for('main.index'))
