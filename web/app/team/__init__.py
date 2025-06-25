from flask import Blueprint

bp =  Blueprint("team", __name__)

from app.team import routes