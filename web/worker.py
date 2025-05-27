import logging
from dotenv import load_dotenv
from redis import Redis
from rq import Worker
from app import create_app

# Load environment variables from .env
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('worker')

# Create Flask app context
flask_app = create_app()
flask_app.app_context().push()

# Connect to Redis
redis_conn = Redis.from_url(flask_app.config['REDIS_URL'])

def handle_exception(job, *exc_info):
    logger.exception('Job %s failed', job.id)
    return False

# Start the worker
worker = Worker(['deployments'], connection=redis_conn, exception_handlers=[handle_exception])
logger.info('Worker starting')
worker.work()