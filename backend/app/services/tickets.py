from sqlalchemy.orm import Session
from datetime import datetime
from backend.app.db.models import Ticket, User, Deployment, Team

def create_ticket(db: Session, title: str, description: str, ticket_type: str,
                  severity: str, filed_by: int, deployment_id: int = None,
                  workspace_id: int = None, team_id: int = None,
                  evidence: str = "") -> Ticket:
    ticket = Ticket(
        title=title,
        description=description,
        ticket_type=ticket_type,
        severity=severity,
        filed_by=filed_by,
        deployment_id=deployment_id,
        workspace_id=workspace_id,
        team_id=team_id,
        evidence=evidence
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket

def get_all_tickets(db: Session, status: str = None) -> list:
    query = db.query(Ticket)
    if status:
        query = query.filter(Ticket.status == status)
    tickets = query.order_by(Ticket.filed_at.desc()).all()
    return _enrich_tickets(db, tickets)

def get_user_tickets(db: Session, user_id: int) -> list:
    tickets = db.query(Ticket).filter(
        Ticket.filed_by == user_id
    ).order_by(Ticket.filed_at.desc()).all()
    return _enrich_tickets(db, tickets)

def get_team_tickets(db: Session, team_id: int) -> list:
    tickets = db.query(Ticket).filter(
        Ticket.team_id == team_id
    ).order_by(Ticket.filed_at.desc()).all()
    return _enrich_tickets(db, tickets)

def update_ticket_status(db: Session, ticket_id: int, status: str,
                          resolved_by: int = None, resolution_note: str = "") -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        return None
    ticket.status = status
    if status in ["resolved", "closed"]:
        ticket.resolved_by = resolved_by
        ticket.resolved_at = datetime.utcnow()
        ticket.resolution_note = resolution_note
    db.commit()
    db.refresh(ticket)
    return ticket

def _enrich_tickets(db: Session, tickets: list) -> list:
    result = []
    for t in tickets:
        user = db.query(User).filter(User.id == t.filed_by).first()
        dep = db.query(Deployment).filter(Deployment.id == t.deployment_id).first() if t.deployment_id else None
        team = db.query(Team).filter(Team.id == t.team_id).first() if t.team_id else None
        resolver = db.query(User).filter(User.id == t.resolved_by).first() if t.resolved_by else None
        result.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "ticket_type": t.ticket_type,
            "severity": t.severity,
            "status": t.status,
            "deployment_id": t.deployment_id,
            "deployment_name": dep.name if dep else None,
            "model_name": dep.model_name if dep else None,
            "team_id": t.team_id,
            "team_name": team.name if team else None,
            "filed_by": t.filed_by,
            "filed_by_name": user.name if user else "unknown",
            "filed_by_username": user.username if user else "unknown",
            "filed_at": t.filed_at,
            "resolved_by": t.resolved_by,
            "resolved_by_name": resolver.name if resolver else None,
            "resolved_at": t.resolved_at,
            "resolution_note": t.resolution_note,
            "evidence": t.evidence
        })
    return result
