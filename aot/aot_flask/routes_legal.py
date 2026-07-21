# coding=utf-8
"""Public legal pages (Privacy Policy / Terms of Service).

Reachable without login: required for Google OAuth verification, which
crawls these URLs anonymously.
"""
from flask import Blueprint, render_template

blueprint = Blueprint('routes_legal',
                       __name__,
                       static_folder='../static',
                       template_folder='../templates')


@blueprint.route('/privacy-policy')
def page_privacy_policy():
    """Public privacy policy page (no login required)."""
    return render_template('pages/privacy_policy.html', active_page='privacy_policy')


@blueprint.route('/terms-of-service')
def page_terms_of_service():
    """Public terms of service page (no login required)."""
    return render_template('pages/terms_of_service.html', active_page='terms_of_service')
