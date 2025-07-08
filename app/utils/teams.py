from sqlalchemy import select

from models import Team


async def get_latest_teams(db, current_team=None, limit=5):
    if current_team:
        result = await db.execute(
            select(Team)
            .where(
                Team.status != 'deleted',
                Team.id != current_team.id
            )
            .order_by(Team.updated_at.desc())
            .limit(limit)
        )
    else:
        result = await db.execute(
            select(Team)
            .where(Team.status != 'deleted')
            .order_by(Team.updated_at.desc())
            .limit(limit)
        )
    
    return result.scalars().all()