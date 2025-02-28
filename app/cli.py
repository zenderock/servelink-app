import click
from app.services.nginx import sync_aliases

def register_commands(app):
    @app.cli.command("sync-aliases")
    def sync_aliases_command():
        """Sync active NGINX aliases from the database."""
        click.echo("Starting to sync aliases with NGINX...")
        sync_aliases()
        click.echo("NGINX aliases have been synced.")