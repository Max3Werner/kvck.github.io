"""Email service for sending verification, approval, and notification emails."""

from flask import current_app, render_template, url_for
from flask_mail import Message


def get_mail():
    """Get the Flask-Mail instance."""
    return current_app.extensions.get('mail')


def send_email(subject, recipients, text_body, html_body):
    """Send an email with both text and HTML versions."""
    mail = get_mail()
    if not mail:
        current_app.logger.warning('Email not configured - skipping send')
        return False

    msg = Message(
        subject=subject,
        recipients=recipients if isinstance(recipients, list) else [recipients],
        body=text_body,
        html=html_body,
        sender=current_app.config.get('MAIL_DEFAULT_SENDER')
    )

    try:
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f'Failed to send email: {e}')
        return False


def send_verification_email(user, token):
    """Send email verification link to user."""
    site_url = current_app.config.get('SITE_URL', 'http://localhost:5001')
    verify_url = f"{site_url}{url_for('auth.verify_email', token=token.token)}"

    subject = 'Verifiera din e-postadress - Klubbans Vanner'

    text_body = render_template(
        'email/verify_email.txt',
        user=user,
        verify_url=verify_url
    )

    html_body = render_template(
        'email/verify_email.html',
        user=user,
        verify_url=verify_url
    )

    return send_email(subject, user.email, text_body, html_body)


def send_approval_notification(user):
    """Send notification that account has been approved."""
    site_url = current_app.config.get('SITE_URL', 'http://localhost:5001')
    login_url = f"{site_url}{url_for('auth.login')}"

    subject = 'Ditt konto har godkants! - Klubbans Vanner'

    text_body = render_template(
        'email/account_approved.txt',
        user=user,
        login_url=login_url
    )

    html_body = render_template(
        'email/account_approved.html',
        user=user,
        login_url=login_url
    )

    return send_email(subject, user.email, text_body, html_body)


def send_rejection_notification(user, reason=None):
    """Send notification that account has been rejected."""
    subject = 'Angaende ditt konto - Klubbans Vanner'

    text_body = render_template(
        'email/account_rejected.txt',
        user=user,
        reason=reason
    )

    html_body = render_template(
        'email/account_rejected.html',
        user=user,
        reason=reason
    )

    return send_email(subject, user.email, text_body, html_body)


def send_pending_approval_to_admins(user):
    """Send notification to admins about new user pending approval."""
    from models import User, UserRole

    # Get all admin/moderator users
    admins = User.query.filter(
        User.role.in_([UserRole.ADMIN.value, UserRole.MODERATOR.value])
    ).all()

    if not admins:
        current_app.logger.warning('No admins found to notify about pending approval')
        return False

    site_url = current_app.config.get('SITE_URL', 'http://localhost:5001')
    approvals_url = f"{site_url}{url_for('admin.approvals_list')}"

    subject = f'Ny medlem vantar pa godkannande: {user.display_name or user.username}'

    for admin in admins:
        text_body = render_template(
            'email/pending_approval.txt',
            admin=admin,
            user=user,
            approvals_url=approvals_url
        )

        html_body = render_template(
            'email/pending_approval.html',
            admin=admin,
            user=user,
            approvals_url=approvals_url
        )

        send_email(subject, admin.email, text_body, html_body)

    return True
