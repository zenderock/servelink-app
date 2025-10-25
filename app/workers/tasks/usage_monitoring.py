import logging
import docker
from db import AsyncSessionLocal
from services.usage_tracking import UsageTrackingService
from services.additional_resources import AdditionalResourceService
from models import Project
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def update_project_storage(ctx):
    """Tâche périodique pour mettre à jour l'espace disque utilisé par les projets"""
    logger.info("Updating project storage usage...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Récupérer tous les projets actifs
            result = await db.execute(
                select(Project).where(Project.status == "active")
            )
            projects = result.scalars().all()
            
            # Connecter à Docker
            try:
                docker_client = docker.from_env()
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                return
            
            updated_count = 0
            for project in projects:
                try:
                    # Calculer l'espace disque utilisé par le projet
                    storage_bytes = await _calculate_project_storage(project, docker_client)
                    
                    # Mettre à jour dans la base de données
                    await UsageTrackingService.update_storage(
                        project_id=project.id,
                        storage_bytes=storage_bytes,
                        db=db
                    )
                    
                    updated_count += 1
                    logger.debug(f"Updated storage for project {project.id}: {storage_bytes} bytes")
                
                except Exception as e:
                    logger.error(f"Error updating storage for project {project.id}: {e}")
                    continue
            
            logger.info(f"Storage updated for {updated_count}/{len(projects)} projects")
            
        except Exception as e:
            logger.error(f"Error in storage monitoring: {e}", exc_info=True)
            raise
        finally:
            if 'docker_client' in locals():
                docker_client.close()


async def _calculate_project_storage(project: Project, docker_client) -> int:
    """
    Calcule l'espace disque utilisé par un projet
    
    Args:
        project: Le projet
        docker_client: Client Docker
        
    Returns:
        Espace disque en octets
    """
    total_size = 0
    
    try:
        # Récupérer les volumes Docker associés au projet
        # Les volumes sont nommés avec le pattern: servelink_{project.id}_{volume_name}
        volumes = docker_client.volumes.list(
            filters={'name': f'servelink_{project.id}_'}
        )
        
        for volume in volumes:
            try:
                # Inspecter le volume pour obtenir le point de montage
                volume_info = docker_client.api.inspect_volume(volume.name)
                mountpoint = volume_info.get('Mountpoint')
                
                if mountpoint:
                    # Exécuter une commande pour calculer la taille
                    # On utilise un container temporaire pour lire le volume
                    container = docker_client.containers.run(
                        'alpine:latest',
                        command=f'du -sb {mountpoint}',
                        volumes={mountpoint: {'bind': mountpoint, 'mode': 'ro'}},
                        remove=True,
                        detach=False
                    )
                    
                    # Parser la sortie (format: "size path")
                    output = container.decode('utf-8').strip()
                    if output:
                        size = int(output.split()[0])
                        total_size += size
                        
            except Exception as e:
                logger.warning(f"Error calculating size for volume {volume.name}: {e}")
                continue
        
        # Ajouter la taille des images Docker du projet si applicable
        try:
            images = docker_client.images.list(
                filters={'label': f'project_id={project.id}'}
            )
            for image in images:
                total_size += image.attrs.get('Size', 0)
        except Exception as e:
            logger.warning(f"Error calculating image size for project {project.id}: {e}")
        
    except Exception as e:
        logger.error(f"Error calculating storage for project {project.id}: {e}")
    
    return total_size


async def check_usage_limits_task(ctx):
    """Tâche périodique pour vérifier les limites d'utilisation et envoyer des alertes"""
    logger.info("Checking usage limits for all projects...")
    
    async with AsyncSessionLocal() as db:
        try:
            from models import Team
            
            # Récupérer toutes les équipes actives
            result = await db.execute(
                select(Team).where(Team.status == "active")
            )
            teams = result.scalars().all()
            
            warnings_sent = 0
            for team in teams:
                try:
                    # Récupérer le résumé d'utilisation
                    summary = await UsageTrackingService.get_usage_summary(
                        team_id=team.id,
                        db=db
                    )
                    
                    if not summary:
                        continue
                    
                    # Vérifier les seuils d'alerte (80% et 95%)
                    traffic_pct = summary['limits']['traffic']['percentage']
                    storage_pct = summary['limits']['storage']['percentage']
                    
                    if traffic_pct >= 95 or storage_pct >= 95:
                        await _send_usage_alert(team, summary, 'critical', db)
                        warnings_sent += 1
                    elif traffic_pct >= 80 or storage_pct >= 80:
                        await _send_usage_alert(team, summary, 'warning', db)
                        warnings_sent += 1
                
                except Exception as e:
                    logger.error(f"Error checking limits for team {team.id}: {e}")
                    continue
            
            logger.info(f"Sent {warnings_sent} usage alerts")
            
        except Exception as e:
            logger.error(f"Error in usage limits check: {e}", exc_info=True)
            raise


async def _send_usage_alert(team, summary: dict, alert_level: str, db):
    """
    Envoie une alerte d'utilisation à l'équipe
    
    Args:
        team: L'équipe
        summary: Résumé d'utilisation
        alert_level: 'warning' (80%) ou 'critical' (95%)
        db: Session de base de données
    """
    try:
        from services.notification import DeploymentNotificationService
        from config import get_settings
        from models import User
        
        settings = get_settings()
        
        # Récupérer le propriétaire de l'équipe
        owner = await db.get(User, team.created_by_user_id)
        if not owner:
            logger.warning(f"No owner found for team {team.id}")
            return
        
        # Préparer les données pour l'email
        traffic_pct = summary['limits']['traffic']['percentage']
        storage_pct = summary['limits']['storage']['percentage']
        
        # Pour l'instant, on log seulement
        # TODO: Implémenter l'envoi d'email d'alerte
        logger.warning(
            f"Usage alert ({alert_level}) for team {team.name}: "
            f"Traffic {traffic_pct:.1f}%, Storage {storage_pct:.1f}%"
        )
        
    except Exception as e:
        logger.error(f"Error sending usage alert: {e}")


async def expire_additional_resources(ctx):
    """Tâche périodique pour expirer les ressources additionnelles"""
    logger.info("Expiring additional resources...")
    
    async with AsyncSessionLocal() as db:
        try:
            count = await AdditionalResourceService.expire_resources(db)
            logger.info(f"Expired {count} additional resources")
        except Exception as e:
            logger.error(f"Error expiring resources: {e}", exc_info=True)
            raise
