from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import SubscriptionPlan, Team, TeamMember, Project, User, TeamSubscription
from config import get_settings


class PricingService:
    @staticmethod
    async def get_default_free_plan(db: AsyncSession) -> SubscriptionPlan:
        """Get or create default free plan"""
        result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == "free")
        )
        plan = result.scalar_one_or_none()
        
        if not plan:
            plan = SubscriptionPlan(
                name="free",
                display_name="Free",
                max_teams=1,
                max_team_members=1,
                max_projects=2,
                custom_domains_allowed=False,
                default_cpu_cores=0.3,
                default_memory_mb=100,
                max_cpu_cores=0.3,
                max_memory_mb=100,
                price_per_month=None
            )
            db.add(plan)
            await db.commit()
        
        return plan

    @staticmethod
    async def get_pay_as_you_go_plan(db: AsyncSession) -> SubscriptionPlan:
        """Get or create pay as you go plan"""
        result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == "pay_as_you_go")
        )
        plan = result.scalar_one_or_none()
        
        if not plan:
            plan = SubscriptionPlan(
                name="pay_as_you_go",
                display_name="Pay as You Go",
                max_teams=-1,  # Unlimited
                max_team_members=-1,  # Unlimited
                max_projects=-1,  # Unlimited
                custom_domains_allowed=True,
                default_cpu_cores=0.5,
                default_memory_mb=512,
                max_cpu_cores=4.0,
                max_memory_mb=6144,  # 6GB max théorique
                price_per_month=0.0
            )
            db.add(plan)
            await db.commit()
        
        return plan

    @staticmethod
    async def validate_team_creation(user: User, db: AsyncSession) -> tuple[bool, str]:
        """Validate if user can create a new team"""
        # Count user's active teams
        result = await db.execute(
            select(Team)
            .join(TeamMember, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id == user.id, Team.status == "active")
        )
        user_teams = result.scalars().all()
        
        # Get user's default team plan to check team limits
        if user.default_team:
            default_team = await db.get(Team, user.default_team.id)
            if default_team:
                plan = default_team.current_plan
                if plan and plan.max_teams != -1 and len(user_teams) >= plan.max_teams:
                    return False, f"Team limit reached. You can have up to {plan.max_teams} team(s) on the {plan.display_name} plan."
        else:
            # If user has no default team, they're on free plan (max 1 team)
            if len(user_teams) >= 1:
                return False, "Team limit reached. You can have up to 1 team(s) on the Free plan."
        
        return True, ""

    @staticmethod
    async def validate_member_addition(team: Team, db: AsyncSession) -> tuple[bool, str]:
        """Validate if team can add a new member"""
        if not team.can_add_member():
            plan = team.current_plan
            if plan and plan.max_team_members == -1:
                return True, ""
            if plan:
                return False, f"Member limit reached. You can have up to {plan.max_team_members} member(s) on the {plan.display_name} plan."
            return False, "Member limit reached. No active plan found."
        
        return True, ""

    @staticmethod
    async def validate_project_creation(team: Team, db: AsyncSession) -> tuple[bool, str]:
        """Validate if team can create a new project"""
        if not team.can_add_project():
            plan = team.current_plan
            if plan and plan.max_projects == -1:
                return True, ""
            if plan:
                return False, f"Project limit reached. You can have up to {plan.max_projects} project(s) on the {plan.display_name} plan."
            return False, "Project limit reached. No active plan found."
        
        return True, ""

    @staticmethod
    async def validate_custom_domain(team: Team, db: AsyncSession) -> tuple[bool, str]:
        """Validate if team can add custom domains"""
        if not team.can_add_custom_domain():
            plan = team.current_plan
            if plan:
                return False, f"Custom domains are not available on the {plan.display_name} plan. Upgrade to add custom domains."
            return False, "Custom domains are not available. No active plan found."
        
        return True, ""

    @staticmethod
    async def assign_free_plan_to_team(team: Team, db: AsyncSession) -> TeamSubscription:
        """Assign free plan to a team"""
        free_plan = await PricingService.get_default_free_plan(db)
        
        # Check if team already has a subscription
        existing_subscription = await db.execute(
            select(TeamSubscription).where(TeamSubscription.team_id == team.id)
        )
        subscription = existing_subscription.scalar_one_or_none()
        
        if subscription:
            subscription.plan_id = free_plan.id
            subscription.status = "active"
        else:
            subscription = TeamSubscription(
                team_id=team.id,
                plan_id=free_plan.id,
                status="active"
            )
            db.add(subscription)
        
        await db.commit()
        return subscription

    @staticmethod
    async def assign_pay_as_you_go_plan_to_team(team: Team, db: AsyncSession) -> TeamSubscription:
        """Assign pay as you go plan to a team"""
        pay_as_you_go_plan = await PricingService.get_pay_as_you_go_plan(db)
        
        # Check if team already has a subscription
        existing_subscription = await db.execute(
            select(TeamSubscription).where(TeamSubscription.team_id == team.id)
        )
        subscription = existing_subscription.scalar_one_or_none()
        
        if subscription:
            subscription.plan_id = pay_as_you_go_plan.id
            subscription.status = "active"
        else:
            subscription = TeamSubscription(
                team_id=team.id,
                plan_id=pay_as_you_go_plan.id,
                status="active"
            )
            db.add(subscription)
        
        await db.commit()
        return subscription

    @staticmethod
    async def get_team_usage_stats(team: Team, db: AsyncSession) -> dict:
        """Get detailed usage statistics for a team"""
        # Count active members
        members_result = await db.execute(
            select(func.count(TeamMember.id))
            .where(
                TeamMember.team_id == team.id,
                TeamMember.user_id.in_(
                    select(User.id).where(User.status == "active")
                )
            )
        )
        active_members = members_result.scalar() or 0
        
        # Count active projects
        projects_result = await db.execute(
            select(func.count(Project.id))
            .where(
                Project.team_id == team.id,
                Project.status == "active"
            )
        )
        active_projects = projects_result.scalar() or 0
        
        # Count custom domains
        domains_result = await db.execute(
            select(func.count(Project.id))
            .where(
                Project.team_id == team.id,
                Project.status == "active"
            )
        )
        # Note: We would need to join with Domain table to get actual domain count
        # For now, we'll use the team's method
        custom_domains_count = len([d for d in team.domains if d.status == "active"]) if hasattr(team, 'domains') else 0
        
        plan = team.current_plan
        
        if not plan:
            # Return default free plan stats if no plan is found
            return {
                "plan": {
                    "name": "free",
                    "display_name": "Free",
                    "price_per_month": None
                },
                "members": {
                    "current": active_members,
                    "limit": 1,  # Free plan default
                    "unlimited": False,
                    "percentage": (active_members / 1) * 100
                },
                "projects": {
                    "current": active_projects,
                    "limit": 2,  # Free plan default
                    "unlimited": False,
                    "percentage": (active_projects / 2) * 100
                },
                "custom_domains": {
                    "allowed": False,  # Free plan default
                    "current": custom_domains_count
                }
            }
        return usage_stats


class ResourceValidationService:
    @staticmethod
    async def get_available_memory(team: Team, db: AsyncSession) -> int:
        """Calcul dynamique basé sur VPS de 8GB et projets actifs"""
        total_vps_memory = 8192  # 8GB en MB
        system_reserve = 2048  # 2GB pour système
        available = total_vps_memory - system_reserve
        
        # Calculer mémoire utilisée par autres projets de la team
        result = await db.execute(
            select(func.sum(Project.allocated_memory_mb))
            .where(Project.team_id == team.id, Project.status == "active")
        )
        used_memory = result.scalar() or 0
        return max(0, available - used_memory)
    
    @staticmethod
    async def validate_resources(
        team: Team, 
        cpu: float | None, 
        memory: int | None,
        db: AsyncSession,
        current_project_id: str | None = None
    ) -> tuple[bool, str]:
        """Valider allocation selon plan et disponibilité"""
        plan = team.current_plan
        if not plan:
            return False, "No active plan found"
        
        # Validation CPU
        if cpu is not None:
            if cpu > plan.max_cpu_cores:
                return False, f"CPU limit: {plan.max_cpu_cores} cores on {plan.display_name}"
        
        # Validation Mémoire avec calcul dynamique pour Pay as You Go
        if memory is not None:
            if plan.name == "pay_as_you_go":
                available = await ResourceValidationService.get_available_memory(team, db)
                if memory > available:
                    return False, f"Insufficient memory. {available}MB available"
            else:
                if memory > plan.max_memory_mb:
                    return False, f"Memory limit: {plan.max_memory_mb}MB on {plan.display_name}"
        
        return True, ""
