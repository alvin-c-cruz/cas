"""
CAS (Computerized Accounting System) - Flask Application Entry Point

CAS is a general-purpose, industry-agnostic accounting system for
Philippine SMEs (BIR-compliant), used by multiple companies across
different industries. Sample/demo data may use industry-flavored names
(e.g., construction suppliers), but these are illustrative only.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app import create_app

# Create app with environment-based configuration
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(config_name=env)

if __name__ == '__main__':
    # Get debug mode from config (already set from .env)
    debug_mode = app.config.get('DEBUG', False)
    app.run(debug=debug_mode, port=5000)
