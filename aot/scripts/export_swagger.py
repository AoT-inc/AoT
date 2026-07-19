import json
import os
import sys
import mock

# Mock problematic dependencies to avoid import errors
mock_modules = [
    'influxdb', 'influxdb.exceptions', 'pandas', 'pyarrow', 'numpy', 
    'numpy.core', 'matplotlib', 'matplotlib.pyplot', 'seaborn',
    'scipy', 'scipy.stats', 'cv2'
]
for module in mock_modules:
    sys.modules[module] = mock.MagicMock()

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from flask import Flask
from aot.aot_flask.api import api

def export_swagger():
    """Export the Flask-RESTX API spec as JSON to stdout.

    Creates a minimal Flask app context with mocked dependencies,
    registers all API resource modules, and prints the OpenAPI spec.

    @phase doc-generation
    @dependency flask, aot.aot_flask.api
    """
    # We need a minimal app context for Flask-RESTX
    app = Flask(__name__)
    app.config['SERVER_NAME'] = 'localhost'
    app.config['APPLICATION_ROOT'] = '/'
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    app.config['RESTX_MASK_SWAGGER'] = False
    app.config['RESTX_INCLUDE_ALL_MODELS'] = True
    app.config['RESTX_VALIDATE'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://' # Avoid DB issues
    
    # Mock base_path to avoid url_for issues
    from aot.aot_flask.api import api
    with mock.patch.object(api.__class__, 'base_path', new_callable=mock.PropertyMock) as mock_base_path:
        mock_base_path.return_value = '/api'
        
        # Manually import all API modules to register resources
        import aot.aot_flask.api.camera
        import aot.aot_flask.api.choices
        import aot.aot_flask.api.controller
        import aot.aot_flask.api.daemon
        import aot.aot_flask.api.export_import
        import aot.aot_flask.api.function
        import aot.aot_flask.api.input
        import aot.aot_flask.api.measurement
        import aot.aot_flask.api.note
        import aot.aot_flask.api.output
        import aot.aot_flask.api.pid
        import aot.aot_flask.api.settings
        import aot.aot_flask.api.geo
        import aot.aot_flask.api.ai
        import aot.aot_flask.api.locale

        with app.app_context():
            # Flask-RESTX provides the spec via api.__schema__
            spec = api.__schema__
            print(json.dumps(spec, indent=2))

if __name__ == "__main__":
    export_swagger()
