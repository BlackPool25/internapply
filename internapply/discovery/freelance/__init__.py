"""Freelance lite discovery — Freelancer RSS + Internshala freelance + Upwork webhook."""
from backend.app.discovery.freelance.freelancer_rss import FreelancerRSSDiscovery
from backend.app.discovery.freelance.internshala_freelance import InternshalaFreelanceDiscovery
from backend.app.discovery.freelance.upwork_webhook import handle_upwork_webhook

__all__ = ["FreelancerRSSDiscovery", "InternshalaFreelanceDiscovery", "handle_upwork_webhook"]
