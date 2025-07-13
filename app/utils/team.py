from sqlalchemy import select

from models import Team


async def get_latest_teams(db, current_user, current_team=None, limit=5):
    from models import TeamMember

    query = (
        select(Team)
        .join(TeamMember, Team.id == TeamMember.team_id)
        .where(Team.status != "deleted", TeamMember.user_id == current_user.id)
        .order_by(Team.updated_at.desc())
        .limit(limit)
    )

    if current_team:
        query = query.where(Team.id != current_team.id)

    result = await db.execute(query)

    return result.scalars().all()
